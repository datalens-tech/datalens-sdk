from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
import json
from types import ModuleType
from typing import cast

import httpx
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.lakehouse_operation import LakehouseOperationAPI, LakehouseOperationService
from datalens_sdk.api.rest_catalog import RestCatalogAPI, RestCatalogService
from datalens_sdk.converter.rest_catalog import RestCatalogConverter
from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation, LakehouseTimestamp
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.rest_catalog import (
    RestCatalog,
    RestCatalogBucket,
    RestCatalogBucketDetails,
    RestCatalogBucketSettings,
    RestCatalogListOptions,
    RestCatalogSortField,
)
from datalens_sdk.errors import DataLensValidationError, DTOValidationError, InvalidResponseError
from datalens_sdk.http import DataLensHTTPClient


def test_rest_catalog_list_options_normalize_filters_and_preserve_explicit_values() -> None:
    filters = ["name='analytics'", "createdById='user-1'"]

    options = RestCatalogListOptions.create(
        cloud_environment_id="environment-1",
        filters=filters,
        include_permissions=False,
        sort_by="created_at",
        order="desc",
        page_size=0,
        page_token="",
    )
    filters.append("name='later'")

    assert options == RestCatalogListOptions(
        cloud_environment_id="environment-1",
        filters=("name='analytics'", "createdById='user-1'"),
        include_permissions=False,
        sort_by="created_at",
        order="desc",
        page_size=0,
        page_token="",
    )


@pytest.mark.parametrize("filters", ["name='analytics'", b"name='analytics'"])
def test_rest_catalog_list_options_reject_invalid_semantic_arguments_for_scalar_filters(filters: object) -> None:
    with pytest.raises(DataLensValidationError) as raised:
        RestCatalogListOptions.create(filters=cast(list[str], filters))

    assert type(raised.value) is DataLensValidationError


@pytest.mark.parametrize("cloud_environment_id", ["", 123, True])
def test_rest_catalog_list_options_reject_invalid_semantic_arguments_for_environment(
    cloud_environment_id: object,
) -> None:
    with pytest.raises(DataLensValidationError) as raised:
        RestCatalogListOptions.create(cloud_environment_id=cast(str, cloud_environment_id))

    assert type(raised.value) is DataLensValidationError


def test_rest_catalog_list_options_reject_invalid_semantic_arguments_for_sort() -> None:
    with pytest.raises(DataLensValidationError) as raised:
        RestCatalogListOptions.create(sort_by=cast(RestCatalogSortField, "unsupported"))

    assert type(raised.value) is DataLensValidationError


def test_rest_catalog_list_options_reject_invalid_semantic_arguments_for_order() -> None:
    with pytest.raises(DataLensValidationError) as raised:
        RestCatalogListOptions.create(order=cast(SortDirection, "unsupported"))

    assert type(raised.value) is DataLensValidationError


class RecordedCatalogTransport:
    def __init__(self, *responses: dict[str, object] | int) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, int):
            return httpx.Response(response, json={"code": "TEMPORARY", "message": "retry"})
        return httpx.Response(200, json=response)

    def bodies(self) -> list[object]:
        return [json.loads(request.content) for request in self.requests]


def _catalog_service(recorder: RecordedCatalogTransport) -> tuple[RestCatalogService, DataLensHTTPClient]:
    http_client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handle),
    )
    return (
        RestCatalogService(
            installation="yacloud",
            api=RestCatalogAPI(http_client),
            lakehouse_operations=LakehouseOperationService(api=LakehouseOperationAPI(http_client)),
        ),
        http_client,
    )


def _empty_page(next_token: str = "") -> dict[str, object]:
    return {"restCatalogs": [], "nextPageToken": next_token}


def test_rest_catalog_list_defaults_are_lazy_and_send_exact_payload() -> None:
    recorder = RecordedCatalogTransport(_empty_page())
    service, http_client = _catalog_service(recorder)
    with http_client:
        pager = service.list_rest_catalogs(RestCatalogListOptions.create())
        assert recorder.requests == []
        assert [page.items for page in pager.pages()] == [()]

    assert [request.url.path for request in recorder.requests] == ["/rpc/listCatalogs"]
    assert recorder.bodies() == [{"pageSize": 100, "reverseOrder": False}]


