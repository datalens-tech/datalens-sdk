"""Fluent builder of a dashboard state for one dashboard tab.

The builder keeps the queue of sources (selectors, selectors of groups, charts) and the widget states: choosing a
chart or tabs-selector tab sets ``state.tabId`` of that widget, as the UI does, and its queue item gets the same
``tabId``. A repeated ``select`` of the same source moves it to the end of the queue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, cast

from typing_extensions import Self

from datalens_sdk.domain.dashboard_state import (
    _PARAM_OPERATIONS,
    DashboardState,
    DashboardStateData,
    ParamOperation,
    StateOperand,
    StateParamValue,
    StateQueueItem,
    StateSelection,
    StateValue,
    StateWidget,
    StateWidgetState,
    _QueueEntry,
    _resolve_selection,
    _resolve_state_tab,
)
from datalens_sdk.domain.dashboard_state_effects import (
    _ACTION_PARAM_PREFIX,
    _active_inner_tab_id,
    _default_inner_tab_id,
    _find_item,
    _has_inner_tabs,
    _inner_tab_ids,
)
from datalens_sdk.domain.dashboard_types import (
    DateInterval,
    RelativeDate,
    RelativeDateInterval,
    ValidationIssue,
)
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import (
        ControlMemberView,
        ControlView,
        Dashboard,
        DashboardItemView,
        DashboardTabView,
    )
    from datalens_sdk.domain.fields import DatasetField

StateInputValue: TypeAlias = "str | DateInterval | RelativeDateInterval | RelativeDate"
StateInput: TypeAlias = "StateInputValue | Sequence[StateInputValue]"
"""Values of one parameter: a value or a sequence of values (a list for multiselect sources)."""

_RAW_SELECTION_KEYS = frozenset({"id", "groupItemId", "tabId", "params"})
_UNBOUND = "Object is not bound to client operations. Use a client namespace."


@dataclass(frozen=True, slots=True)
class _SelectorSource:
    item_id: str
    group_item_id: str | None
    inner_tab_id: str | None
    member: ControlMemberView

    @property
    def label(self) -> str:
        title = f" ({self.member.title!r})" if self.member.title else ""
        member = f"/{self.group_item_id or self.inner_tab_id}" if self.group_item_id or self.inner_tab_id else ""
        return f"{self.item_id}{member}{title}"


def _selector_sources(tab: DashboardTabView) -> list[_SelectorSource]:
    sources: list[_SelectorSource] = []
    for control in tab.controls:
        if not control.id:
            continue
        if control.item.item_type == "group_control":
            sources.extend(_SelectorSource(control.id, _.id, None, _) for _ in control.members if _.id)
        elif _has_inner_tabs(control.item):
            sources.extend(_SelectorSource(control.id, None, _.id, _) for _ in control.members if _.id)
        else:
            sources.extend(_SelectorSource(control.id, None, None, _) for _ in control.members[:1])
    return sources


def _member_param(member: ControlMemberView) -> str:
    source = member.source
    if member.source_type == "dataset" and source.dataset_field_id:
        return source.dataset_field_id
    if member.source_type == "manual" and source.param_name:
        return source.param_name
    keys = list(member.defaults)
    if len(keys) == 1:
        return keys[0]
    raise DataLensValidationError(
        f"Selector {member.id!r} declares parameters {keys!r}; pass values as a mapping of parameter to value"
    )


def _single_match(candidates: Sequence[_SelectorSource], what: str) -> _SelectorSource | None:
    if len(candidates) > 1:
        raise DataLensValidationError(
            f"{what} matches several selectors: {[_.label for _ in candidates]!r}; pass a selector view or an item id"
        )
    return candidates[0] if candidates else None


def _view_kind(view: object) -> str:
    if hasattr(view, "source_type"):
        return "member"
    if hasattr(view, "wire_format"):
        return "control"
    return "item" if hasattr(view, "item_type") else "unknown"


_VALUELESS_OPERATIONS = frozenset({"ISNULL", "ISNOTNULL"})


def _state_item(value: object) -> StateParamValue:
    if isinstance(value, RelativeDateInterval):
        return DateInterval(RelativeDate(value.start), RelativeDate(value.end))
    if isinstance(value, (str, DateInterval, RelativeDate)):
        return value
    raise DataLensValidationError(
        f"State values must be strings, DateInterval, RelativeDateInterval or RelativeDate, got {value!r}"
    )


def _value_items(values: object) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, DateInterval, RelativeDateInterval, RelativeDate)):
        return (values,)
    if isinstance(values, Sequence):
        return tuple(values)
    raise DataLensValidationError(f"State values must be a value or a sequence of values, got {values!r}")


def _state_value(
    param: str,
    values: object,
    operation: ParamOperation | None,
    *,
    multiselect: bool,
    is_range: bool,
    own_operation: ParamOperation | None = None,
) -> StateValue:
    """Validate a selection like the UI does and mark whether the ``__<op>_`` prefix is written.

    A selector with its own operation prefixes every value with it; otherwise only an operation other than IN
    (BETWEEN for ranges) is written.
    """
    for candidate in (operation, own_operation):
        if candidate is not None and candidate not in _PARAM_OPERATIONS:
            raise DataLensValidationError(
                f"Unknown parameter operation {candidate!r}; expected one of {sorted(_PARAM_OPERATIONS)}"
            )
    items = tuple(_state_item(_) for _ in _value_items(values))
    if is_range and (len(items) != 1 or not isinstance(items[0], DateInterval)):
        raise DataLensValidationError("A range selector takes exactly one DateInterval or RelativeDateInterval")
    implicit: ParamOperation = "BETWEEN" if is_range else "IN"
    effective = operation or own_operation
    if effective in _VALUELESS_OPERATIONS and items:
        raise DataLensValidationError(f"{effective} takes no values")
    if effective not in _VALUELESS_OPERATIONS and not multiselect and len(items) != 1:
        raise DataLensValidationError(f"A single-value source takes exactly one value, got {len(items)}")
    prefixed = effective is not None and (own_operation is not None or effective != implicit)
    operation = effective or implicit
    if effective in _VALUELESS_OPERATIONS:
        operands: tuple[StateOperand, ...] = (StateOperand(operation, None),)
    else:
        operands = tuple(StateOperand(operation, item, prefixed=prefixed and item != "") for item in items)
    return StateValue(param=param, operands=operands, multiple=multiselect)


def _wire_value(param: str, value: str | Sequence[str]) -> StateValue:
    raw: str | tuple[str, ...] = value if isinstance(value, str) else tuple(value)
    return StateValue(param, (), multiple=not isinstance(value, str), raw=raw)


def _param_pairs(values: object, default_param: str | None) -> list[tuple[str, object]]:
    if not isinstance(values, Mapping):
        if default_param is None:
            raise DataLensValidationError("Chart values need field= or a mapping of chart parameters")
        return [(default_param, values)]
    bad = [key for key in values if not isinstance(key, str) or not key]
    if bad:
        raise DataLensValidationError(f"Parameter names must be non-empty strings, got {bad!r}")
    return list(values.items())


def _is_wire_value(value: object) -> bool:
    if isinstance(value, str):
        return True
    return isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)


def _optional_id(selection: Mapping[str, object], key: str) -> str | None:
    value = selection.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise DataLensValidationError(f"{key!r} must be a non-empty string")
    return value


def _raw_entry(selection: StateSelection | Mapping[str, object]) -> _QueueEntry:
    if isinstance(selection, StateSelection):
        return _QueueEntry(selection.item_id, selection.group_item_id, selection.widget_tab_id, selection.values)
    if not isinstance(selection, Mapping):
        raise DataLensValidationError(f"A selection must be a StateSelection or a mapping, got {selection!r}")
    unknown = sorted(set(selection) - _RAW_SELECTION_KEYS)
    if unknown:
        raise DataLensValidationError(f"Unknown selection keys {unknown!r}; expected {sorted(_RAW_SELECTION_KEYS)!r}")
    item_id = selection.get("id")
    params = selection.get("params", {})
    if not isinstance(item_id, str) or not item_id:
        raise DataLensValidationError("A raw selection needs a non-empty 'id'")
    if not isinstance(params, Mapping) or not all(
        isinstance(key, str) and _is_wire_value(value) for key, value in params.items()
    ):
        raise DataLensValidationError(
            f"'params' of selection {item_id!r} must map parameter names to strings or lists of strings"
        )
    return _QueueEntry(
        item_id,
        _optional_id(selection, "groupItemId"),
        _optional_id(selection, "tabId"),
        tuple(_wire_value(key, value) for key, value in params.items()),
    )


class DashboardStateBuilder:
    """Build a dashboard state for one tab: ``dashboard.new_state(tab).select(...).create()``."""

    def __init__(self, dashboard: Dashboard, tab: str | DashboardTabView) -> None:
        self._dashboard = dashboard
        self._tab = _resolve_state_tab(dashboard, tab, [])
        self._entries: list[_QueueEntry] = []
        self._widget_states: dict[str, StateWidgetState] = {}
        self._meta_extra: Mapping[str, object] = {}

    @property
    def tab_id(self) -> str:
        return self._tab.id or ""

    @property
    def selections(self) -> tuple[StateSelection, ...]:
        """The current queue resolved against the loaded revision."""
        data = self.to_data()
        return tuple(_resolve_selection(self._tab, entry, data, []) for entry in self._entries)

    def select(
        self,
        target: str | ControlView | ControlMemberView | DashboardItemView | None = None,
        values: StateInput | Mapping[str, StateInput] | None = None,
        *,
        field: DatasetField | None = None,
        item: str | DashboardItemView | None = None,
        widget_tab: str | None = None,
        operation: ParamOperation | None = None,
    ) -> Self:
        """Select values of a source and put it at the end of the queue.

        ``target`` is an item or selector id, a selector title or a parameter name (tried in this order), or a
        view of the loaded revision. ``field=`` finds the selector bound to that dataset field; ``item=`` with
        ``field=`` selects a chart value as the action parameter ``_ap_<guid>``. ``widget_tab`` picks the chart tab
        and makes it the active one (``state.tabId``); without it the active tab is kept. ``item=`` without
        ``field=`` takes ``values`` as a mapping of chart parameters, or only switches the chart tab. Values are
        strings, sequences of strings, :class:`DateInterval`, :class:`RelativeDateInterval` or
        :class:`RelativeDate`; a mapping sets several parameters of one source. A selector with its own operation
        prefixes the values with it, as the UI does; ``operation=`` writes another one.
        """
        chart = self._resolve_chart(target if item is None else item)
        if chart is not None:
            inner_tab = self._choose_inner_tab(chart, widget_tab)
            params = self._chart_params(values, field=field, operation=operation)
            return self._put(_QueueEntry(chart.id or "", None, inner_tab, params))
        if item is not None:
            raise DataLensValidationError(f"Item {item!r} is not a chart widget on tab {self.tab_id!r}")
        source = self._resolve_selector(target, field=field)
        inner_tab = None
        if source.inner_tab_id is not None:
            control = _find_item(self._tab, source.item_id)
            inner_tab = self._choose_inner_tab(cast("DashboardItemView", control), source.inner_tab_id)
        params = self._selector_params(source.member, values, operation=operation)
        return self._put(_QueueEntry(source.item_id, source.group_item_id, inner_tab, params))

    def clear(self, target: str | ControlView | ControlMemberView | DashboardItemView) -> Self:
        """Remove a source from the queue; the widget keeps its active tab."""
        chart = self._resolve_chart(target)
        if chart is not None:
            key: tuple[str, str | None] = (chart.id or "", None)
        else:
            source = self._resolve_selector(target, field=None)
            key = (source.item_id, source.group_item_id)
        self._entries = [_ for _ in self._entries if (_.item_id, _.group_item_id) != key]
        return self

    def add(self, selection: StateSelection | Mapping[str, object]) -> Self:
        """Append a source as is: a selection of a read state or a raw ``{"id", "groupItemId", "tabId", "params"}``.

        A chart or tabs-selector source makes its tab the active one, so it keeps applying; a selection that was not
        applied in its state is added without changing the active tab.
        """
        entry = _raw_entry(selection)
        item = _find_item(self._tab, entry.item_id)
        keep_inactive = isinstance(selection, StateSelection) and not selection.applied
        if item is not None and entry.widget_tab_id in _inner_tab_ids(item) and not keep_inactive:
            self._choose_inner_tab(item, entry.widget_tab_id)
        return self._put(entry)

    def prune(self) -> tuple[StateSelection, ...]:
        """Drop sources missing from the loaded revision and return them."""
        data = self.to_data()
        kept: list[_QueueEntry] = []
        removed: list[StateSelection] = []
        for entry in self._entries:
            selection = _resolve_selection(self._tab, entry, data, [])
            if selection.is_orphan:
                removed.append(selection)
            else:
                kept.append(entry)
        self._entries = kept
        return tuple(removed)

    def to_data(self) -> DashboardStateData:
        """The state as typed data: queued params per widget (per selector for groups) and widget states."""
        params: dict[str, dict[str, object]] = {}
        for entry in self._entries:
            values = {value.param: value for value in entry.values}
            if entry.group_item_id is not None:
                params.setdefault(entry.item_id, {})[entry.group_item_id] = values
            else:
                params[entry.item_id] = dict(values)
        widget_ids = dict.fromkeys([*params, *self._widget_states])
        widgets = {
            widget_id: StateWidget(
                params=cast("Mapping[str, StateValue]", params[widget_id]) if widget_id in params else None,
                state=self._widget_states.get(widget_id),
            )
            for widget_id in widget_ids
        }
        queue = tuple(StateQueueItem(_.item_id, _.group_item_id, _.widget_tab_id) for _ in self._entries)
        return DashboardStateData(version=2, queue=queue, widgets=widgets, meta_extra=self._meta_extra)

    def create(self) -> DashboardState:
        """Validate the state against the loaded revision, store it and return it with its hash.

        Raises :class:`DataLensValidationError` on any orphan, item outside this tab, undeclared parameter or a
        payload above 50 000 characters. Storing is idempotent: equal data gets the same hash.
        """
        data = self.to_data()
        issues: list[ValidationIssue] = []
        for entry in self._entries:
            _resolve_selection(self._tab, entry, data, issues)
        if issues:
            problems = "; ".join(self._describe(issue) for issue in issues)
            raise DataLensValidationError(f"Cannot create the dashboard state: {problems}")
        operations = self._dashboard._operations
        if operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self._dashboard.id:
            raise DataLensValidationError("Cannot create a state for a dashboard without an id")
        record = operations.create_dashboard_state(self._dashboard.id, data)
        return DashboardState.from_data(self._dashboard, record.data, raw=record.raw, tab=self.tab_id, hash=record.hash)

    def _load(self, state: DashboardState) -> Self:
        self._entries = [_raw_entry(selection) for selection in state.selections]
        self._widget_states = {
            widget_id: widget.state for widget_id, widget in state.data.widgets.items() if widget.state is not None
        }
        self._meta_extra = state.data.meta_extra
        return self

    def _describe(self, issue: ValidationIssue) -> str:
        if issue.kind != "unknown_state_item" or issue.item_id is None:
            return issue.message
        owners = [_.id for _ in self._dashboard.tabs if _.id != self.tab_id and _find_item(_, issue.item_id)]
        if owners:
            return f"Item {issue.item_id!r} is on tab {owners[0]!r}, not on tab {self.tab_id!r} and not global"
        return issue.message

    def _put(self, entry: _QueueEntry) -> Self:
        key = (entry.item_id, entry.group_item_id)
        self._entries = [_ for _ in self._entries if (_.item_id, _.group_item_id) != key]
        self._entries.append(entry)
        return self

    def _choose_inner_tab(self, item: DashboardItemView, inner_tab: str | None) -> str | None:
        known = _inner_tab_ids(item)
        if inner_tab is None:
            return _active_inner_tab_id(item, self.to_data())
        if inner_tab not in known:
            raise DataLensValidationError(f"Item {item.id!r} has no tab {inner_tab!r}; its tabs: {known!r}")
        current = self._widget_states.get(item.id or "", StateWidgetState())
        tab_id = None if inner_tab == _default_inner_tab_id(item) else inner_tab
        if tab_id is None and not current.extra:
            self._widget_states.pop(item.id or "", None)
        else:
            self._widget_states[item.id or ""] = StateWidgetState(tab_id=tab_id, extra=current.extra)
        return inner_tab

    def _resolve_chart(
        self,
        target: str | ControlView | ControlMemberView | DashboardItemView | None,
    ) -> DashboardItemView | None:
        if isinstance(target, str):
            item = _find_item(self._tab, target)
        elif _view_kind(target) == "item":
            item_id = getattr(target, "id", None)
            item = _find_item(self._tab, item_id) if isinstance(item_id, str) else None
            if item is None:
                raise DataLensValidationError(f"Item {item_id!r} is not on tab {self.tab_id!r}")
        else:
            return None
        if item is None or item.item_type != "widget" or not item.id:
            return None
        if not _inner_tab_ids(item):
            raise DataLensValidationError(f"Chart widget {item.id!r} has no tabs")
        return item

    def _resolve_selector(
        self,
        target: str | ControlView | ControlMemberView | DashboardItemView | None,
        *,
        field: DatasetField | None,
    ) -> _SelectorSource:
        sources = _selector_sources(self._tab)
        if field is not None:
            if target is not None:
                raise DataLensValidationError("Pass either a target or field=, not both")
            match = _single_match([_ for _ in sources if _.member.source.dataset_field_id == field.guid], "field")
            if match is None:
                raise DataLensValidationError(
                    f"No selector on tab {self.tab_id!r} is bound to field {field.title or field.guid!r}"
                )
            return match
        if target is None:
            raise DataLensValidationError("select() needs a target, field= or item=")
        if not isinstance(target, str):
            return self._source_for_view(target, sources)
        for what, candidates in (
            ("id", [_ for _ in sources if target in (_.item_id, _.group_item_id, _.inner_tab_id)]),
            ("title", [_ for _ in sources if _.member.title == target]),
            ("parameter", [_ for _ in sources if target in _.member.defaults]),
        ):
            match = _single_match(candidates, f"{what} {target!r}")
            if match is not None:
                return match
        known = [_.label for _ in sources]
        raise DataLensValidationError(f"No selector {target!r} on tab {self.tab_id!r}; selectors: {known!r}")

    def _source_for_view(
        self,
        view: ControlView | ControlMemberView | DashboardItemView,
        sources: Sequence[_SelectorSource],
    ) -> _SelectorSource:
        view_id = view.id
        if _view_kind(view) == "member":
            candidates = [_ for _ in sources if _.member.id == view_id]
        else:
            candidates = [_ for _ in sources if _.item_id == view_id]
        match = _single_match(candidates, f"view {view_id!r}")
        if match is None:
            raise DataLensValidationError(f"Selector {view_id!r} is not on tab {self.tab_id!r}")
        return match

    def _selector_params(
        self,
        member: ControlMemberView,
        values: object,
        *,
        operation: ParamOperation | None,
    ) -> tuple[StateValue, ...]:
        source = member.source
        own = cast("ParamOperation | None", source.operation if source.operation in _PARAM_OPERATIONS else None)
        return tuple(
            _state_value(
                key,
                value,
                operation,
                multiselect=source.multiselect,
                is_range=source.is_range,
                own_operation=own,
            )
            for key, value in _param_pairs(values, _member_param(member) if not isinstance(values, Mapping) else None)
        )

    def _chart_params(
        self,
        values: object,
        *,
        field: DatasetField | None,
        operation: ParamOperation | None,
    ) -> tuple[StateValue, ...]:
        if field is not None:
            key = f"{_ACTION_PARAM_PREFIX}{field.guid}"
            return (_state_value(key, values, operation, multiselect=True, is_range=False),)
        if values is None:
            return ()
        return tuple(
            _state_value(key, value, operation, multiselect=not isinstance(value, str), is_range=False)
            for key, value in _param_pairs(values, None)
        )
