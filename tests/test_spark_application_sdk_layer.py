from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from importlib import import_module
import json
from types import ModuleType
from typing import Any, cast

import httpx
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.lakehouse_operation import LakehouseOperationAPI, LakehouseOperationService
from datalens_sdk.api.spark_application import SparkApplicationAPI, SparkApplicationService
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.domain import spark_application as spark_application_module
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation, LakehouseOperationError, LakehouseTimestamp
from datalens_sdk.domain.ports import SparkApplicationOperations
from datalens_sdk.domain.rest_catalog import RestCatalog, RestCatalogBucket, RestCatalogBucketSettings
from datalens_sdk.domain.spark_application import (
    SparkApplication,
    SparkApplicationCatalogRef,
    SparkApplicationConnectSpec,
    SparkApplicationListOptions,
    SparkApplicationPySparkSpec,
    SparkApplicationSparkSpec,
    normalize_spark_application_cluster,
)
from datalens_sdk.domain.spark_cluster import (
    SparkCluster,
    SparkClusterConfig,
    SparkClusterDependencies,
    SparkFixedScalePolicy,
    SparkResourcePoolConfig,
    SparkResourcePoolsConfig,
)
from datalens_sdk.domain.specs.spark_application import SparkApplicationSparkCreateSpec
from datalens_sdk.errors import (
    DataLensAPIError,
    DataLensConfigurationError,
    DataLensTransportError,
    DataLensValidationError,
    DTOValidationError,
    InvalidResponseError,
)
from datalens_sdk.http import DataLensHTTPClient


def _cluster(
    *,
    id: str = "lakehouse-1",
    cluster_id: str = "managed-1",
    entry_id: str = "entry-1",
    installation: str = "yacloud",
) -> SparkCluster:
    pool = SparkResourcePoolConfig(resource_preset_id="preset-1", scale_policy=SparkFixedScalePolicy(size=1))
    return SparkCluster(
        id=id,
        cluster_id=cluster_id,
        installation=installation,
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        name="cluster",
        description="",
        labels={},
        config=SparkClusterConfig(
            spark_version="3.5",
            resource_pools=SparkResourcePoolsConfig(driver=pool, executor=pool),
            dependencies=SparkClusterDependencies(pip_packages=(), deb_packages=()),
            logging=None,
        ),
        health="ALIVE",
        status="RUNNING",
        entry_id=entry_id,
        raw={},
    )


def test_application_cluster_reference_uses_lakehouse_id_and_rejects_known_mismatches() -> None:
    assert normalize_spark_application_cluster(_cluster(), installation="yacloud") == "lakehouse-1"
    assert normalize_spark_application_cluster("raw-lakehouse", installation="yacloud") == "raw-lakehouse"
    for value in ("", _cluster(id=""), _cluster(installation="enterprise"), _cluster(installation=""), 42):
        with pytest.raises(DataLensValidationError):
            normalize_spark_application_cluster(value, installation="yacloud")  # type: ignore[arg-type]


def test_application_list_options_snapshot_filters_and_preserve_explicit_pagination() -> None:
    filters = ['name="first"', 'created_by="second"']
    options = SparkApplicationListOptions.create(
        installation="yacloud", cluster=_cluster(), filters=filters, page_size=0, page_token=""
    )
    filters.append('job_type="sparkApplication"')

    assert options == SparkApplicationListOptions("lakehouse-1", ('name="first"', 'created_by="second"'), 0, "")
    assert SparkApplicationListOptions.create(installation="yacloud", cluster="raw-lakehouse").page_token is None
    for invalid in ('name="x"', b'name="x"'):
        with pytest.raises(DataLensValidationError):
            SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1", filters=invalid)  # type: ignore[arg-type]


def test_application_refresh_requires_binding_and_uses_held_lakehouse_ids_without_mutation() -> None:
    application = SparkApplication(
        id="application-1",
        cluster_id="lakehouse-1",
        installation="yacloud",
        name="before",
        created_by="user-1",
        status="RUNNING",
        connect_url="",
        catalogs=(),
        created_at=LakehouseTimestamp("1", 0),
        started_at=None,
        finished_at=None,
        spec=None,
        raw={},
    )
    with pytest.raises(DataLensConfigurationError):
        application.refresh()

    class FakeOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def get_spark_application(self, cluster_id: str, application_id: str) -> SparkApplication:
            self.calls.append((cluster_id, application_id))
            return replace(application, name="after")

    operations = FakeOperations()
    bound = replace(application, _operations=cast(SparkApplicationOperations, operations))
    assert bound.refresh() == replace(application, name="after")
    assert bound.name == "before"
    assert operations.calls == [("lakehouse-1", "application-1")]
    for invalid in (replace(bound, id=""), replace(bound, cluster_id="")):
        with pytest.raises(DataLensValidationError):
            invalid.refresh()
    assert operations.calls == [("lakehouse-1", "application-1")]


def _wire_application(kind: str | None = "sparkApplication", *, cluster_id: str = "managed-1") -> dict[str, object]:
    common: dict[str, object] = {
        "archiveUris": [],
        "fileUris": [],
        "jarFileUris": [],
        "packages": [],
        "repositories": [],
        "excludePackages": [],
        "properties": {},
    }
    result: dict[str, object] = {
        "id": "application-1",
        "clusterId": cluster_id,
        "name": "analytics",
        "createdBy": "user-1",
        "status": "RUNNING",
        "connectUrl": "",
        "catalogs": [{"catalogId": "catalog-1", "futureCatalog": True}],
        "createdAt": {"seconds": "123", "nanos": 9007199254740993, "futureTime": 1},
        "startedAt": None,
        "finishedAt": None,
        "futureField": {"new": True},
    }
    if kind == "sparkApplication":
        result.update(
            applicationSpec=kind,
            sparkApplication={
                **common,
                "args": [],
                "mainJarFileUri": "s3://application.jar",
                "mainClass": "Main",
                "futureSpec": 3,
            },
        )
    elif kind == "pysparkApplication":
        result.update(
            applicationSpec=kind,
            pysparkApplication={**common, "args": [], "mainPythonFileUri": "s3://application.py", "pythonFileUris": []},
        )
    elif kind == "sparkConnectApplication":
        result.update(applicationSpec=kind, sparkConnectApplication=common)
    return result


