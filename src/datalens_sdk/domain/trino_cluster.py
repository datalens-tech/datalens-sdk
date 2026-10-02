from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from typing_extensions import Self

from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    resolve_entry_location,
)
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.ports import TrinoClusterOperations
from datalens_sdk.domain.rest_catalog import RestCatalog
from datalens_sdk.domain.specs.trino_cluster import TrinoClusterCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

TrinoClusterHealth: TypeAlias = Literal["HEALTH_UNKNOWN", "ALIVE", "DEAD", "DEGRADED"]
TrinoClusterStatus: TypeAlias = Literal[
    "STATUS_UNKNOWN",
    "CREATING",
    "RUNNING",
    "ERROR",
    "STOPPING",
    "STOPPED",
    "STARTING",
    "UPDATING",
]


def _catalog_id(
    catalog: RestCatalog | str,
    *,
    installation: str,
    cloud_environment_id: str | None = None,
) -> str:
    if isinstance(catalog, RestCatalog):
        if not isinstance(catalog.id, str) or not catalog.id:
            raise DataLensValidationError("catalog id must be a non-empty string")
        if not catalog.installation or catalog.installation != installation:
            raise DataLensValidationError("catalog installation does not match the client")
        if cloud_environment_id is not None and catalog.cloud_environment_id != cloud_environment_id:
            raise DataLensValidationError("catalog cloud_environment_id does not match the cluster")
        return catalog.id
    if not isinstance(catalog, str) or not catalog:
        raise DataLensValidationError("catalog must be a non-empty ID or RestCatalog")
    return catalog


@dataclass(frozen=True, slots=True)
class TrinoCatalogRef:
    catalog_id: str


@dataclass(frozen=True, slots=True)
class TrinoResourceConfig:
    resource_preset_id: str


@dataclass(frozen=True, slots=True)
class TrinoAutoScalePolicy:
    min_count: int
    max_count: int


@dataclass(frozen=True, slots=True)
class TrinoCoordinatorConfig:
    resources: TrinoResourceConfig


@dataclass(frozen=True, slots=True)
class TrinoWorkerConfig:
    resources: TrinoResourceConfig
    scale_policy: TrinoAutoScalePolicy


@dataclass(frozen=True, slots=True)
class TrinoClusterConfig:
    trino_version: str
    catalogs: tuple[TrinoCatalogRef, ...]
    coordinator: TrinoCoordinatorConfig
    worker: TrinoWorkerConfig


@dataclass(slots=True)
class TrinoCluster:
    id: str
    cluster_id: str
    installation: str
    location: EntryLocation
    cloud_environment_id: str
    name: str
    description: str
    labels: Mapping[str, str]
    config: TrinoClusterConfig
    health: TrinoClusterHealth
    status: TrinoClusterStatus
    coordinator_url: str
    entry_id: str
    raw: Mapping[str, object]
    _operations: TrinoClusterOperations | None = field(default=None, repr=False, compare=False)

    def refresh(self) -> TrinoCluster:
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Trino cluster id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster is not bound to client operations")
        return self._operations.get_trino_cluster(self.id)

    def start(self) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster is not bound to client operations")
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Trino cluster id must be a non-empty string")
        return self._operations.start_trino_cluster(self.id)

    def stop(self) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster is not bound to client operations")
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Trino cluster id must be a non-empty string")
        return self._operations.stop_trino_cluster(self.id)

    def delete(self) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster is not bound to client operations")
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Trino cluster id must be a non-empty string")
        return self._operations.delete_trino_cluster(self.id)

    def attach_catalog(self, catalog: RestCatalog | str) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster is not bound to client operations")
        if not isinstance(self.cluster_id, str) or not self.cluster_id:
            raise DataLensValidationError("Trino cluster cluster_id must be a non-empty string")
        return self._operations.attach_trino_cluster_catalog(self, catalog)

    def detach_catalog(self, catalog: RestCatalog | str) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster is not bound to client operations")
        if not isinstance(self.cluster_id, str) or not self.cluster_id:
            raise DataLensValidationError("Trino cluster cluster_id must be a non-empty string")
        return self._operations.detach_trino_cluster_catalog(self, catalog)


@dataclass(frozen=True, slots=True)
class TrinoResourcePreset:
    id: str
    installation: str
    cloud_environment_id: str
    cores: str
    memory: str
    raw: Mapping[str, object]


class TrinoClusterCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        cloud_environment_id: str,
        operations: TrinoClusterOperations | None = None,
    ) -> None:
        resolved = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"collection"},
            context="Trino cluster creation",
        )
        collection_id = collection_id_from_location(resolved)
        if not isinstance(collection_id, str) or not collection_id:
            raise DataLensValidationError("collection ID must be a non-empty string")
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("cloud_environment_id must be a non-empty string")
        self._installation = installation
        self._name = name
        self._location = resolved
        self._cloud_environment_id = cloud_environment_id
        self._operations = operations
        self._worker: TrinoWorkerConfig | None = None
        self._description: str | None = None
        self._labels: Mapping[str, str] | None = None
        self._trino_version: str | None = None
        self._catalog_ids: tuple[str, ...] | None = None

    def worker(
        self,
        *,
        resource_preset: TrinoResourcePreset | str,
        min_count: int,
        max_count: int,
    ) -> Self:
        if isinstance(resource_preset, TrinoResourcePreset):
            if not isinstance(resource_preset.id, str) or not resource_preset.id:
                raise DataLensValidationError("resource_preset id must be a non-empty string")
            if resource_preset.installation != self._installation:
                raise DataLensValidationError("resource_preset installation does not match the client")
            if resource_preset.cloud_environment_id != self._cloud_environment_id:
                raise DataLensValidationError("resource_preset cloud_environment_id does not match the cluster")
            resource_preset_id = resource_preset.id
        elif isinstance(resource_preset, str) and resource_preset:
            resource_preset_id = resource_preset
        else:
            raise DataLensValidationError("resource_preset must be a non-empty ID or TrinoResourcePreset")
        if type(min_count) is not int or type(max_count) is not int:
            raise DataLensValidationError("worker min_count and max_count must be integers")
        self._worker = TrinoWorkerConfig(
            resources=TrinoResourceConfig(resource_preset_id=resource_preset_id),
            scale_policy=TrinoAutoScalePolicy(min_count=min_count, max_count=max_count),
        )
        return self

    def description(self, value: str) -> Self:
        if not isinstance(value, str):
            raise DataLensValidationError("description must be a string")
        self._description = value
        return self

    def labels(self, values: Mapping[str, str]) -> Self:
        if not isinstance(values, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()
        ):
            raise DataLensValidationError("labels must map strings to strings")
        self._labels = dict(values)
        return self

    def trino_version(self, value: str) -> Self:
        if not isinstance(value, str):
            raise DataLensValidationError("trino_version must be a string")
        self._trino_version = value
        return self

    def catalogs(self, values: Sequence[RestCatalog | str]) -> Self:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise DataLensValidationError("catalogs must be a sequence of catalog references")
        self._catalog_ids = tuple(
            _catalog_id(value, installation=self._installation, cloud_environment_id=self._cloud_environment_id)
            for value in values
        )
        return self

    def to_spec(self) -> TrinoClusterCreateSpec:
        if self._worker is None:
            raise DataLensValidationError("Trino cluster creation requires worker configuration")
        return TrinoClusterCreateSpec(
            name=self._name,
            location=self._location,
            cloud_environment_id=self._cloud_environment_id,
            worker=self._worker,
            description=self._description,
            labels=None if self._labels is None else dict(self._labels),
            trino_version=self._trino_version,
            catalog_ids=self._catalog_ids,
        )

    def build(self) -> LakehouseOperation:
        self.to_spec()
        if self._operations is None:
            raise DataLensConfigurationError("Trino cluster creation is not bound to client operations")
        return self._operations.create_trino_cluster(self)


@dataclass(frozen=True, slots=True)
class TrinoClusterListOptions:
    collection_id: str | None = None
    filters: tuple[str, ...] = ()
    page_size: int = 100
    page_token: str | None = None
    catalog_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        installation: str,
        catalog: RestCatalog | str | None = None,
        collection: EntryLocation | str | None = None,
        filters: Sequence[str] = (),
        page_size: int = 100,
        page_token: str | None = None,
    ) -> TrinoClusterListOptions:
        if isinstance(collection, EntryLocation):
            resolved = resolve_entry_location(
                location=collection,
                installation=installation,
                allowed_kinds={"collection"},
                context="Trino cluster list",
            )
            collection_id = collection_id_from_location(resolved)
        elif collection is None:
            collection_id = None
        elif isinstance(collection, str) and collection:
            collection_id = collection
        else:
            raise DataLensValidationError("collection must be a non-empty collection ID or collection location")

        if isinstance(filters, (str, bytes)) or not isinstance(filters, Sequence):
            raise DataLensValidationError("filters must be a sequence of strings, not a scalar string")
        return cls(
            catalog_id=None if catalog is None else _catalog_id(catalog, installation=installation),
            collection_id=collection_id,
            filters=tuple(filters),
            page_size=page_size,
            page_token=page_token,
        )


@dataclass(frozen=True, slots=True)
class TrinoResourcePresetListOptions:
    cloud_environment_id: str
    page_size: int = 100
    page_token: str | None = None

    @classmethod
    def create(
        cls,
        *,
        cloud_environment_id: str,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> TrinoResourcePresetListOptions:
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("cloud_environment_id must be a non-empty string")
        return cls(
            cloud_environment_id=cloud_environment_id,
            page_size=page_size,
            page_token=page_token,
        )
