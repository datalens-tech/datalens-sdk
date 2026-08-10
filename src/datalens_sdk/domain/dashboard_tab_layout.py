"""Create-side layout helpers for :class:`DashboardTab` (epic D5.2).

Free functions kept out of ``dashboard_tab.py`` (which is near the domain
650-LOC cap): per-group auto-cursor placement and ``apply_layout`` ref
resolution. They operate on the tab's pending-item list by duck typing
(``_PendingItem`` stays private to ``dashboard_tab``) so there is no import
cycle.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from typing_extensions import Self

from datalens_sdk.domain.dashboard_layout import DEFAULT_ITEM_SIZES, GRID_COLUMNS, Position
from datalens_sdk.domain.dashboard_types import PARENT_FIX_GCONT, PARENT_FIX_HEAD, DashboardItemType, PinZone
from datalens_sdk.domain.specs.dashboard import GroupControlItem
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard_tab import _PendingItem


def validated_at(at: Position | tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Validate an explicit ``at=`` (a :class:`Position` or 4-element sequence)
    into a plain ``(x, y, w, h)`` placement. Annotated as a tuple, but any
    non-string sequence of 4 is accepted — ``[x, y, w, h]`` lists worked before
    the D5 layout rework and must keep working."""
    if isinstance(at, Position):
        return at.as_tuple()
    if isinstance(at, (str, bytes)) or not isinstance(at, Sequence) or len(at) != 4:
        raise DataLensValidationError(f"at must be a Position or an (x, y, w, h) tuple, got {at!r}")
    return Position(*at).as_tuple()


def pin_parent(pinned: bool | PinZone) -> str | None:
    """Wire ``layout.parent`` for a ``pinned=`` value: "fixed" is the always
    visible header (``__fixHead``), "collapsible" the foldable zone
    (``__fixGCont``); ``True`` is a shorthand for "collapsible"."""
    if pinned is False:
        return None
    if pinned is True or pinned == "collapsible":
        return PARENT_FIX_GCONT
    if pinned == "fixed":
        return PARENT_FIX_HEAD
    raise DataLensValidationError(f'pinned must be "fixed", "collapsible" or a bool, got {pinned!r}')


def _validated_size(size: tuple[int, int]) -> tuple[int, int]:
    """Validate a ``size=(w, h)`` override for an auto-placed item."""
    if isinstance(size, (str, bytes)) or not isinstance(size, Sequence) or len(size) != 2:
        raise DataLensValidationError(f"size must be a (w, h) pair, got {size!r}")
    w, h = size
    Position(0, 0, w, h)  # reuse int/positive/grid-width validation
    return (w, h)