class _Transport:
    def __init__(self, responses: Sequence[httpx.Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, f"unexpected request: {request.url.path}"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def bodies(self) -> list[dict[str, object]]:
        return [cast(dict[str, object], json.loads(request.content)) for request in self.requests]


def _service(transport: _Transport) -> tuple[DataLensHTTPClient, SparkApplicationService]:
    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://spark.test",
        transport=httpx.MockTransport(transport.handle),
    )
    return client, SparkApplicationService(
        installation="yacloud",
        api=SparkApplicationAPI(client),
        lakehouse_operations=LakehouseOperationService(api=LakehouseOperationAPI(client)),
    )


@pytest.mark.parametrize("kind", ["sparkApplication", "pysparkApplication", "sparkConnectApplication", None])
def test_application_get_maps_typed_and_common_only_specs_preserving_raw(kind: str | None) -> None:
    wire = _wire_application(kind, cluster_id="lakehouse-1")
    transport = _Transport([httpx.Response(200, json=wire), httpx.Response(200, json=wire)])
    client, service = _service(transport)
    with client:
        application = service.get_spark_application("lakehouse-1", "application-1")
        refreshed = application.refresh()

    expected_spec = {
        "sparkApplication": SparkApplicationSparkSpec("s3://application.jar", "Main", (), (), (), (), (), (), (), {}),
        "pysparkApplication": SparkApplicationPySparkSpec("s3://application.py", (), (), (), (), (), (), (), (), {}),
        "sparkConnectApplication": SparkApplicationConnectSpec((), (), (), (), (), (), {}),
        None: None,
    }[kind]
    expected = SparkApplication(
        id="application-1",
        cluster_id="lakehouse-1",
        installation="yacloud",
        name="analytics",
        created_by="user-1",
        status="RUNNING",
        connect_url="",
        catalogs=(SparkApplicationCatalogRef("catalog-1"),),
        created_at=LakehouseTimestamp("123", 9007199254740993),
        started_at=None,
        finished_at=None,
        spec=expected_spec,
        raw=wire,
    )
    assert application == expected
    assert refreshed == expected
    assert refreshed is not application
    assert type(application.created_at.nanos) is int
    assert transport.bodies() == [
        {"clusterId": "lakehouse-1", "applicationId": "application-1"},
        {"clusterId": "lakehouse-1", "applicationId": "application-1"},
    ]


@pytest.mark.parametrize("operation", ["getSparkApplication", "listSparkApplications"])
def test_application_read_rejects_python_field_name_instead_of_nested_wire_alias(operation: str) -> None:
    wire = _wire_application("sparkApplication")
    spark_spec = cast(dict[str, object], wire["sparkApplication"])
    spark_spec["main_jar_file_uri"] = spark_spec.pop("mainJarFileUri")
    response = wire if operation == "getSparkApplication" else {"applications": [wire], "nextPageToken": ""}
    transport = _Transport([httpx.Response(200, json=response)])
    client, service = _service(transport)

    def read() -> None:
        if operation == "getSparkApplication":
            service.get_spark_application("managed-1", "application-1")
        else:
            options = SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1")
            next(service.list_spark_applications(options).pages())

    with client, pytest.raises(DTOValidationError, match=operation):
        read()
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"applicationSpec": "unknown"},
        {"applicationSpec": "pysparkApplication"},
        {"sparkApplication": None},
        {"pysparkApplication": {}},
        {"applicationSpec": "missing"},
        {"finishedAt": "missing"},
        {"status": "FUTURE_STATUS"},
        {"id": ""},
        {"clusterId": ""},
        {"catalogs": [{"catalogId": ""}]},
        {"sparkApplication": {"mainJarFileUri": "missing"}},
        {"startedAt": "missing"},
        {"createdAt": None},
    ],
)
@pytest.mark.parametrize("operation", ["getSparkApplication", "listSparkApplications"])
def test_application_read_rejects_malformed_typed_response_with_rpc_context(
    change: dict[str, object], operation: str
) -> None:
    wire = _wire_application()
    for key, value in change.items():
        if key == "sparkApplication" and isinstance(value, dict):
            cast(dict[str, object], wire["sparkApplication"]).pop("mainJarFileUri")
        elif value == "missing":
            wire.pop(key)
        else:
            wire[key] = value
    response = (
        wire
        if operation == "getSparkApplication"
        else {"applications": [_wire_application(None), wire], "nextPageToken": ""}
    )
    transport = _Transport([httpx.Response(200, json=response)])
    client, service = _service(transport)

    def read() -> None:
        if operation == "getSparkApplication":
            service.get_spark_application("managed-1", "application-1")
        else:
            next(
                service.list_spark_applications(
                    SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1")
                ).pages()
            )

    with client, pytest.raises(DTOValidationError, match=operation):
        read()
    assert len(transport.requests) == 1


