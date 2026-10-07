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
from datalens_sdk.api.spark_cluster import SparkClusterAPI, SparkClusterService
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import Pager
from datalens_sdk.domain.ports import SparkClusterOperations
from datalens_sdk.domain.spark_cluster import (
    SparkAutoScalePolicy,
    SparkCluster,
    SparkClusterConfig,
    SparkClusterDependencies,
    SparkClusterListOptions,
    SparkFixedScalePolicy,
    SparkLoggingConfig,
    SparkResourcePoolConfig,
    SparkResourcePoolsConfig,
    SparkResourcePreset,
    SparkResourcePresetListOptions,
)
from datalens_sdk.errors import (
    DataLensConfigurationError,
    DataLensValidationError,
    DTOValidationError,
    InvalidResponseError,
    NotSupportedError,
)
from datalens_sdk.http import DataLensHTTPClient


def _cluster(*, cluster_id: str = "managed-1", id: str = "public-1") -> SparkCluster:
    return SparkCluster(
        id=id,
        cluster_id=cluster_id,
        installation="yacloud",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        name="analytics",
        description="",
        labels={},
        config=SparkClusterConfig(
            spark_version="3.5",
            resource_pools=SparkResourcePoolsConfig(
                driver=SparkResourcePoolConfig(
                    resource_preset_id="driver-1", scale_policy=SparkFixedScalePolicy(size=1)
                ),
                executor=SparkResourcePoolConfig(
                    resource_preset_id="executor-1",
                    scale_policy=SparkAutoScalePolicy(min_size=0, max_size=10, initial_size=2),
                ),
            ),
            dependencies=None,
            logging=None,
        ),
        health="ALIVE",
        status="CREATING",
        entry_id="",
        raw={},
    )


def test_spark_list_options_normalize_collection_filters_and_tokens() -> None:
    by_location = SparkClusterListOptions.create(
        installation="yacloud",
        collection=EntryLocation.collection("collection-1"),
        filters=["name=analytics", "status=RUNNING"],
        page_size=0,
        page_token="",
    )
    assert by_location.collection_id == "collection-1"
    assert by_location.filters == ("name=analytics", "status=RUNNING")
    assert by_location.page_size == 0
    assert by_location.page_token == ""
    assert (
        SparkClusterListOptions.create(installation="yacloud", collection="collection-2").collection_id
        == "collection-2"
    )
    assert SparkClusterListOptions.create(installation="yacloud").collection_id is None

    presets = SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_size=0, page_token="")
    assert presets.cloud_environment_id == "environment-1"
    assert presets.page_size == 0
    assert presets.page_token == ""


def test_spark_list_options_reject_wrong_location_foreign_installation_and_scalar_filters() -> None:
    class ForeignCollection(EntryLocation):
        installation = "enterprise"

        def _as_entry_location(self) -> EntryLocation:
            return EntryLocation.collection("collection-1")

    for collection in (EntryLocation.path("/"), EntryLocation.workbook("workbook-1"), ""):
        with pytest.raises(DataLensValidationError):
            SparkClusterListOptions.create(installation="yacloud", collection=collection)
    with pytest.raises(NotSupportedError):
        SparkClusterListOptions.create(installation="yacloud", collection=ForeignCollection())
    for filters in ("name=analytics", b"name=analytics"):
        with pytest.raises(DataLensValidationError):
            SparkClusterListOptions.create(installation="yacloud", filters=cast(Sequence[str], filters))
    with pytest.raises(DataLensValidationError):
        SparkResourcePresetListOptions.create(cloud_environment_id="")


@pytest.mark.parametrize("invalid", [True, "1", 1.0, object()])
def test_spark_policy_models_reject_non_integer_fields(invalid: object) -> None:
    with pytest.raises(DataLensValidationError):
        SparkFixedScalePolicy(size=cast(int, invalid))
    for field in ("min_size", "max_size", "initial_size"):
        values = {"min_size": 0, "max_size": 10, "initial_size": 2}
        values[field] = cast(int, invalid)
        with pytest.raises(DataLensValidationError):
            SparkAutoScalePolicy(**values)

    assert SparkFixedScalePolicy(size=101).size == 101
    unordered = SparkAutoScalePolicy(min_size=7, max_size=1, initial_size=9)
    assert (unordered.min_size, unordered.max_size, unordered.initial_size) == (7, 1, 9)


