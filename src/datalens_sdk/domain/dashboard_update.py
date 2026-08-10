"""Dashboard update builder (epic D3) — raw read-modify-write.

The update is full-document while the read DTO is tolerant. The builder
therefore snapshots the loaded revision's raw ``data`` verbatim and accumulates
typed operation records; the converter applies them point-wise to a deep copy,
leaving untouched nodes byte-identical.

Concurrency: the server has NO optimistic locking — a save with a stale
snapshot silently creates a new revision on top (last-write-wins), and someone
else's fresher edits are overwritten. Call ``refresh()`` right before
``.update`` and keep the builder short-lived.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import json
from typing import TYPE_CHECKING, get_args

from typing_extensions import Self

from datalens_sdk.domain.dashboard_create import _DashboardIdAllocator
from datalens_sdk.domain.dashboard_types import (
    UNSET,
    DashboardLoadPriority,
    _RemoveParam,
    _Unset,
)
from datalens_sdk.domain.dashboard_update_adders import _StructuralAddersMixin
from datalens_sdk.domain.dashboard_update_layout import _LayoutOpsMixin
from datalens_sdk.domain.dashboard_update_support import (
    _GLOBAL_ITEMS_FIELD,
    _ITEMS_FIELD,
    _display_pinned_to_current_tabs,
    _ItemOccurrence,
    _iter_mappings,
    _iter_mappings_or_lists,
    _mapping_or_none,
    _normalize_param_values,
    _resolve_chart_id,
    _string_or_none,
    _TabIndex,
)
from datalens_sdk.domain.dashboard_update_wiring import _WiringAddersMixin
from datalens_sdk.domain.specs.dashboard import (
    DashboardSettingsSpec,
    DashboardUpdateOp,
    DashboardUpdateSpec,
    GlobalParamsOp,
    RemoveAliasOp,
    RemoveConnectionOp,
    RemoveItemOp,
    RemoveTabOp,
    ReorderTabsOp,
    ReplaceChartOp,
    SelectorMemberSpec,
    SetChartParamsOp,
    UpdateTabOp,
)
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_UNBOUND = "Object is not bound to client operations. Use a client namespace."

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import Dashboard
    from datalens_sdk.domain.editor_chart import EditorChart
    from datalens_sdk.domain.entry_location import EntryLocation
    from datalens_sdk.domain.ports import DashboardOperations
    from datalens_sdk.domain.wizard_chart import WizardChart

__all__ = ["DashboardUpdate"]

_MIN_AUTOUPDATE_INTERVAL = 30


class DashboardUpdate(_StructuralAddersMixin, _WiringAddersMixin, _LayoutOpsMixin):
    """Accumulates point-wise operations over a loaded dashboard revision.

    Created via :attr:`Dashboard.update`. Every mutator validates its
    references at call time against a shadow index of the snapshot (kept in
    sync after each recorded operation) and returns ``self`` for chaining;
    ``to_spec()`` is a repeatable dry-run snapshot.

    Last-write-wins: the snapshot is the revision that was fetched. The server
    detects no revision conflicts — concurrent edits made after the fetch are
    silently overwritten on execute.
    """

    def __init__(self, *, dashboard: Dashboard, operations: DashboardOperations | None = None) -> None:
        if not dashboard.id:
            raise DataLensValidationError("Cannot update a dashboard without an id")
        self._dashboard_id: str = dashboard.id
        self._installation = dashboard.installation
        # JSON round-trip: raw wire data holds only JSON types; the builder must
        # be isolated from later mutation of the source object and vice versa.
        self._data: dict[str, object] = json.loads(json.dumps(dict(dashboard.data)))
        # meta/annotation get the same JSON deep copy as data: a shallow dict()
        # would share nested nodes with dashboard.raw, leaking later mutations
        # of the source object into the payload.
        raw_meta = _mapping_or_none(dashboard.raw.get("meta"))
        self._meta: dict[str, object] | None = None if raw_meta is None else json.loads(json.dumps(dict(raw_meta)))
        raw_annotation = _mapping_or_none(dashboard.raw.get("annotation"))
        self._annotation: dict[str, object] | None = (
            None if raw_annotation is None else json.loads(json.dumps(dict(raw_annotation)))
        )
        self._location: EntryLocation | None = dashboard.location
        self._name: str | None = dashboard.name
        self._operations = operations
        self._ops: list[DashboardUpdateOp] = []
        self._description: str | None = None
        self._access_description: str | None = None
        self._support_description: str | None = None
        self._settings = DashboardSettingsSpec()
        self._settings_cleared: set[str] = set()
        self._allocator: _DashboardIdAllocator | None = None
        self._tabs: list[_TabIndex] = []
        self._item_occurrences: dict[str, list[_ItemOccurrence]] = {}
        self._item_types: dict[str, str | None] = {}
        self._item_widget_tab_ids: dict[str, set[str]] = {}
        self._item_group_children: dict[str, set[str]] = {}
        # shared selectors scoped to ALL tabs: tabs added later in this
        # builder must pick them up too (the applier copies them over)
        self._all_tabs_shared_ids: set[str] = set()
        # shadow of already-removed connections/aliases: repeat removals and
        # removals of vanished entries must fail at call time, not in the applier
        self._removed_connections: set[tuple[str, str, str]] = set()
        self._removed_aliases: set[tuple[str, frozenset[str]]] = set()
        self._added_connections: set[tuple[str, str, str]] = set()
        self._added_aliases: set[tuple[str, frozenset[str]]] = set()
        self._pending_update_groups: dict[str, list[SelectorMemberSpec]] = {}
        self._build_index()

    # -- shadow index -------------------------------------------------------

    def _build_index(self) -> None:
        for tab in _iter_mappings(self._data.get("tabs")):
            tab_id = _string_or_none(tab.get("id"))
            if tab_id is None:
                continue
            entry = _TabIndex(tab_id=tab_id, title=_string_or_none(tab.get("title")))
            for container in (_ITEMS_FIELD, _GLOBAL_ITEMS_FIELD):
                for item in _iter_mappings(tab.get(container)):
                    self._index_item(entry, item, container)
            self._tabs.append(entry)
        self._recompute_all_tabs_shared_ids()

    def _recompute_all_tabs_shared_ids(self) -> None:
        """Presence-based set of shared items a tab added later would inherit —
        mirrors the applier (``_shared_ids_displayed_on_all_tabs``): an item in
        the globalItems of EVERY current tab, minus explicit display pins.
        Recomputed after ``remove_tab``: removing a tab can turn an item that
        was displayed on all-but-one tabs into displayed-on-all."""
        if not self._tabs:
            self._all_tabs_shared_ids = set()
            return
        raw_items: dict[str, Mapping[str, object]] = {}
        for tab in _iter_mappings(self._data.get("tabs")):
            for item in _iter_mappings(tab.get(_GLOBAL_ITEMS_FIELD)):
                item_id = _string_or_none(item.get("id"))
                if item_id is not None:
                    raw_items.setdefault(item_id, item)
        remaining: set[object] = {entry.tab_id for entry in self._tabs}
        shared: set[str] = set()
        for item_id, occurrences in self._item_occurrences.items():
            tabs_with = {occ.tab_id for occ in occurrences if occ.container == _GLOBAL_ITEMS_FIELD}
            if not tabs_with or not remaining <= tabs_with:
                continue
            payload = raw_items.get(item_id)
            if payload is None or not _display_pinned_to_current_tabs(payload, remaining):
                shared.add(item_id)
        self._all_tabs_shared_ids = shared

    def _index_item(self, tab: _TabIndex, item: Mapping[str, object], container: str) -> None:
        item_id = _string_or_none(item.get("id"))
        if item_id is None:
            return
        tab.item_ids.add(item_id)
        self._item_occurrences.setdefault(item_id, []).append(_ItemOccurrence(tab_id=tab.tab_id, container=container))
        self._item_types.setdefault(item_id, _string_or_none(item.get("type")))
        data = _mapping_or_none(item.get("data")) or {}
        for widget_tab in _iter_mappings(data.get("tabs")):
            widget_tab_id = _string_or_none(widget_tab.get("id"))
            if widget_tab_id is not None:
                tab.widget_tab_ids.add(widget_tab_id)
                self._item_widget_tab_ids.setdefault(item_id, set()).add(widget_tab_id)
        for child in _iter_mappings(data.get("group")):
            child_id = _string_or_none(child.get("id"))
            if child_id is not None:
                tab.control_child_ids.add(child_id)
                self._item_group_children.setdefault(item_id, set()).add(child_id)

    def _resolve_tab(self, ref: str) -> str:
        """Resolve a tab reference: id first, then title (must be unambiguous)."""
        if not isinstance(ref, str) or not ref:
            raise DataLensValidationError(f"tab reference must be a non-empty string, got {ref!r}")
        for tab in self._tabs:
            if tab.tab_id == ref:
                return tab.tab_id
        matches = [tab.tab_id for tab in self._tabs if tab.title == ref]
        if len(matches) > 1:
            raise DataLensValidationError(f"Tab title {ref!r} is ambiguous (tabs {matches!r}); use the tab id instead")
        if not matches:
            known = [tab.tab_id for tab in self._tabs]
            raise DataLensValidationError(f"Unknown tab {ref!r}; known tab ids: {known!r}")
        return matches[0]

    def _require_item(self, item_id: str) -> str:
        """Return the item's type after checking it still exists in the index."""
        if not isinstance(item_id, str) or not item_id:
            raise DataLensValidationError(f"item_id must be a non-empty string, got {item_id!r}")
        if item_id not in self._item_occurrences:
            raise DataLensValidationError(f"Unknown item id {item_id!r}")
        return self._item_types.get(item_id) or ""

    def _tab_index(self, tab_id: str) -> _TabIndex:
        for entry in self._tabs:
            if entry.tab_id == tab_id:
                return entry
        raise DataLensValidationError(f"Unknown tab {tab_id!r}")  # pragma: no cover - guarded by _resolve_tab

    def _drop_item_from_index(self, item_id: str) -> None:
        for occurrence in self._item_occurrences.pop(item_id, []):
            tab = self._tab_index(occurrence.tab_id)
            tab.item_ids.discard(item_id)
            tab.widget_tab_ids -= self._item_widget_tab_ids.get(item_id, set())
            tab.control_child_ids -= self._item_group_children.get(item_id, set())
        self._item_types.pop(item_id, None)
        self._item_widget_tab_ids.pop(item_id, None)
        self._item_group_children.pop(item_id, None)
        self._all_tabs_shared_ids.discard(item_id)

    def _raw_tabs(self) -> list[Mapping[str, object]]:
        live_ids = {entry.tab_id for entry in self._tabs}
        return [tab for tab in _iter_mappings(self._data.get("tabs")) if _string_or_none(tab.get("id")) in live_ids]

    # -- tab operations -------------------------------------------------------

    def update_tab(self, tab: str, *, title: str | None = None, hidden: bool | None = None) -> Self:
        """Partial patch of an existing tab; omitted kwargs stay untouched."""
        tab_id = self._resolve_tab(tab)
        if title is None and hidden is None:
            raise DataLensValidationError("update_tab requires at least one of title= or hidden=")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise DataLensValidationError(f"tab title must be a non-empty string, got {title!r}")
        if hidden is not None and not isinstance(hidden, bool):
            raise DataLensValidationError(f"hidden must be a bool or None, got {hidden!r}")
        self._ops.append(UpdateTabOp(tab_id=tab_id, title=title, hidden=hidden))
        if title is not None:
            self._tab_index(tab_id).title = title
        return self

    def hide_tab(self, tab: str) -> Self:
        return self.update_tab(tab, hidden=True)

    def show_tab(self, tab: str) -> Self:
        return self.update_tab(tab, hidden=False)

    def remove_tab(self, tab: str) -> Self:
        tab_id = self._resolve_tab(tab)
        if len(self._tabs) == 1:
            raise DataLensValidationError("Cannot remove the last remaining tab")
        entry = self._tab_index(tab_id)
        for item_id in sorted(entry.item_ids):
            occurrences = self._item_occurrences.get(item_id, [])
            occurrences[:] = [occ for occ in occurrences if occ.tab_id != tab_id]
            if not occurrences:
                self._item_occurrences.pop(item_id, None)
                self._item_types.pop(item_id, None)
                self._item_widget_tab_ids.pop(item_id, None)
                self._item_group_children.pop(item_id, None)
        self._tabs.remove(entry)
        self._ops.append(RemoveTabOp(tab_id=tab_id))
        # removing a tab can flip a shared item into displayed-on-all
        self._recompute_all_tabs_shared_ids()
        return self

    def reorder_tabs(self, order: Sequence[str]) -> Self:
        """Reorder tabs; ``order`` must be an exact permutation of all tabs."""
        if isinstance(order, str) or not isinstance(order, Sequence):
            raise DataLensValidationError(f"reorder_tabs expects a sequence of tab references, got {order!r}")
        resolved = [self._resolve_tab(ref) for ref in order]
        current = [entry.tab_id for entry in self._tabs]
        if sorted(resolved) != sorted(current) or len(set(resolved)) != len(resolved):
            raise DataLensValidationError(
                f"reorder_tabs must list every tab exactly once; current tabs {current!r}, got {resolved!r}"
            )
        by_id = {entry.tab_id: entry for entry in self._tabs}
        self._tabs = [by_id[tab_id] for tab_id in resolved]
        self._ops.append(ReorderTabsOp(order=tuple(resolved)))
        return self

    # -- item operations -------------------------------------------------------

    def replace_chart(
        self,
        *,
        item_id: str,
        chart: WizardChart | EditorChart | str,
        widget_tab_id: str | None = None,
    ) -> Self:
        """Swap the chart of one widget chart-tab by ``item_id``.

        Only ``chartId`` changes; the chart-tab title and params stay verbatim.
        A shared global item is ONE logical item: the swap applies to every
        occurrence on every tab (same semantics as ``remove_item``).
        Dangling-params risk: the new chart's dataset parameter NAMES may
        differ from the old one's (widget params filter by dataset parameter
        name, not field title) — the SDK cannot detect this without HTTP; the
        D4.6 ``validate_dashboard_refs`` recipe is the planned detector.
        """
        item_type = self._require_item(item_id)
        if item_type != "widget":
            raise DataLensValidationError(
                f"replace_chart targets widget items; item {item_id!r} has type {item_type!r}"
            )
        chart_id, chart_installation = _resolve_chart_id(chart)
        if chart_installation and chart_installation != self._installation:
            raise DataLensValidationError(
                f"Cannot place a {chart_installation!r} chart on a {self._installation!r} dashboard"
            )
        widget_tabs = self._item_widget_tab_ids.get(item_id, set())
        if widget_tab_id is None:
            if len(widget_tabs) > 1:
                raise DataLensValidationError(
                    f"Widget {item_id!r} has {len(widget_tabs)} chart tabs "
                    f"({sorted(widget_tabs)!r}); pass widget_tab_id= to pick one"
                )
        elif widget_tab_id not in widget_tabs:
            raise DataLensValidationError(
                f"Widget {item_id!r} has no chart tab {widget_tab_id!r}; known: {sorted(widget_tabs)!r}"
            )
        self._ops.append(ReplaceChartOp(item_id=item_id, chart_id=chart_id, widget_tab_id=widget_tab_id))
        return self

    def remove_item(self, item_id: str) -> Self:
        """Remove an item everywhere it occurs, with a cascade.

        Removes every occurrence (``items`` and ``globalItems`` on ALL tabs —
        a shared global item disappears from every tab), its layout entries,
        and all connections that reference the item or, for a
        ``group_control``, any of its nested controls. Alias fields whose
        LAST parameter user this removal took away are auto-dropped and
        groups shrunk below two fields are removed — the UI self-repair
        semantics; fields used by another item, and fields the document never
        references as parameters at all (cross-dataset aliases pairing a
        widget's dataset field, live UAT P021), survive verbatim. Detecting
        pre-existing dangling fields is ``validate_dashboard_refs``' job.

        The removed id stays reserved: a later ``add_*(item_id=<same id>)``
        in this builder fails with "Duplicate item id" (conservative — the
        allocator seeds from the raw document, removals do not free ids).
        """
        self._require_item(item_id)
        self._drop_item_from_index(item_id)
        self._ops.append(RemoveItemOp(item_id=item_id))
        return self

    def set_chart_params(
        self,
        *,
        item_id: str,
        params: Mapping[str, object],
        merge: bool = True,
    ) -> Self:
        """Set widget params (ALL chart tabs of the widget) or selector defaults.

        For a multi-tab widget the params apply to every chart tab; there is
        no per-chart-tab targeting yet. A shared global item is ONE logical
        item: the patch applies to every occurrence on every tab (same
        semantics as ``remove_item``). ``merge=False`` replaces the whole
        params mapping instead of merging by key.

        ``group_control`` is deliberately rejected: its defaults live on the
        NESTED controls (``data.group[].defaults``) — use
        :meth:`update_selector` with the member id instead.
        """
        item_type = self._require_item(item_id)
        if item_type == "group_control":
            raise DataLensValidationError(
                f"set_chart_params does not support group_control items (item {item_id!r}): "
                "defaults live on the nested controls; use update_selector(item_id=<member id>)"
            )
        if item_type not in ("widget", "control"):
            raise DataLensValidationError(
                f"set_chart_params targets widget/control items; item {item_id!r} has type {item_type!r}"
            )
        if not isinstance(params, Mapping):
            raise DataLensValidationError(f"params expects a mapping, got {params!r}")
        normalized: dict[str, tuple[str, ...]] = {}
        for key, value in params.items():
            if not isinstance(key, str) or not key:
                raise DataLensValidationError(f"params keys must be non-empty strings, got {key!r}")
            normalized[key] = _normalize_param_values(key, value)
        self._ops.append(SetChartParamsOp(item_id=item_id, params=normalized, merge=merge))
        return self

    # -- connections / aliases -------------------------------------------------

    def _require_connection_endpoint(self, ref: str) -> None:
        """Connections reference item ids, nested group-control child ids, or
        widget chart-tab ids (live wire fact: widget endpoints are the chart
        TAB ids, not the widget item id)."""
        if not isinstance(ref, str) or not ref:
            raise DataLensValidationError(f"connection endpoint must be a non-empty string, got {ref!r}")
        if ref in self._item_occurrences:
            return
        if any(ref in children for children in self._item_group_children.values()):
            return
        if any(ref in widget_tabs for widget_tabs in self._item_widget_tab_ids.values()):
            return
        raise DataLensValidationError(f"Unknown item id {ref!r}")

    def remove_connection(self, *, from_item: str, to_item: str, tab: str | None = None) -> Self:
        self._require_connection_endpoint(from_item)
        self._require_connection_endpoint(to_item)
        matches: list[str] = []
        for raw_tab in self._raw_tabs():
            tab_id = _string_or_none(raw_tab.get("id"))
            if tab_id is None:
                continue
            if (tab_id, from_item, to_item) in self._removed_connections:
                continue  # already removed by an earlier op in this builder
            for connection in _iter_mappings(raw_tab.get("connections")):
                if connection.get("from") == from_item and connection.get("to") == to_item:
                    matches.append(tab_id)
                    break
        if tab is not None:
            tab_id = self._resolve_tab(tab)
            if tab_id not in matches:
                raise DataLensValidationError(f"Tab {tab_id!r} has no connection {from_item!r} -> {to_item!r}")
        elif not matches:
            raise DataLensValidationError(f"No connection {from_item!r} -> {to_item!r} on any tab")
        elif len(matches) > 1:
            raise DataLensValidationError(
                f"Connection {from_item!r} -> {to_item!r} exists on several tabs {matches!r}; pass tab="
            )
        else:
            tab_id = matches[0]
        self._removed_connections.add((tab_id, from_item, to_item))
        self._ops.append(RemoveConnectionOp(tab_id=tab_id, from_id=from_item, to_id=to_item))
        return self

    def remove_alias(self, *fields: str, tab: str | None = None) -> Self:
        if len(fields) < 2:
            raise DataLensValidationError("remove_alias requires at least two field names")
        for field_name in fields:
            if not isinstance(field_name, str) or not field_name:
                raise DataLensValidationError(f"alias fields must be non-empty strings, got {field_name!r}")
        wanted = set(fields)
        matches: list[str] = []
        for raw_tab in self._raw_tabs():
            tab_id = _string_or_none(raw_tab.get("id"))
            if tab_id is None:
                continue
            if (tab_id, frozenset(wanted)) in self._removed_aliases:
                continue  # already removed by an earlier op in this builder
            aliases = _mapping_or_none(raw_tab.get("aliases")) or {}
            for group in _iter_mappings_or_lists(aliases.get("default")):
                if isinstance(group, list) and {entry for entry in group if isinstance(entry, str)} == wanted:
                    matches.append(tab_id)
                    break
        if tab is not None:
            tab_id = self._resolve_tab(tab)
            if tab_id not in matches:
                raise DataLensValidationError(f"Tab {tab_id!r} has no alias {sorted(wanted)!r}")
        elif not matches:
            raise DataLensValidationError(f"No alias {sorted(wanted)!r} on any tab")
        elif len(matches) > 1:
            raise DataLensValidationError(f"Alias {sorted(wanted)!r} exists on several tabs {matches!r}; pass tab=")
        else:
            tab_id = matches[0]
        self._removed_aliases.add((tab_id, frozenset(wanted)))
        self._ops.append(RemoveAliasOp(tab_id=tab_id, fields=tuple(sorted(wanted))))
        return self

    # -- plumbing (scalar setters) -------------------------------------------

    def description(self, value: str) -> Self:
        """Set ``data.description``; ``""`` clears the field (key removal)."""
        if not isinstance(value, str):
            raise DataLensValidationError(f"description must be a string, got {value!r}")
        self._description = value
        return self

    def access_description(self, value: str) -> Self:
        """Set ``data.accessDescription``; ``""`` clears the field (key removal)."""
        if not isinstance(value, str):
            raise DataLensValidationError(f"access_description must be a string, got {value!r}")
        self._access_description = value
        return self

    def support_description(self, value: str) -> Self:
        """Set ``data.supportDescription``; ``""`` clears the field (key removal)."""
        if not isinstance(value, str):
            raise DataLensValidationError(f"support_description must be a string, got {value!r}")
        self._support_description = value
        return self

    def settings(
        self,
        *,
        silent_loading: bool | _Unset | None = UNSET,
        dependent_selectors: bool | _Unset | None = UNSET,
        expand_toc: bool | _Unset | None = UNSET,
        hide_dash_title: bool | _Unset | None = UNSET,
        hide_tabs: bool | _Unset | None = UNSET,
        autoupdate_interval: int | _Unset | None = UNSET,
        max_concurrent_requests: int | _Unset | None = UNSET,
        load_priority: DashboardLoadPriority | _Unset | None = UNSET,
    ) -> Self:
        """Patch dashboard settings tri-state: omitted = untouched, ``None`` = reset to the canon, a value = set.
        Unknown existing settings keys stay verbatim."""
        for name, value in (
            ("silent_loading", silent_loading),
            ("dependent_selectors", dependent_selectors),
            ("expand_toc", expand_toc),
            ("hide_dash_title", hide_dash_title),
            ("hide_tabs", hide_tabs),
        ):
            if isinstance(value, _Unset) or value is None:
                continue
            if not isinstance(value, bool):
                raise DataLensValidationError(f"{name} must be a bool or None, got {value!r}")
        if not isinstance(autoupdate_interval, _Unset) and autoupdate_interval is not None:
            if isinstance(autoupdate_interval, bool) or not isinstance(autoupdate_interval, int):
                raise DataLensValidationError(f"autoupdate_interval must be an int, got {autoupdate_interval!r}")
            if autoupdate_interval < _MIN_AUTOUPDATE_INTERVAL:
                raise DataLensValidationError(
                    f"autoupdate_interval must be >= {_MIN_AUTOUPDATE_INTERVAL}, got {autoupdate_interval}"
                )
        if not isinstance(max_concurrent_requests, _Unset) and max_concurrent_requests is not None:
            if isinstance(max_concurrent_requests, bool) or not isinstance(max_concurrent_requests, int):
                raise DataLensValidationError(
                    f"max_concurrent_requests must be an int, got {max_concurrent_requests!r}"
                )
            if max_concurrent_requests < 1:
                raise DataLensValidationError(f"max_concurrent_requests must be >= 1, got {max_concurrent_requests}")
        if (
            not isinstance(load_priority, _Unset)
            and load_priority is not None
            and load_priority not in get_args(DashboardLoadPriority)
        ):
            raise DataLensValidationError(f"Unknown load_priority {load_priority!r}")

        updated = self._settings
        if not isinstance(silent_loading, _Unset):
            self._mark_cleared("silent_loading", cleared=silent_loading is None)
            updated = replace(updated, silent_loading=silent_loading)
        if not isinstance(dependent_selectors, _Unset):
            self._mark_cleared("dependent_selectors", cleared=dependent_selectors is None)
            updated = replace(updated, dependent_selectors=dependent_selectors)
        if not isinstance(expand_toc, _Unset):
            self._mark_cleared("expand_toc", cleared=expand_toc is None)
            updated = replace(updated, expand_toc=expand_toc)
        if not isinstance(hide_dash_title, _Unset):
            self._mark_cleared("hide_dash_title", cleared=hide_dash_title is None)
            updated = replace(updated, hide_dash_title=hide_dash_title)
        if not isinstance(hide_tabs, _Unset):
            self._mark_cleared("hide_tabs", cleared=hide_tabs is None)
            updated = replace(updated, hide_tabs=hide_tabs)
        if not isinstance(autoupdate_interval, _Unset):
            self._mark_cleared("autoupdate_interval", cleared=autoupdate_interval is None)
            updated = replace(updated, autoupdate_interval=autoupdate_interval)
        if not isinstance(max_concurrent_requests, _Unset):
            self._mark_cleared("max_concurrent_requests", cleared=max_concurrent_requests is None)
            updated = replace(updated, max_concurrent_requests=max_concurrent_requests)
        if not isinstance(load_priority, _Unset):
            self._mark_cleared("load_priority", cleared=load_priority is None)
            updated = replace(updated, load_priority=load_priority)
        self._settings = updated
        return self

    def _mark_cleared(self, field_name: str, *, cleared: bool) -> None:
        if cleared:
            self._settings_cleared.add(field_name)
        else:
            self._settings_cleared.discard(field_name)

    def global_params(self, params: Mapping[str, object]) -> Self:
        """Deep-merge ``settings.globalParams`` by key; a ``REMOVE_PARAM``
        value deletes the key. Values are normalized to lists of strings."""
        if not isinstance(params, Mapping):
            raise DataLensValidationError(f"global_params expects a mapping, got {params!r}")
        changes: dict[str, tuple[str, ...] | _RemoveParam] = {}
        for key, value in params.items():
            if not isinstance(key, str) or not key:
                raise DataLensValidationError(f"global_params keys must be non-empty strings, got {key!r}")
            if isinstance(value, _RemoveParam):
                changes[key] = value
            else:
                changes[key] = _normalize_param_values(key, value)
        if changes:
            self._ops.append(GlobalParamsOp(changes=changes))
        return self

    # -- execution -------------------------------------------------------------

    def execute(self, *, publish: bool, lock_token: str | None = None) -> Dashboard:
        """Apply the accumulated operations with a single one-phase call.

        ``publish`` is deliberately required: ``publish=True`` persists the
        data AND publishes it in one call; ``publish=False`` saves a draft
        revision. Last-write-wins — the server has no optimistic locking, a
        stale snapshot silently overwrites concurrent edits. A locked entry
        (someone edits it in the UI) raises ``LockedError`` (423): the public
        API cannot acquire locks yet, so ``lock_token`` is pass-through only.
        """
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_dashboard(self, publish=publish, lock_token=lock_token)

    # -- snapshot -------------------------------------------------------------

    @property
    def ops(self) -> tuple[DashboardUpdateOp, ...]:
        return tuple(self._ops)

    def _require_no_unclaimed_groups(self) -> None:
        if self._pending_update_groups:
            raise DataLensValidationError(
                f"Selector groups {sorted(self._pending_update_groups)!r} were registered via "
                "add_selector(group=...) but never assembled with add_group_selector"
            )

    def to_spec(self) -> DashboardUpdateSpec:
        self._require_no_unclaimed_groups()
        # every raw channel is deep-copied: the spec is an independent snapshot,
        # not a window into the builder's mutable state
        return DashboardUpdateSpec(
            dashboard_id=self._dashboard_id,
            installation=self._installation,
            location=self._location,
            name=self._name,
            data=json.loads(json.dumps(self._data)),
            meta=None if self._meta is None else json.loads(json.dumps(self._meta)),
            annotation=None if self._annotation is None else json.loads(json.dumps(self._annotation)),
            ops=tuple(self._ops),
            description=self._description,
            access_description=self._access_description,
            support_description=self._support_description,
            settings=self._settings,
            settings_cleared=frozenset(self._settings_cleared),
            generated_id_count=0 if self._allocator is None else self._allocator.generated_count,
        )
