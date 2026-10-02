from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from datalens_sdk.api.spark_cluster import SparkClusterAPI, SparkClusterService
from datalens_sdk.domain import spark_cluster as spark_domain
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
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
    DataLensAPIError,
    DataLensConfigurationError,
    DataLensTransportError,
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


def test_spark_create_requires_collection_environment_and_both_pools() -> None:
    class ForeignCollection(EntryLocation):
        installation = "enterprise"

        def _as_entry_location(self) -> EntryLocation:
            return EntryLocation.collection("collection-1")

    class FakeOperations:
        creates = 0

        def create_spark_cluster(self, builder: object) -> LakehouseOperation:
            self.creates += 1
            return LakehouseOperation(id="operation-1", done=False, metadata={})

    operations = FakeOperations()
    empty_collection = EntryLocation.collection("collection-1")
    object.__setattr__(empty_collection, "value", "")
    for location in (
        EntryLocation.path("/"),
        EntryLocation.workbook("workbook-1"),
        empty_collection,
    ):
        with pytest.raises(DataLensValidationError):
            spark_domain.SparkClusterCreate(
                installation="yacloud",
                name="analytics",
                location=location,
                cloud_environment_id="environment-1",
                operations=cast(SparkClusterOperations, operations),
            )
    with pytest.raises(NotSupportedError):
        spark_domain.SparkClusterCreate(
            installation="yacloud",
            name="analytics",
            location=ForeignCollection(),
            cloud_environment_id="environment-1",
            operations=cast(SparkClusterOperations, operations),
        )
    with pytest.raises(DataLensValidationError):
        spark_domain.SparkClusterCreate(
            installation="yacloud",
            name="analytics",
            location=EntryLocation.collection("collection-1"),
            cloud_environment_id="",
            operations=cast(SparkClusterOperations, operations),
        )
    builder = spark_domain.SparkClusterCreate(
        installation="yacloud",
        name="analytics",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        operations=cast(SparkClusterOperations, operations),
    )
    with pytest.raises(DataLensValidationError, match="driver"):
        builder.build()
    builder.driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(size=1))
    with pytest.raises(DataLensValidationError, match="executor"):
        builder.build()
    builder.executor(resource_preset="executor-1", scale_policy=SparkFixedScalePolicy(size=1))
    assert builder.build().id == "operation-1"
    assert operations.creates == 1


def test_spark_create_validates_both_preset_references_and_policy_types() -> None:
    class FakeOperations:
        creates = 0

        def create_spark_cluster(self, builder: object) -> LakehouseOperation:
            self.creates += 1
            return LakehouseOperation(id="operation-1", done=False, metadata={})

    operations = FakeOperations()
    builder = spark_domain.SparkClusterCreate(
        installation="yacloud",
        name="analytics",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        operations=cast(SparkClusterOperations, operations),
    )
    policy = SparkFixedScalePolicy(size=1)
    preset = SparkResourcePreset("preset-1", "yacloud", "environment-1", "2", "8GiB", {})
    for pool in (builder.driver, builder.executor):
        for invalid in (
            "",
            replace(preset, id=""),
            replace(preset, installation=""),
            replace(preset, installation="enterprise"),
            replace(preset, cloud_environment_id="environment-2"),
        ):
            with pytest.raises(DataLensValidationError):
                pool(resource_preset=invalid, scale_policy=policy)
        with pytest.raises(DataLensValidationError):
            pool(resource_preset="preset-1", scale_policy=cast(SparkFixedScalePolicy, object()))
    assert operations.creates == 0
    builder.driver(resource_preset="driver-1", scale_policy=policy)
    builder.executor(resource_preset=preset, scale_policy=SparkAutoScalePolicy(0, 10, 2))
    spec = builder.to_spec()
    assert spec.driver == SparkResourcePoolConfig("driver-1", policy)
    assert spec.executor == SparkResourcePoolConfig("preset-1", SparkAutoScalePolicy(0, 10, 2))
    builder.driver(resource_preset=preset, scale_policy=policy)
    builder.executor(resource_preset="executor-2", scale_policy=policy)
    assert builder.to_spec().driver == SparkResourcePoolConfig("preset-1", policy)
    assert builder.to_spec().executor == SparkResourcePoolConfig("executor-2", policy)


