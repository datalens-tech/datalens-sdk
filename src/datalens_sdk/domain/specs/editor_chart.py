from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from datalens_sdk.domain.entry_location import EntryLocation

__all__ = ["EditorChartCreateSpec"]


@dataclass(frozen=True, slots=True)
class EditorChartCreateSpec:
    """Immutable snapshot of an editor-chart-create builder's state.

    This is the read contract between the domain builder layer and the
    converter/api layers. Converters and services consume this spec instead of
    reaching into builder ``_protected`` attributes.
    """

    wire_type: str
    name: str
    tabs: Mapping[str, str | None]
    location: EntryLocation
    description: str | None
