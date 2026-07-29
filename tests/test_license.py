from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl


class RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: list(response) if isinstance(response, list) else [response] for path, response in routes.items()
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responses = self._routes.get(request.url.path)
        if not responses:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": f"Unexpected {request.url.path}"})
        response = responses.pop(0)
        response.request = request
        return response

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)


def _license(
    license_id: str,
    user_id: str,
    *,
    expires_at: str | None = "2026-12-31T00:00:00Z",
    last_login_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "licenseId": license_id,
        "userId": user_id,
        "tenantId": "tenant-1",
        "licenseType": "creator",
        "isActive": True,
        "expiresAt": expires_at,
        "createdBy": "admin-1",
        "createdAt": "2026-07-01T00:00:00Z",
        "updatedBy": "admin-2",
        "updatedAt": "2026-07-02T00:00:00Z",
        "meta": {"source": "test"},
    }
    if last_login_at is not None:
        payload["lastLoginAt"] = last_login_at
    return payload


def _limits(*, value: int) -> dict[str, object]:
    return {
        "current": {
            "type": "regular",
            "value": value,
            "startedAt": "2026-07-01T00:00:00Z",
            "activeLicensesCount": 2,
        },
        "next": None,
    }


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(recorder.handler),
    )


def test_assign_get_and_set_license_limits_use_typed_models() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/assignLicenses": httpx.Response(200, json=[_license("lic-1", "user-1")]),
            "/rpc/getLicensesLimit": httpx.Response(200, json=_limits(value=10)),
            "/rpc/setLicenseLimit": httpx.Response(200, json=_limits(value=20)),
        }
    )
    client = _client(recorder)

    assigned = client.licenses.assign(user_ids=["user-1"])
    current_limits = client.licenses.get_limit()
    updated_limits = client.licenses.set_limit(value=20)

    assert assigned == (
        dl.License(
            id="lic-1",
            user_id="user-1",
            tenant_id="tenant-1",
            type="creator",
            is_active=True,
            expires_at="2026-12-31T00:00:00Z",
            created_by="admin-1",
            created_at="2026-07-01T00:00:00Z",
            updated_by="admin-2",
            updated_at="2026-07-02T00:00:00Z",
            meta={"source": "test"},
            raw=_license("lic-1", "user-1"),
        ),
    )
    assert current_limits == dl.LicenseLimits(
        current=dl.LicenseLimit(
            type="regular",
            value=10,
            started_at="2026-07-01T00:00:00Z",
            active_licenses_count=2,
        ),
        next=None,
    )
    assert updated_limits.current is not None
    assert updated_limits.current.value == 20
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/assignLicenses",
        "/rpc/getLicensesLimit",
        "/rpc/setLicenseLimit",
    ]
    assert recorder.request_json(0) == {"userIds": ["user-1"]}
    assert recorder.request_json(1) == {}
    assert recorder.request_json(2) == {"value": 20}


def test_list_licenses_maps_filters_and_paginates_lazily() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getLicenses": [
                httpx.Response(
                    200,
                    json={
                        "licenses": [_license("lic-1", "user-1", last_login_at="2026-07-10T00:00:00Z")],
                        "nextPageToken": "page-2",
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "licenses": [_license("lic-2", "user-2", expires_at=None) | {"lastLoginAt": None}],
                    },
                ),
            ]
        }
    )
    client = _client(recorder)

    pager = client.licenses.list(
        user_ids=["user-1", "user-2"],
        status="active",
        sort_by="updated_at",
        order="desc",
        page_size=2,
    )

    assert recorder.requests == []
    pages = list(pager.pages())
    assert [license.id for page in pages for license in page.items] == ["lic-1", "lic-2"]
    assert pages[0].items[0].last_login_at == "2026-07-10T00:00:00Z"
    assert pages[1].items[0].last_login_at is None
    assert pages[1].items[0].expires_at is None
    assert recorder.request_json(0) == {
        "userIds": ["user-1", "user-2"],
        "status": "active",
        "sortBy": "updatedAt",
        "order": "desc",
        "limit": 2,
    }
    assert recorder.request_json(1) == {
        "userIds": ["user-1", "user-2"],
        "status": "active",
        "sortBy": "updatedAt",
        "order": "desc",
        "limit": 2,
        "pageToken": "page-2",
    }


def test_license_argument_bounds_fail_before_requests() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(dl.DatalensValidationError, match="between 1 and 1000"):
        client.licenses.assign(user_ids=[])
    with pytest.raises(dl.DatalensValidationError, match="at most 1000"):
        client.licenses.list(user_ids=["user"] * 1001)
    with pytest.raises(dl.DatalensValidationError, match="between 1 and 200"):
        client.licenses.list(page_size=201)
    with pytest.raises(dl.DatalensValidationError, match="status must be one of"):
        client.licenses.list(status=cast(dl.LicenseStatus, "unknown"))
    with pytest.raises(dl.DatalensValidationError, match="between 1 and 10000"):
        client.licenses.set_limit(value=0)

    assert recorder.requests == []


def test_license_responses_are_strictly_validated() -> None:
    invalid = RecordedTransport({"/rpc/getLicenses": httpx.Response(200, json={"licenses": [{"licenseId": "bad"}]})})
    client = _client(invalid)

    with pytest.raises(dl.DTOValidationError, match="getLicenses"):
        list(client.licenses.list())

    repeated = RecordedTransport(
        {
            "/rpc/getLicenses": [
                httpx.Response(200, json={"licenses": [], "nextPageToken": "same"}),
                httpx.Response(200, json={"licenses": [], "nextPageToken": "same"}),
            ]
        }
    )
    client = _client(repeated)

    with pytest.raises(dl.InvalidResponseError, match="repeated nextPageToken"):
        list(client.licenses.list())


def test_license_read_rpcs_retry_transient_failures_but_mutations_do_not() -> None:
    reads = RecordedTransport(
        {
            "/rpc/getLicenses": [
                httpx.Response(503, json={"message": "temporarily unavailable"}),
                httpx.Response(200, json={"licenses": []}),
            ],
            "/rpc/getLicensesLimit": [
                httpx.Response(503, json={"message": "temporarily unavailable"}),
                httpx.Response(200, json=_limits(value=10)),
            ],
        }
    )
    client = _client(reads)

    assert list(client.licenses.list()) == []
    assert client.licenses.get_limit().current is not None
    assert [request.url.path for request in reads.requests] == [
        "/rpc/getLicenses",
        "/rpc/getLicenses",
        "/rpc/getLicensesLimit",
        "/rpc/getLicensesLimit",
    ]

    mutation = RecordedTransport(
        {
            "/rpc/assignLicenses": [
                httpx.Response(503, json={"message": "temporarily unavailable"}),
                httpx.Response(200, json=[_license("lic-1", "user-1")]),
            ]
        }
    )
    client = _client(mutation)

    with pytest.raises(dl.ServerError, match="temporarily unavailable"):
        client.licenses.assign(user_ids=["user-1"])
    assert len(mutation.requests) == 1
