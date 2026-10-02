from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from importlib import import_module
import json
from types import ModuleType
from typing import cast

import httpx
from pydantic import TypeAdapter
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.spark_job import SparkJobAPI, SparkJobService
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.converter.spark_job import SparkJobConverter
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.ports import SparkJobOperations
from datalens_sdk.domain.spark_cluster import (
    SparkCluster,
    SparkClusterConfig,
    SparkClusterDependencies,
    SparkFixedScalePolicy,
    SparkResourcePoolConfig,
    SparkResourcePoolsConfig,
)
from datalens_sdk.domain.spark_job import (
    SparkJob,
    SparkJobCatalogRef,
    SparkJobConnectSpec,
    SparkJobListOptions,
    SparkJobPySparkSpec,
    SparkJobSparkSpec,
    normalize_spark_job_cluster,
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


def test_job_cluster_reference_uses_managed_id_and_rejects_known_mismatches() -> None:
    assert normalize_spark_job_cluster(_cluster(), installation="yacloud") == "managed-1"
    assert normalize_spark_job_cluster("raw-managed", installation="yacloud") == "raw-managed"
    for value in ("", _cluster(cluster_id=""), _cluster(installation="enterprise"), _cluster(installation=""), 42):
        with pytest.raises(DataLensValidationError):
            normalize_spark_job_cluster(value, installation="yacloud")  # type: ignore[arg-type]


def test_job_list_options_snapshot_filters_and_preserve_explicit_pagination() -> None:
    filters = ['name="first"', 'created_by="second"']
    options = SparkJobListOptions.create(
        installation="yacloud", cluster=_cluster(), filters=filters, page_size=0, page_token=""
    )
    filters.append('job_type="sparkJob"')

    assert options == SparkJobListOptions("managed-1", ('name="first"', 'created_by="second"'), 0, "")
    assert SparkJobListOptions.create(installation="yacloud", cluster="managed-1").page_token is None
    for invalid in ('name="x"', b'name="x"'):
        with pytest.raises(DataLensValidationError):
            SparkJobListOptions.create(installation="yacloud", cluster="managed-1", filters=invalid)  # type: ignore[arg-type]


def test_job_refresh_requires_binding_and_uses_held_managed_ids_without_mutation() -> None:
    job = SparkJob(
        id="job-1",
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
        job.refresh()

    class FakeOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def get_spark_job(self, cluster_id: str, job_id: str) -> SparkJob:
            self.calls.append((cluster_id, job_id))
            return replace(job, name="after")

    operations = FakeOperations()
    bound = replace(job, _operations=cast(SparkJobOperations, operations))
    assert bound.refresh() == replace(job, name="after")
    assert bound.name == "before"
    assert operations.calls == [("managed-1", "job-1")]
    for invalid in (replace(bound, id=""), replace(bound, cluster_id="")):
        with pytest.raises(DataLensValidationError):
            invalid.refresh()
    assert operations.calls == [("managed-1", "job-1")]


def _wire_job(kind: str | None = "sparkJob") -> dict[str, object]:
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
        "id": "job-1",
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
    if kind == "sparkJob":
        result.update(
            jobSpec=kind,
            sparkJob={**common, "args": [], "mainJarFileUri": "s3://job.jar", "mainClass": "Main", "futureSpec": 3},
        )
    elif kind == "pysparkJob":
        result.update(
            jobSpec=kind, pysparkJob={**common, "args": [], "mainPythonFileUri": "s3://job.py", "pythonFileUris": []}
        )
    elif kind == "sparkConnectJob":
        result.update(jobSpec=kind, sparkConnectJob=common)
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


def _service(transport: _Transport) -> tuple[DataLensHTTPClient, SparkJobService]:
    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://spark.test",
        transport=httpx.MockTransport(transport.handle),
    )
    return client, SparkJobService(installation="yacloud", api=SparkJobAPI(client))


@pytest.mark.parametrize("kind", ["sparkJob", "pysparkJob", "sparkConnectJob", None])
def test_job_get_maps_typed_and_common_only_specs_preserving_raw(kind: str | None) -> None:
    wire = _wire_job(kind)
    transport = _Transport([httpx.Response(200, json=wire), httpx.Response(200, json=wire)])
    client, service = _service(transport)
    with client:
        job = service.get_spark_job("managed-1", "job-1")
        refreshed = job.refresh()

    expected_spec = {
        "sparkJob": SparkJobSparkSpec("s3://job.jar", "Main", (), (), (), (), (), (), (), {}),
        "pysparkJob": SparkJobPySparkSpec("s3://job.py", (), (), (), (), (), (), (), (), {}),
        "sparkConnectJob": SparkJobConnectSpec((), (), (), (), (), (), {}),
        None: None,
    }[kind]
    expected = SparkJob(
        id="job-1",
        cluster_id="managed-1",
        installation="yacloud",
        name="analytics",
        created_by="user-1",
        status="RUNNING",
        connect_url="",
        catalogs=(SparkJobCatalogRef("catalog-1"),),
        created_at=LakehouseTimestamp("123", 9007199254740993),
        started_at=None,
        finished_at=None,
        spec=expected_spec,
        raw=wire,
    )
    assert job == expected
    assert refreshed == expected
    assert refreshed is not job
    assert type(job.created_at.nanos) is int
    assert transport.bodies() == [
        {"clusterId": "managed-1", "jobId": "job-1"},
        {"clusterId": "managed-1", "jobId": "job-1"},
    ]


@pytest.mark.parametrize("operation", ["getSparkJob", "listSparkJobs"])
def test_job_read_rejects_python_field_name_instead_of_nested_wire_alias(operation: str) -> None:
    wire = _wire_job("sparkJob")
    spark_spec = cast(dict[str, object], wire["sparkJob"])
    spark_spec["main_jar_file_uri"] = spark_spec.pop("mainJarFileUri")
    response = wire if operation == "getSparkJob" else {"jobs": [wire], "nextPageToken": ""}
    transport = _Transport([httpx.Response(200, json=response)])
    client, service = _service(transport)

    def read() -> None:
        if operation == "getSparkJob":
            service.get_spark_job("managed-1", "job-1")
        else:
            options = SparkJobListOptions.create(installation="yacloud", cluster="managed-1")
            next(service.list_spark_jobs(options).pages())

    with client, pytest.raises(DTOValidationError, match=operation):
        read()
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"jobSpec": "unknown"},
        {"jobSpec": "pysparkJob"},
        {"sparkJob": None},
        {"pysparkJob": {}},
        {"jobSpec": "missing"},
        {"finishedAt": "missing"},
        {"status": "FUTURE_STATUS"},
        {"id": ""},
        {"clusterId": ""},
        {"catalogs": [{"catalogId": ""}]},
        {"sparkJob": {"mainJarFileUri": "missing"}},
        {"startedAt": "missing"},
        {"createdAt": None},
    ],
)
@pytest.mark.parametrize("operation", ["getSparkJob", "listSparkJobs"])
def test_job_read_rejects_malformed_typed_response_with_rpc_context(change: dict[str, object], operation: str) -> None:
    wire = _wire_job()
    for key, value in change.items():
        if key == "sparkJob" and isinstance(value, dict):
            cast(dict[str, object], wire["sparkJob"]).pop("mainJarFileUri")
        elif value == "missing":
            wire.pop(key)
        else:
            wire[key] = value
    response = wire if operation == "getSparkJob" else {"jobs": [_wire_job(None), wire], "nextPageToken": ""}
    transport = _Transport([httpx.Response(200, json=response)])
    client, service = _service(transport)

    def read() -> None:
        if operation == "getSparkJob":
            service.get_spark_job("managed-1", "job-1")
        else:
            next(
                service.list_spark_jobs(SparkJobListOptions.create(installation="yacloud", cluster="managed-1")).pages()
            )

    with client, pytest.raises(DTOValidationError, match=operation):
        read()
    assert len(transport.requests) == 1


