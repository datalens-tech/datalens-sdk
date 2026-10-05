from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from importlib import import_module
import json
from types import ModuleType
from typing import cast

import httpx
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.spark_application import SparkApplicationAPI, SparkApplicationService
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.ports import SparkApplicationOperations
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
from datalens_sdk.errors import (
    DataLensConfigurationError,
    DataLensValidationError,
    DTOValidationError,
    InvalidResponseError,
)
from datalens_sdk.http import DataLensHTTPClient


def _cluster(*, cluster_id: str = "managed-1", installation: str = "yacloud") -> SparkCluster:
    pool = SparkResourcePoolConfig(resource_preset_id="preset-1", scale_policy=SparkFixedScalePolicy(size=1))
    return SparkCluster(
        id="entry-1",
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
        entry_id="entry-1",
        raw={},
    )


def test_application_cluster_reference_uses_managed_id_and_rejects_known_mismatches() -> None:
    assert normalize_spark_application_cluster(_cluster(), installation="yacloud") == "managed-1"
    assert normalize_spark_application_cluster("raw-managed", installation="yacloud") == "raw-managed"
    for value in ("", _cluster(cluster_id=""), _cluster(installation="enterprise"), _cluster(installation=""), 42):
        with pytest.raises(DataLensValidationError):
            normalize_spark_application_cluster(value, installation="yacloud")  # type: ignore[arg-type]


def test_application_list_options_snapshot_filters_and_preserve_explicit_pagination() -> None:
    filters = ['name="first"', 'created_by="second"']
    options = SparkApplicationListOptions.create(
        installation="yacloud", cluster=_cluster(), filters=filters, page_size=0, page_token=""
    )
    filters.append('job_type="sparkApplication"')

    assert options == SparkApplicationListOptions("managed-1", ('name="first"', 'created_by="second"'), 0, "")
    assert SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1").page_token is None
    for invalid in ('name="x"', b'name="x"'):
        with pytest.raises(DataLensValidationError):
            SparkApplicationListOptions.create(installation="yacloud", cluster="managed-1", filters=invalid)  # type: ignore[arg-type]


def test_application_refresh_requires_binding_and_uses_held_managed_ids_without_mutation() -> None:
    application = SparkApplication(
        id="application-1",
        cluster_id="managed-1",
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
    assert operations.calls == [("managed-1", "application-1")]
    for invalid in (replace(bound, id=""), replace(bound, cluster_id="")):
        with pytest.raises(DataLensValidationError):
            invalid.refresh()
    assert operations.calls == [("managed-1", "application-1")]


def _wire_application(kind: str | None = "sparkApplication") -> dict[str, object]:
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
        "clusterId": "managed-1",
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
    def __init__(self, responses: Sequence[httpx.Response]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, f"unexpected request: {request.url.path}"
        return self.responses.pop(0)

    def bodies(self) -> list[dict[str, object]]:
        return [cast(dict[str, object], json.loads(request.content)) for request in self.requests]


def _service(transport: _Transport) -> tuple[DataLensHTTPClient, SparkApplicationService]:
    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://spark.test",
        transport=httpx.MockTransport(transport.handle),
    )
    return client, SparkApplicationService(installation="yacloud", api=SparkApplicationAPI(client))


@pytest.mark.parametrize("kind", ["sparkApplication", "pysparkApplication", "sparkConnectApplication", None])
def test_application_get_maps_typed_and_common_only_specs_preserving_raw(kind: str | None) -> None:
    wire = _wire_application(kind)
    transport = _Transport([httpx.Response(200, json=wire), httpx.Response(200, json=wire)])
    client, service = _service(transport)
    with client:
        application = service.get_spark_application("managed-1", "application-1")
        refreshed = application.refresh()

    expected_spec = {
        "sparkApplication": SparkApplicationSparkSpec("s3://application.jar", "Main", (), (), (), (), (), (), (), {}),
        "pysparkApplication": SparkApplicationPySparkSpec("s3://application.py", (), (), (), (), (), (), (), (), {}),
        "sparkConnectApplication": SparkApplicationConnectSpec((), (), (), (), (), (), {}),
        None: None,
    }[kind]
    expected = SparkApplication(
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
        spec=expected_spec,
        raw=wire,
    )
    assert application == expected
    assert refreshed == expected
    assert refreshed is not application
    assert type(application.created_at.nanos) is int
    assert transport.bodies() == [
        {"clusterId": "managed-1", "applicationId": "application-1"},
        {"clusterId": "managed-1", "applicationId": "application-1"},
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
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "A"},
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "B"},
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "A"},
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "B"},
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


def test_yc_application_actions_use_managed_cluster_id_and_return_bound_models() -> None:
    transport = _Transport(
        [
            httpx.Response(200, json=_wire_application()),
            httpx.Response(200, json={"applications": [_wire_application(None)], "nextPageToken": ""}),
        ]
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        application = client.get.spark_application(cluster=_cluster(), by_id="application-1")
        pager = client.list.spark_applications(cluster=_cluster())
        assert len(transport.requests) == 1
        assert next(iter(pager)).id == "application-1"
    assert application.cluster_id == "managed-1"
    assert transport.bodies() == [
        {"clusterId": "managed-1", "applicationId": "application-1"},
        {"clusterId": "managed-1", "pageSize": 100},
    ]


def test_yc_application_actions_reject_unusable_inputs_before_http() -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        for cluster, application_id in ((_cluster(cluster_id=""), "application-1"), (_cluster(), "")):
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
        for namespace, name in ((client.get, "spark_application"), (client.list, "spark_applications")):
            with pytest.raises(AttributeError) as exc:
                getattr(namespace, name)
            assert type(exc.value) is AttributeError

    class YaTeamStyleClient(DataLensClientBase):
        INSTALLATION = "yacloud"
        DEFAULT_BASE_URL = "https://yateam.test"

    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(transport.handle)) as base:
        for namespace, name in ((base.get, "spark_application"), (base.list, "spark_applications")):
            with pytest.raises(AttributeError) as exc:
                getattr(namespace, name)
            assert type(exc.value) is AttributeError
    assert transport.requests == []