def test_application_read_preserves_zero_and_fractional_timestamp_nanos() -> None:
    zero = _wire_application(None)
    zero["createdAt"] = {"seconds": "0", "nanos": 0}
    fractional = _wire_application(None)
    fractional["createdAt"] = {"seconds": "0", "nanos": 1.25}
    transport = _Transport([httpx.Response(200, json=value) for value in (zero, fractional)])
    client, service = _service(transport)
    with client:
        first = service.get_spark_application("managed-1", "application-1")
        second = service.get_spark_application("managed-1", "application-1")

    assert first.created_at == LakehouseTimestamp("0", 0)
    assert type(first.created_at.nanos) is int
    assert second.created_at == LakehouseTimestamp("0", 1.25)
    assert type(second.created_at.nanos) is float


def test_application_list_is_lazy_repeatable_and_keeps_final_empty_token() -> None:
    first = {"applications": [_wire_application(None)], "nextPageToken": "B"}
    last = {"applications": [_wire_application("sparkConnectApplication")], "nextPageToken": ""}
    transport = _Transport([httpx.Response(200, json=page) for page in (first, last, first, last)])
    client, service = _service(transport)
    options = SparkApplicationListOptions.create(
        installation="yacloud", cluster=_cluster(), filters=['name="analytics"'], page_size=0, page_token="A"
    )
    expected_applications = [
        SparkApplication(
            id="application-1",
            cluster_id="managed-1",
            installation="yacloud",
            name="analytics",
            created_by="user-1",
            status="RUNNING",
            connect_url="",
            catalogs=(SparkApplicationCatalogRef("catalog-1"),),
            created_at=LakehouseTimestamp("123", 9007199254740993),
            started_at=None,
            finished_at=None,
            spec=None,
            raw=_wire_application(None),
        ),
        SparkApplication(
            id="application-1",
            cluster_id="managed-1",
            installation="yacloud",
            name="analytics",
            created_by="user-1",
            status="RUNNING",
            connect_url="",
            catalogs=(SparkApplicationCatalogRef("catalog-1"),),
            created_at=LakehouseTimestamp("123", 9007199254740993),
            started_at=None,
            finished_at=None,
            spec=SparkApplicationConnectSpec((), (), (), (), (), (), {}),
            raw=_wire_application("sparkConnectApplication"),
        ),
    ]
    with client:
        pager = service.list_spark_applications(options)
        assert transport.requests == []
        pages = list(pager.pages())
        assert [page.next_page_token for page in pages] == ["B", ""]
        assert [application for page in pages for application in page.items] == expected_applications
        assert list(pager) == expected_applications
    assert transport.bodies() == [
        {"clusterId": "lakehouse-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "A"},
        {"clusterId": "lakehouse-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "B"},
        {"clusterId": "lakehouse-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "A"},
        {"clusterId": "lakehouse-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "B"},
    ]


def test_application_list_sends_explicit_initial_empty_token() -> None:
    transport = _Transport([httpx.Response(200, json={"applications": [], "nextPageToken": ""})])
    client, service = _service(transport)
    options = SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1", page_token="")
    with client:
        pager = service.list_spark_applications(options)
        assert transport.requests == []
        assert [page.next_page_token for page in pager.pages()] == [""]
    assert transport.bodies() == [{"clusterId": "managed-1", "pageSize": 100, "pageToken": ""}]


@pytest.mark.parametrize("tokens", [["A"], ["B", "A"]])
def test_application_list_rejects_token_cycle_before_replaying_page(tokens: list[str]) -> None:
    transport = _Transport([httpx.Response(200, json={"applications": [], "nextPageToken": token}) for token in tokens])
    client, service = _service(transport)
    options = SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1", page_token="A")
    with client, pytest.raises(InvalidResponseError, match="listSparkApplications"):
        list(service.list_spark_applications(options).pages())
    assert transport.bodies() == [
        {"clusterId": "managed-1", "pageSize": 100, "pageToken": token} for token in ["A", *tokens[:-1]]
    ]


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        ({"nextPageToken": ""}, DTOValidationError),
        ({"applications": []}, DTOValidationError),
        ({"applications": "invalid", "nextPageToken": ""}, DTOValidationError),
        ({"applications": [], "nextPageToken": None}, DTOValidationError),
        ([], InvalidResponseError),
    ],
)
def test_application_list_rejects_malformed_page_root_with_rpc_context(
    response: object, error_type: type[Exception]
) -> None:
    transport = _Transport([httpx.Response(200, json=response)])
    client, service = _service(transport)
    with client, pytest.raises(error_type, match="listSparkApplications"):
        next(
            service.list_spark_applications(
                SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1")
            ).pages()
        )
    assert len(transport.requests) == 1


def test_application_get_and_each_list_page_retry_transient_http_failures() -> None:
    unavailable = httpx.Response(503, json={"code": "TEMPORARY", "message": "try later"})
    first = {"applications": [_wire_application(None)], "nextPageToken": "B"}
    last = {"applications": [], "nextPageToken": ""}
    transport = _Transport(
        [
            unavailable,
            httpx.Response(200, json=_wire_application(None)),
            unavailable,
            httpx.Response(200, json=first),
            unavailable,
            httpx.Response(200, json=last),
        ]
    )
    client, service = _service(transport)
    with client:
        assert service.get_spark_application("managed-1", "application-1").id == "application-1"
        assert [
            application.id
            for application in service.list_spark_applications(
                SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1")
            )
        ] == ["application-1"]
    assert [request.url.path for request in transport.requests] == [
        "/rpc/getSparkApplication",
        "/rpc/getSparkApplication",
        "/rpc/listSparkApplications",
        "/rpc/listSparkApplications",
        "/rpc/listSparkApplications",
        "/rpc/listSparkApplications",
    ]
    assert transport.bodies()[2:] == [
        {"clusterId": "managed-1", "pageSize": 100},
        {"clusterId": "managed-1", "pageSize": 100},
        {"clusterId": "managed-1", "pageSize": 100, "pageToken": "B"},
        {"clusterId": "managed-1", "pageSize": 100, "pageToken": "B"},
    ]


@pytest.mark.parametrize(
    ("cluster_id", "page_size", "filters", "page_token"),
    [
        ("managed-1", -1, (), None),
        ("managed-1", 1001, (), None),
        ("managed-1", 100, ('bad="x"',), None),
        ("managed-1", 100, ('name="unterminated',), None),
        ("managed-1", 100, ('name="' + "x" * 194 + '"',), None),
        ("managed-1", 100, ('name="x"',) * 101, None),
        ("managed-1", 100, (), "x" * 201),
        ("x" * 51, 100, (), None),
    ],
)
def test_application_list_request_constraints_fail_before_http(
    cluster_id: str, page_size: int, filters: tuple[str, ...], page_token: str | None
) -> None:
    transport = _Transport([])
    client, service = _service(transport)
    options = SparkApplicationListOptions.create(
        installation="yacloud", cluster=cluster_id, page_size=page_size, filters=filters, page_token=page_token
    )
    with client, pytest.raises(DTOValidationError, match="listSparkApplications"):
        list(service.list_spark_applications(options))
    assert transport.requests == []


def test_application_list_validates_unhashable_initial_token_before_http() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    options = SparkApplicationListOptions.create(
        installation="yacloud", cluster="managed-1", page_token=cast(str, ["resume"])
    )

    with client:
        pager = service.list_spark_applications(options)
        assert transport.requests == []
        with pytest.raises(DTOValidationError, match="listSparkApplications"):
            list(pager.pages())

    assert transport.requests == []


def test_application_get_rejects_overlong_application_id_before_http() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    with client, pytest.raises(DTOValidationError, match="getSparkApplication"):
        service.get_spark_application("managed-1", "x" * 51)
    assert transport.requests == []


def test_application_list_sends_maximum_allowed_request_values() -> None:
    transport = _Transport([httpx.Response(200, json={"applications": [], "nextPageToken": ""})])
    client, service = _service(transport)
    filters = ('name="x"',) * 100
    options = SparkApplicationListOptions.create(
        installation="yacloud", cluster="x" * 50, filters=filters, page_size=1000, page_token="x" * 200
    )
    with client:
        assert list(service.list_spark_applications(options)) == []
    assert transport.bodies() == [
        {"clusterId": "x" * 50, "filter": list(filters), "pageSize": 1000, "pageToken": "x" * 200}
    ]


def test_yc_application_actions_use_lakehouse_id_and_return_bound_models() -> None:
    transport = _Transport(
        [
            httpx.Response(200, json=_wire_application(cluster_id="lakehouse-1")),
            httpx.Response(200, json=_wire_application(cluster_id="lakehouse-1")),
            httpx.Response(
                200,
                json={"applications": [_wire_application(None, cluster_id="lakehouse-1")], "nextPageToken": ""},
            ),
        ]
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        application = client.get.spark_application(cluster=_cluster(), by_id="application-1")
        refreshed = application.refresh()
        pager = client.list.spark_applications(cluster=_cluster())
        assert len(transport.requests) == 2
        listed_application = next(iter(pager))
        assert listed_application.id == "application-1"
        assert listed_application.cluster_id == "lakehouse-1"
    assert application.cluster_id == "lakehouse-1"
    assert refreshed.cluster_id == "lakehouse-1"
    assert transport.bodies() == [
        {"clusterId": "lakehouse-1", "applicationId": "application-1"},
        {"clusterId": "lakehouse-1", "applicationId": "application-1"},
        {"clusterId": "lakehouse-1", "pageSize": 100},
    ]


def test_yc_application_actions_reject_unusable_inputs_before_http() -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        for cluster, application_id in ((_cluster(id=""), "application-1"), (_cluster(), "")):
            with pytest.raises(DataLensValidationError):
                client.get.spark_application(cluster=cluster, by_id=application_id)
        with pytest.raises(DataLensValidationError):
            client.list.spark_applications(cluster="managed-1", filters=cast(Sequence[str], "name=bad"))
    assert transport.requests == []


def test_foreign_client_never_accesses_spark_application_dtos(monkeypatch: pytest.MonkeyPatch) -> None:
    class DtoWithoutSparkApplications(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "SparkApplication" in name:
                raise AssertionError(f"Unexpected SparkApplications DTO access: {name}")
            return getattr(generated_dto, name)

    original_import = import_module
    dto_stub = DtoWithoutSparkApplications("datalens_sdk._generated.dto")
    monkeypatch.setattr(
        client_module,
        "import_module",
        lambda name: dto_stub if name == "datalens_sdk._generated.dto" else original_import(name),
    )

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("SparkApplications service initialized on a base client")

    monkeypatch.setattr(SparkApplicationService, "__init__", unexpected_service)
    transport = _Transport([])
    with DataLensClientEnterprise(
        auth=None,
        base_url="https://enterprise.test",
        transport=httpx.MockTransport(transport.handle),
    ) as client:
        for namespace, name in (
            (client.create, "spark_application"),
            (client.get, "spark_application"),
            (client.list, "spark_applications"),
        ):
            with pytest.raises(AttributeError) as exc:
                getattr(namespace, name)
            assert type(exc.value) is AttributeError

    class YaTeamStyleClient(DataLensClientBase):
        INSTALLATION = "yacloud"
        DEFAULT_BASE_URL = "https://yateam.test"

    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(transport.handle)) as base:
        for namespace, name in (
            (base.create, "spark_application"),
            (base.get, "spark_application"),
            (base.list, "spark_applications"),
        ):
            with pytest.raises(AttributeError) as exc:
                getattr(namespace, name)
            assert type(exc.value) is AttributeError
    assert transport.requests == []


def _catalog(
    *, catalog_id: str = "catalog-1", installation: str = "yacloud", environment: str = "environment-1"
) -> RestCatalog:
    return RestCatalog(
        id=catalog_id,
        installation=installation,
        organization_id="org-1",
        tenant_id="tenant-1",
        cloud_environment_id=environment,
        name="catalog",
        description="",
        created_by_id="user-1",
        bucket=RestCatalogBucket(RestCatalogBucketSettings("STANDARD", "1", "bucket", "")),
        labels={},
        permissions=None,
        created_at=None,
        updated_at=None,
        raw={},
    )


def _operation_wire() -> dict[str, object]:
    return {"id": "operation-1", "done": False, "metadata": {"opaque": "value"}}


def test_application_create_uses_lakehouse_id_and_validates_known_references() -> None:
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster=_cluster())
    assert builder.spark_connect().to_spec().cluster_id == "lakehouse-1"
    assert (
        spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="raw-lakehouse")
        .spark_connect()
        .to_spec()
        .cluster_id
        == "raw-lakehouse"
    )
    for cluster in ("", 42, _cluster(id=""), _cluster(installation="enterprise")):
        with pytest.raises(DataLensValidationError):
            spark_application_module.SparkApplicationCreate(
                installation="yacloud", cluster=cast(SparkCluster | str, cluster)
            )


def test_application_catalogs_validate_local_facts_without_raw_cluster_discovery() -> None:
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster=_cluster())
    builder.catalogs([_catalog(), "catalog-raw"])
    assert builder.spark_connect().to_spec().catalog_ids == ("catalog-1", "catalog-raw")
    original = builder.to_spec()
    for catalogs in (
        [_catalog(environment="other")],
        [_catalog(installation="enterprise")],
        [_catalog(), _catalog(installation="enterprise")],
        [_catalog(catalog_id="")],
        [""],
        [3],
        "catalog-1",
        b"catalog-1",
    ):
        with pytest.raises(DataLensValidationError):
            builder.catalogs(cast(Sequence[RestCatalog | str], catalogs))
        assert builder.to_spec() == original
    raw = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="raw-lakehouse")
    assert raw.catalogs([_catalog(environment="other")]).spark_connect().to_spec().catalog_ids == ("catalog-1",)


