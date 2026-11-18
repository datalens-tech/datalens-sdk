from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_state import DashboardStateConverter
from datalens_sdk.errors import DashboardStateNotFoundError, DTOValidationError, NotFoundError

Client = dl.DataLensClientYC | dl.DataLensClientEnterprise
INSTALLATIONS = ("yacloud", "enterprise")
STATE_DATA: dict[str, object] = {
    "__meta__": {"version": 2, "queue": [{"id": "sel-1"}, {"id": "chart-1", "tabId": "t2"}]},
    "sel-1": {"params": {"region": ["EU"]}},
    "chart-1": {"params": {}, "state": {"tabId": "t2", "scroll": 4}},
}
TYPED_DATA = dl.DashboardStateData(
    version=2,
    queue=(dl.StateQueueItem("sel-1"), dl.StateQueueItem("chart-1", tab_id="t2")),
    widgets={
        "sel-1": dl.StateWidget(params={"region": ("EU",)}),
        "chart-1": dl.StateWidget(params={}, state=dl.StateWidgetState(tab_id="t2", extra={"scroll": 4})),
    },
)


class RecordedTransport:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self._responses, f"Unexpected request {request.url.path}"
        response = self._responses.pop(0)
        response.request = request
        return response

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def bodies(self) -> list[dict[str, object]]:
        return [cast(dict[str, object], json.loads(request.content)) for request in self.requests]


def _client(recorder: RecordedTransport, installation: str) -> Client:
    client_type = dl.DataLensClientYC if installation == "yacloud" else dl.DataLensClientEnterprise
    return client_type(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(recorder.handler))


def _state_response(**overrides: object) -> httpx.Response:
    body: dict[str, object] = {
        "entryId": "dash-1",
        "hash": "21e04f18384",
        "data": STATE_DATA,
        "createdAt": "2026-11-12T10:20:30.123Z",
        **overrides,
    }
    return httpx.Response(200, json=body)


@pytest.mark.parametrize("installation", INSTALLATIONS)
def test_get_dashboard_state_reads_typed_data_through_generated_dtos(installation: str) -> None:
    recorder = RecordedTransport([_state_response()])

    record = _client(recorder, installation)._dashboard_service.get_dashboard_state("dash-1", "21e04f18384")

    assert recorder.paths() == ["/rpc/getEntryState"]
    assert recorder.bodies() == [{"entryId": "dash-1", "hash": "21e04f18384"}]
    assert record.hash == "21e04f18384"
    assert record.data == TYPED_DATA
    assert record.raw == STATE_DATA
    assert record.created_at == datetime(2026, 11, 12, 10, 20, 30, 123000, tzinfo=timezone.utc)


@pytest.mark.parametrize(("created_at", "expected"), [("not a date", None), ("2026-11-12T10:20:30+03:00", 7)])
def test_get_dashboard_state_parses_created_at_leniently(created_at: str, expected: int | None) -> None:
    recorder = RecordedTransport([_state_response(createdAt=created_at)])

    record = _client(recorder, "yacloud")._dashboard_service.get_dashboard_state("dash-1", "h")

    if expected is None:
        assert record.created_at is None
    else:
        assert record.created_at is not None
        assert record.created_at.astimezone(timezone.utc).hour == expected


def test_null_and_legacy_data_are_typed() -> None:
    legacy = {"w1": {"params": {"region": "EU"}}}
    recorder = RecordedTransport([_state_response(data=None), _state_response(data=legacy)])
    service = _client(recorder, "yacloud")._dashboard_service

    empty = service.get_dashboard_state("dash-1", "h").data
    old = service.get_dashboard_state("dash-1", "h").data

    assert (empty.version, empty.queue, dict(empty.widgets)) == (2, (), {})
    assert (old.version, old.queue, old.widgets["w1"].params) == (1, (), {"region": "EU"})


