"""Contract tests for the geometry core (D5.1): Position, coerce, overlap."""

from __future__ import annotations

import pytest

from datalens_sdk import GRID_COLUMNS, Position
from datalens_sdk.domain.dashboard_layout import (
    DEFAULT_ITEM_SIZES,
    LayoutEntry,
    find_overlaps,
    layout_entries,
    rects_overlap,
)
from datalens_sdk.domain.dashboard_types import KNOWN_DASHBOARD_ITEM_TYPES
from datalens_sdk.errors import DataLensValidationError

# -- Position validation -----------------------------------------------------


def test_position_accepts_valid_rect() -> None:
    pos = Position(0, 0, 12, 6)
    assert pos.as_tuple() == (0, 0, 12, 6)


def test_position_rejects_negative_x_y() -> None:
    with pytest.raises(DataLensValidationError, match="x and y must be >= 0"):
        Position(-1, 0, 4, 4)
    with pytest.raises(DataLensValidationError, match="x and y must be >= 0"):
        Position(0, -1, 4, 4)


def test_position_rejects_nonpositive_w_h() -> None:
    with pytest.raises(DataLensValidationError, match="w and h must be > 0"):
        Position(0, 0, 0, 4)
    with pytest.raises(DataLensValidationError, match="w and h must be > 0"):
        Position(0, 0, 4, 0)


def test_position_rejects_grid_overflow() -> None:
    with pytest.raises(DataLensValidationError, match=f"x \\+ w must be <= {GRID_COLUMNS}"):
        Position(30, 0, 10, 4)


def test_position_allows_full_width_row() -> None:
    assert Position(0, 5, GRID_COLUMNS, 2).as_tuple() == (0, 5, 36, 2)


@pytest.mark.parametrize("field", ["x", "y", "w", "h"])
def test_position_rejects_bool(field: str) -> None:
    kwargs: dict[str, object] = {"x": 0, "y": 0, "w": 4, "h": 4}
    kwargs[field] = True
    with pytest.raises(DataLensValidationError, match=f"Position.{field} must be an int"):
        Position(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["x", "y", "w", "h"])
def test_position_rejects_non_int(field: str) -> None:
    kwargs: dict[str, object] = {"x": 0, "y": 0, "w": 4, "h": 4}
    kwargs[field] = 1.5
    with pytest.raises(DataLensValidationError, match=f"Position.{field} must be an int"):
        Position(**kwargs)  # type: ignore[arg-type]


# -- Position.coerce ---------------------------------------------------------


def test_coerce_passthrough_position() -> None:
    pos = Position(1, 2, 3, 4)
    assert Position.coerce(pos) is pos


def test_coerce_from_tuple() -> None:
    assert Position.coerce((0, 0, 12, 6)) == Position(0, 0, 12, 6)


@pytest.mark.parametrize(
    "bad",
    [
        [0, 0, 12, 6],  # list, not tuple
        "0,0,12,6",  # str
        (0, 0, 12),  # wrong length
        (0, 0, 12, 6, 1),  # wrong length
        42,  # scalar
    ],
)
def test_coerce_rejects_non_tuple(bad: object) -> None:
    with pytest.raises(DataLensValidationError, match="must be a Position or an"):
        Position.coerce(bad)  # type: ignore[arg-type]


# -- default sizes -----------------------------------------------------------


def test_default_item_sizes_cover_all_types() -> None:
    assert set(DEFAULT_ITEM_SIZES) == set(KNOWN_DASHBOARD_ITEM_TYPES)


def test_default_item_sizes_are_valid_positions() -> None:
    for w, h in DEFAULT_ITEM_SIZES.values():
        # a default placed at the origin must be a legal grid rectangle
        Position(0, 0, w, h)


# -- overlap -----------------------------------------------------------------


def _entry(item_id: str, x: int, y: int, w: int, h: int, parent: str | None = None) -> LayoutEntry:
    return LayoutEntry(item_id, x, y, w, h, parent)


def test_rects_touching_edges_do_not_overlap() -> None:
    a = _entry("a", 0, 0, 12, 4)
    b = _entry("b", 12, 0, 12, 4)  # shares the x=12 border
    assert rects_overlap(a, b) is False
    c = _entry("c", 0, 4, 12, 4)  # shares the y=4 border
    assert rects_overlap(a, c) is False


def test_rects_overlapping_detected() -> None:
    a = _entry("a", 0, 0, 12, 4)
    b = _entry("b", 6, 2, 12, 4)
    assert rects_overlap(a, b) is True


def test_find_overlaps_within_group() -> None:
    entries = [_entry("a", 0, 0, 12, 4), _entry("b", 6, 2, 12, 4)]
    assert find_overlaps(entries) == [("a", "b")]


def test_find_overlaps_ignores_cross_group() -> None:
    # identical rects but in different pin-groups: not compared
    entries = [
        _entry("a", 0, 0, 12, 4, parent=None),
        _entry("b", 0, 0, 12, 4, parent="__fixHead"),
    ]
    assert find_overlaps(entries) == []


def test_find_overlaps_within_pinned_group() -> None:
    entries = [
        _entry("a", 0, 0, 12, 4, parent="__fixGCont"),
        _entry("b", 4, 0, 12, 4, parent="__fixGCont"),
    ]
    assert find_overlaps(entries) == [("a", "b")]


def test_find_overlaps_skips_same_id() -> None:
    entries = [_entry("dup", 0, 0, 12, 4), _entry("dup", 0, 0, 12, 4)]
    assert find_overlaps(entries) == []


def test_find_overlaps_stable_and_deduped() -> None:
    entries = [
        _entry("a", 0, 0, 20, 10),
        _entry("b", 5, 5, 20, 10),
        _entry("c", 10, 8, 20, 10),
    ]
    result = find_overlaps(entries)
    # deterministic insertion order, each pair once
    assert result == [("a", "b"), ("a", "c"), ("b", "c")]
    assert len(result) == len(set(result))


# -- layout_entries extraction ----------------------------------------------


def test_layout_entries_splits_valid_and_malformed() -> None:
    raw = [
        {"i": "ok", "x": 0, "y": 0, "w": 12, "h": 4},
        {"i": "pinned", "x": 0, "y": 0, "w": 12, "h": 2, "parent": "__fixHead"},
        {"i": "bad_y", "x": 0, "y": "top", "w": 12, "h": 4},  # non-int
        {"x": 0, "y": 0, "w": 12, "h": 4},  # missing id
        {"i": "bool_w", "x": 0, "y": 0, "w": True, "h": 4},  # bool rejected
        "not-a-mapping",
    ]
    valid, malformed = layout_entries(raw)
    assert [e.item_id for e in valid] == ["ok", "pinned"]
    assert valid[1].parent == "__fixHead"
    # two malformed dicts captured (the non-mapping string is dropped silently)
    assert len(malformed) == 3
