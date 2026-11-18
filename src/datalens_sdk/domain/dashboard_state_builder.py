"""Fluent builder of a dashboard state for one dashboard tab.

The builder keeps a queue of sources (selectors, group selector members, charts); a repeated ``select`` of the same
source moves it to the end of the queue, as the UI does. ``create()`` validates the whole state against the loaded
revision and stores it with ``createEntryState``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

from typing_extensions import Self

from datalens_sdk.domain.dashboard_state import (
    STATE_META_KEY,
    STATE_VERSION,
    DashboardState,
    QueueEntry,
    StateSelection,
    find_item,
    resolve_selection,
    resolve_state_tab,
    widget_tab_ids,
)
from datalens_sdk.domain.dashboard_types import ValidationIssue
from datalens_sdk.domain.param_values import ACTION_PARAM_PREFIX, ParamOperation, encode_param_value
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

MAX_STATE_DATA_SYMBOLS = 50_000
RAW_SELECTION_KEYS = frozenset({"id", "groupItemId", "tabId", "params"})


@dataclass(frozen=True, slots=True)
class SelectorSource:
    item_id: str
    group_item_id: str | None
    member: ControlMemberView

    @property
    def label(self) -> str:
        title = f" ({self.member.title!r})" if self.member.title else ""
        member = f"/{self.group_item_id}" if self.group_item_id else ""
        return f"{self.item_id}{member}{title}"


def state_data_symbols(data: Mapping[str, object]) -> int:
    """Length of the state JSON in UTF-16 code units, as ``JSON.stringify(data).length`` counts it in US."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return len(text.encode("utf-16-le")) // 2


def selector_sources(tab: DashboardTabView) -> list[SelectorSource]:
    sources: list[SelectorSource] = []
    for control in tab.controls:
        if not control.id:
            continue
        if control.item.item_type == "group_control":
            sources.extend(SelectorSource(control.id, member.id, member) for member in control.members if member.id)
        else:
            sources.extend(SelectorSource(control.id, None, member) for member in control.members[:1])
    return sources


def member_param(member: ControlMemberView) -> str:
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


def single_match(candidates: Sequence[SelectorSource], what: str) -> SelectorSource | None:
    if len(candidates) > 1:
        raise DataLensValidationError(
            f"{what} matches several selectors: {[_.label for _ in candidates]!r}; pass a selector view or an item id"
        )
    return candidates[0] if candidates else None


