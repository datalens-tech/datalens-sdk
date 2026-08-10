"""Contract tests for Dashboard.validate() — total collect-all inspection (D2.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datalens_sdk import Dashboard
from datalens_sdk.converter.dashboard import DashboardConverter
from datalens_sdk.domain.dashboard_validate import validate_dashboard
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.specs.dashboard import (
    DashboardCreateSpec,
    DashboardSettingsSpec,
    LayoutItemSpec,
    TabSpec,
    TextItem,
)
from datalens_sdk.errors import DataLensValidationError

_FIXTURES = Path(__file__).parent / "fixtures" / "dashboards"


# -- raw builders ------------------------------------------------------------


def _text(item_id: str) -> dict[str, object]:
    return {"id": item_id, "type": "text", "namespace": "default", "data": {"text": "x"}}


def _lay(i: str, *, x: int = 0, y: int = 0, w: int = 12, h: int = 4, parent: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"i": i, "x": x, "y": y, "w": w, "h": h}
    if parent is not None:
        entry["parent"] = parent
    return entry


def _tab(
    tab_id: str = "t1",
    *,
    items: list[dict[str, object]] | None = None,
    layout: list[dict[str, object]] | None = None,
    global_items: list[dict[str, object]] | None = None,
    aliases: object = None,
) -> dict[str, object]:
    tab: dict[str, object] = {
        "id": tab_id,
        "title": "Tab",
        "items": items if items is not None else [],
        "layout": layout if layout is not None else [],
        "connections": [],
        "aliases": aliases if aliases is not None else {"default": []},
    }
    if global_items is not None:
        tab["globalItems"] = global_items
    return tab


def _data(*tabs: dict[str, object]) -> dict[str, object]:
    return {"schemeVersion": 8, "salt": "s", "counter": 1, "settings": {}, "tabs": list(tabs)}


def _kinds(data: dict[str, object]) -> list[str]:
    return [issue.kind for issue in validate_dashboard(data)]


# -- per-kind detection ------------------------------------------------------


def test_valid_dashboard_has_no_issues() -> None:
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")]))
    assert validate_dashboard(data) == ()


def test_duplicate_tab_id() -> None:
    data = _data(_tab("t1", items=[_text("a")], layout=[_lay("a")]), _tab("t1", items=[_text("b")], layout=[_lay("b")]))
    assert "duplicate_id" in _kinds(data)


def test_duplicate_item_id_cross_tab() -> None:
    data = _data(
        _tab("t1", items=[_text("dup")], layout=[_lay("dup")]), _tab("t2", items=[_text("dup")], layout=[_lay("dup")])
    )
    assert _kinds(data).count("duplicate_id") == 1


def test_duplicate_item_id_same_tab() -> None:
    data = _data(_tab("t1", items=[_text("a"), _text("a")], layout=[_lay("a")]))
    assert "duplicate_id" in _kinds(data)


def test_shared_global_item_replica_is_not_duplicate() -> None:
    control = {"id": "sel", "type": "control", "namespace": "default", "data": {"title": "R"}}
    data = _data(
        _tab("t1", global_items=[dict(control)], layout=[_lay("sel")]),
        _tab("t2", global_items=[dict(control)], layout=[_lay("sel")]),
    )
    assert "duplicate_id" not in _kinds(data)


def test_shared_global_item_divergent_payload_is_duplicate() -> None:
    data = _data(
        _tab("t1", global_items=[{"id": "sel", "type": "control", "data": {"title": "A"}}], layout=[_lay("sel")]),
        _tab("t2", global_items=[{"id": "sel", "type": "control", "data": {"title": "B"}}], layout=[_lay("sel")]),
    )
    assert "duplicate_id" in _kinds(data)


def test_duplicate_widget_tab_id() -> None:
    def widget(item_id: str) -> dict[str, object]:
        return {
            "id": item_id,
            "type": "widget",
            "namespace": "default",
            "data": {"tabs": [{"id": "wt_1", "chartId": "ch-1", "isDefault": True}]},
        }

    data = _data(_tab("t1", items=[widget("w1"), widget("w2")], layout=[_lay("w1"), _lay("w2", y=6)]))
    assert "duplicate_id" in _kinds(data)


def test_member_id_colliding_with_item_id() -> None:
    group: dict[str, object] = {
        "id": "grp",
        "type": "group_control",
        "namespace": "default",
        "data": {"group": [{"id": "clash", "title": "m"}]},
    }
    data = _data(_tab("t1", items=[_text("clash"), group], layout=[_lay("clash"), _lay("grp", y=6)]))
    assert "duplicate_id" in _kinds(data)


def test_out_of_grid_overflow() -> None:
    data = _data(_tab(items=[_text("a")], layout=[_lay("a", x=30, w=12)]))
    assert "out_of_grid" in _kinds(data)


def test_out_of_grid_non_integer_geometry_is_total() -> None:
    data = _data(_tab(items=[_text("a")], layout=[{"i": "a", "x": 0, "y": "top", "w": 12, "h": 4}]))
    kinds = _kinds(data)
    assert "out_of_grid" in kinds  # reported, not crashed


def test_overlap_default_group() -> None:
    data = _data(_tab(items=[_text("a"), _text("b")], layout=[_lay("a", w=20, h=10), _lay("b", x=5, y=5, w=20, h=10)]))
    assert "overlap" in _kinds(data)


def test_overlap_ignored_across_pin_groups() -> None:
    data = _data(
        _tab(
            items=[_text("a"), _text("b")],
            layout=[_lay("a", w=12, h=4), _lay("b", w=12, h=4, parent="__fixHead")],
        )
    )
    assert "overlap" not in _kinds(data)


def test_out_of_grid_entries_excluded_from_overlap() -> None:
    # both overflow the grid; they must be reported out_of_grid but not overlap
    data = _data(_tab(items=[_text("a"), _text("b")], layout=[_lay("a", x=30, w=12), _lay("b", x=30, w=12)]))
    kinds = _kinds(data)
    assert "out_of_grid" in kinds
    assert "overlap" not in kinds


def test_empty_chart_id() -> None:
    widget: dict[str, object] = {
        "id": "w1",
        "type": "widget",
        "namespace": "default",
        "data": {"tabs": [{"id": "wt_1", "chartId": "", "isDefault": True}]},
    }
    data = _data(_tab(items=[widget], layout=[_lay("w1")]))
    assert "empty_chart_id" in _kinds(data)


def test_missing_and_orphan_layout() -> None:
    data = _data(_tab(items=[_text("a")], layout=[_lay("ghost")]))
    kinds = _kinds(data)
    assert "missing_layout" in kinds  # 'a' has no layout entry
    assert "orphan_layout" in kinds  # 'ghost' has no item


def test_duplicate_layout_reference_is_flagged() -> None:
    # create's bijection rejects a layout id appearing more than once; validate()
    # mirrors it (a set-diff alone would silently miss the duplicate)
    data = _data(_tab(items=[_text("a")], layout=[_lay("a"), _lay("a", y=6)]))
    assert "duplicate_layout" in _kinds(data)


def test_alias_group_too_small() -> None:
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["only_one"]]}))
    assert "alias_group_too_small" in _kinds(data)


def test_alias_group_of_two_is_ok() -> None:
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["f1", "f2"]]}))
    assert "alias_group_too_small" not in _kinds(data)


def test_alias_group_with_non_string_field_is_flagged() -> None:
    # C11 parity: the converter requires every alias field to be a non-empty
    # string; validate() must flag the same shapes it would reject
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["f1", 42]]}))
    assert "alias_group_too_small" in _kinds(data)


def test_alias_group_with_empty_field_is_flagged() -> None:
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["f1", ""]]}))
    assert "alias_group_too_small" in _kinds(data)


def test_alias_group_with_duplicate_field_is_flagged() -> None:
    # ["f1", "f1"] has two raw entries but one unique field — converter parity
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["f1", "f1"]]}))
    assert "alias_group_too_small" in _kinds(data)


def test_duplicate_alias_group_is_flagged() -> None:
    # reordered duplicate: the converter rejects it, so the mirror must too
    data = _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["f1", "f2"], ["f2", "f1"]]}))
    assert "duplicate_alias_group" in _kinds(data)


def test_unknown_item_type_participates_but_skips_type_checks() -> None:
    neuro: dict[str, object] = {"id": "nw", "type": "neuro_widget", "namespace": "default", "data": {"prompt": "hi"}}
    data = _data(_tab(items=[neuro], layout=[_lay("nw")]))
    # counted for coverage/identity (no missing_layout), no widget-specific check
    assert validate_dashboard(data) == ()


# -- total property (never raises on malformed raw) --------------------------


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"tabs": "not-a-list"},
        {"tabs": ["not-a-dict", 42]},
        _data(_tab(items=["not-a-dict"], layout=["also-bad"])),  # type: ignore[list-item]
        _data(_tab(aliases="not-a-dict")),
        _data(_tab(aliases={"default": "not-a-list"})),
        {"tabs": [{"id": "t", "layout": [{"i": "x", "x": None, "y": None, "w": None, "h": None}]}]},
    ],
)
def test_validate_never_raises_on_malformed(data: object) -> None:
    result = validate_dashboard(data)  # type: ignore[arg-type]
    assert isinstance(result, tuple)


def test_issue_order_is_deterministic() -> None:
    data = _data(
        _tab(
            items=[_text("a"), _text("b"), _text("c")],
            layout=[_lay("a", w=20, h=10), _lay("b", x=5, y=5, w=20, h=10), _lay("c", x=10, y=8, w=20, h=10)],
        )
    )
    first = validate_dashboard(data)
    second = validate_dashboard(data)
    assert first == second
    assert [i.kind for i in first if i.kind == "overlap"] == ["overlap", "overlap", "overlap"]


# -- golden fixtures have no structural DEFECTS ------------------------------
#
# layout_reflow is informational, not a defect: real published dashboards
# routinely leave interior gaps (e.g. an empty top-right corner) that vertical
# compaction would close, and they render fine as authored — so it is excluded
# from the "clean" bar here.


@pytest.mark.parametrize("fixture", sorted(p.name for p in _FIXTURES.glob("*.json")))
def test_golden_fixtures_have_no_structural_defects(fixture: str) -> None:
    data = json.loads((_FIXTURES / fixture).read_text())
    defects = [issue for issue in validate_dashboard(data.get("data")) if issue.kind != "layout_reflow"]
    assert defects == []


# -- Dashboard.validate() delegates ------------------------------------------


def test_dashboard_validate_delegates() -> None:
    data = _data(
        _tab("t1", items=[_text("dup")], layout=[_lay("dup")]), _tab("t2", items=[_text("dup")], layout=[_lay("dup")])
    )
    dashboard = Dashboard(id="d1", installation="yacloud", data=data, raw={})
    issues = dashboard.validate()
    assert any(i.kind == "duplicate_id" for i in issues)


def test_dashboard_validate_empty_is_empty() -> None:
    assert Dashboard(id="d1", installation="yacloud", data={}, raw={}).validate() == ()


# -- drift: every fail-loud converter validator has a mirror validate() kind --


def _spec(tab: TabSpec) -> DashboardCreateSpec:
    return DashboardCreateSpec(
        installation="yacloud",
        name="D",
        location=EntryLocation.path("/Users/me"),
        tabs=(tab,),
        description=None,
        access_description=None,
        support_description=None,
        settings=DashboardSettingsSpec(),
        meta=None,
        generated_id_count=0,
    )


def test_drift_out_of_grid() -> None:
    spec = _spec(
        TabSpec(
            id="t1",
            title="T",
            items=(TextItem(id="a", text="x"),),
            layout=(LayoutItemSpec(i="a", x=30, y=0, w=12, h=6),),
        )
    )
    with pytest.raises(DataLensValidationError, match="x \\+ w must be <= 36"):
        DashboardConverter.from_domain_create(spec)
    assert "out_of_grid" in _kinds(_data(_tab(items=[_text("a")], layout=[_lay("a", x=30, w=12)])))


def test_drift_overlap() -> None:
    spec = _spec(
        TabSpec(
            id="t1",
            title="T",
            items=(TextItem(id="a", text="x"), TextItem(id="b", text="y")),
            layout=(LayoutItemSpec(i="a", x=0, y=0, w=20, h=10), LayoutItemSpec(i="b", x=5, y=5, w=20, h=10)),
        )
    )
    with pytest.raises(DataLensValidationError, match="overlap"):
        DashboardConverter.from_domain_create(spec)
    assert "overlap" in _kinds(
        _data(_tab(items=[_text("a"), _text("b")], layout=[_lay("a", w=20, h=10), _lay("b", x=5, y=5, w=20, h=10)]))
    )


def test_drift_duplicate_id() -> None:
    spec = _spec(
        TabSpec(
            id="t1",
            title="T",
            items=(TextItem(id="dup", text="x"), TextItem(id="dup", text="y")),
            layout=(LayoutItemSpec(i="dup", x=0, y=0, w=12, h=6),),
        )
    )
    with pytest.raises(DataLensValidationError, match="Duplicate item id"):
        DashboardConverter.from_domain_create(spec)
    assert "duplicate_id" in _kinds(_data(_tab(items=[_text("dup"), _text("dup")], layout=[_lay("dup")])))


def test_drift_missing_layout() -> None:
    spec = _spec(TabSpec(id="t1", title="T", items=(TextItem(id="a", text="x"),), layout=()))
    with pytest.raises(DataLensValidationError, match="items without layout"):
        DashboardConverter.from_domain_create(spec)
    assert "missing_layout" in _kinds(_data(_tab(items=[_text("a")], layout=[])))


def test_drift_orphan_layout() -> None:
    spec = _spec(TabSpec(id="t1", title="T", items=(), layout=(LayoutItemSpec(i="ghost", x=0, y=0, w=6, h=6),)))
    with pytest.raises(DataLensValidationError, match="layout without items"):
        DashboardConverter.from_domain_create(spec)
    assert "orphan_layout" in _kinds(_data(_tab(items=[], layout=[_lay("ghost")])))


def test_drift_alias_group_too_small() -> None:
    spec = _spec(
        TabSpec(
            id="t1",
            title="T",
            items=(TextItem(id="a", text="x"),),
            layout=(LayoutItemSpec(i="a", x=0, y=0, w=12, h=6),),
            aliases=(("only",),),
        )
    )
    with pytest.raises(DataLensValidationError, match=">=2 unique fields"):
        DashboardConverter.from_domain_create(spec)
    assert "alias_group_too_small" in _kinds(
        _data(_tab(items=[_text("a")], layout=[_lay("a")], aliases={"default": [["only"]]}))
    )


def test_shared_replica_duplicated_inside_one_tab_is_flagged() -> None:
    # K3: comparing only against the FIRST occurrence missed a duplicated
    # replica in a later tab — both copies matched the first tab's payload
    control = {"id": "sel", "type": "control", "namespace": "default", "data": {"title": "R"}}
    data = _data(
        _tab("t1", global_items=[dict(control)], layout=[_lay("sel")]),
        _tab("t2", global_items=[dict(control), dict(control)], layout=[_lay("sel")]),
    )
    assert _kinds(data).count("duplicate_id") == 1


def test_shared_replica_member_duplicated_inside_one_tab_is_flagged() -> None:
    # K3 for member ids: a doubled group replica also doubles its member id
    group: dict[str, object] = {
        "id": "grp",
        "type": "group_control",
        "namespace": "default",
        "data": {"group": [{"id": "m", "title": "m"}]},
    }
    data = _data(
        _tab("t1", global_items=[dict(group)], layout=[_lay("grp")]),
        _tab("t2", global_items=[dict(group), dict(group)], layout=[_lay("grp")]),
    )
    dup_ids = {i.item_id for i in validate_dashboard(data) if i.kind == "duplicate_id"}
    assert "grp" in dup_ids
    assert "m" in dup_ids


def test_shared_replicas_on_three_tabs_stay_clean() -> None:
    control = {"id": "sel", "type": "control", "namespace": "default", "data": {"title": "R"}}
    data = _data(*[_tab(t, global_items=[dict(control)], layout=[_lay("sel")]) for t in ("t1", "t2", "t3")])
    assert "duplicate_id" not in _kinds(data)
