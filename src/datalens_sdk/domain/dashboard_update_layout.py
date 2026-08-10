"""Layout-operation mixin of the dashboard update builder (epics D5.2 / D5.3).

Batch ``apply_layout`` lives here (D5.2); the six point operations
(move/resize/swap/shift/pin/unpin) join it in D5.3. Kept out of
``dashboard_update.py`` (near the 650-LOC domain cap). Every mutator validates
its references against the shadow index at call time and appends a typed op;
the converter appliers do the raw mutation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from typing_extensions import Self

from datalens_sdk.domain.dashboard_layout import Position
from datalens_sdk.domain.dashboard_tab_layout import pin_parent
from datalens_sdk.domain.dashboard_types import PinZone
from datalens_sdk.domain.specs.dashboard import (
    ApplyLayoutOp,
    CompactLayoutOp,
    MoveItemOp,
    PinItemOp,
    ResizeItemOp,
    ShiftBelowOp,
    SwapItemsOp,
    UnpinItemOp,
)
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard_update_support import _ItemOccurrence
    from datalens_sdk.domain.specs.dashboard import DashboardUpdateOp

_PINNABLE_TYPES = frozenset({"widget", "text", "title", "image"})


def _checked_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataLensValidationError(f"{field} must be an int, got {value!r}")
    return value


def _checked_axis(name: str, absolute: int | None, delta: int | None) -> None:
    if absolute is not None:
        _checked_int(absolute, field=name)
    if delta is not None and _checked_int(delta, field=f"d{name}") == 0:
        raise DataLensValidationError(f"d{name}=0 is a no-op")
    if absolute is not None and delta is not None:
        raise DataLensValidationError(f"pass either {name}= (absolute) or d{name}= (delta), not both")


class _LayoutOpsMixin:
    """Layout mutators shared into :class:`DashboardUpdate`."""

    if TYPE_CHECKING:
        _ops: list[DashboardUpdateOp]
        _item_occurrences: dict[str, list[_ItemOccurrence]]
        _item_group_children: dict[str, set[str]]

        def _resolve_tab(self, ref: str) -> str: ...

        def _require_item(self, item_id: str) -> str: ...

    def apply_layout(
        self,
        layout: Mapping[str, Position | tuple[int, int, int, int]],
        *,
        tab: str | None = None,
    ) -> Self:
        """Reposition existing items to absolute cells by id (batch move/resize).

        Keys are item ids (a singleton selector's member id resolves to its
        wrapper; a member of a multi-selector group is rejected). ``tab=`` limits
        the change to one tab; without it a shared item moves on every tab it
        appears on. Unknown ids fail loud before any op is queued.
        """
        tab_id = self._resolve_tab(tab) if tab is not None else None
        positions: list[tuple[str, int, int, int, int]] = []
        for ref, position in layout.items():
            item_id = self._resolve_update_layout_ref(ref)
            # tab-scoped: fail loud at CALL time if the item isn't on that tab,
            # so a typo'd/foreign target never looks like a silent success
            if tab_id is not None and tab_id not in {occ.tab_id for occ in self._item_occurrences.get(item_id, ())}:
                raise DataLensValidationError(f"apply_layout: item {item_id!r} is not on tab {tab_id!r}")
            resolved = Position.coerce(position)
            positions.append((item_id, resolved.x, resolved.y, resolved.w, resolved.h))
        self._ops.append(ApplyLayoutOp(tab_id=tab_id, positions=tuple(positions)))
        return self

    def move_item(
        self, item_id: str, *, x: int | None = None, y: int | None = None, dx: int | None = None, dy: int | None = None
    ) -> Self:
        """Move an item (all occurrences of a shared one). Per axis pass an
        absolute (``x``/``y``) OR a non-zero relative (``dx``/``dy``)."""
        item_id = self._resolve_update_layout_ref(item_id)
        self._require_item(item_id)
        _checked_axis("x", x, dx)
        _checked_axis("y", y, dy)
        if x is None and y is None and dx is None and dy is None:
            raise DataLensValidationError("move_item needs at least one of x/y/dx/dy")
        self._ops.append(MoveItemOp(item_id=item_id, x=x, y=y, dx=dx, dy=dy))
        return self

    def resize_item(
        self, item_id: str, *, w: int | None = None, h: int | None = None, dw: int | None = None, dh: int | None = None
    ) -> Self:
        """Resize an item (all occurrences). Per dimension pass an absolute
        (``w``/``h``) OR a non-zero relative (``dw``/``dh``)."""
        item_id = self._resolve_update_layout_ref(item_id)
        self._require_item(item_id)
        _checked_axis("w", w, dw)
        _checked_axis("h", h, dh)
        if w is None and h is None and dw is None and dh is None:
            raise DataLensValidationError("resize_item needs at least one of w/h/dw/dh")
        self._ops.append(ResizeItemOp(item_id=item_id, w=w, h=h, dw=dw, dh=dh))
        return self

    def swap_items(self, first: str, second: str, *, tab: str | None = None) -> Self:
        """Swap the rectangles of two items on one tab."""
        first = self._resolve_update_layout_ref(first)
        second = self._resolve_update_layout_ref(second)
        if first == second:
            raise DataLensValidationError("swap_items needs two different items")
        self._require_item(first)
        self._require_item(second)
        tab_id = self._resolve_tab(tab) if tab is not None else None
        self._ops.append(SwapItemsOp(first_item_id=first, second_item_id=second, tab_id=tab_id))
        return self

    def shift_below(self, *, y_threshold: int, dy: int, tab: str | None = None) -> Self:
        """Shift every item at ``y >= y_threshold`` down by ``dy`` (one tab, or
        all tabs when ``tab`` is omitted)."""
        if isinstance(y_threshold, bool) or not isinstance(y_threshold, int) or y_threshold < 0:
            raise DataLensValidationError(f"y_threshold must be a non-negative int, got {y_threshold!r}")
        if isinstance(dy, bool) or not isinstance(dy, int) or dy == 0:
            raise DataLensValidationError(f"dy must be a non-zero int, got {dy!r}")
        tab_id = self._resolve_tab(tab) if tab is not None else None
        self._ops.append(ShiftBelowOp(tab_id=tab_id, y_threshold=y_threshold, dy=dy))
        return self

    def pin_item(self, item_id: str, *, zone: PinZone = "collapsible") -> Self:
        """Pin a widget/text/title/image into a header pin zone (all
        occurrences): "fixed" is always visible, "collapsible" can be folded.
        Pinning selectors is deferred to D5.6."""
        item_id = self._resolve_update_layout_ref(item_id)
        item_type = self._require_item(item_id)
        if item_type not in _PINNABLE_TYPES:
            raise DataLensValidationError(
                f"pin_item does not support {item_type!r} items yet (item {item_id!r}); "
                "pinning selectors is deferred to D5.6"
            )
        parent = pin_parent(zone)
        if parent is None:
            raise DataLensValidationError('zone must be "fixed" or "collapsible"; use unpin_item to unpin')
        self._ops.append(PinItemOp(item_id=item_id, parent=parent))
        return self

    def unpin_item(self, item_id: str) -> Self:
        """Return a pinned item to the normal flow (all occurrences; idempotent)."""
        item_id = self._resolve_update_layout_ref(item_id)
        self._require_item(item_id)
        self._ops.append(UnpinItemOp(item_id=item_id))
        return self

    def compact_layout(self, *, tab: str | None = None) -> Self:
        """Opt-in: pull the default-flow items of a tab (or all tabs) upward to
        close vertical gaps. Pinned zones are untouched. Compaction is never
        automatic — the UI's silent reflow is what :meth:`Dashboard.validate`
        flags, so this is the explicit way to accept it."""
        tab_id = self._resolve_tab(tab) if tab is not None else None
        self._ops.append(CompactLayoutOp(tab_id=tab_id))
        return self

    def _resolve_update_layout_ref(self, ref: str) -> str:
        """Map a layout ref to the addressable (wrapper/item) id, à la create's
        resolver but over the shadow index."""
        if ref in self._item_occurrences:
            return ref
        for wrapper, children in self._item_group_children.items():
            if ref in children:
                if len(children) == 1:
                    return wrapper
                raise DataLensValidationError(
                    f"apply_layout: {ref!r} is a member of a multi-selector group; "
                    "reposition the group by its item_id instead"
                )
        known = sorted(self._item_occurrences)
        raise DataLensValidationError(f"apply_layout: unknown item id {ref!r}; known ids: {known}")