def test_job_read_preserves_zero_and_fractional_timestamp_nanos() -> None:
    zero = _wire_job(None)
    zero["createdAt"] = {"seconds": "0", "nanos": 0}
    fractional = _wire_job(None)
    fractional["createdAt"] = {"seconds": "0", "nanos": 1.25}
    transport = _Transport([httpx.Response(200, json=value) for value in (zero, fractional)])
    client, service = _service(transport)
    with client:
        first = service.get_spark_job("managed-1", "job-1")
        second = service.get_spark_job("managed-1", "job-1")

    assert first.created_at == LakehouseTimestamp("0", 0)
    assert type(first.created_at.nanos) is int
    assert second.created_at == LakehouseTimestamp("0", 1.25)
    assert type(second.created_at.nanos) is float


def test_job_list_uses_page_validated_items_without_revalidating_union(monkeypatch: pytest.MonkeyPatch) -> None:
    validate_python = TypeAdapter.validate_python
    item_validations = 0

    def count_item_validation(adapter: object, value: object, **kwargs: object) -> object:
        nonlocal item_validations
        item_validations += 1
        return validate_python(adapter, value, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(TypeAdapter, "validate_python", count_item_validation)
    jobs = [_wire_job(None), _wire_job("sparkJob")]
    page = SparkJobConverter.to_page({"jobs": jobs, "nextPageToken": ""}, installation="yacloud", operations=None)

    assert [job.raw for job in page.items] == jobs
    assert item_validations == 0


def test_job_list_is_lazy_repeatable_and_keeps_final_empty_token() -> None:
    first = {"jobs": [_wire_job(None)], "nextPageToken": "B"}
    last = {"jobs": [_wire_job("sparkConnectJob")], "nextPageToken": ""}
    transport = _Transport([httpx.Response(200, json=page) for page in (first, last, first, last)])
    client, service = _service(transport)
    options = SparkJobListOptions.create(
        installation="yacloud", cluster=_cluster(), filters=['name="analytics"'], page_size=0, page_token="A"
    )
    with client:
        pager = service.list_spark_jobs(options)
        assert transport.requests == []
        assert [page.next_page_token for page in pager.pages()] == ["B", ""]
        assert [job.id for job in pager] == ["job-1", "job-1"]
    assert transport.bodies() == [
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "A"},
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "B"},
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "A"},
        {"clusterId": "managed-1", "filter": ['name="analytics"'], "pageSize": 0, "pageToken": "B"},
    ]


