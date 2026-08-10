"""Six layout ops + pin/unpin + occurrence-aware overlap gate (D5.3)."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_layout import Position
from datalens_sdk.domain.specs.dashboard import ApplyLayoutOp
from datalens_sdk.errors import DataLensValidationError


def _text_item(item_id: str) -> dict[str, object]:
    return {"id": item_id, "type": "text", "namespace": "default", "data": {"text": "x"}}


def _widget_item(item_id: str) -> dict[str, object]:
    return {
        "id": item_id,
        "type": "widget",
        "namespace": "default",
        "data": {"tabs": [{"id": f"wt_{item_id}", "chartId": "ch", "isDefault": True}]},
    }


def _group_control(wrapper_id: str, member_ids: list[str]) -> dict[str, object]:
    return {
        "id": wrapper_id,
        "type": "group_control",
        "namespace": "default",
        "data": {"group": [{"id": m, "title": m, "sourceType": "manual", "source": {}} for m in member_ids]},
    }


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
    return Dashboard(id="d", installation="yacloud", data=data, raw={"entryId": "d", "data": data})


def _layout_map(data: dict[str, object], tab_index: int = 0) -> dict[str, tuple[int, int, int, int, str | None]]:
    tabs = cast("list[dict[str, object]]", data["tabs"])
    out: dict[str, tuple[int, int, int, int, str | None]] = {}
    for e in cast("list[dict[str, object]]", tabs[tab_index]["layout"]):
        parent = e.get("parent")
        out[cast(str, e["i"])] = (
            cast(int, e["x"]),
            cast(int, e["y"]),
            cast(int, e["w"]),
            cast(int, e["h"]),
            parent if isinstance(parent, str) else None,
        )
    return out


def _one_item(item: dict[str, object], layout: dict[str, object]) -> Dashboard:
    return _dashboard([_tab("t1", items=[item], layout=[layout])])


# -- move_item ---------------------------------------------------------------


def test_move_item_absolute() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    applied = _apply_update(dash.update.move_item("a", x=5, y=6).to_spec())
    assert _layout_map(applied)["a"] == (5, 6, 12, 4, None)


def test_move_item_delta() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 5, 5, 12, 4))
    applied = _apply_update(dash.update.move_item("a", dx=3, dy=-2).to_spec())
    assert _layout_map(applied)["a"] == (8, 3, 12, 4, None)


def test_move_item_mixed_axis_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="not both"):
        dash.update.move_item("a", x=1, dx=1)


def test_move_item_zero_delta_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="dx=0 is a no-op"):
        dash.update.move_item("a", dx=0)


def test_move_item_no_args_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="needs at least one"):
        dash.update.move_item("a")


def test_move_item_bool_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="x must be an int"):
        dash.update.move_item("a", x=True)


def test_move_item_overflow_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="exceed the 36-column grid"):
        _apply_update(dash.update.move_item("a", x=30).to_spec())


# -- resize_item -------------------------------------------------------------


def test_resize_item_absolute_and_delta() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    applied = _apply_update(dash.update.resize_item("a", w=18).to_spec())
    assert _layout_map(applied)["a"] == (0, 0, 18, 4, None)
    applied2 = _apply_update(dash.update.resize_item("a", dh=2).to_spec())
    assert _layout_map(applied2)["a"] == (0, 0, 12, 6, None)


def test_resize_item_overflow_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 30, 0, 4, 4))
    with pytest.raises(DataLensValidationError, match="exceed the 36-column grid"):
        _apply_update(dash.update.resize_item("a", w=12).to_spec())


# -- swap_items --------------------------------------------------------------


def test_swap_items_local() -> None:
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 12, 6, 18, 8)])]
    )
    applied = _apply_update(dash.update.swap_items("a", "b").to_spec())
    layout = _layout_map(applied)
    assert layout["a"] == (12, 6, 18, 8, None)
    assert layout["b"] == (0, 0, 12, 4, None)


def test_shift_below_translates_pre_existing_overlap_without_failing() -> None:
    # the gate is delta-based: an op that moves an already-overlapping pair
    # uniformly did not CREATE the overlap and must not be rejected
    dash = _dashboard(
        [
            _tab(
                "t1",
                items=[_text_item("a"), _text_item("b")],
                layout=[_lay("a", 0, 10, 12, 6), _lay("b", 6, 12, 12, 6)],
            )
        ]
    )
    applied = _apply_update(dash.update.shift_below(y_threshold=10, dy=5).to_spec())
    layout = _layout_map(applied)
    assert layout["a"] == (0, 15, 12, 6, None)
    assert layout["b"] == (6, 17, 12, 6, None)


def test_swap_of_pre_existing_overlapping_pair_is_allowed() -> None:
    # swapping the two members of an already-overlapping pair keeps the same
    # overlap (same rectangles, exchanged) — nothing new was created
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 6), _lay("b", 6, 2, 12, 6)])]
    )
    applied = _apply_update(dash.update.swap_items("a", "b").to_spec())
    layout = _layout_map(applied)
    assert layout["a"] == (6, 2, 12, 6, None)
    assert layout["b"] == (0, 0, 12, 6, None)


def test_move_creating_a_new_overlap_still_fails() -> None:
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 6), _lay("b", 12, 0, 12, 6)])]
    )
    with pytest.raises(DataLensValidationError, match="overlap"):
        _apply_update(dash.update.move_item("a", x=12).to_spec())


def test_overlap_gate_ignores_out_of_grid_entries() -> None:
    # b(35,0,5,4) sticks out of the 36-column grid: validate() excludes it from
    # overlap checks, and the update gate must agree — moving a legally must
    # not be blocked by a pre-existing defective row
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 35, 0, 5, 4)])]
    )
    applied = _apply_update(dash.update.move_item("a", x=24).to_spec())
    assert _layout_map(applied)["a"] == (24, 0, 12, 4, None)


def test_unpin_item_without_layout_entry_fails_loud() -> None:
    # fail-semantics parity with pin/move/resize: an item present in items but
    # missing its layout entry (defective raw) must not unpin silently
    dash = _dashboard([_tab("t1", items=[_text_item("a")], layout=[])])
    with pytest.raises(DataLensValidationError, match="unpin_item: no layout entry"):
        _apply_update(dash.update.unpin_item("a").to_spec())


def test_apply_layout_op_checks_bounds_at_apply_time() -> None:
    # a hand-built ApplyLayoutOp bypasses the builder's Position validation;
    # the applier itself must reject out-of-grid geometry like move/resize do
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    spec = replace(dash.update.to_spec(), ops=(ApplyLayoutOp(tab_id=None, positions=(("a", 30, 0, 12, 4),)),))
    with pytest.raises(DataLensValidationError, match="exceed the 36-column grid"):
        _apply_update(spec)


def test_swap_identical_geometry_is_noop_and_skips_overlap_gate() -> None:
    # C7: swapping two entries with identical geometry changes nothing — the
    # no-op must not mark the items as touched, so a pre-existing overlap in
    # the raw (preserved verbatim) does not suddenly fail the final gate
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 0, 0, 12, 4)])]
    )
    applied = _apply_update(dash.update.swap_items("a", "b").to_spec())
    layout = _layout_map(applied)
    assert layout["a"] == (0, 0, 12, 4, None)
    assert layout["b"] == (0, 0, 12, 4, None)


def test_swap_same_item_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="two different items"):
        dash.update.swap_items("a", "a")


def test_swap_shared_ambiguous_needs_tab() -> None:
    shared = _group_control("s", ["m"])
    dash = _dashboard(
        [
            _tab(
                "t1",
                items=[_text_item("a")],
                layout=[_lay("a", 0, 0, 12, 4), _lay("s", 0, 6, 8, 2)],
                global_items=[shared],
            ),
            _tab(
                "t2",
                items=[_text_item("a")],
                layout=[_lay("a", 0, 0, 12, 4), _lay("s", 0, 6, 8, 2)],
                global_items=[dict(shared)],
            ),
        ]
    )
    # "a" and "s" appear together on both tabs -> ambiguous without tab=
    with pytest.raises(DataLensValidationError, match="pass tab= to disambiguate"):
        _apply_update(dash.update.swap_items("a", "s").to_spec())
    applied = _apply_update(dash.update.swap_items("a", "s", tab="t1").to_spec())
    assert _layout_map(applied, 0)["a"] == (0, 6, 8, 2, None)
    assert _layout_map(applied, 1)["a"] == (0, 0, 12, 4, None)  # t2 untouched


# -- shift_below -------------------------------------------------------------


def test_shift_below_moves_only_at_or_after_threshold() -> None:
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 0, 10, 12, 4)])]
    )
    applied = _apply_update(dash.update.shift_below(y_threshold=10, dy=5).to_spec())
    layout = _layout_map(applied)
    assert layout["a"] == (0, 0, 12, 4, None)  # above threshold, untouched
    assert layout["b"] == (0, 15, 12, 4, None)


def test_shift_below_negative_result_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 5, 12, 4))
    with pytest.raises(DataLensValidationError, match="above the grid"):
        _apply_update(dash.update.shift_below(y_threshold=0, dy=-10).to_spec())


def test_shift_below_zero_dy_rejected() -> None:
    dash = _one_item(_text_item("a"), _lay("a", 0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="dy must be a non-zero int"):
        dash.update.shift_below(y_threshold=0, dy=0)


# -- pin / unpin -------------------------------------------------------------


def test_pin_item_writes_parent_and_unpin_restores_flow() -> None:
    dash = _one_item(_widget_item("w"), _lay("w", 0, 0, 18, 14))
    pinned = _apply_update(dash.update.pin_item("w").to_spec())
    assert _layout_map(pinned)["w"] == (0, 0, 18, 14, "__fixGCont")

    dash2 = _one_item(_widget_item("w"), _lay("w", 0, 0, 18, 14, parent="__fixGCont"))
    unpinned = _apply_update(dash2.update.unpin_item("w").to_spec())
    assert _layout_map(unpinned)["w"] == (0, 0, 18, 14, None)  # coords preserved, parent gone


def test_unpin_is_idempotent_when_not_pinned() -> None:
    dash = _one_item(_widget_item("w"), _lay("w", 0, 0, 18, 14))
    unpinned = _apply_update(dash.update.unpin_item("w").to_spec())
    assert _layout_map(unpinned)["w"] == (0, 0, 18, 14, None)


def test_pin_selector_is_rejected_pending_d5_6() -> None:
    dash = _one_item(_group_control("grp", ["m"]), _lay("grp", 0, 0, 8, 2))
    with pytest.raises(DataLensValidationError, match="deferred to D5"):
        dash.update.pin_item("grp")


def test_noop_unpin_leaves_preexisting_overlap_alone() -> None:
    # a and b already overlap (pre-existing); unpinning a — which was never
    # pinned — changes nothing and must NOT trip the overlap gate
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 0, 0, 12, 4)])]
    )
    applied = _apply_update(dash.update.unpin_item("a").to_spec())  # no-op, must not raise
    assert _layout_map(applied)["a"] == (0, 0, 12, 4, None)


def test_apply_layout_foreign_tab_id_fails_loud_at_call_time() -> None:
    # 'a' lives only on t1; applying it scoped to t2 must fail loud when the op is
    # queued (call time), not silently no-op — a typo'd target is caught early
    dash = _dashboard(
        [
            _tab("t1", items=[_text_item("a")], layout=[_lay("a", 0, 0, 12, 4)]),
            _tab("t2", items=[_text_item("b")], layout=[_lay("b", 0, 0, 12, 4)]),
        ]
    )
    with pytest.raises(DataLensValidationError, match="not on tab"):
        dash.update.apply_layout({"a": (0, 8, 12, 4)}, tab="t2")


# -- shared occurrences + occurrence-aware overlap ---------------------------


def test_move_shared_item_affects_all_occurrences() -> None:
    shared = _group_control("s", ["m"])
    dash = _dashboard(
        [
            _tab("t1", items=[], layout=[_lay("s", 0, 0, 8, 2)], global_items=[shared]),
            _tab("t2", items=[], layout=[_lay("s", 0, 0, 8, 2)], global_items=[dict(shared)]),
        ]
    )
    applied = _apply_update(dash.update.move_item("s", x=5).to_spec())
    assert _layout_map(applied, 0)["s"][0] == 5
    assert _layout_map(applied, 1)["s"][0] == 5


def test_move_creating_overlap_is_rejected() -> None:
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 0, 10, 12, 4)])]
    )
    with pytest.raises(DataLensValidationError, match="items 'a' and 'b' overlap"):
        _apply_update(dash.update.move_item("b", y=0).to_spec())


def test_preexisting_overlap_of_untouched_items_is_not_blocked() -> None:
    # a & b already overlap; the op only touches c (elsewhere) -> update succeeds
    dash = _dashboard(
        [
            _tab(
                "t1",
                items=[_text_item("a"), _text_item("b"), _text_item("c")],
                layout=[_lay("a", 0, 0, 12, 6), _lay("b", 6, 2, 12, 6), _lay("c", 0, 20, 12, 4)],
            )
        ]
    )
    applied = _apply_update(dash.update.move_item("c", y=25).to_spec())
    assert _layout_map(applied)["c"] == (0, 25, 12, 4, None)


def test_composition_move_then_swap() -> None:
    dash = _dashboard(
        [_tab("t1", items=[_text_item("a"), _text_item("b")], layout=[_lay("a", 0, 0, 12, 4), _lay("b", 0, 10, 12, 4)])]
    )
    applied = _apply_update(dash.update.move_item("a", x=12).swap_items("a", "b").to_spec())
    layout = _layout_map(applied)
    assert layout["b"] == (12, 0, 12, 4, None)
    assert layout["a"] == (0, 10, 12, 4, None)


def test_pin_item_zone_fixed_and_repin() -> None:
    dash = _one_item(_widget_item("w"), _lay("w", 0, 0, 12, 4))
    pinned = _apply_update(dash.update.pin_item("w", zone="fixed").to_spec())
    assert _layout_map(pinned)["w"] == (0, 0, 12, 4, "__fixHead")
    # re-pin an already collapsible-pinned item into the fixed zone
    dash2 = _one_item(_widget_item("w"), _lay("w", 0, 0, 12, 4, parent="__fixGCont"))
    repinned = _apply_update(dash2.update.pin_item("w", zone="fixed").to_spec())
    assert _layout_map(repinned)["w"] == (0, 0, 12, 4, "__fixHead")


# -- one layout entry per occurrence (K2): no silent partial application -----------


def _shared_on_two_tabs_missing_layout_on_second() -> Dashboard:
    shared = _group_control("s", ["m"])
    return _dashboard(
        [
            _tab("t1", items=[], layout=[_lay("s", 0, 0, 8, 2)], global_items=[shared]),
            _tab("t2", items=[], layout=[], global_items=[dict(shared)]),  # layout entry missing
        ]
    )


@pytest.mark.parametrize(
    "apply",
    [
        lambda u: u.move_item("s", x=5),
        lambda u: u.resize_item("s", w=10),
        lambda u: u.unpin_item("s"),
        lambda u: u.apply_layout({"s": Position(0, 5, 8, 2)}),
    ],
)
def test_layout_op_fails_loud_when_an_occurrence_lacks_layout(apply: object) -> None:
    # the "all occurrences" contract: mutating only the tab that HAS a layout
    # entry would silently desync the identical-id replicas — fail instead
    dash = _shared_on_two_tabs_missing_layout_on_second()
    with pytest.raises(DataLensValidationError, match="occurs on tab 't2' but has 0 layout entries"):
        _apply_update(apply(dash.update).to_spec())  # type: ignore[operator]


def test_move_shared_item_with_full_layout_still_covers_all_occurrences() -> None:
    shared = _group_control("s", ["m"])
    dash = _dashboard(
        [
            _tab("t1", items=[], layout=[_lay("s", 0, 0, 8, 2)], global_items=[shared]),
            _tab("t2", items=[], layout=[_lay("s", 2, 4, 8, 2)], global_items=[dict(shared)]),
        ]
    )
    applied = _apply_update(dash.update.move_item("s", dx=1).to_spec())
    assert _layout_map(applied, 0)["s"][0] == 1
    assert _layout_map(applied, 1)["s"][0] == 3
