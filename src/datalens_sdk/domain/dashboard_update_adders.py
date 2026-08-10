"""Structural add_* mixin of the dashboard update builder (epic D3.3).

New tabs and items are staged through the SAME snapshot helpers the create
builder uses (:func:`_snapshot_tab` / :func:`_snapshot_items`), so the wire
shape has a single source of truth. The id allocator is lazily seeded with
every id already present in the raw document, so staged auto-ids can never
collide with server-side ones.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from typing_extensions import Self

from datalens_sdk.domain.dashboard_create import (
    _ITEM_NAMESPACE,
    _TAB_NAMESPACE,
    _WIDGET_TAB_NAMESPACE,
    _DashboardIdAllocator,
    _snapshot_items,
    _snapshot_tab,
)
from datalens_sdk.domain.dashboard_layout import DEFAULT_ITEM_SIZES, Position
from datalens_sdk.domain.dashboard_tab import DashboardTab
from datalens_sdk.domain.dashboard_tab_charts import DashboardChartParams, DashboardChartTab
from datalens_sdk.domain.dashboard_tab_layout import _validated_size
from datalens_sdk.domain.dashboard_tab_layout import validated_at as _validated_at
from datalens_sdk.domain.dashboard_types import (
    DEFAULT_TEXT_BACKGROUND,
    Affects,
    ControlElementType,
    DashboardTitleSize,
    DateInterval,
    PinZone,
    RelativeDateInterval,
    SelectorOperation,
    SelectorTitlePlacement,
    ShowOnTabs,
    ThemedColor,
    validate_border_radius,
)
from datalens_sdk.domain.dashboard_update_support import (
    _GLOBAL_ITEMS_FIELD,
    _ITEMS_FIELD,
    _SPEC_ITEM_TYPES,
    _STAGED_TAB_TITLE,
    _ItemOccurrence,
    _iter_mappings,
    _mapping_or_none,
    _string_or_none,
    _TabIndex,
)
from datalens_sdk.domain.specs.dashboard import (
    AddGroupSelectorOp,
    AddItemsOp,
    AddTabOp,
    AutoLayoutItemSpec,
    DashboardItemSpec,
    GroupControlItem,
    LayoutItemSpec,
    SelectorMemberSpec,
    WidgetItem,
)
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.editor_chart import EditorChart
    from datalens_sdk.domain.fields import FieldLike
    from datalens_sdk.domain.specs.dashboard import DashboardUpdateOp
    from datalens_sdk.domain.wizard_chart import WizardChart


class _StructuralAddersMixin:
    """add_tab / add_* methods shared into :class:`DashboardUpdate`."""

    if TYPE_CHECKING:
        _data: dict[str, object]
        _installation: str
        _ops: list[DashboardUpdateOp]
        _tabs: list[_TabIndex]
        _item_occurrences: dict[str, list[_ItemOccurrence]]
        _item_types: dict[str, str | None]
        _item_widget_tab_ids: dict[str, set[str]]
        _item_group_children: dict[str, set[str]]
        _all_tabs_shared_ids: set[str]
        _pending_update_groups: dict[str, list[SelectorMemberSpec]]
        _allocator: _DashboardIdAllocator | None

        def _resolve_tab(self, ref: str) -> str: ...

        def _tab_index(self, tab_id: str) -> _TabIndex: ...

    @property
    def _id_allocator(self) -> _DashboardIdAllocator:
        """Lazily seeded with every raw document id so staged auto-ids cannot
        collide. ``reserve`` is idempotent for replicated global items."""
        allocator = self._allocator
        if allocator is None:
            allocator = _DashboardIdAllocator()
            for tab in _iter_mappings(self._data.get("tabs")):
                tab_id = _string_or_none(tab.get("id"))
                if tab_id is not None:
                    allocator.reserve(_TAB_NAMESPACE, (tab_id,))
                item_ids: set[str] = set()
                for container in (_ITEMS_FIELD, _GLOBAL_ITEMS_FIELD):
                    for item in _iter_mappings(tab.get(container)):
                        item_id = _string_or_none(item.get("id"))
                        if item_id is not None:
                            item_ids.add(item_id)
                        item_data = _mapping_or_none(item.get("data")) or {}
                        for widget_tab in _iter_mappings(item_data.get("tabs")):
                            widget_tab_id = _string_or_none(widget_tab.get("id"))
                            if widget_tab_id is not None:
                                allocator.reserve(_WIDGET_TAB_NAMESPACE, (widget_tab_id,))
                        for child in _iter_mappings(item_data.get("group")):
                            child_id = _string_or_none(child.get("id"))
                            if child_id is not None:
                                item_ids.add(child_id)
                for layout_entry in _iter_mappings(tab.get("layout")):
                    layout_id = _string_or_none(layout_entry.get("i"))
                    if layout_id is not None:
                        item_ids.add(layout_id)
                allocator.reserve(_ITEM_NAMESPACE, item_ids)
            self._allocator = allocator
        return allocator

    def _register_added_items(
        self,
        tab_index: _TabIndex,
        items: tuple[DashboardItemSpec, ...],
    ) -> None:
        for item in items:
            self._item_types.setdefault(item.id, _SPEC_ITEM_TYPES[type(item)])
            if isinstance(item, GroupControlItem):
                self._register_added_group(tab_index, item)
                continue
            tab_index.item_ids.add(item.id)
            self._item_occurrences.setdefault(item.id, []).append(
                _ItemOccurrence(tab_id=tab_index.tab_id, container=_ITEMS_FIELD)
            )
            if isinstance(item, WidgetItem):
                for widget_tab in item.tabs:
                    tab_index.widget_tab_ids.add(widget_tab.id)
                    self._item_widget_tab_ids.setdefault(item.id, set()).add(widget_tab.id)

    def _register_added_group(self, tab_index: _TabIndex, item: GroupControlItem) -> None:
        """Index a builder-added group_control: member ids become addressable
        (update_selector/remove_selector/connections in the same builder), and
        a shared group occurs in globalItems of its TARGET tabs — mirroring
        what the applier emits."""
        children = {member.id for member in item.members}
        self._item_group_children[item.id] = children
        if item.show_on_tabs == "all":
            self._all_tabs_shared_ids.add(item.id)
        if item.show_on_tabs == "current":
            targets = [tab_index]
        elif item.show_on_tabs == "all":
            targets = list(self._tabs)
        else:
            # show_on_tabs targets are tab IDS (not titles) — same contract
            # the applier enforces
            targets = [self._tab_index(tab_ref) for tab_ref in item.show_on_tabs]
        container = _ITEMS_FIELD if item.show_on_tabs == "current" else _GLOBAL_ITEMS_FIELD
        for target in targets:
            target.item_ids.add(item.id)
            target.control_child_ids.update(children)
            self._item_occurrences.setdefault(item.id, []).append(
                _ItemOccurrence(tab_id=target.tab_id, container=container)
            )

    def add_tab(self, tab: DashboardTab) -> Self:
        """Append a NEW tab snapshotted from a DashboardTab entity (the same
        form as on create; point-edits of EXISTING tabs go through
        ``update_tab``/item ops). The entity is never mutated and stays
        reusable; the fresh tab id is addressable by later ops here."""
        tab_spec = _snapshot_tab(tab, allocator=self._id_allocator, installation=self._installation, defer_auto=True)
        self._ops.append(AddTabOp(tab=tab_spec))
        tab_index = _TabIndex(tab_id=tab_spec.id, title=tab_spec.title)
        self._tabs.append(tab_index)
        self._register_added_items(tab_index, tab_spec.items)
        # existing allTabs shared selectors reach the new tab too (the applier
        # copies them into its globalItems): mirror that in the index
        for shared_id in sorted(self._all_tabs_shared_ids):
            if shared_id in tab_index.item_ids or shared_id not in self._item_occurrences:
                continue
            tab_index.item_ids.add(shared_id)
            tab_index.control_child_ids.update(self._item_group_children.get(shared_id, set()))
            self._item_occurrences[shared_id].append(
                _ItemOccurrence(tab_id=tab_index.tab_id, container=_GLOBAL_ITEMS_FIELD)
            )
        return self

    def _add_staged_items(self, tab: str, staged: DashboardTab) -> Self:
        tab_id = self._resolve_tab(tab)
        items, layout = _snapshot_items(
            staged, allocator=self._id_allocator, installation=self._installation, defer_auto=True
        )
        self._ops.append(AddItemsOp(tab_id=tab_id, items=items, layout=layout))
        self._register_added_items(self._tab_index(tab_id), items)
        return self

    def add_chart(
        self,
        chart: WizardChart | EditorChart | str,
        *,
        tab: str,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        title: str | None = None,
        item_id: str | None = None,
        params: DashboardChartParams | None = None,
        show_title: bool = True,
        auto_height: bool = False,
        background: str | ThemedColor | None = None,
        description: str | None = None,
        hint: str | None = None,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
        enable_action_params: bool = False,
    ) -> Self:
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_chart(
            chart,
            title=title,
            item_id=item_id,
            at=at,
            size=size,
            params=params,
            show_title=show_title,
            auto_height=auto_height,
            background=background,
            description=description,
            hint=hint,
            border_radius=border_radius,
            pinned=pinned,
            enable_action_params=enable_action_params,
        )
        return self._add_staged_items(tab, staged)

    def add_chart_group(
        self,
        charts: Sequence[DashboardChartTab],
        *,
        tab: str,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        item_id: str | None = None,
        show_title: bool = True,
        background: str | ThemedColor | None = None,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_chart_group(
            charts,
            item_id=item_id,
            at=at,
            size=size,
            show_title=show_title,
            background=background,
            border_radius=border_radius,
            pinned=pinned,
        )
        return self._add_staged_items(tab, staged)

    def add_title(
        self,
        text: str,
        *,
        tab: str,
        at: Position | tuple[int, int, int, int] | None = None,
        item_id: str | None = None,
        size: DashboardTitleSize = "m",
        show_in_toc: bool = False,
        text_color: str | ThemedColor | None = None,
        background: str | ThemedColor | None = None,
        hint: str | None = None,
        auto_height: bool = True,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_title(
            text,
            item_id=item_id,
            at=at,
            size=size,
            show_in_toc=show_in_toc,
            text_color=text_color,
            background=background,
            hint=hint,
            auto_height=auto_height,
            border_radius=border_radius,
            pinned=pinned,
        )
        return self._add_staged_items(tab, staged)

    def add_text(
        self,
        text: str,
        *,
        tab: str,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        item_id: str | None = None,
        background: str | ThemedColor | None = DEFAULT_TEXT_BACKGROUND,
        auto_height: bool = True,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_text(
            text,
            item_id=item_id,
            at=at,
            size=size,
            background=background,
            auto_height=auto_height,
            border_radius=border_radius,
            pinned=pinned,
        )
        return self._add_staged_items(tab, staged)

    def add_image(
        self,
        *,
        src: str,
        tab: str,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        alt: str | None = None,
        preserve_aspect_ratio: bool = True,
        item_id: str | None = None,
        background: str | ThemedColor | None = None,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_image(
            src=src,
            alt=alt,
            preserve_aspect_ratio=preserve_aspect_ratio,
            item_id=item_id,
            at=at,
            size=size,
            background=background,
            border_radius=border_radius,
            pinned=pinned,
        )
        return self._add_staged_items(tab, staged)

    def add_section_divider(
        self,
        text: str,
        *,
        tab: str,
        at: Position | tuple[int, int, int, int] | None = None,
        item_id: str | None = None,
        background: str | ThemedColor | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_section_divider(text, item_id=item_id, at=at, background=background, pinned=pinned)
        return self._add_staged_items(tab, staged)

    # -- selectors (epic D4) -----------------------------------------------------

    def add_selector(
        self,
        *,
        tab: str | None = None,
        group: str | None = None,
        item_id: str | None = None,
        dataset: Dataset | None = None,
        field: FieldLike | str | None = None,
        param_name: str | None = None,
        chart: WizardChart | EditorChart | str | None = None,
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
        show_on_tabs: ShowOnTabs = "current",
        affects: Affects = "as_group",
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        auto_height: bool = False,
    ) -> Self:
        """Update mirror of :meth:`DashboardTab.add_selector`: without ``group=``
        the selector lands immediately on ``tab`` as a single-member
        group_control; with ``group=`` the member registers on this builder for
        a later :meth:`add_group_selector` call (``tab`` belongs there)."""
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged.add_selector(
            item_id=item_id,
            dataset=dataset,
            field=field,
            param_name=param_name,
            chart=chart,
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
            show_on_tabs=show_on_tabs,
            affects=affects,
            group=group,
            at=at,
            size=size,
            auto_height=auto_height,
        )
        if group is not None:
            if tab is not None:
                raise DataLensValidationError("tab= belongs to add_group_selector when group= is used")
            members = staged._pending_groups[group]
            # no allocator reservation here: explicit member ids are CLAIMED
            # by the group assembly snapshot; duplicates are prechecked
            # against the document and every other pending member
            pending_ids = {
                member.id
                for pending_members in self._pending_update_groups.values()
                for member in pending_members
                if member.id
            }
            for member in members:
                if member.id and (self._id_allocator.is_used(_ITEM_NAMESPACE, member.id) or member.id in pending_ids):
                    raise DataLensValidationError(f"Duplicate item id {member.id!r}")
            self._pending_update_groups.setdefault(group, []).extend(members)
            return self
        if tab is None:
            raise DataLensValidationError("tab= is required for a standalone selector on update")
        return self._add_staged_items(tab, staged)

    def add_group_selector(
        self,
        *,
        group: str | None = None,
        tab: str,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        include: Sequence[str] = (),
        apply_button: bool = False,
        reset_button: bool = False,
        update_on_change: bool = True,
        show_group_name: bool = False,
        show_on_tabs: ShowOnTabs = "current",
        auto_height: bool | None = None,
        border_radius: int | None = None,
    ) -> Self:
        """Assemble a group_control on update from builder-registered members
        and/or EXISTING selectors of the dashboard (``include`` item ids).

        Absorbed selectors keep their member ids verbatim (connections stay
        intact); the absorbed wrappers and layout entries are removed. Shared
        selectors cannot be absorbed; ``show_on_tabs`` does not combine with
        ``include``. ``at=None`` auto-places the group full-width below the
        tab's content; ``auto_height`` defaults to True then (create parity)."""
        resolved_border_radius = validate_border_radius(border_radius)
        members = list(self._pending_update_groups.get(group, ())) if group is not None else []
        if group is not None and not members:
            known = sorted(self._pending_update_groups)
            hint = f" Known groups: {', '.join(known)}." if known else ""
            raise DataLensValidationError(
                f"Selector group {group!r} has no registered members; call add_selector(group=...) first.{hint}"
            )
        include_ids = tuple(self._resolved_absorb_ref(ref) for ref in include)
        if not members and not include_ids:
            raise DataLensValidationError("add_group_selector needs group= members and/or include= item ids")
        if include_ids and show_on_tabs != "current":
            raise DataLensValidationError("show_on_tabs sharing does not combine with include= absorption")
        if len(set(include_ids)) != len(include_ids):
            raise DataLensValidationError("include item ids must be unique")
        tab_id = self._resolve_tab(tab)
        for absorbed_id in include_ids:
            self._require_absorbable(absorbed_id, tab_id)
        staged = DashboardTab(_STAGED_TAB_TITLE)
        staged._pending_groups["__update__"] = members
        if not members:
            # an include-only group still needs the wrapper: stage a throwaway
            # member-less assembly is impossible, so build the wrapper spec here
            wrapper = GroupControlItem(
                id=item_id if item_id is not None else "",
                members=(),
                apply_button=apply_button,
                reset_button=reset_button,
                update_on_change=update_on_change,
                show_group_name=show_group_name,
                show_on_tabs=show_on_tabs,
                auto_height=auto_height if auto_height is not None else (at is None),
                border_radius=resolved_border_radius,
            )
            entry: LayoutItemSpec | AutoLayoutItemSpec
            if at is None:
                w, h = _validated_size(size) if size is not None else DEFAULT_ITEM_SIZES["group_control"]
                entry = AutoLayoutItemSpec(i="", w=w, h=h)
            else:
                if size is not None:
                    raise DataLensValidationError(
                        "size= applies to auto placement (at=None) only; put the size inside at=(x, y, w, h)"
                    )
                x, y, w, h = _validated_at(at)
                entry = LayoutItemSpec(i="", x=x, y=y, w=w, h=h)
            resolved_items, resolved_layout = self._resolved_group_items((wrapper,), (entry,), item_id)
        else:
            staged.add_group_selector(
                group="__update__",
                item_id=item_id,
                at=at,
                size=size,
                apply_button=apply_button,
                reset_button=reset_button,
                update_on_change=update_on_change,
                show_group_name=show_group_name,
                show_on_tabs=show_on_tabs,
                auto_height=auto_height,
                border_radius=border_radius,
            )
            # defer_auto keeps an at=None group as an AutoLayoutItemSpec so the
            # applier flows it below the target tab's content, like every adder
            resolved_items, resolved_layout = _snapshot_items(
                staged, allocator=self._id_allocator, installation=self._installation, defer_auto=True
            )
        if group is not None:
            del self._pending_update_groups[group]
        wrapper_item = resolved_items[0]
        assert isinstance(wrapper_item, GroupControlItem)
        if not include_ids:
            self._ops.append(AddItemsOp(tab_id=tab_id, items=resolved_items, layout=resolved_layout))
            # local AND shared groups are indexed here: _register_added_items
            # mirrors the applier's globalItems propagation for shared ones
            self._register_added_items(self._tab_index(tab_id), resolved_items)
            return self
        self._ops.append(
            AddGroupSelectorOp(
                tab_id=tab_id,
                item=wrapper_item,
                layout=resolved_layout[0],
                absorbed_item_ids=include_ids,
            )
        )
        self._absorb_into_index(tab_id, wrapper_item, include_ids)
        return self

    def _resolved_group_items(
        self,
        items: tuple[DashboardItemSpec, ...],
        layout: tuple[LayoutItemSpec | AutoLayoutItemSpec, ...],
        item_id: str | None,
    ) -> tuple[tuple[DashboardItemSpec, ...], tuple[LayoutItemSpec | AutoLayoutItemSpec, ...]]:
        """Assign the wrapper id for an include-only (member-less) group."""
        allocator = self._id_allocator
        if item_id is not None:
            wrapper_id = allocator.claim(_ITEM_NAMESPACE, item_id)
        else:
            wrapper_id = allocator.generate(_ITEM_NAMESPACE, "el_")
        wrapper = replace(items[0], id=wrapper_id)
        entry = replace(layout[0], i=wrapper_id)
        return (wrapper,), (entry,)

    def _resolved_absorb_ref(self, ref: str) -> str:
        """An include reference may be a member id (the selector identity):
        it resolves to its owning wrapper — absorbing a singleton by its
        member id is legal, extracting one member of a multi-member group is
        not."""
        if not ref or ref in self._item_occurrences:
            return ref
        for wrapper_id, children in self._item_group_children.items():
            if ref in children:
                if children == {ref}:
                    return wrapper_id
                raise DataLensValidationError(
                    f"Selector {ref!r} is one of several members of group {wrapper_id!r}; "
                    "absorb the whole group by its wrapper id instead"
                )
        return ref

    def _require_absorbable(self, absorbed_id: str, tab_id: str) -> None:
        if not absorbed_id:
            raise DataLensValidationError("include item ids must not be empty strings")
        occurrences = self._item_occurrences.get(absorbed_id)
        if not occurrences:
            raise DataLensValidationError(f"Unknown item id {absorbed_id!r}")
        item_type = self._item_types.get(absorbed_id)
        if item_type not in ("control", "group_control"):
            raise DataLensValidationError(f"Item {absorbed_id!r} of type {item_type!r} is not a selector")
        if len(occurrences) > 1 or occurrences[0].container == _GLOBAL_ITEMS_FIELD:
            raise DataLensValidationError(f"Shared selector {absorbed_id!r} cannot be absorbed into a group")
        if occurrences[0].tab_id != tab_id:
            raise DataLensValidationError(
                f"Item {absorbed_id!r} lives on tab {occurrences[0].tab_id!r}, not {tab_id!r}"
            )
        if self._raw_source_type(absorbed_id) == "external":
            raise DataLensValidationError(
                f"External selector {absorbed_id!r} cannot join a group (server schema, P017)"
            )

    def _raw_source_type(self, item_id: str) -> str | None:
        for raw_tab in _iter_mappings(self._data.get("tabs")):
            for container in (_ITEMS_FIELD, _GLOBAL_ITEMS_FIELD):
                for item in _iter_mappings(raw_tab.get(container)):
                    if item.get("id") == item_id:
                        item_data = _mapping_or_none(item.get("data")) or {}
                        return _string_or_none(item_data.get("sourceType"))
        return None

    def _absorb_into_index(
        self,
        tab_id: str,
        wrapper: GroupControlItem,
        absorbed_ids: tuple[str, ...],
    ) -> None:
        tab_index = self._tab_index(tab_id)
        children: set[str] = {member.id for member in wrapper.members}
        for absorbed_id in absorbed_ids:
            if self._item_types.get(absorbed_id) == "group_control":
                children.update(self._item_group_children.get(absorbed_id, set()))
            else:
                children.add(absorbed_id)
            # the absorbed wrapper stops existing as an item
            self._item_occurrences.pop(absorbed_id, None)
            self._item_types.pop(absorbed_id, None)
            self._item_group_children.pop(absorbed_id, None)
            tab_index.item_ids.discard(absorbed_id)
        tab_index.item_ids.add(wrapper.id)
        tab_index.control_child_ids.update(children)
        self._item_occurrences.setdefault(wrapper.id, []).append(_ItemOccurrence(tab_id=tab_id, container=_ITEMS_FIELD))
        self._item_types[wrapper.id] = "group_control"
        self._item_group_children[wrapper.id] = children
