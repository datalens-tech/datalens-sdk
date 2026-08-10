"""Layout applicators for the dashboard update RMW engine (epics D5.2 / D5.3).

Split out of :mod:`datalens_sdk.converter.dashboard_apply` (the plan's intended
``dashboard_apply_layout`` seam): deferred auto-placement, the six point layout
operations, occurrence marking and the final overlap gate. This module is the
lower layer — it imports nothing from ``dashboard_apply`` (one-way dependency),
so it also hosts the raw-navigation primitive ``_data_tabs`` those ops share.
"""

from __future__ import annotations

from typing import cast

from datalens_sdk.domain.dashboard_layout import (
    GRID_COLUMNS,
    compact_vertical,
    find_overlaps,
    is_in_grid,
    layout_entries,
)
from datalens_sdk.domain.specs.dashboard import (
    ApplyLayoutOp,
    AutoLayoutItemSpec,
    CompactLayoutOp,
    LayoutItemSpec,
    MoveItemOp,
    PinItemOp,
    ResizeItemOp,
    ShiftBelowOp,
    SwapItemsOp,
    UnpinItemOp,
)
from datalens_sdk.errors import DataLensValidationError


def _data_tabs(data: dict[str, object]) -> list[dict[str, object]]:
    tabs = data.get("tabs")
    if not isinstance(tabs, list):
        raise DataLensValidationError("Dashboard data tabs is not a list; cannot apply update ops")
    return cast("list[dict[str, object]]", [tab for tab in tabs if isinstance(tab, dict)])


def _mark(affected: set[tuple[str, str]], tab: dict[str, object], item_id: object) -> None:
    tab_id = tab.get("id")
    if isinstance(tab_id, str) and isinstance(item_id, str):
        affected.add((tab_id, item_id))


def _resolve_auto_layout(
    op_layout: tuple[LayoutItemSpec | AutoLayoutItemSpec, ...],
    existing: list[object],
) -> tuple[LayoutItemSpec, ...]:
    """Resolve deferred ``at=None`` entries below the target tab's current
    content: this op's auto items start a fresh row under the bottom of their
    pin-group and flow left-to-right, wrapping when a row fills. Flow markers
    replay the create-side structure: ``new_row``/``gap`` break the row,
    ``floor`` (an explicit section divider's bottom) raises the item to
    ``y >= floor`` because concrete entries never move this cursor."""
    # out-of-grid / malformed rows are preserved verbatim but must not move the
    # auto cursor (mirrors validate()'s in-grid filter)
    bottoms: dict[str | None, int] = {}
    valid, _ = layout_entries(existing)
    for existing_entry in valid:
        if is_in_grid(existing_entry):
            bottoms[existing_entry.parent] = max(
                bottoms.get(existing_entry.parent, 0), existing_entry.y + existing_entry.h
            )
    cursors: dict[str | None, tuple[int, int, int]] = {}  # group -> (x, y, row_height)
    resolved: list[LayoutItemSpec] = []
    for entry in op_layout:
        if isinstance(entry, AutoLayoutItemSpec):
            x, y, row_height = cursors.get(entry.parent, (0, bottoms.get(entry.parent, 0), 0))
            if entry.new_row:  # start_row()/space() marker: break the row here
                x, y, row_height = 0, y + row_height, 0
            if x + entry.w > GRID_COLUMNS:
                x, y, row_height = 0, y + row_height, 0
            if y < entry.floor:  # explicit section divider's cursor floor raises the BASE
                x, y, row_height = 0, entry.floor, 0
            y += entry.gap  # the gap rides on top of the (possibly floored) row base
            cursors[entry.parent] = (x + entry.w, y, max(row_height, entry.h))
            resolved.append(LayoutItemSpec(i=entry.i, x=x, y=y, w=entry.w, h=entry.h, parent=entry.parent))
        else:
            resolved.append(entry)
    return tuple(resolved)


