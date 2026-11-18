"""Read model of a saved dashboard state, checked against the loaded dashboard revision.

The state format is the ``DashboardState`` schema (see :class:`~datalens_sdk.domain.entry_state.DashboardStateData`).
Only sources listed in ``__meta__.queue`` contribute parameters, in queue order. A chart source applies only while
its queue ``tabId`` is the active tab of the widget (``state.tabId``, else ``isDefault``, else the first tab).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlencode
import warnings

from datalens_sdk.domain.dashboard_state_effects import StateEffect, _params_for, _receivers, _resolve_usage
from datalens_sdk.domain.dashboard_state_support import (
    _active_inner_tab_id,
    _find_item,
    _has_inner_tabs,
    _inner_tab_ids,
    _inner_tab_params,
    _tab_item_ids,
)
from datalens_sdk.domain.dashboard_types import ValidationIssue
from datalens_sdk.domain.param_values import _PARAM_OPERATIONS as _PARAM_OPERATIONS
from datalens_sdk.domain.param_values import ParamOperation, StateValue, decode_param_value
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import (
        ControlMemberView,
        ControlView,
        Dashboard,
        DashboardItemView,
        DashboardTabView,
    )
    from datalens_sdk.domain.dashboard_state_builder import DashboardStateBuilder
    from datalens_sdk.domain.entry_state import DashboardStateData, StateWireValue
    from datalens_sdk.domain.runtime_params import NormalizedRuntimeParams

StateSelectionKind = Literal["selector", "group_selector", "chart", "unknown"]

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


@dataclass(frozen=True, slots=True)
class StateSelection:
    """One queued source: a selector, a selector of a group, or a chart with action params.

    ``item`` is the matching view of the loaded revision (``ControlView`` for a selector, ``ControlMemberView`` for
    a selector of a group, ``DashboardItemView`` for a chart) and ``None`` for an orphan. ``applied`` is ``False``
    when DashKit skips the source: an orphan, or a chart tab that is not the active tab of its widget.
    """

    item_id: str
    group_item_id: str | None
    widget_tab_id: str | None
    kind: StateSelectionKind
    item: ControlView | ControlMemberView | DashboardItemView | None
    values: tuple[StateValue, ...]
    applied: bool = True

    @property
    def is_orphan(self) -> bool:
        return self.item is None

    @property
    def params(self) -> dict[str, str | tuple[str, ...]]:
        """The params of this source, as stored in the state."""
        return {value.param: value.raw for value in self.values}


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    item_id: str
    group_item_id: str | None
    widget_tab_id: str | None
    params: Mapping[str, StateWireValue]


@dataclass(frozen=True, slots=True)
class DashboardState:
    """Immutable snapshot of a dashboard state applied to one dashboard tab.

    ``selections`` follow the queue; ``issues`` describe what does not match the loaded revision (the state itself
    is not bound to a revision). ``data`` is the typed state and ``raw`` the JSON it was read from or sent as.
    """

    hash: str | None
    dashboard_id: str | None
    tab_id: str
    rev_id: str | None
    version: Literal[1, 2]
    created_at: datetime | None
    selections: tuple[StateSelection, ...]
    issues: tuple[ValidationIssue, ...]
    data: DashboardStateData
    raw: Mapping[str, object] = field(default_factory=dict)
    _dashboard: Dashboard | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_data(
        cls,
        dashboard: Dashboard,
        data: DashboardStateData,
        *,
        raw: Mapping[str, object] | None = None,
        tab: str | DashboardTabView | None = None,
        hash: str | None = None,
        created_at: datetime | None = None,
        strict: bool = False,
    ) -> DashboardState:
        """Check typed state data against the loaded dashboard revision.

        Without ``tab`` the first tab that contains every queued item is used. Problems are collected into
        ``issues`` and reported with one warning; ``strict=True`` raises :class:`DataLensValidationError` instead.
        """
        entries = _state_entries(data)
        resolved_tab = _resolve_state_tab(dashboard, tab, [entry.item_id for entry in entries])
        tab_id = resolved_tab.id or ""
        issues: list[ValidationIssue] = []
        if data.version == 1:
            issues.append(
                ValidationIssue(
                    "legacy_state_version",
                    tab_id,
                    None,
                    "State has no __meta__ queue (version 1); every widget keeps only its own stored params",
                )
            )
        selections = tuple(_resolve_selection(resolved_tab, entry, data, issues) for entry in entries)
        state = cls(
            hash=hash,
            dashboard_id=dashboard.id,
            tab_id=tab_id,
            rev_id=dashboard.rev_id,
            version=data.version,
            created_at=created_at,
            selections=selections,
            issues=tuple(issues),
            data=data,
            raw=raw or {},
            _dashboard=dashboard,
        )
        _report_issues(state, strict=strict)
        return state

    def edit(self) -> DashboardStateBuilder:
        """Start a builder with a copy of this state on the same tab; ``create()`` stores a new state."""
        return self.dashboard.new_state(self.tab_id)._load(self)

    def params_for(self, item: str | ControlView | ControlMemberView | DashboardItemView) -> NormalizedRuntimeParams:
        """Parameters the item receives under this state, ready for ``get_chart_data(params=...)``.

        Follows DashKit: the active chart tab params < dashboard ``globalParams`` < selector defaults (the first
        selector in the dashboard wins) < the queue (later sources win). Sources and receivers meet within one
        ``namespace``, ``kind="ignore"`` connections between active endpoints stop delivery, ``aliases`` copy
        values, and a foreign ``_ap_<guid>`` arrives as ``<guid>``. Pass a group selector by its member id.
        """
        return _params_for(self, item)

    def effects(
        self,
        *,
        resolve_charts: bool = False,
        items: Sequence[str | ControlView | ControlMemberView | DashboardItemView] | None = None,
    ) -> tuple[StateEffect, ...]:
        """Receivers of each applied source of this state; ``items`` limits the receivers.

        By default only delivery is computed (``certainty="received"``), without HTTP. ``resolve_charts=True`` keeps
        the receivers that use the parameters: selectors by their defaults, Wizard charts by dataset field guid or
        title, QL charts by parameter name (``exact``); QL ``<name>_from``/``<name>_to`` and Editor chart tab
        params are ``declared``, and an Editor tab without params is ``unknown`` (the public API exposes no
        ``usedParams``). It sends one ``getEntries`` for the chart kinds, one request per distinct chart and one per
        distinct dataset of the Wizard charts.
        """
        effects = _receivers(self, items)
        if not resolve_charts:
            return effects
        operations = self.dashboard._operations
        if operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return _resolve_usage(self, effects, operations)

    def url(self, base: str | None = None) -> str:
        """Link that opens this state: ``{base}/{dashboard_id}?tab={tab_id}&state={hash}``.

        ``base`` defaults to the client's ``ui_base_url`` (``https://datalens.ru`` for Yandex Cloud; required for
        enterprise installations).
        """
        if not self.hash:
            raise DataLensValidationError("This state has no hash yet; store it with create() first")
        operations = self._dashboard._operations if self._dashboard is not None else None
        resolved = base or (operations.ui_base_url if operations is not None else None)
        if not resolved:
            raise DataLensConfigurationError(
                "No DataLens UI address: pass base= or create the client with ui_base_url= set to your DataLens address"
            )
        query = urlencode({"tab": self.tab_id, "state": self.hash})
        return f"{resolved.rstrip('/')}/{self.dashboard_id}?{query}"

    @property
    def dashboard(self) -> Dashboard:
        """The dashboard revision this state was read or created against."""
        if self._dashboard is None:
            raise DataLensValidationError("This state is not attached to a dashboard; read it with get_state()")
        return self._dashboard

    @property
    def tab(self) -> DashboardTabView:
        """The dashboard tab of this state in the loaded revision."""
        return _resolve_state_tab(self.dashboard, self.tab_id, [])


def _report_issues(state: DashboardState, *, strict: bool) -> None:
    if not state.issues:
        return
    details = "; ".join(f"[{issue.kind}] {issue.message}" for issue in state.issues)
    summary = (
        f"Dashboard state {state.hash or '<unsaved>'} does not fully match revision {state.rev_id or '<unknown>'} "
        f"of dashboard {state.dashboard_id or '<unknown>'} (tab {state.tab_id!r}): {details}"
    )
    if strict:
        raise DataLensValidationError(summary)
    warnings.warn(summary, UserWarning, stacklevel=4)


def _flat_params(params: object) -> Mapping[str, StateWireValue]:
    if not isinstance(params, Mapping):
        return {}
    return {key: value for key, value in params.items() if isinstance(value, (str, tuple))}


def _state_entries(data: DashboardStateData) -> list[_QueueEntry]:
    if data.version == 1:
        return [
            _QueueEntry(widget_id, None, None, _flat_params(widget.params))
            for widget_id, widget in data.widgets.items()
            if widget.params
        ]
    entries: list[_QueueEntry] = []
    for item in data.queue:
        widget = data.widgets.get(item.id)
        params: object = widget.params if widget is not None else None
        if item.group_item_id is not None:
            params = params.get(item.group_item_id) if isinstance(params, Mapping) else None
        entries.append(_QueueEntry(item.id, item.group_item_id, item.tab_id, _flat_params(params)))
    return entries


def _resolve_state_tab(
    dashboard: Dashboard,
    tab: str | DashboardTabView | None,
    item_ids: Sequence[str],
) -> DashboardTabView:
    tabs = dashboard.tabs
    known = [_.id for _ in tabs]
    if tab is not None:
        reference = tab if isinstance(tab, str) else tab.id
        if not isinstance(reference, str) or not reference:
            raise DataLensValidationError(f"tab must be a tab id, title or DashboardTabView, got {tab!r}")
        for candidate in tabs:
            if candidate.id == reference:
                return candidate
        if not isinstance(tab, str):
            raise DataLensValidationError(f"Tab {reference!r} is not part of this dashboard; known tab ids: {known!r}")
        titled = [candidate for candidate in tabs if candidate.title == reference]
        if len(titled) > 1:
            raise DataLensValidationError(
                f"Tab title {reference!r} is ambiguous (tabs {[_.id for _ in titled]!r}); use the tab id instead"
            )
        if not titled:
            raise DataLensValidationError(f"Unknown tab {reference!r}; known tab ids: {known!r}")
        return titled[0]
    wanted = set(item_ids)
    candidates = [candidate for candidate in tabs if wanted <= _tab_item_ids(candidate)]
    if not candidates:
        raise DataLensValidationError(
            f"No dashboard tab contains every state item {sorted(wanted)!r}; pass tab= explicitly "
            f"(known tab ids: {known!r})"
        )
    # Several tabs fit only when every item is global; the UI opens a link without ?tab= on the first tab.
    return candidates[0]


def _default_operation(member: ControlMemberView | None) -> ParamOperation | None:
    operation = member.source.operation if member is not None else None
    return cast(ParamOperation, operation) if operation in _PARAM_OPERATIONS else None


def _decode_values(
    params: Mapping[str, StateWireValue],
    member: ControlMemberView | None = None,
) -> tuple[StateValue, ...]:
    dataset_field = member is not None and member.source_type == "dataset"
    operation = _default_operation(member)
    return tuple(
        decode_param_value(key, value, operation, dataset_field=dataset_field and not key.startswith("_ap_"))
        for key, value in params.items()
    )


def _check_params(
    values: tuple[StateValue, ...],
    allowed: set[str],
    *,
    tab_id: str,
    item_id: str,
    owner: str,
    issues: list[ValidationIssue],
) -> None:
    for value in values:
        if value.is_action_param or value.param in allowed:
            continue
        issues.append(
            ValidationIssue(
                "unknown_state_param",
                tab_id,
                item_id,
                f"Parameter {value.param!r} of {owner} is not declared in the loaded revision and is not applied",
                tuple(sorted(allowed)),
            )
        )


def _orphan(entry: _QueueEntry, kind: StateSelectionKind) -> StateSelection:
    return StateSelection(
        entry.item_id,
        entry.group_item_id,
        entry.widget_tab_id,
        kind,
        None,
        _decode_values(entry.params),
        applied=False,
    )


def _resolve_selection(
    tab: DashboardTabView,
    entry: _QueueEntry,
    data: DashboardStateData,
    issues: list[ValidationIssue],
) -> StateSelection:
    tab_id = tab.id or ""
    item = _find_item(tab, entry.item_id)
    if item is None:
        issues.append(
            ValidationIssue(
                "unknown_state_item",
                tab_id,
                entry.item_id,
                f"Item {entry.item_id!r} is not on tab {tab_id!r}",
                tuple(sorted(_tab_item_ids(tab))),
            )
        )
        return _orphan(entry, "unknown")
    if item.item_type == "group_control":
        return _resolve_group_selection(tab, entry, issues)
    if _has_inner_tabs(item) and data.version == 2:
        return _resolve_tabbed_selection(tab, item, entry, data, issues)
    if item.item_type == "control":
        control = next(_ for _ in tab.controls if _.id == entry.item_id)
        member = control.members[0] if control.members else None
        values = _decode_values(entry.params, member)
        owner = f"selector {entry.item_id!r}"
        _check_params(values, set(item.defaults), tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
        return StateSelection(entry.item_id, None, entry.widget_tab_id, "selector", control, values)
    kind: StateSelectionKind = "chart" if item.item_type == "widget" else "unknown"
    return StateSelection(entry.item_id, None, entry.widget_tab_id, kind, item, _decode_values(entry.params))


def _resolve_group_selection(
    tab: DashboardTabView,
    entry: _QueueEntry,
    issues: list[ValidationIssue],
) -> StateSelection:
    tab_id = tab.id or ""
    control = next(_ for _ in tab.controls if _.id == entry.item_id)
    member = control.member(entry.group_item_id) if entry.group_item_id is not None else None
    if member is None:
        issues.append(
            ValidationIssue(
                "unknown_group_item",
                tab_id,
                entry.item_id,
                f"Group selector {entry.item_id!r} has no member {entry.group_item_id!r}",
                tuple(_.id for _ in control.members if _.id),
            )
        )
        return _orphan(entry, "group_selector")
    values = _decode_values(entry.params, member)
    owner = f"group selector {entry.item_id!r} member {entry.group_item_id!r}"
    _check_params(values, set(member.defaults), tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
    return StateSelection(entry.item_id, entry.group_item_id, None, "group_selector", member, values)


def _resolve_tabbed_selection(
    tab: DashboardTabView,
    item: DashboardItemView,
    entry: _QueueEntry,
    data: DashboardStateData,
    issues: list[ValidationIssue],
) -> StateSelection:
    tab_id = tab.id or ""
    kind: StateSelectionKind = "selector" if item.item_type == "control" else "chart"
    known_tabs = _inner_tab_ids(item)
    if entry.widget_tab_id is None or entry.widget_tab_id not in known_tabs:
        issues.append(
            ValidationIssue(
                "unknown_widget_tab",
                tab_id,
                entry.item_id,
                f"{'Selector' if kind == 'selector' else 'Chart widget'} {entry.item_id!r} has no tab "
                f"{entry.widget_tab_id!r}",
                tuple(known_tabs),
            )
        )
        return _orphan(entry, kind)
    control = next((_ for _ in tab.controls if _.id == entry.item_id), None) if kind == "selector" else None
    member = control.member(entry.widget_tab_id) if control is not None else None
    values = _decode_values(entry.params, member)
    allowed = set(_inner_tab_params(item, entry.widget_tab_id))
    owner = f"{'selector' if kind == 'selector' else 'chart widget'} {entry.item_id!r} tab {entry.widget_tab_id!r}"
    _check_params(values, allowed, tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
    view: ControlView | DashboardItemView = control if control is not None else item
    applied = _active_inner_tab_id(item, data) == entry.widget_tab_id
    return StateSelection(entry.item_id, None, entry.widget_tab_id, kind, view, values, applied=applied)