@pytest.mark.parametrize("first", ["spark", "pyspark", "spark_connect"])
@pytest.mark.parametrize("second", ["spark", "pyspark", "spark_connect"])
def test_application_builder_rejects_every_second_selector_without_changing_selection(first: str, second: str) -> None:
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1")

    def select(name: str) -> object:
        if name == "spark":
            return builder.spark(main_jar_file_uri="s3://bucket/main.jar")
        if name == "pyspark":
            return builder.pyspark(main_python_file_uri="s3://bucket/main.py")
        return builder.spark_connect()

    with pytest.raises(DataLensValidationError):
        builder.to_spec()
    select(first)
    valid = builder.to_spec()
    with pytest.raises(DataLensValidationError):
        select(second)
    assert builder.to_spec() == valid


def test_application_builder_snapshots_inputs_and_preserves_explicit_empty_values() -> None:
    args = ["first"]
    props = {"key": "before"}
    catalogs = ["catalog-1"]
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1", name="")
    builder.catalogs(catalogs).spark(
        main_jar_file_uri="s3://bucket/main.jar", args=args, properties=props, archive_uris=[]
    )
    before = builder.to_spec()
    args.append("later")
    props["key"] = "after"
    catalogs.append("catalog-2")
    assert before == builder.to_spec()
    assert before.catalog_ids == ("catalog-1",)
    assert isinstance(before.variant, SparkApplicationSparkCreateSpec)
    assert before.variant.args == ("first",)
    assert before.variant.properties == {"key": "before"}
    assert before.variant.archive_uris == ()
    assert builder.catalogs([]).to_spec().catalog_ids == ()
    assert (
        spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1")
        .spark_connect()
        .to_spec()
        .variant.properties
        is None
    )
    for invalid in ("one", b"one"):
        candidate = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1")
        with pytest.raises(DataLensValidationError):
            candidate.spark_connect(packages=cast(Sequence[str], invalid))
        candidate.spark_connect()


