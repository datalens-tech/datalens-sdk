from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter.lakehouse_operation import LakehouseOperationReadDtoModule
from datalens_sdk.domain.entry_location import EntryLocation, collection_id_from_location
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.ports import TrinoClusterOperations
from datalens_sdk.domain.specs.trino_cluster import TrinoClusterCreateSpec
from datalens_sdk.domain.trino_cluster import (
    TrinoAutoScalePolicy,
    TrinoCatalogRef,
    TrinoCluster,
    TrinoClusterConfig,
    TrinoClusterHealth,
    TrinoClusterListOptions,
    TrinoClusterStatus,
    TrinoCoordinatorConfig,
    TrinoResourceConfig,
    TrinoResourcePreset,
    TrinoResourcePresetListOptions,
    TrinoWorkerConfig,
)
from datalens_sdk.errors import translate_invalid_response_error


class TrinoClusterWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class TrinoClusterWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> TrinoClusterWriteDTOProtocol: ...


class TrinoClusterReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> object: ...


class TrinoClusterDtoModule(LakehouseOperationReadDtoModule, Protocol):
    CreateTrinoClusterArgsDTO: TrinoClusterWriteDTOClass
    StartTrinoClusterArgsDTO: TrinoClusterWriteDTOClass
    StopTrinoClusterArgsDTO: TrinoClusterWriteDTOClass
    DeleteTrinoClusterArgsDTO: TrinoClusterWriteDTOClass
    GetTrinoClusterArgsDTO: TrinoClusterWriteDTOClass
    ListTrinoClustersArgsDTO: TrinoClusterWriteDTOClass
    GetTrinoResourcePresetArgsDTO: TrinoClusterWriteDTOClass
    ListTrinoResourcePresetsArgsDTO: TrinoClusterWriteDTOClass
    TrinoClusterReadDTO: TrinoClusterReadDTOClass
    ListTrinoClustersResultReadDTO: TrinoClusterReadDTOClass
    TrinoResourcePresetReadDTO: TrinoClusterReadDTOClass
    ListTrinoResourcePresetsResultReadDTO: TrinoClusterReadDTOClass


def _dto_module(dto_module: TrinoClusterDtoModule | None) -> TrinoClusterDtoModule:
    return cast(TrinoClusterDtoModule, generated_dto if dto_module is None else dto_module)


class _ResourceDTO(Protocol):
    resource_preset_id: str


class _CatalogDTO(Protocol):
    catalog_id: str


class _CoordinatorDTO(Protocol):
    resources: _ResourceDTO


class _AutoScaleDTO(Protocol):
    min_count: str
    max_count: str


class _ScalePolicyDTO(Protocol):
    auto_scale: _AutoScaleDTO


class _WorkerDTO(Protocol):
    resources: _ResourceDTO
    scale_policy: _ScalePolicyDTO


class _ConfigDTO(Protocol):
    trino_version: str
    catalogs_config: list[_CatalogDTO]
    coordinator_config: _CoordinatorDTO
    worker_config: _WorkerDTO


class _ClusterDTO(Protocol):
    id: str
    cluster_id: str
    collection_id: str
    cloud_environment_id: str
    name: str
    description: str
    labels: dict[str, str]
    config: _ConfigDTO
    health: TrinoClusterHealth
    status: TrinoClusterStatus
    coordinator_url: str
    entry_id: str


class _PresetDTO(Protocol):
    id: str
    cores: str
    memory: str


class _ClusterPageDTO(Protocol):
    next_page_token: str


class _PresetPageDTO(Protocol):
    next_page_token: str


