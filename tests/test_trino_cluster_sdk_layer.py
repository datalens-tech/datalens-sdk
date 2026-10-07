from __future__ import annotations

from copy import deepcopy
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
from datalens_sdk.api.lakehouse_operation import LakehouseOperationAPI, LakehouseOperationService
from datalens_sdk.api.trino_cluster import TrinoClusterAPI, TrinoClusterService
from datalens_sdk.converter.trino_cluster import TrinoClusterConverter
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.navigation import Pager
from datalens_sdk.domain.ports import TrinoClusterOperations
from datalens_sdk.domain.trino_cluster import (
    TrinoAutoScalePolicy,
    TrinoCatalogRef,
    TrinoCluster,
    TrinoClusterConfig,
    TrinoClusterCreate,
    TrinoClusterListOptions,
    TrinoCoordinatorConfig,
    TrinoResourceConfig,
    TrinoResourcePreset,
    TrinoResourcePresetListOptions,
    TrinoWorkerConfig,
)
from datalens_sdk.errors import (
    DataLensAPIError,
    DataLensConfigurationError,
    DataLensValidationError,
    DTOValidationError,
    InvalidResponseError,
    NotSupportedError,
)
from datalens_sdk.http import DataLensHTTPClient


def _cluster_response(*, name: str = "Analytics") -> dict[str, object]:
    return {
        "id": "trino-1",
        "clusterId": "managed-2",
        "collectionId": "collection-1",
        "cloudEnvironmentId": "env-1",
        "name": name,
        "description": "A cluster",
        "labels": {"team": "analytics"},
        "config": {
            "trinoVersion": "476",
            "catalogsConfig": [{"catalogId": "catalog-1"}],
            "coordinatorConfig": {"resources": {"resourcePresetId": "coordinator-preset"}},
            "workerConfig": {
                "resources": {"resourcePresetId": "worker-preset"},
                "scalePolicy": {"scaleType": "autoScale", "autoScale": {"minCount": "0", "maxCount": "64"}},
            },
        },
        "health": "ALIVE",
        "status": "RUNNING",
        "coordinatorUrl": "",
        "entryId": "entry-3",
    }


class RecordedTrinoTransport:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def bodies(self) -> list[object]:
        return [json.loads(request.content) for request in self.requests]


def _service(http_client: DataLensHTTPClient) -> TrinoClusterService:
    return TrinoClusterService(
        installation="yacloud",
        api=TrinoClusterAPI(http_client),
        lakehouse_operations=LakehouseOperationService(api=LakehouseOperationAPI(http_client)),
    )


def test_yc_trino_create_dispatches_and_returns_bound_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    original_load_installations = client_module._load_installations

    def load_without_trino_namespace(generated_package: str) -> dict[str, client_module.InstallationInfo]:
        installations = original_load_installations(generated_package)
        installations["yacloud"]["namespaces"] = [
            namespace for namespace in installations["yacloud"]["namespaces"] if namespace != "trino_clusters"
        ]
        return installations

    monkeypatch.setattr(client_module, "_load_installations", load_without_trino_namespace)
    recorder = RecordedTrinoTransport(
        httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}}),
        httpx.Response(200, json={"id": "operation-1", "done": True, "metadata": {}}),
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with client:
        operation = (
            client.create.trino_cluster(
                name="analytics-trino",
                location=EntryLocation.collection("collection-1"),
                cloud_environment_id="env-1",
            )
            .worker(resource_preset="preset-1", min_count=1, max_count=8)
            .build()
        )
        assert operation.id == "operation-1"
        assert operation.done is False
        assert operation.refresh().done is True

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createTrinoCluster",
        "/rpc/getLakehouseOperation",
    ]
    assert recorder.bodies() == [
        {
            "collectionId": "collection-1",
            "cloudEnvironmentId": "env-1",
            "name": "analytics-trino",
            "workerConfig": {
                "resources": {"resourcePresetId": "preset-1"},
                "scalePolicy": {"autoScale": {"minCount": "1", "maxCount": "8"}},
            },
        },
        {"operationId": "operation-1"},
    ]


def test_yc_unknown_create_action_raises_plain_attribute_error_without_http() -> None:
    recorder = RecordedTrinoTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    action = "unrelated_action"
    with client, pytest.raises(AttributeError) as raised:
        getattr(client.create, action)

    assert type(raised.value) is AttributeError
    assert recorder.requests == []


