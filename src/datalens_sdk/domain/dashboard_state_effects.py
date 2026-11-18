"""Which dashboard items receive the parameters of a state, following the dashkit delivery rules.

Parameters travel inside one ``namespace``. A connection ``{"from": R, "to": S, "kind": "ignore"}`` stops R
receiving the parameters of S (endpoints are item, selector member or chart tab ids). ``aliases[namespace]`` groups
parameter names that receive the same value. A chart's own ``_ap_<guid>`` action parameter reaches other items as
``<guid>``. Matching parameter names alone never decides delivery.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from datalens_sdk.domain.dashboard_state_items import find_item, optional_str, widget_tab_ids, widget_tabs
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.param_values import ACTION_PARAM_PREFIX
from datalens_sdk.domain.ql_chart import QLChart
from datalens_sdk.domain.runtime_params import NormalizedRuntimeParams
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import DashboardItemView, DashboardTabView
    from datalens_sdk.domain.dashboard_state import DashboardState, StateSelection
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.ports import DashboardOperations

DEFAULT_NAMESPACE = "default"
RECEIVER_TYPES = frozenset({"widget", "control", "group_control"})
SELECTOR_TYPES = frozenset({"control", "group_control"})
QL_INTERVAL_TYPE = "date-interval"

EffectCertainty = Literal["received", "exact", "declared", "unknown"]
EffectMatch = Literal["guid", "title"]


@dataclass(frozen=True, slots=True)
class StateEffect:
    """A receiver of a state source and the parameter names it gets.

    ``certainty`` is ``"received"`` when only delivery is known. With ``resolve_charts=True`` it tells whether the
    receiver uses the parameters: ``"exact"`` (selector defaults, dataset field guid or title, QL parameter),
    ``"declared"`` (Editor chart tab params) or ``"unknown"``; ``matched_by`` says how a dataset field matched.
    """

    selection: StateSelection
    receiver: DashboardItemView
    params: tuple[str, ...]
    certainty: EffectCertainty
    matched_by: EffectMatch | None = None


def state_tab(state: DashboardState) -> DashboardTabView:
    for tab in state.dashboard.tabs:
        if tab.id == state.tab_id:
            return tab
    raise DataLensValidationError(f"Tab {state.tab_id!r} is missing from the loaded dashboard revision")


def receiver_items(tab: DashboardTabView) -> list[DashboardItemView]:
    seen: set[str] = set()
    items: list[DashboardItemView] = []
    for item in (*tab.items, *tab.global_items):
        if item.item_type in RECEIVER_TYPES and item.id and item.id not in seen:
            seen.add(item.id)
            items.append(item)
    return items


def group_members(item: DashboardItemView) -> tuple[Mapping[str, object], ...]:
    group = item.data.get("group")
    if not isinstance(group, Sequence) or isinstance(group, str):
        return ()
    return tuple(member for member in group if isinstance(member, Mapping))


def item_namespace(item: DashboardItemView) -> str:
    return item.namespace or DEFAULT_NAMESPACE


def member_namespace(member: Mapping[str, object], item: DashboardItemView) -> str:
    return optional_str(member.get("namespace")) or item_namespace(item)


def item_endpoints(item: DashboardItemView) -> set[str]:
    ids = {item.id} if item.id else set()
    ids.update(widget_tab_ids(item))
    ids.update(member_id for member in group_members(item) if (member_id := optional_str(member.get("id"))))
    return ids


def source_endpoints(selection: StateSelection) -> set[str]:
    return {_ for _ in (selection.item_id, selection.group_item_id, selection.widget_tab_id) if _}


def ignored(tab: DashboardTabView, *, receiver: set[str], source: set[str]) -> bool:
    return any(
        connection.get("kind") == "ignore" and connection.get("from") in receiver and connection.get("to") in source
        for connection in tab.connections
    )


def alias_groups(tab: DashboardTabView, namespace: str) -> list[set[str]]:
    groups = tab.aliases.get(namespace)
    if not isinstance(groups, Sequence) or isinstance(groups, str):
        return []
    return [
        {name for name in group if isinstance(name, str)}
        for group in groups
        if isinstance(group, Sequence) and not isinstance(group, str)
    ]


def wire(value: object) -> str | tuple[str, ...]:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return tuple(item if isinstance(item, str) else str(item) for item in value)
    return str(value)


def delivered(
    params: Mapping[str, object],
    *,
    own: bool,
    aliases: list[set[str]],
) -> dict[str, str | tuple[str, ...]]:
    result: dict[str, str | tuple[str, ...]] = {}
    for key, value in params.items():
        name = key if own or not key.startswith(ACTION_PARAM_PREFIX) else key[len(ACTION_PARAM_PREFIX) :]
        value = wire(value)
        result[name] = value
        for group in aliases:
            if name in group:
                result.update(dict.fromkeys(group, value))
    return result


def resolve_item(tab: DashboardTabView, ref: object) -> DashboardItemView:
    ref_id = ref if isinstance(ref, str) else getattr(ref, "id", None)
    if not isinstance(ref_id, str) or not ref_id:
        raise DataLensValidationError(f"Expected an item id or a dashboard view, got {ref!r}")
    item = find_item(tab, ref_id)
    if item is None:
        item = next((_ for _ in receiver_items(tab) if ref_id in item_endpoints(_)), None)
    if item is None:
        raise DataLensValidationError(f"Item {ref_id!r} is not on tab {tab.id!r}")
    return item


def current_widget_tab(state: DashboardState, item: DashboardItemView) -> Mapping[str, object] | None:
    chosen = next(
        (_.widget_tab_id for _ in reversed(state.selections) if _.item_id == item.id and _.widget_tab_id),
        None,
    )
    tabs = widget_tabs(item)
    return next((_ for _ in tabs if _.get("id") == chosen), tabs[0] if tabs else None)


def own_defaults(state: DashboardState, item: DashboardItemView) -> Mapping[str, object]:
    if item.item_type != "widget":
        return {}
    widget_tab = current_widget_tab(state, item)
    params = widget_tab.get("params") if widget_tab is not None else None
    return params if isinstance(params, Mapping) else {}


def params_for(state: DashboardState, item: object) -> NormalizedRuntimeParams:
    """Parameters the receiver ends up with: ``globalParams`` < namespace defaults < queue, in queue order."""
    tab = state_tab(state)
    receiver = resolve_item(tab, item)
    namespace = item_namespace(receiver)
    aliases = alias_groups(tab, namespace)
    receiver_ids = item_endpoints(receiver)
    settings = state.dashboard.data.get("settings")
    global_params = settings.get("globalParams") if isinstance(settings, Mapping) else None
    result: dict[str, str | tuple[str, ...]] = {}
    if isinstance(global_params, Mapping):
        result.update(delivered(global_params, own=True, aliases=aliases))
    for source in receiver_items(tab):
        own = source.id == receiver.id
        if source.item_type == "group_control":
            for member in group_members(source):
                member_id = optional_str(member.get("id"))
                if member_namespace(member, source) != namespace:
                    continue
                if not own and ignored(tab, receiver=receiver_ids, source={member_id} if member_id else set()):
                    continue
                defaults = member.get("defaults")
                if isinstance(defaults, Mapping):
                    result.update(delivered(defaults, own=own, aliases=aliases))
            continue
        if item_namespace(source) != namespace:
            continue
        if not own and ignored(tab, receiver=receiver_ids, source=item_endpoints(source)):
            continue
        defaults = own_defaults(state, source) if source.item_type == "widget" else source.defaults
        result.update(delivered(defaults, own=own, aliases=aliases))
    for selection in state.selections:
        if not reaches(tab, selection, receiver, namespace=namespace, receiver_ids=receiver_ids):
            continue
        own = selection.item_id == receiver.id
        result.update(delivered(selection.params, own=own, aliases=aliases))
    return MappingProxyType(result)


def selection_namespace(tab: DashboardTabView, selection: StateSelection) -> str | None:
    item = find_item(tab, selection.item_id)
    if item is None:
        return None
    if selection.group_item_id is not None:
        member = next((_ for _ in group_members(item) if _.get("id") == selection.group_item_id), None)
        return member_namespace(member, item) if member is not None else None
    return item_namespace(item)


def reaches(
    tab: DashboardTabView,
    selection: StateSelection,
    receiver: DashboardItemView,
    *,
    namespace: str,
    receiver_ids: set[str],
) -> bool:
    if selection.is_orphan or selection_namespace(tab, selection) != namespace:
        return False
    if selection.item_id == receiver.id:
        return True
    return not ignored(tab, receiver=receiver_ids, source=source_endpoints(selection))


def receivers(
    state: DashboardState,
    items: Sequence[object] | None = None,
) -> tuple[StateEffect, ...]:
    """Every (source, receiver) pair of the state with the parameter names the receiver gets."""
    tab = state_tab(state)
    candidates = receiver_items(tab) if items is None else [resolve_item(tab, ref) for ref in items]
    effects: list[StateEffect] = []
    for selection in state.selections:
        if not selection.params:
            continue
        namespace = selection_namespace(tab, selection)
        for receiver in candidates:
            if receiver.id == selection.item_id or item_namespace(receiver) != namespace:
                continue
            if not reaches(tab, selection, receiver, namespace=namespace, receiver_ids=item_endpoints(receiver)):
                continue
            names = delivered(selection.params, own=False, aliases=alias_groups(tab, namespace))
            effects.append(StateEffect(selection, receiver, tuple(names), "received"))
    return tuple(effects)


def selector_param_keys(item: DashboardItemView) -> set[str]:
    keys = set(item.defaults)
    for member in group_members(item):
        defaults = member.get("defaults")
        if isinstance(defaults, Mapping):
            keys.update(defaults)
    return keys


def widget_chart_id(state: DashboardState, item: DashboardItemView) -> str | None:
    widget_tab = current_widget_tab(state, item)
    return optional_str(widget_tab.get("chartId")) if widget_tab is not None else None


def ql_param_names(chart: QLChart) -> set[str]:
    names: set[str] = set()
    for param in chart.params:
        name = optional_str(param.get("name"))
        if name is None:
            continue
        names.add(name)
        if param.get("type") == QL_INTERVAL_TYPE:
            names.update({f"{name}_from", f"{name}_to"})
    return names


def wizard_matches(
    chart: WizardChart,
    params: Sequence[str],
    datasets: dict[str, Dataset],
    operations: DashboardOperations,
) -> tuple[list[str], EffectMatch | None]:
    guids: set[str] = set()
    titles: set[str] = set()
    for dataset_id in chart.dataset_ids:
        if dataset_id not in datasets:
            datasets[dataset_id] = operations.dataset_operations.get_dataset(dataset_id)
        for dataset_field in datasets[dataset_id].fields:
            guids.add(dataset_field.guid)
            titles.add(dataset_field.title)
    by_guid = [_ for _ in params if _ in guids]
    by_title = [_ for _ in params if _ not in guids and _ in titles]
    matched_by: EffectMatch | None = "title" if by_title else "guid" if by_guid else None
    return [_ for _ in params if _ in guids or _ in titles], matched_by


def resolve_usage(
    state: DashboardState,
    effects: Sequence[StateEffect],
    operations: DashboardOperations,
) -> tuple[StateEffect, ...]:
    """Keep the receivers that use the delivered parameters and mark how sure that is.

    Costs one ``getEntries`` for the chart kinds, one read per distinct chart and one per distinct dataset of the
    Wizard charts; nothing is read twice within a call.
    """
    chart_ids = {
        effect.receiver.id: chart_id
        for effect in effects
        if effect.receiver.item_type == "widget" and (chart_id := widget_chart_id(state, effect.receiver))
    }
    charts = operations.chart_operations.get_charts(list(chart_ids.values()))
    datasets: dict[str, Dataset] = {}
    resolved: list[StateEffect] = []
    for effect in effects:
        receiver = effect.receiver
        if receiver.item_type in SELECTOR_TYPES:
            keys = selector_param_keys(receiver)
            matched = [_ for _ in effect.params if _ in keys]
            if matched:
                resolved.append(replace(effect, params=tuple(matched), certainty="exact", matched_by="guid"))
            continue
        chart = charts.get(chart_ids.get(receiver.id or "", ""))
        if isinstance(chart, WizardChart):
            matched, matched_by = wizard_matches(chart, effect.params, datasets, operations)
            if matched:
                resolved.append(replace(effect, params=tuple(matched), certainty="exact", matched_by=matched_by))
        elif isinstance(chart, QLChart):
            names = ql_param_names(chart)
            matched = [_ for _ in effect.params if _ in names]
            if matched:
                resolved.append(replace(effect, params=tuple(matched), certainty="exact"))
        elif isinstance(chart, EditorChart):
            widget_tab = current_widget_tab(state, receiver)
            declared_params = widget_tab.get("params") if widget_tab is not None else None
            declared = set(declared_params) if isinstance(declared_params, Mapping) else set()
            if not declared:
                resolved.append(replace(effect, certainty="unknown"))
                continue
            matched = [_ for _ in effect.params if _ in declared]
            if matched:
                resolved.append(replace(effect, params=tuple(matched), certainty="declared"))
        else:
            resolved.append(replace(effect, certainty="unknown"))
    return tuple(resolved)
