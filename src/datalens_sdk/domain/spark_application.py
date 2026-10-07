from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.ports import SparkApplicationOperations
from datalens_sdk.domain.spark_cluster import SparkCluster
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

SparkApplicationStatus: TypeAlias = Literal[
    "STATUS_UNSPECIFIED", "PROVISIONING", "PENDING", "RUNNING", "ERROR", "DONE", "CANCELLED", "CANCELLING"
]


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
