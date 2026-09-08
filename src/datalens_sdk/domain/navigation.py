from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeAlias, TypeVar, cast, get_args

from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.errors import DataLensValidationError

EntryOrderField: TypeAlias = Literal["created_at", "name"]
StructureOrderField: TypeAlias = Literal["name", "created_at", "updated_at"]
CollectionContentMode: TypeAlias = Literal["all", "collections", "workbooks", "entries"]
LinkDirection: TypeAlias = Literal["from", "to"]
EntryScope: TypeAlias = Literal[
    "dash",
    "report",
    "widget",
    "dataset",
    "folder",
    "connection",
    "compute",
    "artifact",
    "sql_query",
]
_ENTRY_SCOPE_VALUES: frozenset[str] = frozenset(get_args(EntryScope))


def _invalid_scope(value: object) -> DataLensValidationError:
    supported = ", ".join(sorted(_ENTRY_SCOPE_VALUES))
    return DataLensValidationError(f"scope must be one of: {supported}; got {value!r}")


def _validated_entry_scope(value: object) -> EntryScope:
    if not isinstance(value, str) or value not in _ENTRY_SCOPE_VALUES:
        raise _invalid_scope(value)
    return cast(EntryScope, value)


def _validate_entry_scope(scope: object) -> None:
    if scope is not None:
        _validated_entry_scope(scope)


def _normalize_entry_scopes(scope: object) -> EntryScope | tuple[EntryScope, ...] | None:
    if scope is None:
        return None
    if isinstance(scope, str):
        return _validated_entry_scope(scope)
    if not isinstance(scope, Sequence):
        raise _invalid_scope(scope)
    return tuple(_validated_entry_scope(value) for value in scope)


@dataclass(frozen=True, slots=True)
class EntrySummary:
    id: str
    scope: str
    type: str
    name: str | None = None
    key: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    saved_id: str | None = None
    published_id: str | None = None
    workbook_id: str | None = None
    collection_id: str | None = None
    hidden: bool | None = None
    is_favorite: bool | None = None
    is_locked: bool = False
    meta: Mapping[str, object] = field(default_factory=dict)
    permissions: Mapping[str, object] = field(default_factory=dict)
    data: Mapping[str, object] = field(default_factory=dict)
    links: Mapping[str, str] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    id: str
    name: str
    description: str | None = None
    parent_id: str | None = None
    tenant_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    permissions: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkbookSummary:
    id: str
    name: str
    description: str | None = None
    collection_id: str | None = None
    status: str | None = None
    tenant_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    permissions: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EntryRelation:
    id: str
    scope: str
    type: str
    key: str | None = None
    created_at: str | None = None
    public: bool = False
    tenant_id: str | None = None
    workbook_id: str | None = None
    collection_id: str | None = None
    is_locked: bool = False
    permissions: Mapping[str, object] = field(default_factory=dict)
    full_permissions: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DirectoryBreadcrumb:
    id: str
    name: str
    path: str
    is_locked: bool = False
    permissions: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Page(Generic[T_co]):
    items: tuple[T_co, ...]
    next_page_token: str | None = None


@dataclass(frozen=True, slots=True)
class DirectoryPage(Page[T_co]):
    breadcrumbs: tuple[DirectoryBreadcrumb, ...] = ()


class Pager(Generic[T_co]):
    def __init__(self, loader: Callable[[], Iterator[Page[T_co]]]) -> None:
        self._loader = loader

    def pages(self) -> Iterator[Page[T_co]]:
        return self._loader()

    def __iter__(self) -> Iterator[T_co]:
        for page in self.pages():
            yield from page.items


class DirectoryPager(Pager[T_co]):
    def __init__(self, loader: Callable[[], Iterator[DirectoryPage[T_co]]]) -> None:
        super().__init__(loader)
        self._directory_loader = loader

    def pages(self) -> Iterator[DirectoryPage[T_co]]:
        return self._directory_loader()


StructureSummary: TypeAlias = CollectionSummary | WorkbookSummary | EntrySummary