def _entry_int(entry: dict[str, object], key: str) -> int:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataLensValidationError(f"layout entry {entry.get('i')!r} has a non-integer {key}")
    return value


def _check_bounds(item_id: str, x: int, y: int, w: int, h: int) -> None:
    if x < 0 or y < 0:
        raise DataLensValidationError(f"Item {item_id!r} would leave the grid: x={x}, y={y} (must be >= 0)")
    if w <= 0 or h <= 0:
        raise DataLensValidationError(f"Item {item_id!r} must keep w and h > 0, got w={w}, h={h}")
    if x + w > GRID_COLUMNS:
        raise DataLensValidationError(
            f"Item {item_id!r} would exceed the {GRID_COLUMNS}-column grid: x={x} + w={w} = {x + w}"
        )


def _item_layout_entries(
    data: dict[str, object], item_id: str, tab_id: str | None = None
) -> list[tuple[dict[str, object], dict[str, object]]]:
    out: list[tuple[dict[str, object], dict[str, object]]] = []
    for tab in _data_tabs(data):
        if tab_id is not None and tab.get("id") != tab_id:
            continue
        layout = tab.get("layout")
        if not isinstance(layout, list):
            continue
        for entry in layout:
            if isinstance(entry, dict) and entry.get("i") == item_id:
                out.append((tab, entry))
    return out


def _require_occurrence_layout_entries(
    data: dict[str, object], item_id: str, op_name: str
) -> list[tuple[dict[str, object], dict[str, object]]]:
    """Layout entries of an item with the "all occurrences" contract enforced:
    every tab carrying the item (items or globalItems) must have EXACTLY ONE
    layout entry for it. Without this, a shared item with a missing layout on
    one tab would be mutated on the others only, silently desynchronizing the
    identical-id replicas."""
    entries = _item_layout_entries(data, item_id)
    if not entries:
        raise DataLensValidationError(f"{op_name}: no layout entry for {item_id!r}")
    counts: dict[object, int] = {}
    for tab, _ in entries:
        tab_id = tab.get("id")
        counts[tab_id] = counts.get(tab_id, 0) + 1
    for tab in _data_tabs(data):
        occurs = False
        for container in ("items", "globalItems"):
            container_items = tab.get(container)
            if isinstance(container_items, list) and any(
                isinstance(entry, dict) and entry.get("id") == item_id for entry in container_items
            ):
                occurs = True
                break
        if not occurs:
            continue
        count = counts.get(tab.get("id"), 0)
        if count != 1:
            raise DataLensValidationError(
                f"{op_name}: item {item_id!r} occurs on tab {tab.get('id')!r} but has {count} layout entries there "
                "(validate() reports this as missing_layout/duplicate_layout); cannot apply to all occurrences"
            )
    return entries


def _apply_move_item(data: dict[str, object], op: MoveItemOp, affected: set[tuple[str, str]]) -> None:
    entries = _require_occurrence_layout_entries(data, op.item_id, "move_item")
    for tab, entry in entries:
        x = op.x if op.x is not None else _entry_int(entry, "x") + (op.dx or 0)
        y = op.y if op.y is not None else _entry_int(entry, "y") + (op.dy or 0)
        _check_bounds(op.item_id, x, y, _entry_int(entry, "w"), _entry_int(entry, "h"))
        if entry.get("x") == x and entry.get("y") == y:
            continue  # no-op move: leave a pre-existing overlap alone
        entry["x"], entry["y"] = x, y
        _mark(affected, tab, op.item_id)


def _apply_resize_item(data: dict[str, object], op: ResizeItemOp, affected: set[tuple[str, str]]) -> None:
    entries = _require_occurrence_layout_entries(data, op.item_id, "resize_item")
    for tab, entry in entries:
        w = op.w if op.w is not None else _entry_int(entry, "w") + (op.dw or 0)
        h = op.h if op.h is not None else _entry_int(entry, "h") + (op.dh or 0)
        _check_bounds(op.item_id, _entry_int(entry, "x"), _entry_int(entry, "y"), w, h)
        if entry.get("w") == w and entry.get("h") == h:
            continue  # no-op resize: leave a pre-existing overlap alone
        entry["w"], entry["h"] = w, h
        _mark(affected, tab, op.item_id)