class TrinoClusterConverter:
    @staticmethod
    def create_payload(
        spec: TrinoClusterCreateSpec,
        *,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        worker = spec.worker
        payload: dict[str, object] = {
            "collectionId": collection_id_from_location(spec.location),
            "cloudEnvironmentId": spec.cloud_environment_id,
            "name": spec.name,
            "workerConfig": {
                "resources": {"resourcePresetId": worker.resources.resource_preset_id},
                "scalePolicy": {
                    "autoScale": {
                        "minCount": str(worker.scale_policy.min_count),
                        "maxCount": str(worker.scale_policy.max_count),
                    }
                },
            },
        }
        if spec.description is not None:
            payload["description"] = spec.description
        if spec.labels is not None:
            payload["labels"] = dict(spec.labels)
        if spec.trino_version is not None:
            payload["trinoVersion"] = spec.trino_version
        return _dto_module(dto_module).CreateTrinoClusterArgsDTO.model_validate(payload)

    @staticmethod
    def start_payload(
        cluster_id: str,
        *,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        return _dto_module(dto_module).StartTrinoClusterArgsDTO.model_validate({"clusterId": cluster_id})

    @staticmethod
    def stop_payload(
        cluster_id: str,
        *,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        return _dto_module(dto_module).StopTrinoClusterArgsDTO.model_validate({"clusterId": cluster_id})

    @staticmethod
    def delete_payload(
        trino_cluster_id: str,
        *,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        return _dto_module(dto_module).DeleteTrinoClusterArgsDTO.model_validate({"id": trino_cluster_id})

    @staticmethod
    def get_payload(
        trino_cluster_id: str,
        *,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        return _dto_module(dto_module).GetTrinoClusterArgsDTO.model_validate({"id": trino_cluster_id})

    @staticmethod
    def list_payload(
        options: TrinoClusterListOptions,
        *,
        page_token: str | None,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        payload: dict[str, object] = {"pageSize": options.page_size}
        if options.collection_id is not None:
            payload["collectionId"] = options.collection_id
        if options.filters:
            payload["filter"] = list(options.filters)
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListTrinoClustersArgsDTO.model_validate(payload)

    @staticmethod
    def get_resource_preset_payload(
        resource_preset_id: str,
        *,
        cloud_environment_id: str,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        return _dto_module(dto_module).GetTrinoResourcePresetArgsDTO.model_validate(
            {"resourcePresetId": resource_preset_id, "cloudEnvironmentId": cloud_environment_id}
        )

    @staticmethod
    def list_resource_presets_payload(
        options: TrinoResourcePresetListOptions,
        *,
        page_token: str | None,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoClusterWriteDTOProtocol:
        payload: dict[str, object] = {
            "cloudEnvironmentId": options.cloud_environment_id,
            "pageSize": options.page_size,
        }
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListTrinoResourcePresetsArgsDTO.model_validate(payload)

    @staticmethod
    def to_cluster(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: TrinoClusterOperations | None,
        operation: Literal["getTrinoCluster", "listTrinoClusters"],
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoCluster:
        dto = cast(_ClusterDTO, _dto_module(dto_module).TrinoClusterReadDTO.model_validate(raw))
        try:
            config = dto.config
            return TrinoCluster(
                id=dto.id,
                cluster_id=dto.cluster_id,
                installation=installation,
                location=EntryLocation.collection(dto.collection_id),
                cloud_environment_id=dto.cloud_environment_id,
                name=dto.name,
                description=dto.description,
                labels=dto.labels,
                config=TrinoClusterConfig(
                    trino_version=config.trino_version,
                    catalogs=tuple(TrinoCatalogRef(catalog_id=item.catalog_id) for item in config.catalogs_config),
                    coordinator=TrinoCoordinatorConfig(
                        resources=TrinoResourceConfig(
                            resource_preset_id=config.coordinator_config.resources.resource_preset_id
                        )
                    ),
                    worker=TrinoWorkerConfig(
                        resources=TrinoResourceConfig(
                            resource_preset_id=config.worker_config.resources.resource_preset_id
                        ),
                        scale_policy=TrinoAutoScalePolicy(
                            min_count=int(config.worker_config.scale_policy.auto_scale.min_count),
                            max_count=int(config.worker_config.scale_policy.auto_scale.max_count),
                        ),
                    ),
                ),
                health=dto.health,
                status=dto.status,
                coordinator_url=dto.coordinator_url,
                entry_id=dto.entry_id,
                raw=dict(raw),
                _operations=operations,
            )
        except (TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation=operation, reason=str(exc)) from exc

    @staticmethod
    def to_resource_preset(
        raw: Mapping[str, object],
        *,
        installation: str,
        cloud_environment_id: str,
        operation: Literal["getTrinoResourcePreset", "listTrinoResourcePresets"],
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> TrinoResourcePreset:
        dto = cast(_PresetDTO, _dto_module(dto_module).TrinoResourcePresetReadDTO.model_validate(raw))
        return TrinoResourcePreset(
            id=dto.id,
            installation=installation,
            cloud_environment_id=cloud_environment_id,
            cores=dto.cores,
            memory=dto.memory,
            raw=dict(raw),
        )

    @staticmethod
    def to_cluster_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: TrinoClusterOperations | None,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> Page[TrinoCluster]:
        validated = cast(_ClusterPageDTO, _dto_module(dto_module).ListTrinoClustersResultReadDTO.model_validate(raw))
        items = cast(list[Mapping[str, object]], raw["clusters"])
        return Page(
            items=tuple(
                TrinoClusterConverter.to_cluster(
                    item,
                    installation=installation,
                    operations=operations,
                    operation="listTrinoClusters",
                    dto_module=dto_module,
                )
                for item in items
            ),
            next_page_token=validated.next_page_token,
        )

    @staticmethod
    def to_resource_preset_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        cloud_environment_id: str,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> Page[TrinoResourcePreset]:
        if "resourcePresets" not in raw:
            raise translate_invalid_response_error(
                operation="listTrinoResourcePresets", reason="missing required resourcePresets field"
            )
        validated = cast(
            _PresetPageDTO, _dto_module(dto_module).ListTrinoResourcePresetsResultReadDTO.model_validate(raw)
        )
        items = cast(list[Mapping[str, object]], raw["resourcePresets"])
        return Page(
            items=tuple(
                TrinoClusterConverter.to_resource_preset(
                    item,
                    installation=installation,
                    cloud_environment_id=cloud_environment_id,
                    operation="listTrinoResourcePresets",
                    dto_module=dto_module,
                )
                for item in items
            ),
            next_page_token=validated.next_page_token,
        )