def test_job_list_sends_explicit_initial_empty_token() -> None:
    transport = _Transport([httpx.Response(200, json={"jobs": [], "nextPageToken": ""})])
    client, service = _service(transport)
    options = SparkJobListOptions.create(installation="yacloud", cluster="managed-1", page_token="")
    with client:
        pager = service.list_spark_jobs(options)
        assert transport.requests == []
        assert [page.next_page_token for page in pager.pages()] == [""]
    assert transport.bodies() == [{"clusterId": "managed-1", "pageSize": 100, "pageToken": ""}]


@pytest.mark.parametrize("tokens", [["A"], ["B", "A"]])
def test_job_list_rejects_token_cycle_before_replaying_page(tokens: list[str]) -> None:
    transport = _Transport([httpx.Response(200, json={"jobs": [], "nextPageToken": token}) for token in tokens])
    client, service = _service(transport)
    options = SparkJobListOptions.create(installation="yacloud", cluster="managed-1", page_token="A")
    with client, pytest.raises(InvalidResponseError, match="listSparkJobs"):
        list(service.list_spark_jobs(options).pages())
    assert transport.bodies() == [
        {"clusterId": "managed-1", "pageSize": 100, "pageToken": token} for token in ["A", *tokens[:-1]]
    ]


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        ({"nextPageToken": ""}, DTOValidationError),
        ({"jobs": []}, DTOValidationError),
        ({"jobs": "invalid", "nextPageToken": ""}, DTOValidationError),
        ({"jobs": [], "nextPageToken": None}, DTOValidationError),
        ([], InvalidResponseError),
    ],
)
def test_job_list_rejects_malformed_page_root_with_rpc_context(response: object, error_type: type[Exception]) -> None:
    transport = _Transport([httpx.Response(200, json=response)])
    client, service = _service(transport)
    with client, pytest.raises(error_type, match="listSparkJobs"):
        next(service.list_spark_jobs(SparkJobListOptions.create(installation="yacloud", cluster="managed-1")).pages())
    assert len(transport.requests) == 1


