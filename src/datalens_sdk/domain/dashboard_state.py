"""Read model of a saved dashboard state (``getEntryState`` data).

A v2 state is ``{item_id: {"params": ...}, "__meta__": {"version": 2, "queue": [...]}}``. Group selectors nest params
under the member id (``params[groupItemId]``); queue ``tabId`` is a tab inside a chart widget, not a dashboard tab.
The queue order is the order in which the UI applies the selections.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast
import warnings

from datalens_sdk.domain.dashboard_types import ValidationIssue
from datalens_sdk.domain.param_values import (
    ACTION_PARAM_PREFIX,
    PARAM_OPERATIONS,
    ParamOperation,
    StateValue,
    decode_param_value,
)
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import (
        ControlMemberView,
        ControlView,
        Dashboard,
        DashboardItemView,
        DashboardTabView,
    )

STATE_META_KEY = "__meta__"
STATE_VERSION = 2

StateSelectionKind = Literal["selector", "group_selector", "chart", "unknown"]


@dataclass(frozen=True, slots=True)
class StateSelection:
    """One source in the state queue: a selector, a group selector member or a chart with action params.

    ``item`` is the matching view of the loaded revision (``ControlView`` for a standalone selector,
    ``ControlMemberView`` for a group member, ``DashboardItemView`` for a chart) and ``None`` for an orphan whose
    item, group member or widget tab is missing from that revision.
    """

    item_id: str
    group_item_id: str | None
    widget_tab_id: str | None
    kind: StateSelectionKind
    item: ControlView | ControlMemberView | DashboardItemView | None
    values: tuple[StateValue, ...]

    @property
    def is_orphan(self) -> bool:
        return self.item is None

    @property
    def params(self) -> dict[str, str | list[str]]:
        """The wire params of this source, as stored in the state."""
        return {value.param: value.raw if isinstance(value.raw, str) else list(value.raw) for value in self.values}


@dataclass(frozen=True, slots=True)
class QueueEntry:
    item_id: str
    group_item_id: str | None
    widget_tab_id: str | None
    params: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class DashboardState:
    """Immutable snapshot of a dashboard state applied to one dashboard tab.

    ``selections`` follow the queue order; ``issues`` describe what does not match the loaded revision (the state
    itself is not bound to a revision). ``raw`` keeps the stored JSON verbatim.
    """

    hash: str | None
    dashboard_id: str | None
    tab_id: str
    rev_id: str | None
    version: Literal[1, 2]
    created_at: datetime | None
    selections: tuple[StateSelection, ...]
    issues: tuple[ValidationIssue, ...]
    raw: Mapping[str, object]
    _dashboard: Dashboard | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_raw(
        cls,
        dashboard: Dashboard,
        data: Mapping[str, object] | None,
        *,
        tab: str | DashboardTabView | None = None,
        hash: str | None = None,
        created_at: datetime | None = None,
        strict: bool = False,
    ) -> DashboardState:
        """Parse stored state data against the loaded dashboard revision.

        Without ``tab`` the only tab that contains every queued item is used. Problems are collected into
        ``issues`` and reported with one warning; ``strict=True`` raises :class:`DataLensValidationError` instead.
        """
        raw: Mapping[str, object] = data if data is not None else {}
        if not isinstance(raw, Mapping):
            raise DataLensValidationError(f"Dashboard state data must be an object, got {type(raw).__name__}")
        meta = raw.get(STATE_META_KEY)
        version: Literal[1, 2] = 2 if isinstance(meta, Mapping) or not has_legacy_params(raw) else 1
        entries = queue_entries(raw) if version == 2 else legacy_entries(raw)
        resolved_tab = resolve_state_tab(dashboard, tab, [entry.item_id for entry in entries])
        tab_id = resolved_tab.id or ""
        issues: list[ValidationIssue] = []
        if version == 1:
            issues.append(
                ValidationIssue(
                    "legacy_state_version",
                    tab_id,
                    None,
                    "State has no __meta__ queue (version 1); selections follow the stored key order",
                )
            )
        selections = tuple(resolve_selection(resolved_tab, entry, issues) for entry in entries)
        state = cls(
            hash=hash,
            dashboard_id=dashboard.id,
            tab_id=tab_id,
            rev_id=dashboard.rev_id,
            version=version,
            created_at=created_at,
            selections=selections,
            issues=tuple(issues),
            raw=raw,
            _dashboard=dashboard,
        )
        report_issues(state, strict=strict)
        return state


def report_issues(state: DashboardState, *, strict: bool) -> None:
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


def has_legacy_params(raw: Mapping[str, object]) -> bool:
    return any(key != STATE_META_KEY and isinstance(value, Mapping) and "params" in value for key, value in raw.items())


def item_params(raw: Mapping[str, object], item_id: str) -> Mapping[str, object]:
    entry = raw.get(item_id)
    params = entry.get("params") if isinstance(entry, Mapping) else None
    return params if isinstance(params, Mapping) else {}


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def queue_entries(raw: Mapping[str, object]) -> list[QueueEntry]:
    meta = raw.get(STATE_META_KEY)
    queue = meta.get("queue") if isinstance(meta, Mapping) else None
    entries: list[QueueEntry] = []
    queued: set[tuple[str, str | None]] = set()
    for record in queue if isinstance(queue, Sequence) and not isinstance(queue, str) else ():
        if not isinstance(record, Mapping) or optional_str(record.get("id")) is None:
            continue
        item_id = cast(str, record["id"])
        group_item_id = optional_str(record.get("groupItemId"))
        params = item_params(raw, item_id)
        if group_item_id is not None:
            group_params = params.get(group_item_id)
            params = group_params if isinstance(group_params, Mapping) else {}
        entries.append(QueueEntry(item_id, group_item_id, optional_str(record.get("tabId")), params))
        queued.add((item_id, group_item_id))
    queued_items = {item_id for item_id, _ in queued}
    for item_id in raw:
        if item_id == STATE_META_KEY or item_id in queued_items:
            continue
        params = item_params(raw, item_id)
        if params and all(isinstance(value, Mapping) for value in params.values()):
            entries.extend(
                QueueEntry(item_id, group_item_id, None, cast("Mapping[str, object]", group_params))
                for group_item_id, group_params in params.items()
            )
        else:
            entries.append(QueueEntry(item_id, None, None, params))
    return entries


def legacy_entries(raw: Mapping[str, object]) -> list[QueueEntry]:
    return [QueueEntry(item_id, None, None, item_params(raw, item_id)) for item_id in raw if item_id != STATE_META_KEY]


def tab_item_ids(tab: DashboardTabView) -> set[str]:
    return {item.id for item in (*tab.items, *tab.global_items) if item.id}


def resolve_state_tab(
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
    candidates = [candidate for candidate in tabs if wanted <= tab_item_ids(candidate)]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise DataLensValidationError(
            f"No dashboard tab contains every state item {sorted(wanted)!r}; pass tab= explicitly "
            f"(known tab ids: {known!r})"
        )
    raise DataLensValidationError(f"State items fit several tabs {[_.id for _ in candidates]!r}; pass tab= explicitly")


def find_item(tab: DashboardTabView, item_id: str) -> DashboardItemView | None:
    for item in (*tab.items, *tab.global_items):
        if item.id == item_id:
            return item
    return None


def default_operation(member: ControlMemberView | None) -> ParamOperation | None:
    operation = member.source.operation if member is not None else None
    return cast(ParamOperation, operation) if operation in PARAM_OPERATIONS else None


def decode_values(
    params: Mapping[str, object],
    member: ControlMemberView | None = None,
) -> tuple[StateValue, ...]:
    dataset_field = member is not None and member.source_type == "dataset"
    operation = default_operation(member)
    return tuple(
        decode_param_value(key, wire_value(value), operation, dataset_field=dataset_field and not is_action(key))
        for key, value in params.items()
    )


def wire_value(value: object) -> str | list[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return [item if isinstance(item, str) else str(item) for item in value]
    return str(value)


def is_action(key: str) -> bool:
    return key.startswith(ACTION_PARAM_PREFIX)


def widget_tabs(item: DashboardItemView) -> tuple[Mapping[str, object], ...]:
    tabs = item.data.get("tabs")
    if not isinstance(tabs, Sequence) or isinstance(tabs, str):
        return ()
    return tuple(tab for tab in tabs if isinstance(tab, Mapping))


def widget_tab_params(item: DashboardItemView, widget_tab_id: str | None) -> set[str]:
    keys: set[str] = set()
    for widget_tab in widget_tabs(item):
        if widget_tab_id is not None and widget_tab.get("id") != widget_tab_id:
            continue
        params = widget_tab.get("params")
        if isinstance(params, Mapping):
            keys.update(params)
    return keys


def widget_tab_ids(item: DashboardItemView) -> list[str]:
    return [tab_id for tab in widget_tabs(item) if isinstance(tab_id := tab.get("id"), str)]


def check_params(
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
                f"Parameter {value.param!r} of {owner} is not declared in the loaded revision",
                tuple(sorted(allowed)),
            )
        )


def resolve_selection(tab: DashboardTabView, entry: QueueEntry, issues: list[ValidationIssue]) -> StateSelection:
    tab_id = tab.id or ""
    item = find_item(tab, entry.item_id)
    if item is None:
        issues.append(
            ValidationIssue(
                "unknown_state_item",
                tab_id,
                entry.item_id,
                f"Item {entry.item_id!r} is not on tab {tab_id!r}",
                tuple(sorted(tab_item_ids(tab))),
            )
        )
        return StateSelection(
            entry.item_id, entry.group_item_id, entry.widget_tab_id, "unknown", None, decode_values(entry.params)
        )
    if item.item_type == "group_control":
        return resolve_group_selection(tab, item, entry, issues)
    if item.item_type == "control":
        return resolve_control_selection(tab, item, entry, issues)
    if item.item_type == "widget":
        return resolve_chart_selection(tab, item, entry, issues)
    return StateSelection(
        entry.item_id, entry.group_item_id, entry.widget_tab_id, "unknown", item, decode_values(entry.params)
    )


def resolve_group_selection(
    tab: DashboardTabView,
    item: DashboardItemView,
    entry: QueueEntry,
    issues: list[ValidationIssue],
) -> StateSelection:
    tab_id = tab.id or ""
    control = next(_ for _ in tab.controls if _.id == entry.item_id)
    member = control.member(entry.group_item_id) if entry.group_item_id is not None else None
    values = decode_values(entry.params, member)
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
        return StateSelection(entry.item_id, entry.group_item_id, entry.widget_tab_id, "group_selector", None, values)
    owner = f"group selector {entry.item_id!r} member {entry.group_item_id!r}"
    check_params(values, set(member.defaults), tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
    return StateSelection(entry.item_id, entry.group_item_id, entry.widget_tab_id, "group_selector", member, values)


def resolve_control_selection(
    tab: DashboardTabView,
    item: DashboardItemView,
    entry: QueueEntry,
    issues: list[ValidationIssue],
) -> StateSelection:
    control = next(_ for _ in tab.controls if _.id == entry.item_id)
    members = control.members
    member = members[0] if len(members) == 1 else control.member(entry.widget_tab_id or "")
    values = decode_values(entry.params, member)
    allowed = set(member.defaults) if member is not None else {key for _ in members for key in _.defaults}
    owner = f"selector {entry.item_id!r}"
    check_params(values, allowed, tab_id=tab.id or "", item_id=entry.item_id, owner=owner, issues=issues)
    return StateSelection(entry.item_id, entry.group_item_id, entry.widget_tab_id, "selector", control, values)


def resolve_chart_selection(
    tab: DashboardTabView,
    item: DashboardItemView,
    entry: QueueEntry,
    issues: list[ValidationIssue],
) -> StateSelection:
    tab_id = tab.id or ""
    values = decode_values(entry.params)
    known_tabs = widget_tab_ids(item)
    if entry.widget_tab_id is not None and entry.widget_tab_id not in known_tabs:
        issues.append(
            ValidationIssue(
                "unknown_widget_tab",
                tab_id,
                entry.item_id,
                f"Chart widget {entry.item_id!r} has no tab {entry.widget_tab_id!r}",
                tuple(known_tabs),
            )
        )
        return StateSelection(entry.item_id, entry.group_item_id, entry.widget_tab_id, "chart", None, values)
    allowed = widget_tab_params(item, entry.widget_tab_id)
    owner = f"chart widget {entry.item_id!r}"
    check_params(values, allowed, tab_id=tab_id, item_id=entry.item_id, owner=owner, issues=issues)
    return StateSelection(entry.item_id, entry.group_item_id, entry.widget_tab_id, "chart", item, values)
