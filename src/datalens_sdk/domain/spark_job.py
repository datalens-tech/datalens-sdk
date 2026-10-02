from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.ports import SparkJobOperations
from datalens_sdk.domain.spark_cluster import SparkCluster
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

SparkJobStatus: TypeAlias = Literal[
    "STATUS_UNSPECIFIED", "PROVISIONING", "PENDING", "RUNNING", "ERROR", "DONE", "CANCELLED", "CANCELLING"
]


def normalize_spark_job_cluster(cluster: SparkCluster | str, *, installation: str) -> str:
    if isinstance(cluster, SparkCluster):
        if (
            not isinstance(cluster.installation, str)
            or not cluster.installation
            or cluster.installation != installation
        ):
            raise DataLensValidationError("Spark cluster must belong to this installation")
        cluster_id = cluster.cluster_id
    else:
        cluster_id = cluster
    if not isinstance(cluster_id, str) or not cluster_id:
        raise DataLensValidationError("Spark managed cluster id must be a non-empty string")
    return cluster_id


@dataclass(frozen=True, slots=True)
class SparkJobCatalogRef:
    catalog_id: str


@dataclass(frozen=True, slots=True)
class SparkJobSparkSpec:
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
class SparkJobPySparkSpec:
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
class SparkJobConnectSpec:
    archive_uris: tuple[str, ...]
    file_uris: tuple[str, ...]
    jar_file_uris: tuple[str, ...]
    packages: tuple[str, ...]
    repositories: tuple[str, ...]
    exclude_packages: tuple[str, ...]
    properties: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SparkJob:
    id: str
    cluster_id: str
    installation: str
    name: str
    created_by: str
    status: SparkJobStatus
    connect_url: str
    catalogs: tuple[SparkJobCatalogRef, ...]
    created_at: LakehouseTimestamp
    started_at: LakehouseTimestamp | None
    finished_at: LakehouseTimestamp | None
    spec: SparkJobSparkSpec | SparkJobPySparkSpec | SparkJobConnectSpec | None
    raw: Mapping[str, object]
    _operations: SparkJobOperations | None = field(default=None, repr=False, compare=False)

    def refresh(self) -> SparkJob:
        if not isinstance(self.cluster_id, str) or not self.cluster_id:
            raise DataLensValidationError("Spark managed cluster id must be a non-empty string")
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("Spark job id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Spark job is not bound to client operations")
        return self._operations.get_spark_job(self.cluster_id, self.id)


@dataclass(frozen=True, slots=True)
class SparkJobListOptions:
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
    ) -> SparkJobListOptions:
        cluster_id = normalize_spark_job_cluster(cluster, installation=installation)
        if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
            raise DataLensValidationError("filters must be a sequence of strings")
        if any(not isinstance(value, str) for value in filters):
            raise DataLensValidationError("filters must contain only strings")
        return cls(cluster_id, tuple(filters), page_size, page_token)