def test_job_get_and_each_list_page_retry_transient_http_failures() -> None:
    unavailable = httpx.Response(503, json={"code": "TEMPORARY", "message": "try later"})
    first = {"jobs": [_wire_job(None)], "nextPageToken": "B"}
    last = {"jobs": [], "nextPageToken": ""}
    transport = _Transport(
        [
            unavailable,
            httpx.Response(200, json=_wire_job(None)),
            unavailable,
            httpx.Response(200, json=first),
            unavailable,
            httpx.Response(200, json=last),
        ]
    )
    client, service = _service(transport)
    with client:
        assert service.get_spark_job("managed-1", "job-1").id == "job-1"
        assert [
            job.id
            for job in service.list_spark_jobs(SparkJobListOptions.create(installation="yacloud", cluster="managed-1"))
        ] == ["job-1"]
    assert [request.url.path for request in transport.requests] == [
        "/rpc/getSparkJob",
        "/rpc/getSparkJob",
        "/rpc/listSparkJobs",
        "/rpc/listSparkJobs",
        "/rpc/listSparkJobs",
        "/rpc/listSparkJobs",
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
def test_job_list_request_constraints_fail_before_http(
    cluster_id: str, page_size: int, filters: tuple[str, ...], page_token: str | None
) -> None:
    transport = _Transport([])
    client, service = _service(transport)
    options = SparkJobListOptions.create(
        installation="yacloud", cluster=cluster_id, page_size=page_size, filters=filters, page_token=page_token
    )
    with client, pytest.raises(DTOValidationError, match="listSparkJobs"):
        list(service.list_spark_jobs(options))
    assert transport.requests == []


def test_job_list_validates_unhashable_initial_token_before_http() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    options = SparkJobListOptions.create(installation="yacloud", cluster="managed-1", page_token=cast(str, ["resume"]))

    with client:
        pager = service.list_spark_jobs(options)
        assert transport.requests == []
        with pytest.raises(DTOValidationError, match="listSparkJobs"):
            list(pager.pages())

    assert transport.requests == []


def test_job_get_rejects_overlong_job_id_before_http() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    with client, pytest.raises(DTOValidationError, match="getSparkJob"):
        service.get_spark_job("managed-1", "x" * 51)
    assert transport.requests == []


def test_job_list_sends_maximum_allowed_request_values() -> None:
    transport = _Transport([httpx.Response(200, json={"jobs": [], "nextPageToken": ""})])
    client, service = _service(transport)
    filters = ('name="x"',) * 100
    options = SparkJobListOptions.create(
        installation="yacloud", cluster="x" * 50, filters=filters, page_size=1000, page_token="x" * 200
    )
    with client:
        assert list(service.list_spark_jobs(options)) == []
    assert transport.bodies() == [
        {"clusterId": "x" * 50, "filter": list(filters), "pageSize": 1000, "pageToken": "x" * 200}
    ]


def test_yc_job_actions_use_managed_cluster_id_and_return_bound_models() -> None:
    transport = _Transport(
        [
            httpx.Response(200, json=_wire_job()),
            httpx.Response(200, json={"jobs": [_wire_job(None)], "nextPageToken": ""}),
        ]
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        job = client.get.spark_job(cluster=_cluster(), by_id="job-1")
        pager = client.list.spark_jobs(cluster=_cluster())
        assert len(transport.requests) == 1
        assert next(iter(pager)).id == "job-1"
    assert job.cluster_id == "managed-1"
    assert transport.bodies() == [
        {"clusterId": "managed-1", "jobId": "job-1"},
        {"clusterId": "managed-1", "pageSize": 100},
    ]


def test_yc_job_actions_reject_unusable_inputs_before_http() -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        for cluster, job_id in ((_cluster(cluster_id=""), "job-1"), (_cluster(), "")):
            with pytest.raises(DataLensValidationError):
                client.get.spark_job(cluster=cluster, by_id=job_id)
        with pytest.raises(DataLensValidationError):
            client.list.spark_jobs(cluster="managed-1", filters=cast(Sequence[str], "name=bad"))
    assert transport.requests == []


def test_foreign_client_never_accesses_spark_job_dtos(monkeypatch: pytest.MonkeyPatch) -> None:
    class DtoWithoutSparkJobs(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "SparkJob" in name:
                raise AssertionError(f"Unexpected SparkJobs DTO access: {name}")
            return getattr(generated_dto, name)

    original_import = import_module
    dto_stub = DtoWithoutSparkJobs("datalens_sdk._generated.dto")
    monkeypatch.setattr(
        client_module,
        "import_module",
        lambda name: dto_stub if name == "datalens_sdk._generated.dto" else original_import(name),
    )

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("SparkJobs service initialized on a base client")

    monkeypatch.setattr(SparkJobService, "__init__", unexpected_service)
    transport = _Transport([])
    with DataLensClientEnterprise(
        auth=None,
        base_url="https://enterprise.test",
        transport=httpx.MockTransport(transport.handle),
    ) as client:
        for namespace, name in ((client.get, "spark_job"), (client.list, "spark_jobs")):
            with pytest.raises(AttributeError) as exc:
                getattr(namespace, name)
            assert type(exc.value) is AttributeError

    class YaTeamStyleClient(DataLensClientBase):
        INSTALLATION = "yacloud"
        DEFAULT_BASE_URL = "https://yateam.test"

    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(transport.handle)) as base:
        for namespace, name in ((base.get, "spark_job"), (base.list, "spark_jobs")):
            with pytest.raises(AttributeError) as exc:
                getattr(namespace, name)
            assert type(exc.value) is AttributeError
    assert transport.requests == []