def test_bound_spark_cluster_refresh_requires_public_id() -> None:
    source = _cluster(cluster_id="")
    with pytest.raises(DataLensConfigurationError):
        source.refresh()

    class FakeOperations:
        def __init__(self) -> None:
            self.requested_ids: list[str] = []

        def get_spark_cluster(self, spark_cluster_id: str) -> SparkCluster:
            self.requested_ids.append(spark_cluster_id)
            return replace(source, status="RUNNING", _operations=cast(SparkClusterOperations, self))

    operations = FakeOperations()
    bound = replace(source, _operations=cast(SparkClusterOperations, operations))
    with pytest.raises(DataLensValidationError):
        replace(bound, id="").refresh()
    refreshed = bound.refresh()

    assert operations.requested_ids == ["public-1"]
    assert refreshed is not bound
    assert refreshed.status == "RUNNING"
    assert refreshed.cluster_id == ""
    assert bound.status == "CREATING"


def _cluster_response(
    *, cluster_id: str = "managed-1", dependencies: object = None, logging: object = None
) -> dict[str, object]:
    return {
        "id": "public-1",
        "clusterId": cluster_id,
        "collectionId": "collection-1",
        "cloudEnvironmentId": "environment-1",
        "name": "analytics",
        "description": "",
        "labels": {},
        "health": "ALIVE",
        "status": "CREATING",
        "entryId": "",
        "futureResource": 7,
        "config": {
            "sparkVersion": "",
            "dependencies": dependencies,
            "logging": logging,
            "futureConfig": {"x": 1},
            "resourcePools": {
                "driver": {
                    "resourcePresetId": "driver-1",
                    "scalePolicy": {"scaleType": "fixedScale", "fixedScale": {"size": "1", "futureSize": True}},
                },
                "executor": {
                    "resourcePresetId": "executor-1",
                    "scalePolicy": {
                        "scaleType": "autoScale",
                        "autoScale": {"minSize": "0", "initialSize": "2", "maxSize": "10"},
                    },
                },
            },
        },
    }


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


def _service(transport: _Transport) -> tuple[DataLensHTTPClient, SparkClusterService]:
    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://spark.test",
        transport=httpx.MockTransport(transport.handle),
    )
    return client, SparkClusterService(installation="yacloud", api=SparkClusterAPI(client))