@pytest.mark.parametrize(
    "body",
    [
        {"entryId": "dash-1", "hash": "h"},
        {"hash": "", "data": {}, "createdAt": "x"},
        {"entryId": "dash-1", "hash": "h", "createdAt": "x", "data": {"__meta__": {"version": 3, "queue": []}}},
        {"entryId": "dash-1", "hash": "h", "createdAt": "x", "data": {"w": {"params": {"a": 1}}}},
    ],
)
def test_get_dashboard_state_rejects_invalid_responses(body: dict[str, object]) -> None:
    recorder = RecordedTransport([httpx.Response(200, json=body)])

    with pytest.raises(DTOValidationError, match="getEntryState"):
        _client(recorder, "yacloud")._dashboard_service.get_dashboard_state("dash-1", "h")


def test_get_dashboard_state_rejects_empty_hash_before_request() -> None:
    recorder = RecordedTransport([])

    with pytest.raises(dl.DataLensValidationError):
        _client(recorder, "yacloud")._dashboard_service.get_dashboard_state("dash-1", "")
    assert recorder.requests == []


@pytest.mark.parametrize("installation", INSTALLATIONS)
def test_create_dashboard_state_sends_the_generated_payload(installation: str) -> None:
    recorder = RecordedTransport([httpx.Response(200, json={"hash": "298725dd251"})])

    record = _client(recorder, installation)._dashboard_service.create_dashboard_state("dash-1", TYPED_DATA)

    assert record.hash == "298725dd251"
    assert record.data == TYPED_DATA
    assert record.raw == STATE_DATA
    assert recorder.paths() == ["/rpc/createEntryState"]
    assert recorder.bodies() == [{"entryId": "dash-1", "data": STATE_DATA}]


def test_create_dashboard_state_rejects_missing_hash() -> None:
    recorder = RecordedTransport([httpx.Response(200, json={})])

    with pytest.raises(DTOValidationError, match="createEntryState"):
        _client(recorder, "yacloud")._dashboard_service.create_dashboard_state("dash-1", TYPED_DATA)


def test_create_dashboard_state_retries_transient_failures() -> None:
    recorder = RecordedTransport([httpx.Response(503, json={}), httpx.Response(200, json={"hash": "h"})])

    assert _client(recorder, "yacloud")._dashboard_service.create_dashboard_state("dash-1", TYPED_DATA).hash == "h"
    assert recorder.paths() == ["/rpc/createEntryState", "/rpc/createEntryState"]


def test_create_dashboard_state_rejects_payloads_above_the_limit_before_request() -> None:
    recorder = RecordedTransport([])
    data = dl.DashboardStateData(
        version=2,
        queue=(dl.StateQueueItem("w"),),
        widgets={"w": dl.StateWidget(params={"p": "Ж" * 50_000})},
    )

    with pytest.raises(dl.DataLensValidationError, match="limit is 50000"):
        _client(recorder, "yacloud")._dashboard_service.create_dashboard_state("dash-1", data)
    assert recorder.requests == []


def test_state_size_counts_utf16_code_units() -> None:
    assert DashboardStateConverter.symbols({"a": "😀"}) == len('{"a":"') + 2 + len('"}')
    assert DashboardStateConverter.symbols({"a": "Ж"}) == 9


@pytest.mark.parametrize("installation", INSTALLATIONS)
def test_missing_state_maps_to_dashboard_state_not_found(installation: str) -> None:
    body = {
        "status": 404,
        "code": "NOT_EXIST_STATE_BY_HASH",
        "message": "The state by this hash has doesn't exist",
        "details": {"title": "NOT_EXIST_STATE_BY_HASH"},
    }
    recorder = RecordedTransport([httpx.Response(404, json=body)])

    with pytest.raises(DashboardStateNotFoundError) as exc_info:
        _client(recorder, installation)._dashboard_service.get_dashboard_state("dash-1", "00000000000")

    assert isinstance(exc_info.value, NotFoundError)
    assert exc_info.value.context.code == "NOT_EXIST_STATE_BY_HASH"
    assert recorder.paths() == ["/rpc/getEntryState"]