@dataclass(frozen=True, slots=True)
class GetEntriesOptions:
    ids: tuple[str, ...] = ()
    created_by: tuple[str, ...] = ()
    name: str | None = None
    exclude_locked: bool | None = None
    ignore_shared_entries: bool | None = None
    ignore_workbook_entries: bool | None = None
    include_data: bool | None = None
    include_links: bool | None = None
    include_permissions_info: bool | None = None
    order_by: EntryOrderField | None = None
    order_direction: SortDirection = "asc"
    page_size: int = 100
    scope: EntryScope | None = None
    type: str | None = None

    def __post_init__(self) -> None:
        _validate_entry_scope(self.scope)

    @classmethod
    def create(
        cls,
        *,
        ids: Sequence[str] = (),
        created_by: Sequence[str] = (),
        name: str | None = None,
        exclude_locked: bool | None = None,
        ignore_shared_entries: bool | None = None,
        ignore_workbook_entries: bool | None = None,
        include_data: bool | None = None,
        include_links: bool | None = None,
        include_permissions_info: bool | None = None,
        order_by: EntryOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
        scope: EntryScope | None = None,
        type: str | None = None,
    ) -> GetEntriesOptions:
        return cls(
            ids=tuple(ids),
            created_by=tuple(created_by),
            name=name,
            exclude_locked=exclude_locked,
            ignore_shared_entries=ignore_shared_entries,
            ignore_workbook_entries=ignore_workbook_entries,
            include_data=include_data,
            include_links=include_links,
            include_permissions_info=include_permissions_info,
            order_by=order_by,
            order_direction=order_direction,
            page_size=page_size,
            scope=scope,
            type=type,
        )


@dataclass(frozen=True, slots=True)
class DirectoryListOptions:
    created_by: str | tuple[str, ...] | None = None
    name: str | None = None
    include_permissions_info: bool | None = None
    order_by: EntryOrderField | None = None
    order_direction: SortDirection = "asc"
    page_size: int = 100
    scope: EntryScope | tuple[EntryScope, ...] | None = None

    def __post_init__(self) -> None:
        _normalize_entry_scopes(self.scope)

    @classmethod
    def create(
        cls,
        *,
        created_by: str | Sequence[str] | None = None,
        name: str | None = None,
        include_permissions_info: bool | None = None,
        order_by: EntryOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
        scope: EntryScope | Sequence[EntryScope] | None = None,
    ) -> DirectoryListOptions:
        normalized = tuple(created_by) if created_by is not None and not isinstance(created_by, str) else created_by
        normalized_scope = _normalize_entry_scopes(scope)
        return cls(
            created_by=normalized,
            name=name,
            include_permissions_info=include_permissions_info,
            order_by=order_by,
            order_direction=order_direction,
            page_size=page_size,
            scope=normalized_scope,
        )


@dataclass(frozen=True, slots=True)
class CollectionListOptions:
    filter_string: str | None = None
    include_permissions_info: bool | None = None
    mode: CollectionContentMode = "all"
    only_my: bool | None = None
    order_by: StructureOrderField | None = None
    order_direction: SortDirection = "asc"
    page_size: int = 100


@dataclass(frozen=True, slots=True)
class WorkbookListOptions:
    created_by: str | None = None
    name: str | None = None
    include_permissions_info: bool | None = None
    order_by: EntryOrderField | None = None
    order_direction: SortDirection = "asc"
    page_size: int = 100
    scope: EntryScope | tuple[EntryScope, ...] | None = None

    def __post_init__(self) -> None:
        _normalize_entry_scopes(self.scope)

    @classmethod
    def create(
        cls,
        *,
        created_by: str | None = None,
        name: str | None = None,
        include_permissions_info: bool | None = None,
        order_by: EntryOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
        scope: EntryScope | Sequence[EntryScope] | None = None,
    ) -> WorkbookListOptions:
        normalized_scope = _normalize_entry_scopes(scope)
        return cls(
            created_by=created_by,
            name=name,
            include_permissions_info=include_permissions_info,
            order_by=order_by,
            order_direction=order_direction,
            page_size=page_size,
            scope=normalized_scope,
        )


@dataclass(frozen=True, slots=True)
class RelationOptions:
    include_permissions_info: bool | None = None
    link_direction: LinkDirection | None = None
    page_size: int = 100
    scope: EntryScope | None = None

    def __post_init__(self) -> None:
        _validate_entry_scope(self.scope)
