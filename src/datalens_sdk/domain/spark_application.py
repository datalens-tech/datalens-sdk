from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias, TypedDict

from typing_extensions import Self

from datalens_sdk.domain.lakehouse_operation import LakehouseOperation, LakehouseTimestamp
from datalens_sdk.domain.ports import SparkApplicationOperations
from datalens_sdk.domain.rest_catalog import RestCatalog
from datalens_sdk.domain.spark_cluster import SparkCluster
from datalens_sdk.domain.specs.spark_application import (
    SparkApplicationConnectCreateSpec,
    SparkApplicationCreateSpec,
    SparkApplicationPySparkCreateSpec,
    SparkApplicationSparkCreateSpec,
)
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

SparkApplicationStatus: TypeAlias = Literal[
    "STATUS_UNSPECIFIED", "PROVISIONING", "PENDING", "RUNNING", "ERROR", "DONE", "CANCELLED", "CANCELLING"
]


class _CommonCreateValues(TypedDict):
    archive_uris: tuple[str, ...] | None
    file_uris: tuple[str, ...] | None
    jar_file_uris: tuple[str, ...] | None
    packages: tuple[str, ...] | None
    repositories: tuple[str, ...] | None
    exclude_packages: tuple[str, ...] | None
    properties: Mapping[str, str] | None


def _optional_strings(values: Sequence[str] | None, *, field_name: str) -> tuple[str, ...] | None:
    if values is None:
        return None
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise DataLensValidationError(f"{field_name} must be a sequence of strings")
    return tuple(values)


def _optional_properties(values: Mapping[str, str] | None) -> Mapping[str, str] | None:
    if values is None:
        return None
    if not isinstance(values, Mapping):
        raise DataLensValidationError("properties must be a mapping")
    return MappingProxyType(dict(values))


