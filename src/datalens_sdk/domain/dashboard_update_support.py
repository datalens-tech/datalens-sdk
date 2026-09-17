"""Shared support for the dashboard update builder: the shadow-index data
structures and tolerant raw-document helpers (epic D3).

Split out of :mod:`datalens_sdk.domain.dashboard_update` to keep each domain
module within the size invariant; everything here is package-internal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from datalens_sdk.domain.specs.dashboard import (
    ExternalControlItem,
    GroupControlItem,
    ImageItem,
    TextItem,
    TitleItem,
    WidgetItem,
)
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.editor_chart import EditorChart
    from datalens_sdk.domain.wizard_chart import WizardChart

_ITEMS_FIELD = "items"
_GLOBAL_ITEMS_FIELD = "globalItems"

# One-shot staging tab title for the update-side item adders; never emitted.
_STAGED_TAB_TITLE = "__staged__"

_SPEC_ITEM_TYPES: dict[type, str] = {
    WidgetItem: "widget",
    TextItem: "text",
    TitleItem: "title",
    ImageItem: "image",
    GroupControlItem: "group_control",
    ExternalControlItem: "control",
}


@dataclass(slots=True)
class _ItemOccurrence:
    tab_id: str
    container: str  # "items" | "globalItems"


@dataclass(slots=True)
class _TabIndex:
    """One tab's identity slice of the shadow index."""

    tab_id: str
    title: str | None
    item_ids: set[str] = field(default_factory=set)
    widget_tab_ids: set[str] = field(default_factory=set)
    control_child_ids: set[str] = field(default_factory=set)


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _iter_mappings(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [entry for entry in value if isinstance(entry, Mapping)]
    return []


def _iter_mappings_or_lists(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _resolve_widget_tab_ids_for_update(
    *,
    item_id: str,
    raw_tabs: Sequence[Mapping[str, object]],
    occurrence_count: int,
    staged_widget_tab_ids: set[str],
) -> tuple[str | None, ...]:
    """Resolve one live widget occurrence, preserving malformed inner ids."""
    raw_occurrences = [
        item
        for tab in raw_tabs
        for container in (_ITEMS_FIELD, _GLOBAL_ITEMS_FIELD)
        for item in _iter_mappings(tab.get(container))
        if item.get("id") == item_id
    ]
    if len(raw_occurrences) > 1:
        raise DataLensValidationError(
            f"Widget item id {item_id!r} occurs {len(raw_occurrences)} times; DataLens widget ids must be unique"
        )
    if raw_occurrences:
        data = _mapping_or_none(raw_occurrences[0].get("data")) or {}
        return tuple(_string_or_none(widget_tab.get("id")) for widget_tab in _iter_mappings(data.get("tabs")))
    if occurrence_count != 1:  # pragma: no cover - typed adders reserve unique ids
        raise DataLensValidationError(f"Widget item id {item_id!r} must occur exactly once")
    return tuple(sorted(staged_widget_tab_ids))


def _require_exact_widget_tab(item_id: str, widget_tab_id: str | None, widget_tab_ids: tuple[str | None, ...]) -> None:
    if widget_tab_id is None:
        if len(widget_tab_ids) != 1:
            known = sorted(tab_id for tab_id in widget_tab_ids if tab_id is not None)
            raise DataLensValidationError(
                f"Widget {item_id!r} has {len(widget_tab_ids)} chart tabs ({known!r}); pass widget_tab_id= to pick one"
            )
        return
    match_count = widget_tab_ids.count(widget_tab_id)
    if match_count == 0:
        known = sorted(tab_id for tab_id in widget_tab_ids if tab_id is not None)
        raise DataLensValidationError(f"Widget {item_id!r} has no chart tab {widget_tab_id!r}; known: {known!r}")
    if match_count != 1:
        raise DataLensValidationError(
            f"Widget {item_id!r} has {match_count} chart tabs with id {widget_tab_id!r}; expected exactly one"
        )


def _display_pinned_to_current_tabs(item: Mapping[str, object], tab_ids: set[object]) -> bool:
    """True when the item's DISPLAY scope is an explicit tab list (it must not
    follow new tabs). Dashboard V2 keeps display scope on the group itself;
    member-level impact fields only describe that member's influence."""
    del tab_ids
    item_data = _mapping_or_none(item.get("data"))
    if item_data is None:
        return False
    return item_data.get("impactType") == "selectedTabs"


def _shared_ids_displayed_on_all_tabs(tabs: Sequence[Mapping[str, object]]) -> list[str]:
    """Ids of shared items a freshly added tab inherits, in first-seen order.

    DISPLAY on the wire is globalItems membership — a selector shows on all tabs
    iff EVERY existing tab carries it. Member ``impactType`` is influence and
    must not drive this decision. Explicit group-level ``selectedTabs`` display
    pins stay pinned to their list. This is the single source of truth for the
    decision, shared by the update builder's shadow index and the converter
    applier (they must never diverge)."""
    if not tabs:
        return []
    tab_ids = {tab.get("id") for tab in tabs}
    counts: dict[str, int] = {}
    first_item: dict[str, Mapping[str, object]] = {}
    for tab in tabs:
        seen_here: set[str] = set()
        for item in _iter_mappings(tab.get("globalItems")):
            item_id = item.get("id")
            if not isinstance(item_id, str) or item_id in seen_here:
                continue
            seen_here.add(item_id)
            counts[item_id] = counts.get(item_id, 0) + 1
            first_item.setdefault(item_id, item)
    return [
        item_id
        for item_id, count in counts.items()
        if count == len(tabs) and not _display_pinned_to_current_tabs(first_item[item_id], tab_ids)
    ]


def _resolve_chart_id(chart: WizardChart | EditorChart | str) -> tuple[str, str]:
    """Resolve a chart reference into (chart_id, installation).

    Unlike attach-time resolution, no title is needed: replace_chart keeps the
    existing chart-tab title verbatim. An id string carries no installation.
    """
    if isinstance(chart, str):
        if not chart:
            raise DataLensValidationError("chart id must not be an empty string")
        return chart, ""
    if not chart.id:
        raise DataLensValidationError("Cannot place a chart without an id on a dashboard")
    return chart.id, chart.installation or ""


def _normalize_param_values(key: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        values = tuple(value)
        if all(isinstance(entry, str) for entry in values):
            return tuple(values)
    raise DataLensValidationError(f"param {key!r} must be a string or a sequence of strings, got {value!r}")
