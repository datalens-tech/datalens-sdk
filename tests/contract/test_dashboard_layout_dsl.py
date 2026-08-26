"""Contract tests for the create-side layout DSL (D5.2): auto-cursor, Layout, apply_layout."""

from __future__ import annotations

import pytest

from datalens_sdk import DashboardCreate, DashboardTab, EntryLocation, Layout, Position
from datalens_sdk.domain.specs.dashboard import GroupControlItem, LayoutItemSpec
from datalens_sdk.errors import DataLensValidationError


def _laid_out(tab: DashboardTab) -> dict[str, tuple[int, int, int, int, str | None]]:
    """item_id -> (x, y, w, h, parent) after snapshot (layout id == final id)."""
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    spec = builder.add_tab(tab).to_spec()
    out: dict[str, tuple[int, int, int, int, str | None]] = {}
    for e in spec.tabs[0].layout:
        assert isinstance(e, LayoutItemSpec)  # create path resolves autos eagerly
        out[e.i] = (e.x, e.y, e.w, e.h, e.parent)
    return out


# -- auto-cursor -------------------------------------------------------------


def test_auto_cursor_flows_into_rows() -> None:
    tab = DashboardTab("T").add_text("a", item_id="a").add_text("b", item_id="b")
    layout = _laid_out(tab)
    assert layout["a"] == (0, 0, 12, 6, None)
    assert layout["b"] == (12, 0, 12, 6, None)  # flows into the same row


def test_auto_cursor_wraps_when_row_fills() -> None:
    tab = (
        DashboardTab("T")
        .add_chart("ch", title="1", item_id="c1")
        .add_chart("ch", title="2", item_id="c2")
        .add_chart("ch", title="3", item_id="c3")
        .add_chart("ch", title="4", item_id="c4")
    )
    layout = _laid_out(tab)
    assert layout["c1"] == (0, 0, 12, 12, None)
    assert layout["c2"] == (12, 0, 12, 12, None)
    assert layout["c3"] == (24, 0, 12, 12, None)  # third fills the row
    assert layout["c4"] == (0, 12, 12, 12, None)  # fourth wraps to the next row


def test_auto_selector_uses_control_size() -> None:
    tab = DashboardTab("T").add_selector(item_id="sel", param_name="region", element="input")
    placements = set(_laid_out(tab).values())
    assert (0, 0, 9, 2, None) in placements  # standalone selector auto-places at the control default


def test_four_auto_controls_fill_one_row_before_body_wraps() -> None:
    tab = (
        DashboardTab("T")
        .add_selector(item_id="s1", param_name="p1", element="input")
        .add_selector(item_id="s2", param_name="p2", element="input")
        .add_selector(item_id="s3", param_name="p3", element="input")
        .add_selector(item_id="external", chart="chart-id", title="External")
        .add_text("body", item_id="body")
    )
    layout = _laid_out(tab)
    controls = sorted(placement for item_id, placement in layout.items() if item_id != "body")
    assert controls == [
        (0, 0, 9, 2, None),
        (9, 0, 9, 2, None),
        (18, 0, 9, 2, None),
        (27, 0, 9, 2, None),
    ]
    assert layout["external"] == (27, 0, 9, 2, None)
    assert layout["body"] == (0, 2, 12, 6, None)


def test_auto_group_selector_is_full_width_with_auto_height() -> None:
    tab = (
        DashboardTab("T")
        .add_selector(param_name="a", element="input", group="g")
        .add_selector(param_name="b", element="input", group="g")
        .add_group_selector(group="g", item_id="grp")  # at=None -> auto
    )
    spec = (
        DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
        .add_tab(tab)
        .to_spec()
    )
    assert _laid_out(tab)["grp"] == (0, 0, 36, 2, None)  # full-width own row
    group = next(item for item in spec.tabs[0].items if isinstance(item, GroupControlItem))
    assert group.auto_height is True  # auto-placed group defaults to auto-height


def test_default_sizes_by_type() -> None:
    tab = (
        DashboardTab("T")
        .add_chart("ch-1", title="C", item_id="c")
        .add_title("t", item_id="ti")
        .add_text("x", item_id="tx")
        .add_image(src="https://img.test/x.png", item_id="im")
    )
    layout = _laid_out(tab)
    assert layout["c"] == (0, 0, 12, 12, None)  # widget, row 1
    assert layout["ti"] == (0, 12, 36, 2, None)  # title wraps (full width) to row 2
    assert layout["tx"] == (0, 14, 12, 6, None)  # text starts row 3
    assert layout["im"] == (12, 14, 12, 12, None)  # image flows beside the text


