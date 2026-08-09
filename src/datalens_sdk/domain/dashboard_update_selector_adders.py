"""Selector-member additions for the dashboard update builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from typing_extensions import Self

from datalens_sdk.domain.dashboard_create import _ITEM_NAMESPACE, _DashboardIdAllocator
from datalens_sdk.domain.dashboard_tab import DashboardTab
from datalens_sdk.domain.dashboard_types import (
    Affects,
    ControlElementType,
    DateInterval,
    RelativeDateInterval,
    SelectorOperation,
    SelectorTitlePlacement,
)
from datalens_sdk.domain.dashboard_update_support import _STAGED_TAB_TITLE, _ItemOccurrence, _TabIndex
from datalens_sdk.domain.specs.dashboard import AddSelectorMemberOp, DashboardUpdateOp, SelectorMemberSpec
from datalens_sdk.errors import DatalensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.fields import FieldLike


class _SelectorMemberAddersMixin:
    """Append typed members to group controls already in the snapshot."""

    if TYPE_CHECKING:
        _ops: list[DashboardUpdateOp]
        _tabs: list[_TabIndex]
        _item_occurrences: dict[str, list[_ItemOccurrence]]
        _item_types: dict[str, str | None]
        _item_group_children: dict[str, set[str]]
        _pending_update_groups: dict[str, list[SelectorMemberSpec]]

        @property
        def _id_allocator(self) -> _DashboardIdAllocator: ...

        def _tab_index(self, tab_id: str) -> _TabIndex: ...

    def add_selector_to_group(
        self,
        *,
        group_item_id: str,
        item_id: str,
        dataset: Dataset | None = None,
        field: FieldLike | str | None = None,
        param_name: str | None = None,
        element: ControlElementType | None = None,
        title: str | None = None,
        default_value: str | Sequence[str] | bool | DateInterval | RelativeDateInterval | None = None,
        multiselect: bool = False,
        is_range: bool = False,
        options: Sequence[str | tuple[str, str] | Mapping[str, str]] | None = None,
        operation: SelectorOperation | None = None,
        required: bool = False,
        show_title: bool = True,
        title_placement: SelectorTitlePlacement = "left",
        inner_title: str | None = None,
        hint: str | None = None,
        affects: Affects = "as_group",
    ) -> Self:
        """Append a dataset or manual selector to an existing group_control.

        The wrapper's settings and layout stay untouched. Shared wrappers are
        patched in every tab where they occur, and the new member is indexed
        immediately for later wiring operations in this builder chain.
        """
        item_type = self._item_types.get(group_item_id)
        if group_item_id not in self._item_occurrences:
            raise DatalensValidationError(f"Unknown item id {group_item_id!r}")
        if item_type != "group_control":
            raise DatalensValidationError(f"Item {group_item_id!r} of type {item_type!r} is not a group_control")
        if not isinstance(item_id, str) or not item_id:
            raise DatalensValidationError(f"item_id must be a non-empty string, got {item_id!r}")
        if isinstance(affects, tuple):
            known_tabs = {entry.tab_id for entry in self._tabs}
            unknown = sorted(set(affects) - known_tabs)
            if unknown:
                raise DatalensValidationError(f"Selector {item_id!r} references unknown tab ids {unknown!r}")

        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_selector(
            group="__append__",
            item_id=item_id,
            dataset=dataset,
            field=field,
            param_name=param_name,
            element=element,
            title=title,
            default_value=default_value,
            multiselect=multiselect,
            is_range=is_range,
            options=options,
            operation=operation,
            required=required,
            show_title=show_title,
            title_placement=title_placement,
            inner_title=inner_title,
            hint=hint,
            affects=affects,
        )
        (member,) = staged._pending_groups["__append__"]
        pending_ids = {
            pending.id
            for pending_members in self._pending_update_groups.values()
            for pending in pending_members
            if pending.id
        }
        if item_id in pending_ids:
            raise DatalensValidationError(f"Duplicate item id {item_id!r}")
        self._id_allocator.claim(_ITEM_NAMESPACE, item_id)

        self._ops.append(AddSelectorMemberOp(item_id=group_item_id, member=member))
        self._item_group_children.setdefault(group_item_id, set()).add(item_id)
        for occurrence in self._item_occurrences[group_item_id]:
            self._tab_index(occurrence.tab_id).control_child_ids.add(item_id)
        return self
