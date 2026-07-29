"""Content operations of DashboardUpdate (D3.2): call-time prechecks over the
shadow index and point-wise appliers that leave everything else verbatim."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.specs.dashboard import AddAliasOp, AddConnectionOp
from datalens_sdk.errors import DatalensValidationError

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


def _dashboard(stem: str) -> Dashboard:
    return _dashboard_from(_load_entry(stem))


def _tabs(data: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", data["tabs"])


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value)


def _as_dicts(value: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", value)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _synthetic(tabs: list[dict[str, object]]) -> Dashboard:
    data: dict[str, object] = {"counter": 1, "salt": "s", "schemeVersion": 8, "settings": {}, "tabs": tabs}
    return Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "dash-1", "data": data})


# -- tab operations ----------------------------------------------------------


def test_update_tab_by_title_renames_and_toggles_hidden() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    update.update_tab("Title 11", title="Renamed", hidden=True)
    applied = _apply_update(update.to_spec())
    tab = _tabs(applied)[0]
    assert tab["title"] == "Renamed"
    assert tab["hidden"] is True
    # everything else verbatim
    source = _load_entry("selectors_manual_two_tabs")
    assert _canonical(_tabs(applied)[1]) == _canonical(_tabs(_as_dict(source["data"]))[1])


def test_update_tab_requires_a_change_and_valid_title() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    with pytest.raises(DatalensValidationError, match="at least one of"):
        update.update_tab("tab_1")
    with pytest.raises(DatalensValidationError, match="non-empty string"):
        update.update_tab("tab_1", title="   ")
    with pytest.raises(DatalensValidationError, match="hidden must be a bool"):
        update.update_tab("tab_1", hidden=cast(bool, "yes"))
    assert update.ops == ()


def test_update_tab_unknown_and_ambiguous_title_fail_loud() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    with pytest.raises(DatalensValidationError, match="Unknown tab"):
        update.update_tab("no-such-tab", hidden=True)
    dashboard = _synthetic(
        [
            {"id": "tab_1", "title": "Same", "items": [], "layout": []},
            {"id": "tab_2", "title": "Same", "items": [], "layout": []},
        ]
    )
    with pytest.raises(DatalensValidationError, match="ambiguous"):
        dashboard.update.update_tab("Same", hidden=True)


def test_rename_shifts_title_resolution_immediately() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    update.update_tab("Title 11", title="Renamed")
    update.update_tab("Renamed", hidden=True)  # new title resolves
    with pytest.raises(DatalensValidationError, match="Unknown tab"):
        update.update_tab("Title 11", hidden=True)  # old title does not
    applied = _apply_update(update.to_spec())
    assert _tabs(applied)[0]["hidden"] is True


def test_hide_show_tab_sugar() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    cast("list[dict[str, object]]", _as_dict(entry["data"])["tabs"])[1]["hidden"] = True
    update = _dashboard_from(entry).update.hide_tab("tab_1").show_tab("tab_2")
    applied = _apply_update(update.to_spec())
    assert _tabs(applied)[0]["hidden"] is True
    assert "hidden" not in _tabs(applied)[1]  # canonical absence


def test_remove_tab_and_last_tab_guard() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    update.remove_tab("tab_2")
    applied = _apply_update(update.to_spec())
    assert [tab["id"] for tab in _tabs(applied)] == ["tab_1"]
    with pytest.raises(DatalensValidationError, match="last remaining tab"):
        update.remove_tab("tab_1")


def test_removed_tab_is_not_addressable_afterwards() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    update.remove_tab("tab_2")
    with pytest.raises(DatalensValidationError, match="Unknown tab"):
        update.update_tab("tab_2", hidden=True)
    with pytest.raises(DatalensValidationError, match="Unknown item"):
        update.remove_item("item_12")  # lived on the removed tab


def test_reorder_tabs_applies_and_requires_exact_permutation() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    with pytest.raises(DatalensValidationError, match="every tab exactly once"):
        update.reorder_tabs(["tab_1"])
    with pytest.raises(DatalensValidationError, match="every tab exactly once"):
        update.reorder_tabs(["tab_1", "tab_1"])
    update.reorder_tabs(["Title 12", "tab_1"])  # titles resolve too
    applied = _apply_update(update.to_spec())
    assert [tab["id"] for tab in _tabs(applied)] == ["tab_2", "tab_1"]


# -- replace_chart -----------------------------------------------------------


def test_replace_chart_swaps_only_chart_id() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    update = _dashboard_from(entry).update
    update.replace_chart(item_id="item_3", chart="new-chart-id")
    applied = _apply_update(update.to_spec())
    source_item = next(i for i in _as_dicts(_tabs(_as_dict(entry["data"]))[0]["items"]) if i["id"] == "item_3")
    applied_item = next(i for i in _as_dicts(_tabs(applied)[0]["items"]) if i["id"] == "item_3")
    source_tab = _as_dicts(_as_dict(source_item["data"])["tabs"])[0]
    applied_tab = _as_dicts(_as_dict(applied_item["data"])["tabs"])[0]
    assert applied_tab["chartId"] == "new-chart-id"
    assert applied_tab["title"] == source_tab["title"]
    assert applied_tab.get("params") == source_tab.get("params")


def test_replace_chart_prechecks() -> None:
    update = _dashboard("selectors_manual_two_tabs").update
    with pytest.raises(DatalensValidationError, match="Unknown item"):
        update.replace_chart(item_id="nope", chart="c")
    with pytest.raises(DatalensValidationError, match="targets widget items"):
        update.replace_chart(item_id="item_1", chart="c")  # a control
    with pytest.raises(DatalensValidationError, match="chart id must not be an empty string"):
        update.replace_chart(item_id="item_3", chart="")
    assert update.ops == ()


def test_replace_chart_multi_tab_widget_requires_widget_tab_id() -> None:
    entry = _load_entry("group_control_manual")
    data = cast(dict[str, object], entry["data"])
    widget = next(
        item
        for tab in _tabs(data)
        for item in cast("list[dict[str, object]]", tab["items"])
        if item.get("type") == "widget" and len(_as_dicts(_as_dict(item["data"]).get("tabs", []))) > 1
    )
    widget_id = cast(str, widget["id"])
    widget_tab_ids = [cast(str, t["id"]) for t in _as_dicts(_as_dict(widget["data"])["tabs"])]
    update = _dashboard_from(entry).update
    with pytest.raises(DatalensValidationError, match="pass widget_tab_id="):
        update.replace_chart(item_id=widget_id, chart="c")
    with pytest.raises(DatalensValidationError, match="no chart tab"):
        update.replace_chart(item_id=widget_id, chart="c", widget_tab_id="wt_nope")
    update.replace_chart(item_id=widget_id, chart="new-id", widget_tab_id=widget_tab_ids[1])
    applied = _apply_update(update.to_spec())
    applied_widget = next(
        item
        for tab in _tabs(applied)
        for item in cast("list[dict[str, object]]", tab["items"])
        if item.get("id") == widget_id
    )
    applied_tabs = _as_dicts(_as_dict(applied_widget["data"])["tabs"])
    assert applied_tabs[1]["chartId"] == "new-id"
    assert applied_tabs[0]["chartId"] == _as_dicts(_as_dict(widget["data"])["tabs"])[0]["chartId"]


def test_replace_chart_patches_every_occurrence_of_shared_widget() -> None:
    widget: dict[str, object] = {
        "id": "wg_shared",
        "type": "widget",
        "namespace": "default",
        "data": {"tabs": [{"id": "wt_1", "chartId": "old", "title": "T"}]},
    }
    tabs: list[dict[str, object]] = [
        {"id": "tab_1", "title": "One", "items": [], "layout": [], "globalItems": [json.loads(json.dumps(widget))]},
        {"id": "tab_2", "title": "Two", "items": [], "layout": [], "globalItems": [json.loads(json.dumps(widget))]},
    ]
    update = _synthetic(tabs).update
    update.replace_chart(item_id="wg_shared", chart="new")
    applied = _apply_update(update.to_spec())
    for tab in _tabs(applied):
        item = _as_dicts(tab["globalItems"])[0]
        assert _as_dicts(_as_dict(item["data"])["tabs"])[0]["chartId"] == "new"


def test_replace_chart_rejects_foreign_installation_chart() -> None:
    class _FakeChart:
        id = "chart-1"
        installation = "enterprise"

    update = _dashboard("selectors_manual_two_tabs").update
    with pytest.raises(DatalensValidationError, match="Cannot place a 'enterprise' chart"):
        update.replace_chart(item_id="item_3", chart=cast("str", _FakeChart()))


# -- remove_item cascade -------------------------------------------------------


def test_remove_item_cascades_layout_and_connections_of_group_children() -> None:
    entry = _load_entry("group_control_manual")
    update = _dashboard_from(entry).update
    update.remove_item("2j")  # group_control with children no/7o/om/... and connections from them
    applied = _apply_update(update.to_spec())
    tab = _tabs(applied)[0]
    item_ids = [item["id"] for item in _as_dicts(tab["items"])]
    layout_ids = [entry_["i"] for entry_ in _as_dicts(tab["layout"])]
    connections = _as_dicts(tab["connections"])
    assert "2j" not in item_ids
    assert "2j" not in layout_ids
    assert connections == []  # all referenced removed group children
    # groups whose selector-side field the removal took away are auto-dropped
    # (D4 self-repair semantics, user decision); ["date", "date_1jp0"] pairs
    # two widget-dataset fields the removal never touched — it stays verbatim
    # (cross-dataset aliases live outside the document's parameter keys, P021)
    assert _as_dict(tab["aliases"])["default"] == [["date", "date_1jp0"]]


def test_remove_item_on_shared_global_item_cleans_every_tab() -> None:
    entry = _load_entry("global_items_shared_selectors")
    update = _dashboard_from(entry).update
    update.remove_item("item_1")
    applied = _apply_update(update.to_spec())
    for tab in _tabs(applied):
        global_ids = [item["id"] for item in _as_dicts(tab.get("globalItems", []))]
        assert "item_1" not in global_ids
        for connection in _as_dicts(tab.get("connections", [])):
            assert connection.get("from") != "item_1"
            assert connection.get("to") != "item_1"
    with pytest.raises(DatalensValidationError, match="Unknown item"):
        update.remove_item("item_1")  # already gone from the index


def test_remove_item_then_remove_connection_referencing_it_fails() -> None:
    entry = _load_entry("group_control_manual")
    update = _dashboard_from(entry).update
    update.remove_item("2j")
    with pytest.raises(DatalensValidationError, match="Unknown item"):
        update.remove_connection(from_item="2j", to_item="rB")


# -- set_chart_params ----------------------------------------------------------


def test_set_chart_params_merges_into_all_widget_chart_tabs() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    update = _dashboard_from(entry).update
    update.set_chart_params(item_id="item_3", params={"region": "north", "cities": ["a", "b"]})
    applied = _apply_update(update.to_spec())
    applied_item = next(i for i in _as_dicts(_tabs(applied)[0]["items"]) if i["id"] == "item_3")
    for widget_tab in _as_dicts(_as_dict(applied_item["data"])["tabs"]):
        params = _as_dict(widget_tab["params"])
        assert params["region"] == ["north"]
        assert params["cities"] == ["a", "b"]


def test_set_chart_params_replace_mode_and_selector_defaults() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    update = _dashboard_from(entry).update
    update.set_chart_params(item_id="item_1", params={"only": "value"}, merge=False)
    applied = _apply_update(update.to_spec())
    applied_item = next(i for i in _as_dicts(_tabs(applied)[0]["items"]) if i["id"] == "item_1")
    assert applied_item["defaults"] == {"only": ["value"]}


def test_set_chart_params_prechecks() -> None:
    entry = _load_entry("selectors_manual_two_tabs")
    tab0 = _tabs(_as_dict(entry["data"]))[0]
    _as_dicts(tab0["items"]).append({"id": "txt_x", "type": "text", "namespace": "default", "data": {"text": "t"}})
    update = _dashboard_from(entry).update
    with pytest.raises(DatalensValidationError, match="targets widget/control items"):
        update.set_chart_params(item_id="txt_x", params={"a": "b"})
    with pytest.raises(DatalensValidationError, match="string or a sequence of strings"):
        update.set_chart_params(item_id="item_3", params={"a": 5})


def test_set_chart_params_rejects_group_control() -> None:
    update = _dashboard("group_control_manual").update
    with pytest.raises(DatalensValidationError, match="does not support group_control"):
        update.set_chart_params(item_id="2j", params={"a": "b"})
    assert update.ops == ()


def test_set_chart_params_patches_every_occurrence_of_shared_global_item() -> None:
    entry = _load_entry("global_items_shared_selectors")
    update = _dashboard_from(entry).update
    update.set_chart_params(item_id="item_1", params={"p": "v"})
    applied = _apply_update(update.to_spec())
    occurrences = [
        item for tab in _tabs(applied) for item in _as_dicts(tab.get("globalItems", [])) if item.get("id") == "item_1"
    ]
    assert len(occurrences) > 1  # the fixture shares item_1 across tabs
    for item in occurrences:
        assert _as_dict(item["defaults"])["p"] == ["v"]
    # one logical item: every occurrence stays identical
    assert len({_canonical(item) for item in occurrences}) == 1


# -- connections / aliases -------------------------------------------------------


def test_remove_connection_by_search_and_ambiguity_rules() -> None:
    entry = _load_entry("group_control_manual")
    update = _dashboard_from(entry).update
    update.remove_connection(from_item="no", to_item="rB")
    applied = _apply_update(update.to_spec())
    connections = _as_dicts(_tabs(applied)[0]["connections"])
    assert {"from": "no", "kind": "ignore", "to": "rB"} not in connections
    assert len(connections) == 2  # the two remaining survive verbatim


def test_remove_connection_missing_fails_loud() -> None:
    entry = _load_entry("group_control_manual")
    update = _dashboard_from(entry).update
    with pytest.raises(DatalensValidationError, match="No connection"):
        update.remove_connection(from_item="no", to_item="Lp")
    with pytest.raises(DatalensValidationError, match="Unknown tab"):
        update.remove_connection(from_item="no", to_item="rB", tab="no-such")
    other_tab = next(t["id"] for t in _tabs(_as_dict(entry["data"])) if not t.get("connections"))
    with pytest.raises(DatalensValidationError, match="has no connection"):
        update.remove_connection(from_item="no", to_item="rB", tab=cast(str, other_tab))


def test_remove_alias_matches_exact_member_set() -> None:
    tabs: list[dict[str, object]] = [
        {
            "id": "tab_1",
            "title": "One",
            "items": [],
            "layout": [],
            "connections": [],
            "aliases": {"default": [["region", "city"], ["a", "b", "c"]]},
        },
        {"id": "tab_2", "title": "Two", "items": [], "layout": [], "connections": [], "aliases": {"default": []}},
    ]
    update = _synthetic(tabs).update
    with pytest.raises(DatalensValidationError, match="at least two"):
        update.remove_alias("region")
    with pytest.raises(DatalensValidationError, match="No alias"):
        update.remove_alias("region", "b")
    update.remove_alias("city", "region")  # order-insensitive
    applied = _apply_update(update.to_spec())
    assert _as_dict(_tabs(applied)[0]["aliases"])["default"] == [["a", "b", "c"]]


def test_repeat_remove_connection_fails_at_call_time() -> None:
    entry = _load_entry("group_control_manual")
    update = _dashboard_from(entry).update
    update.remove_connection(from_item="no", to_item="rB")
    with pytest.raises(DatalensValidationError, match="No connection"):
        update.remove_connection(from_item="no", to_item="rB")
    assert len(update.ops) == 1
    _apply_update(update.to_spec())  # the single recorded op still applies cleanly


def test_repeat_remove_alias_fails_at_call_time() -> None:
    tabs: list[dict[str, object]] = [
        {"id": "tab_1", "title": "One", "items": [], "layout": [], "aliases": {"default": [["x", "y"]]}},
        {"id": "tab_2", "title": "Two", "items": [], "layout": [], "aliases": {"default": []}},
    ]
    update = _synthetic(tabs).update
    update.remove_alias("x", "y")
    with pytest.raises(DatalensValidationError, match="No alias"):
        update.remove_alias("y", "x")
    assert len(update.ops) == 1
    _apply_update(update.to_spec())


def test_remove_connection_ambiguous_across_tabs_requires_tab() -> None:
    tabs: list[dict[str, object]] = [
        {
            "id": "tab_1",
            "title": "One",
            "items": [{"id": "a", "type": "control"}, {"id": "b", "type": "control"}],
            "layout": [],
            "connections": [{"from": "a", "to": "b", "kind": "ignore"}],
        },
        {
            "id": "tab_2",
            "title": "Two",
            "items": [{"id": "a", "type": "control"}, {"id": "b", "type": "control"}],
            "layout": [],
            "connections": [{"from": "a", "to": "b", "kind": "ignore"}],
        },
    ]
    update = _synthetic(tabs).update
    with pytest.raises(DatalensValidationError, match="several tabs"):
        update.remove_connection(from_item="a", to_item="b")
    update.remove_connection(from_item="a", to_item="b", tab="tab_2")
    applied = _apply_update(update.to_spec())
    assert _as_dicts(_tabs(applied)[0]["connections"])  # tab_1 untouched
    assert _as_dicts(_tabs(applied)[1]["connections"]) == []


def test_remove_alias_ambiguous_across_tabs_requires_tab() -> None:
    tabs: list[dict[str, object]] = [
        {"id": "tab_1", "title": "One", "items": [], "layout": [], "aliases": {"default": [["x", "y"]]}},
        {"id": "tab_2", "title": "Two", "items": [], "layout": [], "aliases": {"default": [["x", "y"]]}},
    ]
    update = _synthetic(tabs).update
    with pytest.raises(DatalensValidationError, match="several tabs"):
        update.remove_alias("x", "y")
    update.remove_alias("x", "y", tab="tab_2")
    applied = _apply_update(update.to_spec())
    assert _as_dict(_tabs(applied)[0]["aliases"])["default"] == [["x", "y"]]
    assert _as_dict(_tabs(applied)[1]["aliases"])["default"] == []


# -- verbatim guarantees over feature fixtures -----------------------------------


# One valid scenario per content-op family over the items_features fixture
# (ctl1 control, wg1 widget with enableActionParams=True on wt1, nw1
# neuro_widget). Each op must leave the untouched unknown wire fragments —
# the whole neuro_widget and the enableActionParams flag — byte-identical.
_CONTENT_OPS = {
    "update_tab": lambda update: update.update_tab("tab_1", title="Renamed"),
    "hide_tab": lambda update: update.hide_tab("tab_1"),
    "replace_chart": lambda update: update.replace_chart(item_id="wg1", chart="swapped"),
    "set_chart_params_widget": lambda update: update.set_chart_params(item_id="wg1", params={"p": "v"}),
    "set_chart_params_control": lambda update: update.set_chart_params(item_id="ctl1", params={"p": "v"}),
    "remove_item": lambda update: update.remove_item("tx1"),
    "add_text": lambda update: update.add_text("new", tab="tab_1", at=(0, 90, 8, 4)),
    "global_params": lambda update: update.global_params({"g": "1"}),
}


@pytest.mark.parametrize("op_name", sorted(_CONTENT_OPS))
def test_unknown_items_survive_every_content_op(op_name: str) -> None:
    entry = _load_entry("items_features")
    data = cast(dict[str, object], entry["data"])
    source_neuro = [
        item for tab in _tabs(data) for item in _as_dicts(tab["items"]) if item.get("type") == "neuro_widget"
    ]
    assert source_neuro, "fixture must carry a neuro_widget"

    update = _dashboard_from(entry).update
    _CONTENT_OPS[op_name](update)
    applied = _apply_update(update.to_spec())

    applied_neuro = [
        item for tab in _tabs(applied) for item in _as_dicts(tab["items"]) if item.get("type") == "neuro_widget"
    ]
    assert _canonical(applied_neuro) == _canonical(source_neuro)
    # enableActionParams on the widget's chart tab survives every op
    applied_widget = next(item for tab in _tabs(applied) for item in _as_dicts(tab["items"]) if item.get("id") == "wg1")
    widget_tab = _as_dicts(_as_dict(applied_widget["data"])["tabs"])[0]
    assert widget_tab["enableActionParams"] is True


# -- add_connection / disconnect_all / add_alias (epic D4, stage 14) ----------------
#
# group_control_manual.json: tab GJ carries group 2j (members no/7o/om/4G/Yg),
# widget 1l with chart-tab rB, and pre-existing edges member->rB.


def test_update_add_connection_translates_widget_and_member_ids() -> None:
    update = _dashboard("group_control_manual").update
    update.add_connection(from_item="1l", to_item="no")
    ops = [op for op in update.ops if isinstance(op, AddConnectionOp)]
    # widget 1l expands to ALL its chart tabs (fixture: Mx and rB)
    assert sorted((op.from_id, op.to_id) for op in ops) == [("Mx", "no"), ("rB", "no")]

    data = _apply_update(update.to_spec())
    connections = _as_dicts(_tabs(data)[0]["connections"])
    assert {"from": "rB", "to": "no", "kind": "ignore"} in connections
    assert {"from": "Mx", "to": "no", "kind": "ignore"} in connections


def test_update_add_connection_dedups_against_the_snapshot() -> None:
    update = _dashboard("group_control_manual").update
    # member->rB edges already exist in the fixture: adding them again is a no-op
    update.add_connection(from_item="no", to_item="rB")
    assert [op for op in update.ops if isinstance(op, AddConnectionOp)] == []


def test_update_add_connection_group_reference_expands_to_members() -> None:
    update = _dashboard("group_control_manual").update
    update.add_connection(from_item="1l", to_item="2j")
    ops = [op for op in update.ops if isinstance(op, AddConnectionOp)]
    targets = {op.to_id for op in ops}
    assert {"no", "7o", "om"}.issubset(targets)
    assert {op.from_id for op in ops} == {"Mx", "rB"}  # all chart tabs of widget 1l


def test_update_add_connection_rejects_text_and_unknown_endpoints() -> None:
    update = _dashboard("group_control_manual").update
    with pytest.raises(DatalensValidationError, match="Unknown item id"):
        update.add_connection(from_item="nope", to_item="no")


def test_update_readd_after_remove_is_allowed_in_one_builder() -> None:
    update = _dashboard("group_control_manual").update
    update.remove_connection(from_item="no", to_item="rB")
    update.add_connection(from_item="no", to_item="rB")
    data = _apply_update(update.to_spec())
    connections = _as_dicts(_tabs(data)[0]["connections"])
    assert {"from": "no", "to": "rB", "kind": "ignore"} in connections


def test_update_disconnect_all_full_mesh_over_expansions() -> None:
    update = _dashboard("group_control_manual").update
    update.disconnect_all("1l", "om")
    ops = [op for op in update.ops if isinstance(op, AddConnectionOp)]
    pairs = {(op.from_id, op.to_id) for op in ops}
    assert ("rB", "om") in pairs
    # om->rB already exists in the fixture: only the missing direction is added
    assert ("om", "rB") not in pairs


def test_update_add_alias_dedup_and_tab_requirements() -> None:
    update = _dashboard("group_control_manual").update
    with pytest.raises(DatalensValidationError, match="pass tab="):
        update.add_alias("guid_x", "guid_y")  # the fixture has several tabs
    update.add_alias("guid_x", "guid_y", tab="GJ")
    update.add_alias("guid_y", "guid_x", tab="GJ")  # same set: silent skip
    ops = [op for op in update.ops if isinstance(op, AddAliasOp)]
    assert [op.fields for op in ops] == [("guid_x", "guid_y")]
    data = _apply_update(update.to_spec())
    default = _tabs(data)[0]["aliases"]["default"]  # type: ignore[index]
    assert ["guid_x", "guid_y"] in default

    with pytest.raises(DatalensValidationError, match="at least two"):
        update.add_alias("only")


# -- update_selector / remove_selector (epic D4, stage 16) --------------------------


def test_update_selector_patches_a_group_member_verbatim_elsewhere() -> None:
    update = _dashboard("group_control_manual").update
    update.update_selector(item_id="om", title="Новый титул", default_value=["Title 6"], required=False)
    data = _apply_update(update.to_spec())
    group = _as_dicts(_as_dict(_as_dicts(_tabs(data)[0]["items"])[0]["data"])["group"])
    member = next(m for m in group if m["id"] == "om")
    source = _as_dict(member["source"])
    assert member["title"] == "Новый титул"
    assert source["required"] is False
    assert source["defaultValue"] == ["Title 6"]
    # operation EQ untouched -> defaults re-encoded with the existing prefix
    assert member["defaults"] == {"field_0004": ["__eq_Title 6"]}
    # neighbours untouched
    other = next(m for m in group if m["id"] == "no")
    assert other["title"] == "Title 2"
    assert _as_dict(other["source"])["defaultValue"] == "Value 1"


def test_update_selector_patches_every_occurrence_of_a_shared_selector() -> None:
    update = _dashboard("global_items_shared_selectors").update
    update.update_selector(item_id="item_1", title="Общий титул")
    data = _apply_update(update.to_spec())
    for tab in _tabs(data):
        occurrence = next(it for it in _as_dicts(tab["globalItems"]) if it.get("id") == "item_1")
        assert _as_dict(occurrence["data"])["title"] == "Общий титул", f"tab {tab.get('id')} not patched"


def test_update_selector_wrapper_shorthand_needs_single_member() -> None:
    update = _dashboard("group_control_manual").update
    with pytest.raises(DatalensValidationError, match="pass the member id"):
        update.update_selector(item_id="2j", title="X")


def test_update_selector_requires_a_change_and_known_id() -> None:
    update = _dashboard("group_control_manual").update
    with pytest.raises(DatalensValidationError, match="at least one field"):
        update.update_selector(item_id="om")
    with pytest.raises(DatalensValidationError, match="Unknown item id"):
        update.update_selector(item_id="nope", title="X")


def test_remove_selector_member_and_cascades_connections() -> None:
    update = _dashboard("group_control_manual").update
    update.remove_selector(item_id="om")
    data = _apply_update(update.to_spec())
    tab = _tabs(data)[0]
    group = _as_dicts(_as_dict(_as_dicts(tab["items"])[0]["data"])["group"])
    assert all(m["id"] != "om" for m in group)
    assert len(group) >= 2  # group survives
    connections = _as_dicts(tab["connections"])
    assert all("om" not in (edge.get("from"), edge.get("to")) for edge in connections)


def test_remove_selector_wrapper_removes_the_whole_item() -> None:
    update = _dashboard("group_control_manual").update
    update.remove_selector(item_id="2j")
    data = _apply_update(update.to_spec())
    tab = _tabs(data)[0]
    assert all(it.get("id") != "2j" for it in _as_dicts(tab["items"]))


def test_remove_selector_rejects_non_selectors() -> None:
    update = _dashboard("group_control_manual").update
    with pytest.raises(DatalensValidationError, match="is not a selector"):
        update.remove_selector(item_id="1l")  # a widget
