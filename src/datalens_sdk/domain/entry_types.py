from __future__ import annotations

from typing import Literal, TypeAlias

# Generic, entry-level type literals shared across entry kinds
# (dashboards, charts, datasets, connections). Mirrors the spec's
# EntryBranch / EntryUpdateMode schemas. Lives apart from navigation.py
# so navigation structures (EntryRelation, RelationOptions, Pager) can
# depend on these primitives without owning them.

EntryBranch: TypeAlias = Literal["saved", "published"]
EntryUpdateMode: TypeAlias = Literal["save", "publish"]