class SparkApplicationCreate:
    def __init__(
        self,
        *,
        installation: str,
        cluster: SparkCluster | str,
        name: str | None = None,
        operations: SparkApplicationOperations | None = None,
    ) -> None:
        self._installation = installation
        self._cluster_id = normalize_spark_application_cluster(cluster, installation=installation)
        self._cloud_environment_id = cluster.cloud_environment_id if isinstance(cluster, SparkCluster) else None
        self._name = name
        self._operations = operations
        self._catalog_ids: tuple[str, ...] | None = None
        self._variant: (
            SparkApplicationSparkCreateSpec
            | SparkApplicationPySparkCreateSpec
            | SparkApplicationConnectCreateSpec
            | None
        ) = None

    def catalogs(self, values: Sequence[RestCatalog | str]) -> Self:
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise DataLensValidationError("catalogs must be a sequence of catalog references")
        ids: list[str] = []
        for value in values:
            if isinstance(value, RestCatalog):
                if value.installation != self._installation or not value.installation:
                    raise DataLensValidationError("REST catalog must belong to this installation")
                if self._cloud_environment_id is not None and value.cloud_environment_id != self._cloud_environment_id:
                    raise DataLensValidationError("REST catalog and Spark cluster cloud environments differ")
                catalog_id = value.id
            else:
                catalog_id = value
            if not isinstance(catalog_id, str) or not catalog_id:
                raise DataLensValidationError("REST catalog id must be a non-empty string")
            ids.append(catalog_id)
        self._catalog_ids = tuple(ids)
        return self

    def _common(
        self,
        *,
        archive_uris: Sequence[str] | None,
        file_uris: Sequence[str] | None,
        jar_file_uris: Sequence[str] | None,
        packages: Sequence[str] | None,
        repositories: Sequence[str] | None,
        exclude_packages: Sequence[str] | None,
        properties: Mapping[str, str] | None,
    ) -> _CommonCreateValues:
        if self._variant is not None:
            raise DataLensValidationError("Spark application variant is already selected")
        return {
            "archive_uris": _optional_strings(archive_uris, field_name="archive_uris"),
            "file_uris": _optional_strings(file_uris, field_name="file_uris"),
            "jar_file_uris": _optional_strings(jar_file_uris, field_name="jar_file_uris"),
            "packages": _optional_strings(packages, field_name="packages"),
            "repositories": _optional_strings(repositories, field_name="repositories"),
            "exclude_packages": _optional_strings(exclude_packages, field_name="exclude_packages"),
            "properties": _optional_properties(properties),
        }

    def spark(
        self,
        *,
        main_jar_file_uri: str,
        main_class: str | None = None,
        args: Sequence[str] | None = None,
        archive_uris: Sequence[str] | None = None,
        file_uris: Sequence[str] | None = None,
        jar_file_uris: Sequence[str] | None = None,
        packages: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        exclude_packages: Sequence[str] | None = None,
        properties: Mapping[str, str] | None = None,
    ) -> Self:
        common = self._common(
            archive_uris=archive_uris,
            file_uris=file_uris,
            jar_file_uris=jar_file_uris,
            packages=packages,
            repositories=repositories,
            exclude_packages=exclude_packages,
            properties=properties,
        )
        self._variant = SparkApplicationSparkCreateSpec(
            main_jar_file_uri=main_jar_file_uri,
            main_class=main_class,
            args=_optional_strings(args, field_name="args"),
            **common,
        )
        return self

    def pyspark(
        self,
        *,
        main_python_file_uri: str,
        args: Sequence[str] | None = None,
        python_file_uris: Sequence[str] | None = None,
        archive_uris: Sequence[str] | None = None,
        file_uris: Sequence[str] | None = None,
        jar_file_uris: Sequence[str] | None = None,
        packages: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        exclude_packages: Sequence[str] | None = None,
        properties: Mapping[str, str] | None = None,
    ) -> Self:
        common = self._common(
            archive_uris=archive_uris,
            file_uris=file_uris,
            jar_file_uris=jar_file_uris,
            packages=packages,
            repositories=repositories,
            exclude_packages=exclude_packages,
            properties=properties,
        )
        self._variant = SparkApplicationPySparkCreateSpec(
            main_python_file_uri=main_python_file_uri,
            args=_optional_strings(args, field_name="args"),
            python_file_uris=_optional_strings(python_file_uris, field_name="python_file_uris"),
            **common,
        )
        return self

    def spark_connect(
        self,
        *,
        archive_uris: Sequence[str] | None = None,
        file_uris: Sequence[str] | None = None,
        jar_file_uris: Sequence[str] | None = None,
        packages: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        exclude_packages: Sequence[str] | None = None,
        properties: Mapping[str, str] | None = None,
    ) -> Self:
        common = self._common(
            archive_uris=archive_uris,
            file_uris=file_uris,
            jar_file_uris=jar_file_uris,
            packages=packages,
            repositories=repositories,
            exclude_packages=exclude_packages,
            properties=properties,
        )
        self._variant = SparkApplicationConnectCreateSpec(**common)
        return self

    def to_spec(self) -> SparkApplicationCreateSpec:
        if self._variant is None:
            raise DataLensValidationError("Spark application variant must be selected before creation")
        return SparkApplicationCreateSpec(self._cluster_id, self._name, self._catalog_ids, self._variant)

    def build(self) -> LakehouseOperation:
        self.to_spec()
        if self._operations is None:
            raise DataLensConfigurationError("Spark application builder is not bound to client operations")
        return self._operations.create_spark_application(self)


def normalize_spark_application_cluster(cluster: SparkCluster | str, *, installation: str) -> str:
    if isinstance(cluster, SparkCluster):
        if (
            not isinstance(cluster.installation, str)
            or not cluster.installation
            or cluster.installation != installation
        ):
            raise DataLensValidationError("Spark cluster must belong to this installation")
        cluster_id = cluster.id
    else:
        cluster_id = cluster
    if not isinstance(cluster_id, str) or not cluster_id:
        raise DataLensValidationError("Spark Lakehouse cluster id must be a non-empty string")
    return cluster_id


@dataclass(frozen=True, slots=True)
class SparkApplicationCatalogRef:
    catalog_id: str