def test_explicit_at_does_not_move_cursor() -> None:
    tab = (
        DashboardTab("T")
        .add_text("a", item_id="a", at=(0, 20, 12, 4))  # explicit, out of the flow
        .add_text("b", item_id="b")  # auto starts at cursor 0
    )
    layout = _laid_out(tab)
    assert layout["a"] == (0, 20, 12, 4, None)
    assert layout["b"] == (0, 0, 12, 6, None)


def test_pinned_and_default_cursors_are_independent() -> None:
    tab = DashboardTab("T").add_text("a", item_id="a", pinned=True).add_text("b", item_id="b")
    layout = _laid_out(tab)
    assert layout["a"] == (0, 0, 12, 6, "__fixGCont")
    assert layout["b"] == (0, 0, 12, 6, None)


def test_section_divider_moves_cursor_even_when_explicit() -> None:
    tab = (
        DashboardTab("T")
        .add_text("a", item_id="a")  # auto (0,0,36,4) -> cursor 4
        .add_section_divider("d", item_id="d", at=(0, 20, 36, 2))  # explicit, but drops cursor to 22
        .add_text("b", item_id="b")  # auto at 22
    )
    layout = _laid_out(tab)
    assert layout["b"][1] == 22


# -- Layout.row/grid/stack ---------------------------------------------------


def test_layout_row_even_split() -> None:
    positions = Layout.row("a", "b", "c")
    assert positions["a"] == Position(0, 0, 12, 14)
    assert positions["b"] == Position(12, 0, 12, 14)
    assert positions["c"] == Position(24, 0, 12, 14)


def test_layout_row_remainder_to_last_cell() -> None:
    positions = Layout.row("a", "b", "c", "d", "e")  # 36 // 5 = 7, last = 8
    widths = [positions[i].w for i in ("a", "b", "c", "d", "e")]
    assert widths == [7, 7, 7, 7, 8]
    assert sum(widths) == 36
    assert positions["e"].x == 28


def test_layout_row_height_sequence() -> None:
    positions = Layout.row("a", "b", h=[4, 6])
    assert positions["a"].h == 4
    assert positions["b"].h == 6


def test_layout_grid_wraps_rows() -> None:
    positions = Layout.grid("a", "b", "c", cols=2, h=10)
    assert positions["a"] == Position(0, 0, 18, 10)
    assert positions["b"] == Position(18, 0, 18, 10)
    assert positions["c"] == Position(0, 10, 36, 10)  # partial last row spans full width


def test_layout_stack() -> None:
    positions = Layout.stack("a", "b", h=[4, 6])
    assert positions["a"] == Position(0, 0, 36, 4)
    assert positions["b"] == Position(0, 4, 36, 6)


@pytest.mark.parametrize(
    "call",
    [
        lambda: Layout.row(),
        lambda: Layout.row("a", "a"),
        lambda: Layout.row("a", ""),
        lambda: Layout.row(*[f"i{n}" for n in range(37)]),
        lambda: Layout.row("a", "b", h=[4]),
        lambda: Layout.row("a", h=0),
        lambda: Layout.row("a", h=True),
        lambda: Layout.grid("a", cols=0),
        lambda: Layout.grid("a", cols=37),
        lambda: Layout.stack("a", y=-1),
    ],
)
def test_layout_rejects_bad_input(call: object) -> None:
    with pytest.raises(DataLensValidationError):
        call()  # type: ignore[operator]


# -- apply_layout ------------------------------------------------------------


def test_apply_layout_partial_patch() -> None:
    tab = DashboardTab("T").add_text("a", item_id="a", at=(0, 0, 1, 1)).add_text("b", item_id="b", at=(0, 1, 1, 1))
    tab.apply_layout({"a": Position(0, 0, 18, 8)})
    layout = _laid_out(tab)
    assert layout["a"] == (0, 0, 18, 8, None)
    assert layout["b"] == (0, 1, 1, 1, None)  # untouched


def test_apply_layout_from_layout_row() -> None:
    tab = DashboardTab("T").add_text("a", item_id="a", at=(0, 0, 1, 1)).add_text("b", item_id="b", at=(0, 1, 1, 1))
    tab.apply_layout(Layout.row("a", "b", h=8))
    layout = _laid_out(tab)
    assert layout["a"] == (0, 0, 18, 8, None)
    assert layout["b"] == (18, 0, 18, 8, None)


