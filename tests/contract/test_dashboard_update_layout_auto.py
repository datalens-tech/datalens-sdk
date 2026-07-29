"""Update-side auto-placement + apply_layout (D5.2): deferred at=None resolves
below existing content; apply_layout repositions existing items by id."""

from __future__ import annotations

from typing import cast

import pytest

from datalens_sdk import DashboardTab, Position
from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.errors import DatalensValidationError


def _text_item(item_id: str) -> dict[str, object]:
    return {"id": item_id, "type": "text", "namespace": "default", "data": {"text": "x"}}


def _lay(i: str, x: int, y: int, w: int, h: int, parent: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"i": i, "x": x, "y": y, "w": w, "h": h}
    if parent is not None:
        entry["parent"] = parent
    return entry


def _tab(
    tab_id: str,
    *,
    items: list[dict[str, object]],
    layout: list[dict[str, object]],
    global_items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    tab: dict[str, object] = {
        "id": tab_id,
        "title": tab_id,
        "items": items,
        "layout": layout,
        "connections": [],
        "aliases": {"default": []},
    }
    if global_items is not None:
        tab["globalItems"] = global_items
    return tab


def _dashboard(tabs: list[dict[str, object]]) -> Dashboard:
    data: dict[str, object] = {"counter": 1, "salt": "s", "schemeVersion": 8, "settings": {}, "tabs": tabs}
    return Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "dash-1", "data": data})


def _layout_map(data: dict[str, object], tab_index: int = 0) -> dict[str, tuple[int, int, int, int, str | None]]:
    tabs = cast("list[dict[str, object]]", data["tabs"])
    layout = cast("list[dict[str, object]]", tabs[tab_index]["layout"])
    out: dict[str, tuple[int, int, int, int, str | None]] = {}
    for e in layout:
        parent = e.get("parent")
        out[cast(str, e["i"])] = (
            cast(int, e["x"]),
            cast(int, e["y"]),
            cast(int, e["w"]),
            cast(int, e["h"]),
            parent if isinstance(parent, str) else None,
        )
    return out


# -- deferred auto placement -------------------------------------------------


def test_update_auto_stacks_below_existing_content() -> None:
    dash = _dashboard([_tab("tab_1", items=[_text_item("ex")], layout=[_lay("ex", 0, 0, 36, 10)])])
    applied = _apply_update(dash.update.add_text("new", tab="tab_1", item_id="new").to_spec())
    layout = _layout_map(applied)
    assert layout["ex"] == (0, 0, 36, 10, None)
    assert layout["new"] == (0, 10, 12, 6, None)  # below existing bottom


def test_update_auto_is_group_aware() -> None:
    dash = _dashboard(
        [
            _tab(
                "tab_1",
                items=[_text_item("d"), _text_item("p")],
                layout=[_lay("d", 0, 0, 36, 5), _lay("p", 0, 0, 36, 20, parent="__fixGCont")],
            )
        ]
    )
    update = dash.update.add_text("nd", tab="tab_1", item_id="nd").add_text(
        "np", tab="tab_1", item_id="np", pinned=True
    )
    layout = _layout_map(_apply_update(update.to_spec()))
    assert layout["nd"] == (0, 5, 12, 6, None)  # below the default item only
    assert layout["np"] == (0, 20, 12, 6, "__fixGCont")  # below the pinned group only


def test_update_auto_accumulates_within_one_builder() -> None:
    dash = _dashboard([_tab("tab_1", items=[_text_item("ex")], layout=[_lay("ex", 0, 0, 36, 6)])])
    update = dash.update.add_text("a", tab="tab_1", item_id="a").add_text("b", tab="tab_1", item_id="b")
    layout = _layout_map(_apply_update(update.to_spec()))
    assert layout["a"] == (0, 6, 12, 6, None)
    assert layout["b"] == (0, 12, 12, 6, None)  # stacks below the first auto add


def test_update_add_tab_resolves_auto_against_own_content() -> None:
    dash = _dashboard([_tab("tab_1", items=[_text_item("ex")], layout=[_lay("ex", 0, 0, 36, 6)])])
    new_tab = DashboardTab("New", tab_id="tab_2").add_text("a", item_id="a").add_text("b", item_id="b")
    applied = _apply_update(dash.update.add_tab(new_tab).to_spec())
    layout = _layout_map(applied, tab_index=1)
    assert layout["a"] == (0, 0, 12, 6, None)
    assert layout["b"] == (12, 0, 12, 6, None)  # flows into the same row


# -- apply_layout ------------------------------------------------------------


def test_apply_layout_repositions_existing_item() -> None:
    dash = _dashboard([_tab("tab_1", items=[_text_item("ex")], layout=[_lay("ex", 0, 0, 36, 10)])])
    applied = _apply_update(dash.update.apply_layout({"ex": Position(0, 0, 18, 8)}).to_spec())
    assert _layout_map(applied)["ex"] == (0, 0, 18, 8, None)


def _group_control(wrapper_id: str, member_ids: list[str]) -> dict[str, object]:
    return {
        "id": wrapper_id,
        "type": "group_control",
        "namespace": "default",
        "data": {"group": [{"id": m, "title": m, "sourceType": "manual", "source": {}} for m in member_ids]},
    }


def test_apply_layout_resolves_singleton_member_to_wrapper() -> None:
    dash = _dashboard([_tab("tab_1", items=[_group_control("grp", ["sel_m"])], layout=[_lay("grp", 0, 0, 8, 2)])])
    applied = _apply_update(dash.update.apply_layout({"sel_m": Position(0, 10, 8, 2)}).to_spec())
    assert _layout_map(applied)["grp"] == (0, 10, 8, 2, None)


def test_apply_layout_rejects_multi_member_group_member() -> None:
    dash = _dashboard([_tab("tab_1", items=[_group_control("grp", ["m1", "m2"])], layout=[_lay("grp", 0, 0, 36, 2)])])
    with pytest.raises(DatalensValidationError, match="member of a multi-selector group"):
        dash.update.apply_layout({"m1": Position(0, 5, 12, 2)})


def test_apply_layout_unknown_id_fails_loud() -> None:
    dash = _dashboard([_tab("tab_1", items=[_text_item("ex")], layout=[_lay("ex", 0, 0, 36, 10)])])
    with pytest.raises(DatalensValidationError, match="unknown item id 'ghost'"):
        dash.update.apply_layout({"ghost": Position(0, 0, 12, 4)})


def test_apply_layout_tab_scoped_moves_only_that_tab() -> None:
    shared = _group_control("shared", ["sm"])
    dash = _dashboard(
        [
            _tab("tab_1", items=[], layout=[_lay("shared", 0, 0, 8, 2)], global_items=[shared]),
            _tab("tab_2", items=[], layout=[_lay("shared", 0, 0, 8, 2)], global_items=[dict(shared)]),
        ]
    )
    applied = _apply_update(dash.update.apply_layout({"shared": Position(0, 15, 8, 2)}, tab="tab_1").to_spec())
    assert _layout_map(applied, tab_index=0)["shared"] == (0, 15, 8, 2, None)
    assert _layout_map(applied, tab_index=1)["shared"] == (0, 0, 8, 2, None)  # untouched
