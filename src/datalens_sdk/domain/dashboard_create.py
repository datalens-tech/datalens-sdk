"""Dashboard create builder (epic D2).

Tabs are built standalone as :class:`~datalens_sdk.domain.dashboard_tab.DashboardTab`
entities (the ``dataset.source`` pattern) and attached via ``add_tab(tab)``.
The attach snapshots the tab's content and assigns deterministic ids; the
builder then snapshots into
:class:`~datalens_sdk.domain.specs.dashboard.DashboardCreateSpec` via
``to_spec()`` — the only surface the converter/api layers may consume.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, cast, get_args

from typing_extensions import Self

from datalens_sdk.domain.dashboard_tab import DashboardTab, _PendingItem
from datalens_sdk.domain.dashboard_types import DashboardLoadPriority
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    resolve_entry_location,
    validate_entry_name,
)
from datalens_sdk.domain.specs.dashboard import (
    AutoLayoutItemSpec,
    ConnectionSpec,
    DashboardCreateSpec,
    DashboardItemSpec,
    DashboardSettingsSpec,
    ExternalControlItem,
    GroupControlItem,
    LayoutItemSpec,
    TabSpec,
    WidgetItem,
)
from datalens_sdk.errors import DatalensConfigurationError, DatalensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import Dashboard
    from datalens_sdk.domain.ports import DashboardOperations

_UNBOUND = "Object is not bound to client operations. Use a client namespace."

__all__ = ["DashboardCreate"]

_TAB_ID_PREFIX = "tab_"
_ITEM_ID_PREFIX = "el_"
_WIDGET_TAB_ID_PREFIX = "wt_"

_TAB_NAMESPACE = "tab"
_ITEM_NAMESPACE = "item"
_WIDGET_TAB_NAMESPACE = "widget tab"

_MIN_AUTOUPDATE_INTERVAL = 30


class _DashboardIdAllocator:
    """Deterministic id assignment shared by the create and update builders.

    Explicit ids are claimed (duplicates fail loud); auto ids are generated
    from monotonic per-namespace counters, skipping anything already used.
    ``reserve`` seeds the allocator with pre-existing ids and is idempotent:
    the same id may arrive from several tabs (shared global items).
    """

    __slots__ = ("_counters", "_generated_count", "_used")

    def __init__(self) -> None:
        self._used: dict[str, set[str]] = {
            _TAB_NAMESPACE: set(),
            _ITEM_NAMESPACE: set(),
            _WIDGET_TAB_NAMESPACE: set(),
        }
        self._counters: dict[str, int] = {
            _TAB_NAMESPACE: 0,
            _ITEM_NAMESPACE: 0,
            _WIDGET_TAB_NAMESPACE: 0,
        }
        self._generated_count = 0

    def is_used(self, namespace: str, value: str) -> bool:
        return value in self._used[namespace]

    def reserve(self, namespace: str, values: Iterable[str]) -> None:
        self._used[namespace].update(values)

    def claim(self, namespace: str, value: str) -> str:
        if not value:
            raise DatalensValidationError(f"{namespace} id must not be an empty string")
        used = self._used[namespace]
        if value in used:
            raise DatalensValidationError(f"Duplicate {namespace} id {value!r}")
        used.add(value)
        return value

    def generate(self, namespace: str, prefix: str) -> str:
        used = self._used[namespace]
        while True:
            self._counters[namespace] += 1
            candidate = f"{prefix}{self._counters[namespace]}"
            if candidate not in used:
                used.add(candidate)
                self._generated_count += 1
                return candidate

    @property
    def generated_count(self) -> int:
        return self._generated_count


def _attached_item(entry: _PendingItem, *, allocator: _DashboardIdAllocator) -> DashboardItemSpec:
    item_id = (
        entry.explicit_id if entry.explicit_id is not None else allocator.generate(_ITEM_NAMESPACE, _ITEM_ID_PREFIX)
    )
    item = replace(entry.item, id=item_id)
    if isinstance(item, WidgetItem):
        item = replace(
            item,
            tabs=tuple(
                replace(widget_tab, id=allocator.generate(_WIDGET_TAB_NAMESPACE, _WIDGET_TAB_ID_PREFIX))
                for widget_tab in item.tabs
            ),
        )
    if isinstance(item, GroupControlItem):
        # member ids live in the item namespace: they are the selectors'
        # logical identity (update addressing, connection endpoints); explicit
        # ones were claimed in phase B, pending ones are generated here
        item = replace(
            item,
            members=tuple(
                member if member.id else replace(member, id=allocator.generate(_ITEM_NAMESPACE, _ITEM_ID_PREFIX))
                for member in item.members
            ),
        )
    return item


def _explicit_member_ids(entry: _PendingItem) -> tuple[str, ...]:
    if not isinstance(entry.item, GroupControlItem):
        return ()
    return tuple(member.id for member in entry.item.members if member.id)


def _snapshot_items(
    tab: DashboardTab,
    *,
    allocator: _DashboardIdAllocator,
    installation: str,
    defer_auto: bool = False,
) -> tuple[tuple[DashboardItemSpec, ...], tuple[LayoutItemSpec | AutoLayoutItemSpec, ...]]:
    """Snapshot a tab's pending items into specs, assigning deterministic ids.

    Phase A validates everything without mutating the allocator; phase B
    claims all explicit ids first so autos can never take them. The tab
    entity itself is never mutated (reusable template).

    With ``defer_auto`` (update add_* into an existing tab), an ``at=None`` item
    emits an :class:`AutoLayoutItemSpec` — only its size is known; ``x``/``y``
    resolve at apply time below the target tab's current content. On create the
    tab knows all its items, so autos are resolved eagerly (``defer_auto`` off).
    """
    unclaimed_groups = tab._unclaimed_group_names()
    if unclaimed_groups:
        raise DatalensValidationError(
            f"Selector groups {list(unclaimed_groups)!r} were registered via add_selector(group=...) "
            "but never assembled with add_group_selector"
        )
    pending = tab._pending_snapshot()
    # phase A — validate without touching allocator state
    for entry in pending:
        if entry.explicit_id is not None and allocator.is_used(_ITEM_NAMESPACE, entry.explicit_id):
            raise DatalensValidationError(f"Duplicate item id {entry.explicit_id!r}")
        for member_id in _explicit_member_ids(entry):
            if allocator.is_used(_ITEM_NAMESPACE, member_id):
                raise DatalensValidationError(f"Duplicate item id {member_id!r}")
        for chart_installation in entry.chart_installations:
            if chart_installation and chart_installation != installation:
                raise DatalensValidationError(
                    f"Cannot place a {chart_installation!r} chart on a {installation!r} dashboard"
                )
    # phase B — claim ALL explicit ids first so autos can't take them
    for entry in pending:
        if entry.explicit_id is not None:
            allocator.claim(_ITEM_NAMESPACE, entry.explicit_id)
        for member_id in _explicit_member_ids(entry):
            allocator.claim(_ITEM_NAMESPACE, member_id)
    items: list[DashboardItemSpec] = []
    layout: list[LayoutItemSpec | AutoLayoutItemSpec] = []
    for entry in pending:
        item = _attached_item(entry, allocator=allocator)
        items.append(item)
        x, y, w, h = entry.placement
        parent = entry.parent
        if defer_auto and entry.auto:
            layout.append(
                AutoLayoutItemSpec(
                    i=item.id, w=w, h=h, parent=parent, new_row=entry.new_row, gap=entry.gap, floor=entry.floor
                )
            )
        else:
            layout.append(LayoutItemSpec(i=item.id, x=x, y=y, w=w, h=h, parent=parent))
    return tuple(items), tuple(layout)


def _wire_endpoints(entry: _PendingItem, attached: DashboardItemSpec) -> tuple[str, ...] | None:
    """Wire endpoints a logical item reference expands to."""
    if isinstance(attached, WidgetItem):
        return tuple(widget_tab.id for widget_tab in attached.tabs)
    if isinstance(attached, GroupControlItem):
        return tuple(member.id for member in attached.members)
    if isinstance(attached, ExternalControlItem):
        return (attached.id,)
    return None


def _translated_connections(
    tab: DashboardTab,
    pending: tuple[_PendingItem, ...],
    items: tuple[DashboardItemSpec, ...],
) -> tuple[ConnectionSpec, ...]:
    """Translate logical connection refs into wire endpoint edges.

    References must be explicit ``item_id=`` values of THIS tab (decision:
    auto-ids are not addressable); a selector MEMBER id addresses just that
    member, a group wrapper or widget id expands to all its member/chart-tab
    ids (cartesian product per edge, deduplicated in order).
    """
    logical_pairs, _ = tab._pending_wiring_snapshot()
    if not logical_pairs:
        return ()
    endpoints: dict[str, tuple[str, ...]] = {}
    for entry, attached in zip(pending, items, strict=True):
        expansion = _wire_endpoints(entry, attached)
        if entry.explicit_id is not None and expansion is not None:
            endpoints[entry.explicit_id] = expansion
        if isinstance(entry.item, GroupControlItem) and isinstance(attached, GroupControlItem):
            for pre_member, att_member in zip(entry.item.members, attached.members, strict=True):
                if pre_member.id:
                    endpoints[pre_member.id] = (att_member.id,)
    edges: list[ConnectionSpec] = []
    seen: set[tuple[str, str]] = set()
    for from_ref, to_ref in logical_pairs:
        for name, ref in (("from_item", from_ref), ("to_item", to_ref)):
            if ref not in endpoints:
                raise DatalensValidationError(
                    f"Connection {name} {ref!r} is not an explicit item_id of a selector or chart "
                    f"on tab {tab.title!r} (text/title/image items cannot filter or be filtered)"
                )
        for source in endpoints[from_ref]:
            for target in endpoints[to_ref]:
                if source != target and (source, target) not in seen:
                    seen.add((source, target))
                    edges.append(ConnectionSpec(from_id=source, to_id=target))
    return tuple(edges)


def _snapshot_tab(
    tab: DashboardTab,
    *,
    allocator: _DashboardIdAllocator,
    installation: str,
    defer_auto: bool = False,
) -> TabSpec:
    """Snapshot a DashboardTab entity into a TabSpec with assigned ids.

    On create the tab is complete, so autos resolve eagerly (``defer_auto`` off).
    A tab added on UPDATE keeps its ``at=None`` items as :class:`AutoLayoutItemSpec`
    so the applier can place them below the allTabs selectors the new tab inherits.
    """
    if not isinstance(tab, DashboardTab):
        raise DatalensValidationError(
            f"add_tab expects a DashboardTab, got {type(tab).__name__!r}. "
            'Build the tab first: DashboardTab("Overview").add_chart(...), '
            "then add_tab(tab)."
        )
    if tab.tab_id is not None and allocator.is_used(_TAB_NAMESPACE, tab.tab_id):
        raise DatalensValidationError(f"Duplicate tab id {tab.tab_id!r}")
    items, raw_layout = _snapshot_items(tab, allocator=allocator, installation=installation, defer_auto=defer_auto)
    layout = raw_layout if defer_auto else cast("tuple[LayoutItemSpec, ...]", raw_layout)
    connections = _translated_connections(tab, tab._pending_snapshot(), items)
    _, aliases = tab._pending_wiring_snapshot()
    resolved_tab_id = (
        allocator.claim(_TAB_NAMESPACE, tab.tab_id)
        if tab.tab_id is not None
        else allocator.generate(_TAB_NAMESPACE, _TAB_ID_PREFIX)
    )
    return TabSpec(
        id=resolved_tab_id,
        title=tab.title,
        items=items,
        layout=layout,
        hidden=tab.hidden,
        connections=connections,
        aliases=aliases,
    )


class DashboardCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        operations: DashboardOperations | None = None,
    ) -> None:
        self._installation = installation
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="Dashboard creation",
        )
        validate_entry_name(name=name, location=self._location)
        self._name = name
        self._operations = operations
        self._description: str | None = None
        self._access_description: str | None = None
        self._support_description: str | None = None
        self._settings = DashboardSettingsSpec()
        self._meta: dict[str, str | bool] | None = None
        self._tabs: list[TabSpec] = []
        self._allocator = _DashboardIdAllocator()
        self._last_tab_id: str | None = None

    # -- tabs --------------------------------------------------------------

    def add_tab(self, tab: DashboardTab) -> Self:
        """Attach a snapshot of ``tab``, assigning deterministic ids.

        The tab entity is never mutated: it stays a reusable template, and
        assigned ids are not written back. Pass explicit ``item_id=`` on the
        tab's ``add_*`` calls when stable item handles are needed.
        """
        tab_spec = _snapshot_tab(tab, allocator=self._allocator, installation=self._installation)
        self._tabs.append(tab_spec)
        self._last_tab_id = tab_spec.id
        return self

    @property
    def last_tab_id(self) -> str:
        if self._last_tab_id is None:
            raise DatalensValidationError("No tabs have been added yet")
        return self._last_tab_id

    # -- plumbing ----------------------------------------------------------

    def description(self, value: str) -> Self:
        self._description = value
        return self

    def access_description(self, value: str) -> Self:
        self._access_description = value
        return self

    def support_description(self, value: str) -> Self:
        self._support_description = value
        return self

    def settings(
        self,
        *,
        silent_loading: bool | None = None,
        dependent_selectors: bool | None = None,
        expand_toc: bool | None = None,
        hide_dash_title: bool | None = None,
        hide_tabs: bool | None = None,
        autoupdate_interval: int | None = None,
        max_concurrent_requests: int | None = None,
        load_priority: DashboardLoadPriority | None = None,
    ) -> Self:
        flags = {
            "silent_loading": silent_loading,
            "dependent_selectors": dependent_selectors,
            "expand_toc": expand_toc,
            "hide_dash_title": hide_dash_title,
            "hide_tabs": hide_tabs,
        }
        for name, value in flags.items():
            if value is not None and not isinstance(value, bool):
                raise DatalensValidationError(f"{name} must be a bool or None, got {value!r}")
        if autoupdate_interval is not None:
            if isinstance(autoupdate_interval, bool) or not isinstance(autoupdate_interval, int):
                raise DatalensValidationError(f"autoupdate_interval must be an int, got {autoupdate_interval!r}")
            if autoupdate_interval < _MIN_AUTOUPDATE_INTERVAL:
                raise DatalensValidationError(
                    f"autoupdate_interval must be >= {_MIN_AUTOUPDATE_INTERVAL}, got {autoupdate_interval}"
                )
        if max_concurrent_requests is not None:
            if isinstance(max_concurrent_requests, bool) or not isinstance(max_concurrent_requests, int):
                raise DatalensValidationError(
                    f"max_concurrent_requests must be an int, got {max_concurrent_requests!r}"
                )
            if max_concurrent_requests < 1:
                raise DatalensValidationError(f"max_concurrent_requests must be >= 1, got {max_concurrent_requests}")
        if load_priority is not None and load_priority not in get_args(DashboardLoadPriority):
            raise DatalensValidationError(f"Unknown load_priority {load_priority!r}")
        updated = self._settings
        if silent_loading is not None:
            updated = replace(updated, silent_loading=silent_loading)
        if dependent_selectors is not None:
            updated = replace(updated, dependent_selectors=dependent_selectors)
        if expand_toc is not None:
            updated = replace(updated, expand_toc=expand_toc)
        if hide_dash_title is not None:
            updated = replace(updated, hide_dash_title=hide_dash_title)
        if hide_tabs is not None:
            updated = replace(updated, hide_tabs=hide_tabs)
        if autoupdate_interval is not None:
            updated = replace(updated, autoupdate_interval=autoupdate_interval)
        if max_concurrent_requests is not None:
            updated = replace(updated, max_concurrent_requests=max_concurrent_requests)
        if load_priority is not None:
            updated = replace(updated, load_priority=load_priority)
        self._settings = updated
        return self

    def meta(self, value: Mapping[str, str | bool] | None) -> Self:
        self._meta = None if value is None else dict(value)
        return self

    # -- snapshot ----------------------------------------------------------

    def to_spec(self) -> DashboardCreateSpec:
        return DashboardCreateSpec(
            installation=self._installation,
            name=self._name,
            location=self._location,
            tabs=tuple(self._tabs),
            description=self._description,
            access_description=self._access_description,
            support_description=self._support_description,
            settings=self._settings,
            meta=None if self._meta is None else dict(self._meta),
            generated_id_count=self._allocator.generated_count,
        )

    def build(self) -> Dashboard:
        if self._operations is None:
            raise DatalensConfigurationError(_UNBOUND)
        return self._operations.create_dashboard(self)
