from __future__ import annotations

from typing import Literal, TypeAlias, get_args

from datalens_sdk.errors import DataLensValidationError

# Generic, entry-level type literals shared across entry kinds
# (dashboards, charts, datasets, connections). Mirrors the spec's
# EntryBranch / EntryUpdateMode schemas. Lives apart from navigation.py
# so navigation structures (EntryRelation, RelationOptions, Pager) can
# depend on these primitives without owning them.

EntryBranch: TypeAlias = Literal["saved", "published"]
EntryUpdateMode: TypeAlias = Literal["save", "publish"]


def validate_entry_update_mode(value: EntryUpdateMode) -> EntryUpdateMode:
    if value not in get_args(EntryUpdateMode):
        raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
    return value
