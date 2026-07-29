from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, TypeAlias, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter.collection import CollectionReadDTOProtocol
from datalens_sdk.converter.workbook import WorkbookReadDTOProtocol
from datalens_sdk.domain.navigation import (
    CollectionContentMode,
    CollectionListOptions,
    CollectionSummary,
    DirectoryBreadcrumb,
    DirectoryListOptions,
    EntryRelation,
    EntryScope,
    EntrySummary,
    GetEntriesOptions,
    RelationOptions,
    StructureSummary,
    WorkbookListOptions,
    WorkbookSummary,
)

WireEntryOrder: TypeAlias = Literal["createdAt", "name"]
WireStructureOrder: TypeAlias = Literal["title", "createdAt", "updatedAt"]
WireCollectionMode: TypeAlias = Literal["all", "onlyCollections", "onlyWorkbooks", "onlyEntries"]


class NavigationWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class GetEntriesArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        ids: tuple[str, ...],
        created_by: tuple[str, ...],
        name: str | None,
        exclude_locked: bool | None,
        ignore_shared_entries: bool | None,
        ignore_workbook_entries: bool | None,
        include_data: bool | None,
        include_links: bool | None,
        include_permissions_info: bool | None,
        order_field: WireEntryOrder | None,
        order_direction: Literal["asc", "desc"],
        page_size: int,
        page_token: str | None,
        scope: str | None,
        type: str | None,
    ) -> NavigationWriteDTOProtocol: ...


class ListDirectoryArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        path: str,
        created_by: str | tuple[str, ...] | None,
        name: str | None,
        include_permissions_info: bool | None,
        order_field: WireEntryOrder | None,
        order_direction: Literal["asc", "desc"],
        page: int,
        page_size: int,
    ) -> NavigationWriteDTOProtocol: ...


class CollectionContentArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        collection_id: str,
        filter_string: str | None,
        include_permissions_info: bool | None,
        mode: WireCollectionMode,
        only_my: bool | None,
        order_field: WireStructureOrder | None,
        order_direction: Literal["asc", "desc"],
        page: str | None,
        page_size: int,
    ) -> NavigationWriteDTOProtocol: ...


class WorkbookEntriesArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        workbook_id: str,
        created_by: str | None,
        name: str | None,
        include_permissions_info: bool | None,
        order_field: WireEntryOrder | None,
        order_direction: Literal["asc", "desc"],
        page: int,
        page_size: int,
        scope: str | tuple[str, ...] | None,
    ) -> NavigationWriteDTOProtocol: ...


class EntryRelationsArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        entry_ids: tuple[str, ...],
        include_permissions_info: bool | None,
        link_direction: Literal["from", "to"] | None,
        limit: int,
        page_token: str | None,
        scope: EntryScope | None,
    ) -> NavigationWriteDTOProtocol: ...


class EntrySummaryReadDTOProtocol(Protocol):
    id: str
    scope: str
    type: str
    name: str | None
    key: str | None
    created_by: str | None
    created_at: str | None
    updated_by: str | None
    updated_at: str | None
    saved_id: str | None
    published_id: str | None
    workbook_id: str | None
    collection_id: str | None
    hidden: bool | None
    is_favorite: bool | None
    is_locked: bool
    meta: Mapping[str, object] | None
    permissions: Mapping[str, object] | None
    data: Mapping[str, object] | None
    links: Mapping[str, str] | None
    raw: dict[str, object]


class DirectoryBreadcrumbReadDTOProtocol(Protocol):
    id: str
    name: str
    path: str
    is_locked: bool
    permissions: Mapping[str, object]
    raw: dict[str, object]


class EntryRelationReadDTOProtocol(Protocol):
    id: str
    scope: EntryScope
    type: str
    key: str | None
    created_at: str | None
    public: bool
    tenant_id: str | None
    workbook_id: str | None
    collection_id: str | None
    is_locked: bool
    permissions: Mapping[str, object] | None
    full_permissions: Mapping[str, object] | None
    raw: dict[str, object]


class GetEntriesResultDTOProtocol(Protocol):
    entries: tuple[EntrySummaryReadDTOProtocol, ...]
    next_page_token: str | None


class ListDirectoryResultDTOProtocol(Protocol):
    entries: tuple[EntrySummaryReadDTOProtocol, ...]
    breadcrumbs: tuple[DirectoryBreadcrumbReadDTOProtocol, ...]
    has_next_page: bool


StructureItemReadDTO: TypeAlias = CollectionReadDTOProtocol | WorkbookReadDTOProtocol | EntrySummaryReadDTOProtocol


class CollectionContentResultDTOProtocol(Protocol):
    items: tuple[StructureItemReadDTO, ...]
    next_page_token: str | None


class WorkbookEntriesResultDTOProtocol(Protocol):
    entries: tuple[EntrySummaryReadDTOProtocol, ...]
    next_page_token: str | None


class EntryRelationsResultDTOProtocol(Protocol):
    relations: tuple[EntryRelationReadDTOProtocol, ...]
    next_page_token: str | None


class GetEntriesResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> GetEntriesResultDTOProtocol: ...


class ListDirectoryResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> ListDirectoryResultDTOProtocol: ...


class CollectionContentResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> CollectionContentResultDTOProtocol: ...


class WorkbookEntriesResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> WorkbookEntriesResultDTOProtocol: ...


class EntryRelationsResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> EntryRelationsResultDTOProtocol: ...


class NavigationDtoModule(Protocol):
    GetEntriesArgsDTO: GetEntriesArgsDTOClass
    ListDirectoryArgsDTO: ListDirectoryArgsDTOClass
    CollectionContentArgsDTO: CollectionContentArgsDTOClass
    WorkbookEntriesArgsDTO: WorkbookEntriesArgsDTOClass
    EntryRelationsArgsDTO: EntryRelationsArgsDTOClass
    GetEntriesResultDTO: GetEntriesResultDTOClass
    ListDirectoryResultDTO: ListDirectoryResultDTOClass
    CollectionContentResultDTO: CollectionContentResultDTOClass
    WorkbookEntriesResultDTO: WorkbookEntriesResultDTOClass
    EntryRelationsResultDTO: EntryRelationsResultDTOClass


def _dto_module(dto_module: NavigationDtoModule | None) -> NavigationDtoModule:
    return cast(NavigationDtoModule, generated_dto if dto_module is None else dto_module)


def _entry_order(value: str | None) -> WireEntryOrder | None:
    if value == "created_at":
        return "createdAt"
    if value == "name":
        return "name"
    return None


def _structure_order(value: str | None) -> WireStructureOrder | None:
    values: dict[str, WireStructureOrder] = {
        "name": "title",
        "created_at": "createdAt",
        "updated_at": "updatedAt",
    }
    return values.get(value) if value is not None else None


def _collection_mode(value: CollectionContentMode) -> WireCollectionMode:
    values: dict[CollectionContentMode, WireCollectionMode] = {
        "all": "all",
        "collections": "onlyCollections",
        "workbooks": "onlyWorkbooks",
        "entries": "onlyEntries",
    }
    return values[value]


