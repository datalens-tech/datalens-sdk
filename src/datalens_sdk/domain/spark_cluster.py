from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from typing_extensions import Self

from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    resolve_entry_location,
    validate_entry_name,
)
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.ports import SparkClusterOperations
from datalens_sdk.domain.specs.spark_cluster import SparkClusterCreateSpec
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


def _resource_preset_id(value: SparkResourcePreset | str, *, installation: str, cloud_environment_id: str) -> str:
    if isinstance(value, SparkResourcePreset):
        if not isinstance(value.installation, str) or not value.installation or value.installation != installation:
            raise DataLensValidationError("Spark resource preset must belong to this installation")
        if value.cloud_environment_id != cloud_environment_id:
            raise DataLensValidationError("Spark resource preset must belong to this cloud environment")
        value = value.id
    if not isinstance(value, str) or not value:
        raise DataLensValidationError("Spark resource preset id must be a non-empty string")
    return value


def _packages(value: Sequence[str] | None, *, name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DataLensValidationError(f"{name} must be a sequence of strings")
    if any(not isinstance(package, str) for package in value):
        raise DataLensValidationError(f"{name} must contain only strings")
    return tuple(value)


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

    def start(self) -> LakehouseOperation:
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("spark cluster id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark cluster is not bound to client operations")
        return self._operations.start_spark_cluster(self.id)

    def stop(self) -> LakehouseOperation:
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("spark cluster id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark cluster is not bound to client operations")
        return self._operations.stop_spark_cluster(self.id)

    def delete(self) -> LakehouseOperation:
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("spark cluster id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark cluster is not bound to client operations")
        return self._operations.delete_spark_cluster(self.id)


@dataclass(frozen=True, slots=True)
class SparkResourcePreset:
    id: str
    installation: str
    cloud_environment_id: str
    cores: str
    memory: str
    raw: Mapping[str, object]


class SparkClusterCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        cloud_environment_id: str,
        operations: SparkClusterOperations | None,
    ) -> None:
        if not isinstance(installation, str) or not installation:
            raise DataLensValidationError("installation must be a non-empty string")
        resolved = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"collection"},
            context="Spark cluster creation",
        )
        collection_id = collection_id_from_location(resolved)
        if not isinstance(collection_id, str) or not collection_id:
            raise DataLensValidationError("collection id must be a non-empty string")
        validate_entry_name(name=name, location=resolved)
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("cloud_environment_id must be a non-empty string")
        self._installation = installation
        self._name = name
        self._location = resolved
        self._cloud_environment_id = cloud_environment_id
        self._operations = operations
        self._driver: SparkResourcePoolConfig | None = None
        self._executor: SparkResourcePoolConfig | None = None
        self._dependencies_configured = False
        self._pip_packages: tuple[str, ...] | None = None
        self._deb_packages: tuple[str, ...] | None = None
        self._logging_enabled: bool | None = None
        self._spark_version: str | None = None
        self._description: str | None = None
        self._labels: Mapping[str, str] | None = None

    def driver(self, *, resource_preset: SparkResourcePreset | str, scale_policy: SparkScalePolicy) -> Self:
        preset_id = _resource_preset_id(
            resource_preset, installation=self._installation, cloud_environment_id=self._cloud_environment_id
        )
        if not isinstance(scale_policy, (SparkFixedScalePolicy, SparkAutoScalePolicy)):
            raise DataLensValidationError("driver scale_policy must be a Spark scale policy")
        self._driver = SparkResourcePoolConfig(preset_id, scale_policy)
        return self

    def executor(self, *, resource_preset: SparkResourcePreset | str, scale_policy: SparkScalePolicy) -> Self:
        preset_id = _resource_preset_id(
            resource_preset, installation=self._installation, cloud_environment_id=self._cloud_environment_id
        )
        if not isinstance(scale_policy, (SparkFixedScalePolicy, SparkAutoScalePolicy)):
            raise DataLensValidationError("executor scale_policy must be a Spark scale policy")
        self._executor = SparkResourcePoolConfig(preset_id, scale_policy)
        return self

    def dependencies(
        self,
        *,
        pip_packages: Sequence[str] | None = None,
        deb_packages: Sequence[str] | None = None,
    ) -> Self:
        pip = _packages(pip_packages, name="pip_packages")
        deb = _packages(deb_packages, name="deb_packages")
        self._dependencies_configured = True
        self._pip_packages = pip
        self._deb_packages = deb
        return self

    def logging(self, *, enabled: bool) -> Self:
        self._logging_enabled = enabled
        return self

    def description(self, value: str) -> Self:
        self._description = value
        return self

    def labels(self, values: Mapping[str, str]) -> Self:
        if not isinstance(values, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()
        ):
            raise DataLensValidationError("labels must map strings to strings")
        self._labels = dict(values)
        return self

    def spark_version(self, value: str) -> Self:
        self._spark_version = value
        return self

    def to_spec(self) -> SparkClusterCreateSpec:
        if self._driver is None:
            raise DataLensValidationError("Spark cluster creation requires driver")
        if self._executor is None:
            raise DataLensValidationError("Spark cluster creation requires executor")
        return SparkClusterCreateSpec(
            name=self._name,
            location=self._location,
            cloud_environment_id=self._cloud_environment_id,
            driver=self._driver,
            executor=self._executor,
            dependencies_configured=self._dependencies_configured,
            pip_packages=self._pip_packages,
            deb_packages=self._deb_packages,
            logging_enabled=self._logging_enabled,
            spark_version=self._spark_version,
            description=self._description,
            labels=None if self._labels is None else dict(self._labels),
        )

    def build(self) -> LakehouseOperation:
        self.to_spec()
        if self._operations is None:
            raise DataLensConfigurationError("Spark cluster creation is not bound to client operations")
        return self._operations.create_spark_cluster(self)


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
