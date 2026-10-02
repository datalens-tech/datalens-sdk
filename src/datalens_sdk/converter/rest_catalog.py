from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter.lakehouse_operation import LakehouseTimestampReadDTOProtocol, lakehouse_timestamp_from_dto
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.rest_catalog import (
    RestCatalog,
    RestCatalogBucket,
    RestCatalogBucketDetails,
    RestCatalogBucketSettings,
    RestCatalogListOptions,
)
from datalens_sdk.errors import translate_invalid_response_error


class RestCatalogWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class RestCatalogWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> RestCatalogWriteDTOProtocol: ...


class RestCatalogBucketSettingsDTOProtocol(Protocol):
    @property
    def storage_class(self) -> str: ...

    @property
    def max_size(self) -> str: ...

    @property
    def alias(self) -> str: ...

    @property
    def description(self) -> str | None: ...


class RestCatalogBucketDetailsDTOProtocol(Protocol):
    @property
    def max_size(self) -> str | None: ...

    @property
    def used_size(self) -> str | None: ...

    @property
    def updated_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...


class RestCatalogBucketDTOProtocol(Protocol):
    @property
    def settings(self) -> RestCatalogBucketSettingsDTOProtocol: ...

    @property
    def details(self) -> RestCatalogBucketDetailsDTOProtocol | None: ...


class RestCatalogItemDTOProtocol(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def organization_id(self) -> str: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def cloud_environment_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def created_by_id(self) -> str: ...

    @property
    def bucket(self) -> RestCatalogBucketDTOProtocol: ...

    @property
    def labels(self) -> Mapping[str, str] | None: ...

    @property
    def permissions(self) -> Mapping[str, bool] | None: ...

    @property
    def created_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...

    @property
    def updated_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...


class RestCatalogListResultDTOProtocol(Protocol):
    @property
    def rest_catalogs(self) -> Sequence[RestCatalogItemDTOProtocol]: ...

    @property
    def next_page_token(self) -> str: ...


class RestCatalogListResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> RestCatalogListResultDTOProtocol: ...


class RestCatalogDtoModule(Protocol):
    ListCatalogsArgsDTO: RestCatalogWriteDTOClass
    ListCatalogsResultReadDTO: RestCatalogListResultDTOClass


def _dto_module(dto_module: RestCatalogDtoModule | None) -> RestCatalogDtoModule:
    return cast(RestCatalogDtoModule, generated_dto if dto_module is None else dto_module)


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} is not an object")
    return cast(Mapping[str, object], value)


def _timestamp(
    raw: Mapping[str, object], key: str, dto: LakehouseTimestampReadDTOProtocol | None
) -> LakehouseTimestamp | None:
    value = raw.get(key)
    raw_timestamp = None if value is None else _mapping(value, field=key)
    return lakehouse_timestamp_from_dto(raw_timestamp, dto=dto)


def _catalog_from_dto(raw: Mapping[str, object], dto: RestCatalogItemDTOProtocol, installation: str) -> RestCatalog:
    if not dto.id:
        raise ValueError("catalog id is empty")
    if not dto.cloud_environment_id:
        raise ValueError("catalog cloudEnvironmentId is empty")
    raw_bucket = _mapping(raw["bucket"], field="bucket")
    details_dto = dto.bucket.details
    details = None
    if details_dto is not None:
        raw_details = _mapping(raw_bucket["details"], field="bucket.details")
        details = RestCatalogBucketDetails(
            max_size=details_dto.max_size,
            used_size=details_dto.used_size,
            updated_at=_timestamp(raw_details, "updatedAt", details_dto.updated_at),
        )
    settings = dto.bucket.settings
    return RestCatalog(
        id=dto.id,
        installation=installation,
        organization_id=dto.organization_id,
        tenant_id=dto.tenant_id,
        cloud_environment_id=dto.cloud_environment_id,
        name=dto.name,
        description=dto.description,
        created_by_id=dto.created_by_id,
        bucket=RestCatalogBucket(
            settings=RestCatalogBucketSettings(
                storage_class=settings.storage_class,
                max_size=settings.max_size,
                alias=settings.alias,
                description=settings.description,
            ),
            details=details,
        ),
        labels=dto.labels if dto.labels is not None else {},
        permissions=dto.permissions,
        created_at=_timestamp(raw, "createdAt", dto.created_at),
        updated_at=_timestamp(raw, "updatedAt", dto.updated_at),
        raw=dict(raw),
    )


class RestCatalogConverter:
    @staticmethod
    def list_payload(
        options: RestCatalogListOptions,
        *,
        page_token: str | None,
        dto_module: RestCatalogDtoModule | None = None,
    ) -> RestCatalogWriteDTOProtocol:
        payload: dict[str, object] = {
            "pageSize": options.page_size,
            "reverseOrder": options.order == "desc",
        }
        if options.cloud_environment_id is not None:
            payload["cloudEnvironmentId"] = options.cloud_environment_id
        if options.filters:
            payload["filter"] = list(options.filters)
        if options.include_permissions is not None:
            payload["includePermissions"] = options.include_permissions
        if options.sort_by is not None:
            payload["sortBy"] = {
                "name": "name",
                "created_at": "createdAt",
                "updated_at": "updatedAt",
            }[options.sort_by]
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListCatalogsArgsDTO.model_validate(payload)

    @staticmethod
    def to_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        dto_module: RestCatalogDtoModule | None = None,
    ) -> Page[RestCatalog]:
        result = _dto_module(dto_module).ListCatalogsResultReadDTO.model_validate(raw)
        try:
            raw_items = raw["restCatalogs"]
            if not isinstance(raw_items, list):
                raise TypeError("restCatalogs is not an array")
            items = tuple(
                _catalog_from_dto(_mapping(raw_item, field="catalog item"), dto_item, installation)
                for raw_item, dto_item in zip(raw_items, result.rest_catalogs, strict=True)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation="listCatalogs", reason=str(exc)) from exc
        return Page(items=items, next_page_token=result.next_page_token)