def test_spark_read_surface_is_yc_only(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_cluster = _cluster_response(cluster_id="")
    raw_preset = {"id": "preset-1", "cores": "2", "memory": "8GiB"}
    transport = _Transport(
        [
            httpx.Response(200, json=raw_cluster),
            httpx.Response(200, json=raw_preset),
            httpx.Response(200, json={"sparkClusters": [raw_cluster], "nextPageToken": ""}),
            httpx.Response(200, json={"resourcePresets": [raw_preset], "nextPageToken": ""}),
        ]
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        cluster = client.get.spark_cluster(by_id="public-1")
        preset = client.get.spark_resource_preset(by_id="preset-1", cloud_environment_id="environment-1")
        clusters = client.list.spark_clusters(collection="collection-1", filters=["status=RUNNING"], page_token="A")
        presets = client.list.spark_resource_presets(cloud_environment_id="environment-1", page_token="B")
        assert transport.requests[0].url.path == "/rpc/getSparkCluster"
        assert len(transport.requests) == 2
        assert [item.id for item in clusters] == ["public-1"]
        assert [item.id for item in presets] == ["preset-1"]
    assert cluster.cluster_id == ""
    assert preset.cloud_environment_id == "environment-1"
    assert [request.url.path for request in transport.requests] == [
        "/rpc/getSparkCluster",
        "/rpc/getSparkResourcePreset",
        "/rpc/listSparkClusters",
        "/rpc/listSparkResourcePresets",
    ]
    assert transport.bodies() == [
        {"id": "public-1"},
        {"resourcePresetId": "preset-1", "cloudEnvironmentId": "environment-1"},
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 100, "pageToken": "A"},
        {"cloudEnvironmentId": "environment-1", "pageSize": 100, "pageToken": "B"},
    ]

    class DtoWithoutSpark(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "Spark" in name:
                raise AssertionError(f"Unexpected Spark DTO access: {name}")
            return getattr(generated_dto, name)

    original_import = import_module
    dto_stub = DtoWithoutSpark("datalens_sdk._generated.dto")
    monkeypatch.setattr(
        client_module,
        "import_module",
        lambda name: dto_stub if name == "datalens_sdk._generated.dto" else original_import(name),
    )

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("Spark service initialized on Enterprise")

    monkeypatch.setattr(SparkClusterService, "__init__", unexpected_service)
    enterprise_transport = _Transport([])
    with DataLensClientEnterprise(
        auth=None,
        base_url="https://enterprise.test",
        transport=httpx.MockTransport(enterprise_transport.handle),
    ) as enterprise:
        for namespace, names in (
            (enterprise.get, ("spark_cluster", "spark_resource_preset")),
            (enterprise.list, ("spark_clusters", "spark_resource_presets")),
        ):
            for name in names:
                with pytest.raises(AttributeError) as raised:
                    getattr(namespace, name)
                assert type(raised.value) is AttributeError
    assert enterprise_transport.requests == []


def test_spark_read_yateam_style_base_client_has_no_spark_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    class YaTeamStyleClient(client_module.DataLensClientBase):
        INSTALLATION = "yateam"
        GENERATED_PACKAGE = "test_yateam_generated"
        DEFAULT_BASE_URL = "https://yateam.test"

    class DtoWithoutSpark(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "Spark" in name:
                raise AssertionError(f"Unexpected Spark DTO access: {name}")
            return getattr(generated_dto, name)

    sources = import_module("datalens_sdk._generated.builders.dataset_sources")
    charts = import_module("datalens_sdk._generated.builders.charts")
    monkeypatch.setattr(sources, "YateamSourceCreateFactory", sources.EnterpriseSourceCreateFactory, raising=False)
    monkeypatch.setattr(
        charts, "YateamEditorChartCreateFactory", charts.EnterpriseEditorChartCreateFactory, raising=False
    )
    modules = {
        "test_yateam_generated.dto": DtoWithoutSpark("test_yateam_generated.dto"),
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
        raise AssertionError("Spark service initialized on YaTeam")

    monkeypatch.setattr(SparkClusterService, "__init__", unexpected_service)
    transport = _Transport([])
    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(transport.handle)) as client:
        assert type(client.get) is client_module.GetNamespace
        assert type(client.list) is client_module.ListNamespace
        for namespace, names in (
            (client.get, ("spark_cluster", "spark_resource_preset")),
            (client.list, ("spark_clusters", "spark_resource_presets")),
        ):
            for name in names:
                with pytest.raises(AttributeError) as raised:
                    getattr(namespace, name)
                assert type(raised.value) is AttributeError
    assert transport.requests == []


def test_spark_get_and_refresh_map_complete_cluster_and_retry_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _cluster_response(cluster_id="")
    second = _cluster_response(
        cluster_id="", dependencies={"pipPackages": [], "debPackages": []}, logging={"enabled": False}
    )
    second["status"] = "RUNNING"
    transport = _Transport(
        [
            httpx.Response(503, json={"message": "retry"}),
            httpx.Response(200, json=first),
            httpx.Response(200, json=second),
        ]
    )
    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.http.time.sleep", sleeps.append)
    client, service = _service(transport)
    with client:
        cluster = service.get_spark_cluster("public-1")
        refreshed = cluster.refresh()

    assert [request.url.path for request in transport.requests] == ["/rpc/getSparkCluster"] * 3
    assert transport.bodies() == [{"id": "public-1"}] * 3
    assert sleeps == [0.1]
    expected = SparkCluster(
        id="public-1",
        cluster_id="",
        installation="yacloud",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        name="analytics",
        description="",
        labels={},
        config=SparkClusterConfig(
            spark_version="",
            resource_pools=SparkResourcePoolsConfig(
                driver=SparkResourcePoolConfig("driver-1", SparkFixedScalePolicy(1)),
                executor=SparkResourcePoolConfig("executor-1", SparkAutoScalePolicy(0, 10, 2)),
            ),
            dependencies=None,
            logging=None,
        ),
        health="ALIVE",
        status="CREATING",
        entry_id="",
        raw=first,
    )
    assert cluster == expected
    assert refreshed == replace(
        expected,
        status="RUNNING",
        config=replace(
            expected.config,
            dependencies=SparkClusterDependencies((), ()),
            logging=SparkLoggingConfig(False),
        ),
        raw=second,
    )
    assert refreshed is not cluster


def test_spark_resource_preset_reads_keep_request_environment_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = {"id": "preset-1", "cores": "2", "memory": "8GiB", "future": {"x": 1}}
    transport = _Transport(
        [
            httpx.Response(503, json={"message": "retry"}),
            httpx.Response(200, json=raw),
            httpx.Response(200, json={"resourcePresets": [raw], "nextPageToken": ""}),
        ]
    )
    monkeypatch.setattr("datalens_sdk.http.time.sleep", lambda _: None)
    client, service = _service(transport)
    with client:
        preset = service.get_spark_resource_preset("preset-1", cloud_environment_id="environment-1")
        pages = list(
            service.list_spark_resource_presets(
                SparkResourcePresetListOptions.create(cloud_environment_id="environment-1")
            ).pages()
        )

    assert preset == SparkResourcePreset("preset-1", "yacloud", "environment-1", "2", "8GiB", raw)
    assert pages[0].items == (preset,)
    assert pages[0].next_page_token == ""
    assert [request.url.path for request in transport.requests] == ["/rpc/getSparkResourcePreset"] * 2 + [
        "/rpc/listSparkResourcePresets"
    ]
    assert transport.bodies() == [
        {"resourcePresetId": "preset-1", "cloudEnvironmentId": "environment-1"},
        {"resourcePresetId": "preset-1", "cloudEnvironmentId": "environment-1"},
        {"cloudEnvironmentId": "environment-1", "pageSize": 100},
    ]


def test_spark_get_rejects_empty_identifiers_before_http() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    with client:
        for operation, call in (
            ("getSparkCluster", lambda: service.get_spark_cluster("")),
            (
                "getSparkResourcePreset",
                lambda: service.get_spark_resource_preset("", cloud_environment_id="environment-1"),
            ),
            ("getSparkResourcePreset", lambda: service.get_spark_resource_preset("preset-1", cloud_environment_id="")),
        ):
            with pytest.raises((DataLensValidationError, DTOValidationError), match=operation):
                call()
    assert transport.requests == []


def test_spark_cluster_list_is_lazy_resumable_and_detects_token_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport(
        [
            httpx.Response(503, json={"message": "retry"}),
            httpx.Response(200, json={"sparkClusters": [_cluster_response()], "nextPageToken": "B", "futureRoot": 1}),
            httpx.Response(200, json={"sparkClusters": [], "nextPageToken": ""}),
            httpx.Response(200, json=_cluster_response()),
        ]
    )
    monkeypatch.setattr("datalens_sdk.http.time.sleep", lambda _: None)
    client, service = _service(transport)
    options = SparkClusterListOptions.create(
        installation="yacloud", collection="collection-1", filters=["status=RUNNING"], page_size=1, page_token="A"
    )
    with client:
        pager = service.list_spark_clusters(options)
        assert transport.requests == []
        pages = list(pager.pages())
        refreshed = pages[0].items[0].refresh()
    assert [page.next_page_token for page in pages] == ["B", ""]
    assert refreshed == pages[0].items[0]
    assert transport.bodies() == [
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 1, "pageToken": "A"}
    ] * 2 + [
        {"collectionId": "collection-1", "filter": ["status=RUNNING"], "pageSize": 1, "pageToken": "B"},
        {"id": "public-1"},
    ]

    for tokens in (("A",), ("B", "A")):
        cycle = _Transport(
            [httpx.Response(200, json={"sparkClusters": [], "nextPageToken": token}) for token in tokens]
        )
        cycle_client, cycle_service = _service(cycle)
        with cycle_client, pytest.raises(InvalidResponseError, match="listSparkClusters"):
            list(
                cycle_service.list_spark_clusters(
                    SparkClusterListOptions.create(installation="yacloud", page_token="A")
                ).pages()
            )
        assert len(cycle.requests) == len(tokens)


def test_spark_resource_preset_list_is_lazy_and_detects_repeated_token(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport(
        [
            httpx.Response(503, json={"message": "retry"}),
            httpx.Response(200, json={"resourcePresets": [], "nextPageToken": "B"}),
            httpx.Response(200, json={"resourcePresets": [], "nextPageToken": ""}),
        ]
    )
    monkeypatch.setattr("datalens_sdk.http.time.sleep", lambda _: None)
    client, service = _service(transport)
    with client:
        pager = service.list_spark_resource_presets(
            SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_token="A")
        )
        assert transport.requests == []
        pages = list(pager.pages())
    assert [page.next_page_token for page in pages] == ["B", ""]
    assert transport.bodies() == [{"cloudEnvironmentId": "environment-1", "pageSize": 100, "pageToken": "A"}] * 2 + [
        {"cloudEnvironmentId": "environment-1", "pageSize": 100, "pageToken": "B"}
    ]

    for tokens in (("A",), ("B", "A")):
        cycle = _Transport(
            [httpx.Response(200, json={"resourcePresets": [], "nextPageToken": token}) for token in tokens]
        )
        cycle_client, cycle_service = _service(cycle)
        with cycle_client, pytest.raises(InvalidResponseError, match="listSparkResourcePresets"):
            list(
                cycle_service.list_spark_resource_presets(
                    SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_token="A")
                ).pages()
            )
        assert len(cycle.requests) == len(tokens)


def test_spark_cluster_list_rejects_python_field_name_in_wire_response() -> None:
    transport = _Transport([httpx.Response(200, json={"spark_clusters": [], "nextPageToken": ""})])
    client, service = _service(transport)

    with client, pytest.raises(DTOValidationError, match="listSparkClusters") as raised:
        list(service.list_spark_clusters(SparkClusterListOptions.create(installation="yacloud")).pages())
    assert "sparkClusters" in str(raised.value)
    assert transport.bodies() == [{"pageSize": 100}]


@pytest.mark.parametrize("operation", ["getSparkCluster", "listSparkClusters"])
def test_spark_cluster_reads_reject_nested_python_field_name_in_wire_response(operation: str) -> None:
    raw_cluster = _cluster_response()
    config = cast(dict[str, object], raw_cluster["config"])
    config["resource_pools"] = config.pop("resourcePools")
    response = raw_cluster if operation == "getSparkCluster" else {"sparkClusters": [raw_cluster], "nextPageToken": ""}
    transport = _Transport([httpx.Response(200, json=response)])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))

    def read_cluster() -> None:
        if operation == "getSparkCluster":
            client.get.spark_cluster(by_id="public-1")
        else:
            list(client.list.spark_clusters())

    with client, pytest.raises(DTOValidationError, match=operation) as raised:
        read_cluster()

    assert "resourcePools" in str(raised.value)
    assert [request.url.path for request in transport.requests] == [f"/rpc/{operation}"]


