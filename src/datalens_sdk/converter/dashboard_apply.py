"""The dashboard update RMW engine (epic D3): op appliers over a deep copy
of the raw ``data`` snapshot.

Split out of :mod:`datalens_sdk.converter.dashboard`; everything here is
package-internal. Untouched nodes are never re-serialized or normalized:
unknown item types (neuro_widget), enableActionParams and any future fields
survive verbatim.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
import json
import re
from typing import cast, get_args

from datalens_sdk.converter.dashboard_apply_layout import (
    _apply_apply_layout,
    _apply_compact_layout,
    _apply_move_item,
    _apply_pin_item,
    _apply_resize_item,
    _apply_shift_below,
    _apply_swap_items,
    _apply_unpin_item,
    _check_final_overlaps,
    _data_tabs,
    _mark,
    _overlap_pairs,
    _resolve_auto_layout,
)
from datalens_sdk.converter.dashboard_contract import DashboardGeneratedContract
from datalens_sdk.converter.dashboard_control import (
    _drop_dangling_aliases,
    _prefixed_defaults_wire,
    _raw_default_wire,
    _tab_used_fields,
    encode_selector_default,
)
from datalens_sdk.converter.dashboard_items import (
    _CANONICAL_SETTINGS,
    _is_shared_group,
    _validate_grid,
    _validate_items_layout_bijection,
    _wire_item,
    _wire_layout_entry,
    _wire_tab,
)
from datalens_sdk.domain.dashboard_tab_selectors import _validated_selector_default
from datalens_sdk.domain.dashboard_types import (
    ControlElementType,
    SelectorDefaultValue,
    _RemoveParam,
)
from datalens_sdk.domain.dashboard_update_support import _shared_ids_displayed_on_all_tabs
from datalens_sdk.domain.specs.dashboard import (
    AddAliasOp,
    AddConnectionOp,
    AddGroupSelectorOp,
    AddItemsOp,
    AddTabOp,
    ApplyLayoutOp,
    AutoLayoutItemSpec,
    CompactLayoutOp,
    DashboardUpdateOp,
    DashboardUpdateSpec,
    GlobalParamsOp,
    GroupControlItem,
    LayoutItemSpec,
    MoveItemOp,
    PinItemOp,
    RemoveAliasOp,
    RemoveConnectionOp,
    RemoveItemOp,
    RemoveSelectorMemberOp,
    RemoveTabOp,
    ReorderTabsOp,
    ReplaceChartOp,
    ResizeItemOp,
    SetChartParamsOp,
    ShiftBelowOp,
    SwapItemsOp,
    TabSpec,
    UnpinItemOp,
    UpdateSelectorOp,
    UpdateTabOp,
)
from datalens_sdk.errors import DataLensValidationError

# -- update RMW engine (epic D3) --------------------------------------------
#
# Applies the typed op queue of a DashboardUpdateSpec to a deep copy of the
# raw ``data`` snapshot. Untouched nodes are never re-serialized or
# normalized: unknown item types (neuro_widget), enableActionParams and any
# future fields survive verbatim.

# snake spec field -> (wire settings key, canonical value present?)
_SETTINGS_WIRE_KEYS: dict[str, str] = {
    "silent_loading": "silentLoading",
    "dependent_selectors": "dependentSelectors",
    "expand_toc": "expandTOC",
    "hide_dash_title": "hideDashTitle",
    "hide_tabs": "hideTabs",
    "autoupdate_interval": "autoupdateInterval",
    "max_concurrent_requests": "maxConcurrentRequests",
    "load_priority": "loadPriority",
}


def _serialize_tab(
    contract: DashboardGeneratedContract | None,
    value: dict[str, object],
) -> dict[str, object]:
    return value if contract is None else contract.serialize_tab(value)


def _serialize_item(
    contract: DashboardGeneratedContract | None,
    value: dict[str, object],
) -> dict[str, object]:
    return value if contract is None else contract.serialize_item(value)


def _serialize_layout(
    contract: DashboardGeneratedContract | None,
    value: dict[str, object],
) -> dict[str, object]:
    return value if contract is None else contract.serialize_layout(value)


def _serialize_connection(
    contract: DashboardGeneratedContract | None,
    value: dict[str, object],
) -> dict[str, object]:
    return value if contract is None else contract.serialize_connection(value)


def _serialize_alias(
    contract: DashboardGeneratedContract | None,
    fields: tuple[str, ...],
) -> list[str]:
    return list(fields) if contract is None else contract.serialize_alias(fields)


def _apply_global_params(data: dict[str, object], op: GlobalParamsOp) -> None:
    settings = data.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise DataLensValidationError("Dashboard data settings is not an object; cannot patch globalParams")
    params = settings.setdefault("globalParams", {})
    if not isinstance(params, dict):
        raise DataLensValidationError("Dashboard settings globalParams is not an object; cannot patch it")
    for key, value in op.changes.items():
        if isinstance(value, _RemoveParam):
            params.pop(key, None)
        else:
            params[key] = list(value)


def _find_tab(data: dict[str, object], tab_id: str) -> dict[str, object]:
    for tab in _data_tabs(data):
        if tab.get("id") == tab_id:
            return tab
    raise DataLensValidationError(f"Unknown tab {tab_id!r} while applying an update op")


def _tab_item_lists(tab: dict[str, object]) -> list[list[dict[str, object]]]:
    lists: list[list[dict[str, object]]] = []
    for container in ("items", "globalItems"):
        entries = tab.get(container)
        if isinstance(entries, list):
            lists.append(cast("list[dict[str, object]]", entries))
    return lists


def _iter_tab_items(tab: dict[str, object]) -> list[dict[str, object]]:
    return [item for entries in _tab_item_lists(tab) for item in entries if isinstance(item, dict)]


def _apply_update_tab(data: dict[str, object], op: UpdateTabOp) -> None:
    tab = _find_tab(data, op.tab_id)
    if op.title is not None:
        tab["title"] = op.title
    if op.hidden is True:
        tab["hidden"] = True
    elif op.hidden is False:
        # canonical absence: the wire only carries hidden when it is true
        tab.pop("hidden", None)


def _apply_remove_tab(data: dict[str, object], op: RemoveTabOp) -> None:
    _find_tab(data, op.tab_id)
    tabs = data["tabs"]
    assert isinstance(tabs, list)
    tabs[:] = [tab for tab in tabs if not (isinstance(tab, dict) and tab.get("id") == op.tab_id)]


def _apply_reorder_tabs(data: dict[str, object], op: ReorderTabsOp) -> None:
    tabs = data["tabs"]
    assert isinstance(tabs, list)
    position = {tab_id: index for index, tab_id in enumerate(op.order)}
    if any(not isinstance(tab, dict) or tab.get("id") not in position for tab in tabs):
        raise DataLensValidationError("reorder_tabs order does not match the document tabs")
    tabs.sort(key=lambda tab: position[cast("str", cast("dict[str, object]", tab)["id"])])


def _find_item_occurrences(data: dict[str, object], item_id: str) -> list[dict[str, object]]:
    """Every occurrence of the item — a shared global item is ONE logical
    item duplicated across tabs, so patches must hit all of them."""
    occurrences = [item for tab in _data_tabs(data) for item in _iter_tab_items(tab) if item.get("id") == item_id]
    if not occurrences:
        raise DataLensValidationError(f"Unknown item {item_id!r} while applying an update op")
    return occurrences


def _item_widget_tabs(item: dict[str, object]) -> list[dict[str, object]]:
    item_data = item.get("data")
    if not isinstance(item_data, dict):
        return []
    tabs = item_data.get("tabs")
    if not isinstance(tabs, list):
        return []
    return cast("list[dict[str, object]]", [tab for tab in tabs if isinstance(tab, dict)])


def _apply_replace_chart(data: dict[str, object], op: ReplaceChartOp) -> None:
    swapped = False
    for item in _find_item_occurrences(data, op.item_id):
        widget_tabs = _item_widget_tabs(item)
        if op.widget_tab_id is None:
            if len(widget_tabs) != 1:
                raise DataLensValidationError(
                    f"Widget {op.item_id!r} does not have exactly one chart tab; pass widget_tab_id="
                )
            widget_tabs[0]["chartId"] = op.chart_id
            swapped = True
        else:
            for widget_tab in widget_tabs:
                if widget_tab.get("id") == op.widget_tab_id:
                    widget_tab["chartId"] = op.chart_id
                    swapped = True
    if not swapped:
        raise DataLensValidationError(f"Widget {op.item_id!r} has no chart tab {op.widget_tab_id!r}")


def _apply_remove_item(data: dict[str, object], op: RemoveItemOp) -> None:
    # the removal set covers connection endpoints beyond the item id itself:
    # nested group-control children AND widget chart-tab ids (live wire fact:
    # widget connections reference chart TAB ids, not the widget item id)
    removed_ids = {op.item_id}
    for tab in _data_tabs(data):
        for item in _iter_tab_items(tab):
            if item.get("id") != op.item_id:
                continue
            item_data = item.get("data")
            if isinstance(item_data, dict):
                for child in item_data.get("group") or []:
                    if isinstance(child, dict) and isinstance(child.get("id"), str):
                        removed_ids.add(cast(str, child["id"]))
                for widget_tab in item_data.get("tabs") or []:
                    if isinstance(widget_tab, dict) and isinstance(widget_tab.get("id"), str):
                        removed_ids.add(cast(str, widget_tab["id"]))
    for tab in _data_tabs(data):
        used_before = _tab_used_fields(tab)
        touched = False
        for entries in _tab_item_lists(tab):
            before = len(entries)
            entries[:] = [item for item in entries if not (isinstance(item, dict) and item.get("id") == op.item_id)]
            touched = touched or len(entries) != before
        layout = tab.get("layout")
        if isinstance(layout, list):
            layout[:] = [entry for entry in layout if not (isinstance(entry, dict) and entry.get("i") == op.item_id)]
        connections = tab.get("connections")
        if isinstance(connections, list):
            before = len(connections)
            connections[:] = [
                entry
                for entry in connections
                if not (
                    isinstance(entry, dict) and (entry.get("from") in removed_ids or entry.get("to") in removed_ids)
                )
            ]
            touched = touched or len(connections) != before
        # alias fields whose last parameter user this removal took away are
        # dropped (the UI self-repair semantics; user decision 2026-07-21
        # revising the D3 keep-them verdict) — fields used by another item,
        # never-referenced ones (cross-dataset aliases, P021) and unrelated
        # tabs stay verbatim (raw-RMW contract).
        if touched:
            _drop_dangling_aliases(tab, used_before=used_before)


def _apply_set_chart_params(data: dict[str, object], op: SetChartParamsOp) -> None:
    # every occurrence is patched: a shared global item must stay identical
    # across tabs (the builder rejects group_control at call time)
    for item in _find_item_occurrences(data, op.item_id):
        if item.get("type") == "widget":
            for widget_tab in _item_widget_tabs(item):
                if op.merge:
                    params = widget_tab.setdefault("params", {})
                    if not isinstance(params, dict):
                        raise DataLensValidationError(f"Widget {op.item_id!r} chart tab params is not an object")
                    params.update({key: list(values) for key, values in op.params.items()})
                else:
                    widget_tab["params"] = {key: list(values) for key, values in op.params.items()}
        elif op.merge:
            defaults = item.setdefault("defaults", {})
            if not isinstance(defaults, dict):
                raise DataLensValidationError(f"Item {op.item_id!r} defaults is not an object")
            defaults.update({key: list(values) for key, values in op.params.items()})
        else:
            item["defaults"] = {key: list(values) for key, values in op.params.items()}


def _apply_remove_connection(data: dict[str, object], op: RemoveConnectionOp) -> None:
    tab = _find_tab(data, op.tab_id)
    connections = tab.get("connections")
    if not isinstance(connections, list):
        raise DataLensValidationError(f"Tab {op.tab_id!r} connections is not a list")
    before = len(connections)
    connections[:] = [
        entry
        for entry in connections
        if not (isinstance(entry, dict) and entry.get("from") == op.from_id and entry.get("to") == op.to_id)
    ]
    if len(connections) == before:
        raise DataLensValidationError(f"Tab {op.tab_id!r} has no connection {op.from_id!r} -> {op.to_id!r}")


def _apply_remove_alias(data: dict[str, object], op: RemoveAliasOp) -> None:
    tab = _find_tab(data, op.tab_id)
    aliases = tab.get("aliases")
    if not isinstance(aliases, dict) or not isinstance(aliases.get("default"), list):
        raise DataLensValidationError(f"Tab {op.tab_id!r} aliases is not in the expected shape")
    groups = cast("list[object]", aliases["default"])
    wanted = set(op.fields)
    before = len(groups)
    groups[:] = [
        group
        for group in groups
        if not (isinstance(group, list) and {entry for entry in group if isinstance(entry, str)} == wanted)
    ]
    if len(groups) == before:
        raise DataLensValidationError(f"Tab {op.tab_id!r} has no alias {sorted(wanted)!r}")


def _validate_merged_tab(tab: dict[str, object]) -> None:
    """Post-validate a raw tab after structural additions.

    Unlike the create-side bijection, layout on a live tab references
    ``items`` UNION ``globalItems`` — validating against ``items`` alone
    would false-positive on tabs with shared global selectors.
    """
    tab_id = tab.get("id")
    item_ids = [
        cast(str, item.get("id"))
        for entries in _tab_item_lists(tab)
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    layout = tab.get("layout")
    layout_ids = [
        cast(str, entry.get("i"))
        for entry in (layout if isinstance(layout, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("i"), str)
    ]
    if len(set(layout_ids)) != len(layout_ids):
        raise DataLensValidationError(f"Tab {tab_id!r} layout references an item more than once")
    if len(set(item_ids)) != len(item_ids):
        raise DataLensValidationError(f"Tab {tab_id!r} carries duplicate item ids")
    if set(item_ids) != set(layout_ids):
        missing = sorted(set(item_ids) - set(layout_ids))
        orphaned = sorted(set(layout_ids) - set(item_ids))
        raise DataLensValidationError(
            f"Tab {tab_id!r} items and layout must match exactly: "
            f"items without layout {missing!r}, layout without items {orphaned!r}"
        )


def _apply_add_connection(
    data: dict[str, object],
    op: AddConnectionOp,
    contract: DashboardGeneratedContract | None,
) -> None:
    tab = _find_tab(data, op.tab_id)
    connections = tab.get("connections")
    if not isinstance(connections, list):
        raise DataLensValidationError(f"Tab {op.tab_id!r} connections is not a list")
    edge: dict[str, object] = {"from": op.from_id, "to": op.to_id, "kind": "ignore"}
    if not any(
        isinstance(entry, dict) and entry.get("from") == op.from_id and entry.get("to") == op.to_id
        for entry in connections
    ):
        connections.append(_serialize_connection(contract, edge))


def _apply_add_alias(
    data: dict[str, object],
    op: AddAliasOp,
    contract: DashboardGeneratedContract | None,
) -> None:
    tab = _find_tab(data, op.tab_id)
    aliases = tab.get("aliases")
    if not isinstance(aliases, dict):
        raise DataLensValidationError(f"Tab {op.tab_id!r} aliases is not a mapping")
    default = aliases.setdefault("default", [])
    if not isinstance(default, list):
        raise DataLensValidationError(f"Tab {op.tab_id!r} aliases.default is not a list")
    wanted = set(op.fields)
    if not any(
        isinstance(entry, list) and {value for value in entry if isinstance(value, str)} == wanted for entry in default
    ):
        default.append(_serialize_alias(contract, op.fields))


def _inherited_shared_items(data: dict[str, object], *, exclude: dict[str, object] | None = None) -> list[str]:
    """Ids of shared items a freshly added tab inherits, in first-seen order.

    Presence-based (C12): the decision lives in
    :func:`datalens_sdk.domain.dashboard_update_support._shared_ids_displayed_on_all_tabs`
    so the update builder's shadow index cannot diverge from this applier.
    """
    tabs = [tab for tab in _data_tabs(data) if tab is not exclude]
    return _shared_ids_displayed_on_all_tabs(tabs)


def _extend_tab_with_all_tabs_items(data: dict[str, object], new_tab: dict[str, object]) -> None:
    """Copy every shared item displayed on ALL existing tabs into a freshly
    added tab.

    ``show_on_tabs="all"`` means every tab of the final document, not every
    tab that happened to exist when the selector op applied — without this,
    ``add_selector(show_on_tabs="all")`` followed by ``add_tab`` in the same
    builder would skip the new tab (order-dependent result). ``selectedTabs``
    display scopes stay pinned to their explicit target list.
    """
    present = {item.get("id") for item in _iter_tab_items(new_tab)}
    inherited = set(_inherited_shared_items(data, exclude=new_tab))
    for tab in _data_tabs(data):
        if tab is new_tab:
            continue
        global_items = tab.get("globalItems")
        if not isinstance(global_items, list):
            continue
        for item in global_items:
            if not isinstance(item, dict) or item.get("id") in present or item.get("id") not in inherited:
                continue
            target_items = new_tab.setdefault("globalItems", [])
            assert isinstance(target_items, list)
            target_items.append(json.loads(json.dumps(item)))
            present.add(item.get("id"))
            layout = tab.get("layout")
            layout_entry = next(
                (
                    entry
                    for entry in (layout if isinstance(layout, list) else [])
                    if isinstance(entry, dict) and entry.get("i") == item.get("id")
                ),
                None,
            )
            new_layout = new_tab.get("layout")
            if layout_entry is not None and isinstance(new_layout, list):
                new_layout.append(dict(layout_entry))
    _validate_merged_tab(new_tab)


def _existing_all_tabs_layout(data: dict[str, object]) -> list[object]:
    """Layout entries of the shared selectors a fresh tab will inherit — the
    band its own auto content must flow below."""
    inherited = _inherited_shared_items(data)
    entries: list[object] = []
    for item_id in inherited:
        for tab in _data_tabs(data):
            layout = tab.get("layout")
            entry = next(
                (
                    candidate
                    for candidate in (layout if isinstance(layout, list) else [])
                    if isinstance(candidate, dict) and candidate.get("i") == item_id
                ),
                None,
            )
            if entry is not None:
                entries.append(entry)
                break
    return entries


def _apply_add_tab(
    data: dict[str, object],
    op: AddTabOp,
    affected: set[tuple[str, str]],
    contract: DashboardGeneratedContract | None,
) -> None:
    tabs = data.get("tabs")
    if not isinstance(tabs, list):
        raise DataLensValidationError("Dashboard data tabs is not a list; cannot append a tab")
    if any(isinstance(tab, dict) and tab.get("id") == op.tab.id for tab in tabs):
        raise DataLensValidationError(f"Duplicate tab id {op.tab.id!r}")
    # resolve the new tab's own at=None items BELOW the allTabs band it inherits,
    # so inherited filters stay on top; shared groups defined here per-target below
    resolved_layout = _resolve_auto_layout(op.tab.layout, _existing_all_tabs_layout(data))
    resolved_tab = replace(op.tab, layout=resolved_layout)
    _validate_grid(resolved_tab)
    _validate_items_layout_bijection(resolved_tab)
    # Serialize the entirely SDK-owned tab before inherited raw globalItems
    # and layout fragments are spliced in below.
    wire = _serialize_tab(contract, _wire_tab(resolved_tab))
    tabs.append(wire)
    _validate_member_affects_targets(resolved_tab.items, data)
    # pull the document's existing all-tabs selectors INTO the new tab FIRST, so
    # a shared group defined on this tab resolves below the inherited band
    _extend_tab_with_all_tabs_items(data, wire)
    # _wire_tab keeps shared groups out of items/layout: replicate them into
    # globalItems of their target tabs (the new tab included), per target. On
    # the SOURCE (new) tab the jointly resolved slot is reused so mixed
    # local/shared autos keep their row-flow; other targets resolve the ORIGINAL
    # spec below their own content.
    orig_spec_by_item = {entry.i: entry for entry in op.tab.layout}
    resolved_by_item = {entry.i: entry for entry in resolved_tab.layout if isinstance(entry, LayoutItemSpec)}
    for item in resolved_tab.items:
        if _is_shared_group(item):
            _propagate_shared_group(
                data,
                resolved_tab,
                item,
                orig_spec_by_item[item.id],
                affected,
                contract,
                source_entry=resolved_by_item[item.id],
            )
    # a freshly added tab has no create-side overlap check: mark every item it
    # carries (its own content plus the inherited allTabs selectors) so the final
    # gate rejects a collision instead of shipping it silently
    for wire_item in _iter_tab_items(wire):
        _mark(affected, wire, wire_item.get("id"))


def _propagate_shared_group(
    data: dict[str, object],
    staged: TabSpec,
    item: object,
    layout_spec: LayoutItemSpec | AutoLayoutItemSpec,
    affected: set[tuple[str, str]],
    contract: DashboardGeneratedContract | None,
    *,
    source_entry: LayoutItemSpec | None = None,
) -> None:
    """Replicate a shared group_control into globalItems of its target tabs
    (identical id contract) with a layout entry per tab. An auto-placed
    (``at=None``) group flows below EACH target tab's own content, not the source
    tab's — except the SOURCE tab itself, which reuses ``source_entry`` (the slot
    the op's joint auto-resolution assigned) so mixed local/shared autos keep
    their row-flow. Every propagated occurrence joins ``affected`` so the final
    overlap gate covers target-tab collisions."""
    assert isinstance(item, GroupControlItem)
    tabs = _data_tabs(data)
    known_ids = [_string_or_none_apply(tab.get("id")) for tab in tabs]
    if item.show_on_tabs == "all":
        targets = [tab_id for tab_id in known_ids if tab_id is not None]
    else:
        targets = list(item.show_on_tabs)
        unknown = sorted(set(targets) - set(known_ids))
        if unknown:
            raise DataLensValidationError(f"Selector {item.id!r} show_on_tabs references unknown tab ids {unknown!r}")
    item_wire = _serialize_item(contract, _wire_item(staged, item))
    for tab in tabs:
        if tab.get("id") not in targets:
            continue
        global_items = tab.setdefault("globalItems", [])
        if not isinstance(global_items, list):
            raise DataLensValidationError(f"Tab {tab.get('id')!r} globalItems is not a list")
        layout = tab.get("layout")
        if not isinstance(layout, list):
            raise DataLensValidationError(f"Tab {tab.get('id')!r} layout is not a list")
        if source_entry is not None and tab.get("id") == staged.id:
            # the source tab keeps the jointly resolved slot (row-flow intact)
            resolved_entry = source_entry
        else:
            # resolve the position against THIS tab's content (a no-op for a concrete spec)
            (resolved_entry,) = _resolve_auto_layout((layout_spec,), layout)
        global_items.append(json.loads(json.dumps(item_wire)))
        layout.append(_serialize_layout(contract, _wire_layout_entry(resolved_entry)))
        _mark(affected, tab, item.id)
        _validate_merged_tab(tab)


def _string_or_none_apply(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _validate_member_affects_targets(items: Iterable[object], data: dict[str, object]) -> None:
    """Update-side parity with create's ``_validate_show_on_tabs_targets``: a
    group member scoped with ``affects=(tab ids...)`` must reference tabs that
    exist in the document (else the wire ships a bogus ``selectedTabs`` scope)."""
    known = {tab_id for tab_id in (_string_or_none_apply(tab.get("id")) for tab in _data_tabs(data)) if tab_id}
    for item in items:
        if not isinstance(item, GroupControlItem):
            continue
        for member in item.members:
            if isinstance(member.affects, tuple):
                unknown = sorted(set(member.affects) - known)
                if unknown:
                    raise DataLensValidationError(f"Selector {member.id!r} references unknown tab ids {unknown!r}")


def _apply_add_items(
    data: dict[str, object],
    op: AddItemsOp,
    affected: set[tuple[str, str]],
    contract: DashboardGeneratedContract | None,
) -> None:
    # grid bounds are checked on the NEW entries only; the merged tab is then
    # checked for id uniqueness and layout<->items consistency
    tab = _find_tab(data, op.tab_id)
    items = tab.get("items")
    layout = tab.get("layout")
    if not isinstance(items, list) or not isinstance(layout, list):
        raise DataLensValidationError(f"Tab {op.tab_id!r} items/layout are not lists; cannot add items")
    _validate_member_affects_targets(op.items, data)
    resolved_layout = _resolve_auto_layout(op.layout, layout)
    staged = TabSpec(id=op.tab_id, title="", items=op.items, layout=resolved_layout)
    _validate_grid(staged)
    layout_by_item = {entry.i: entry for entry in resolved_layout}
    orig_spec_by_item = {entry.i: entry for entry in op.layout}
    for item in op.items:
        if _is_shared_group(item):
            # shared groups resolve per target tab; the source tab keeps the
            # jointly resolved slot so mixed local/shared autos keep row-flow
            _propagate_shared_group(
                data,
                staged,
                item,
                orig_spec_by_item[item.id],
                affected,
                contract,
                source_entry=layout_by_item[item.id],
            )
            continue
        items.append(_serialize_item(contract, _wire_item(staged, item)))
        layout.append(_serialize_layout(contract, _wire_layout_entry(layout_by_item[item.id])))
        # every added occurrence joins the affected set so the final overlap gate covers it
        _mark(affected, tab, item.id)
    _validate_merged_tab(tab)


def _selector_member_and_source(
    item: dict[str, object], member_id: str | None
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    item_data = item.get("data")
    item_data = item_data if isinstance(item_data, dict) else {}
    if member_id is None:
        source = item_data.get("source")
        defaults = item.setdefault("defaults", {})
        if not isinstance(source, dict) or not isinstance(defaults, dict):
            raise DataLensValidationError(f"Control {item.get('id')!r} carries no patchable source")
        # standalone control: the title lives on data
        return item_data, source, defaults
    for member in item_data.get("group") or []:
        if isinstance(member, dict) and member.get("id") == member_id:
            source = member.get("source")
            defaults = member.setdefault("defaults", {})
            if not isinstance(source, dict) or not isinstance(defaults, dict):
                raise DataLensValidationError(f"Selector {member_id!r} carries no patchable source")
            return member, source, defaults
    raise DataLensValidationError(f"Group {item.get('id')!r} has no member {member_id!r}")


def _update_selector_default(value: SelectorDefaultValue, source: dict[str, object]) -> SelectorDefaultValue:
    """Normalize an update_selector default against the selector's live
    elementType so update and create emit the same wire forms (select defaults
    are lists, checkbox requires a bool, intervals are date-only)."""
    element = source.get("elementType")
    if isinstance(element, str) and element in get_args(ControlElementType):
        normalized = _validated_selector_default(value, element=cast("ControlElementType", element))
        assert normalized is not None  # the input value is non-None on this path
        return normalized
    return value


def _selector_defaults_key(source: dict[str, object], op: UpdateSelectorOp) -> str:
    defaults_key = source.get("datasetFieldId") or source.get("fieldName")
    if not isinstance(defaults_key, str) or not defaults_key:
        raise DataLensValidationError(f"Selector {op.member_id or op.item_id!r} has no defaults key")
    return defaults_key


def _apply_update_selector(data: dict[str, object], op: UpdateSelectorOp) -> None:
    for item in _find_item_occurrences(data, op.item_id):
        member, source, defaults = _selector_member_and_source(item, op.member_id)
        if op.title is not None:
            member["title"] = op.title
        if op.operation is not None:
            source["operation"] = op.operation
        if op.required is not None:
            source["required"] = op.required
        if op.hint is not None:
            source["hint"] = op.hint
            source["showHint"] = True
        field_type = source.get("fieldType")
        operation = source.get("operation")
        if op.default_value is not None:
            normalized = _update_selector_default(op.default_value, source)
            defaults_key = _selector_defaults_key(source, op)
            source["defaultValue"] = _raw_default_wire(
                normalized, field_type=field_type if isinstance(field_type, str) else ""
            )
            defaults.clear()
            defaults[defaults_key] = encode_selector_default(
                normalized,
                field_type=field_type if isinstance(field_type, str) else "",
                operation=operation if isinstance(operation, str) else None,
            )
        elif op.operation is not None:
            # operation changed without a new default: re-encode the existing
            # raw default so the __<op>_ prefix in defaults matches the
            # declared operation instead of going stale
            raw = source.get("defaultValue")
            if (isinstance(raw, str) and raw) or (isinstance(raw, list) and raw):
                defaults_key = _selector_defaults_key(source, op)
                defaults.clear()
                defaults[defaults_key] = _prefixed_defaults_wire(cast("str | list[str]", raw), operation=op.operation)


def _apply_remove_selector_member(data: dict[str, object], op: RemoveSelectorMemberOp) -> None:
    # parameter usage BEFORE the removal: the alias cleanup below is a diff
    used_before_by_tab = [_tab_used_fields(tab) for tab in _data_tabs(data)]
    removed = False
    for item in _find_item_occurrences(data, op.item_id):
        item_data = item.get("data")
        if not isinstance(item_data, dict):
            continue
        group = item_data.get("group")
        if not isinstance(group, list):
            continue
        before = len(group)
        group[:] = [member for member in group if not (isinstance(member, dict) and member.get("id") == op.member_id)]
        removed = removed or len(group) != before
    if not removed:
        raise DataLensValidationError(f"Group {op.item_id!r} has no member {op.member_id!r}")
    # cascade: connections referencing the removed member id + alias cleanup,
    # scoped to tabs the removal actually touched (a shared group occurs on
    # several tabs; unrelated tabs stay verbatim)
    member_tab_ids = {
        tab.get("id") for tab in _data_tabs(data) for item in _iter_tab_items(tab) if item.get("id") == op.item_id
    }
    for tab, used_before in zip(_data_tabs(data), used_before_by_tab, strict=True):
        touched = tab.get("id") in member_tab_ids
        connections = tab.get("connections")
        if isinstance(connections, list):
            before = len(connections)
            connections[:] = [
                entry
                for entry in connections
                if not (isinstance(entry, dict) and op.member_id in (entry.get("from"), entry.get("to")))
            ]
            touched = touched or len(connections) != before
        if touched:
            _drop_dangling_aliases(tab, used_before=used_before)


def _apply_add_group_selector(
    data: dict[str, object],
    op: AddGroupSelectorOp,
    affected: set[tuple[str, str]],
    contract: DashboardGeneratedContract | None,
) -> None:
    """Assemble a group on update, absorbing existing selectors verbatim."""
    tab = _find_tab(data, op.tab_id)
    _validate_member_affects_targets((op.item,), data)
    items = tab.get("items")
    layout = tab.get("layout")
    if not isinstance(items, list) or not isinstance(layout, list):
        raise DataLensValidationError(f"Tab {op.tab_id!r} items/layout are not lists; cannot assemble a group")
    absorbed_members: list[object] = []
    for absorbed_id in op.absorbed_item_ids:
        found: dict[str, object] | None = None
        for item in _iter_tab_items(tab):
            if item.get("id") == absorbed_id:
                found = item
                break
        if found is None:
            raise DataLensValidationError(f"Unknown item {absorbed_id!r} while assembling a group")
        item_data = found.get("data")
        item_data = item_data if isinstance(item_data, dict) else {}
        if found.get("type") == "group_control":
            group = item_data.get("group")
            absorbed_members.extend(group if isinstance(group, list) else [])
        else:
            # standalone control: synthesize the member dict, keeping the raw
            # source/defaults payloads verbatim (id preserved = connections keep working)
            absorbed_members.append(
                {
                    "id": absorbed_id,
                    "title": item_data.get("title"),
                    "namespace": found.get("namespace", "default"),
                    "sourceType": item_data.get("sourceType"),
                    "placementMode": "auto",
                    "width": "",
                    "source": item_data.get("source"),
                    "defaults": found.get("defaults") or {},
                }
            )
        for entries in _tab_item_lists(tab):
            entries[:] = [item for item in entries if item.get("id") != absorbed_id]
        layout[:] = [entry for entry in layout if entry.get("i") != absorbed_id]
    # resolve placement AFTER absorption so an at=None group flows below the tab's
    # remaining content (a no-op for a concrete spec)
    (resolved_entry,) = _resolve_auto_layout((op.layout,), layout)
    staged = TabSpec(id=op.tab_id, title="", items=(op.item,), layout=(resolved_entry,))
    _validate_grid(staged)
    # The new wrapper and its new members are SDK-owned and serialized now;
    # absorbed raw members are appended verbatim afterward.
    wire = _serialize_item(contract, _wire_item(staged, op.item))
    wire_data = wire.get("data")
    assert isinstance(wire_data, dict)
    wire_group = wire_data.get("group")
    assert isinstance(wire_group, list)
    wire_group.extend(absorbed_members)
    items.append(wire)
    layout.append(_serialize_layout(contract, _wire_layout_entry(resolved_entry)))
    _mark(affected, tab, op.item.id)
    _validate_merged_tab(tab)


_TRAILING_DIGITS = re.compile(r"(\d+)\Z")


def _id_high_water(data: dict[str, object]) -> int:
    """Highest trailing-digit suffix across every id in the document."""
    highest = 0
    for tab in _data_tabs(data):
        candidates: list[object] = [tab.get("id")]
        for item in _iter_tab_items(tab):
            candidates.append(item.get("id"))
            item_data = item.get("data")
            if isinstance(item_data, dict):
                for widget_tab in item_data.get("tabs") or []:
                    if isinstance(widget_tab, dict):
                        candidates.append(widget_tab.get("id"))
                for child in item_data.get("group") or []:
                    if isinstance(child, dict):
                        candidates.append(child.get("id"))
        layout = tab.get("layout")
        if isinstance(layout, list):
            candidates.extend(entry.get("i") for entry in layout if isinstance(entry, dict))
        for candidate in candidates:
            if isinstance(candidate, str):
                match = _TRAILING_DIGITS.search(candidate)
                if match:
                    highest = max(highest, int(match.group(1)))
    return highest


def _bump_counter(data: dict[str, object], spec: DashboardUpdateSpec) -> None:
    """High-water counter bump; untouched without structural additions."""
    structural = any(isinstance(op, (AddTabOp, AddItemsOp, AddGroupSelectorOp)) for op in spec.ops)
    if not structural:
        return
    existing = data.get("counter")
    existing_int = existing if isinstance(existing, int) and not isinstance(existing, bool) else 0
    # at least +1 so the counter ends strictly above the document's high water
    # even when every added id was explicit (whether the UI increments before
    # or after use is unknown until P0.3 — over-counting is the safe side)
    data["counter"] = max(existing_int, _id_high_water(data)) + max(spec.generated_id_count, 1)


def _apply_op(
    data: dict[str, object],
    op: DashboardUpdateOp,
    affected: set[tuple[str, str]],
    contract: DashboardGeneratedContract | None,
) -> None:
    if isinstance(op, GlobalParamsOp):
        _apply_global_params(data, op)
    elif isinstance(op, UpdateTabOp):
        _apply_update_tab(data, op)
    elif isinstance(op, RemoveTabOp):
        _apply_remove_tab(data, op)
    elif isinstance(op, ReorderTabsOp):
        _apply_reorder_tabs(data, op)
    elif isinstance(op, ReplaceChartOp):
        _apply_replace_chart(data, op)
    elif isinstance(op, RemoveItemOp):
        _apply_remove_item(data, op)
    elif isinstance(op, SetChartParamsOp):
        _apply_set_chart_params(data, op)
    elif isinstance(op, RemoveConnectionOp):
        _apply_remove_connection(data, op)
    elif isinstance(op, RemoveAliasOp):
        _apply_remove_alias(data, op)
    elif isinstance(op, AddTabOp):
        _apply_add_tab(data, op, affected, contract)
    elif isinstance(op, AddItemsOp):
        _apply_add_items(data, op, affected, contract)
    elif isinstance(op, AddGroupSelectorOp):
        _apply_add_group_selector(data, op, affected, contract)
    elif isinstance(op, UpdateSelectorOp):
        _apply_update_selector(data, op)
    elif isinstance(op, RemoveSelectorMemberOp):
        _apply_remove_selector_member(data, op)
    elif isinstance(op, AddConnectionOp):
        _apply_add_connection(data, op, contract)
    elif isinstance(op, AddAliasOp):
        _apply_add_alias(data, op, contract)
    elif isinstance(op, ApplyLayoutOp):
        _apply_apply_layout(data, op, affected)
    elif isinstance(op, MoveItemOp):
        _apply_move_item(data, op, affected)
    elif isinstance(op, ResizeItemOp):
        _apply_resize_item(data, op, affected)
    elif isinstance(op, SwapItemsOp):
        _apply_swap_items(data, op, affected)
    elif isinstance(op, ShiftBelowOp):
        _apply_shift_below(data, op, affected)
    elif isinstance(op, PinItemOp):
        _apply_pin_item(data, op, affected)
    elif isinstance(op, UnpinItemOp):
        _apply_unpin_item(data, op, affected)
    elif isinstance(op, CompactLayoutOp):
        _apply_compact_layout(data, op, affected)
    else:
        raise NotImplementedError(f"Update op {type(op).__name__} is not applied yet")


def _apply_settings_patch(data: dict[str, object], spec: DashboardUpdateSpec) -> None:
    set_values: dict[str, object | None] = {
        "silent_loading": spec.settings.silent_loading,
        "dependent_selectors": spec.settings.dependent_selectors,
        "expand_toc": spec.settings.expand_toc,
        "hide_dash_title": spec.settings.hide_dash_title,
        "hide_tabs": spec.settings.hide_tabs,
        "autoupdate_interval": spec.settings.autoupdate_interval,
        "max_concurrent_requests": spec.settings.max_concurrent_requests,
        "load_priority": spec.settings.load_priority,
    }
    touched = spec.settings_cleared or any(value is not None for value in set_values.values())
    if not touched:
        return
    settings = data.setdefault("settings", {})
    if not isinstance(settings, dict):
        raise DataLensValidationError("Dashboard data settings is not an object; cannot patch it")
    for field_name, value in set_values.items():
        wire_key = _SETTINGS_WIRE_KEYS[field_name]
        if field_name in spec.settings_cleared:
            # reset to the canon; keys without a canonical value are removed
            if wire_key in _CANONICAL_SETTINGS:
                settings[wire_key] = _CANONICAL_SETTINGS[wire_key]
            else:
                settings.pop(wire_key, None)
        elif value is not None:
            settings[wire_key] = value


def _apply_description(data: dict[str, object], key: str, value: str | None) -> None:
    # tri-state: None = not called (verbatim), "" = clear (key removal is the
    # live-verified true clearing form, P0.1), other value = set.
    if value is None:
        return
    if value == "":
        data.pop(key, None)
    else:
        data[key] = value


def _apply_update(
    spec: DashboardUpdateSpec,
    *,
    contract: DashboardGeneratedContract | None = None,
) -> dict[str, object]:
    """Apply the op queue to a deep copy of the raw data snapshot."""
    data: dict[str, object] = json.loads(json.dumps(spec.data))
    affected: set[tuple[str, str]] = set()
    overlaps_before = _overlap_pairs(data)
    for op in spec.ops:
        _apply_op(data, op, affected, contract)
    _check_final_overlaps(data, affected, overlaps_before)
    _bump_counter(data, spec)
    _apply_settings_patch(data, spec)
    _apply_description(data, "accessDescription", spec.access_description)
    _apply_description(data, "supportDescription", spec.support_description)
    return data