def test_spark_create_preserves_dependency_and_optional_setter_intent() -> None:
    builder = spark_domain.SparkClusterCreate(
        installation="yacloud",
        name="analytics",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        operations=None,
    )
    builder.driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(1))
    builder.executor(resource_preset="executor-1", scale_policy=SparkFixedScalePolicy(1))
    untouched = builder.to_spec()
    assert untouched.dependencies_configured is False
    assert (untouched.pip_packages, untouched.deb_packages) == (None, None)
    assert (untouched.logging_enabled, untouched.spark_version, untouched.description, untouched.labels) == (
        None,
        None,
        None,
        None,
    )
    builder.dependencies()
    empty_object = builder.to_spec()
    assert empty_object.dependencies_configured is True
    assert (empty_object.pip_packages, empty_object.deb_packages) == (None, None)
    builder.dependencies(pip_packages=None, deb_packages=[])
    with_one_empty_array = builder.to_spec()
    assert (with_one_empty_array.pip_packages, with_one_empty_array.deb_packages) == (None, ())
    for invalid in ("pandas", b"pandas"):
        with pytest.raises(DataLensValidationError):
            builder.dependencies(pip_packages=cast(Sequence[str], invalid), deb_packages=["lib"])
        with pytest.raises(DataLensValidationError):
            builder.dependencies(pip_packages=["pandas"], deb_packages=cast(Sequence[str], invalid))
        assert builder.to_spec() == with_one_empty_array
    builder.logging(enabled=False).spark_version("").description("").labels({})
    explicit = builder.to_spec()
    assert (explicit.logging_enabled, explicit.spark_version, explicit.description, explicit.labels) == (
        False,
        "",
        "",
        {},
    )
    with pytest.raises(DataLensConfigurationError):
        builder.build()


def test_spark_create_labels_snapshot_ignores_caller_and_prior_spec_mutations() -> None:
    builder = spark_domain.SparkClusterCreate(
        installation="yacloud",
        name="analytics",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        operations=None,
    )
    builder.driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(1))
    builder.executor(resource_preset="executor-1", scale_policy=SparkFixedScalePolicy(1))
    labels = {"team": "analytics"}
    builder.labels(labels)
    labels["team"] = "caller-mutated"
    first = builder.to_spec()
    assert first.labels == {"team": "analytics"}
    cast(dict[str, str], first.labels)["team"] = "spec-mutated"
    assert builder.to_spec().labels == {"team": "analytics"}


@pytest.mark.parametrize(
    "invalid",
    [None, 42, [("team", "other")], {42: "other"}, {"team": 42}],
)
def test_spark_create_labels_reject_invalid_mapping_without_changing_prior_value(invalid: object) -> None:
    builder = spark_domain.SparkClusterCreate(
        installation="yacloud",
        name="analytics",
        location=EntryLocation.collection("collection-1"),
        cloud_environment_id="environment-1",
        operations=None,
    )
    builder.driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(1))
    builder.executor(resource_preset="executor-1", scale_policy=SparkFixedScalePolicy(1))
    builder.labels({"team": "analytics"})

    with pytest.raises(DataLensValidationError, match="labels must map strings to strings"):
        builder.labels(cast(Mapping[str, str], invalid))

    assert builder.to_spec().labels == {"team": "analytics"}