class RecordingTrinoLifecycleOperations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def create_trino_cluster(self, builder: TrinoClusterCreate) -> LakehouseOperation:
        self.calls.append(("create", builder.to_spec().name))
        return LakehouseOperation(id="operation-1", done=False, metadata={})

    def start_trino_cluster(self, cluster_id: str) -> LakehouseOperation:
        self.calls.append(("start", cluster_id))
        return LakehouseOperation(id="operation-2", done=False, metadata={})

    def stop_trino_cluster(self, cluster_id: str) -> LakehouseOperation:
        self.calls.append(("stop", cluster_id))
        return LakehouseOperation(id="operation-3", done=False, metadata={})

    def delete_trino_cluster(self, trino_cluster_id: str) -> LakehouseOperation:
        self.calls.append(("delete", trino_cluster_id))
        return LakehouseOperation(id="operation-4", done=False, metadata={})

    def get_trino_cluster(self, trino_cluster_id: str) -> TrinoCluster:
        raise AssertionError("creation and lifecycle must not fetch clusters")

    def list_trino_clusters(self, options: TrinoClusterListOptions) -> Pager[TrinoCluster]:
        raise AssertionError("creation and lifecycle must not list clusters")

    def get_trino_resource_preset(self, resource_preset_id: str, *, cloud_environment_id: str) -> TrinoResourcePreset:
        raise AssertionError("creation and lifecycle must not fetch presets")

    def list_trino_resource_presets(self, options: TrinoResourcePresetListOptions) -> Pager[TrinoResourcePreset]:
        raise AssertionError("creation and lifecycle must not list presets")


def _create_builder(
    *,
    operations: TrinoClusterOperations | None = None,
    location: EntryLocation | None = None,
    cloud_environment_id: str = "env-1",
) -> TrinoClusterCreate:
    return TrinoClusterCreate(
        installation="yacloud",
        name="analytics-trino",
        location=location if location is not None else EntryLocation.collection("collection-1"),
        cloud_environment_id=cloud_environment_id,
        operations=operations,
    )


def test_trino_create_requires_collection_location_environment_and_worker() -> None:
    class ForeignCollection(EntryLocation):
        installation = "enterprise"

        def _as_entry_location(self) -> EntryLocation:
            return EntryLocation.collection("collection-1")

    operations = RecordingTrinoLifecycleOperations()
    for location in (EntryLocation.path("/folder"), EntryLocation.workbook("workbook-1")):
        with pytest.raises(DataLensValidationError):
            _create_builder(operations=operations, location=location)
    with pytest.raises(DataLensValidationError):
        _create_builder(operations=operations, location=cast(EntryLocation, ""))
    with pytest.raises(NotSupportedError):
        _create_builder(operations=operations, location=ForeignCollection())
    with pytest.raises(DataLensValidationError, match="cloud_environment_id"):
        _create_builder(operations=operations, cloud_environment_id="")
    with pytest.raises(DataLensValidationError, match="worker"):
        _create_builder(operations=operations).build()
    assert operations.calls == []


def test_trino_create_rejects_malformed_collection_reference_before_operations() -> None:
    operations = RecordingTrinoLifecycleOperations()
    malformed = EntryLocation.collection("collection-1")
    object.__setattr__(malformed, "value", "")

    with pytest.raises(DataLensValidationError, match="collection"):
        _create_builder(operations=operations, location=malformed)
    assert operations.calls == []


def test_trino_create_accepts_preset_or_id_and_normalizes_worker() -> None:
    preset = TrinoResourcePreset(
        id="preset-1", installation="yacloud", cloud_environment_id="env-1", cores="2", memory="8 GiB", raw={}
    )
    expected = TrinoWorkerConfig(
        resources=TrinoResourceConfig(resource_preset_id="preset-1"),
        scale_policy=TrinoAutoScalePolicy(min_count=1, max_count=8),
    )
    for reference in ("preset-1", preset):
        operations = RecordingTrinoLifecycleOperations()
        builder = _create_builder(operations=operations).worker(resource_preset=reference, min_count=1, max_count=8)
        assert builder.to_spec().worker == expected
        assert builder.build().id == "operation-1"
        assert operations.calls == [("create", "analytics-trino")]


def test_trino_create_rejects_invalid_preset_provenance_and_worker_types() -> None:
    operations = RecordingTrinoLifecycleOperations()
    matching = TrinoResourcePreset(
        id="preset-1", installation="yacloud", cloud_environment_id="env-1", cores="2", memory="8 GiB", raw={}
    )
    bad_references: tuple[object, ...] = (
        "",
        replace(matching, id=""),
        replace(matching, id=cast(str, 42)),
        replace(matching, installation="enterprise"),
        replace(matching, cloud_environment_id="other-env"),
        42,
    )
    for reference in bad_references:
        with pytest.raises(DataLensValidationError):
            _create_builder(operations=operations).worker(
                resource_preset=cast(str, reference), min_count=1, max_count=8
            )
    for min_count, max_count in ((True, 8), (1, False), (1.5, 8), (1, "8")):
        with pytest.raises(DataLensValidationError, match="count"):
            _create_builder(operations=operations).worker(
                resource_preset="preset-1", min_count=cast(int, min_count), max_count=cast(int, max_count)
            )
    assert operations.calls == []


def test_trino_create_preserves_optional_omission_and_explicit_empty_values() -> None:
    builder = _create_builder().worker(resource_preset="preset-1", min_count=0, max_count=1)
    omitted = builder.to_spec()
    assert (omitted.description, omitted.labels, omitted.trino_version) == (None, None, None)
    explicit = builder.description("").labels({}).trino_version("").to_spec()
    assert (explicit.description, explicit.labels, explicit.trino_version) == ("", {}, "")


