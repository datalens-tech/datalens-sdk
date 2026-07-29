"""Frozen dashboard-create/update specs — the domain↔converter read contract.

Note: ``params`` mappings are ``MappingProxyType`` (immutability over
copyability): specs are not ``copy.deepcopy``/``dataclasses.asdict``/pickle
safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from datalens_sdk.domain.dashboard_types import (
    Affects,
    ControlElementType,
    DashboardLoadPriority,
    DashboardTitleSize,
    SelectorDefaultValue,
    SelectorOperation,
    SelectorPlacementMode,
    SelectorTitlePlacement,
    ShowOnTabs,
    ThemedColor,
    _RemoveParam,
)
from datalens_sdk.domain.entry_location import EntryLocation

__all__ = [
    "AddAliasOp",
    "AddConnectionOp",
    "AddGroupSelectorOp",
    "AddItemsOp",
    "AddTabOp",
    "ApplyLayoutOp",
    "AutoLayoutItemSpec",
    "CompactLayoutOp",
    "ConnectionSpec",
    "DashboardCreateSpec",
    "DashboardItemSpec",
    "DashboardSettingsSpec",
    "DashboardUpdateOp",
    "DashboardUpdateSpec",
    "DatasetSelectorSource",
    "ExternalControlItem",
    "GlobalParamsOp",
    "GroupControlItem",
    "ImageItem",
    "LayoutItemSpec",
    "ManualSelectorSource",
    "MoveItemOp",
    "PinItemOp",
    "RemoveAliasOp",
    "RemoveConnectionOp",
    "RemoveItemOp",
    "RemoveSelectorMemberOp",
    "RemoveTabOp",
    "ReorderTabsOp",
    "ReplaceChartOp",
    "ResizeItemOp",
    "SelectorMemberSpec",
    "SelectorSourceSpec",
    "SetChartParamsOp",
    "ShiftBelowOp",
    "SwapItemsOp",
    "TabSpec",
    "TextItem",
    "TitleItem",
    "UnpinItemOp",
    "UpdateSelectorOp",
    "UpdateTabOp",
    "WidgetItem",
    "WidgetTabSpec",
]


@dataclass(frozen=True, slots=True)
class LayoutItemSpec:
    """Grid placement of one dashboard item; ``i`` is the item id."""

    i: str
    x: int
    y: int
    w: int
    h: int
    parent: str | None = None


@dataclass(frozen=True, slots=True)
class AutoLayoutItemSpec:
    """A deferred placement for an ``at=None`` item added to an EXISTING tab on
    update: only the size is known at build time; ``x``/``y`` resolve at apply
    time below the tab's current content in the item's pin-group."""

    i: str
    w: int
    h: int
    parent: str | None = None
    # flow markers from start_row()/space(): break the row (and leave ``gap``
    # empty rows) before placing this item
    new_row: bool = False
    gap: int = 0
    # absolute y floor from an explicit-at section divider: its cursor effect
    # ("the next auto starts below me") must survive deferred resolution, so
    # the item lands at y >= floor even though concrete entries never move
    # the resolver's cursor
    floor: int = 0


@dataclass(frozen=True, slots=True)
class WidgetTabSpec:
    """One chart tab inside a widget item."""

    id: str
    chart_id: str
    title: str
    is_default: bool
    params: Mapping[str, tuple[str, ...]]
    auto_height: bool = False
    description: str | None = None
    hint: str | None = None
    enable_action_params: bool = False


@dataclass(frozen=True, slots=True)
class WidgetItem:
    id: str
    tabs: tuple[WidgetTabSpec, ...]
    show_title: bool = True
    background: str | ThemedColor | None = None
    border_radius: int | None = None


@dataclass(frozen=True, slots=True)
class TextItem:
    id: str
    text: str
    auto_height: bool = True
    background: str | ThemedColor | None = None
    border_radius: int | None = None


@dataclass(frozen=True, slots=True)
class TitleItem:
    id: str
    text: str
    size: DashboardTitleSize = "m"
    show_in_toc: bool = False
    text_color: str | ThemedColor | None = None
    background: str | ThemedColor | None = None
    hint: str | None = None
    auto_height: bool = True
    border_radius: int | None = None


@dataclass(frozen=True, slots=True)
class ImageItem:
    id: str
    src: str
    alt: str | None = None
    preserve_aspect_ratio: bool = True
    background: str | ThemedColor | None = None
    border_radius: int | None = None


# -- selector specs (epic D4) -----------------------------------------------
#
# A single dataset/manual selector is always emitted as a group_control with
# one member (user decision 2026-07-21). Standalone `control` items are
# read-only legacy EXCEPT external selectors: the server forbids external
# group members, so those are written standalone (P017).


@dataclass(frozen=True, slots=True)
class DatasetSelectorSource:
    """Selector backed by a dataset field (wire ``sourceType="dataset"``)."""

    dataset_id: str
    field_guid: str
    field_type: str
    dataset_field_type: str = "DIMENSION"
    element: ControlElementType = "select"
    multiselect: bool = False
    is_range: bool = False
    operation: SelectorOperation | None = None
    required: bool = False


@dataclass(frozen=True, slots=True)
class ManualSelectorSource:
    """Selector over a manual parameter (wire ``sourceType="manual"``);
    ``options`` are (value, title) pairs and apply to select elements only."""

    param_name: str
    element: ControlElementType = "select"
    options: tuple[tuple[str, str], ...] = ()
    multiselect: bool = False
    is_range: bool = False
    operation: SelectorOperation | None = None
    required: bool = False


SelectorSourceSpec: TypeAlias = "DatasetSelectorSource | ManualSelectorSource"


@dataclass(frozen=True, slots=True)
class SelectorMemberSpec:
    """One selector inside a group_control (``data.group[]`` entry)."""

    id: str
    title: str
    source: SelectorSourceSpec
    default_value: SelectorDefaultValue | None = None
    show_title: bool = True
    title_placement: SelectorTitlePlacement = "left"
    inner_title: str | None = None
    hint: str | None = None
    placement_mode: SelectorPlacementMode = "auto"
    width: str = ""
    affects: Affects = "as_group"


@dataclass(frozen=True, slots=True)
class ExternalControlItem:
    """A standalone ``control`` item with an external chart source.

    The server forbids ``sourceType="external"`` inside group_control members,
    so an external selector is its own item — ``id`` IS the selector identity.
    """

    id: str
    title: str
    chart_id: str


@dataclass(frozen=True, slots=True)
class GroupControlItem:
    """A group_control item: one or more selector members plus group chrome.

    ``id`` is the wrapper item id; member ids live on the members.
    """

    id: str
    members: tuple[SelectorMemberSpec, ...]
    apply_button: bool = False
    reset_button: bool = False
    update_on_change: bool = True
    show_group_name: bool = False
    show_on_tabs: ShowOnTabs = "current"
    auto_height: bool = False
    border_radius: int | None = None


DashboardItemSpec: TypeAlias = "WidgetItem | TextItem | TitleItem | ImageItem | GroupControlItem | ExternalControlItem"


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    """One directed ignore edge: ``from_id`` stops receiving
    ``to_id``'s parameters. The implicit empty-connections state is a full
    broadcast mesh and ignore edges subtract from it.
    """

    from_id: str
    to_id: str


@dataclass(frozen=True, slots=True)
class TabSpec:
    """One dashboard tab: items, their grid layout, ignore edges and field
    alias groups (``aliases`` entries are ≥2 field guids each)."""

    id: str
    title: str
    items: tuple[DashboardItemSpec, ...]
    # a new tab added on update may carry deferred (at=None) auto entries, resolved
    # per target at apply time; on create the layout is always concrete
    layout: tuple[LayoutItemSpec | AutoLayoutItemSpec, ...]
    hidden: bool = False
    connections: tuple[ConnectionSpec, ...] = ()
    aliases: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class DashboardSettingsSpec:
    """User-set dashboard settings; ``None`` means "not set, use the canon"."""

    silent_loading: bool | None = None
    dependent_selectors: bool | None = None
    expand_toc: bool | None = None
    hide_dash_title: bool | None = None
    hide_tabs: bool | None = None
    autoupdate_interval: int | None = None
    max_concurrent_requests: int | None = None
    load_priority: DashboardLoadPriority | None = None


# -- update op records (epic D3) -------------------------------------------
#
# Typed records of the DashboardUpdate operation queue. The converter applies
# them sequentially to a deep copy of the raw ``data`` snapshot; anything the
# ops do not touch stays verbatim (unknown item types, future fields).


@dataclass(frozen=True, slots=True)
class UpdateTabOp:
    """Partial patch of one existing tab; ``None`` fields stay untouched."""

    tab_id: str
    title: str | None
    hidden: bool | None


@dataclass(frozen=True, slots=True)
class RemoveTabOp:
    tab_id: str


@dataclass(frozen=True, slots=True)
class ReorderTabsOp:
    """Exact permutation of ALL tab ids in the desired order."""

    order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplaceChartOp:
    """Swap the chartId of one widget chart-tab; title/params stay verbatim."""

    item_id: str
    chart_id: str
    widget_tab_id: str | None


@dataclass(frozen=True, slots=True)
class RemoveItemOp:
    """Remove ALL occurrences of the item (items and globalItems on every tab)
    plus its layout entries and connections; alias fields no remaining item
    uses are auto-dropped (the UI self-repair semantics)."""

    item_id: str


@dataclass(frozen=True, slots=True)
class SetChartParamsOp:
    item_id: str
    params: Mapping[str, tuple[str, ...]]
    merge: bool


@dataclass(frozen=True, slots=True)
class RemoveConnectionOp:
    tab_id: str
    from_id: str
    to_id: str


@dataclass(frozen=True, slots=True)
class RemoveAliasOp:
    """Remove the alias group whose member set equals ``fields``."""

    tab_id: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GlobalParamsOp:
    """Deep merge into ``settings.globalParams``; a ``REMOVE_PARAM`` value
    deletes the key."""

    changes: Mapping[str, tuple[str, ...] | _RemoveParam]


@dataclass(frozen=True, slots=True)
class UpdateSelectorOp:
    """Point-patch of one selector's source fields; ``None`` fields stay
    untouched (verbatim). ``member_id`` is None for standalone controls."""

    item_id: str
    member_id: str | None
    title: str | None
    default_value: SelectorDefaultValue | None
    operation: SelectorOperation | None
    required: bool | None
    hint: str | None


@dataclass(frozen=True, slots=True)
class RemoveSelectorMemberOp:
    """Remove one member from a group_control; a group emptied by the
    removal is removed entirely (wrapper, layout, connections)."""

    item_id: str
    member_id: str


@dataclass(frozen=True, slots=True)
class AddConnectionOp:
    """Append one directed ignore edge (wire endpoint ids, see ConnectionSpec)."""

    tab_id: str
    from_id: str
    to_id: str


@dataclass(frozen=True, slots=True)
class AddAliasOp:
    """Append one alias group to ``tab.aliases.default``."""

    tab_id: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AddTabOp:
    """Append a new tab snapshotted from a DashboardTab entity."""

    tab: TabSpec


@dataclass(frozen=True, slots=True)
class AddItemsOp:
    """Append staged items (with layout entries) to an existing tab."""

    tab_id: str
    items: tuple[DashboardItemSpec, ...]
    layout: tuple[LayoutItemSpec | AutoLayoutItemSpec, ...]


@dataclass(frozen=True, slots=True)
class AddGroupSelectorOp:
    """Assemble a group_control on update, absorbing existing selectors.

    Existing control/group_control items whose ids are in
    ``absorbed_item_ids`` have their member dicts lifted into the new group
    verbatim; the absorbed wrappers and layout entries are removed.
    """

    tab_id: str
    item: GroupControlItem
    layout: LayoutItemSpec | AutoLayoutItemSpec
    absorbed_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApplyLayoutOp:
    """Reposition existing items to absolute cells (a batch move/resize by id).

    ``positions`` are ``(item_id, x, y, w, h)`` tuples; ``tab_id=None`` targets
    every occurrence of the item (shared globals move on all their tabs)."""

    tab_id: str | None
    positions: tuple[tuple[str, int, int, int, int], ...]


@dataclass(frozen=True, slots=True)
class MoveItemOp:
    """Move an item; ``x``/``y`` are absolute, ``dx``/``dy`` are relative (each
    axis is one or the other). Applies to every occurrence of a shared item."""

    item_id: str
    x: int | None
    y: int | None
    dx: int | None
    dy: int | None


@dataclass(frozen=True, slots=True)
class ResizeItemOp:
    """Resize an item; ``w``/``h`` absolute, ``dw``/``dh`` relative (per dim).
    Applies to every occurrence of a shared item."""

    item_id: str
    w: int | None
    h: int | None
    dw: int | None
    dh: int | None


@dataclass(frozen=True, slots=True)
class SwapItemsOp:
    """Swap the rectangles of two items on one tab."""

    first_item_id: str
    second_item_id: str
    tab_id: str | None


@dataclass(frozen=True, slots=True)
class ShiftBelowOp:
    """Shift every item at ``y >= y_threshold`` down by ``dy`` (per tab, or all
    tabs when ``tab_id`` is None)."""

    tab_id: str | None
    y_threshold: int
    dy: int


@dataclass(frozen=True, slots=True)
class PinItemOp:
    """Pin a widget/text/title/image into a header pin zone (all occurrences)."""

    item_id: str
    parent: str = "__fixGCont"


@dataclass(frozen=True, slots=True)
class UnpinItemOp:
    """Return a pinned item to the normal flow (all occurrences; idempotent)."""

    item_id: str


@dataclass(frozen=True, slots=True)
class CompactLayoutOp:
    """Compact the default-flow items of a tab upward (opt-in; per tab, or all
    tabs when ``tab_id`` is None). Pinned zones are left untouched."""

    tab_id: str | None


DashboardUpdateOp: TypeAlias = (
    "UpdateTabOp | RemoveTabOp | ReorderTabsOp | ReplaceChartOp | RemoveItemOp | "
    "SetChartParamsOp | RemoveConnectionOp | RemoveAliasOp | GlobalParamsOp | AddTabOp | AddItemsOp | "
    "AddConnectionOp | AddAliasOp | AddGroupSelectorOp | UpdateSelectorOp | RemoveSelectorMemberOp | "
    "ApplyLayoutOp | MoveItemOp | ResizeItemOp | SwapItemsOp | ShiftBelowOp | PinItemOp | UnpinItemOp | "
    "CompactLayoutOp"
)


@dataclass(frozen=True, slots=True)
class DashboardUpdateSpec:
    """Immutable snapshot of a dashboard-update builder's state.

    ``data``/``meta``/``annotation`` are verbatim snapshots of the loaded
    revision; ``ops`` apply on top of a deep copy of ``data``. The three
    ``*_description`` fields are tri-state: ``None`` = not called (verbatim),
    ``""`` = clear (the converter removes the key — the live-verified true
    clearing form, P0.1), any other value = set. ``settings`` carries only the
    values the user set; ``settings_cleared`` lists the setting field names
    reset back to the canon.
    """

    dashboard_id: str
    installation: str
    location: EntryLocation | None
    name: str | None
    data: Mapping[str, object]
    meta: Mapping[str, object] | None
    annotation: Mapping[str, object] | None
    ops: tuple[DashboardUpdateOp, ...]
    description: str | None
    access_description: str | None
    support_description: str | None
    settings: DashboardSettingsSpec
    settings_cleared: frozenset[str]
    generated_id_count: int


@dataclass(frozen=True, slots=True)
class DashboardCreateSpec:
    """Immutable snapshot of a dashboard-create builder's state.

    This is the read contract between the domain builder layer and the
    converter/api layers. Converters and services consume this spec instead of
    reaching into builder ``_protected`` attributes.
    """

    installation: str
    name: str
    location: EntryLocation
    tabs: tuple[TabSpec, ...]
    description: str | None
    access_description: str | None
    support_description: str | None
    settings: DashboardSettingsSpec
    meta: Mapping[str, str | bool] | None
    generated_id_count: int