def test_spark_resource_preset_list_rejects_python_field_name_in_wire_response() -> None:
    transport = _Transport([httpx.Response(200, json={"resource_presets": [], "nextPageToken": ""})])
    client, service = _service(transport)

    with client, pytest.raises(DTOValidationError, match="listSparkResourcePresets") as raised:
        list(
            service.list_spark_resource_presets(
                SparkResourcePresetListOptions.create(cloud_environment_id="environment-1")
            ).pages()
        )
    assert "resourcePresets" in str(raised.value)
    assert transport.bodies() == [{"cloudEnvironmentId": "environment-1", "pageSize": 100}]


def test_spark_list_request_dtos_validate_at_first_iteration() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    invalid = (
        (
            "listSparkClusters",
            lambda: service.list_spark_clusters(SparkClusterListOptions.create(installation="yacloud", page_size=-1)),
        ),
        (
            "listSparkClusters",
            lambda: service.list_spark_clusters(
                SparkClusterListOptions.create(installation="yacloud", page_token=cast(str, 1))
            ),
        ),
        (
            "listSparkResourcePresets",
            lambda: service.list_spark_resource_presets(
                SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_size=-1)
            ),
        ),
        (
            "listSparkResourcePresets",
            lambda: service.list_spark_resource_presets(
                SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_size=1001)
            ),
        ),
        (
            "listSparkResourcePresets",
            lambda: service.list_spark_resource_presets(
                SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_token="x" * 101)
            ),
        ),
    )
    with client:
        for operation, create_pager in invalid:
            pager = create_pager()
            assert transport.requests == []
            with pytest.raises(DTOValidationError, match=operation):
                list(pager)
    assert transport.requests == []

    valid = _Transport(
        [
            httpx.Response(200, json={"sparkClusters": [], "nextPageToken": ""}),
            httpx.Response(200, json={"resourcePresets": [], "nextPageToken": ""}),
        ]
    )
    valid_client, valid_service = _service(valid)
    with valid_client:
        list(
            valid_service.list_spark_clusters(
                SparkClusterListOptions.create(installation="yacloud", page_size=0, page_token="")
            )
        )
        list(
            valid_service.list_spark_resource_presets(
                SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_size=0, page_token="")
            )
        )
    assert valid.bodies() == [
        {"pageSize": 0, "pageToken": ""},
        {"cloudEnvironmentId": "environment-1", "pageSize": 0, "pageToken": ""},
    ]


