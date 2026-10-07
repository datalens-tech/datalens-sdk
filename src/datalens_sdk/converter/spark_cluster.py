from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import Page
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
    SparkScalePolicy,
)
from datalens_sdk.errors import translate_invalid_response_error


class SparkClusterWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class SparkClusterWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> SparkClusterWriteDTOProtocol: ...


class SparkClusterReadDTOProtocol(Protocol):
    def model_dump(self, *, mode: Literal["json"], by_alias: bool) -> dict[str, object]: ...


class SparkClusterReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> SparkClusterReadDTOProtocol: ...


class SparkClusterDtoModule(Protocol):
    GetSparkClusterArgsDTO: SparkClusterWriteDTOClass
    ListSparkClustersArgsDTO: SparkClusterWriteDTOClass
    GetSparkResourcePresetArgsDTO: SparkClusterWriteDTOClass
    ListSparkResourcePresetsArgsDTO: SparkClusterWriteDTOClass
    SparkClusterReadDTO: SparkClusterReadDTOClass
    ListSparkClustersResultReadDTO: SparkClusterReadDTOClass
    SparkResourcePresetReadDTO: SparkClusterReadDTOClass
    ListSparkResourcePresetsResultReadDTO: SparkClusterReadDTOClass


def _dto_module(dto_module: SparkClusterDtoModule | None) -> SparkClusterDtoModule:
    return cast(SparkClusterDtoModule, generated_dto if dto_module is None else dto_module)