def test_trino_create_sends_exact_payload_and_returns_bound_operation() -> None:
    created = {
        "id": "operation-1",
        "done": False,
        "metadata": {"resource": "trino-1"},
        "createdBy": "user-1",
        "description": "Creating cluster",
    }
    refreshed = {"id": "operation-1", "done": True, "metadata": {"resource": "trino-1"}}
    recorder = RecordedTrinoTransport(httpx.Response(200, json=created), httpx.Response(200, json=refreshed))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        operation = (
            _create_builder(operations=_service(http_client))
            .worker(resource_preset="preset-1", min_count=1, max_count=8)
            .description("Interactive analytics cluster")
            .labels({"team": "analytics"})
            .trino_version("476")
            .build()
        )
        assert isinstance(operation, LakehouseOperation)
        assert operation.id == "operation-1"
        assert operation.done is False
        assert operation.metadata == {"resource": "trino-1"}
        assert operation.created_by == "user-1"
        assert operation.description == "Creating cluster"
        assert operation.raw == created
        assert [request.url.path for request in recorder.requests] == ["/rpc/createTrinoCluster"]
        assert operation.refresh().done is True

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createTrinoCluster",
        "/rpc/getLakehouseOperation",
    ]
    assert recorder.bodies() == [
        {
            "collectionId": "collection-1",
            "cloudEnvironmentId": "env-1",
            "name": "analytics-trino",
            "workerConfig": {
                "resources": {"resourcePresetId": "preset-1"},
                "scalePolicy": {"autoScale": {"minCount": "1", "maxCount": "8"}},
            },
            "description": "Interactive analytics cluster",
            "labels": {"team": "analytics"},
            "trinoVersion": "476",
        },
        {"operationId": "operation-1"},
    ]


def test_trino_create_distinguishes_omitted_and_explicit_empty_optional_values() -> None:
    recorder = RecordedTrinoTransport(
        httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}}),
        httpx.Response(200, json={"id": "operation-2", "done": False, "metadata": {}}),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        _create_builder(operations=service).worker(resource_preset="preset-1", min_count=0, max_count=1).build()
        (
            _create_builder(operations=service)
            .worker(resource_preset="preset-1", min_count=0, max_count=1)
            .description("")
            .labels({})
            .trino_version("")
            .build()
        )

    first, second = recorder.bodies()
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    for field in ("description", "labels", "trinoVersion"):
        assert field not in first
    assert second["description"] == ""
    assert second["labels"] == {}
    assert second["trinoVersion"] == ""


@pytest.mark.parametrize(("min_count", "max_count"), [(-1, 8), (65, 8), (0, 0), (1, 65)])
def test_trino_create_generated_dto_rejects_out_of_range_worker_counts_before_http(
    min_count: int, max_count: int
) -> None:
    recorder = RecordedTrinoTransport()
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        builder = _create_builder(operations=_service(http_client)).worker(
            resource_preset="preset-1", min_count=min_count, max_count=max_count
        )
        with pytest.raises(DTOValidationError, match="createTrinoCluster"):
            builder.build()
    assert recorder.requests == []


def test_yc_trino_create_empty_name_fails_generated_validation_before_http() -> None:
    recorder = RecordedTrinoTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        builder = client.create.trino_cluster(
            name="",
            location=EntryLocation.collection("collection-1"),
            cloud_environment_id="env-1",
        ).worker(resource_preset="preset-1", min_count=1, max_count=8)
        with pytest.raises(DTOValidationError, match="createTrinoCluster") as raised:
            builder.build()

    assert type(raised.value) is DTOValidationError
    assert recorder.requests == []


def test_trino_bound_lifecycle_requires_operations_and_correct_identifier() -> None:
    cluster = TrinoCluster(
        id="trino-1",
        cluster_id="managed-1",
        installation="yacloud",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="env-1",
        name="Analytics",
        description="",
        labels={},
        config=TrinoClusterConfig(
            trino_version="476",
            catalogs=(),
            coordinator=TrinoCoordinatorConfig(resources=TrinoResourceConfig(resource_preset_id="preset-1")),
            worker=TrinoWorkerConfig(
                resources=TrinoResourceConfig(resource_preset_id="preset-2"),
                scale_policy=TrinoAutoScalePolicy(min_count=1, max_count=8),
            ),
        ),
        health="ALIVE",
        status="RUNNING",
        coordinator_url="",
        entry_id="",
        raw={},
    )
    for action in (cluster.start, cluster.stop, cluster.delete):
        with pytest.raises(DataLensConfigurationError):
            action()

    operations = RecordingTrinoLifecycleOperations()
    bound = replace(cluster, _operations=operations)
    for action in (replace(bound, id="").start, replace(bound, id="").stop):
        with pytest.raises(DataLensValidationError):
            action()
    with pytest.raises(DataLensValidationError):
        replace(bound, id="").delete()
    assert [bound.start().id, bound.stop().id, bound.delete().id] == ["operation-2", "operation-3", "operation-4"]
    assert operations.calls == [("start", "trino-1"), ("stop", "trino-1"), ("delete", "trino-1")]