def test_spark_bound_lifecycle_requires_operations_and_its_exact_identifier() -> None:
    class FakeOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def start_spark_cluster(self, cluster_id: str) -> LakehouseOperation:
            self.calls.append(("start", cluster_id))
            return LakehouseOperation(id="start-1", done=False, metadata={})

        def stop_spark_cluster(self, cluster_id: str) -> LakehouseOperation:
            self.calls.append(("stop", cluster_id))
            return LakehouseOperation(id="stop-1", done=False, metadata={})

        def delete_spark_cluster(self, spark_cluster_id: str) -> LakehouseOperation:
            self.calls.append(("delete", spark_cluster_id))
            return LakehouseOperation(id="delete-1", done=False, metadata={})

    source = _cluster()
    for method in (source.start, source.stop, source.delete):
        with pytest.raises(DataLensConfigurationError):
            method()
    operations = FakeOperations()
    bound = replace(source, _operations=cast(SparkClusterOperations, operations))
    with pytest.raises(DataLensValidationError):
        replace(bound, id="").delete()
    empty_managed = replace(bound, cluster_id="")
    for method in (empty_managed.start, empty_managed.stop):
        with pytest.raises(DataLensValidationError):
            method()
    assert empty_managed.delete().id == "delete-1"
    assert bound.start().id == "start-1"
    assert bound.stop().id == "stop-1"
    assert operations.calls == [("delete", "public-1"), ("start", "managed-1"), ("stop", "managed-1")]


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
    def __init__(self, responses: Sequence[httpx.Response | httpx.TransportError]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, f"unexpected request: {request.url.path}"
        response = self.responses.pop(0)
        if isinstance(response, httpx.TransportError):
            raise response
        return response

    def bodies(self) -> list[dict[str, object]]:
        return [cast(dict[str, object], json.loads(request.content)) for request in self.requests]


def _service(transport: _Transport) -> tuple[DataLensHTTPClient, SparkClusterService]:
    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://spark.test",
        transport=httpx.MockTransport(transport.handle),
    )
    return client, SparkClusterService(
        installation="yacloud",
        api=SparkClusterAPI(client),
        lakehouse_operations=LakehouseOperationService(api=LakehouseOperationAPI(client)),
    )


def _create_builder(service: SparkClusterService) -> spark_domain.SparkClusterCreate:
    return (
        spark_domain.SparkClusterCreate(
            installation="yacloud",
            name="analytics-spark",
            location=EntryLocation.collection("collection-1"),
            cloud_environment_id="environment-1",
            operations=service,
        )
        .driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(size=1))
        .executor(resource_preset="executor-1", scale_policy=SparkAutoScalePolicy(0, 10, 2))
    )


def test_spark_create_sends_both_scale_branches_and_returns_bound_operation() -> None:
    response = {
        "id": "operation-1",
        "done": False,
        "metadata": {"cluster": "analytics-spark"},
        "createdBy": "user-1",
    }
    transport = _Transport([httpx.Response(200, json=response), httpx.Response(200, json=response)])
    http_client, service = _service(transport)
    with http_client:
        operation = _create_builder(service).build()
        assert isinstance(operation, LakehouseOperation)
        assert operation.id == "operation-1"
        assert operation.done is False
        assert operation.metadata == {"cluster": "analytics-spark"}
        assert operation.created_by == "user-1"
        assert [request.url.path for request in transport.requests] == ["/rpc/createSparkCluster"]
        refreshed = operation.refresh()
    assert refreshed.id == "operation-1"
    assert [request.url.path for request in transport.requests] == [
        "/rpc/createSparkCluster",
        "/rpc/getLakehouseOperation",
    ]
    assert transport.bodies() == [
        {
            "collectionId": "collection-1",
            "cloudEnvironmentId": "environment-1",
            "name": "analytics-spark",
            "config": {
                "resourcePools": {
                    "driver": {
                        "resourcePresetId": "driver-1",
                        "scalePolicy": {"fixedScale": {"size": "1"}},
                    },
                    "executor": {
                        "resourcePresetId": "executor-1",
                        "scalePolicy": {"autoScale": {"minSize": "0", "initialSize": "2", "maxSize": "10"}},
                    },
                }
            },
        },
        {"operationId": "operation-1"},
    ]


