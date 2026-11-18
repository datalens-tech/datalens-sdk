from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EntryStateRecord:
    """Raw entry state stored by ``createEntryState``; ``data`` is the opaque JSON object."""

    entry_id: str
    hash: str
    data: Mapping[str, object] | None
    created_at: datetime | None