def test_yc_create_rest_catalog_posts_schema_payload_and_returns_operation() -> None:
    response = {"id": "operation-1", "done": False, "metadata": {}}
    refreshed_response = {"id": "operation-1", "done": True, "metadata": {}}
    recorder = RecordedCatalogTransport(response, refreshed_response)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        operation = (
            client.create.rest_catalog(
                name="analytics",
                cloud_environment_id="environment-1",
                bucket_settings=RestCatalogBucketSettings(
                    storage_class="STANDARD",
                    max_size="1073741824",
                    alias="analytics-bucket",
                    description="Catalog data",
                ),
            )
            .description("Analytics catalog")
            .labels({"team": "data-platform"})
            .build()
        )
        refreshed = operation.refresh()

    assert operation == LakehouseOperation(id="operation-1", done=False, metadata={}, raw=response)
    assert refreshed == LakehouseOperation(id="operation-1", done=True, metadata={}, raw=refreshed_response)
    assert [(request.url.path, body) for request, body in zip(recorder.requests, recorder.bodies(), strict=True)] == [
        (
            "/rpc/createRestCatalog",
            {
                "cloudEnvironmentId": "environment-1",
                "name": "analytics",
                "bucketSettings": {
                    "storageClass": "STANDARD",
                    "maxSize": "1073741824",
                    "alias": "analytics-bucket",
                    "description": "Catalog data",
                },
                "description": "Analytics catalog",
                "labels": {"team": "data-platform"},
            },
        ),
        ("/rpc/getLakehouseOperation", {"operationId": "operation-1"}),
    ]


def test_yc_create_rest_catalog_rejects_invalid_bucket_size_before_http() -> None:
    recorder = RecordedCatalogTransport({"id": "operation-1", "done": False, "metadata": {}})
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client, pytest.raises(DTOValidationError, match="createRestCatalog"):
        client.create.rest_catalog(
            name="analytics",
            cloud_environment_id="environment-1",
            bucket_settings=RestCatalogBucketSettings(
                storage_class="STANDARD",
                max_size="not-a-number",
                alias="analytics-bucket",
            ),
        ).build()

    assert recorder.requests == []


@pytest.mark.parametrize(
    ("sort_by", "wire_sort", "order", "reverse", "include_permissions"),
    [
        ("name", "name", "asc", False, False),
        ("created_at", "createdAt", "desc", True, True),
        ("updated_at", "updatedAt", "asc", False, False),
    ],
)
def test_rest_catalog_list_serializes_environment_filters_permissions_and_sorting(
    sort_by: RestCatalogSortField,
    wire_sort: str,
    order: SortDirection,
    reverse: bool,
    include_permissions: bool,
) -> None:
    recorder = RecordedCatalogTransport(_empty_page())
    service, http_client = _catalog_service(recorder)
    options = RestCatalogListOptions.create(
        cloud_environment_id="environment-1",
        filters=["name='analytics'"],
        include_permissions=include_permissions,
        sort_by=sort_by,
        order=order,
        page_size=7,
        page_token="resume",
    )
    with http_client:
        assert list(service.list_rest_catalogs(options)) == []

    assert recorder.bodies() == [
        {
            "cloudEnvironmentId": "environment-1",
            "filter": ["name='analytics'"],
            "includePermissions": include_permissions,
            "sortBy": wire_sort,
            "reverseOrder": reverse,
            "pageSize": 7,
            "pageToken": "resume",
        }
    ]


@pytest.mark.parametrize(
    ("page_token", "expected"),
    [("", {"pageSize": 0, "reverseOrder": False, "pageToken": ""}), (None, {"pageSize": 0, "reverseOrder": False})],
)
def test_rest_catalog_list_payload_preserves_explicit_falsy_pagination_values(
    page_token: str | None, expected: dict[str, object]
) -> None:
    recorder = RecordedCatalogTransport(_empty_page())
    service, http_client = _catalog_service(recorder)
    with http_client:
        assert list(service.list_rest_catalogs(RestCatalogListOptions.create(page_size=0, page_token=page_token))) == []
    assert recorder.bodies() == [expected]


def test_rest_catalog_list_resumes_and_preserves_empty_final_token() -> None:
    recorder = RecordedCatalogTransport(_empty_page("second"), _empty_page(""))
    service, http_client = _catalog_service(recorder)
    with http_client:
        pages = list(service.list_rest_catalogs(RestCatalogListOptions.create(page_token="first")).pages())

    assert [page.next_page_token for page in pages] == ["second", ""]
    assert recorder.bodies() == [
        {"pageSize": 100, "reverseOrder": False, "pageToken": "first"},
        {"pageSize": 100, "reverseOrder": False, "pageToken": "second"},
    ]