def test_trino_start_stop_and_delete_use_distinct_identifiers_and_bound_operations() -> None:
    operation_response = {"id": "operation-1", "done": False, "metadata": {"resource": "trino-1"}}
    recorder = RecordedTrinoTransport(
        *(httpx.Response(200, json=operation_response) for _ in range(3)),
        httpx.Response(200, json={**operation_response, "done": True}),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        cluster = TrinoClusterConverter.to_cluster(
            _cluster_response(),
            installation="yacloud",
            operations=service,
            operation="getTrinoCluster",
        )
        operations = (cluster.start(), cluster.stop(), cluster.delete())
        assert all(isinstance(operation, LakehouseOperation) and operation.done is False for operation in operations)
        assert [request.url.path for request in recorder.requests] == [
            "/rpc/startTrinoCluster",
            "/rpc/stopTrinoCluster",
            "/rpc/deleteTrinoCluster",
        ]
        assert operations[0].refresh().done is True

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/startTrinoCluster",
        "/rpc/stopTrinoCluster",
        "/rpc/deleteTrinoCluster",
        "/rpc/getLakehouseOperation",
    ]
    assert recorder.bodies() == [
        {"clusterId": "trino-1"},
        {"clusterId": "trino-1"},
        {"id": "trino-1"},
        {"operationId": "operation-1"},
    ]


def _run_trino_mutation(service: TrinoClusterService, mutation: str) -> LakehouseOperation:
    if mutation == "create":
        return _create_builder(operations=service).worker(resource_preset="preset-1", min_count=1, max_count=8).build()
    if mutation == "start":
        return service.start_trino_cluster("managed-2")
    if mutation == "stop":
        return service.stop_trino_cluster("managed-2")
    if mutation == "delete":
        return service.delete_trino_cluster("trino-1")
    raise AssertionError(f"unknown test mutation: {mutation}")


@pytest.mark.parametrize("mutation", ["create", "start", "stop", "delete"])
def test_trino_mutations_never_retry_transient_failures(mutation: str) -> None:
    recorder = RecordedTrinoTransport(httpx.Response(503, json={"code": "UNAVAILABLE", "message": "Try again"}))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        with pytest.raises(DataLensAPIError) as raised:
            _run_trino_mutation(service, mutation)

    assert raised.value.context.attempts == 1
    assert [request.url.path for request in recorder.requests] == [f"/rpc/{mutation}TrinoCluster"]


@pytest.mark.parametrize("mutation", ["create", "start", "stop", "delete"])
@pytest.mark.parametrize(
    "invalid_response",
    [
        {"done": False, "metadata": {}},
        {"id": "operation-1", "done": False, "metadata": {}, "createdAt": {"nanos": 0}},
        {"id": "operation-1", "done": True, "metadata": {}, "error": {"code": 13}},
    ],
    ids=["missing-id", "malformed-timestamp", "malformed-error"],
)
def test_trino_mutations_report_operation_specific_invalid_responses(
    mutation: str, invalid_response: dict[str, object]
) -> None:
    recorder = RecordedTrinoTransport(httpx.Response(200, json=invalid_response))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        with pytest.raises((DTOValidationError, InvalidResponseError), match=f"{mutation}TrinoCluster"):
            _run_trino_mutation(service, mutation)

    assert len(recorder.requests) == 1


@pytest.fixture
def unsupported_trino_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DataLensClientEnterprise, client_module.DataLensClientBase, RecordedTrinoTransport]:
    class YaTeamStyleClient(client_module.DataLensClientBase):
        INSTALLATION = "yateam"
        GENERATED_PACKAGE = "test_yateam_generated"
        DEFAULT_BASE_URL = "https://yateam.test"

    class DtoWithoutTrino(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "Trino" in name:
                raise AssertionError(f"Unexpected Trino DTO access: {name}")
            return getattr(generated_dto, name)

    original_import = import_module
    sources = original_import("datalens_sdk._generated.builders.dataset_sources")
    charts = original_import("datalens_sdk._generated.builders.charts")
    monkeypatch.setattr(sources, "YateamSourceCreateFactory", sources.EnterpriseSourceCreateFactory, raising=False)
    monkeypatch.setattr(
        charts, "YateamEditorChartCreateFactory", charts.EnterpriseEditorChartCreateFactory, raising=False
    )
    modules = {
        "datalens_sdk._generated.dto": DtoWithoutTrino("datalens_sdk._generated.dto"),
        "test_yateam_generated.dto": DtoWithoutTrino("test_yateam_generated.dto"),
        "test_yateam_generated.builders.yateam": original_import("datalens_sdk._generated.builders.enterprise"),
        "test_yateam_generated.builders.dataset_sources": sources,
        "test_yateam_generated.builders.charts": charts,
    }

    def import_without_trino(name: str) -> ModuleType:
        return modules[name] if name in modules else original_import(name)

    installations = client_module._load_installations("datalens_sdk._generated")
    installations["yateam"] = {**installations["enterprise"], "namespaces": []}
    monkeypatch.setattr(client_module, "_load_installations", lambda package: installations)
    monkeypatch.setattr(client_module, "import_module", import_without_trino)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("Trino service initialized on an unsupported installation")

    monkeypatch.setattr(TrinoClusterService, "__init__", unexpected_service)
    recorder = RecordedTrinoTransport()
    no_request = httpx.MockTransport(recorder.handle)
    return (
        DataLensClientEnterprise(auth=None, base_url="https://enterprise.test", transport=no_request),
        YaTeamStyleClient(auth=None, transport=no_request),
        recorder,
    )


def test_trino_read_client_construction_and_reads_survive_required_operation_dependency() -> None:
    recorder = RecordedTrinoTransport(
        httpx.Response(200, json=_cluster_response()),
        httpx.Response(200, json={"id": "preset-1", "cores": "2", "memory": "8 GiB"}),
        httpx.Response(200, json={"clusters": [_cluster_response()], "nextPageToken": ""}),
        httpx.Response(
            200,
            json={"resourcePresets": [{"id": "preset-2", "cores": "4", "memory": "16 GiB"}], "nextPageToken": ""},
        ),
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with client:
        cluster = client.get.trino_cluster(by_id="trino-1")
        preset = client.get.trino_resource_preset(by_id="preset-1", cloud_environment_id="env-1")
        clusters = client.list.trino_clusters(collection="collection-1", filters=["status=RUNNING"], page_size=2)
        presets = client.list.trino_resource_presets(cloud_environment_id="env-1", page_size=3)
        assert recorder.requests[-1].url.path == "/rpc/getTrinoResourcePreset"
        cluster_page = next(clusters.pages())
        preset_page = next(presets.pages())

    assert cluster.id == "trino-1"
    assert preset.cloud_environment_id == "env-1"
    assert cluster_page.items[0].cluster_id == "managed-2"
    assert preset_page.items[0].id == "preset-2"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getTrinoCluster",
        "/rpc/getTrinoResourcePreset",
        "/rpc/listTrinoClusters",
        "/rpc/listTrinoResourcePresets",
    ]
    assert recorder.bodies() == [
        {"id": "trino-1"},
        {"resourcePresetId": "preset-1", "cloudEnvironmentId": "env-1"},
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 2},
        {"cloudEnvironmentId": "env-1", "pageSize": 3},
    ]