def test_apply_layout_empty_is_noop() -> None:
    tab = DashboardTab("T").add_text("a", item_id="a", at=(3, 4, 5, 6))
    tab.apply_layout({})
    assert _laid_out(tab)["a"] == (3, 4, 5, 6, None)


def test_apply_layout_unknown_id_fails_loud() -> None:
    tab = DashboardTab("T").add_text("a", item_id="a", at=(0, 0, 12, 4))
    with pytest.raises(DataLensValidationError, match="unknown item id 'ghost'"):
        tab.apply_layout({"ghost": Position(0, 0, 12, 4)})


def test_apply_layout_resolves_singleton_selector_member_to_wrapper() -> None:
    tab = DashboardTab("T").add_selector(item_id="sel", param_name="region", element="input", at=(0, 0, 8, 2))
    tab.apply_layout({"sel": Position(0, 10, 8, 2)})
    placements = set(_laid_out(tab).values())
    assert (0, 10, 8, 2, None) in placements


def test_apply_layout_rejects_member_of_multi_selector_group() -> None:
    tab = (
        DashboardTab("T")
        .add_selector(item_id="m1", param_name="p1", element="input", group="g")
        .add_selector(item_id="m2", param_name="p2", element="input", group="g")
        .add_group_selector(group="g", item_id="grp", at=(0, 0, 36, 2))
    )
    with pytest.raises(DataLensValidationError, match="member of a multi-selector group"):
        tab.apply_layout({"m1": Position(0, 5, 12, 2)})


# -- flow read-model: preview_layout / next_auto_position / content_bottom ----


def test_preview_layout_reports_effective_placements() -> None:
    tab = (
        DashboardTab("Overview")
        .add_title("Sales", item_id="hdr")
        .add_chart("ch-a", title="A", item_id="a")
        .add_chart("ch-b", title="B", item_id="b")
    )
    assert tab.preview_layout() == {
        "hdr": Position(0, 0, 36, 2),
        "a": Position(0, 2, 12, 12),
        "b": Position(12, 2, 12, 12),
    }
    # the preview matches what the create path actually emits
    assert {k: (p.x, p.y, p.w, p.h, None) for k, p in tab.preview_layout().items()} == _laid_out(tab)


def test_next_auto_position_is_a_pure_read() -> None:
    tab = DashboardTab("T").add_chart("ch-a", title="A", item_id="a")
    slot = tab.next_auto_position("widget")
    assert slot == Position(12, 0, 12, 12)
    assert tab.next_auto_position("widget") == slot  # cursor untouched
    tab.add_chart("ch-b", title="B", item_id="b")
    assert tab.preview_layout()["b"] == slot  # the read predicted the write


def test_next_auto_position_honors_size_and_rejects_unknown_type() -> None:
    tab = DashboardTab("T").add_chart("ch-a", title="A", item_id="a")
    assert tab.next_auto_position("widget", size=(30, 4)) == Position(0, 12, 30, 4)  # 12+30>36 wraps
    with pytest.raises(DataLensValidationError, match="Unknown item type"):
        tab.next_auto_position("banner")  # type: ignore[arg-type]


def test_content_bottom_per_pin_group() -> None:
    tab = DashboardTab("T").add_text("body", item_id="body")  # (0, 0, 12, 6)
    tab.add_text("pinned", item_id="pin", pinned=True, at=(0, 0, 36, 2))
    assert tab.content_bottom() == 6
    assert tab.content_bottom(pinned=True) == 2
    assert DashboardTab("Empty").content_bottom() == 0
    tab.add_chart("ch", title="Big", item_id="big", at=(0, tab.content_bottom(), 36, 20))
    assert tab.content_bottom() == 26


# -- size= : auto position with an explicit size ------------------------------


def test_size_flows_and_moves_the_cursor() -> None:
    laid = _laid_out(
        DashboardTab("T")
        .add_chart("ch-a", title="A", item_id="a")
        .add_chart("ch-b", title="B", item_id="b")
        .add_chart("ch-wide", title="W", item_id="w", size=(12, 10))
        .add_chart("ch-c", title="C", item_id="c")  # cursor accounted for w: wraps
    )
    assert laid["w"] == (24, 0, 12, 10, None)
    assert laid["c"] == (0, 12, 12, 12, None)  # row height stays 12 (max of the row)