@pytest.mark.parametrize(
    ("tokens", "request_count"),
    [(["A"], 1), (["B", "A"], 2)],
)
def test_rest_catalog_list_rejects_repeated_token_before_reuse(tokens: list[str], request_count: int) -> None:
    recorder = RecordedCatalogTransport(*(_empty_page(token) for token in tokens))
    service, http_client = _catalog_service(recorder)
    with http_client, pytest.raises(InvalidResponseError, match="listCatalogs"):
        list(service.list_rest_catalogs(RestCatalogListOptions.create(page_token="A")).pages())

    assert len(recorder.requests) == request_count


@pytest.mark.parametrize("page_size", [-1, True])
def test_rest_catalog_negative_or_boolean_page_size_fails_lazily_before_http(page_size: int) -> None:
    recorder = RecordedCatalogTransport()
    service, http_client = _catalog_service(recorder)
    with http_client:
        pager = service.list_rest_catalogs(RestCatalogListOptions.create(page_size=page_size))
        assert recorder.requests == []
        with pytest.raises(DTOValidationError, match="listCatalogs"):
            list(pager.pages())
    assert recorder.requests == []


def test_rest_catalog_list_retries_each_page_transiently() -> None:
    recorder = RecordedCatalogTransport(503, _empty_page("next"), 503, _empty_page())
    service, http_client = _catalog_service(recorder)
    with http_client:
        pager = service.list_rest_catalogs(RestCatalogListOptions.create())
        assert recorder.requests == []
        assert len(list(pager.pages())) == 2

    assert recorder.bodies() == [
        {"pageSize": 100, "reverseOrder": False},
        {"pageSize": 100, "reverseOrder": False},
        {"pageSize": 100, "reverseOrder": False, "pageToken": "next"},
        {"pageSize": 100, "reverseOrder": False, "pageToken": "next"},
    ]


def _catalog_item() -> dict[str, object]:
    return {
        "id": "catalog-1",
        "organizationId": "organization-1",
        "tenantId": "tenant-1",
        "cloudEnvironmentId": "environment-1",
        "name": "analytics",
        "description": "catalog description",
        "createdById": "user-1",
        "bucket": {
            "settings": {
                "storageClass": "STANDARD",
                "maxSize": "9007199254740993",
                "alias": "bucket-alias",
                "description": "bucket description",
            },
            "details": {
                "maxSize": "10000000000000000000",
                "usedSize": "42",
                "updatedAt": {"seconds": "1710000002", "nanos": 0},
            },
        },
        "labels": {"team": "data"},
        "permissions": {"read": True, "write": False},
        "createdAt": {"seconds": "1710000000", "nanos": 0},
        "updatedAt": {"seconds": "1710000001", "nanos": 0},
    }


@pytest.mark.parametrize(
    ("created_nanos", "updated_nanos", "detail_nanos"),
    [
        (0, 0.25, 9007199254740993),
        (0.25, 9007199254740993, 0),
        (9007199254740993, 0, 0.25),
    ],
)
def test_rest_catalog_list_converts_complete_nested_catalog(
    created_nanos: int | float, updated_nanos: int | float, detail_nanos: int | float
) -> None:
    item = _catalog_item()
    cast(dict[str, object], item["createdAt"])["nanos"] = created_nanos
    cast(dict[str, object], item["updatedAt"])["nanos"] = updated_nanos
    details = cast(dict[str, object], cast(dict[str, object], item["bucket"])["details"])
    cast(dict[str, object], details["updatedAt"])["nanos"] = detail_nanos
    recorder = RecordedCatalogTransport({"restCatalogs": [item], "nextPageToken": ""})
    service, http_client = _catalog_service(recorder)

    with http_client:
        pages = list(service.list_rest_catalogs(RestCatalogListOptions.create()).pages())

    assert pages == [
        Page(
            items=(
                RestCatalog(
                    id="catalog-1",
                    installation="yacloud",
                    organization_id="organization-1",
                    tenant_id="tenant-1",
                    cloud_environment_id="environment-1",
                    name="analytics",
                    description="catalog description",
                    created_by_id="user-1",
                    bucket=RestCatalogBucket(
                        settings=RestCatalogBucketSettings(
                            storage_class="STANDARD",
                            max_size="9007199254740993",
                            alias="bucket-alias",
                            description="bucket description",
                        ),
                        details=RestCatalogBucketDetails(
                            max_size="10000000000000000000",
                            used_size="42",
                            updated_at=LakehouseTimestamp(seconds="1710000002", nanos=detail_nanos),
                        ),
                    ),
                    labels={"team": "data"},
                    permissions={"read": True, "write": False},
                    created_at=LakehouseTimestamp(seconds="1710000000", nanos=created_nanos),
                    updated_at=LakehouseTimestamp(seconds="1710000001", nanos=updated_nanos),
                    raw=item,
                ),
            ),
            next_page_token="",
        )
    ]
    catalog = pages[0].items[0]
    assert catalog.created_at is not None
    assert catalog.updated_at is not None
    assert catalog.bucket.details is not None
    assert catalog.bucket.details.updated_at is not None
    for timestamp, seconds, nanos in (
        (catalog.created_at, "1710000000", created_nanos),
        (catalog.updated_at, "1710000001", updated_nanos),
        (catalog.bucket.details.updated_at, "1710000002", detail_nanos),
    ):
        assert timestamp.seconds == seconds
        assert timestamp.nanos == nanos
        assert type(timestamp.nanos) is type(nanos)
    assert catalog.raw == item
    assert catalog.raw is not item


