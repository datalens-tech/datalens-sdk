from __future__ import annotations

from dataclasses import dataclass

from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.entry_types import EntryUpdateMode


@dataclass(frozen=True, slots=True)
class HtmlPageCreateSpec:
    name: str
    location: EntryLocation
    content: str
    description: str | None


@dataclass(frozen=True, slots=True)
class HtmlPageContentUpdateSpec:
    entry_id: str
    content: str
    mode: EntryUpdateMode
    description: str | None


@dataclass(frozen=True, slots=True)
class HtmlPageRevisionUpdateSpec:
    entry_id: str
    rev_id: str
    mode: EntryUpdateMode