class DashboardStateBuilder:
    """Build a dashboard state for one tab: ``dashboard.new_state(tab).select(...).create()``."""

    def __init__(
        self,
        dashboard: Dashboard,
        tab: str | DashboardTabView,
        entries: Sequence[QueueEntry] = (),
    ) -> None:
        self._dashboard = dashboard
        self._tab = resolve_state_tab(dashboard, tab, [])
        self._entries: list[QueueEntry] = list(entries)

    @property
    def tab_id(self) -> str:
        return self._tab.id or ""

    @property
    def selections(self) -> tuple[StateSelection, ...]:
        """The current queue resolved against the loaded revision."""
        return tuple(resolve_selection(self._tab, entry, []) for entry in self._entries)

    def select(
        self,
        target: str | ControlView | ControlMemberView | DashboardItemView | None = None,
        values: object = None,
        *,
        field: DatasetField | None = None,
        item: str | DashboardItemView | None = None,
        widget_tab: str | None = None,
        operation: ParamOperation | None = None,
    ) -> Self:
        """Select values of a source and put it at the end of the queue.

        ``target`` is an item id, a selector title or a parameter name (tried in this order), or a view of the
        loaded revision. ``field=`` finds the selector bound to that dataset field; ``item=`` with ``field=``
        selects a chart value as the action parameter ``_ap_<guid>`` (``widget_tab`` picks the chart tab). ``item=``
        without ``field=`` takes ``values`` as a mapping of chart parameters, or just switches the chart tab.
        Values are strings, sequences of strings, :class:`DateInterval`, :class:`RelativeDateInterval` or
        :class:`RelativeDate`; a mapping sets several parameters of one source.
        """
        chart = self.resolve_chart(target if item is None else item, widget_tab=widget_tab)
        if chart is not None:
            item_id, widget_tab_id = chart
            params = self.chart_params(values, field=field, operation=operation)
            return self.put(QueueEntry(item_id, None, widget_tab_id, params))
        if item is not None:
            raise DataLensValidationError(f"Item {item!r} is not a chart widget on tab {self.tab_id!r}")
        source = self.resolve_selector(target, field=field)
        params = self.selector_params(source.member, values, operation=operation)
        return self.put(QueueEntry(source.item_id, source.group_item_id, None, params))

    def clear(self, target: str | ControlView | ControlMemberView | DashboardItemView) -> Self:
        """Remove a source from the queue and the state data."""
        chart = self.resolve_chart(target, widget_tab=None)
        if chart is not None:
            key: tuple[str, str | None] = (chart[0], None)
        else:
            source = self.resolve_selector(target, field=None)
            key = (source.item_id, source.group_item_id)
        self._entries = [_ for _ in self._entries if (_.item_id, _.group_item_id) != key]
        return self

    def add(self, selection: StateSelection | Mapping[str, object]) -> Self:
        """Append a source as is: a selection of a read state or a raw ``{"id", "groupItemId", "tabId", "params"}``."""
        return self.put(raw_entry(selection))

    def prune(self) -> tuple[StateSelection, ...]:
        """Drop sources missing from the loaded revision and return them."""
        kept: list[QueueEntry] = []
        removed: list[StateSelection] = []
        for entry in self._entries:
            selection = resolve_selection(self._tab, entry, [])
            if selection.is_orphan:
                removed.append(selection)
            else:
                kept.append(entry)
        self._entries = kept
        return tuple(removed)

    def to_raw(self) -> dict[str, object]:
        """The v2 state payload: ``data[item].params`` (``params[groupItemId]`` for groups) plus ``__meta__``."""
        item_params: dict[str, dict[str, object]] = {}
        queue: list[dict[str, str]] = []
        for entry in self._entries:
            params = {key: wire_copy(value) for key, value in entry.params.items()}
            record: dict[str, str] = {"id": entry.item_id}
            if entry.group_item_id is not None:
                item_params.setdefault(entry.item_id, {})[entry.group_item_id] = params
                record["groupItemId"] = entry.group_item_id
            else:
                item_params[entry.item_id] = params
            if entry.widget_tab_id is not None:
                record["tabId"] = entry.widget_tab_id
            queue.append(record)
        data: dict[str, object] = {item_id: {"params": params} for item_id, params in item_params.items()}
        data[STATE_META_KEY] = {"queue": queue, "version": STATE_VERSION}
        return data

    def create(self) -> DashboardState:
        """Validate the state against the loaded revision, store it and return it with its hash.

        Raises :class:`DataLensValidationError` on any orphan, item outside this tab, undeclared parameter or a
        payload above 50 000 characters. Storing is idempotent: equal data gets the same hash.
        """
        issues: list[ValidationIssue] = []
        for entry in self._entries:
            resolve_selection(self._tab, entry, issues)
        problems = [self.describe(issue) for issue in issues]
        data = self.to_raw()
        size = state_data_symbols(data)
        if size > MAX_STATE_DATA_SYMBOLS:
            problems.append(f"state data has {size} characters, the limit is {MAX_STATE_DATA_SYMBOLS}")
        if problems:
            raise DataLensValidationError("Cannot create the dashboard state: " + "; ".join(problems))
        operations = self._dashboard._operations
        if operations is None:
            raise DataLensConfigurationError("Object is not bound to client operations. Use a client namespace.")
        if not self._dashboard.id:
            raise DataLensValidationError("Cannot create a state for a dashboard without an id")
        hash_value = operations.create_entry_state(self._dashboard.id, data)
        return DashboardState.from_raw(self._dashboard, data, tab=self.tab_id, hash=hash_value)

    def describe(self, issue: ValidationIssue) -> str:
        if issue.kind != "unknown_state_item" or issue.item_id is None:
            return issue.message
        owners = [_.id for _ in self._dashboard.tabs if _.id != self.tab_id and find_item(_, issue.item_id)]
        if owners:
            return f"Item {issue.item_id!r} is on tab {owners[0]!r}, not on tab {self.tab_id!r} and not global"
        return issue.message

    def put(self, entry: QueueEntry) -> Self:
        key = (entry.item_id, entry.group_item_id)
        self._entries = [_ for _ in self._entries if (_.item_id, _.group_item_id) != key]
        self._entries.append(entry)
        return self

    def resolve_chart(
        self,
        target: str | ControlView | ControlMemberView | DashboardItemView | None,
        *,
        widget_tab: str | None,
    ) -> tuple[str, str] | None:
        if isinstance(target, str):
            item = find_item(self._tab, target)
        elif view_kind(target) == "item":
            item_id = getattr(target, "id", None)
            item = find_item(self._tab, item_id) if isinstance(item_id, str) else None
            if item is None:
                raise DataLensValidationError(f"Item {item_id!r} is not on tab {self.tab_id!r}")
        else:
            return None
        if item is None or item.item_type != "widget" or not item.id:
            return None
        known = widget_tab_ids(item)
        if widget_tab is None:
            if not known:
                raise DataLensValidationError(f"Chart widget {item.id!r} has no tabs")
            return item.id, known[0]
        if widget_tab not in known:
            raise DataLensValidationError(f"Chart widget {item.id!r} has no tab {widget_tab!r}; widget tabs: {known!r}")
        return item.id, widget_tab

    def resolve_selector(
        self,
        target: str | ControlView | ControlMemberView | DashboardItemView | None,
        *,
        field: DatasetField | None,
    ) -> SelectorSource:
        sources = selector_sources(self._tab)
        if field is not None:
            if target is not None:
                raise DataLensValidationError("Pass either a target or field=, not both")
            match = single_match([_ for _ in sources if _.member.source.dataset_field_id == field.guid], "field")
            if match is None:
                raise DataLensValidationError(
                    f"No selector on tab {self.tab_id!r} is bound to field {field.title or field.guid!r}"
                )
            return match
        if target is None:
            raise DataLensValidationError("select() needs a target, field= or item=")
        if not isinstance(target, str):
            return self.source_for_view(target, sources)
        for what, candidates in (
            ("id", [_ for _ in sources if target in (_.item_id, _.group_item_id)]),
            ("title", [_ for _ in sources if _.member.title == target]),
            ("parameter", [_ for _ in sources if target in _.member.defaults]),
        ):
            match = single_match(candidates, f"{what} {target!r}")
            if match is not None:
                return match
        known = [_.label for _ in sources]
        raise DataLensValidationError(f"No selector {target!r} on tab {self.tab_id!r}; selectors: {known!r}")

    def source_for_view(
        self,
        view: ControlView | ControlMemberView | DashboardItemView,
        sources: Sequence[SelectorSource],
    ) -> SelectorSource:
        view_id = view.id
        if view_kind(view) == "member":
            candidates = [_ for _ in sources if _.member.id == view_id]
        else:
            candidates = [_ for _ in sources if _.item_id == view_id]
        match = single_match(candidates, f"view {view_id!r}")
        if match is None:
            raise DataLensValidationError(f"Selector {view_id!r} is not on tab {self.tab_id!r}")
        return match

    def selector_params(
        self,
        member: ControlMemberView,
        values: object,
        *,
        operation: ParamOperation | None,
    ) -> dict[str, object]:
        multiselect = member.source.multiselect
        is_range = member.source.is_range
        if isinstance(values, Mapping):
            return {
                key: encode_param_value(value, operation, multiselect=multiselect, is_range=is_range)
                for key, value in values.items()
            }
        return {member_param(member): encode_param_value(values, operation, multiselect=multiselect, is_range=is_range)}

    def chart_params(
        self,
        values: object,
        *,
        field: DatasetField | None,
        operation: ParamOperation | None,
    ) -> dict[str, object]:
        if field is not None:
            key = f"{ACTION_PARAM_PREFIX}{field.guid}"
            return {key: encode_param_value(values, operation, multiselect=True, is_range=False)}
        if values is None:
            return {}
        if not isinstance(values, Mapping):
            raise DataLensValidationError("Chart values need field= or a mapping of chart parameters")
        return {
            key: encode_param_value(value, operation, multiselect=not isinstance(value, str), is_range=False)
            for key, value in values.items()
        }