def _mapping(value: object, *, operation: str, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise translate_invalid_response_error(operation=operation, reason=f"{field} is not an object")
    return cast(Mapping[str, object], value)


def _wire_sequence(raw: Mapping[str, object], *, operation: str, field: str) -> list[object]:
    if field not in raw:
        raise translate_invalid_response_error(operation=operation, reason=f"{field} wire key is missing")
    value = raw[field]
    if not isinstance(value, list):
        raise translate_invalid_response_error(operation=operation, reason=f"{field} is not an array")
    return value


def _scale_policy(raw: Mapping[str, object]) -> SparkScalePolicy:
    if raw["scaleType"] == "fixedScale":
        fixed = cast(Mapping[str, object], raw["fixedScale"])
        return SparkFixedScalePolicy(size=int(cast(str, fixed["size"])))
    auto = cast(Mapping[str, object], raw["autoScale"])
    return SparkAutoScalePolicy(
        min_size=int(cast(str, auto["minSize"])),
        max_size=int(cast(str, auto["maxSize"])),
        initial_size=int(cast(str, auto["initialSize"])),
    )


def _pool(raw: Mapping[str, object]) -> SparkResourcePoolConfig:
    return SparkResourcePoolConfig(
        resource_preset_id=cast(str, raw["resourcePresetId"]),
        scale_policy=_scale_policy(cast(Mapping[str, object], raw["scalePolicy"])),
    )


class SparkClusterConverter:
    @staticmethod
    def get_payload(
        spark_cluster_id: str, *, dto_module: SparkClusterDtoModule | None = None
    ) -> SparkClusterWriteDTOProtocol:
        return _dto_module(dto_module).GetSparkClusterArgsDTO.model_validate({"id": spark_cluster_id})

    @staticmethod
    def list_payload(
        options: SparkClusterListOptions,
        *,
        page_token: str | None,
        dto_module: SparkClusterDtoModule | None = None,
    ) -> SparkClusterWriteDTOProtocol:
        payload: dict[str, object] = {"pageSize": options.page_size}
        if options.collection_id is not None:
            payload["collectionId"] = options.collection_id
        if options.filters:
            payload["filter"] = list(options.filters)
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListSparkClustersArgsDTO.model_validate(payload)

    @staticmethod
    def get_resource_preset_payload(
        resource_preset_id: str,
        *,
        cloud_environment_id: str,
        dto_module: SparkClusterDtoModule | None = None,
    ) -> SparkClusterWriteDTOProtocol:
        return _dto_module(dto_module).GetSparkResourcePresetArgsDTO.model_validate(
            {"resourcePresetId": resource_preset_id, "cloudEnvironmentId": cloud_environment_id}
        )

    @staticmethod
    def list_resource_presets_payload(
        options: SparkResourcePresetListOptions,
        *,
        page_token: str | None,
        dto_module: SparkClusterDtoModule | None = None,
    ) -> SparkClusterWriteDTOProtocol:
        payload: dict[str, object] = {"cloudEnvironmentId": options.cloud_environment_id, "pageSize": options.page_size}
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListSparkResourcePresetsArgsDTO.model_validate(payload)

    @staticmethod
    def to_cluster(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: SparkClusterOperations | None,
        operation: Literal["getSparkCluster", "listSparkClusters"],
        dto_module: SparkClusterDtoModule | None = None,
    ) -> SparkCluster:
        validated = _dto_module(dto_module).SparkClusterReadDTO.model_validate(raw)
        data = validated.model_dump(mode="json", by_alias=True)
        try:
            config = cast(Mapping[str, object], data["config"])
            pools = cast(Mapping[str, object], config["resourcePools"])
            dependencies_raw = config["dependencies"]
            logging_raw = config["logging"]
            dependencies = None
            if dependencies_raw is not None:
                deps = cast(Mapping[str, object], dependencies_raw)
                dependencies = SparkClusterDependencies(
                    pip_packages=tuple(cast(list[str], deps["pipPackages"])),
                    deb_packages=tuple(cast(list[str], deps["debPackages"])),
                )
            logging = None
            if logging_raw is not None:
                logging = SparkLoggingConfig(enabled=cast(bool, cast(Mapping[str, object], logging_raw)["enabled"]))
            return SparkCluster(
                id=cast(str, data["id"]),
                cluster_id=cast(str, data["clusterId"]),
                installation=installation,
                location=EntryLocation.collection(cast(str, data["collectionId"])),
                cloud_environment_id=cast(str, data["cloudEnvironmentId"]),
                name=cast(str, data["name"]),
                description=cast(str, data["description"]),
                labels=cast(Mapping[str, str], data["labels"]),
                config=SparkClusterConfig(
                    spark_version=cast(str, config["sparkVersion"]),
                    resource_pools=SparkResourcePoolsConfig(
                        driver=_pool(cast(Mapping[str, object], pools["driver"])),
                        executor=_pool(cast(Mapping[str, object], pools["executor"])),
                    ),
                    dependencies=dependencies,
                    logging=logging,
                ),
                health=cast(Literal["HEALTH_UNKNOWN", "ALIVE", "DEAD", "DEGRADED"], data["health"]),
                status=cast(
                    Literal[
                        "STATUS_UNSPECIFIED",
                        "CREATING",
                        "RUNNING",
                        "UPDATING",
                        "ERROR",
                        "STOPPING",
                        "STOPPED",
                        "STARTING",
                    ],
                    data["status"],
                ),
                entry_id=cast(str, data["entryId"]),
                raw=dict(raw),
                _operations=operations,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation=operation, reason=str(exc)) from exc

    @staticmethod
    def to_resource_preset(
        raw: Mapping[str, object],
        *,
        installation: str,
        cloud_environment_id: str,
        operation: Literal["getSparkResourcePreset", "listSparkResourcePresets"],
        dto_module: SparkClusterDtoModule | None = None,
    ) -> SparkResourcePreset:
        data = (
            _dto_module(dto_module)
            .SparkResourcePresetReadDTO.model_validate(raw)
            .model_dump(mode="json", by_alias=True)
        )
        return SparkResourcePreset(
            id=cast(str, data["id"]),
            installation=installation,
            cloud_environment_id=cloud_environment_id,
            cores=cast(str, data["cores"]),
            memory=cast(str, data["memory"]),
            raw=dict(raw),
        )

    @staticmethod
    def to_cluster_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: SparkClusterOperations | None,
        dto_module: SparkClusterDtoModule | None = None,
    ) -> Page[SparkCluster]:
        operation: Literal["listSparkClusters"] = "listSparkClusters"
        data = (
            _dto_module(dto_module)
            .ListSparkClustersResultReadDTO.model_validate(raw)
            .model_dump(mode="json", by_alias=True)
        )
        clusters = _wire_sequence(raw, operation=operation, field="sparkClusters")
        return Page(
            items=tuple(
                SparkClusterConverter.to_cluster(
                    _mapping(item, operation=operation, field="sparkClusters item"),
                    installation=installation,
                    operations=operations,
                    operation=operation,
                    dto_module=dto_module,
                )
                for item in clusters
            ),
            next_page_token=cast(str, data["nextPageToken"]),
        )

    @staticmethod
    def to_resource_preset_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        cloud_environment_id: str,
        dto_module: SparkClusterDtoModule | None = None,
    ) -> Page[SparkResourcePreset]:
        operation: Literal["listSparkResourcePresets"] = "listSparkResourcePresets"
        data = (
            _dto_module(dto_module)
            .ListSparkResourcePresetsResultReadDTO.model_validate(raw)
            .model_dump(mode="json", by_alias=True)
        )
        presets = _wire_sequence(raw, operation=operation, field="resourcePresets")
        return Page(
            items=tuple(
                SparkClusterConverter.to_resource_preset(
                    _mapping(item, operation=operation, field="resourcePresets item"),
                    installation=installation,
                    cloud_environment_id=cloud_environment_id,
                    operation=operation,
                    dto_module=dto_module,
                )
                for item in presets
            ),
            next_page_token=cast(str, data["nextPageToken"]),
        )
