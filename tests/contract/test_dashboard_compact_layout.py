"""compact_layout (RGL vertical port) + layout_reflow detection (D5.4)."""

from __future__ import annotations

from typing import cast

import pytest

from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_layout import LayoutEntry, compact_vertical
from datalens_sdk.domain.dashboard_validate import validate_dashboard


def _e(item_id: str, x: int, y: int, w: int, h: int, parent: str | None = None) -> LayoutEntry:
    return LayoutEntry(item_id, x, y, w, h, parent)


# -- compact_vertical: table-driven corpus -----------------------------------

_CORPUS: list[tuple[str, list[LayoutEntry], dict[str, int]]] = [
    ("close_interior_gap", [_e("a", 0, 0, 12, 4), _e("b", 0, 10, 12, 4)], {"a": 0, "b": 4}),
    ("independent_columns", [_e("a", 0, 0, 12, 10), _e("b", 12, 5, 12, 4)], {"a": 0, "b": 0}),
    ("overlap_pushes_down", [_e("a", 0, 0, 12, 4), _e("b", 0, 0, 12, 4)], {"a": 0, "b": 4}),
    (
        "unequal_height_stack",
        [_e("a", 0, 0, 36, 6), _e("b", 0, 20, 36, 3), _e("c", 0, 30, 36, 2)],
        {"a": 0, "b": 6, "c": 9},
    ),
    ("same_row_two_columns", [_e("a", 6, 0, 6, 4), _e("b", 0, 0, 6, 4)], {"a": 0, "b": 0}),
    ("already_compact", [_e("a", 0, 0, 12, 4), _e("b", 0, 4, 12, 4)], {"a": 0, "b": 4}),
]


@pytest.mark.parametrize(("name", "entries", "expected"), _CORPUS, ids=[c[0] for c in _CORPUS])
def test_compact_vertical_corpus(name: str, entries: list[LayoutEntry], expected: dict[str, int]) -> None:
    assert compact_vertical(entries) == expected


def test_compact_vertical_is_idempotent() -> None:
    entries = [_e("a", 0, 0, 12, 4), _e("b", 0, 10, 12, 4), _e("c", 0, 30, 12, 4)]
    first = compact_vertical(entries)
    compacted = [_e(e.item_id, e.x, first[e.item_id], e.w, e.h) for e in entries]
    assert compact_vertical(compacted) == {e.item_id: e.y for e in compacted}


def test_compact_vertical_empty() -> None:
    assert compact_vertical([]) == {}


# -- applier: CompactLayoutOp ------------------------------------------------


def _lay(i: str, x: int, y: int, w: int, h: int, parent: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"i": i, "x": x, "y": y, "w": w, "h": h}
    if parent is not None:
        entry["parent"] = parent
    return entry


def _item(item_id: str) -> dict[str, object]:
    return {"id": item_id, "type": "text", "namespace": "default", "data": {"text": "x"}}


def _tab(tab_id: str, items: list[str], layout: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": tab_id,
        "title": tab_id,
        "items": [_item(i) for i in items],
        "layout": layout,
        "connections": [],
        "aliases": {"default": []},
    }


def _dashboard(tabs: list[dict[str, object]]) -> Dashboard:
    data: dict[str, object] = {"counter": 1, "salt": "s", "schemeVersion": 8, "settings": {}, "tabs": tabs}
    return Dashboard(id="d", installation="yacloud", data=data, raw={"entryId": "d", "data": data})


def _y_of(data: dict[str, object], item_id: str, tab_index: int = 0) -> int:
    tabs = cast("list[dict[str, object]]", data["tabs"])
    for entry in cast("list[dict[str, object]]", tabs[tab_index]["layout"]):
        if entry["i"] == item_id:
            return cast(int, entry["y"])
    raise AssertionError(item_id)


def test_compact_layout_closes_gap() -> None:
    dash = _dashboard([_tab("t1", ["a", "b"], [_lay("a", 0, 0, 12, 4), _lay("b", 0, 10, 12, 4)])])
    applied = _apply_update(dash.update.compact_layout().to_spec())
    assert _y_of(applied, "b") == 4


def test_compact_layout_ignores_out_of_grid_row() -> None:
    # an out-of-grid row (x+w>36) is preserved verbatim and neither holds nor
    # pushes in-grid items during compaction
    dash = _dashboard([_tab("t1", ["a", "bad"], [_lay("a", 0, 10, 12, 4), _lay("bad", 40, 100, 1, 10)])])
    applied = _apply_update(dash.update.compact_layout(tab="t1").to_spec())
    assert _y_of(applied, "a") == 0  # in-grid item compacts to the top
    assert _y_of(applied, "bad") == 100  # out-of-grid row untouched


def test_compact_layout_leaves_pinned_byte_for_byte() -> None:
    pinned = _lay("p", 0, 0, 12, 2, parent="__fixGCont")
    before = dict(pinned)
    dash = _dashboard([_tab("t1", ["p", "a", "b"], [pinned, _lay("a", 0, 0, 12, 4), _lay("b", 0, 10, 12, 4)])])
    applied = _apply_update(dash.update.compact_layout().to_spec())
    tabs = cast("list[dict[str, object]]", applied["tabs"])
    pinned_after = next(e for e in cast("list[dict[str, object]]", tabs[0]["layout"]) if e["i"] == "p")
    assert pinned_after == before  # untouched, parent key intact
    assert _y_of(applied, "b") == 4  # default flow still compacts


def test_compact_layout_scoped_to_one_tab() -> None:
    dash = _dashboard(
        [
            _tab("t1", ["a"], [_lay("a", 0, 10, 12, 4)]),
            _tab("t2", ["b"], [_lay("b", 0, 10, 12, 4)]),
        ]
    )
    applied = _apply_update(dash.update.compact_layout(tab="t1").to_spec())
    assert _y_of(applied, "a", 0) == 0  # compacted
    assert _y_of(applied, "b", 1) == 10  # other tab untouched


# -- validate(): layout_reflow -----------------------------------------------


def _validate_data(tabs: list[dict[str, object]]) -> list[str]:
    data = {"counter": 1, "salt": "s", "schemeVersion": 8, "settings": {}, "tabs": tabs}
    return [i.kind for i in validate_dashboard(data) if i.kind == "layout_reflow"]


def test_reflow_detected_on_interior_gap() -> None:
    kinds = _validate_data([_tab("t1", ["a", "b"], [_lay("a", 0, 0, 12, 4), _lay("b", 0, 10, 12, 4)])])
    assert kinds == ["layout_reflow"]  # b would move up


def test_no_reflow_on_compact_layout() -> None:
    kinds = _validate_data([_tab("t1", ["a", "b"], [_lay("a", 0, 0, 12, 4), _lay("b", 0, 4, 12, 4)])])
    assert kinds == []


def test_no_reflow_for_pinned_gap() -> None:
    # a pinned item with space above is not in the default flow -> not reflowed
    kinds = _validate_data([_tab("t1", ["p"], [_lay("p", 0, 10, 12, 2, parent="__fixGCont")])])
    assert kinds == []
