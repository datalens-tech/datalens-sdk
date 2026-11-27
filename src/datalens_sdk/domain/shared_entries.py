from __future__ import annotations

from collections.abc import Mapping
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
    permissions: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SharedEntryBindingWorkbook:
    workbook_id: str
    title: str
    is_delegated: bool
    collection_title: str | None
    collection_id: str | None
    permissions: Mapping[str, object] | None = None


SharedEntryBindingItem: TypeAlias = SharedEntryBindingEntry | SharedEntryBindingWorkbook