def test_rest_catalog_list_normalizes_omitted_and_empty_values() -> None:
    omitted = _catalog_item()
    omitted.pop("labels")
    omitted.pop("permissions")
    omitted.pop("createdAt")
    omitted.pop("updatedAt")
    cast(dict[str, object], omitted["bucket"]).pop("details")
    empty = _catalog_item()
    empty["id"] = "catalog-2"
    empty["name"] = ""
    empty["description"] = ""
    empty["createdById"] = ""
    empty["labels"] = {}
    empty["permissions"] = {}
    cast(dict[str, object], empty["createdAt"])["nanos"] = 0
    cast(dict[str, object], cast(dict[str, object], empty["bucket"])["settings"])["alias"] = ""
    recorder = RecordedCatalogTransport({"restCatalogs": [omitted, empty], "nextPageToken": ""})
    service, http_client = _catalog_service(recorder)

    with http_client:
        catalog_omitted, catalog_empty = list(service.list_rest_catalogs(RestCatalogListOptions.create()))

    assert catalog_omitted == RestCatalog(
        id="catalog-1",
        installation="yacloud",
        organization_id="organization-1",
        tenant_id="tenant-1",
        cloud_environment_id="environment-1",
        name="analytics",
        description="catalog description",
        created_by_id="user-1",
        bucket=RestCatalogBucket(
            settings=RestCatalogBucketSettings(
                storage_class="STANDARD",
                max_size="9007199254740993",
                alias="bucket-alias",
                description="bucket description",
            )
        ),
        labels={},
        permissions=None,
        created_at=None,
        updated_at=None,
        raw=omitted,
    )
    assert catalog_empty == RestCatalog(
        id="catalog-2",
        installation="yacloud",
        organization_id="organization-1",
        tenant_id="tenant-1",
        cloud_environment_id="environment-1",
        name="",
        description="",
        created_by_id="",
        bucket=RestCatalogBucket(
            settings=RestCatalogBucketSettings(
                storage_class="STANDARD",
                max_size="9007199254740993",
                alias="",
                description="bucket description",
            ),
            details=RestCatalogBucketDetails(
                max_size="10000000000000000000",
                used_size="42",
                updated_at=LakehouseTimestamp(seconds="1710000002", nanos=0),
            ),
        ),
        labels={},
        permissions={},
        created_at=LakehouseTimestamp(seconds="1710000000", nanos=0),
        updated_at=LakehouseTimestamp(seconds="1710000001", nanos=0),
        raw=empty,
    )
    assert catalog_empty.created_at is not None
    assert type(catalog_empty.created_at.nanos) is int


def test_rest_catalog_list_preserves_item_and_nested_unknown_fields_in_raw() -> None:
    item = _catalog_item()
    item["futureField"] = {"enabled": True}
    bucket = cast(dict[str, object], item["bucket"])
    bucket["futureBucket"] = ["value"]
    cast(dict[str, object], bucket["settings"])["futureSetting"] = 17
    cast(dict[str, object], bucket["details"])["futureDetail"] = {"value": "kept"}
    cast(dict[str, object], item["createdAt"])["futureTimestamp"] = "kept"
    catalog = RestCatalogConverter.to_page({"restCatalogs": [item], "nextPageToken": ""}, installation="yacloud").items[
        0
    ]

    assert catalog.raw == item
    assert catalog.raw is not item
    assert catalog.raw["bucket"] is item["bucket"]