def test_size_with_explicit_at_is_rejected() -> None:
    with pytest.raises(DataLensValidationError, match="size= applies to auto placement"):
        DashboardTab("T").add_text("x", at=(0, 0, 12, 6), size=(12, 6))


def test_size_validation_fails_loud() -> None:
    with pytest.raises(DataLensValidationError, match="size must be a"):
        DashboardTab("T").add_text("x", size=(12, 6, 1))  # type: ignore[arg-type]
    with pytest.raises(DataLensValidationError, match="w and h must be > 0"):
        DashboardTab("T").add_text("x", size=(12, 0))
    with pytest.raises(DataLensValidationError, match="must be <= 36"):
        DashboardTab("T").add_text("x", size=(40, 6))


def test_size_on_grouped_selector_member_is_rejected() -> None:
    with pytest.raises(DataLensValidationError, match="belong to add_group_selector"):
        DashboardTab("T").add_selector(param_name="p", element="input", group="g", size=(6, 2))


# -- flow primitives: start_row / space ---------------------------------------


def test_start_row_breaks_the_flow_row() -> None:
    laid = _laid_out(
        DashboardTab("T")
        .add_chart("ch-a", title="A", item_id="a")
        .add_chart("ch-b", title="B", item_id="b")
        .start_row()
        .add_chart("ch-c", title="C", item_id="c")  # (0, 12), not (24, 0)
        .add_chart("ch-d", title="D", item_id="d")
    )
    assert laid["c"] == (0, 12, 12, 12, None)
    assert laid["d"] == (12, 12, 12, 12, None)


def test_space_leaves_a_vertical_gap_without_wire_artifacts() -> None:
    tab = (
        DashboardTab("T")
        .add_chart("ch-a", title="A", item_id="a")
        .add_chart("ch-b", title="B", item_id="b")
        .space(1)
        .add_chart("ch-c", title="C", item_id="c")
    )
    laid = _laid_out(tab)
    assert laid["c"] == (0, 13, 12, 12, None)
    assert set(laid) == {"a", "b", "c"}  # no spacer item reached the layout


def test_space_validates_h_and_flows_per_pin_group() -> None:
    with pytest.raises(DataLensValidationError, match="space h must be a positive int"):
        DashboardTab("T").space(0)
    tab = DashboardTab("T").add_text("p", item_id="p", pinned=True).space(2, pinned=True)
    tab.add_text("q", item_id="q", pinned=True)
    tab.add_text("r", item_id="r")  # default flow untouched by the pinned space
    laid = _laid_out(tab)
    assert laid["q"] == (0, 8, 12, 6, "__fixGCont")
    assert laid["r"] == (0, 0, 12, 6, None)


def test_start_row_when_row_is_already_fresh_is_a_noop() -> None:
    laid = _laid_out(DashboardTab("T").start_row().start_row().add_text("a", item_id="a"))
    assert laid["a"] == (0, 0, 12, 6, None)


def test_content_bottom_includes_pending_space_gap() -> None:
    # an explicit at=(0, content_bottom(), ...) placed after space() must land
    # BELOW the gap, not inside it — the bottom tracks the cursor too
    tab = DashboardTab("T").add_text("a", item_id="a").space(5)
    assert tab.content_bottom() == 11
    assert tab.next_auto_position("text").y == 11  # both reads agree


def test_pinned_zones_fixed_and_collapsible() -> None:
    tab = (
        DashboardTab("T")
        .add_title("head", item_id="h", pinned="fixed")  # __fixHead
        .add_text("fold", item_id="f", pinned="collapsible")  # __fixGCont (== pinned=True)
        .add_text("legacy", item_id="g", pinned=True)
        .add_text("body", item_id="b")
    )
    laid = _laid_out(tab)
    assert laid["h"] == (0, 0, 36, 2, "__fixHead")
    assert laid["f"] == (0, 0, 12, 6, "__fixGCont")
    assert laid["g"] == (12, 0, 12, 6, "__fixGCont")  # same zone flows together
    assert laid["b"] == (0, 0, 12, 6, None)  # zones and default flow are independent
    assert tab.content_bottom(pinned="fixed") == 2
    with pytest.raises(DataLensValidationError, match='pinned must be "fixed", "collapsible" or a bool'):
        DashboardTab("T").add_text("x", pinned="header")  # type: ignore[arg-type]