def resolve_placement(
    cursors: MutableMapping[str | None, tuple[int, int, int]],
    at: Position | tuple[int, int, int, int] | None,
    *,
    item_type: DashboardItemType,
    pinned: bool | PinZone,
    size: tuple[int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Explicit ``at=`` is validated verbatim (cursor untouched); ``at=None``
    auto-places below the current content of its pin-group, sized ``size=`` or
    the item-type default."""
    if at is not None:
        if size is not None:
            raise DataLensValidationError(
                "size= applies to auto placement (at=None) only; put the size inside at=(x, y, w, h)"
            )
        return validated_at(at)
    return auto_placement(cursors, item_type=item_type, pinned=pinned, size=size)


def auto_placement(
    cursors: MutableMapping[str | None, tuple[int, int, int]],
    *,
    item_type: DashboardItemType,
    pinned: bool | PinZone,
    size: tuple[int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Place an ``at=None`` item in a left-to-right, top-to-bottom flow: fill the
    current row, then wrap to a new row when the next item would overrun the
    grid. With the third-width defaults three tiles land per row; a full-width
    item (e.g. a title) takes its own row. Each pin-group flows independently, so
    a pinned item never pushes the default flow (and vice versa). ``size=``
    overrides the item-type default; the cursor accounts for it, so following
    autos keep flowing correctly.

    The cursor state per group is ``(x, y, row_height)``.
    """
    group = pin_parent(pinned)
    if item_type not in DEFAULT_ITEM_SIZES:
        raise DataLensValidationError(f"Unknown item type {item_type!r}; expected one of {sorted(DEFAULT_ITEM_SIZES)}")
    width, height = _validated_size(size) if size is not None else DEFAULT_ITEM_SIZES[item_type]
    x, y, row_height = cursors.get(group, (0, 0, 0))
    if x + width > GRID_COLUMNS:  # wrap to the next row
        x, y, row_height = 0, y + row_height, 0
    cursors[group] = (x + width, y, max(row_height, height))
    return (x, y, width, height)


class TabLayoutFlow:
    """Cursor read-model and flow-control primitives, mixed into
    :class:`~datalens_sdk.domain.dashboard_tab.DashboardTab`.

    The auto-cursor stops being blind state: ``preview_layout`` /
    ``next_auto_position`` / ``content_bottom`` read it, ``start_row`` /
    ``space`` steer it. The flow primitives add NOTHING to the wire — they are
    pure cursor movement, recorded as ``new_row``/``gap`` markers on the next
    auto item so update-side deferred resolution replays the same structure.
    """

    __slots__ = ()

    _cursors: dict[str | None, tuple[int, int, int]]
    _pending_breaks: dict[str | None, tuple[bool, int, int]]  # (new_row, gap, floor)
    if TYPE_CHECKING:
        _pending: list[_PendingItem]

    def _register_divider_flow(self, divider: _PendingItem, *, pinned: bool | PinZone) -> None:
        """A divider always ends its row: the next auto item starts a fresh row
        under it, even when the divider's own placement was explicit (d2ce). An
        EXPLICIT divider must move the deferred resolver too, but concrete
        entries never touch its cursor — so the effect rides as a break+floor
        marker consumed by the next auto item of the group. An auto divider
        needs no marker: the resolver wraps below it naturally."""
        group = pin_parent(pinned)
        _, y, _, height = divider.placement
        self._cursors[group] = (0, y + height, 0)
        if not divider.auto:
            self._pending_breaks[group] = (True, 0, y + height)

    def start_row(self, *, pinned: bool | PinZone = False) -> Self:
        """End the current auto-flow row: the NEXT ``at=None`` item of the
        pin-group starts at ``x=0`` under it instead of filling the row.
        Explicit ``at=`` items are outside the flow and do not consume the
        break — it applies to the next auto-placed item, whenever it comes."""
        group = pin_parent(pinned)
        _, y, row_height = self._cursors.get(group, (0, 0, 0))
        self._cursors[group] = (0, y + row_height, 0)
        _, gap, floor = self._pending_breaks.get(group, (False, 0, 0))
        self._pending_breaks[group] = (True, gap, floor)
        return self

    def space(self, h: int = 1, *, pinned: bool | PinZone = False) -> Self:
        """End the current row AND leave ``h`` empty grid rows before the NEXT
        ``at=None`` item of the pin-group (explicit ``at=`` items are outside
        the flow and skip the gap). No spacer artifact reaches the wire."""
        if isinstance(h, bool) or not isinstance(h, int) or h <= 0:
            raise DataLensValidationError(f"space h must be a positive int, got {h!r}")
        group = pin_parent(pinned)
        _, y, row_height = self._cursors.get(group, (0, 0, 0))
        self._cursors[group] = (0, y + row_height + h, 0)
        _, gap, floor = self._pending_breaks.get(group, (False, 0, 0))
        self._pending_breaks[group] = (True, gap + h, floor)
        return self

    def preview_layout(self) -> dict[str, Position]:
        """Effective placement of every pending item added with an explicit
        ``item_id=``, as the create path will emit it. Items without an
        explicit id are placed too (they move the cursor and count for
        :meth:`content_bottom`) but have no stable key to report."""
        return {
            entry.explicit_id: Position(*entry.placement) for entry in self._pending if entry.explicit_id is not None
        }

    def next_auto_position(
        self,
        item_type: DashboardItemType = "widget",
        *,
        pinned: bool | PinZone = False,
        size: tuple[int, int] | None = None,
    ) -> Position:
        """The slot the NEXT ``at=None`` item of this type would take. Pure
        read: the cursor is not moved."""
        scratch = dict(self._cursors)
        return Position(*auto_placement(scratch, item_type=item_type, pinned=pinned, size=size))

    def content_bottom(self, *, pinned: bool | PinZone = False) -> int:
        """Bottom edge of the pin-group's flow — the ``y`` where a full-width
        explicit ``at=`` block goes below everything. Covers both the pending
        content (max ``y + h``) and the cursor, so a gap left by ``space()``
        stays below the reported bottom."""
        group = pin_parent(pinned)
        _, y, row_height = self._cursors.get(group, (0, 0, 0))
        bottom = max(
            (entry.placement[1] + entry.placement[3] for entry in self._pending if entry.parent == group), default=0
        )
        return max(bottom, y + row_height)


def resolve_layout_ref(pending: Sequence[_PendingItem], ref: str) -> int:
    """Index of the pending item a layout ref addresses.

    A direct explicit id (any item, or a group wrapper) matches first; a
    reference to the single member of a standalone selector resolves to its
    wrapper; a member of a multi-selector group is rejected (reposition the
    group by its ``item_id``). Only items created with an explicit ``item_id=``
    are addressable — auto-assigned ids do not exist until attach.
    """
    for index, entry in enumerate(pending):
        if entry.explicit_id == ref:
            return index
    for index, entry in enumerate(pending):
        item = entry.item
        if isinstance(item, GroupControlItem) and any(member.id == ref for member in item.members):
            if len(item.members) == 1:
                return index
            raise DataLensValidationError(
                f"apply_layout: {ref!r} is a member of a multi-selector group; "
                "reposition the group by its item_id instead"
            )
    known = sorted({entry.explicit_id for entry in pending if entry.explicit_id is not None})
    raise DataLensValidationError(
        f"apply_layout: unknown item id {ref!r}; only items created with an explicit item_id= "
        f"can be repositioned. Known ids: {known}"
    )


def apply_layout(
    pending: Sequence[_PendingItem],
    layout: Mapping[str, Position | tuple[int, int, int, int]],
) -> list[_PendingItem]:
    """Return a copy of ``pending`` with the referenced placements patched.

    Partial: items absent from ``layout`` keep their placement; an empty
    mapping is a no-op. Raises on an unknown ref before any change is applied
    (each ref is resolved against the running copy)."""
    updated = list(pending)
    for ref, position in layout.items():
        index = resolve_layout_ref(updated, ref)
        placement = Position.coerce(position).as_tuple()
        # the item now has an explicit position: it must no longer defer as an
        # auto entry on the update path (update.add_tab snapshots defer_auto)
        updated[index] = replace(updated[index], placement=placement, auto=False)
    return updated
