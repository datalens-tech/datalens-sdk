"""Standalone dashboard tab entity (epic D2).

``DashboardTab`` mirrors the ``dataset.source`` pattern: it is built on its
own — no client, no factory — filled with items, and then attached to a
:class:`~datalens_sdk.domain.dashboard_create.DashboardCreate` via
``add_tab(tab)``. The attach snapshots the tab's content and assigns
deterministic ids from the builder's counters; the tab instance itself stays a
reusable template.

Everything checkable without document context is validated eagerly in the
``add_*`` methods; document-level checks (chart installation, cross-tab id
uniqueness) happen at attach time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import get_args

from typing_extensions import Self

from datalens_sdk.domain.dashboard_layout import Position
from datalens_sdk.domain.dashboard_tab_charts import (
    _PENDING_ID,
    DashboardChartParams,
    DashboardChartTab,
    _pending_widget_tabs,
    _resolve_chart_ref,
    _resolved_chart_tab,
)
from datalens_sdk.domain.dashboard_tab_layout import TabLayoutFlow, pin_parent, resolve_placement
from datalens_sdk.domain.dashboard_tab_layout import apply_layout as _apply_pending_layout
from datalens_sdk.domain.dashboard_tab_selectors import (
    _derived_selector_title,
    _normalized_show_on_tabs,
    _resolved_selector_source,
    _validated_member_scope,
    _validated_selector_default,
)
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
    validate_dashboard_color,
    validate_optional_text,
)
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.fields import FieldLike
from datalens_sdk.domain.specs.dashboard import (
    DashboardItemSpec,
    ExternalControlItem,
    GroupControlItem,
    ImageItem,
    SelectorMemberSpec,
    TextItem,
    TitleItem,
    WidgetItem,
)
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError

__all__ = ["DashboardChartTab", "DashboardTab"]


@dataclass(frozen=True, slots=True)
class _PendingItem:
    """One tab item awaiting attach: spec payload with the sentinel id plus
    the non-spec context the builder needs (placement, pinning, and the
    installation of every referenced chart — WidgetTabSpec does not carry it).
    """

    item: DashboardItemSpec
    explicit_id: str | None
    placement: tuple[int, int, int, int]
    parent: str | None  # wire layout.parent: pin zone or None (default flow)
    chart_installations: tuple[str, ...] = ()
    auto: bool = False
    # flow markers replayed by update-side deferred resolution: start_row()/space()
    # (new_row/gap) and the explicit divider's absolute y floor
    new_row: bool = False
    gap: int = 0
    floor: int = 0


def _validated_color(value: str | ThemedColor | None, *, field_name: str) -> str | ThemedColor | None:
    if value is None:
        return None
    return validate_dashboard_color(value, field=field_name)


@dataclass(slots=True)
class DashboardTab(TabLayoutFlow):
    """A dashboard tab built standalone and attached via ``add_tab(tab)``.

    Item ids are assigned by the builder at attach time; pass an explicit
    ``item_id=`` when a stable handle is needed (e.g. for future
    connections). The tab is a reusable template: attaching it never mutates
    it, and later mutations do not affect builders it was attached to.
    """

    title: str
    tab_id: str | None = field(default=None, kw_only=True)
    hidden: bool = field(default=False, kw_only=True)
    _pending: list[_PendingItem] = field(default_factory=list, init=False, repr=False)
    _explicit_item_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _pending_groups: dict[str, list[SelectorMemberSpec]] = field(default_factory=dict, init=False, repr=False)
    _pending_connections: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    _pending_aliases: list[tuple[str, ...]] = field(default_factory=list, init=False, repr=False)
    _cursors: dict[str | None, tuple[int, int, int]] = field(default_factory=dict, init=False, repr=False)
    _pending_breaks: dict[str | None, tuple[bool, int, int]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.title:
            raise DataLensValidationError("Tab title must not be an empty string")
        if self.tab_id is not None and not self.tab_id:
            raise DataLensValidationError("tab id must not be an empty string")

    def _pending_snapshot(self) -> tuple[_PendingItem, ...]:
        """Package-internal seam: builders consume the tab through this snapshot."""
        return tuple(self._pending)

    # every add_* validates ALL inputs before touching tab state

    def _validated_item_id(self, item_id: str | None) -> str | None:
        if item_id is None:
            return None
        if not item_id:
            raise DataLensValidationError("item id must not be an empty string")
        if item_id in self._explicit_item_ids:
            raise DataLensValidationError(f"Duplicate item id {item_id!r}")
        return item_id

    def _append(
        self,
        item: DashboardItemSpec,
        *,
        explicit_id: str | None,
        placement: tuple[int, int, int, int],
        pinned: bool | PinZone,
        chart_installations: tuple[str, ...] = (),
        auto: bool = False,
    ) -> Self:
        # an auto item consumes the pending start_row()/space()/divider marker of its group
        group = pin_parent(pinned)
        new_row, gap, floor = self._pending_breaks.pop(group, (False, 0, 0)) if auto else (False, 0, 0)
        self._pending.append(
            _PendingItem(
                item=item,
                explicit_id=explicit_id,
                placement=placement,
                parent=group,
                chart_installations=chart_installations,
                auto=auto,
                new_row=new_row,
                gap=gap,
                floor=floor,
            )
        )
        if explicit_id is not None:
            self._explicit_item_ids.add(explicit_id)
        return self

    def apply_layout(self, layout: Mapping[str, Position | tuple[int, int, int, int]]) -> Self:
        """Reposition already-added items by explicit ``item_id`` (partial patch;
        unknown ids fail loud), e.g. a mapping from :meth:`Layout.row`."""
        self._pending[:] = _apply_pending_layout(self._pending, layout)
        return self

    # -- items -----------------------------------------------------------------

    def add_chart(
        self,
        chart: WizardChart | EditorChart | str,
        *,
        title: str | None = None,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
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
        explicit_id = self._validated_item_id(item_id)
        resolved = _resolved_chart_tab(
            chart,
            title=title,
            params=params,
            description=description,
            hint=hint,
            auto_height=auto_height,
            is_default=True,
            enable_action_params=enable_action_params,
        )
        item = WidgetItem(
            id=_PENDING_ID,
            tabs=_pending_widget_tabs((resolved,)),
            show_title=show_title,
            background=_validated_color(background, field_name="background"),
            border_radius=validate_border_radius(border_radius),
        )
        placement = resolve_placement(self._cursors, at, item_type="widget", pinned=pinned, size=size)
        return self._append(
            item,
            explicit_id=explicit_id,
            placement=placement,
            pinned=pinned,
            auto=at is None,
            chart_installations=(resolved.installation,),
        )

    def add_chart_group(
        self,
        charts: Sequence[DashboardChartTab],
        *,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        show_title: bool = True,
        background: str | ThemedColor | None = None,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        entries = tuple(charts)
        if not entries:
            raise DataLensValidationError("add_chart_group requires at least one chart")
        marked = [index for index, entry in enumerate(entries) if entry.default]
        if len(marked) > 1:
            raise DataLensValidationError("add_chart_group allows exactly one chart marked default=True")
        default_index = marked[0] if marked else 0
        explicit_id = self._validated_item_id(item_id)
        resolved = tuple(
            _resolved_chart_tab(
                entry.chart,
                title=entry.title,
                params=entry.params,
                description=entry.description,
                hint=entry.hint,
                auto_height=entry.auto_height,
                is_default=index == default_index,
                enable_action_params=entry.enable_action_params,
            )
            for index, entry in enumerate(entries)
        )
        item = WidgetItem(
            id=_PENDING_ID,
            tabs=_pending_widget_tabs(resolved),
            show_title=show_title,
            background=_validated_color(background, field_name="background"),
            border_radius=validate_border_radius(border_radius),
        )
        placement = resolve_placement(self._cursors, at, item_type="widget", pinned=pinned, size=size)
        return self._append(
            item,
            explicit_id=explicit_id,
            placement=placement,
            pinned=pinned,
            auto=at is None,
            chart_installations=tuple(entry.installation for entry in resolved),
        )

    def add_title(
        self,
        text: str,
        *,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: DashboardTitleSize = "m",
        show_in_toc: bool = False,
        text_color: str | ThemedColor | None = None,
        background: str | ThemedColor | None = None,
        hint: str | None = None,
        auto_height: bool = True,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        """``size`` is the heading size ("xs".."l") — the name predates the
        layout ``size=(w, h)`` the other adders take, so custom title geometry
        goes through explicit ``at=(x, y, w, h)`` instead."""
        if not text:
            raise DataLensValidationError("Title text must not be an empty string")
        if size not in get_args(DashboardTitleSize):
            raise DataLensValidationError(f"Unknown title size {size!r}")
        explicit_id = self._validated_item_id(item_id)
        item = TitleItem(
            id=_PENDING_ID,
            text=text,
            size=size,
            show_in_toc=show_in_toc,
            text_color=_validated_color(text_color, field_name="text_color"),
            background=_validated_color(background, field_name="background"),
            hint=validate_optional_text(hint, field="hint"),
            auto_height=auto_height,
            border_radius=validate_border_radius(border_radius),
        )
        placement = resolve_placement(self._cursors, at, item_type="title", pinned=pinned)
        return self._append(item, explicit_id=explicit_id, placement=placement, pinned=pinned, auto=at is None)

    def add_text(
        self,
        text: str,
        *,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        background: str | ThemedColor | None = DEFAULT_TEXT_BACKGROUND,
        auto_height: bool = True,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        if not text:
            raise DataLensValidationError("Text must not be an empty string")
        explicit_id = self._validated_item_id(item_id)
        item = TextItem(
            id=_PENDING_ID,
            text=text,
            auto_height=auto_height,
            background=_validated_color(background, field_name="background"),
            border_radius=validate_border_radius(border_radius),
        )
        placement = resolve_placement(self._cursors, at, item_type="text", pinned=pinned, size=size)
        return self._append(item, explicit_id=explicit_id, placement=placement, pinned=pinned, auto=at is None)

    def add_image(
        self,
        *,
        src: str,
        alt: str | None = None,
        preserve_aspect_ratio: bool = True,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        background: str | ThemedColor | None = None,
        border_radius: int | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        if not src:
            raise DataLensValidationError("Image src must not be an empty string")
        explicit_id = self._validated_item_id(item_id)
        item = ImageItem(
            id=_PENDING_ID,
            src=src,
            alt=alt,
            preserve_aspect_ratio=preserve_aspect_ratio,
            background=_validated_color(background, field_name="background"),
            border_radius=validate_border_radius(border_radius),
        )
        placement = resolve_placement(self._cursors, at, item_type="image", pinned=pinned, size=size)
        return self._append(item, explicit_id=explicit_id, placement=placement, pinned=pinned, auto=at is None)

    def add_section_divider(
        self,
        text: str,
        *,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        background: str | ThemedColor | None = None,
        pinned: bool | PinZone = False,
    ) -> Self:
        self.add_title(
            text,
            item_id=item_id,
            at=at,
            size="l",
            show_in_toc=True,
            background=background,
            pinned=pinned,
        )
        self._register_divider_flow(self._pending[-1], pinned=pinned)
        return self

    # -- selectors (epic D4) ---------------------------------------------------

    def add_selector(
        self,
        *,
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
        group: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        auto_height: bool = False,
    ) -> Self:
        """Add one selector; without ``group=`` it lands as a single-member
        group_control, with ``group=`` it registers for :meth:`add_group_selector`.

        ``item_id`` names the selector MEMBER — the logical identity used by
        update operations and connections; the wrapper item id is generated.
        No explicit ``operation`` emits none (the live API filters fine, P016).
        ``affects`` is the per-member INFLUENCE axis (see :data:`Affects`);
        display stays group-level ``show_on_tabs``. ``chart=`` makes an EXTERNAL
        selector — standalone ``control`` items only (P017), so ``item_id``
        names the item itself and group/element/value options do not apply."""
        member_id = self._validated_item_id(item_id)
        if chart is not None:
            return self._add_external_selector(
                chart,
                member_id=member_id,
                title=title,
                at=at,
                size=size,
                forbidden={
                    "dataset": dataset,
                    "field": field,
                    "param_name": param_name,
                    "element": element,
                    "default_value": default_value,
                    "multiselect": multiselect or None,
                    "is_range": is_range or None,
                    "options": options,
                    "operation": operation,
                    "required": required or None,
                    "inner_title": inner_title,
                    "hint": hint,
                    "group": group,
                    "auto_height": auto_height or None,
                    "affects": affects if affects != "as_group" else None,
                },
                show_on_tabs=show_on_tabs,
            )
        effective_element: ControlElementType = element if element is not None else "select"
        source, auto_title = _resolved_selector_source(
            dataset=dataset,
            field=field,
            param_name=param_name,
            element=effective_element,
            multiselect=multiselect,
            is_range=is_range,
            options=options,
            operation=operation,
            required=required,
        )
        resolved_title = _derived_selector_title(title, auto_title=auto_title)
        normalized_default = _validated_selector_default(default_value, element=effective_element)
        member_show_on_tabs, member_affects = _validated_member_scope(
            group=group, show_on_tabs=show_on_tabs, affects=affects
        )
        if group is not None:
            if at is not None or size is not None:
                raise DataLensValidationError("at=/size= belong to add_group_selector when group= is used")
            if auto_height:
                raise DataLensValidationError("auto_height belongs to add_group_selector when group= is used")
        member = SelectorMemberSpec(
            id=member_id if member_id is not None else _PENDING_ID,
            title=resolved_title,
            source=source,
            default_value=normalized_default,
            show_title=show_title,
            title_placement=title_placement,
            inner_title=validate_optional_text(inner_title, field="inner_title"),
            hint=validate_optional_text(hint, field="hint"),
            affects=member_affects if group is not None else "as_group",
        )
        if group is not None:
            self._pending_groups.setdefault(group, []).append(member)
            if member_id is not None:
                self._explicit_item_ids.add(member_id)
            return self
        # a standalone selector IS its singleton group (show_on_tabs = group setting)
        placement = resolve_placement(self._cursors, at, item_type="control", pinned=False, size=size)
        wrapper = GroupControlItem(
            id=_PENDING_ID,
            members=(member,),
            show_on_tabs=member_show_on_tabs,
            auto_height=auto_height,
        )
        self._append(wrapper, explicit_id=None, placement=placement, pinned=False, auto=at is None)
        if member_id is not None:
            self._explicit_item_ids.add(member_id)
        return self

    def add_group_selector(
        self,
        *,
        group: str,
        item_id: str | None = None,
        at: Position | tuple[int, int, int, int] | None = None,
        size: tuple[int, int] | None = None,
        apply_button: bool = False,
        reset_button: bool = False,
        update_on_change: bool = True,
        show_group_name: bool = False,
        show_on_tabs: ShowOnTabs = "current",
        auto_height: bool | None = None,
        border_radius: int | None = None,
    ) -> Self:
        """Assemble the selectors registered via ``add_selector(group=...)`` into
        one group_control. ``item_id`` names the WRAPPER; members keep their
        ``add_selector`` ids and render side by side (``placementMode="auto"``,
        P018). ``at=None`` auto-places the group full-width; ``auto_height``
        defaults to True when auto-placed, False otherwise."""
        if not group:
            raise DataLensValidationError("group must not be an empty string")
        members = self._pending_groups.get(group)
        if not members:
            known = sorted(self._pending_groups)
            hint = f" Known groups: {', '.join(known)}." if known else ""
            raise DataLensValidationError(
                f"Selector group {group!r} has no registered members; call add_selector(group={group!r}) first.{hint}"
            )
        wrapper_id = self._validated_item_id(item_id)
        group_show_on_tabs = _normalized_show_on_tabs(show_on_tabs)
        effective_auto_height = auto_height if auto_height is not None else (at is None)
        wrapper = GroupControlItem(
            id=_PENDING_ID,
            members=tuple(members),
            apply_button=apply_button,
            reset_button=reset_button,
            update_on_change=update_on_change,
            show_group_name=show_group_name,
            show_on_tabs=group_show_on_tabs,
            auto_height=effective_auto_height,
            border_radius=validate_border_radius(border_radius),
        )
        placement = resolve_placement(self._cursors, at, item_type="group_control", pinned=False, size=size)
        self._append(wrapper, explicit_id=wrapper_id, placement=placement, pinned=False, auto=at is None)
        del self._pending_groups[group]
        return self

    def _add_external_selector(
        self,
        chart: WizardChart | EditorChart | str,
        *,
        member_id: str | None,
        title: str | None,
        at: Position | tuple[int, int, int, int] | None,
        size: tuple[int, int] | None,
        forbidden: Mapping[str, object],
        show_on_tabs: ShowOnTabs,
    ) -> Self:
        offending = sorted(name for name, value in forbidden.items() if value is not None)
        if offending:
            raise DataLensValidationError(f"chart= (external selector) does not combine with: {', '.join(offending)}")
        if show_on_tabs != "current":
            raise DataLensValidationError("show_on_tabs sharing is not supported for external selectors")
        chart_id, resolved_title, installation = _resolve_chart_ref(chart, title=title)
        item = ExternalControlItem(id=_PENDING_ID, title=resolved_title, chart_id=chart_id)
        placement = resolve_placement(self._cursors, at, item_type="control", pinned=False, size=size)
        return self._append(
            item,
            explicit_id=member_id,
            placement=placement,
            pinned=False,
            chart_installations=(installation,),
            auto=at is None,
        )

    def _unclaimed_group_names(self) -> tuple[str, ...]:
        """Package-internal seam: selector groups registered via
        ``add_selector(group=...)`` but never assembled."""
        return tuple(self._pending_groups)

    # -- connections and aliases (epic D4) ---------------------------------------
    #
    # References here are LOGICAL item ids (explicit item_id= values); the
    # snapshot translates them into wire endpoints — selector member ids and
    # widget chart-tab ids, the only endpoints the server accepts (P019).

    def add_connection(self, *, from_item: str, to_item: str, mutual: bool = False) -> Self:
        """Add a directed ignore edge: ``from_item`` stops RECEIVING
        ``to_item``'s parameters (live-verified direction, P019).

        To stop a selector filtering a widget pass the WIDGET as
        ``from_item`` — or use ``mutual=True`` / :meth:`disconnect_all` for a
        guaranteed full break in both directions (the safe default pattern).
        An empty ``connections`` list means a full broadcast mesh: ignore
        edges subtract from it, they never "connect" anything.
        """
        for name, value in (("from_item", from_item), ("to_item", to_item)):
            if not value:
                raise DataLensValidationError(f"{name} must not be an empty string")
        if from_item == to_item:
            raise DataLensValidationError("from_item and to_item must differ")
        pairs = [(from_item, to_item)]
        if mutual:
            pairs.append((to_item, from_item))
        for pair in pairs:
            if pair not in self._pending_connections:  # idempotent (taxi canon)
                self._pending_connections.append(pair)
        return self

    def disconnect_all(self, *item_ids: str) -> Self:
        """Fully sever every pair among ``item_ids``: the full N·(N-1) mesh
        of directed ignore edges (both directions per pair)."""
        if len(item_ids) < 2:
            raise DataLensValidationError("disconnect_all needs at least two item ids")
        if len(set(item_ids)) != len(item_ids):
            raise DataLensValidationError("disconnect_all item ids must be unique")
        for item_id in item_ids:
            if not item_id:
                raise DataLensValidationError("item ids must not be empty strings")
        for source in item_ids:
            for target in item_ids:
                if source != target and (source, target) not in self._pending_connections:
                    self._pending_connections.append((source, target))
        return self

    def add_alias(self, *fields: str) -> Self:
        """Declare ≥2 dataset field guids equivalent (one alias group);
        repeated groups (any order) are deduplicated silently."""
        if len(fields) < 2:
            raise DataLensValidationError("add_alias needs at least two field guids")
        if not all(isinstance(entry, str) and entry for entry in fields):
            raise DataLensValidationError(f"alias fields must be non-empty strings, got {fields!r}")
        if len(set(fields)) != len(fields):
            raise DataLensValidationError("alias fields must be unique")
        group = tuple(fields)
        if not any(frozenset(existing) == frozenset(group) for existing in self._pending_aliases):
            self._pending_aliases.append(group)
        return self

    def _pending_wiring_snapshot(self) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, ...], ...]]:
        """Package-internal seam: (connections as logical id pairs, alias groups)."""
        return tuple(self._pending_connections), tuple(self._pending_aliases)