@pytest.mark.parametrize("client_index", [0, 1], ids=["enterprise", "yateam"])
def test_trino_read_surface_is_yc_only_on_unsupported_installations(
    unsupported_trino_clients: tuple[
        DataLensClientEnterprise, client_module.DataLensClientBase, RecordedTrinoTransport
    ],
    client_index: int,
) -> None:
    enterprise, yateam, recorder = unsupported_trino_clients
    client = (enterprise, yateam)[client_index]
    with client:
        for namespace, action in (
            (client.get, "trino_cluster"),
            (client.get, "trino_resource_preset"),
            (client.list, "trino_clusters"),
            (client.list, "trino_resource_presets"),
        ):
            with pytest.raises(AttributeError) as raised:
                getattr(namespace, action)
            assert type(raised.value) is AttributeError
        unknown_action = "unknown_action"
        for namespace in (client.get, client.list):
            with pytest.raises(AttributeError) as unknown:
                getattr(namespace, unknown_action)
            assert type(unknown.value) is AttributeError
        assert type(client.get) is client_module.GetNamespace
        assert type(client.list) is client_module.ListNamespace
    assert recorder.requests == []


def test_trino_create_is_absent_on_unsupported_installations(
    unsupported_trino_clients: tuple[
        DataLensClientEnterprise, client_module.DataLensClientBase, RecordedTrinoTransport
    ],
) -> None:
    enterprise, yateam, unsupported_recorder = unsupported_trino_clients
    for unsupported in (enterprise, yateam):
        with unsupported:
            for action in ("trino_cluster", "unknown_action"):
                with pytest.raises(AttributeError) as missing:
                    getattr(unsupported.create, action)
                assert type(missing.value) is AttributeError
            assert type(unsupported.create) is client_module.CreateNamespace
    assert unsupported_recorder.requests == []


def test_trino_read_responses_reject_invalid_nested_values_and_ignore_extra_fields() -> None:
    response_with_extra = _cluster_response()
    response_with_extra["newBackendField"] = {"future": True}
    invalid_responses: list[tuple[str, dict[str, object], str]] = []
    missing_required = _cluster_response()
    del missing_required["name"]
    invalid_responses.append(("cluster", missing_required, "getTrinoCluster"))
    for field, value in (("health", "UNKNOWN_HEALTH"), ("status", "UNKNOWN_STATUS")):
        response = _cluster_response()
        response[field] = value
        invalid_responses.append(("cluster", response, "getTrinoCluster"))
    invalid_scale = deepcopy(_cluster_response())
    config = cast(dict[str, object], invalid_scale["config"])
    worker = cast(dict[str, object], config["workerConfig"])
    policy = cast(dict[str, object], worker["scalePolicy"])
    auto_scale = cast(dict[str, object], policy["autoScale"])
    auto_scale["minCount"] = "not-a-number"
    invalid_responses.append(("cluster", invalid_scale, "getTrinoCluster"))
    invalid_responses.append(("preset", {"id": "preset-1", "cores": 2, "memory": "8 GiB"}, "getTrinoResourcePreset"))

    responses = [httpx.Response(200, json=response_with_extra)]
    responses.extend(httpx.Response(200, json=body) for _, body, _ in invalid_responses)
    recorder = RecordedTrinoTransport(*responses)
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        loaded = service.get_trino_cluster("trino-1")
        assert loaded.name == "Analytics"
        assert loaded.raw["newBackendField"] == {"future": True}
        for kind, _, operation in invalid_responses:
            with pytest.raises((DTOValidationError, InvalidResponseError), match=operation) as raised:
                (
                    service.get_trino_cluster("trino-1")
                    if kind == "cluster"
                    else service.get_trino_resource_preset("preset-1", cloud_environment_id="env-1")
                )
            assert type(raised.value) in (DTOValidationError, InvalidResponseError)
    assert len(recorder.requests) == 1 + len(invalid_responses)