def test_rest_catalog_list_tolerates_unexposed_root_unknown_fields() -> None:
    item = _catalog_item()
    recorder = RecordedCatalogTransport({"restCatalogs": [item], "nextPageToken": "", "futureRoot": "hidden"})
    service, http_client = _catalog_service(recorder)

    with http_client:
        page = next(service.list_rest_catalogs(RestCatalogListOptions.create()).pages())

    assert len(page.items) == 1
    assert page.items[0].raw == item
    assert "futureRoot" not in page.items[0].raw


_MISSING = object()


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("restCatalogs",), _MISSING),
        (("restCatalogs",), "not an array"),
        (("nextPageToken",), _MISSING),
        (("nextPageToken",), 123),
        (("restCatalogs", 1, "id"), _MISSING),
        (("restCatalogs", 1, "organizationId"), _MISSING),
        (("restCatalogs", 1, "tenantId"), _MISSING),
        (("restCatalogs", 1, "cloudEnvironmentId"), _MISSING),
        (("restCatalogs", 1, "name"), _MISSING),
        (("restCatalogs", 1, "description"), _MISSING),
        (("restCatalogs", 1, "createdById"), _MISSING),
        (("restCatalogs", 1, "bucket"), _MISSING),
        (("restCatalogs", 1, "bucket", "settings"), _MISSING),
        (("restCatalogs", 1, "bucket", "settings", "storageClass"), _MISSING),
        (("restCatalogs", 1, "bucket", "settings", "maxSize"), _MISSING),
        (("restCatalogs", 1, "bucket", "settings", "alias"), _MISSING),
        (("restCatalogs", 1, "createdAt", "seconds"), _MISSING),
        (("restCatalogs", 1, "bucket", "details", "updatedAt", "seconds"), 123),
        (("restCatalogs", 1, "labels", "team"), 123),
        (("restCatalogs", 1, "permissions", "read"), "yes"),
        (("restCatalogs", 1, "bucket"), []),
        (("restCatalogs", 1, "bucket", "details"), []),
        (("restCatalogs", 1, "updatedAt"), []),
    ],
)
def test_rest_catalog_list_rejects_missing_or_malformed_response_fields(
    path: tuple[str | int, ...], replacement: object
) -> None:
    response: dict[str, object] = {"restCatalogs": [_catalog_item(), _catalog_item()], "nextPageToken": ""}
    target: object = response
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    last = path[-1]
    if replacement is _MISSING:
        del target[last]  # type: ignore[attr-defined]
    else:
        target[last] = replacement  # type: ignore[index]
    recorder = RecordedCatalogTransport(response)
    service, http_client = _catalog_service(recorder)

    with http_client, pytest.raises(DTOValidationError, match="listCatalogs") as raised:
        next(service.list_rest_catalogs(RestCatalogListOptions.create()).pages())

    assert type(raised.value) is DTOValidationError
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("identifier", ["id", "cloudEnvironmentId"])
def test_rest_catalog_list_rejects_empty_reference_ids(identifier: str) -> None:
    valid = _catalog_item()
    invalid = _catalog_item()
    invalid[identifier] = ""
    recorder = RecordedCatalogTransport({"restCatalogs": [valid, invalid], "nextPageToken": ""})
    service, http_client = _catalog_service(recorder)

    with http_client, pytest.raises(InvalidResponseError, match="listCatalogs") as raised:
        next(service.list_rest_catalogs(RestCatalogListOptions.create()).pages())

    assert type(raised.value) is InvalidResponseError
    assert len(recorder.requests) == 1


def test_yc_list_rest_catalogs_dispatches_read_with_public_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_load_installations = client_module._load_installations

    def load_without_catalog_namespace(generated_package: str) -> dict[str, client_module.InstallationInfo]:
        installations = original_load_installations(generated_package)
        installations["yacloud"]["namespaces"] = [
            namespace for namespace in installations["yacloud"]["namespaces"] if namespace != "rest_catalogs"
        ]
        return installations

    monkeypatch.setattr(client_module, "_load_installations", load_without_catalog_namespace)
    recorder = RecordedCatalogTransport({"restCatalogs": [_catalog_item()], "nextPageToken": ""})
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        pager = client.list.rest_catalogs(
            cloud_environment_id="environment-1",
            filters=["name='analytics'"],
            include_permissions=False,
        )
        assert recorder.requests == []
        catalogs = list(pager)

    assert [(catalog.id, catalog.installation) for catalog in catalogs] == [("catalog-1", "yacloud")]
    assert [request.url.path for request in recorder.requests] == ["/rpc/listCatalogs"]
    assert recorder.bodies() == [
        {
            "cloudEnvironmentId": "environment-1",
            "filter": ["name='analytics'"],
            "includePermissions": False,
            "pageSize": 100,
            "reverseOrder": False,
        }
    ]


