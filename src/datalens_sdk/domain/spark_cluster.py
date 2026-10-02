from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from datalens_sdk.domain.entry_location import EntryLocation, collection_id_from_location, resolve_entry_location
from datalens_sdk.domain.ports import SparkClusterOperations
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

SparkClusterHealth: TypeAlias = Literal["HEALTH_UNKNOWN", "ALIVE", "DEAD", "DEGRADED"]
SparkClusterStatus: TypeAlias = Literal[
    "STATUS_UNSPECIFIED", "CREATING", "RUNNING", "UPDATING", "ERROR", "STOPPING", "STOPPED", "STARTING"
]


def _exact_integer(value: object, *, field_name: str) -> None:
    if type(value) is not int:
        raise DataLensValidationError(f"{field_name} must be an integer")


@dataclass(frozen=True, slots=True)
class SparkFixedScalePolicy:
    size: int

    def __post_init__(self) -> None:
        _exact_integer(self.size, field_name="size")


@dataclass(frozen=True, slots=True)
class SparkAutoScalePolicy:
    min_size: int
    max_size: int
    initial_size: int

    def __post_init__(self) -> None:
        _exact_integer(self.min_size, field_name="min_size")
        _exact_integer(self.max_size, field_name="max_size")
        _exact_integer(self.initial_size, field_name="initial_size")


SparkScalePolicy: TypeAlias = SparkFixedScalePolicy | SparkAutoScalePolicy


@dataclass(frozen=True, slots=True)
class SparkResourcePoolConfig:
    resource_preset_id: str
    scale_policy: SparkScalePolicy


@dataclass(frozen=True, slots=True)
class SparkResourcePoolsConfig:
    driver: SparkResourcePoolConfig
    executor: SparkResourcePoolConfig


@dataclass(frozen=True, slots=True)
class SparkClusterDependencies:
    pip_packages: tuple[str, ...]
    deb_packages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SparkLoggingConfig:
    enabled: bool


@dataclass(frozen=True, slots=True)
class SparkClusterConfig:
    spark_version: str
    resource_pools: SparkResourcePoolsConfig
    dependencies: SparkClusterDependencies | None
    logging: SparkLoggingConfig | None


@dataclass(slots=True)
class SparkCluster:
    id: str
    cluster_id: str
    installation: str
    location: EntryLocation
    cloud_environment_id: str
    name: str
    description: str
    labels: Mapping[str, str]
    config: SparkClusterConfig
    health: SparkClusterHealth
    status: SparkClusterStatus
    entry_id: str
    raw: Mapping[str, object]
    _operations: SparkClusterOperations | None = field(default=None, repr=False, compare=False)

    def refresh(self) -> SparkCluster:
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("spark cluster id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark cluster is not bound to client operations")
        return self._operations.get_spark_cluster(self.id)


@dataclass(frozen=True, slots=True)
class SparkResourcePreset:
    id: str
    installation: str
    cloud_environment_id: str
    cores: str
    memory: str
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SparkClusterListOptions:
    collection_id: str | None
    filters: tuple[str, ...]
    page_size: int
    page_token: str | None

    @classmethod
    def create(
        cls,
        *,
        installation: str,
        collection: EntryLocation | str | None = None,
        filters: Sequence[str] = (),
        page_size: int = 100,
        page_token: str | None = None,
    ) -> SparkClusterListOptions:
        if collection is None:
            collection_id = None
        else:
            if isinstance(collection, str):
                if not collection:
                    raise DataLensValidationError("collection must be a non-empty string")
                collection = EntryLocation.collection(collection)
            resolved = resolve_entry_location(
                location=collection,
                installation=installation,
                allowed_kinds={"collection"},
                context="Spark cluster listing",
            )
            collection_id = collection_id_from_location(resolved)
        if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
            raise DataLensValidationError("filters must be a sequence of strings")
        return cls(collection_id=collection_id, filters=tuple(filters), page_size=page_size, page_token=page_token)


@dataclass(frozen=True, slots=True)
class SparkResourcePresetListOptions:
    cloud_environment_id: str
    page_size: int
    page_token: str | None

    @classmethod
    def create(
        cls,
        *,
        cloud_environment_id: str,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> SparkResourcePresetListOptions:
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("cloud_environment_id must be a non-empty string")
        return cls(cloud_environment_id=cloud_environment_id, page_size=page_size, page_token=page_token)
