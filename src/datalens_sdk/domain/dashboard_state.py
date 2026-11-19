"""Dashboard states: the typed ``DashboardState`` schema and its check against the loaded dashboard revision.

Only sources listed in ``__meta__.queue`` contribute parameters, in queue order. A chart source applies only while
its queue ``tabId`` is the active tab of the widget (``state.tabId``, else ``isDefault``, else the first tab).
Wire encoding of values (``__<op>_``, ``__interval_``, ``__relative_``) belongs to the converter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeAlias, cast, get_args
from urllib.parse import urlencode
import warnings

from datalens_sdk.domain.chart_types import FilterOperation
from datalens_sdk.domain.dashboard_state_effects import (
    _ACTION_PARAM_PREFIX,
    StateEffect,
    _active_inner_tab_id,
    _find_item,
    _group_members,
    _has_inner_tabs,
    _inner_tab_ids,
    _inner_tab_params,
    _inner_tabs,
    _optional_str,
    _params_for,
    _receivers,
    _resolve_usage,
    _tab_item_ids,
    _tab_items,
)
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDate, ValidationIssue
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
    from datalens_sdk.domain.runtime_params import NormalizedRuntimeParams

ParamOperation: TypeAlias = Literal[
    FilterOperation,
    "NIN",
    "ICONTAINS",
    "NOTCONTAINS",
    "NOTICONTAINS",
    "ISTARTSWITH",
    "ENDSWITH",
    "IENDSWITH",
    "LENEQ",
    "LENGT",
    "LENGTE",
    "LENLT",
    "LENLTE",
]
StateParamValue: TypeAlias = "str | DateInterval | RelativeDate"
StateSelectionKind = Literal["selector", "group_selector", "chart", "unknown"]

_PARAM_OPERATIONS: frozenset[str] = frozenset(get_args(ParamOperation))
_UNBOUND = "Object is not bound to client operations. Use a client namespace."


def _freeze(value: object) -> object:
    """Deep read-only copy of JSON-shaped data: mappings become proxies, lists become tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    """Independent JSON-shaped copy of frozen data."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _frozen_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return cast("Mapping[str, object]", _freeze(value))


@dataclass(frozen=True, slots=True)
class StateOperand:
    """One stored value of a parameter.

    ``operation`` is the ``__<op>_`` prefix written on the wire, ``None`` for an unprefixed value; ``value`` is
    ``None`` for ISNULL and ISNOTNULL. ``effective_operation`` is what charts apply, following Wizard
    ``prepareArrayFilterValues``: an interval is BETWEEN whatever its prefix, an unprefixed value is IN. Wizard also
    turns a single unprefixed value of a date field into EQ, which depends on the receiving field.
    """

    operation: ParamOperation | None
    value: StateParamValue | None

    @property
    def effective_operation(self) -> ParamOperation:
        if isinstance(self.value, DateInterval):
            return "BETWEEN"
        if isinstance(self.value, str) and self.value.startswith("__interval_"):
            # Wizard resolves interval forms the SDK keeps as strings (``now-7d``, ISO offsets) as BETWEEN too.
            return "BETWEEN"
        return self.operation or "IN"


@dataclass(frozen=True, slots=True)
class StateValue:
    """One parameter of a state source: its operands in wire order.

    ``multiple`` keeps a list on the wire; ``raw`` is the stored wire value of a state that was read or created.
    """

    param: str
    operands: tuple[StateOperand, ...]
    multiple: bool = False
    raw: str | tuple[str, ...] | None = None
    dataset_field: bool = False

    @property
    def values(self) -> tuple[StateParamValue, ...]:
        return tuple(operand.value for operand in self.operands if operand.value is not None)

    @property
    def operation(self) -> ParamOperation | None:
        """The effective operation shared by every operand, or ``None`` when they differ or there are none."""
        operations = {operand.effective_operation for operand in self.operands}
        return next(iter(operations)) if len(operations) == 1 else None

    @property
    def is_action_param(self) -> bool:
        return self.param.startswith(_ACTION_PARAM_PREFIX)

    @property
    def field_guid(self) -> str | None:
        if self.is_action_param:
            return self.param[len(_ACTION_PARAM_PREFIX) :]
        return self.param if self.dataset_field else None


StateWidgetParams: TypeAlias = "Mapping[str, StateValue] | Mapping[str, Mapping[str, StateValue]]"


@dataclass(frozen=True, slots=True)
class StateQueueItem:
    """One ``__meta__.queue`` item: a widget, a selector of a group (``group_item_id``) or a chart tab (``tab_id``)."""

    id: str
    group_item_id: str | None = None
    tab_id: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", _frozen_mapping(self.extra))


@dataclass(frozen=True, slots=True)
class StateWidgetState:
    """The ``state`` of a widget entry: the active chart tab and any other widget settings."""

    tab_id: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", _frozen_mapping(self.extra))


@dataclass(frozen=True, slots=True)
class StateWidget:
    """One widget entry of a dashboard state; ``params`` is ``None`` when the entry stores none."""

    params: StateWidgetParams | None = None
    state: StateWidgetState | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.params is not None:
            object.__setattr__(self, "params", _freeze(self.params))
        object.__setattr__(self, "extra", _frozen_mapping(self.extra))


@dataclass(frozen=True, slots=True)
class DashboardStateData:
    """A dashboard state as the ``DashboardState`` schema describes it, keyed by widget id. Read-only."""

    version: Literal[1, 2]
    queue: tuple[StateQueueItem, ...]
    widgets: Mapping[str, StateWidget]
    meta_extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "queue", tuple(self.queue))
        object.__setattr__(self, "widgets", MappingProxyType(dict(self.widgets)))
        object.__setattr__(self, "meta_extra", _frozen_mapping(self.meta_extra))


@dataclass(frozen=True, slots=True)
class DashboardStateRecord:
    """A stored dashboard state: typed ``data`` and the JSON object it was read from or sent as."""

    hash: str
    data: DashboardStateData
    raw: Mapping[str, object]
    created_at: datetime | None = None


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
        """The stored wire params of this source (values not stored yet are left out)."""
        return {value.param: value.raw for value in self.values if value.raw is not None}


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    item_id: str
    group_item_id: str | None
    widget_tab_id: str | None
    values: tuple[StateValue, ...]
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DashboardState:
    """Immutable snapshot of a dashboard state applied to one dashboard tab.

    ``selections`` follow the queue; ``issues`` describe what does not match the loaded revision (the state itself
    is not bound to a revision). ``data`` is the typed state and ``raw`` the JSON it was read from or sent as.
    Lookups such as ``tab``, ``active_chart_id()``, ``params_for()`` and ``effects()`` read the attached
    ``Dashboard`` object, which is not copied: keep it unchanged, or read the state again after reloading it.
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
    _raw: Mapping[str, object] = field(default_factory=dict, repr=False)
    _dashboard: Dashboard | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_raw", _frozen_mapping(self._raw))

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

        Without ``tab`` the first tab that contains every queued item is used (the only tab of a one-tab
        dashboard); when no tab fits, :class:`DataLensValidationError` is raised before any issue is collected,
        whatever ``strict`` is. Problems are collected into
        ``issues`` and reported with one warning; ``strict=True`` raises :class:`DataLensValidationError` instead.
        """
        if any(value.raw is None or (not value.operands and value.raw != ()) for value in _stored_values(data)):
            raise DataLensValidationError(
                "State data holds values that are not stored yet; store them with DashboardStateBuilder.create() "
                "and read the returned state"
            )
        entries = _state_entries(data)
        resolved_tab = _resolve_state_tab(dashboard, tab, [entry.item_id for entry in entries])
        tab_id = resolved_tab.id or ""
        issues: list[ValidationIssue] = []
        if data.version == 1:
            message = "State has no __meta__ queue (version 1); every widget keeps only its own stored params"
            issues.append(ValidationIssue("legacy_state_version", tab_id, None, message))
        if data.version == 1:
            entries = [_legacy_member_entry(resolved_tab, entry) for entry in entries]
        selections = tuple(_resolve_selection(resolved_tab, entry, data, issues) for entry in entries)
        _check_widget_states(resolved_tab, data, issues)
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
            _raw=raw or {},
            _dashboard=dashboard,
        )
        _report_issues(state, strict=strict)
        return state

    def edit(self) -> DashboardStateBuilder:
        """Start a builder with a copy of this state on the same tab; ``create()`` stores a new state.

        A version 1 state keeps params per widget, which a version 2 queue cannot express. Migrate it by building
        a new state and choosing each source explicitly, for example
        ``dashboard.new_state(tab).select(item="<chart>", widget_tab="<tab>", field=field, values=[...])`` for a
        chart click, since a version 1 chart source records no widget tab.
        """
        if self.version == 1:
            raise DataLensValidationError(
                "A version 1 state keeps params per widget and cannot be edited as a queue; build a new state with "
                "dashboard.new_state() or dashboard.create_state() instead"
            )
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
    def raw(self) -> dict[str, object]:
        """An independent copy of the JSON the state was read from or sent as."""
        return cast("dict[str, object]", _thaw(self._raw))

    def active_chart_id(self, item: str | DashboardItemView) -> str | None:
        """Saved chart id of the widget tab this state shows: ``state.tabId``, else ``isDefault``, else the first."""
        item_id = item if isinstance(item, str) else item.id
        widget = _find_item(self.tab, item_id or "")
        if widget is None or widget.item_type != "widget":
            raise DataLensValidationError(f"Item {item_id!r} is not a chart widget on tab {self.tab_id!r}")
        active = _active_inner_tab_id(widget, self.data)
        tab = next((_ for _ in _inner_tabs(widget) if _.get("id") == active), None)
        chart_id = tab.get("chartId") if tab is not None else None
        return chart_id if isinstance(chart_id, str) else None

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


def _stored_values(data: DashboardStateData) -> list[StateValue]:
    values: list[StateValue] = []
    for widget in data.widgets.values():
        for value in (widget.params or {}).values():
            values.extend(value.values() if isinstance(value, Mapping) else [value])
    return values


def _flat_values(params: object) -> tuple[StateValue, ...]:
    if not isinstance(params, Mapping):
        return ()
    return tuple(value for value in params.values() if isinstance(value, StateValue))


def _state_entries(data: DashboardStateData) -> list[_QueueEntry]:
    if data.version == 1:
        return [
            _QueueEntry(widget_id, None, None, _flat_values(widget.params))
            for widget_id, widget in data.widgets.items()
            if widget.params
        ]
    entries: list[_QueueEntry] = []
    for item in data.queue:
        widget = data.widgets.get(item.id)
        params: object = widget.params if widget is not None else None
        if item.group_item_id is not None:
            params = params.get(item.group_item_id) if isinstance(params, Mapping) else None
        entries.append(_QueueEntry(item.id, item.group_item_id, item.tab_id, _flat_values(params), item.extra))
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
    candidates = [candidate for candidate in tabs if wanted <= _tab_source_ids(candidate)]
    if not candidates and len(tabs) == 1:
        return tabs[0]
    if not candidates:
        raise DataLensValidationError(
            f"No dashboard tab contains every state item {sorted(wanted)!r}; pass tab= explicitly "
            f"(known tab ids: {known!r})"
        )
    # Several tabs fit only when every item is global; the UI opens a link without ?tab= on the first tab.
    return candidates[0]


def _bind_values(values: tuple[StateValue, ...], member: ControlMemberView | None = None) -> tuple[StateValue, ...]:
    """Mark dataset field keys; operands keep the operations charts apply to them."""
    dataset = member is not None and member.source_type == "dataset"
    return tuple(replace(value, dataset_field=dataset and not value.is_action_param) for value in values)


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
        message = f"Parameter {value.param!r} of {owner} is not declared in the loaded revision and is not applied"
        issues.append(ValidationIssue("unknown_state_param", tab_id, item_id, message, tuple(sorted(allowed))))


def _orphan(entry: _QueueEntry, kind: StateSelectionKind) -> StateSelection:
    return StateSelection(
        entry.item_id, entry.group_item_id, entry.widget_tab_id, kind, None, _bind_values(entry.values), applied=False
    )


def _tab_source_ids(tab: DashboardTabView) -> set[str]:
    """Item ids of the tab plus the selector ids of its groups (version 1 states key group selectors by them)."""
    ids = _tab_item_ids(tab)
    for item in _tab_items(tab):
        if item.item_type == "group_control":
            ids.update(member_id for member in _group_members(item) if (member_id := _optional_str(member.get("id"))))
    return ids


def _legacy_member_entry(tab: DashboardTabView, entry: _QueueEntry) -> _QueueEntry:
    if _find_item(tab, entry.item_id) is not None:
        return entry
    for item in _tab_items(tab):
        if item.item_type == "group_control" and any(_.get("id") == entry.item_id for _ in _group_members(item)):
            return replace(entry, item_id=item.id or "", group_item_id=entry.item_id)
    return entry


def _check_widget_states(tab: DashboardTabView, data: DashboardStateData, issues: list[ValidationIssue]) -> None:
    for widget_id, widget in data.widgets.items():
        item = _find_item(tab, widget_id)
        tab_id = widget.state.tab_id if widget.state is not None else None
        if item is None or tab_id is None or not _has_inner_tabs(item) or tab_id in _inner_tab_ids(item):
            continue
        message = f"Widget {widget_id!r} has no tab {tab_id!r} from state.tabId; the dashboard shows its default tab"
        issues.append(
            ValidationIssue("unknown_widget_tab", tab.id or "", widget_id, message, tuple(_inner_tab_ids(item)))
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
        message = f"Item {entry.item_id!r} is not on tab {tab_id!r}"
        issues.append(
            ValidationIssue("unknown_state_item", tab_id, entry.item_id, message, tuple(sorted(_tab_item_ids(tab))))
        )
        return _orphan(entry, "unknown")
    if item.item_type == "group_control":
        return _resolve_group_selection(tab, entry, issues)
    if entry.group_item_id is not None:
        # DashKit reads groupItemId only for selector groups; other items take their flat params.
        message = (
            f"Item {entry.item_id!r} is not a selector group, so its groupItemId {entry.group_item_id!r} is invalid"
        )
        issues.append(ValidationIssue("unknown_group_item", tab_id, entry.item_id, message))
        return _orphan(entry, "chart" if item.item_type == "widget" else "unknown")
    if _has_inner_tabs(item) and data.version == 2:
        return _resolve_tabbed_selection(tab, item, entry, data, issues)
    if item.item_type == "control":
        control = next(_ for _ in tab.controls if _.id == entry.item_id)
        values = _bind_values(entry.values, control.members[0] if control.members else None)
        owner = f"selector {entry.item_id!r}"
        _check_params(values, set(item.defaults), tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
        return StateSelection(entry.item_id, None, entry.widget_tab_id, "selector", control, values)
    kind: StateSelectionKind = "chart" if item.item_type == "widget" else "unknown"
    values = _bind_values(entry.values)
    if kind == "unknown":
        owner = f"{item.item_type or 'item'} {entry.item_id!r}"
        _check_params(values, set(item.defaults), tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
    return StateSelection(entry.item_id, None, entry.widget_tab_id, kind, item, values)


def _resolve_group_selection(
    tab: DashboardTabView,
    entry: _QueueEntry,
    issues: list[ValidationIssue],
) -> StateSelection:
    tab_id = tab.id or ""
    control = next(_ for _ in tab.controls if _.id == entry.item_id)
    member = control.member(entry.group_item_id) if entry.group_item_id is not None else None
    if member is None:
        message = f"Group selector {entry.item_id!r} has no member {entry.group_item_id!r}"
        members = tuple(_.id for _ in control.members if _.id)
        issues.append(ValidationIssue("unknown_group_item", tab_id, entry.item_id, message, members))
        return _orphan(entry, "group_selector")
    values = _bind_values(entry.values, member)
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
    noun = "Selector" if kind == "selector" else "Chart widget"
    known_tabs = _inner_tab_ids(item)
    if entry.widget_tab_id is None or entry.widget_tab_id not in known_tabs:
        message = f"{noun} {entry.item_id!r} has no tab {entry.widget_tab_id!r}"
        issues.append(ValidationIssue("unknown_widget_tab", tab_id, entry.item_id, message, tuple(known_tabs)))
        return _orphan(entry, kind)
    control = next((_ for _ in tab.controls if _.id == entry.item_id), None) if kind == "selector" else None
    values = _bind_values(entry.values, control.member(entry.widget_tab_id) if control is not None else None)
    owner = f"{noun.lower()} {entry.item_id!r} tab {entry.widget_tab_id!r}"
    allowed = set(_inner_tab_params(item, entry.widget_tab_id))
    _check_params(values, allowed, tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
    view: ControlView | DashboardItemView = control if control is not None else item
    applied = _active_inner_tab_id(item, data) == entry.widget_tab_id
    return StateSelection(entry.item_id, None, entry.widget_tab_id, kind, view, values, applied=applied)
