from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from datalens_sdk.domain.entry_location import EntryLocation

__all__ = ["CollectionCreateSpec", "CollectionUpdateSpec"]


@dataclass(frozen=True, slots=True)
class CollectionCreateSpec:
    """Immutable snapshot of a collection-create builder's state."""

    name: str
    parent: EntryLocation | None
    description: str | None


@dataclass(frozen=True, slots=True)
class CollectionUpdateSpec:
    """Immutable snapshot of a collection-update builder's state."""

    collection_id: str
    changes: Mapping[str, str]