@dataclass(frozen=True, slots=True)
class SparkApplicationSparkSpec:
    main_jar_file_uri: str
    main_class: str
    args: tuple[str, ...]
    archive_uris: tuple[str, ...]
    file_uris: tuple[str, ...]
    jar_file_uris: tuple[str, ...]
    packages: tuple[str, ...]
    repositories: tuple[str, ...]
    exclude_packages: tuple[str, ...]
    properties: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SparkApplicationPySparkSpec:
    main_python_file_uri: str
    python_file_uris: tuple[str, ...]
    args: tuple[str, ...]
    archive_uris: tuple[str, ...]
    file_uris: tuple[str, ...]
    jar_file_uris: tuple[str, ...]
    packages: tuple[str, ...]
    repositories: tuple[str, ...]
    exclude_packages: tuple[str, ...]
    properties: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SparkApplicationConnectSpec:
    archive_uris: tuple[str, ...]
    file_uris: tuple[str, ...]
    jar_file_uris: tuple[str, ...]
    packages: tuple[str, ...]
    repositories: tuple[str, ...]
    exclude_packages: tuple[str, ...]
    properties: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SparkApplication:
    id: str
    cluster_id: str
    installation: str
    name: str
    created_by: str
    status: SparkApplicationStatus
    connect_url: str
    catalogs: tuple[SparkApplicationCatalogRef, ...]
    created_at: LakehouseTimestamp
    started_at: LakehouseTimestamp | None
    finished_at: LakehouseTimestamp | None
    spec: SparkApplicationSparkSpec | SparkApplicationPySparkSpec | SparkApplicationConnectSpec | None
    raw: Mapping[str, object]
    _operations: SparkApplicationOperations | None = field(default=None, repr=False, compare=False)

    def refresh(self) -> SparkApplication:
        if not isinstance(self.cluster_id, str) or not self.cluster_id:
            raise DataLensValidationError("Spark Lakehouse cluster id must be a non-empty string")
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Spark application id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark application is not bound to client operations")
        return self._operations.get_spark_application(self.cluster_id, self.id)

    def cancel(self) -> LakehouseOperation:
        if not isinstance(self.cluster_id, str) or not self.cluster_id:
            raise DataLensValidationError("Spark Lakehouse cluster id must be a non-empty string")
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Spark application id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark application is not bound to client operations")
        return self._operations.cancel_spark_application(self.cluster_id, self.id)


@dataclass(frozen=True, slots=True)
class SparkApplicationListOptions:
    cluster_id: str
    filters: tuple[str, ...] = ()
    page_size: int = 100
    page_token: str | None = None

    @classmethod
    def create(
        cls,
        *,
        installation: str,
        cluster: SparkCluster | str,
        filters: Sequence[str] = (),
        page_size: int = 100,
        page_token: str | None = None,
    ) -> SparkApplicationListOptions:
        cluster_id = normalize_spark_application_cluster(cluster, installation=installation)
        if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
            raise DataLensValidationError("filters must be a sequence of strings")
        if any(not isinstance(value, str) for value in filters):
            raise DataLensValidationError("filters must contain only strings")
        return cls(cluster_id, tuple(filters), page_size, page_token)


@dataclass(frozen=True, slots=True)
class SparkApplicationLogPage:
    content: str
    next_page_token: str


@dataclass(frozen=True, slots=True)
class SparkApplicationLogOptions:
    cluster_id: str
    application_id: str
    page_size: int | None = None
    page_token: str | None = None

    @classmethod
    def create(
        cls,
        *,
        installation: str,
        cluster: SparkCluster | str,
        application: SparkApplication | str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> SparkApplicationLogOptions:
        cluster_id = normalize_spark_application_cluster(cluster, installation=installation)
        if isinstance(application, SparkApplication):
            if (
                not isinstance(application.installation, str)
                or not application.installation
                or application.installation != installation
            ):
                raise DataLensValidationError("Spark application must belong to this installation")
            if (
                not isinstance(application.cluster_id, str)
                or not application.cluster_id
                or application.cluster_id != cluster_id
            ):
                raise DataLensValidationError("Spark application must belong to the selected Lakehouse cluster")
            application_id = application.id
        else:
            application_id = application
        if not isinstance(application_id, str) or not application_id:
            raise DataLensValidationError("Spark application id must be a non-empty string")
        return cls(cluster_id, application_id, page_size, page_token)


class SparkApplicationLogPager:
    def __init__(self, loader: Callable[[], Iterator[SparkApplicationLogPage]]) -> None:
        self._loader = loader

    def pages(self) -> Iterator[SparkApplicationLogPage]:
        return self._loader()

    def __iter__(self) -> Iterator[str]:
        for page in self.pages():
            yield page.content
