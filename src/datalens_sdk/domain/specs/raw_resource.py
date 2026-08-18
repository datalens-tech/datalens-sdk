from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.serialization.json_types import JsonValue


@dataclass(frozen=True, slots=True)
class RawCreateSpec:
    response_snapshot: Mapping[str, JsonValue] = field(repr=False)
    name: str
    location: EntryLocation


@dataclass(frozen=True, slots=True)
class RawReplaceSpec:
    response_snapshot: Mapping[str, JsonValue] = field(repr=False)
    target_id: str
    target_name: str | None
    target_location: EntryLocation | None
    target_revision_id: str | None = None
