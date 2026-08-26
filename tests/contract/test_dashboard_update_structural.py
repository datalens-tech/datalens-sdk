"""Structural add_* on DashboardUpdate (D3.3): staged snapshot via the shared
create-side helpers, id seeding from the raw document, counter high-water."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk import DashboardChartTab, DashboardTab, Position
from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.specs.dashboard import AddItemsOp, GroupControlItem, WidgetItem
from datalens_sdk.errors import DataLensValidationError

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"


def _load_entry(stem: str) -> dict[str, object]:
    entry: object = json.loads((_FIXTURES_DIR / f"{stem}.json").read_text())
    assert isinstance(entry, dict)
    return cast(dict[str, object], entry)


def _dashboard_from(entry: dict[str, object]) -> Dashboard:
    return Dashboard(
        id=cast(str, entry["entryId"]),
        installation="yacloud",
        data=cast(dict[str, object], entry["data"]),
        raw=entry,
    )


def _tabs(data: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", data["tabs"])


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value)


def _as_dicts(value: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", value)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _synthetic(tabs: list[dict[str, object]], *, counter: int = 1) -> Dashboard:
    data: dict[str, object] = {"counter": counter, "salt": "s", "settings": {}, "tabs": tabs}
    return Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "dash-1", "data": data})


def _seeded_dashboard() -> Dashboard:
    return _synthetic(
        [
            {
                "id": "tab_1",
                "title": "One",
                "items": [{"id": "el_1", "type": "text", "namespace": "default", "data": {"text": "t"}}],
                "layout": [{"i": "el_1", "x": 0, "y": 0, "w": 8, "h": 4}],
                "connections": [],
                "aliases": {"default": []},
            }
        ],
        counter=2,
    )


def test_add_tab_generates_non_colliding_ids_and_registers_tab() -> None:
    update = _seeded_dashboard().update
    tab = DashboardTab("New").add_text("hello", at=(0, 0, 8, 4))
    update.add_tab(tab)
    update.hide_tab("New")  # the added tab is addressable immediately
    applied = _apply_update(update.to_spec())
    added = _tabs(applied)[1]
    assert added["id"] == "tab_2"  # tab_1 seeded from raw, skipped
    assert added["hidden"] is True
    items = _as_dicts(added["items"])
    assert items[0]["id"] == "el_2"  # el_1 seeded from raw, skipped


def test_add_tab_entity_is_reusable_and_not_mutated() -> None:
    update = _seeded_dashboard().update
    tab = DashboardTab("Twice").add_text("x", at=(0, 0, 8, 4))
    update.add_tab(tab)
    update.add_tab(tab)
    applied = _apply_update(update.to_spec())
    added = _tabs(applied)[1:]
    assert [t["id"] for t in added] == ["tab_2", "tab_3"]
    first_items = [i["id"] for i in _as_dicts(added[0]["items"])]
    second_items = [i["id"] for i in _as_dicts(added[1]["items"])]
    assert first_items != second_items
    assert tab.tab_id is None  # entity untouched


def test_add_chart_into_existing_tab_grows_exactly_one_item() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    source = json.loads(json.dumps(entry["data"]))
    update = _dashboard_from(entry).update
    update.add_chart("chart-xyz", title="New chart", tab="Title 12", at=(0, 40, 12, 6))
    applied = _apply_update(update.to_spec())
    source_tab = _tabs(_as_dict(source))[1]
    applied_tab = _tabs(applied)[1]
    assert len(_as_dicts(applied_tab["items"])) == len(_as_dicts(source_tab["items"])) + 1
    assert len(_as_dicts(applied_tab["layout"])) == len(_as_dicts(source_tab["layout"])) + 1
    new_item = _as_dicts(applied_tab["items"])[-1]
    assert new_item["type"] == "widget"
    chart_tabs = _as_dicts(_as_dict(new_item["data"])["tabs"])
    assert chart_tabs[0]["chartId"] == "chart-xyz"
    # tab 1 and everything else verbatim
    assert _canonical(_tabs(applied)[0]) == _canonical(_tabs(_as_dict(source))[0])


def test_add_items_into_tab_with_global_items_passes_validation() -> None:
    entry = _load_entry("global_items_shared_selectors")
    update = _dashboard_from(entry).update
    first_tab = cast(str, _tabs(_as_dict(entry["data"]))[0]["id"])
    update.add_text("note", tab=first_tab, at=(0, 100, 8, 4))
    applied = _apply_update(update.to_spec())  # merged validation must not false-positive
    tab = _tabs(applied)[0]
    layout_ids = {e["i"] for e in _as_dicts(tab["layout"])}
    item_ids = {i["id"] for i in _as_dicts(tab["items"])} | {i["id"] for i in _as_dicts(tab["globalItems"])}
    assert layout_ids == item_ids


def test_explicit_item_id_collision_with_existing_raw_id_fails_at_call() -> None:
    update = _seeded_dashboard().update
    with pytest.raises(DataLensValidationError, match="Duplicate item id 'el_1'"):
        update.add_text("x", tab="tab_1", at=(0, 10, 8, 4), item_id="el_1")
    with pytest.raises(DataLensValidationError, match="Duplicate tab id"):
        update.add_tab(DashboardTab("T", tab_id="tab_1"))
    assert update.ops == ()


def test_add_chart_group_and_seeded_widget_tab_ids() -> None:
    tabs: list[dict[str, object]] = [
        {
            "id": "tab_1",
            "title": "One",
            "items": [
                {
                    "id": "el_1",
                    "type": "widget",
                    "namespace": "default",
                    "data": {"tabs": [{"id": "wt_1", "chartId": "c1", "title": "T"}]},
                }
            ],
            "layout": [{"i": "el_1", "x": 0, "y": 0, "w": 8, "h": 4}],
        }
    ]
    update = _synthetic(tabs).update
    update.add_chart_group(
        [DashboardChartTab(chart="c2", title="A"), DashboardChartTab(chart="c3", title="B", default=True)],
        tab="tab_1",
        at=(8, 0, 12, 6),
    )
    applied = _apply_update(update.to_spec())
    new_item = _as_dicts(_tabs(applied)[0]["items"])[-1]
    chart_tabs = _as_dicts(_as_dict(new_item["data"])["tabs"])
    assert [t["id"] for t in chart_tabs] == ["wt_2", "wt_3"]  # wt_1 seeded, skipped
    assert [t["isDefault"] for t in chart_tabs] == [False, True]


def test_grid_overflow_of_staged_items_fails_fast() -> None:
    update = _seeded_dashboard().update
    # Position validates at the add_* call site (fail-fast), before apply.
    with pytest.raises(DataLensValidationError, match="must be <= 36"):
        update.add_text("wide", tab="tab_1", at=(30, 0, 12, 4))  # 30 + 12 > 36


def test_counter_high_water_formula() -> None:
    # suffixes above the counter: high-water must win over existing counter
    update = _seeded_dashboard().update  # counter=2, ids el_1/tab_1
    update.add_text("a", tab="tab_1", at=(0, 10, 8, 4))  # generates el_2 (1 id)
    applied = _apply_update(update.to_spec())
    assert applied["counter"] == 2 + 1  # max(2, high-water 2 (el_2)) + 1... see below

    # existing counter above all suffixes: counter must win
    dashboard = _synthetic(
        [
            {
                "id": "tab_1",
                "title": "One",
                "items": [{"id": "el_9", "type": "text", "namespace": "default", "data": {"text": "t"}}],
                "layout": [{"i": "el_9", "x": 0, "y": 0, "w": 8, "h": 4}],
            }
        ],
        counter=50,
    )
    update = dashboard.update
    update.add_text("b", tab="tab_1", at=(0, 10, 8, 4))
    applied = _apply_update(update.to_spec())
    assert applied["counter"] == 50 + 1

    # suffixes above the counter
    dashboard = _synthetic(
        [
            {
                "id": "tab_7",
                "title": "One",
                "items": [{"id": "el_9", "type": "text", "namespace": "default", "data": {"text": "t"}}],
                "layout": [{"i": "el_9", "x": 0, "y": 0, "w": 8, "h": 4}],
            }
        ],
        counter=2,
    )
    update = dashboard.update
    update.add_text("c", tab="tab_7", at=(0, 10, 8, 4))
    applied = _apply_update(update.to_spec())
    assert applied["counter"] == 9 + 1  # high-water el_9 beats counter=2; one generated id


def test_counter_bumps_for_explicit_only_structural_ops() -> None:
    # no auto ids generated, but an explicit el_999 raises the high water:
    # the counter must still end strictly above it (UI collision guard)
    update = _seeded_dashboard().update  # counter=2
    update.add_text("x", tab="tab_1", at=(0, 10, 8, 4), item_id="el_999")
    spec = update.to_spec()
    assert spec.generated_id_count == 0
    applied = _apply_update(spec)
    assert applied["counter"] == 999 + 1

    # explicit-id empty tab: same rule
    update = _seeded_dashboard().update
    update.add_tab(DashboardTab("T", tab_id="tab_500"))
    applied = _apply_update(update.to_spec())
    assert applied["counter"] == 500 + 1


def test_counter_verbatim_without_structural_ops() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    update = _dashboard_from(entry).update.hide_tab("tab_1")
    applied = _apply_update(update.to_spec())
    assert applied["counter"] == _as_dict(entry["data"])["counter"]


def test_update_add_chart_passes_enable_action_params() -> None:
    builder = _seeded_dashboard().update
    builder.add_chart("ch-new", tab="tab_1", title="New", at=(0, 0, 12, 6), enable_action_params=True)
    op = builder.ops[-1]
    assert isinstance(op, AddItemsOp)
    item = op.items[0]
    assert isinstance(item, WidgetItem)
    assert item.tabs[0].enable_action_params is True


# -- selector mirrors: add_selector / add_group_selector (epic D4, stage 15) --------


def _fixture_dashboard(stem: str) -> Dashboard:
    return _dashboard_from(_load_entry(stem))


def test_update_add_selector_lands_as_singleton_group_control() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(tab="tab_1", item_id="sel_new", param_name="region", element="input", at=(0, 4, 12, 2))
    op = builder.ops[-1]
    assert isinstance(op, AddItemsOp)
    item = op.items[0]
    assert isinstance(item, GroupControlItem)
    assert item.members[0].id == "sel_new"

    data = _apply_update(builder.to_spec())
    added = [it for it in _as_dicts(_tabs(data)[0]["items"]) if it.get("type") == "group_control"]
    assert len(added) == 1


def test_update_group_registration_requires_assembly_before_spec() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(group="filters", param_name="region", element="input")
    with pytest.raises(DataLensValidationError, match="never assembled"):
        builder.to_spec()
    builder.add_group_selector(group="filters", tab="tab_1", at=(0, 4, 24, 2))
    data = _apply_update(builder.to_spec())
    assert any(it.get("type") == "group_control" for it in _as_dicts(_tabs(data)[0]["items"]))


def test_update_absorb_standalone_controls_into_a_group() -> None:
    # selectors_dataset.json: tab with standalone dataset controls
    entry = _load_entry("selectors_dataset")
    dashboard = _dashboard_from(entry)
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    control_ids = [cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "control"][:2]
    assert len(control_ids) == 2

    builder = dashboard.update
    builder.add_group_selector(tab=tab_id, item_id="grp_new", at=None, include=control_ids)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == tab_id)
    remaining_ids = {it.get("id") for it in _as_dicts(new_tab["items"])}
    assert set(control_ids).isdisjoint(remaining_ids)  # wrappers removed as items
    group_item = next(it for it in _as_dicts(new_tab["items"]) if it.get("id") == "grp_new")
    members = _as_dicts(_as_dict(group_item["data"])["group"])
    member_ids = [m.get("id") for m in members]
    assert member_ids == control_ids  # ids preserved verbatim, in include order
    # verbatim source payloads survive
    original = {it["id"]: it for it in _as_dicts(tab_raw["items"]) if it.get("id") in control_ids}
    for member in members:
        source = _as_dict(member["source"])
        original_source = _as_dict(_as_dict(original[cast(str, member["id"])]["data"])["source"])
        assert source == original_source
    # layout entries of the absorbed wrappers are gone; the new group has one
    layout_ids = [entry.get("i") for entry in _as_dicts(new_tab["layout"])]
    assert set(control_ids).isdisjoint(set(layout_ids))
    assert "grp_new" in layout_ids


def test_update_absorb_prechecks() -> None:
    builder = _fixture_dashboard("selectors_dataset").update
    with pytest.raises(DataLensValidationError, match="Unknown item id"):
        builder.add_group_selector(tab=_first_tab_id("selectors_dataset"), at=(0, 0, 12, 2), include=("nope",))
    with pytest.raises(DataLensValidationError, match="needs group= members and/or include"):
        builder.add_group_selector(tab=_first_tab_id("selectors_dataset"), at=(0, 0, 12, 2))


def _first_tab_id(stem: str) -> str:
    return cast(str, _tabs(_as_dict(_load_entry(stem)["data"]))[0]["id"])


def test_update_absorbed_member_stays_addressable_for_connections() -> None:
    entry = _load_entry("selectors_dataset")
    dashboard = _dashboard_from(entry)
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    control_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "control")
    widget_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "widget")

    builder = dashboard.update
    builder.add_group_selector(tab=tab_id, item_id="grp_new", at=None, include=(control_id,))
    # the absorbed selector keeps its id: wiring by member id still works,
    # and the NEW wrapper resolves to its members
    builder.add_connection(from_item=widget_id, to_item="grp_new")
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == tab_id)
    connections = _as_dicts(new_tab["connections"])
    assert any(edge.get("to") == control_id for edge in connections)


def test_update_shared_selector_propagates_to_global_items_of_all_tabs() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    dashboard = _dashboard_from(entry)
    tab_ids = [cast(str, t["id"]) for t in _tabs(_as_dict(entry["data"]))]
    assert len(tab_ids) >= 2

    builder = dashboard.update
    builder.add_selector(
        tab=tab_ids[0],
        item_id="sel_shared",
        param_name="region",
        element="input",
        at=None,  # auto-place: flows below each target tab's own content (per-target)
        show_on_tabs="all",
    )
    data = _apply_update(builder.to_spec())
    for tab in _tabs(data):
        globals_ = _as_dicts(tab.get("globalItems", []))
        wrappers = [
            it
            for it in globals_
            if any(m.get("id") == "sel_shared" for m in _as_dicts(_as_dict(it.get("data", {})).get("group", [])))
        ]
        assert len(wrappers) == 1, f"tab {tab.get('id')} must carry the shared selector"


def test_update_group_member_affects_maps_to_impact_type() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    dashboard = _dashboard_from(entry)
    home = cast(str, _tabs(_as_dict(entry["data"]))[0]["id"])

    builder = dashboard.update
    builder.add_selector(group="flt", item_id="m_scoped", param_name="region", element="input", affects=(home,))
    builder.add_selector(group="flt", item_id="m_inherit", param_name="cat", element="input")
    builder.add_group_selector(group="flt", tab=home, at=(0, 50, 36, 2), show_on_tabs="all")
    data = _apply_update(builder.to_spec())

    new_tab = next(t for t in _tabs(data) if t.get("id") == home)
    wrapper = next(
        it
        for it in _as_dicts(new_tab["globalItems"])
        if any(m.get("id") == "m_scoped" for m in _as_dicts(_as_dict(it.get("data", {})).get("group", [])))
    )
    members = {cast(str, m["id"]): m for m in _as_dicts(_as_dict(wrapper["data"])["group"])}
    assert members["m_scoped"]["impactType"] == "selectedTabs"
    assert members["m_scoped"]["impactTabsIds"] == [home]
    assert "impactType" not in members["m_inherit"]  # affects defaults to as_group


def test_update_add_tab_auto_flows_below_inherited_all_tabs() -> None:
    # a new tab inherits the document's allTabs selectors; its own at=None content
    # must resolve BELOW that band, not collide with it at (0,0)
    builder = _seeded_dashboard().update
    builder.add_selector(
        tab="tab_1", item_id="flt", param_name="p", element="input", at=(0, 4, 12, 2), show_on_tabs="all"
    )
    builder.add_tab(DashboardTab("New").add_text("body", item_id="body", at=None))
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    body = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "body")
    assert body["y"] == 6  # flt (inherited) ends at y=6, so body flows below it


def _shared_singleton_wire(
    item_id: str, *, impact_type: str, impact_tabs: list[str] | None = None
) -> dict[str, object]:
    """A raw V2 singleton whose member carries an explicit influence scope."""
    member: dict[str, object] = {
        "id": f"{item_id}_m",
        "title": "P",
        "sourceType": "manual",
        "source": {"fieldName": "p", "elementType": "input", "defaultValue": ""},
        "defaults": {"p": ""},
        "impactType": impact_type,
    }
    if impact_tabs is not None:
        member["impactTabsIds"] = impact_tabs
    return {
        "id": item_id,
        "type": "group_control",
        "namespace": "default",
        "data": {"group": [member]},
    }


def _shared_singleton_group_wire(
    item_id: str, *, impact_type: str, impact_tabs: list[str] | None = None
) -> dict[str, object]:
    """A raw V2 singleton whose group carries its display scope."""
    wire = _shared_singleton_wire(item_id, impact_type="allTabs")
    data = cast("dict[str, object]", wire["data"])
    member = cast("list[dict[str, object]]", data["group"])[0]
    member.pop("impactType", None)
    data["impactType"] = impact_type
    if impact_tabs is not None:
        data["impactTabsIds"] = impact_tabs
    return wire


def _raw_tab(
    tab_id: str, *, global_items: list[dict[str, object]], layout: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "id": tab_id,
        "title": tab_id,
        "items": [],
        "globalItems": global_items,
        "layout": layout,
        "connections": [],
        "aliases": {"default": []},
    }


def test_update_add_tab_inherits_singleton_despite_member_selected_tabs() -> None:
    # C12(a): a single-member shared group displayed on EVERY tab may carry the
    # MEMBER's influence scope in data.group[0]; a selectedTabs value there is
    # not a display pin and must not stop the new tab from inheriting it
    flt = _shared_singleton_wire("flt", impact_type="selectedTabs", impact_tabs=["tab_1"])
    tabs = [
        _raw_tab(
            tab_id, global_items=[json.loads(json.dumps(flt))], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]
        )
        for tab_id in ("tab_1", "tab_2")
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.add_tab(DashboardTab("New").add_text("body", item_id="body", at=None))
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    assert [i["id"] for i in _as_dicts(new_tab["globalItems"])] == ["flt"]
    body = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "body")
    assert body["y"] == 2  # flows below the inherited selector


def test_update_add_tab_ignores_singleton_member_all_tabs_influence() -> None:
    # C12(b): group[0].impactType == "allTabs" here is the MEMBER's influence
    # scope; the group itself is displayed on tab_1 only and must stay there
    flt = _shared_singleton_wire("flt", impact_type="allTabs")
    tabs = [
        _raw_tab("tab_1", global_items=[flt], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]),
        _raw_tab("tab_2", global_items=[], layout=[]),
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.add_tab(DashboardTab("New").add_text("body", item_id="body", at=None))
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    assert "flt" not in {i["id"] for i in _as_dicts(new_tab.get("globalItems") or [])}
    body = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "body")
    assert body["y"] == 0  # nothing inherited, content starts at the top


def test_update_add_tab_display_pinned_singleton_stays_pinned() -> None:
    # V2 keeps show_on_tabs=(...) on the group itself, so a new tab must not
    # inherit an explicitly pinned selector.
    flt = _shared_singleton_group_wire("flt", impact_type="selectedTabs", impact_tabs=["tab_1", "tab_2"])
    tabs = [
        _raw_tab(
            tab_id, global_items=[json.loads(json.dumps(flt))], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]
        )
        for tab_id in ("tab_1", "tab_2")
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.add_tab(DashboardTab("New").add_text("body", item_id="body", at=None))
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    assert "flt" not in {i["id"] for i in _as_dicts(new_tab.get("globalItems") or [])}


def test_update_add_tab_display_pinned_singleton_survives_remove_tab() -> None:
    # remove_tab does not rewrite impactTabsIds: a singleton pinned to
    # ("tab_1","tab_2","tab_3") still lists tab_3 after it was removed. The
    # stale SUPERSET is the same display pin — a tab added in the same builder
    # must not inherit the selector
    flt = _shared_singleton_group_wire("flt", impact_type="selectedTabs", impact_tabs=["tab_1", "tab_2", "tab_3"])
    tabs = [
        _raw_tab(
            tab_id,
            global_items=[json.loads(json.dumps(flt))],
            layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}],
        )
        for tab_id in ("tab_1", "tab_2", "tab_3")
    ]
    builder = _synthetic(tabs, counter=4).update
    builder.remove_tab("tab_3")
    builder.add_tab(DashboardTab("New").add_text("body", item_id="body", at=None))
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    assert "flt" not in {i["id"] for i in _as_dicts(new_tab.get("globalItems") or [])}


def test_update_add_tab_shared_auto_selector_resolves_below_inherited_band() -> None:
    # C5: a shared at=None selector defined ON the new tab must land below the
    # allTabs band the tab inherits, not at (0,0) on top of it
    flt = _shared_singleton_wire("flt", impact_type="allTabs")
    tabs = [_raw_tab("tab_1", global_items=[flt], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}])]
    builder = _synthetic(tabs, counter=2).update
    tab = DashboardTab("New")
    tab.add_selector(param_name="q", element="input", item_id="q_sel", at=None, show_on_tabs="all")
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    # item_id names the member; the group wrapper carries an auto id
    wrapper = next(i for i in _as_dicts(new_tab["globalItems"]) if i["id"] != "flt")
    q_entry = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == wrapper["id"])
    assert q_entry["y"] == 2  # inherited flt occupies y=0..2


def test_update_add_tab_mixed_local_and_shared_autos_keep_row_flow() -> None:
    # C5: local and shared at=None items flow in declaration order on the new
    # tab — the shared group keeps the slot the joint resolution assigned it
    # instead of dropping below all local content
    builder = _synthetic([_raw_tab("tab_1", global_items=[], layout=[])], counter=2).update
    tab = DashboardTab("New")
    tab.add_text("a", item_id="a", at=None)  # (0, 0, 12, 6)
    tab.add_selector(param_name="p", element="input", item_id="s", at=None, show_on_tabs="all")  # (12, 0, 9, 2)
    tab.add_text("b", item_id="b", at=None)  # (21, 0, 12, 6)
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    layout = {e["i"]: e for e in _as_dicts(new_tab["layout"])}
    # item_id names the member; the group wrapper carries an auto id
    (wrapper_id,) = [i["id"] for i in _as_dicts(new_tab["globalItems"])]
    # the shared selector keeps its inline slot (no drop below the tab content)
    assert (layout[wrapper_id]["x"], layout[wrapper_id]["y"]) == (12, 0)
    # ...and the following local item flows right after it (no gap at x=12)
    assert (layout["b"]["x"], layout["b"]["y"]) == (21, 0)


def test_tab_apply_layout_pins_auto_item_for_update_add_tab() -> None:
    # apply_layout gives an initially-auto item an explicit position: the
    # update path must honor it instead of re-deferring the item as auto
    tab = DashboardTab("New").add_text("x", item_id="x", at=None)
    tab.apply_layout({"x": (6, 20, 12, 4)})
    builder = _seeded_dashboard().update
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    entry = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "x")
    assert (entry["x"], entry["y"], entry["w"], entry["h"]) == (6, 20, 12, 4)


def test_update_add_item_overlapping_existing_fails_loud() -> None:
    # el_1 sits at (0,0,8,4); an explicit add on top of it fails loud, matching
    # the create-side overlap rejection (previously shipped silently)
    builder = _seeded_dashboard().update
    builder.add_text("on top", tab="tab_1", at=(0, 0, 12, 6))
    with pytest.raises(DataLensValidationError, match="overlap"):
        _apply_update(builder.to_spec())


def test_update_add_tab_with_overlapping_items_fails_loud() -> None:
    tab = DashboardTab("New")
    tab.add_text("a", at=(0, 0, 12, 6))
    tab.add_text("b", at=(0, 0, 12, 6))  # identical rectangle
    builder = _seeded_dashboard().update
    builder.add_tab(tab)
    with pytest.raises(DataLensValidationError, match="overlap"):
        _apply_update(builder.to_spec())


def test_update_add_chart_auto_flows_below_existing_content() -> None:
    # a full-width item occupies (0,0,36,10); an at=None chart resolves BELOW it
    # (y == 10) rather than emitting a concrete (0,0) that overlaps
    dash = _synthetic(
        [
            {
                "id": "tab_1",
                "title": "One",
                "items": [
                    {
                        "id": "el_1",
                        "type": "widget",
                        "namespace": "default",
                        "data": {"tabs": [{"id": "wt_1", "chartId": "c", "title": "E", "isDefault": True}]},
                    }
                ],
                "layout": [{"i": "el_1", "x": 0, "y": 0, "w": 36, "h": 10}],
                "connections": [],
                "aliases": {"default": []},
            }
        ]
    )
    builder = dash.update
    builder.add_chart("chart_new", tab="tab_1", title="New", at=None)
    data = _apply_update(builder.to_spec())
    new_entry = next(e for e in _as_dicts(_tabs(data)[0]["layout"]) if e["i"] != "el_1")
    assert new_entry["y"] == 10


def test_update_group_include_validates_member_affects_unknown_tab() -> None:
    # the include= assembly path must reject a builder member scoped to a
    # nonexistent tab, just like the plain AddItems path
    entry = _load_entry("selectors_dataset")
    dashboard = _dashboard_from(entry)
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    control_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "control")

    builder = dashboard.update
    builder.add_selector(group="g", item_id="m_bad", param_name="p", element="input", affects=("ghost",))
    builder.add_group_selector(group="g", tab=tab_id, item_id="grp", at=None, include=(control_id,))
    with pytest.raises(DataLensValidationError, match="unknown tab ids"):
        _apply_update(builder.to_spec())


def test_update_group_member_affects_unknown_tab_fails_loud() -> None:
    # create/update parity: an affects tuple referencing a nonexistent tab must
    # raise on update too (create raises via _validate_show_on_tabs_targets)
    entry = _load_entry("selectors_manual_two_tabs")
    dashboard = _dashboard_from(entry)
    home = cast(str, _tabs(_as_dict(entry["data"]))[0]["id"])

    builder = dashboard.update
    builder.add_selector(group="flt", item_id="m_bad", param_name="region", element="input", affects=("ghost",))
    builder.add_selector(group="flt", item_id="m_ok", param_name="cat", element="input")
    builder.add_group_selector(group="flt", tab=home, at=(0, 50, 36, 2), show_on_tabs="all")
    with pytest.raises(DataLensValidationError, match="unknown tab ids"):
        _apply_update(builder.to_spec())


# -- update composition: builder-added selectors stay addressable (review fixes) ----


def test_update_added_selector_supports_update_and_connection_in_same_builder() -> None:
    entry = _load_entry("selectors_dataset")
    dashboard = _dashboard_from(entry)
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    widget_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "widget")

    builder = dashboard.update
    builder.add_selector(tab=tab_id, item_id="sel_new", param_name="note", element="input", at=None)
    builder.update_selector(item_id="sel_new", title="Renamed")
    builder.add_connection(from_item=widget_id, to_item="sel_new")
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == tab_id)
    member = next(
        m
        for it in _as_dicts(new_tab["items"])
        if it.get("type") == "group_control"
        for m in _as_dicts(_as_dict(it["data"]).get("group", []))
        if m.get("id") == "sel_new"
    )
    assert member["title"] == "Renamed"
    assert any(edge.get("to") == "sel_new" for edge in _as_dicts(new_tab["connections"]))


def test_update_added_selector_can_be_removed_in_same_builder() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(tab="tab_1", item_id="sel_tmp", param_name="p", element="input", at=(0, 8, 12, 2))
    builder.remove_selector(item_id="sel_tmp")
    data = _apply_update(builder.to_spec())
    assert not any(it.get("type") == "group_control" for it in _as_dicts(_tabs(data)[0]["items"]))


def test_update_group_with_explicit_member_ids_assembles_and_wires() -> None:
    entry = _load_entry("selectors_dataset")
    dashboard = _dashboard_from(entry)
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    widget_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "widget")

    builder = dashboard.update
    builder.add_selector(group="g", item_id="sel_a", param_name="p1", element="input")
    builder.add_selector(group="g", item_id="sel_b", param_name="p2", element="input")
    builder.add_group_selector(group="g", tab=tab_id, item_id="grp_g", at=None)
    builder.add_connection(from_item=widget_id, to_item="sel_a")  # member id addressing
    builder.add_connection(from_item=widget_id, to_item="grp_g")  # wrapper expands to members
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == tab_id)
    group_item = next(it for it in _as_dicts(new_tab["items"]) if it.get("id") == "grp_g")
    member_ids = [m.get("id") for m in _as_dicts(_as_dict(group_item["data"])["group"])]
    assert member_ids == ["sel_a", "sel_b"]
    targets = {edge.get("to") for edge in _as_dicts(new_tab["connections"])}
    assert {"sel_a", "sel_b"} <= targets


def test_update_duplicate_pending_member_id_fails_at_call() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(group="g", item_id="sel_a", param_name="p1", element="input")
    with pytest.raises(DataLensValidationError, match="Duplicate item id"):
        builder.add_selector(group="h", item_id="sel_a", param_name="p2", element="input")


def test_update_add_selector_rejects_tab_with_group() -> None:
    builder = _seeded_dashboard().update
    with pytest.raises(DataLensValidationError, match="tab= belongs to add_group_selector"):
        builder.add_selector(tab="tab_1", group="g", param_name="p", element="input")


def test_update_include_only_group_validates_placement_and_border_radius() -> None:
    entry = _load_entry("selectors_dataset")
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    control_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "control")

    with pytest.raises(DataLensValidationError, match="at must be"):
        _dashboard_from(entry).update.add_group_selector(
            tab=tab_id,
            at=cast("tuple[int, int, int, int]", (0, 0, 12)),
            include=(control_id,),
        )
    with pytest.raises(DataLensValidationError, match="border_radius"):
        _dashboard_from(entry).update.add_group_selector(
            tab=tab_id, at=(0, 0, 12, 2), include=(control_id,), border_radius=3
        )


def test_update_shared_added_selector_is_removable_from_all_tabs() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    builder = _dashboard_from(entry).update
    tab_ids = [cast(str, t["id"]) for t in _tabs(_as_dict(entry["data"]))]
    builder.add_selector(
        tab=tab_ids[0],
        item_id="sel_shared",
        param_name="region",
        element="input",
        at=(0, 0, 12, 2),
        show_on_tabs="all",
    )
    builder.remove_selector(item_id="sel_shared")  # the member id is indexed on every target tab
    data = _apply_update(builder.to_spec())
    for tab in _tabs(data):
        for item in _as_dicts(tab.get("globalItems", [])):
            members = _as_dicts(_as_dict(item.get("data", {})).get("group", []))
            assert not any(m.get("id") == "sel_shared" for m in members)


def _tabs_carrying_member(data: dict[str, object], member_id: str) -> list[object]:
    return [
        tab.get("id")
        for tab in _tabs(data)
        if any(
            m.get("id") == member_id
            for it in _as_dicts(tab.get("globalItems", []))
            for m in _as_dicts(_as_dict(it.get("data", {})).get("group", []))
        )
    ]


def test_all_tabs_shared_selector_reaches_a_tab_added_later() -> None:
    # show_on_tabs="all" means every tab of the FINAL document: the result
    # must not depend on whether add_tab comes before or after the selector
    later = DashboardTab("Later").add_text("x", at=(0, 4, 8, 4))

    selector_first = _seeded_dashboard().update
    selector_first.add_selector(
        tab="tab_1", item_id="m_all", param_name="p", element="input", at=(0, 8, 12, 2), show_on_tabs="all"
    )
    selector_first.add_tab(later)
    first = _apply_update(selector_first.to_spec())
    assert _tabs_carrying_member(first, "m_all") == ["tab_1", "tab_2"]
    new_tab = _tabs(first)[1]
    wrapper_id = next(it["id"] for it in _as_dicts(new_tab["globalItems"]))
    assert wrapper_id in [entry.get("i") for entry in _as_dicts(new_tab["layout"])]  # layout copied too

    tab_first = _seeded_dashboard().update
    tab_first.add_tab(later)
    tab_first.add_selector(
        tab="tab_1", item_id="m_all", param_name="p", element="input", at=(0, 8, 12, 2), show_on_tabs="all"
    )
    second = _apply_update(tab_first.to_spec())
    assert _tabs_carrying_member(second, "m_all") == ["tab_1", "tab_2"]


def test_all_tabs_selector_added_then_tab_added_stays_addressable_and_removable() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(
        tab="tab_1", item_id="m_all", param_name="p", element="input", at=(0, 8, 12, 2), show_on_tabs="all"
    )
    builder.add_tab(DashboardTab("Later").add_text("x", at=(0, 4, 8, 4)))
    builder.remove_selector(item_id="m_all")  # the new tab's occurrence is indexed too
    data = _apply_update(builder.to_spec())
    assert _tabs_carrying_member(data, "m_all") == []


def test_only_on_tabs_shared_selector_does_not_leak_into_added_tab() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(
        tab="tab_1", item_id="m_only", param_name="p", element="input", at=(0, 8, 12, 2), show_on_tabs=("tab_1",)
    )
    builder.add_tab(DashboardTab("Later").add_text("x", at=(0, 4, 8, 4)))
    data = _apply_update(builder.to_spec())
    assert _tabs_carrying_member(data, "m_only") == ["tab_1"]


def test_added_tab_picks_up_preexisting_raw_all_tabs_control() -> None:
    # legacy standalone shared control with impactType allTabs in the raw doc
    dashboard = _synthetic(
        [
            {
                "id": "tab_1",
                "title": "One",
                "items": [],
                "globalItems": [
                    {
                        "id": "c_all",
                        "type": "control",
                        "namespace": "default",
                        "defaults": {"p_shared": ""},
                        "data": {
                            "title": "Shared",
                            "sourceType": "manual",
                            "impactType": "allTabs",
                            "source": {"elementType": "input", "fieldName": "p_shared"},
                        },
                    }
                ],
                "layout": [{"i": "c_all", "x": 0, "y": 0, "w": 12, "h": 2}],
                "connections": [],
                "aliases": {"default": []},
            }
        ],
        counter=2,
    )
    update = dashboard.update
    update.add_tab(DashboardTab("Later").add_text("x", at=(0, 4, 8, 4)))
    data = _apply_update(update.to_spec())
    new_tab = _tabs(data)[1]
    copied = [it.get("id") for it in _as_dicts(new_tab.get("globalItems", []))]
    assert copied == ["c_all"]
    assert "c_all" in [entry.get("i") for entry in _as_dicts(new_tab["layout"])]


def test_update_add_tab_propagates_shared_selectors() -> None:
    update = _seeded_dashboard().update
    # a shared at=None selector on a new tab resolves per target tab: it flows
    # below tab_1's existing content instead of colliding at (0,0)
    tab = DashboardTab("New").add_selector(
        item_id="sel_all", param_name="p", element="input", at=None, show_on_tabs="all"
    )
    update.add_tab(tab)
    data = _apply_update(update.to_spec())
    assert len(_tabs(data)) == 2
    for wire_tab in _tabs(data):
        globals_ = _as_dicts(wire_tab.get("globalItems", []))
        assert any(
            m.get("id") == "sel_all"
            for it in globals_
            for m in _as_dicts(_as_dict(it.get("data", {})).get("group", []))
        ), f"tab {wire_tab.get('id')} must carry the shared selector"


def test_update_add_tab_replays_start_row_and_space_markers() -> None:
    # start_row()/space() are recorded on the deferred autos, so the apply-time
    # resolution reproduces the same row structure on the new tab
    builder = _synthetic([_raw_tab("tab_1", global_items=[], layout=[])], counter=2).update
    tab = DashboardTab("New")
    tab.add_text("a", item_id="a")  # (0, 0, 12, 6)
    tab.add_text("b", item_id="b")  # (12, 0, 12, 6)
    tab.start_row()
    tab.space(1)
    tab.add_text("c", item_id="c")  # new row + gap -> (0, 7)
    tab.add_text("d", item_id="d")  # flows beside c
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("title") == "New")
    layout = {e["i"]: e for e in _as_dicts(new_tab["layout"])}
    assert (layout["c"]["x"], layout["c"]["y"]) == (0, 7)
    assert (layout["d"]["x"], layout["d"]["y"]) == (12, 7)
    assert tab.preview_layout()["c"].y == 7  # create-side preview agrees


def test_update_add_chart_size_survives_deferred_resolution() -> None:
    # size= on an update adder reaches the AutoLayoutItemSpec: the item flows
    # below the tab content with the requested w/h
    builder = _seeded_dashboard().update  # el_1 occupies (0, 0, 8, 4)
    builder.add_chart("ch-w", title="Wide", tab="tab_1", size=(18, 10))
    data = _apply_update(builder.to_spec())
    entry = next(e for e in _as_dicts(_tabs(data)[0]["layout"]) if e["i"] != "el_1")
    assert (entry["x"], entry["y"], entry["w"], entry["h"]) == (0, 4, 18, 10)


# -- K1: shadow index mirrors the applier's presence-based add_tab inheritance -----


def test_add_tab_then_layout_op_on_inherited_singleton_member_scope() -> None:
    # a singleton whose group[0] holds the MEMBER's influence (selectedTabs) is
    # inherited by a new tab presence-based; the shadow index must register the
    # occurrence so a tab-scoped layout op is legal in the same builder
    flt = _shared_singleton_wire("flt", impact_type="selectedTabs", impact_tabs=["tab_1"])
    tabs = [
        _raw_tab(
            tid, global_items=[json.loads(json.dumps(flt))], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]
        )
        for tid in ("tab_1", "tab_2")
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.add_tab(DashboardTab("New", tab_id="tab_new"))
    builder.apply_layout({"flt": Position(0, 10, 36, 2)}, tab="tab_new")  # must not fail at call time
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == "tab_new")
    entry = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "flt")
    assert entry["y"] == 10


def test_add_tab_does_not_register_phantom_occurrence_for_member_all_tabs() -> None:
    # a singleton displayed on ONE tab whose group[0] holds member influence
    # "allTabs" is NOT inherited; the shadow index must reject a tab-scoped
    # layout op at call time (previously it passed and failed late, in apply)
    flt = _shared_singleton_wire("flt", impact_type="allTabs")
    tabs = [
        _raw_tab("tab_1", global_items=[flt], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]),
        _raw_tab("tab_2", global_items=[], layout=[]),
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.add_tab(DashboardTab("New", tab_id="tab_new"))
    with pytest.raises(DataLensValidationError, match="not on tab"):
        builder.apply_layout({"flt": Position(0, 10, 36, 2)}, tab="tab_new")


# -- K4: section divider cursor floor survives deferred update resolution ----------


def test_update_add_tab_replays_explicit_divider_cursor_floor() -> None:
    # an explicit-at divider ends the flow row below itself; the deferred
    # resolution must reproduce that (concrete entries never move its cursor)
    tab = DashboardTab("New", tab_id="tab_new")
    tab.add_section_divider("Section", item_id="div", at=(0, 20, 36, 2))
    tab.add_text("body", item_id="body")
    assert tab.preview_layout()["body"].y == 22  # create-side behavior
    builder = _synthetic([_raw_tab("tab_1", global_items=[], layout=[])], counter=2).update
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == "tab_new")
    entry = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "body")
    assert entry["y"] == 22  # update-side parity


def test_update_add_tab_auto_divider_carries_no_stale_floor() -> None:
    # an AUTO divider re-resolves with the flow; its create-side bottom must not
    # leak into the replay as an absolute floor
    tab = DashboardTab("New", tab_id="tab_new")
    tab.add_chart("ch", title="c", item_id="c1")
    tab.add_section_divider("Section", item_id="div")
    tab.add_text("body", item_id="body")
    builder = _synthetic([_raw_tab("tab_1", global_items=[], layout=[])], counter=2).update
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == "tab_new")
    layout = {e["i"]: e for e in _as_dicts(new_tab["layout"])}
    assert (layout["div"]["y"], layout["body"]["y"]) == (12, 14)  # same as create-side preview


# -- K5: update add_group_selector auto_height parity with create ------------------


def test_update_group_auto_placed_defaults_auto_height_true() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(group="g", item_id="m1", param_name="p", element="input")
    builder.add_group_selector(group="g", tab="tab_1", item_id="grp")  # at=None -> auto
    data = _apply_update(builder.to_spec())
    grp = next(i for i in _as_dicts(_tabs(data)[0]["items"]) if i["id"] == "grp")
    assert _as_dict(grp["data"]).get("autoHeight") is True  # create parity


def test_update_group_explicit_at_defaults_auto_height_false() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(group="g", item_id="m1", param_name="p", element="input")
    builder.add_group_selector(group="g", tab="tab_1", item_id="grp", at=(0, 50, 36, 2))
    data = _apply_update(builder.to_spec())
    grp = next(i for i in _as_dicts(_tabs(data)[0]["items"]) if i["id"] == "grp")
    assert _as_dict(grp["data"]).get("autoHeight") is False


def test_update_group_auto_height_explicit_override() -> None:
    builder = _seeded_dashboard().update
    builder.add_selector(group="g", item_id="m1", param_name="p", element="input")
    builder.add_group_selector(group="g", tab="tab_1", item_id="grp", auto_height=False)  # override auto default
    data = _apply_update(builder.to_spec())
    grp = next(i for i in _as_dicts(_tabs(data)[0]["items"]) if i["id"] == "grp")
    assert _as_dict(grp["data"]).get("autoHeight") is False


def test_update_group_include_only_auto_placed_defaults_auto_height_true() -> None:
    entry = _load_entry("selectors_dataset")
    dashboard = _dashboard_from(entry)
    tab_raw = _tabs(_as_dict(entry["data"]))[0]
    tab_id = cast(str, tab_raw["id"])
    control_id = next(cast(str, it["id"]) for it in _as_dicts(tab_raw["items"]) if it.get("type") == "control")
    builder = dashboard.update
    builder.add_group_selector(tab=tab_id, item_id="grp", at=None, include=(control_id,))
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == tab_id)
    grp = next(i for i in _as_dicts(new_tab["items"]) if i["id"] == "grp")
    assert _as_dict(grp["data"]).get("autoHeight") is True


def test_remove_tab_recomputes_all_tabs_inheritance() -> None:
    # a singleton displayed on tab_1 of two with member influence "allTabs" is
    # NOT inherited initially; after remove_tab("tab_2") it IS displayed on
    # every remaining tab, and the shadow index must see it (the applier does)
    flt = _shared_singleton_wire("flt", impact_type="allTabs")
    tabs = [
        _raw_tab("tab_1", global_items=[flt], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]),
        _raw_tab("tab_2", global_items=[], layout=[]),
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.remove_tab("tab_2")
    builder.add_tab(DashboardTab("New", tab_id="tab_new"))
    builder.apply_layout({"flt": Position(0, 10, 36, 2)}, tab="tab_new")  # must not fail at call time
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == "tab_new")
    entry = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "flt")
    assert entry["y"] == 10


def test_remove_tab_keeps_display_pin_pinned() -> None:
    # the reverse: a singleton display-pinned to (tab_1, tab_2) stays pinned
    # after tab_2 is removed (superset pin) — a new tab must NOT inherit it
    flt = _shared_singleton_group_wire("flt", impact_type="selectedTabs", impact_tabs=["tab_1", "tab_2"])
    tabs = [
        _raw_tab(
            tid, global_items=[json.loads(json.dumps(flt))], layout=[{"i": "flt", "x": 0, "y": 0, "w": 36, "h": 2}]
        )
        for tid in ("tab_1", "tab_2")
    ]
    builder = _synthetic(tabs, counter=3).update
    builder.remove_tab("tab_2")
    builder.add_tab(DashboardTab("New", tab_id="tab_new"))
    with pytest.raises(DataLensValidationError, match="not on tab"):
        builder.apply_layout({"flt": Position(0, 10, 36, 2)}, tab="tab_new")


def test_update_add_tab_space_after_explicit_divider_rides_on_floor() -> None:
    # create: divider (0,20,36,2) + space(5) -> text at y=27; the deferred
    # replay must apply the gap on top of the divider floor, not under it
    tab = DashboardTab("New", tab_id="tab_new")
    tab.add_section_divider("Section", item_id="div", at=(0, 20, 36, 2))
    tab.space(5)
    tab.add_text("body", item_id="body")
    assert tab.preview_layout()["body"].y == 27  # create-side behavior
    builder = _synthetic([_raw_tab("tab_1", global_items=[], layout=[])], counter=2).update
    builder.add_tab(tab)
    data = _apply_update(builder.to_spec())
    new_tab = next(t for t in _tabs(data) if t.get("id") == "tab_new")
    entry = next(e for e in _as_dicts(new_tab["layout"]) if e["i"] == "body")
    assert entry["y"] == 27  # update-side parity