def test_trino_list_options_normalize_collection_filters_and_page_token() -> None:
    from_location = TrinoClusterListOptions.create(
        installation="yacloud",
        collection=EntryLocation.collection("collection-1"),
        filters=["name=analytics", "status=RUNNING"],
        page_token="resume-here",
    )
    from_id = TrinoClusterListOptions.create(installation="yacloud", collection="collection-2")

    assert from_location.collection_id == "collection-1"
    assert from_location.filters == ("name=analytics", "status=RUNNING")
    assert from_location.page_token == "resume-here"
    assert from_id.collection_id == "collection-2"
    assert from_id.filters == ()
    assert TrinoClusterListOptions.create(installation="yacloud").collection_id is None


def test_trino_list_options_reject_wrong_location_foreign_installation_and_scalar_filters() -> None:
    class ForeignCollection(EntryLocation):
        installation = "enterprise"

        def _as_entry_location(self) -> EntryLocation:
            return EntryLocation.collection("collection-1")

    for collection in (EntryLocation.path("/folder"), EntryLocation.workbook("workbook-1"), ""):
        with pytest.raises(DataLensValidationError):
            TrinoClusterListOptions.create(installation="yacloud", collection=collection)

    with pytest.raises(NotSupportedError):
        TrinoClusterListOptions.create(installation="yacloud", collection=ForeignCollection())

    with pytest.raises(DataLensValidationError, match="filters"):
        TrinoClusterListOptions.create(installation="yacloud", filters="status=RUNNING")


def test_trino_list_options_preserve_page_sizes_for_generated_validation() -> None:
    assert TrinoClusterListOptions.create(installation="yacloud", page_size=-1).page_size == -1
    assert TrinoClusterListOptions.create(installation="yacloud", page_size=0).page_size == 0
    assert TrinoResourcePresetListOptions.create(cloud_environment_id="env-1", page_size=1001).page_size == 1001
    assert TrinoResourcePresetListOptions.create(cloud_environment_id="env-1", page_size=0).page_size == 0


def test_trino_resource_preset_list_requires_cloud_environment_id() -> None:
    with pytest.raises(DataLensValidationError, match="cloud_environment_id"):
        TrinoResourcePresetListOptions.create(cloud_environment_id="")


def test_bound_trino_cluster_refresh_requires_operations_and_public_id() -> None:
    cluster = TrinoCluster(
        id="trino-1",
        cluster_id="managed-2",
        installation="yacloud",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="env-1",
        name="Original",
        description="",
        labels={},
        config=TrinoClusterConfig(
            trino_version="476",
            catalogs=(),
            coordinator=TrinoCoordinatorConfig(resources=TrinoResourceConfig(resource_preset_id="preset-1")),
            worker=TrinoWorkerConfig(
                resources=TrinoResourceConfig(resource_preset_id="preset-2"),
                scale_policy=TrinoAutoScalePolicy(min_count=1, max_count=8),
            ),
        ),
        health="ALIVE",
        status="RUNNING",
        coordinator_url="",
        entry_id="",
        raw={},
    )

    with pytest.raises(DataLensConfigurationError):
        cluster.refresh()

    class RecordingOperations(RecordingTrinoLifecycleOperations):
        def __init__(self) -> None:
            super().__init__()
            self.received_id: str | None = None

        def get_trino_cluster(self, trino_cluster_id: str) -> TrinoCluster:
            self.received_id = trino_cluster_id
            return replace(cluster, name="Refreshed", _operations=self)

        def list_trino_clusters(self, options: TrinoClusterListOptions) -> Pager[TrinoCluster]:
            raise AssertionError("refresh must not list clusters")

        def get_trino_resource_preset(
            self,
            resource_preset_id: str,
            *,
            cloud_environment_id: str,
        ) -> TrinoResourcePreset:
            raise AssertionError("refresh must not get a resource preset")

        def list_trino_resource_presets(self, options: TrinoResourcePresetListOptions) -> Pager[TrinoResourcePreset]:
            raise AssertionError("refresh must not list resource presets")

    operations = RecordingOperations()
    bound = replace(cluster, _operations=operations)
    with pytest.raises(DataLensValidationError):
        replace(bound, id="").refresh()

    refreshed = bound.refresh()
    assert operations.received_id == "trino-1"
    assert refreshed is not bound
    assert refreshed.name == "Refreshed"
    assert bound.name == "Original"