@pytest.mark.parametrize("selector", ["spark", "pyspark", "spark_connect"])
@pytest.mark.parametrize(
    "field",
    [
        "archive_uris",
        "file_uris",
        "jar_file_uris",
        "packages",
        "repositories",
        "exclude_packages",
    ],
)
@pytest.mark.parametrize("invalid", ["single", b"single"])
def test_application_builder_rejects_scalar_sequence_for_every_variant_field(
    selector: str, field: str, invalid: object
) -> None:
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1")
    kwargs: dict[str, object] = {field: invalid}

    def select() -> None:
        if selector == "spark":
            builder.spark(main_jar_file_uri="jar", **cast(Any, kwargs))
        elif selector == "pyspark":
            builder.pyspark(main_python_file_uri="python", **cast(Any, kwargs))
        else:
            builder.spark_connect(**cast(Any, kwargs))

    with pytest.raises(DataLensValidationError):
        select()
    builder.spark_connect()


@pytest.mark.parametrize(
    ("selector", "field"),
    [
        ("spark", "args"),
        ("pyspark", "args"),
        ("pyspark", "python_file_uris"),
    ],
)
@pytest.mark.parametrize("invalid", ["single", b"single"])
def test_application_builder_rejects_scalar_variant_sequence_without_selecting(
    selector: str, field: str, invalid: object
) -> None:
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1")
    kwargs: dict[str, object] = {field: invalid}

    def select() -> None:
        if selector == "spark":
            builder.spark(main_jar_file_uri="jar", **cast(Any, kwargs))
        else:
            builder.pyspark(main_python_file_uri="python", **cast(Any, kwargs))

    with pytest.raises(DataLensValidationError):
        select()
    builder.spark_connect()


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("spark", {"clusterId": "lakehouse-1", "sparkApplication": {"mainJarFileUri": "s3://bucket/main.jar"}}),
        ("pyspark", {"clusterId": "lakehouse-1", "pysparkApplication": {"mainPythonFileUri": "s3://bucket/main.py"}}),
        ("spark_connect", {"clusterId": "lakehouse-1", "sparkConnectApplication": {}}),
    ],
)
def test_application_create_serializes_three_variants_and_returns_bound_operation(
    selector: str, expected: dict[str, object]
) -> None:
    transport = _Transport([httpx.Response(200, json=_operation_wire()), httpx.Response(200, json=_operation_wire())])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster=_cluster())
        if selector == "spark":
            builder.spark(main_jar_file_uri="s3://bucket/main.jar")
        elif selector == "pyspark":
            builder.pyspark(main_python_file_uri="s3://bucket/main.py")
        else:
            builder.spark_connect()
        operation = builder.build()
        assert operation.id == "operation-1"
        assert operation.metadata == {"opaque": "value"}
        assert len(transport.requests) == 1
        refreshed = operation.refresh()
        assert refreshed.id == operation.id
        assert refreshed is not operation
    assert [request.url.path for request in transport.requests] == [
        "/rpc/createSparkApplication",
        "/rpc/getLakehouseOperation",
    ]
    assert transport.bodies() == [expected, {"operationId": "operation-1"}]