def test_spark_create_preserves_dependency_and_explicit_falsy_payloads() -> None:
    operation_response = {"id": "operation-1", "done": False, "metadata": {}}
    transport = _Transport([httpx.Response(200, json=operation_response) for _ in range(5)])
    http_client, service = _service(transport)
    with http_client:
        _create_builder(service).build()
        _create_builder(service).dependencies().build()
        _create_builder(service).dependencies(pip_packages=None, deb_packages=[]).build()
        (_create_builder(service).logging(enabled=False).spark_version("").description("").labels({}).build())
        _create_builder(service).dependencies(pip_packages=["pandas==2.2.3"], deb_packages=["libpq5"]).build()
    bodies = transport.bodies()
    assert "dependencies" not in cast(dict[str, object], bodies[0]["config"])
    assert cast(dict[str, object], bodies[1]["config"])["dependencies"] == {}
    assert cast(dict[str, object], bodies[2]["config"])["dependencies"] == {"debPackages": []}
    config = cast(dict[str, object], bodies[3]["config"])
    assert config["logging"] == {"enabled": False}
    assert config["sparkVersion"] == ""
    assert "dependencies" not in config
    assert bodies[3]["description"] == ""
    assert bodies[3]["labels"] == {}
    assert cast(dict[str, object], bodies[4]["config"])["dependencies"] == {
        "pipPackages": ["pandas==2.2.3"],
        "debPackages": ["libpq5"],
    }


@pytest.mark.parametrize(
    ("driver_size", "min_size", "initial_size", "max_size"),
    [
        (0, 0, 2, 10),
        (101, 0, 2, 10),
        (1, -1, 2, 10),
        (1, 0, -1, 10),
        (1, 0, 101, 10),
        (1, 0, 2, 0),
        (1, 0, 2, 101),
    ],
)
def test_spark_create_generated_dto_enforces_independent_scale_ranges_before_http(
    driver_size: int, min_size: int, initial_size: int, max_size: int
) -> None:
    transport = _Transport([])
    http_client, service = _service(transport)
    builder = _create_builder(service)
    builder.driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(size=driver_size))
    builder.executor(
        resource_preset="executor-1",
        scale_policy=SparkAutoScalePolicy(min_size=min_size, initial_size=initial_size, max_size=max_size),
    )
    with http_client, pytest.raises(DTOValidationError, match="createSparkCluster"):
        builder.build()
    assert transport.requests == []


def test_spark_create_does_not_invent_auto_scale_ordering_constraint() -> None:
    valid_transport = _Transport([httpx.Response(200, json={"id": "operation-2", "done": False, "metadata": {}})])
    valid_client, valid_service = _service(valid_transport)
    valid_builder = _create_builder(valid_service)
    valid_builder.executor(
        resource_preset="executor-1", scale_policy=SparkAutoScalePolicy(min_size=10, initial_size=1, max_size=2)
    )
    with valid_client:
        assert valid_builder.build().id == "operation-2"
    assert len(valid_transport.requests) == 1


def test_spark_start_stop_delete_use_distinct_identifiers_and_bound_operations() -> None:
    operation = {"id": "operation-1", "done": False, "metadata": {}}
    stopped = {
        "id": "operation-2",
        "done": True,
        "metadata": {},
        "error": {"code": 9, "message": "cluster is busy", "details": []},
    }
    transport = _Transport(
        [httpx.Response(200, json=raw) for raw in (_cluster_response(), operation, stopped, operation, operation)]
    )
    client, service = _service(transport)
    with client:
        cluster = service.get_spark_cluster("public-1")
        started = cluster.start()
        stopped_operation = cluster.stop()
        deleted = cluster.delete()
        assert [request.url.path for request in transport.requests] == [
            "/rpc/getSparkCluster",
            "/rpc/startSparkCluster",
            "/rpc/stopSparkCluster",
            "/rpc/deleteSparkCluster",
        ]
        assert started.refresh().id == "operation-1"

    assert transport.requests[-1].url.path == "/rpc/getLakehouseOperation"
    assert transport.bodies()[1:] == [
        {"clusterId": "managed-1"},
        {"clusterId": "managed-1"},
        {"id": "public-1"},
        {"operationId": "operation-1"},
    ]
    assert started == LakehouseOperation(
        id="operation-1",
        done=False,
        metadata={},
        raw=operation,
    )
    assert stopped_operation.done is True
    assert stopped_operation.error is not None
    assert stopped_operation.error.code == 9
    assert stopped_operation.error.message == "cluster is busy"
    assert deleted.id == "operation-1"


