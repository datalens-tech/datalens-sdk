from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from datalens_sdk.domain.entry_location import EntryLocation

__all__ = ["WorkbookCreateSpec", "WorkbookUpdateSpec"]


@dataclass(frozen=True, slots=True)
class WorkbookCreateSpec:
    """Immutable snapshot of a workbook-create builder's state."""

    name: str
    collection: EntryLocation | None
    description: str | None


@dataclass(frozen=True, slots=True)
class WorkbookUpdateSpec:
    """Immutable snapshot of a workbook-update builder's state."""

    workbook_id: str
    changes: Mapping[str, str]