class NavigationConverter:
    @staticmethod
    def get_entries_payload(
        options: GetEntriesOptions,
        *,
        page_token: str | None,
        dto_module: NavigationDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        return generated.GetEntriesArgsDTO(
            ids=options.ids,
            created_by=options.created_by,
            name=options.name,
            exclude_locked=options.exclude_locked,
            ignore_shared_entries=options.ignore_shared_entries,
            ignore_workbook_entries=options.ignore_workbook_entries,
            include_data=options.include_data,
            include_links=options.include_links,
            include_permissions_info=options.include_permissions_info,
            order_field=_entry_order(options.order_by),
            order_direction=options.order_direction,
            page_size=options.page_size,
            page_token=page_token,
            scope=options.scope,
            type=options.type,
        ).to_payload()

    @staticmethod
    def directory_payload(
        path: str,
        options: DirectoryListOptions,
        *,
        page: int,
        dto_module: NavigationDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        return generated.ListDirectoryArgsDTO(
            path=path,
            created_by=options.created_by,
            name=options.name,
            include_permissions_info=options.include_permissions_info,
            order_field=_entry_order(options.order_by),
            order_direction=options.order_direction,
            page=page,
            page_size=options.page_size,
        ).to_payload()

    @staticmethod
    def collection_payload(
        collection_id: str,
        options: CollectionListOptions,
        *,
        page: str | None,
        dto_module: NavigationDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        return generated.CollectionContentArgsDTO(
            collection_id=collection_id,
            filter_string=options.filter_string,
            include_permissions_info=options.include_permissions_info,
            mode=_collection_mode(options.mode),
            only_my=options.only_my,
            order_field=_structure_order(options.order_by),
            order_direction=options.order_direction,
            page=page,
            page_size=options.page_size,
        ).to_payload()

    @staticmethod
    def workbook_payload(
        workbook_id: str,
        options: WorkbookListOptions,
        *,
        page: int,
        dto_module: NavigationDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        return generated.WorkbookEntriesArgsDTO(
            workbook_id=workbook_id,
            created_by=options.created_by,
            name=options.name,
            include_permissions_info=options.include_permissions_info,
            order_field=_entry_order(options.order_by),
            order_direction=options.order_direction,
            page=page,
            page_size=options.page_size,
            scope=options.scope,
        ).to_payload()

    @staticmethod
    def relations_payload(
        entry_id: str,
        options: RelationOptions,
        *,
        page_token: str | None,
        dto_module: NavigationDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        return generated.EntryRelationsArgsDTO(
            entry_ids=(entry_id,),
            include_permissions_info=options.include_permissions_info,
            link_direction=options.link_direction,
            limit=options.page_size,
            page_token=page_token,
            scope=options.scope,
        ).to_payload()

    @staticmethod
    def _entry(read_dto: EntrySummaryReadDTOProtocol) -> EntrySummary:
        return EntrySummary(
            id=read_dto.id,
            scope=read_dto.scope,
            type=read_dto.type,
            name=read_dto.name,
            key=read_dto.key,
            created_by=read_dto.created_by,
            created_at=read_dto.created_at,
            updated_by=read_dto.updated_by,
            updated_at=read_dto.updated_at,
            saved_id=read_dto.saved_id,
            published_id=read_dto.published_id,
            workbook_id=read_dto.workbook_id,
            collection_id=read_dto.collection_id,
            hidden=read_dto.hidden,
            is_favorite=read_dto.is_favorite,
            is_locked=read_dto.is_locked,
            meta=dict(read_dto.meta or {}),
            permissions=dict(read_dto.permissions or {}),
            data=dict(read_dto.data or {}),
            links=dict(read_dto.links or {}),
            raw=read_dto.raw,
        )

    @staticmethod
    def get_entries_result(
        raw: Mapping[str, object],
        *,
        dto_module: NavigationDtoModule | None = None,
    ) -> tuple[tuple[EntrySummary, ...], str | None]:
        result = _dto_module(dto_module).GetEntriesResultDTO.model_validate(raw)
        return tuple(NavigationConverter._entry(item) for item in result.entries), result.next_page_token

    @staticmethod
    def directory_result(
        raw: Mapping[str, object],
        *,
        dto_module: NavigationDtoModule | None = None,
    ) -> tuple[tuple[EntrySummary, ...], tuple[DirectoryBreadcrumb, ...], bool]:
        result = _dto_module(dto_module).ListDirectoryResultDTO.model_validate(raw)
        breadcrumbs = tuple(
            DirectoryBreadcrumb(
                id=item.id,
                name=item.name,
                path=item.path,
                is_locked=item.is_locked,
                permissions=dict(item.permissions),
                raw=item.raw,
            )
            for item in result.breadcrumbs
        )
        return tuple(NavigationConverter._entry(item) for item in result.entries), breadcrumbs, result.has_next_page

    @staticmethod
    def collection_result(
        raw: Mapping[str, object],
        *,
        dto_module: NavigationDtoModule | None = None,
    ) -> tuple[tuple[StructureSummary, ...], str | None]:
        result = _dto_module(dto_module).CollectionContentResultDTO.model_validate(raw)
        items: list[StructureSummary] = []
        for item in result.items:
            entity = item.raw.get("entity")
            if entity == "collection":
                collection = cast(CollectionReadDTOProtocol, item)
                items.append(
                    CollectionSummary(
                        id=collection.id,
                        name=collection.name,
                        description=collection.description,
                        parent_id=collection.parent_id,
                        tenant_id=collection.tenant_id,
                        created_by=collection.created_by,
                        created_at=collection.created_at,
                        updated_by=collection.updated_by,
                        updated_at=collection.updated_at,
                        permissions=dict(collection.permissions or {}),
                        raw=collection.raw,
                    )
                )
            elif entity == "workbook":
                workbook = cast(WorkbookReadDTOProtocol, item)
                items.append(
                    WorkbookSummary(
                        id=workbook.id,
                        name=workbook.name,
                        description=workbook.description,
                        collection_id=workbook.collection_id,
                        status=workbook.status,
                        tenant_id=workbook.tenant_id,
                        created_by=workbook.created_by,
                        created_at=workbook.created_at,
                        updated_by=workbook.updated_by,
                        updated_at=workbook.updated_at,
                        permissions=dict(workbook.permissions or {}),
                        raw=workbook.raw,
                    )
                )
            else:
                items.append(NavigationConverter._entry(cast(EntrySummaryReadDTOProtocol, item)))
        return tuple(items), result.next_page_token

    @staticmethod
    def workbook_result(
        raw: Mapping[str, object],
        *,
        dto_module: NavigationDtoModule | None = None,
    ) -> tuple[tuple[EntrySummary, ...], str | None]:
        result = _dto_module(dto_module).WorkbookEntriesResultDTO.model_validate(raw)
        return tuple(NavigationConverter._entry(item) for item in result.entries), result.next_page_token

    @staticmethod
    def relations_result(
        raw: Mapping[str, object],
        *,
        dto_module: NavigationDtoModule | None = None,
    ) -> tuple[tuple[EntryRelation, ...], str | None]:
        result = _dto_module(dto_module).EntryRelationsResultDTO.model_validate(raw)
        return (
            tuple(
                EntryRelation(
                    id=item.id,
                    scope=item.scope,
                    type=item.type,
                    key=item.key,
                    created_at=item.created_at,
                    public=item.public,
                    tenant_id=item.tenant_id,
                    workbook_id=item.workbook_id,
                    collection_id=item.collection_id,
                    is_locked=item.is_locked,
                    permissions=dict(item.permissions or {}),
                    full_permissions=dict(item.full_permissions or {}),
                    raw=item.raw,
                )
                for item in result.relations
            ),
            result.next_page_token,
        )