@pytest.mark.parametrize("status", ["RUNNING", "DONE", "CANCELLED", "CANCELLING"])
def test_application_cancel_posts_snapshot_ids_without_status_preflight(status: str) -> None:
    wire = _wire_application(None)
    wire["clusterId"] = "lakehouse-1"
    wire["status"] = status
    transport = _Transport(
        [
            httpx.Response(200, json=wire),
            httpx.Response(200, json=_operation_wire()),
            httpx.Response(200, json=_operation_wire()),
        ]
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        application = client.get.spark_application(cluster="lakehouse-1", by_id="application-1")
        operation = application.cancel()
        assert application.status == status
        assert operation.id == "operation-1"
        assert len(transport.requests) == 2
        refreshed = operation.refresh()
        assert refreshed.id == operation.id
        assert refreshed is not operation
    assert [request.url.path for request in transport.requests] == [
        "/rpc/getSparkApplication",
        "/rpc/cancelSparkApplication",
        "/rpc/getLakehouseOperation",
    ]
    assert transport.bodies()[1:] == [
        {"clusterId": "lakehouse-1", "applicationId": "application-1"},
        {"operationId": "operation-1"},
    ]


@pytest.mark.parametrize(
    ("selector", "key", "required"),
    [
        ("spark", "sparkApplication", {"mainJarFileUri": "s3://bucket/main.jar"}),
        ("pyspark", "pysparkApplication", {"mainPythonFileUri": "s3://bucket/main.py"}),
        ("spark_connect", "sparkConnectApplication", {}),
    ],
)
def test_application_create_preserves_all_variant_fields_and_explicit_empty_values(
    selector: str,
    key: str,
    required: dict[str, object],
) -> None:
    transport = _Transport([httpx.Response(200, json=_operation_wire())])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster=_cluster(), name="").catalogs([_catalog(), "catalog-raw"])
        common: dict[str, object] = {
            "archive_uris": ["archive"],
            "file_uris": ["file"],
            "jar_file_uris": ["jar"],
            "packages": ["package"],
            "repositories": ["repository"],
            "exclude_packages": ["exclude"],
            "properties": {"key": "value"},
        }
        if selector == "spark":
            builder.spark(main_jar_file_uri="s3://bucket/main.jar", main_class="", args=[], **cast(Any, common))
        elif selector == "pyspark":
            builder.pyspark(
                main_python_file_uri="s3://bucket/main.py", args=["arg"], python_file_uris=[], **cast(Any, common)
            )
        else:
            builder.spark_connect(**cast(Any, common))
        builder.build()
    nested = {
        **required,
        "archiveUris": ["archive"],
        "fileUris": ["file"],
        "jarFileUris": ["jar"],
        "packages": ["package"],
        "repositories": ["repository"],
        "excludePackages": ["exclude"],
        "properties": {"key": "value"},
    }
    if selector == "spark":
        nested.update(mainClass="", args=[])
    elif selector == "pyspark":
        nested.update(args=["arg"], pythonFileUris=[])
    assert transport.bodies() == [
        {
            "clusterId": "lakehouse-1",
            "name": "",
            "catalogs": [{"catalogId": "catalog-1"}, {"catalogId": "catalog-raw"}],
            key: nested,
        }
    ]


