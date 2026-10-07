from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias

from typing_extensions import Self

from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.specs.rest_catalog import RestCatalogCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
    from datalens_sdk.domain.ports import RestCatalogOperations

RestCatalogSortField: TypeAlias = Literal["name", "created_at", "updated_at"]
_UNBOUND_CREATE = "REST catalog create builder is not bound to client operations"


@dataclass(frozen=True, slots=True)
class RestCatalogBucketSettings:
    storage_class: str
    max_size: str
    alias: str
    description: str | None = None


class RestCatalogCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        cloud_environment_id: str,
        bucket_settings: RestCatalogBucketSettings,
        operations: RestCatalogOperations | None = None,
    ) -> None:
        if not isinstance(installation, str) or not installation:
            raise DataLensValidationError("installation must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise DataLensValidationError("name must be a non-empty string")
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("cloud_environment_id must be a non-empty string")
        if not isinstance(bucket_settings, RestCatalogBucketSettings):
            raise DataLensValidationError("bucket_settings must be RestCatalogBucketSettings")
        self._name = name
        self._cloud_environment_id = cloud_environment_id
        self._bucket_settings = bucket_settings
        self._operations = operations
        self._description: str | None = None
        self._labels: Mapping[str, str] | None = None

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

    def to_spec(self) -> RestCatalogCreateSpec:
        return RestCatalogCreateSpec(
            name=self._name,
            cloud_environment_id=self._cloud_environment_id,
            bucket_settings=self._bucket_settings,
            description=self._description,
            labels=self._labels,
        )

    def build(self) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND_CREATE)
        self.to_spec()
        return self._operations.create_rest_catalog(self)


@dataclass(frozen=True, slots=True)
class RestCatalogBucketDetails:
    max_size: str | None = None
    used_size: str | None = None
    updated_at: LakehouseTimestamp | None = None


@dataclass(frozen=True, slots=True)
class RestCatalogBucket:
    settings: RestCatalogBucketSettings
    details: RestCatalogBucketDetails | None = None


@dataclass(frozen=True, slots=True)
class RestCatalog:
    id: str
    installation: str
    organization_id: str
    tenant_id: str
    cloud_environment_id: str
    name: str
    description: str
    created_by_id: str
    bucket: RestCatalogBucket
    labels: Mapping[str, str]
    permissions: Mapping[str, bool] | None
    created_at: LakehouseTimestamp | None
    updated_at: LakehouseTimestamp | None
    raw: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RestCatalogListOptions:
    cloud_environment_id: str | None = None
    filters: tuple[str, ...] = ()
    include_permissions: bool | None = None
    sort_by: RestCatalogSortField | None = None
    order: SortDirection = "asc"
    page_size: int = 100
    page_token: str | None = None

    @classmethod
    def create(
        cls,
        *,
        cloud_environment_id: str | None = None,
        filters: Sequence[str] = (),
        include_permissions: bool | None = None,
        sort_by: RestCatalogSortField | None = None,
        order: SortDirection = "asc",
        page_size: int = 100,
        page_token: str | None = None,
    ) -> RestCatalogListOptions:
        if cloud_environment_id is not None and (not isinstance(cloud_environment_id, str) or not cloud_environment_id):
            raise DataLensValidationError("cloud_environment_id must be a non-empty string when supplied")
        if isinstance(filters, (str, bytes)) or not isinstance(filters, Sequence):
            raise DataLensValidationError("filters must be a sequence of strings")
        if sort_by is not None and (
            not isinstance(sort_by, str) or sort_by not in ("name", "created_at", "updated_at")
        ):
            raise DataLensValidationError("sort_by must be one of: name, created_at, updated_at")
        if not isinstance(order, str) or order not in ("asc", "desc"):
            raise DataLensValidationError("order must be one of: asc, desc")
        return cls(
            cloud_environment_id=cloud_environment_id,
            filters=tuple(filters),
            include_permissions=include_permissions,
            sort_by=sort_by,
            order=order,
            page_size=page_size,
            page_token=page_token,
        )