def test_spark_empty_managed_id_can_delete_but_cannot_start_or_stop() -> None:
    transport = _Transport(
        [
            httpx.Response(200, json=_cluster_response(cluster_id="")),
            httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}}),
        ]
    )
    client, service = _service(transport)
    with client:
        cluster = service.get_spark_cluster("public-1")
        with pytest.raises(DataLensValidationError):
            cluster.start()
        with pytest.raises(DataLensValidationError):
            cluster.stop()
        assert len(transport.requests) == 1
        assert cluster.delete().id == "operation-1"
    assert [request.url.path for request in transport.requests] == ["/rpc/getSparkCluster", "/rpc/deleteSparkCluster"]
    assert transport.bodies()[1] == {"id": "public-1"}


@pytest.mark.parametrize("operation", ["startSparkCluster", "stopSparkCluster", "deleteSparkCluster"])
def test_spark_lifecycle_generated_dto_rejects_overlong_identifier_before_http(operation: str) -> None:
    transport = _Transport([])
    client, service = _service(transport)
    cluster = replace(_cluster(cluster_id="x" * 51, id="x" * 51), _operations=service)
    calls = {
        "startSparkCluster": cluster.start,
        "stopSparkCluster": cluster.stop,
        "deleteSparkCluster": cluster.delete,
    }
    with client, pytest.raises(DTOValidationError, match=operation):
        calls[operation]()
    assert transport.requests == []


@pytest.mark.parametrize(
    "operation", ["createSparkCluster", "startSparkCluster", "stopSparkCluster", "deleteSparkCluster"]
)
def test_spark_mutations_make_one_attempt_on_transient_failure(operation: str) -> None:
    transport = _Transport(
        [
            httpx.Response(
                503,
                json={"code": "TEMPORARY", "message": "try later"},
                headers={"x-request-id": "spark-temporary"},
            )
        ]
    )
    client, service = _service(transport)
    cluster = replace(_cluster(), _operations=service)
    calls = {
        "createSparkCluster": lambda: _create_builder(service).build(),
        "startSparkCluster": cluster.start,
        "stopSparkCluster": cluster.stop,
        "deleteSparkCluster": cluster.delete,
    }
    with client, pytest.raises(DataLensAPIError) as raised:
        calls[operation]()
    assert [request.url.path for request in transport.requests] == [f"/rpc/{operation}"]
    assert raised.value.context.code == "TEMPORARY"
    assert raised.value.context.request_id == "spark-temporary"
    assert raised.value.context.attempts == 1


@pytest.mark.parametrize(
    "operation", ["createSparkCluster", "startSparkCluster", "stopSparkCluster", "deleteSparkCluster"]
)
def test_spark_mutations_do_not_retry_after_transport_error(operation: str) -> None:
    transport = _Transport(
        [
            httpx.ConnectError("connection lost"),
            httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}}),
        ]
    )
    client, service = _service(transport)
    cluster = replace(_cluster(), _operations=service)
    calls = {
        "createSparkCluster": lambda: _create_builder(service).build(),
        "startSparkCluster": cluster.start,
        "stopSparkCluster": cluster.stop,
        "deleteSparkCluster": cluster.delete,
    }
    with client, pytest.raises(DataLensTransportError) as raised:
        calls[operation]()

    assert [request.url.path for request in transport.requests] == [f"/rpc/{operation}"]
    assert raised.value.url.endswith(f"/rpc/{operation}")
    assert raised.value.attempts == 1


