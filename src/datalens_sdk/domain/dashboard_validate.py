"""Total collect-all structural validation of a dashboard (D2.6).

Pure — no HTTP, never raises. This is the inspection mirror of the fail-loud
converter validators (``_validate_unique_ids`` / ``_validate_grid`` /
``_validate_items_layout_bijection`` / wiring): the same defects surface as
accumulated :class:`ValidationIssue` records so a whole dashboard can be
inspected at once. Robust against malformed raw — bad structures are skipped,
not crashed on; non-integer geometry is reported and excluded from geometry.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import json

from datalens_sdk.domain.dashboard_layout import (
    GRID_COLUMNS,
    compact_vertical,
    find_overlaps,
    is_in_grid,
    layout_entries,
)
from datalens_sdk.domain.dashboard_types import ValidationIssue

_ITEM_CONTAINERS = ("items", "globalItems")


def validate_dashboard(data: Mapping[str, object] | None) -> tuple[ValidationIssue, ...]:
    """Collect every structural issue in ``data`` (a raw ``DashboardData``)."""
    tabs = _sequence(data.get("tabs")) if isinstance(data, Mapping) else None
    if tabs is None:
        return ()
    issues: list[ValidationIssue] = []
    _check_duplicate_ids(tabs, issues)
    for tab in tabs:
        if not isinstance(tab, Mapping):
            continue
        tab_id = _str_or_none(tab.get("id"))
        _check_layout(tab, tab_id, issues)
        _check_layout_reflow(tab, tab_id, issues)
        _check_empty_chart_ids(tab, tab_id, issues)
        _check_layout_coverage(tab, tab_id, issues)
        _check_aliases(tab, tab_id, issues)
    return tuple(issues)


# -- helpers -----------------------------------------------------------------


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return None


def _iter_mappings(value: object) -> Iterator[Mapping[str, object]]:
    seq = _sequence(value)
    if seq is None:
        return
    for item in seq:
        if isinstance(item, Mapping):
            yield item


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


# -- checks ------------------------------------------------------------------


def _check_duplicate_ids(tabs: Sequence[object], issues: list[ValidationIssue]) -> None:
    """Document-wide id uniqueness, mirroring ``_validate_unique_ids``.

    A shared item legitimately repeats across the ``globalItems`` of different
    tabs (one logical identity) only when every copy carries an identical
    payload; a repeat in the same tab, a mix of ``items``/``globalItems``, or
    diverging payloads under one id is a real duplicate. Member ids share the
    item namespace; widget-tab ids are their own namespace.
    """
    seen_tabs: set[str] = set()
    # id -> [(tab_id, container, canonical payload)] in document order
    occurrences: dict[str, list[tuple[str | None, str, str]]] = {}
    seen_widget_tabs: set[str] = set()
    for tab in tabs:
        if not isinstance(tab, Mapping):
            continue
        tab_id = _str_or_none(tab.get("id"))
        if tab_id is not None:
            if tab_id in seen_tabs:
                issues.append(ValidationIssue("duplicate_id", tab_id, None, f"Duplicate tab id {tab_id!r}"))
            seen_tabs.add(tab_id)
        for container in _ITEM_CONTAINERS:
            for item in _iter_mappings(tab.get(container)):
                item_id = _str_or_none(item.get("id"))
                if item_id is not None:
                    occurrences.setdefault(item_id, []).append((tab_id, container, _canonical(item)))
                item_data = item.get("data")
                if not isinstance(item_data, Mapping):
                    continue
                for member in _iter_mappings(item_data.get("group")):
                    member_id = _str_or_none(member.get("id"))
                    if member_id is not None:
                        occurrences.setdefault(member_id, []).append((tab_id, container, _canonical(member)))
                for widget_tab in _iter_mappings(item_data.get("tabs")):
                    wt_id = _str_or_none(widget_tab.get("id"))
                    if wt_id is None:
                        continue
                    if wt_id in seen_widget_tabs:
                        issues.append(
                            ValidationIssue("duplicate_id", tab_id, item_id, f"Duplicate widget tab id {wt_id!r}")
                        )
                    seen_widget_tabs.add(wt_id)
    for item_id, occs in occurrences.items():
        if not _is_legit_shared_replicas(occs):
            # anchor at the tab of the second occurrence (where the dup surfaces)
            issues.append(ValidationIssue("duplicate_id", occs[1][0], item_id, f"Duplicate item id {item_id!r}"))


def _is_legit_shared_replicas(occs: list[tuple[str | None, str, str]]) -> bool:
    """True iff the occurrences are legal shared replicas: at most one per
    (tab, container), all in ``globalItems``, on pairwise distinct tabs, with
    identical payloads. Anything else — a same-tab repeat, an ``items`` mix,
    diverging payloads — is a real duplicate. Comparing every occurrence
    against the WHOLE set (not just the first) catches a duplicated replica
    inside one tab, which the first-occurrence check missed."""
    if len(occs) == 1:
        return True
    pair_counts: dict[tuple[str | None, str], int] = {}
    for tab_id, container, _ in occs:
        key = (tab_id, container)
        pair_counts[key] = pair_counts.get(key, 0) + 1
    return (
        all(count == 1 for count in pair_counts.values())
        and all(container == "globalItems" for _, container, _ in occs)
        and len({tab_id for tab_id, _, _ in occs}) == len(occs)
        and len({signature for _, _, signature in occs}) == 1
    )


def _check_layout(tab: Mapping[str, object], tab_id: str | None, issues: list[ValidationIssue]) -> None:
    layout = _sequence(tab.get("layout"))
    if layout is None:
        return
    valid, malformed = layout_entries(layout)
    for raw in malformed:
        item_id = _str_or_none(raw.get("i"))
        issues.append(
            ValidationIssue("out_of_grid", tab_id, item_id, f"Item {item_id!r} has non-integer layout geometry")
        )
    in_grid = []
    for entry in valid:
        if not is_in_grid(entry):
            issues.append(
                ValidationIssue(
                    "out_of_grid",
                    tab_id,
                    entry.item_id,
                    f"Item {entry.item_id!r} is out of the {GRID_COLUMNS}-column grid: "
                    f"x={entry.x} y={entry.y} w={entry.w} h={entry.h}",
                )
            )
        else:
            in_grid.append(entry)
    for first, second in find_overlaps(in_grid):
        issues.append(ValidationIssue("overlap", tab_id, first, f"Items {first!r} and {second!r} overlap"))


def _check_layout_reflow(tab: Mapping[str, object], tab_id: str | None, issues: list[ValidationIssue]) -> None:
    """Flag default-flow items the UI would silently pull upward (interior gaps).

    Trailing space below the last item is not an item, so it never reflows;
    out-of-grid entries are excluded (reported as out_of_grid) and pinned zones
    are not compacted."""
    layout = _sequence(tab.get("layout"))
    if layout is None:
        return
    valid, _ = layout_entries(layout)
    default = [entry for entry in valid if entry.parent is None and is_in_grid(entry)]
    new_y = compact_vertical(default)
    for entry in default:
        compacted = new_y.get(entry.item_id, entry.y)
        if compacted != entry.y:
            issues.append(
                ValidationIssue(
                    "layout_reflow",
                    tab_id,
                    entry.item_id,
                    f"Item {entry.item_id!r} reflows: y={entry.y} -> y={compacted}",
                )
            )


def _check_empty_chart_ids(tab: Mapping[str, object], tab_id: str | None, issues: list[ValidationIssue]) -> None:
    for container in _ITEM_CONTAINERS:
        for item in _iter_mappings(tab.get(container)):
            if item.get("type") != "widget":
                continue
            item_id = _str_or_none(item.get("id"))
            item_data = item.get("data")
            if not isinstance(item_data, Mapping):
                continue
            for widget_tab in _iter_mappings(item_data.get("tabs")):
                chart_id = widget_tab.get("chartId")
                if not isinstance(chart_id, str) or not chart_id:
                    issues.append(
                        ValidationIssue(
                            "empty_chart_id", tab_id, item_id, f"Widget {item_id!r} has a chart tab with no chartId"
                        )
                    )


def _check_layout_coverage(tab: Mapping[str, object], tab_id: str | None, issues: list[ValidationIssue]) -> None:
    item_ids: set[str] = set()
    for container in _ITEM_CONTAINERS:
        for item in _iter_mappings(tab.get(container)):
            item_id = _str_or_none(item.get("id"))
            if item_id is not None:
                item_ids.add(item_id)
    layout_ids: set[str] = set()
    layout_counts: dict[str, int] = {}
    for entry in _iter_mappings(tab.get("layout")):
        layout_id = _str_or_none(entry.get("i"))
        if layout_id is not None:
            layout_ids.add(layout_id)
            layout_counts[layout_id] = layout_counts.get(layout_id, 0) + 1
    for duplicate in sorted(layout_id for layout_id, count in layout_counts.items() if count > 1):
        issues.append(
            ValidationIssue(
                "duplicate_layout", tab_id, duplicate, f"Layout references item {duplicate!r} more than once"
            )
        )
    for missing in sorted(item_ids - layout_ids):
        issues.append(ValidationIssue("missing_layout", tab_id, missing, f"Item {missing!r} has no layout entry"))
    for orphan in sorted(layout_ids - item_ids):
        issues.append(ValidationIssue("orphan_layout", tab_id, orphan, f"Layout entry {orphan!r} references no item"))


def _check_aliases(tab: Mapping[str, object], tab_id: str | None, issues: list[ValidationIssue]) -> None:
    aliases = tab.get("aliases")
    if not isinstance(aliases, Mapping):
        return
    groups = _sequence(aliases.get("default"))
    if groups is None:
        return
    seen_groups: set[frozenset[str]] = set()
    for group in groups:
        fields = _sequence(group)
        if fields is None:
            continue
        raw = list(fields)
        string_fields = [value for value in raw if isinstance(value, str) and value]
        # mirror the converter's _validate_tab_wiring: a group must be >=2 fields,
        # all non-empty strings, and unique — any of those failing is malformed
        # (empty/non-string entries drop out of string_fields, so the counts diverge)
        if len(raw) < 2 or len(string_fields) != len(raw) or len(set(string_fields)) != len(raw):
            issues.append(
                ValidationIssue(
                    "alias_group_too_small",
                    tab_id,
                    None,
                    f"Alias group must be >=2 unique non-empty string fields, got {raw!r}",
                )
            )
            continue
        key = frozenset(string_fields)
        if key in seen_groups:
            issues.append(
                ValidationIssue("duplicate_alias_group", tab_id, None, f"Duplicate alias group {sorted(key)!r}")
            )
        seen_groups.add(key)
