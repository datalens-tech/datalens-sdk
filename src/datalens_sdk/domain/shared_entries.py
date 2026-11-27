from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

SharedEntryRole: TypeAlias = Literal["source", "target"]
SharedEntryMode: TypeAlias = Literal["all", "workbooks", "entries"]


@dataclass(frozen=True, slots=True)
class SharedEntryBinding:
    source_id: str
    target_id: str
    is_delegated: bool


@dataclass(frozen=True, slots=True)
class SharedEntryBindingEntryPermissions:
    can_copy: bool
    create_entry_binding: bool
    create_limited_entry_binding: bool
    delete: bool
    limited_view: bool
    list_access_bindings: bool
    move: bool
    security_approve: bool
    update: bool
    update_access_bindings: bool
    view: bool


@dataclass(frozen=True, slots=True)
class SharedEntryBindingWorkbookPermissions:
    can_copy: bool
    delete: bool
    embed: bool
    limited_view: bool
    list_access_bindings: bool
    move: bool
    publish: bool
    update: bool
    update_access_bindings: bool
    view: bool


@dataclass(frozen=True, slots=True)
class SharedEntryBindingEntry:
    entry_id: str
    scope: str
    type: str
    is_delegated: bool
    collection_title: str
    collection_id: str | None
    workbook_id: str | None
    key: str | None
    display_key: str | None
    permissions: SharedEntryBindingEntryPermissions | None = None


@dataclass(frozen=True, slots=True)
class SharedEntryBindingWorkbook:
    workbook_id: str
    title: str
    is_delegated: bool
    collection_title: str | None
    collection_id: str | None
    permissions: SharedEntryBindingWorkbookPermissions | None = None


SharedEntryBindingItem: TypeAlias = SharedEntryBindingEntry | SharedEntryBindingWorkbook
