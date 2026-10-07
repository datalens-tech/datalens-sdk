from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    resolve_entry_location,
)
from datalens_sdk.domain.ports import TrinoClusterOperations
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


@dataclass(frozen=True, slots=True)
class TrinoResourcePreset:
    id: str
    installation: str
    cloud_environment_id: str
    cores: str
    memory: str
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TrinoClusterListOptions:
    collection_id: str | None = None
    filters: tuple[str, ...] = ()
    page_size: int = 100
    page_token: str | None = None

    @classmethod
    def create(
        cls,
        *,
        installation: str,
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