def test_trino_get_and_refresh_map_complete_cluster_and_retry_reads() -> None:
    first = _cluster_response()
    second = _cluster_response(name="Refreshed")
    second["description"] = "A refreshed cluster"
    second["status"] = "UPDATING"
    second_config = cast(dict[str, object], second["config"])
    second_config["catalogsConfig"] = [{"catalogId": "catalog-2"}]
    recorder = RecordedTrinoTransport(
        httpx.Response(503, json={"code": "UNAVAILABLE", "message": "Try again"}),
        httpx.Response(200, json=first),
        httpx.Response(200, json=second),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        cluster = _service(http_client).get_trino_cluster("trino-1")
        refreshed = cluster.refresh()

    assert [request.url.path for request in recorder.requests] == ["/rpc/getTrinoCluster"] * 3
    assert recorder.bodies() == [{"id": "trino-1"}] * 3
    assert cluster == TrinoCluster(
        id="trino-1",
        cluster_id="managed-2",
        installation="yacloud",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="env-1",
        name="Analytics",
        description="A cluster",
        labels={"team": "analytics"},
        config=TrinoClusterConfig(
            trino_version="476",
            catalogs=(TrinoCatalogRef(catalog_id="catalog-1"),),
            coordinator=TrinoCoordinatorConfig(resources=TrinoResourceConfig(resource_preset_id="coordinator-preset")),
            worker=TrinoWorkerConfig(
                resources=TrinoResourceConfig(resource_preset_id="worker-preset"),
                scale_policy=TrinoAutoScalePolicy(min_count=0, max_count=64),
            ),
        ),
        health="ALIVE",
        status="RUNNING",
        coordinator_url="",
        entry_id="entry-3",
        raw=first,
    )
    assert refreshed is not cluster
    assert refreshed == TrinoCluster(
        id="trino-1",
        cluster_id="managed-2",
        installation="yacloud",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="env-1",
        name="Refreshed",
        description="A refreshed cluster",
        labels={"team": "analytics"},
        config=TrinoClusterConfig(
            trino_version="476",
            catalogs=(TrinoCatalogRef(catalog_id="catalog-2"),),
            coordinator=TrinoCoordinatorConfig(resources=TrinoResourceConfig(resource_preset_id="coordinator-preset")),
            worker=TrinoWorkerConfig(
                resources=TrinoResourceConfig(resource_preset_id="worker-preset"),
                scale_policy=TrinoAutoScalePolicy(min_count=0, max_count=64),
            ),
        ),
        health="ALIVE",
        status="UPDATING",
        coordinator_url="",
        entry_id="entry-3",
        raw=second,
    )
    assert cluster.name == "Analytics"


def test_trino_resource_preset_reads_preserve_environment_and_retry() -> None:
    preset = {"id": "preset-1", "cores": "2.5", "memory": "16 GiB"}
    recorder = RecordedTrinoTransport(
        httpx.Response(503, json={"code": "UNAVAILABLE", "message": "Try again"}),
        httpx.Response(200, json=preset),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        loaded = _service(http_client).get_trino_resource_preset("preset-1", cloud_environment_id="env-1")

    assert [request.url.path for request in recorder.requests] == ["/rpc/getTrinoResourcePreset"] * 2
    assert recorder.bodies() == [{"resourcePresetId": "preset-1", "cloudEnvironmentId": "env-1"}] * 2
    assert loaded == TrinoResourcePreset(
        id="preset-1",
        installation="yacloud",
        cloud_environment_id="env-1",
        cores="2.5",
        memory="16 GiB",
        raw=preset,
    )


def test_trino_cluster_list_is_lazy_resumable_and_rejects_repeated_tokens() -> None:
    recorder = RecordedTrinoTransport(
        httpx.Response(200, json={"clusters": [_cluster_response()], "nextPageToken": "next"}),
        httpx.Response(503, json={"code": "UNAVAILABLE", "message": "Try again"}),
        httpx.Response(200, json={"clusters": [_cluster_response(name="Second")], "nextPageToken": ""}),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        pager = service.list_trino_clusters(
            TrinoClusterListOptions.create(
                installation="yacloud",
                collection="collection-1",
                filters=["status=RUNNING"],
                page_size=2,
                page_token="resume",
            )
        )
        assert recorder.requests == []
        pages = list(pager.pages())

    assert [request.url.path for request in recorder.requests] == ["/rpc/listTrinoClusters"] * 3
    assert recorder.bodies() == [
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 2, "pageToken": "resume"},
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 2, "pageToken": "next"},
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 2, "pageToken": "next"},
    ]
    assert [page.next_page_token for page in pages] == ["next", ""]
    assert all(isinstance(page.items[0], TrinoCluster) for page in pages)
    assert [page.items[0].name for page in pages] == ["Analytics", "Second"]

    repeat = RecordedTrinoTransport(httpx.Response(200, json={"clusters": [], "nextPageToken": "resume"}))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(repeat.handle),
    ) as http_client:
        pager = _service(http_client).list_trino_clusters(
            TrinoClusterListOptions.create(
                installation="yacloud",
                page_token="resume",
            )
        )
        with pytest.raises(InvalidResponseError, match=r"listTrinoClusters.*repeated"):
            list(pager.pages())
    assert repeat.bodies() == [{"pageSize": 100, "pageToken": "resume"}]


