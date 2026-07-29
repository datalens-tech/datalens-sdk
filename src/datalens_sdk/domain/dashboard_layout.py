"""Pure geometry for dashboard layouts: the grid, item positions, default
sizes, and group-aware overlap detection.

No wire/DTO/HTTP here — this module is imported by both the domain builders and
the converter validators so the grid contract has a single source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from datalens_sdk.domain.dashboard_types import DashboardItemType
from datalens_sdk.errors import DatalensValidationError

GRID_COLUMNS: Final[int] = 36

# Default (w, h) per item type for auto-cursor placement (at=None). User-tuned
# DX defaults for a 3-up grid (charts/text/image are a third of the 36-col
# width, so three fit across a row when arranged with Layout.grid/row);
# titles span full width. Selectors auto-place too: a standalone selector uses
# the compact ``control`` size and an assembled group uses the full-width
# ``group_control`` size. All values are user-overridable via at=. Wrapped in a
# MappingProxyType so the shared table cannot be mutated at runtime.
DEFAULT_ITEM_SIZES: Final[Mapping[DashboardItemType, tuple[int, int]]] = MappingProxyType(
    {
        "title": (36, 2),
        "text": (12, 6),
        "widget": (12, 12),
        "image": (12, 12),
        "control": (2, 2),
        "group_control": (36, 2),
        "neuro_widget": (12, 12),
    }
)


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DatalensValidationError(f"Position.{field} must be an int, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class Position:
    """An item's grid rectangle: ``x``/``y`` top-left cell, ``w``/``h`` span.

    The grid is ``GRID_COLUMNS`` (36) wide and vertically unbounded. Coordinates
    are validated eagerly with actionable messages so a bad ``at=`` fails at the
    call site, not deep in the converter.
    """

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        x = _require_int(self.x, field="x")
        y = _require_int(self.y, field="y")
        w = _require_int(self.w, field="w")
        h = _require_int(self.h, field="h")
        if x < 0 or y < 0:
            raise DatalensValidationError(f"Position x and y must be >= 0, got x={x}, y={y}")
        if w <= 0 or h <= 0:
            raise DatalensValidationError(f"Position w and h must be > 0, got w={w}, h={h}")
        if x + w > GRID_COLUMNS:
            raise DatalensValidationError(
                f"Position x + w must be <= {GRID_COLUMNS} (the grid width), got x={x} + w={w} = {x + w}"
            )

    @classmethod
    def coerce(cls, value: Position | tuple[int, int, int, int]) -> Position:
        """Accept a :class:`Position` or an ``(x, y, w, h)`` tuple; reject anything else."""
        if isinstance(value, Position):
            return value
        if isinstance(value, tuple) and len(value) == 4:
            return cls(*value)
        raise DatalensValidationError(f"position must be a Position or an (x, y, w, h) tuple, got {value!r}")

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    """A normalized, geometry-valid layout row used for overlap/compaction.

    ``parent`` is the pin-group key (``None`` for the default flow,
    ``"__fixHead"``/``"__fixGCont"`` for pinned zones); overlap is only ever
    compared within one group.
    """

    item_id: str
    x: int
    y: int
    w: int
    h: int
    parent: str | None = None


def layout_entries(layout: Iterable[object]) -> tuple[list[LayoutEntry], list[Mapping[str, object]]]:
    """Split a materialized wire/raw ``layout`` array into (well-formed entries,
    malformed rows).

    Malformed = missing string id or non-int (bool-rejecting) x/y/w/h. Callers
    feed the entries to :func:`find_overlaps`; ``validate()`` reports the
    malformed rows as out-of-grid issues and excludes them from geometry.
    """
    valid: list[LayoutEntry] = []
    malformed: list[Mapping[str, object]] = []
    for raw in layout:
        if not isinstance(raw, Mapping):
            continue
        item_id = raw.get("i")
        x, y, w, h = raw.get("x"), raw.get("y"), raw.get("w"), raw.get("h")
        coords_ok = all(not isinstance(v, bool) and isinstance(v, int) for v in (x, y, w, h))
        if not isinstance(item_id, str) or not coords_ok:
            malformed.append(raw)
            continue
        parent = raw.get("parent")
        valid.append(
            LayoutEntry(item_id, x, y, w, h, parent if isinstance(parent, str) else None)  # type: ignore[arg-type]
        )
    return valid, malformed


def is_in_grid(entry: LayoutEntry) -> bool:
    """True when the entry sits fully inside the grid. Out-of-grid/malformed rows
    are excluded from placement math (auto-cursor bottoms, compaction, reflow) and
    preserved verbatim; this is the single source of truth for that predicate."""
    return entry.x >= 0 and entry.y >= 0 and entry.w > 0 and entry.h > 0 and entry.x + entry.w <= GRID_COLUMNS


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DatalensValidationError(f"{field} must be a positive int, got {value!r}")
    return value


def _validated_ids(item_ids: tuple[str, ...]) -> tuple[str, ...]:
    if not item_ids:
        raise DatalensValidationError("Layout needs at least one item id")
    if any(not isinstance(i, str) or not i for i in item_ids):
        raise DatalensValidationError(f"Layout item ids must be non-empty strings, got {item_ids!r}")
    if len(set(item_ids)) != len(item_ids):
        raise DatalensValidationError(f"Layout item ids must be unique, got {item_ids!r}")
    return item_ids


def _row_positions(item_ids: tuple[str, ...], *, y: int, heights: tuple[int, ...]) -> dict[str, Position]:
    """Lay ``item_ids`` across one full-width row; the last cell absorbs the
    division remainder so the row always spans exactly ``GRID_COLUMNS``."""
    count = len(item_ids)
    base = GRID_COLUMNS // count
    positions: dict[str, Position] = {}
    x = 0
    for index, item_id in enumerate(item_ids):
        width = GRID_COLUMNS - x if index == count - 1 else base
        positions[item_id] = Position(x, y, width, heights[index])
        x += width
    return positions


class Layout:
    """Static layout helpers producing ``{item_id: Position}`` mappings for
    :meth:`DashboardTab.apply_layout` / ``DashboardUpdate.apply_layout``.

    The pattern is "add content with explicit item ids, then apply a layout".
    Every row distributes all ``GRID_COLUMNS`` columns (the remainder goes to
    the last cell), so rows never leave a ragged gap.
    """

    @staticmethod
    def row(*item_ids: str, y: int = 0, h: int | Sequence[int] = 14) -> dict[str, Position]:
        """One full-width row of equal-width cells (≤ 36 items)."""
        ids = _validated_ids(item_ids)
        if len(ids) > GRID_COLUMNS:
            raise DatalensValidationError(f"Layout.row fits at most {GRID_COLUMNS} items, got {len(ids)}")
        heights = _resolved_heights(h, len(ids))
        _require_non_negative(y, field="y")
        return _row_positions(ids, y=y, heights=heights)

    @staticmethod
    def grid(*item_ids: str, cols: int, y: int = 0, h: int = 14) -> dict[str, Position]:
        """A ``cols``-wide grid, row by row (the last row may be partial)."""
        ids = _validated_ids(item_ids)
        _require_positive_int(cols, field="cols")
        if cols > GRID_COLUMNS:
            raise DatalensValidationError(f"cols must be <= {GRID_COLUMNS}, got {cols}")
        row_height = _require_positive_int(h, field="h")
        _require_non_negative(y, field="y")
        positions: dict[str, Position] = {}
        for start in range(0, len(ids), cols):
            row_ids = ids[start : start + cols]
            row_y = y + (start // cols) * row_height
            positions.update(_row_positions(row_ids, y=row_y, heights=(row_height,) * len(row_ids)))
        return positions

    @staticmethod
    def stack(*item_ids: str, y: int = 0, h: int | Sequence[int] = 14) -> dict[str, Position]:
        """Full-width items stacked top to bottom."""
        ids = _validated_ids(item_ids)
        heights = _resolved_heights(h, len(ids))
        _require_non_negative(y, field="y")
        positions: dict[str, Position] = {}
        cursor = y
        for item_id, height in zip(ids, heights, strict=True):
            positions[item_id] = Position(0, cursor, GRID_COLUMNS, height)
            cursor += height
        return positions


def _require_non_negative(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DatalensValidationError(f"{field} must be a non-negative int, got {value!r}")
    return value


def _resolved_heights(h: int | Sequence[int], count: int) -> tuple[int, ...]:
    if isinstance(h, int) and not isinstance(h, bool):
        height = _require_positive_int(h, field="h")
        return (height,) * count
    if isinstance(h, Sequence) and not isinstance(h, (str, bytes)):
        heights = tuple(h)
        if len(heights) != count:
            raise DatalensValidationError(f"heights must have one entry per item ({count}), got {len(heights)}")
        return tuple(_require_positive_int(value, field="h") for value in heights)
    raise DatalensValidationError(f"h must be an int or a sequence of ints, got {h!r}")


def rects_overlap(a: LayoutEntry, b: LayoutEntry) -> bool:
    """Edge-exclusive axis-aligned overlap: touching borders do not overlap."""
    return not (a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y)


def _shift_y(entry: LayoutEntry, y: int) -> LayoutEntry:
    return LayoutEntry(entry.item_id, entry.x, y, entry.w, entry.h, entry.parent)


def _first_collision(box: LayoutEntry, placed: list[LayoutEntry]) -> LayoutEntry | None:
    for other in placed:
        if rects_overlap(box, other):
            return other
    return None


def compact_vertical(entries: Iterable[LayoutEntry]) -> dict[str, int]:
    """Port of react-grid-layout vertical compaction: settle each item as high
    as it will go. Returns ``item_id -> new y``. Caller passes a single
    pin-group's entries (compaction never mixes groups) and applies the result.
    """
    items = list(entries)
    order = sorted(range(len(items)), key=lambda i: (items[i].y, items[i].x))
    placed: list[LayoutEntry] = []
    new_y: dict[str, int] = {}
    for index in order:
        box = items[index]
        bottom = max((p.y + p.h for p in placed), default=0)
        box = _shift_y(box, min(bottom, box.y))
        while box.y > 0 and _first_collision(box, placed) is None:
            box = _shift_y(box, box.y - 1)
        while True:
            hit = _first_collision(box, placed)
            if hit is None:
                break
            box = _shift_y(box, hit.y + hit.h)
        placed.append(box)
        new_y[box.item_id] = box.y
    return new_y


def find_overlaps(entries: Iterable[LayoutEntry]) -> list[tuple[str, str]]:
    """All overlapping item-id pairs, compared only WITHIN each pin-group.

    Returns ordered ``(earlier_id, later_id)`` pairs (insertion order within a
    group), deduplicated. Pairs sharing an id are skipped — a repeated id is a
    duplicate-id problem, not an overlap.
    """
    groups: dict[str | None, list[LayoutEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.parent, []).append(entry)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.item_id == b.item_id:
                    continue
                if rects_overlap(a, b) and (a.item_id, b.item_id) not in seen:
                    seen.add((a.item_id, b.item_id))
                    pairs.append((a.item_id, b.item_id))
    return pairs