def test_application_create_sends_explicit_empty_catalogs_arrays_and_properties() -> None:
    transport = _Transport([httpx.Response(200, json=_operation_wire())])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        client.create.spark_application(cluster="lakehouse-1", name="").catalogs([]).spark_connect(
            archive_uris=[],
            properties={},
        ).build()
    assert transport.bodies() == [
        {
            "clusterId": "lakehouse-1",
            "name": "",
            "catalogs": [],
            "sparkConnectApplication": {"archiveUris": [], "properties": {}},
        }
    ]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("name", "Bad_name"),
        ("name", "x" * 256),
        ("cluster", "x" * 51),
        ("catalog_id", "x" * 51),
        ("main_jar_file_uri", ""),
        ("main_jar_file_uri", "x" * 2048),
        ("main_class", "x" * 256),
        ("args", ["x" * 2048]),
        ("args", ["x"] * 101),
        ("packages", ["x" * 256]),
        ("exclude_packages", ["x" * 256]),
        ("archive_uris", ["x" * 2048]),
        ("file_uris", ["x"] * 101),
        ("repositories", ["x"] * 11),
        ("properties", {"key": "x" * 257}),
        ("args", [1]),
        ("properties", {"key": 1}),
    ],
)
def test_application_create_generated_constraints_fail_before_http_with_rpc_context(name: str, value: object) -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        cluster = cast(str, value) if name == "cluster" else "lakehouse-1"
        builder = client.create.spark_application(cluster=cluster, name=cast(str, value) if name == "name" else None)
        kwargs: dict[str, object] = {"main_jar_file_uri": "s3://bucket/main.jar"}
        if name == "catalog_id":
            builder.catalogs([cast(str, value)])
        elif name not in {"cluster", "name"}:
            kwargs[name] = value
        builder.spark(**cast(Any, kwargs))
        with pytest.raises(DTOValidationError, match="createSparkApplication"):
            builder.build()
    assert transport.requests == []


@pytest.mark.parametrize("main_python_file_uri", ["", "x" * 2048])
def test_application_create_pyspark_rejects_out_of_bounds_main_file_before_http(main_python_file_uri: str) -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster="lakehouse-1").pyspark(
            main_python_file_uri=main_python_file_uri
        )
        with pytest.raises(DTOValidationError, match="createSparkApplication"):
            builder.build()
    assert transport.requests == []


@pytest.mark.parametrize("selector", ["spark", "pyspark", "spark_connect"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("archive_uris", ["x"] * 101),
        ("jar_file_uris", ["x" * 2048]),
        ("repositories", ["x"] * 11),
        ("properties", {"key": "x" * 257}),
        ("packages", [1]),
    ],
)
def test_application_create_all_variants_apply_generated_common_constraints(
    selector: str,
    field: str,
    value: object,
) -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster="lakehouse-1")
        kwargs: dict[str, object] = {field: value}
        if selector == "spark":
            builder.spark(main_jar_file_uri="jar", **cast(Any, kwargs))
        elif selector == "pyspark":
            builder.pyspark(main_python_file_uri="python", **cast(Any, kwargs))
        else:
            builder.spark_connect(**cast(Any, kwargs))
        with pytest.raises(DTOValidationError, match="createSparkApplication"):
            builder.build()
    assert transport.requests == []


_SPARK_APPLICATION_BOUNDED_ARRAY_LIMITS = (
    *(
        (selector, field, max_items)
        for selector in ("spark", "pyspark", "spark_connect")
        for field, max_items in (
            ("archive_uris", 100),
            ("file_uris", 100),
            ("jar_file_uris", 100),
            ("packages", 100),
            ("repositories", 10),
            ("exclude_packages", 100),
        )
    ),
    ("spark", "args", 100),
    ("pyspark", "args", 100),
    ("pyspark", "python_file_uris", 100),
)


@pytest.mark.parametrize(
    ("selector", "field", "max_items"),
    [(selector, field, max_items) for selector, field, max_items in _SPARK_APPLICATION_BOUNDED_ARRAY_LIMITS],
)
def test_application_create_rejects_over_limit_array_for_each_variant_schema(
    selector: str,
    field: str,
    max_items: int,
) -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster="lakehouse-1")
        kwargs = {field: ["item"] * (max_items + 1)}
        if selector == "spark":
            builder.spark(main_jar_file_uri="jar", **cast(Any, kwargs))
        elif selector == "pyspark":
            builder.pyspark(main_python_file_uri="python", **cast(Any, kwargs))
        else:
            builder.spark_connect(**cast(Any, kwargs))
        with pytest.raises(DTOValidationError, match="createSparkApplication"):
            builder.build()
    assert transport.requests == []


@pytest.mark.parametrize(
    ("selector", "field", "max_items"),
    _SPARK_APPLICATION_BOUNDED_ARRAY_LIMITS,
)
def test_application_create_accepts_array_at_generated_limit_for_each_variant_schema(
    selector: str,
    field: str,
    max_items: int,
) -> None:
    transport = _Transport([httpx.Response(200, json=_operation_wire())])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster="lakehouse-1")
        kwargs = {field: ["item"] * max_items}
        if selector == "spark":
            builder.spark(main_jar_file_uri="jar", **cast(Any, kwargs))
        elif selector == "pyspark":
            builder.pyspark(main_python_file_uri="python", **cast(Any, kwargs))
        else:
            builder.spark_connect(**cast(Any, kwargs))
        assert builder.build().id == "operation-1"
    assert len(transport.requests) == 1


@pytest.mark.parametrize("selector", ["spark", "pyspark", "spark_connect"])
def test_application_create_accepts_inclusive_generated_boundaries_and_empty_optional_uri(selector: str) -> None:
    transport = _Transport([httpx.Response(200, json=_operation_wire())])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        builder = client.create.spark_application(cluster="c" * 50, name="a" + "x" * 61 + "z").catalogs(["d" * 50])
        common: dict[str, object] = {
            "archive_uris": [""],
            "file_uris": ["x" * 2047] * 100,
            "packages": ["p" * 255],
            "repositories": ["r" * 2047] * 10,
            "properties": {"key": "v" * 256},
        }
        if selector == "spark":
            builder.spark(main_jar_file_uri="j" * 2047, main_class="M" * 255, **cast(Any, common))
        elif selector == "pyspark":
            builder.pyspark(main_python_file_uri="p" * 2047, python_file_uris=[""], **cast(Any, common))
        else:
            builder.spark_connect(**cast(Any, common))
        assert builder.build().id == "operation-1"
    assert len(transport.requests) == 1


