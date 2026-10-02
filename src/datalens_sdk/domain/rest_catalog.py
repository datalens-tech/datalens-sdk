from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.errors import DataLensValidationError

RestCatalogSortField: TypeAlias = Literal["name", "created_at", "updated_at"]


@dataclass(frozen=True, slots=True)
class RestCatalogBucketSettings:
    storage_class: str
    max_size: str
    alias: str
    description: str | None = None


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