def view_kind(view: object) -> str:
    if hasattr(view, "source_type"):
        return "member"
    if hasattr(view, "wire_format"):
        return "control"
    if hasattr(view, "item_type"):
        return "item"
    return "unknown"


def wire_copy(value: object) -> object:
    return list(value) if isinstance(value, (list, tuple)) else value


def raw_entry(selection: StateSelection | Mapping[str, object]) -> QueueEntry:
    if isinstance(selection, StateSelection):
        return QueueEntry(selection.item_id, selection.group_item_id, selection.widget_tab_id, selection.params)
    if not isinstance(selection, Mapping):
        raise DataLensValidationError(f"A selection must be a StateSelection or a mapping, got {selection!r}")
    unknown = sorted(set(selection) - RAW_SELECTION_KEYS)
    if unknown:
        raise DataLensValidationError(f"Unknown selection keys {unknown!r}; expected {sorted(RAW_SELECTION_KEYS)!r}")
    item_id = selection.get("id")
    params = selection.get("params", {})
    if not isinstance(item_id, str) or not item_id:
        raise DataLensValidationError("A raw selection needs a non-empty 'id'")
    if not isinstance(params, Mapping) or not all(
        isinstance(key, str) and is_wire_value(value) for key, value in params.items()
    ):
        raise DataLensValidationError(
            f"'params' of selection {item_id!r} must map parameter names to strings or lists of strings"
        )
    group_item_id = optional_id(selection, "groupItemId")
    widget_tab_id = optional_id(selection, "tabId")
    return QueueEntry(item_id, group_item_id, widget_tab_id, {key: wire_copy(value) for key, value in params.items()})


def optional_id(selection: Mapping[str, object], key: str) -> str | None:
    value = selection.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise DataLensValidationError(f"{key!r} must be a non-empty string")
    return value


def is_wire_value(value: object) -> bool:
    if isinstance(value, str):
        return True
    return isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)