@pytest.mark.parametrize("field", ["cluster_id", "application_id"])
def test_application_cancel_generated_id_constraints_prevent_transport(field: str) -> None:
    transport = _Transport([])
    client, service = _service(transport)
    ids = {"cluster_id": "lakehouse-1", "application_id": "application-1"}
    ids[field] = "x" * 51
    with client, pytest.raises(DTOValidationError, match="cancelSparkApplication"):
        service.cancel_spark_application(ids["cluster_id"], ids["application_id"])
    assert transport.requests == []


def test_application_cancel_and_create_require_binding_and_completed_intent() -> None:
    builder = spark_application_module.SparkApplicationCreate(installation="yacloud", cluster="lakehouse-1")
    with pytest.raises(DataLensValidationError):
        builder.build()
    with pytest.raises(DataLensConfigurationError):
        builder.spark_connect().build()
    unbound = SparkApplication(
        id="application-1",
        cluster_id="lakehouse-1",
        installation="yacloud",
        name="application",
        created_by="user",
        status="DONE",
        connect_url="",
        catalogs=(),
        created_at=LakehouseTimestamp("1"),
        started_at=None,
        finished_at=None,
        spec=None,
        raw={},
    )
    with pytest.raises(DataLensConfigurationError):
        unbound.cancel()
    for invalid in (replace(unbound, id=""), replace(unbound, cluster_id="")):
        with pytest.raises(DataLensValidationError):
            invalid.cancel()


@pytest.mark.parametrize("mutation", ["create", "cancel"])
def test_application_mutations_preserve_terminal_operation_errors_and_unknown_data(mutation: str) -> None:
    wire: dict[str, object] = {
        "id": "operation-1",
        "done": True,
        "metadata": {"future": {"applicationId": "not-a-snapshot"}},
        "error": {"code": 0, "message": "", "details": [], "futureError": "preserved"},
        "response": {},
        "createdAt": {"seconds": "0", "nanos": 0},
        "modifiedAt": {"seconds": "1", "nanos": 0.5},
        "futureOperation": True,
    }
    transport = _Transport([httpx.Response(200, json=wire)])
    http_client, service = _service(transport)
    with http_client:
        operation = (
            spark_application_module.SparkApplicationCreate(
                installation="yacloud",
                cluster="lakehouse-1",
                operations=service,
            )
            .spark_connect()
            .build()
            if mutation == "create"
            else service.cancel_spark_application("lakehouse-1", "application-1")
        )
    assert operation == LakehouseOperation(
        id="operation-1",
        done=True,
        metadata={"future": {"applicationId": "not-a-snapshot"}},
        created_at=LakehouseTimestamp("0", 0),
        modified_at=LakehouseTimestamp("1", 0.5),
        error=LakehouseOperationError(0, "", ()),
        response={},
        raw=wire,
    )
    assert len(transport.requests) == 1


def _invoke_mutation(service: SparkApplicationService, mutation: str) -> LakehouseOperation:
    if mutation == "create":
        return (
            spark_application_module.SparkApplicationCreate(
                installation="yacloud",
                cluster="lakehouse-1",
                operations=service,
            )
            .spark_connect()
            .build()
        )
    return service.cancel_spark_application("lakehouse-1", "application-1")


@pytest.mark.parametrize("mutation", ["create", "cancel"])
@pytest.mark.parametrize("failure", ["server", "transport"])
def test_application_mutations_never_retry_transient_failures(mutation: str, failure: str) -> None:
    response: httpx.Response | Exception = (
        httpx.ConnectError("connection lost")
        if failure == "transport"
        else httpx.Response(
            503, json={"code": "SPARK_FAILED", "message": "temporary"}, headers={"x-request-id": "req-1"}
        )
    )
    transport = _Transport([response])
    http_client, service = _service(transport)
    expected_error = DataLensTransportError if failure == "transport" else DataLensAPIError
    with http_client, pytest.raises(expected_error) as caught:
        _invoke_mutation(service, mutation)
    assert len(transport.requests) == 1
    assert transport.requests[0].url.path == f"/rpc/{mutation}SparkApplication"
    if failure == "server":
        assert isinstance(caught.value, DataLensAPIError)
        assert caught.value.context.code == "SPARK_FAILED"
        assert caught.value.context.request_id == "req-1"


@pytest.mark.parametrize("mutation", ["create", "cancel"])
@pytest.mark.parametrize(
    "wire",
    [
        {"done": False, "metadata": {}},
        {"id": "operation-1", "done": False},
        {"id": "operation-1", "done": False, "metadata": {}, "createdAt": {"seconds": 1}},
        {"id": "operation-1", "done": True, "metadata": {}, "error": {"code": "bad", "message": "oops"}},
        ["not-an-operation"],
    ],
)
def test_application_mutations_report_malformed_operations_with_original_rpc(mutation: str, wire: object) -> None:
    transport = _Transport([httpx.Response(200, json=wire)])
    http_client, service = _service(transport)
    with http_client, pytest.raises((DTOValidationError, InvalidResponseError), match=f"{mutation}SparkApplication"):
        _invoke_mutation(service, mutation)
    assert len(transport.requests) == 1
