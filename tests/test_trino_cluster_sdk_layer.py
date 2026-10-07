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
from datalens_sdk.api.trino_cluster import TrinoClusterAPI, TrinoClusterService
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import Pager
from datalens_sdk.domain.trino_cluster import (
    TrinoAutoScalePolicy,
    TrinoCatalogRef,
    TrinoCluster,
    TrinoClusterConfig,
    TrinoClusterListOptions,
    TrinoCoordinatorConfig,
    TrinoResourceConfig,
    TrinoResourcePreset,
    TrinoResourcePresetListOptions,
    TrinoWorkerConfig,
)
from datalens_sdk.errors import (
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
        "entryId": "",
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
    return TrinoClusterService(installation="yacloud", api=TrinoClusterAPI(http_client))


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


def test_trino_read_surface_is_yc_only() -> None:
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

    class RecordingOperations:
        def __init__(self) -> None:
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
        entry_id="",
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
        entry_id="",
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