def test_trino_resource_preset_list_is_lazy_and_rejects_repeated_tokens() -> None:
    preset = {"id": "preset-1", "cores": "4", "memory": "32 GiB"}
    recorder = RecordedTrinoTransport(
        httpx.Response(200, json={"resourcePresets": [preset], "nextPageToken": "next"}),
        httpx.Response(503, json={"code": "UNAVAILABLE", "message": "Try again"}),
        httpx.Response(200, json={"resourcePresets": [preset], "nextPageToken": ""}),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        pager = _service(http_client).list_trino_resource_presets(
            TrinoResourcePresetListOptions.create(cloud_environment_id="env-1", page_size=3, page_token="resume")
        )
        assert recorder.requests == []
        pages = list(pager.pages())

    assert [request.url.path for request in recorder.requests] == ["/rpc/listTrinoResourcePresets"] * 3
    assert recorder.bodies() == [
        {"cloudEnvironmentId": "env-1", "pageSize": 3, "pageToken": "resume"},
        {"cloudEnvironmentId": "env-1", "pageSize": 3, "pageToken": "next"},
        {"cloudEnvironmentId": "env-1", "pageSize": 3, "pageToken": "next"},
    ]
    assert [page.next_page_token for page in pages] == ["next", ""]
    assert all(isinstance(page.items[0], TrinoResourcePreset) for page in pages)
    assert all(page.items[0].cloud_environment_id == "env-1" for page in pages)
    assert all(page.items[0].installation == "yacloud" for page in pages)

    repeat = RecordedTrinoTransport(httpx.Response(200, json={"resourcePresets": [], "nextPageToken": "resume"}))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(repeat.handle),
    ) as http_client:
        pager = _service(http_client).list_trino_resource_presets(
            TrinoResourcePresetListOptions.create(cloud_environment_id="env-1", page_token="resume")
        )
        with pytest.raises(InvalidResponseError, match=r"listTrinoResourcePresets.*repeated"):
            list(pager.pages())
    assert repeat.bodies() == [{"cloudEnvironmentId": "env-1", "pageSize": 100, "pageToken": "resume"}]


def test_trino_resource_preset_list_rejects_missing_wire_alias_with_rpc_context() -> None:
    recorder = RecordedTrinoTransport(httpx.Response(200, json={"resource_presets": [], "nextPageToken": ""}))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        pager = _service(http_client).list_trino_resource_presets(
            TrinoResourcePresetListOptions.create(cloud_environment_id="env-1")
        )
        with pytest.raises(InvalidResponseError, match=r"listTrinoResourcePresets.*resourcePresets"):
            list(pager.pages())

    assert len(recorder.requests) == 1


def test_trino_cluster_list_validates_unhashable_initial_token_before_http() -> None:
    recorder = RecordedTrinoTransport()
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        pager = _service(http_client).list_trino_clusters(
            TrinoClusterListOptions.create(installation="yacloud", page_token=cast(str, ["resume"]))
        )
        assert recorder.requests == []
        with pytest.raises(DTOValidationError, match="listTrinoClusters"):
            list(pager.pages())

    assert recorder.requests == []


def test_trino_resource_preset_list_validates_unhashable_initial_token_before_http() -> None:
    recorder = RecordedTrinoTransport()
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        pager = _service(http_client).list_trino_resource_presets(
            TrinoResourcePresetListOptions.create(cloud_environment_id="env-1", page_token=cast(str, ["resume"]))
        )
        assert recorder.requests == []
        with pytest.raises(DTOValidationError, match="listTrinoResourcePresets"):
            list(pager.pages())

    assert recorder.requests == []


@pytest.mark.parametrize(
    ("kind", "page_size", "valid"),
    [
        ("cluster", 0, True),
        ("cluster", -1, False),
        ("cluster", True, False),
        ("preset", 0, True),
        ("preset", 1000, True),
        ("preset", 1001, False),
        ("preset", True, False),
    ],
)
def test_trino_list_page_sizes_use_generated_validation_before_http(
    kind: str,
    page_size: int,
    valid: bool,
) -> None:
    response = (
        {"clusters": [], "nextPageToken": ""}
        if kind == "cluster"
        else {
            "resourcePresets": [],
            "nextPageToken": "",
        }
    )
    recorder = RecordedTrinoTransport(httpx.Response(200, json=response))
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://trino.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _service(http_client)
        pager: Pager[TrinoCluster] | Pager[TrinoResourcePreset]
        if kind == "cluster":
            pager = service.list_trino_clusters(
                TrinoClusterListOptions.create(
                    installation="yacloud",
                    page_size=page_size,
                )
            )
        else:
            pager = service.list_trino_resource_presets(
                TrinoResourcePresetListOptions.create(
                    cloud_environment_id="env-1",
                    page_size=page_size,
                )
            )
        assert recorder.requests == []
        if valid:
            assert next(pager.pages()).items == ()
            assert len(recorder.requests) == 1
        else:
            with pytest.raises(DTOValidationError, match="listTrino"):
                list(pager.pages())
            assert recorder.requests == []