def _apply_swap_items(data: dict[str, object], op: SwapItemsOp, affected: set[tuple[str, str]]) -> None:
    shared: dict[str, dict[str, dict[str, object]]] = {}
    for tab in _data_tabs(data):
        tab_id = tab.get("id")
        layout = tab.get("layout")
        if not isinstance(tab_id, str) or not isinstance(layout, list):
            continue
        found = {
            entry["i"]: entry
            for entry in layout
            if isinstance(entry, dict) and entry.get("i") in (op.first_item_id, op.second_item_id)
        }
        if op.first_item_id in found and op.second_item_id in found:
            shared[tab_id] = found
    if op.tab_id is not None:
        if op.tab_id not in shared:
            raise DataLensValidationError(
                f"swap_items: {op.first_item_id!r} and {op.second_item_id!r} are not both on tab {op.tab_id!r}"
            )
        targets = [op.tab_id]
    elif len(shared) == 1:
        targets = list(shared)
    else:
        raise DataLensValidationError(
            f"swap_items: {op.first_item_id!r} and {op.second_item_id!r} appear together on "
            f"{sorted(shared)}; pass tab= to disambiguate"
        )
    for tab_id in targets:
        first, second = shared[tab_id][op.first_item_id], shared[tab_id][op.second_item_id]
        geom = ("x", "y", "w", "h")
        if all(first.get(k) == second.get(k) for k in geom):
            continue  # identical geometry: the swap is a no-op, leave overlaps alone
        for key in geom:
            first[key], second[key] = second.get(key), first.get(key)
        _check_bounds(op.first_item_id, *(_entry_int(first, k) for k in geom))
        _check_bounds(op.second_item_id, *(_entry_int(second, k) for k in geom))
        affected.add((tab_id, op.first_item_id))
        affected.add((tab_id, op.second_item_id))


def _apply_shift_below(data: dict[str, object], op: ShiftBelowOp, affected: set[tuple[str, str]]) -> None:
    for tab in _data_tabs(data):
        if op.tab_id is not None and tab.get("id") != op.tab_id:
            continue
        layout = tab.get("layout")
        if not isinstance(layout, list):
            continue
        for entry in layout:
            if not isinstance(entry, dict):
                continue
            y = entry.get("y")
            if isinstance(y, int) and not isinstance(y, bool) and y >= op.y_threshold:
                new_y = y + op.dy
                if new_y < 0:
                    raise DataLensValidationError(
                        f"shift_below moved item {entry.get('i')!r} above the grid (y={new_y})"
                    )
                entry["y"] = new_y
                _mark(affected, tab, entry.get("i"))


def _apply_pin_item(data: dict[str, object], op: PinItemOp, affected: set[tuple[str, str]]) -> None:
    entries = _require_occurrence_layout_entries(data, op.item_id, "pin_item")
    for tab, entry in entries:
        if entry.get("parent") == op.parent:
            continue  # already in this zone: no-op must not trip a pre-existing overlap
        entry["parent"] = op.parent
        _mark(affected, tab, op.item_id)


def _apply_unpin_item(data: dict[str, object], op: UnpinItemOp, affected: set[tuple[str, str]]) -> None:
    entries = _require_occurrence_layout_entries(data, op.item_id, "unpin_item")
    for tab, entry in entries:
        if entry.pop("parent", None) is not None:  # only mark when it actually unpinned
            _mark(affected, tab, op.item_id)