@pytest.mark.parametrize(
    ("argument", "value"),
    [("filters", "name='analytics'"), ("cloud_environment_id", ""), ("sort_by", "invalid"), ("order", "invalid")],
)
def test_yc_rest_catalog_invalid_options_fail_before_http(argument: str, value: str) -> None:
    recorder = RecordedCatalogTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client, pytest.raises(DataLensValidationError) as raised:
        cast(Callable[..., object], client.list.rest_catalogs)(**{argument: value})

    assert type(raised.value) is DataLensValidationError
    assert recorder.requests == []


def test_yc_rest_catalog_list_requires_keyword_arguments() -> None:
    recorder = RecordedCatalogTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client, pytest.raises(TypeError):
        cast(Callable[..., object], client.list.rest_catalogs)("environment-1")

    assert recorder.requests == []


def test_yc_unknown_list_action_raises_plain_attribute_error_without_http() -> None:
    recorder = RecordedCatalogTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    action = "unrelated_action"
    with client, pytest.raises(AttributeError) as raised:
        getattr(client.list, action)

    assert type(raised.value) is AttributeError
    assert recorder.requests == []


class DtoWithoutCatalogs(ModuleType):
    def __getattr__(self, name: str) -> object:
        if "Catalog" in name:
            raise AssertionError(f"Unexpected catalog DTO access: {name}")
        return getattr(generated_dto, name)


def test_enterprise_list_rest_catalogs_is_absent_without_catalog_dto_or_service_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = import_module
    dto_stub = DtoWithoutCatalogs("datalens_sdk._generated.dto")

    def import_without_catalogs(name: str) -> ModuleType:
        if name == "datalens_sdk._generated.dto":
            return dto_stub
        return original_import(name)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("Catalog service initialized on Enterprise")

    monkeypatch.setattr(client_module, "import_module", import_without_catalogs)
    monkeypatch.setattr(RestCatalogService, "__init__", unexpected_service)
    recorder = RecordedCatalogTransport()
    with DataLensClientEnterprise(
        auth=None, base_url="https://enterprise.test", transport=httpx.MockTransport(recorder.handle)
    ) as client:
        action = "rest_catalogs"
        with pytest.raises(AttributeError) as raised:
            getattr(client.list, action)
        assert type(raised.value) is AttributeError
    assert recorder.requests == []


def test_yateam_style_list_rest_catalogs_is_absent_without_catalog_dto_or_service_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class YaTeamStyleClient(client_module.DataLensClientBase):
        INSTALLATION = "yateam"
        GENERATED_PACKAGE = "test_yateam_generated"
        DEFAULT_BASE_URL = "https://yateam.test"

    sources = import_module("datalens_sdk._generated.builders.dataset_sources")
    charts = import_module("datalens_sdk._generated.builders.charts")
    monkeypatch.setattr(sources, "YateamSourceCreateFactory", sources.EnterpriseSourceCreateFactory, raising=False)
    monkeypatch.setattr(
        charts, "YateamEditorChartCreateFactory", charts.EnterpriseEditorChartCreateFactory, raising=False
    )
    modules = {
        "test_yateam_generated.dto": DtoWithoutCatalogs("test_yateam_generated.dto"),
        "test_yateam_generated.builders.yateam": import_module("datalens_sdk._generated.builders.enterprise"),
        "test_yateam_generated.builders.dataset_sources": sources,
        "test_yateam_generated.builders.charts": charts,
    }
    monkeypatch.setattr(
        client_module,
        "_load_installations",
        lambda package: {
            "yateam": {
                "connectors": {},
                "dataset_sources": {},
                "namespaces": [],
                "chart_factories": {"wizard": [], "ql": [], "editor": []},
            }
        },
    )
    monkeypatch.setattr(client_module, "import_module", modules.__getitem__)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("Catalog service initialized on YaTeam")

    monkeypatch.setattr(RestCatalogService, "__init__", unexpected_service)
    recorder = RecordedCatalogTransport()
    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(recorder.handle)) as client:
        action = "rest_catalogs"
        with pytest.raises(AttributeError) as raised:
            getattr(client.list, action)
        assert type(raised.value) is AttributeError
    assert recorder.requests == []