@pytest.mark.parametrize(
    "operation", ["createSparkCluster", "startSparkCluster", "stopSparkCluster", "deleteSparkCluster"]
)
@pytest.mark.parametrize(
    "raw",
    [
        {"id": "operation-1", "done": False},
        {"id": "operation-1", "done": False, "metadata": {}, "createdAt": {"seconds": "1", "nanos": "invalid"}},
        {"id": "operation-1", "done": True, "metadata": {}, "error": {"code": "invalid", "message": "failed"}},
    ],
    ids=["missing-metadata", "invalid-timestamp", "invalid-error"],
)
def test_spark_mutations_report_operation_specific_invalid_responses(operation: str, raw: dict[str, object]) -> None:
    transport = _Transport([httpx.Response(200, json=raw)])
    client, service = _service(transport)
    cluster = replace(_cluster(), _operations=service)
    calls = {
        "createSparkCluster": lambda: _create_builder(service).build(),
        "startSparkCluster": cluster.start,
        "stopSparkCluster": cluster.stop,
        "deleteSparkCluster": cluster.delete,
    }
    with client, pytest.raises((DTOValidationError, InvalidResponseError), match=operation):
        calls[operation]()
    assert [request.url.path for request in transport.requests] == [f"/rpc/{operation}"]


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


def test_spark_create_yateam_style_base_client_has_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert type(client.create) is client_module.CreateNamespace
        assert type(client.get) is client_module.GetNamespace
        assert type(client.list) is client_module.ListNamespace
        for namespace, names in (
            (client.create, ("spark_cluster",)),
            (client.get, ("spark_cluster", "spark_resource_preset")),
            (client.list, ("spark_clusters", "spark_resource_presets")),
        ):
            for name in names:
                with pytest.raises(AttributeError) as raised:
                    getattr(namespace, name)
                assert type(raised.value) is AttributeError
    assert transport.requests == []


def test_spark_lifecycle_surface_is_yc_only(monkeypatch: pytest.MonkeyPatch) -> None:
    operation_response = {"id": "operation-1", "done": False, "metadata": {}}
    yc_transport = _Transport([httpx.Response(200, json=operation_response)])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(yc_transport.handle))
    with client:
        operation = (
            client.create.spark_cluster(
                name="analytics-spark",
                location=EntryLocation.collection("collection-1"),
                cloud_environment_id="environment-1",
            )
            .driver(resource_preset="driver-1", scale_policy=SparkFixedScalePolicy(size=1))
            .executor(resource_preset="executor-1", scale_policy=SparkAutoScalePolicy(0, 10, 2))
            .build()
        )
    assert isinstance(operation, LakehouseOperation)
    assert operation.id == "operation-1"
    assert [request.url.path for request in yc_transport.requests] == ["/rpc/createSparkCluster"]
    assert yc_transport.bodies() == [
        {
            "collectionId": "collection-1",
            "cloudEnvironmentId": "environment-1",
            "name": "analytics-spark",
            "config": {
                "resourcePools": {
                    "driver": {"resourcePresetId": "driver-1", "scalePolicy": {"fixedScale": {"size": "1"}}},
                    "executor": {
                        "resourcePresetId": "executor-1",
                        "scalePolicy": {"autoScale": {"minSize": "0", "initialSize": "2", "maxSize": "10"}},
                    },
                }
            },
        }
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
        spark_action = "spark_cluster"
        with pytest.raises(AttributeError) as raised:
            getattr(enterprise.create, spark_action)
        assert type(raised.value) is AttributeError
    assert enterprise_transport.requests == []


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