@pytest.mark.parametrize("operation", ["listSparkClusters", "listSparkResourcePresets"])
def test_spark_lists_reject_unhashable_page_token_with_operation_dto_error(operation: str) -> None:
    transport = _Transport([])
    client, service = _service(transport)
    pager: Pager[SparkCluster | SparkResourcePreset]
    if operation == "listSparkClusters":
        pager = service.list_spark_clusters(
            SparkClusterListOptions.create(installation="yacloud", page_token=cast(str, ["A"]))
        )
    else:
        pager = service.list_spark_resource_presets(
            SparkResourcePresetListOptions.create(cloud_environment_id="environment-1", page_token=cast(str, ["A"]))
        )

    with client, pytest.raises(DTOValidationError, match=operation):
        list(pager)
    assert transport.requests == []


@pytest.mark.parametrize(
    ("operation", "raw"),
    [
        ("getSparkCluster", {"id": "public-1"}),
        ("getSparkCluster", {**_cluster_response(), "health": "FUTURE"}),
        ("getSparkCluster", {**_cluster_response(), "status": "FUTURE"}),
        (
            "getSparkCluster",
            {
                **_cluster_response(),
                "config": {**cast(dict[str, object], _cluster_response()["config"]), "dependencies": {}},
            },
        ),
        (
            "getSparkCluster",
            {
                **_cluster_response(),
                "config": {
                    **cast(dict[str, object], _cluster_response()["config"]),
                    "resourcePools": {
                        "driver": {"resourcePresetId": "driver-1", "scalePolicy": {"scaleType": "future"}},
                        "executor": cast(
                            dict[str, object], cast(dict[str, object], _cluster_response()["config"])["resourcePools"]
                        )["executor"],
                    },
                },
            },
        ),
        ("getSparkResourcePreset", {"id": "preset-1", "cores": None, "memory": "8GiB"}),
        ("listSparkClusters", {"sparkClusters": []}),
        ("listSparkResourcePresets", {"resourcePresets": "wrong", "nextPageToken": ""}),
    ],
)
def test_spark_read_responses_reject_missing_or_malformed_fields_with_operation(
    operation: str, raw: dict[str, object]
) -> None:
    transport = _Transport([httpx.Response(200, json=raw)])
    client, service = _service(transport)

    def call() -> None:
        if operation == "getSparkCluster":
            service.get_spark_cluster("public-1")
        elif operation == "getSparkResourcePreset":
            service.get_spark_resource_preset("preset-1", cloud_environment_id="environment-1")
        elif operation == "listSparkClusters":
            list(service.list_spark_clusters(SparkClusterListOptions.create(installation="yacloud")))
        else:
            list(
                service.list_spark_resource_presets(
                    SparkResourcePresetListOptions.create(cloud_environment_id="environment-1")
                )
            )

    with client, pytest.raises((DTOValidationError, InvalidResponseError), match=operation):
        call()


@pytest.mark.parametrize(
    "scale_policy",
    [
        {"scaleType": "fixedScale", "fixedScale": {}},
        {"scaleType": "autoScale", "autoScale": {"minSize": "0", "maxSize": "10"}},
    ],
    ids=["fixed-scale-missing-size", "auto-scale-missing-initial-size"],
)
def test_spark_get_rejects_known_scale_type_with_malformed_branch(scale_policy: dict[str, object]) -> None:
    raw = _cluster_response()
    config = cast(dict[str, object], raw["config"])
    pools = cast(dict[str, object], config["resourcePools"])
    driver = cast(dict[str, object], pools["driver"])
    driver["scalePolicy"] = scale_policy
    transport = _Transport([httpx.Response(200, json=raw)])
    client, service = _service(transport)

    with client, pytest.raises((DTOValidationError, InvalidResponseError), match="getSparkCluster"):
        service.get_spark_cluster("public-1")
    assert len(transport.requests) == 1
