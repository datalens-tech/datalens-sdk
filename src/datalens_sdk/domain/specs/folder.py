from __future__ import annotations

from dataclasses import dataclass

from datalens_sdk.domain.entry_location import EntryLocation

__all__ = ["FolderCreateSpec", "FolderUpdateSpec"]


@dataclass(frozen=True, slots=True)
class FolderCreateSpec:
    """Immutable snapshot of a folder-create builder's state."""

    name: str
    location: EntryLocation


@dataclass(frozen=True, slots=True)
class FolderUpdateSpec:
    """Immutable snapshot of a folder-update builder's state."""

    folder_id: str
    name: str