def _apply_apply_layout(data: dict[str, object], op: ApplyLayoutOp, affected: set[tuple[str, str]]) -> None:
    positions = {item_id: (x, y, w, h) for item_id, x, y, w, h in op.positions}
    if op.tab_id is None:
        # unscoped applies to every occurrence: enforce one entry per occurrence
        # per id (ids with no entry anywhere fall through to the unmatched error)
        for check_id in positions:
            if _item_layout_entries(data, check_id):
                _require_occurrence_layout_entries(data, check_id, "apply_layout")
    matched: set[str] = set()
    for tab in _data_tabs(data):
        if op.tab_id is not None and tab.get("id") != op.tab_id:
            continue
        layout = tab.get("layout")
        if not isinstance(layout, list):
            continue
        for entry in layout:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get("i")
            position = positions.get(item_id) if isinstance(item_id, str) else None
            if position is None:
                continue
            matched.add(cast("str", item_id))
            # apply-time bounds parity with move/resize/swap: a hand-built
            # ApplyLayoutOp must not ship out-of-grid geometry silently
            _check_bounds(cast("str", item_id), *position)
            if (entry.get("x"), entry.get("y"), entry.get("w"), entry.get("h")) != position:
                entry["x"], entry["y"], entry["w"], entry["h"] = position
                _mark(affected, tab, item_id)
    # fail loud when a requested id resolves to no entry in scope: a typo'd or
    # foreign-tab target must not look like a silent success
    unmatched = sorted(set(positions) - matched)
    if unmatched:
        scope = f" on tab {op.tab_id!r}" if op.tab_id is not None else ""
        raise DataLensValidationError(f"apply_layout: items {unmatched!r} have no layout entry{scope}")


def _apply_compact_layout(data: dict[str, object], op: CompactLayoutOp, affected: set[tuple[str, str]]) -> None:
    for tab in _data_tabs(data):
        if op.tab_id is not None and tab.get("id") != op.tab_id:
            continue
        layout = tab.get("layout")
        if not isinstance(layout, list):
            continue
        valid, _ = layout_entries(layout)
        # out-of-grid rows keep their coordinates: exclude them from compaction
        new_y = compact_vertical([entry for entry in valid if entry.parent is None and is_in_grid(entry)])
        for entry in layout:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get("i")
            # default-flow only: a pinned entry keeps its coordinates
            if not isinstance(item_id, str) or isinstance(entry.get("parent"), str) or item_id not in new_y:
                continue
            if entry.get("y") != new_y[item_id]:
                entry["y"] = new_y[item_id]
                _mark(affected, tab, item_id)


def _overlap_pairs(data: dict[str, object]) -> set[tuple[str, frozenset[str]]]:
    """Overlapping (tab_id, {item, item}) pairs among in-grid entries. Out-of-grid
    rows are excluded for parity with validate() and the auto-cursor."""
    pairs: set[tuple[str, frozenset[str]]] = set()
    for tab in _data_tabs(data):
        tab_id = tab.get("id")
        if not isinstance(tab_id, str):
            continue
        layout = tab.get("layout")
        entries, _ = layout_entries(layout if isinstance(layout, list) else [])
        for first, second in find_overlaps([entry for entry in entries if is_in_grid(entry)]):
            pairs.add((tab_id, frozenset((first, second))))
    return pairs


def _check_final_overlaps(
    data: dict[str, object], affected: set[tuple[str, str]], before: set[tuple[str, frozenset[str]]]
) -> None:
    """Fail only when this update CREATED an overlap: a pair is reported when it
    was not already overlapping before the ops ran and at least one of its items
    was touched. Pre-existing overlaps are left alone even when an op moved the
    whole pair uniformly (the renderer hides them; validate() reports)."""
    if not affected:
        return
    for tab_id, pair in _overlap_pairs(data):
        if (tab_id, pair) in before:
            continue
        first, second = sorted(pair)
        if (tab_id, first) in affected or (tab_id, second) in affected:
            raise DataLensValidationError(f"Tab {tab_id!r}: items {first!r} and {second!r} overlap")
