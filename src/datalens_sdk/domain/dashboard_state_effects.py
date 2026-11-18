"""DashKit rules for dashboard states: active inner tabs and parameter delivery (``getItemsParams``).

An item with ``data.tabs`` (chart widget or tabs-selector) shows ``state.tabId`` when that tab exists, else the tab
marked ``isDefault``, else the first tab. A selector of a global group takes part on a tab only when its
``impactType``/``impactTabsIds`` (or the group's, for ``asGroup``) include that tab.

Receivers are the items of the tab, with every visible selector of a group as its own receiver. An item with tabs
is addressed by its active tab id. A connection ``{"from": R, "to": S, "kind": "ignore"}`` stops receiver R
(its active endpoint) receiving anything from S. Matching parameter names alone never decides delivery.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.ql_chart import QLChart
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import ControlMemberView, DashboardItemView, DashboardTabView
    from datalens_sdk.domain.dashboard_state import DashboardState, DashboardStateData, StateSelection
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.ports import DashboardOperations
    from datalens_sdk.domain.runtime_params import NormalizedRuntimeParams

EffectCertainty = Literal["received", "exact", "declared", "unknown"]
EffectMatch = Literal["guid", "title"]

_RECEIVER_TYPES = frozenset({"widget", "control", "group_control"})
_SELECTOR_TYPES = frozenset({"control", "group_control"})
_QL_INTERVAL_TYPES = frozenset({"date-interval", "datetime-interval"})

_Params = dict[str, "str | tuple[str, ...]"]


_ACTION_PARAM_PREFIX = "_ap_"
_DEFAULT_NAMESPACE = "default"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(entry for entry in value if isinstance(entry, Mapping))


def _tab_items(tab: DashboardTabView) -> tuple[DashboardItemView, ...]:
    seen: set[str] = set()
    items: list[DashboardItemView] = []
    for item in (*tab.items, *tab.global_items):
        if item.id and item.id not in seen:
            seen.add(item.id)
            items.append(item)
    return tuple(items)


def _tab_item_ids(tab: DashboardTabView) -> set[str]:
    return {item.id for item in _tab_items(tab) if item.id}


def _global_item_ids(tab: DashboardTabView) -> set[str]:
    return {item.id for item in tab.global_items if item.id}


def _find_item(tab: DashboardTabView, item_id: str) -> DashboardItemView | None:
    return next((_ for _ in _tab_items(tab) if _.id == item_id), None)


def _has_inner_tabs(item: DashboardItemView) -> bool:
    tabs = item.data.get("tabs")
    return isinstance(tabs, Sequence) and not isinstance(tabs, str)


def _inner_tabs(item: DashboardItemView) -> tuple[Mapping[str, object], ...]:
    return _mappings(item.data.get("tabs"))


def _inner_tab_ids(item: DashboardItemView) -> list[str]:
    return [tab_id for tab in _inner_tabs(item) if (tab_id := _optional_str(tab.get("id")))]


def _mappings_list(value: object) -> tuple[tuple[Mapping[str, object], ...], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(_mappings(entry) for entry in value)


def _group_members(item: DashboardItemView) -> tuple[Mapping[str, object], ...]:
    return _mappings(item.data.get("group"))


def _state_tab_id(data: DashboardStateData, item_id: str) -> str | None:
    widget = data.widgets.get(item_id)
    return widget.state.tab_id if widget is not None and widget.state is not None else None


def _default_inner_tab_id(item: DashboardItemView) -> str | None:
    tabs = _inner_tabs(item)
    marked = next((tab for tab in tabs if tab.get("isDefault") is True), None)
    chosen = marked if marked is not None else (tabs[0] if tabs else None)
    return _optional_str(chosen.get("id")) if chosen is not None else None


def _active_inner_tab_id(item: DashboardItemView, data: DashboardStateData) -> str | None:
    """The tab DashKit shows: ``state.tabId`` when it exists, else ``isDefault``, else the first tab."""
    state_tab_id = _state_tab_id(data, item.id or "")
    if state_tab_id is not None and state_tab_id in _inner_tab_ids(item):
        return state_tab_id
    return _default_inner_tab_id(item)


def _inner_tab_params(item: DashboardItemView, tab_id: str | None) -> Mapping[str, object]:
    tab = next((_ for _ in _inner_tabs(item) if _.get("id") == tab_id), None)
    params = tab.get("params") if tab is not None else None
    return params if isinstance(params, Mapping) else {}


def _member_defaults(member: Mapping[str, object]) -> Mapping[str, object]:
    defaults = member.get("defaults")
    return defaults if isinstance(defaults, Mapping) else {}


def _is_group_member_visible(
    member: Mapping[str, object],
    group: DashboardItemView,
    tab: DashboardTabView,
) -> bool:
    """``isGlobalGroupItemVisible``: only members of a global group are filtered by their impact tabs."""
    if group.id not in _global_item_ids(tab):
        return True
    impact_type = member.get("impactType")
    if impact_type == "allTabs":
        return True
    if impact_type in ("asGroup", None):
        group_impact_type = group.data.get("impactType")
        group_tab_ids = group.data.get("impactTabsIds")
        if (group_impact_type is None and group_tab_ids is None) or group_impact_type == "allTabs":
            return True
        return isinstance(group_tab_ids, Sequence) and tab.id in group_tab_ids
    member_tab_ids = member.get("impactTabsIds")
    return isinstance(member_tab_ids, Sequence) and tab.id in member_tab_ids


def _is_action_param(key: str) -> bool:
    return key.startswith(_ACTION_PARAM_PREFIX)


@dataclass(frozen=True, slots=True)
class StateEffect:
    """A receiver of a state source and the parameter names it gets.

    ``receiver`` is the chart or selector item, or the ``ControlMemberView`` of a selector in a group.
    ``certainty`` is ``"received"`` when only delivery is known. With ``resolve_charts=True`` it tells whether the
    receiver uses the parameters: ``"exact"`` (selector defaults, Wizard dataset field guid or title, QL parameter
    name), ``"declared"`` (QL interval bounds, Editor chart tab params) or ``"unknown"``; ``matched_by`` says how
    a dataset field matched.
    """

    selection: StateSelection
    receiver: DashboardItemView | ControlMemberView
    params: tuple[str, ...]
    certainty: EffectCertainty
    matched_by: EffectMatch | None = None


@dataclass(frozen=True, slots=True)
class _Receiver:
    id: str
    namespace: str
    endpoint: str
    item: DashboardItemView
    view: DashboardItemView | ControlMemberView
    defaults: Mapping[str, object] | None
    own_params: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Source:
    selection: StateSelection
    id: str
    namespace: str
    params: Mapping[str, object]


def _wire(value: object) -> str | tuple[str, ...]:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return tuple(item if isinstance(item, str) else str(item) for item in value)
    return str(value)


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _alias_groups(tab: DashboardTabView, namespace: str) -> list[list[str]]:
    groups = tab.aliases.get(namespace)
    if not isinstance(groups, Sequence) or isinstance(groups, str):
        return []
    return [
        [name for name in group if isinstance(name, str)]
        for group in groups
        if isinstance(group, Sequence) and not isinstance(group, str)
    ]


def _merged(
    params: Mapping[str, object],
    aliases: list[list[str]],
    action_params: Mapping[str, object] | None = None,
) -> _Params:
    """``mergeParamsWithAliases``: every parameter also sets the other names of its alias groups."""
    result: _Params = {}
    for key, value in {**params, **(action_params or {})}.items():
        names = [key, *(name for group in aliases if key in group for name in group)]
        result.update(dict.fromkeys(names, _wire(value)))
    return result


def _member_receivers(state: DashboardState, item: DashboardItemView) -> list[_Receiver]:
    control = next(_ for _ in state.tab.controls if _.id == item.id)
    receivers: list[_Receiver] = []
    for member in _group_members(item):
        member_id = _optional_str(member.get("id"))
        view = control.member(member_id) if member_id else None
        if member_id is None or view is None or not _is_group_member_visible(member, item, state.tab):
            continue
        receivers.append(
            _Receiver(
                id=member_id,
                namespace=_optional_str(member.get("namespace")) or _DEFAULT_NAMESPACE,
                endpoint=member_id,
                item=item,
                view=view,
                defaults=_optional_mapping(member.get("defaults")),
                own_params=_member_defaults(member),
            )
        )
    return receivers


def _all_receivers(state: DashboardState) -> list[_Receiver]:
    receivers: list[_Receiver] = []
    for item in _tab_items(state.tab):
        if not item.id:
            continue
        if item.item_type == "group_control":
            receivers.extend(_member_receivers(state, item))
            continue
        defaults = _optional_mapping(item.raw.get("defaults"))
        if _has_inner_tabs(item):
            active = _active_inner_tab_id(item, state.data)
            endpoint, own_params = active or item.id, _inner_tab_params(item, active)
        else:
            endpoint, own_params = item.id, defaults or {}
        receivers.append(
            _Receiver(
                id=item.id,
                namespace=item.namespace or _DEFAULT_NAMESPACE,
                endpoint=endpoint,
                item=item,
                view=item,
                defaults=defaults,
                own_params=own_params,
            )
        )
    return receivers


def _ignores(state: DashboardState, receivers: list[_Receiver]) -> dict[str, set[str]]:
    """``getMapItemsIgnores``: receiver id -> ids it does not receive from."""
    by_endpoint = {receiver.endpoint: receiver.id for receiver in receivers}
    connections = [_ for _ in state.tab.connections if _.get("kind") == "ignore"]
    result: dict[str, set[str]] = {}
    for receiver in receivers:
        if state.version == 1:
            # DashKit keeps the v1 behaviour: an ignore on any tab of a widget applies to the whole widget.
            endpoints = {receiver.id, *(_inner_tab_ids(receiver.item) if receiver.view is receiver.item else ())}
        else:
            endpoints = {receiver.endpoint}
        result[receiver.id] = {
            by_endpoint[target]
            for connection in connections
            if connection.get("from") in endpoints
            and isinstance(target := connection.get("to"), str)
            and target in by_endpoint
        }
    return result


def _sources(state: DashboardState) -> list[_Source]:
    """``formQueueData``: applied queue sources with params limited to declared keys plus action params."""
    sources: list[_Source] = []
    for selection in state.selections:
        item = _find_item(state.tab, selection.item_id) if selection.applied else None
        if item is None:
            continue
        if selection.group_item_id is not None:
            member = next((_ for _ in _group_members(item) if _.get("id") == selection.group_item_id), {})
            declared: Mapping[str, object] = _member_defaults(member)
            source_id = selection.group_item_id
            namespace = _optional_str(member.get("namespace")) or _DEFAULT_NAMESPACE
        else:
            has_tabs = _has_inner_tabs(item) and state.version == 2
            declared = _inner_tab_params(item, selection.widget_tab_id) if has_tabs else item.defaults
            source_id = selection.item_id
            namespace = item.namespace or _DEFAULT_NAMESPACE
        params = {key: value for key, value in selection.params.items() if key in declared or _is_action_param(key)}
        sources.append(_Source(selection, source_id, namespace, params))
    return sources


def _delivered(source: _Source, receiver: _Receiver, aliases: list[list[str]]) -> _Params:
    if source.id != receiver.id and any(_is_action_param(_) for _ in source.params):
        plain = {key: value for key, value in source.params.items() if not _is_action_param(key)}
        action = {
            key[len(_ACTION_PARAM_PREFIX) :]: value for key, value in source.params.items() if _is_action_param(key)
        }
        return _merged(plain, aliases, action)
    return _merged(source.params, aliases)


def _receiver_params(state: DashboardState, receiver: _Receiver, receivers: list[_Receiver]) -> _Params:
    aliases = _alias_groups(state.tab, receiver.namespace)
    ignored = _ignores(state, receivers)[receiver.id]
    settings = state.dashboard.data.get("settings")
    global_params = _optional_mapping(settings.get("globalParams") if isinstance(settings, Mapping) else None)
    params: _Params = _merged(global_params or {}, aliases)
    # DashKit folds defaults with reduceRight: the first selector of the dashboard wins on a shared name.
    for other in reversed(receivers):
        if other.defaults is not None and other.namespace == receiver.namespace and other.id not in ignored:
            params.update(_merged(other.defaults, aliases))
    if state.version == 1:
        widget = state.data.widgets.get(receiver.id)
        own = widget.params if widget is not None and widget.params is not None else {}
        for key, value in own.items():
            raw = None if isinstance(value, Mapping) else value.raw
            if raw is not None:
                params[key] = raw
    else:
        for source in _sources(state):
            if source.namespace == receiver.namespace and source.id not in ignored:
                params.update(_delivered(source, receiver, aliases))
    return {**{key: _wire(value) for key, value in receiver.own_params.items()}, **params}


def _resolve_receivers(receivers: list[_Receiver], ref: object) -> list[_Receiver]:
    ref_id = ref if isinstance(ref, str) else getattr(ref, "id", None)
    if not isinstance(ref_id, str) or not ref_id:
        raise DataLensValidationError(f"Expected an item id or a dashboard view, got {ref!r}")
    own = [_ for _ in receivers if _.id == ref_id]
    if own:
        return own
    members = [_ for _ in receivers if _.item.id == ref_id]
    if not members:
        raise DataLensValidationError(f"Item {ref_id!r} is not on this tab or receives no parameters here")
    return members


def _params_for(state: DashboardState, item: object) -> NormalizedRuntimeParams:
    receivers = _all_receivers(state)
    matches = _resolve_receivers(receivers, item)
    if len(matches) > 1:
        raise DataLensValidationError(
            f"Item {matches[0].item.id!r} is a selector group; pass one of its selectors: {[_.id for _ in matches]!r}"
        )
    return MappingProxyType(_receiver_params(state, matches[0], receivers))


def _receivers(state: DashboardState, items: Sequence[object] | None = None) -> tuple[StateEffect, ...]:
    """Every (source, receiver) pair of a v2 state with the parameter names the receiver gets."""
    if state.version == 1:
        return ()
    receivers = _all_receivers(state)
    candidates = [_ for _ in receivers if _.item.item_type in _RECEIVER_TYPES]
    if items is not None:
        wanted = {id(receiver) for ref in items for receiver in _resolve_receivers(receivers, ref)}
        candidates = [_ for _ in candidates if id(_) in wanted]
    ignores = _ignores(state, receivers)
    effects: list[StateEffect] = []
    for source in _sources(state):
        for receiver in candidates:
            if receiver.id == source.id or receiver.namespace != source.namespace or source.id in ignores[receiver.id]:
                continue
            names = tuple(_delivered(source, receiver, _alias_groups(state.tab, receiver.namespace)))
            if names:
                effects.append(StateEffect(source.selection, receiver.view, names, "received"))
    return tuple(effects)


def _is_selector(receiver: DashboardItemView | ControlMemberView) -> bool:
    return hasattr(receiver, "source_type") or getattr(receiver, "item_type", None) in _SELECTOR_TYPES


def _selector_keys(state: DashboardState, receiver: DashboardItemView | ControlMemberView) -> set[str]:
    keys = set(receiver.defaults)
    item = _find_item(state.tab, receiver.id or "") if not hasattr(receiver, "source_type") else None
    if item is not None and _has_inner_tabs(item):
        keys.update(_inner_tab_params(item, _active_inner_tab_id(item, state.data)))
    return keys


def _active_chart_tab(state: DashboardState, receiver: DashboardItemView | ControlMemberView) -> Mapping[str, object]:
    item = _find_item(state.tab, receiver.id or "") if not _is_selector(receiver) else None
    if item is None:
        return {}
    active = _active_inner_tab_id(item, state.data)
    return next((_ for _ in _inner_tabs(item) if _.get("id") == active), {})


def _ql_names(chart: QLChart) -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    bounds: set[str] = set()
    for param in chart.params:
        name = _optional_str(param.get("name"))
        if name is None:
            continue
        exact.add(name)
        if param.get("type") in _QL_INTERVAL_TYPES:
            bounds.update({f"{name}_from", f"{name}_to"})
    return exact, bounds


def _wizard_matches(
    chart: WizardChart,
    params: Sequence[str],
    datasets: dict[str, Dataset],
    operations: DashboardOperations,
) -> tuple[list[str], EffectMatch | None]:
    guids = {_.guid for _ in chart.fields}
    titles = {_.title for _ in chart.fields}
    for local_fields in _mappings_list(chart.data.get("datasetsPartialFields")):
        guids.update(guid for _ in local_fields if (guid := _optional_str(_.get("guid"))))
        titles.update(title for _ in local_fields if (title := _optional_str(_.get("title"))))
    for dataset_id in chart.dataset_ids:
        if dataset_id not in datasets:
            datasets[dataset_id] = operations.dataset_operations.get_dataset(dataset_id)
        for dataset_field in datasets[dataset_id].fields:
            guids.add(dataset_field.guid)
            titles.add(dataset_field.title)
    by_title = [_ for _ in params if _ not in guids and _ in titles]
    matched = [_ for _ in params if _ in guids or _ in titles]
    return matched, "title" if by_title else "guid" if matched else None


def _chart_usage(
    effect: StateEffect,
    chart: object,
    chart_tab: Mapping[str, object],
    datasets: dict[str, Dataset],
    operations: DashboardOperations,
) -> list[StateEffect]:
    if isinstance(chart, WizardChart):
        matched, matched_by = _wizard_matches(chart, effect.params, datasets, operations)
        return [replace(effect, params=tuple(matched), certainty="exact", matched_by=matched_by)] if matched else []
    if isinstance(chart, QLChart):
        exact, bounds = _ql_names(chart)
        exact_params = tuple(_ for _ in effect.params if _ in exact)
        bound_params = tuple(_ for _ in effect.params if _ in bounds and _ not in exact)
        result = [replace(effect, params=exact_params, certainty="exact")] if exact_params else []
        return result + ([replace(effect, params=bound_params, certainty="declared")] if bound_params else [])
    if isinstance(chart, EditorChart):
        # Editor code may read any parameter; only the chart tab params are declared.
        declared_params = chart_tab.get("params")
        declared = set(declared_params) if isinstance(declared_params, Mapping) else set()
        used = tuple(_ for _ in effect.params if _ in declared)
        other = tuple(_ for _ in effect.params if _ not in declared)
        result = [replace(effect, params=used, certainty="declared")] if used else []
        return result + ([replace(effect, params=other, certainty="unknown")] if other else [])
    return [replace(effect, certainty="unknown")]


def _resolve_usage(
    state: DashboardState,
    effects: Sequence[StateEffect],
    operations: DashboardOperations,
) -> tuple[StateEffect, ...]:
    """Keep the receivers that use the delivered parameters and mark how sure that is."""
    chart_tabs = {id(effect): _active_chart_tab(state, effect.receiver) for effect in effects}
    chart_ids = [_ for tab in chart_tabs.values() if (_ := _optional_str(tab.get("chartId")))]
    charts = operations.chart_operations.get_charts(chart_ids)
    datasets: dict[str, Dataset] = {}
    resolved: list[StateEffect] = []
    for effect in effects:
        if _is_selector(effect.receiver):
            matched = tuple(_ for _ in effect.params if _ in _selector_keys(state, effect.receiver))
            if matched:
                resolved.append(replace(effect, params=matched, certainty="exact"))
            continue
        chart_tab = chart_tabs[id(effect)]
        chart = charts.get(_optional_str(chart_tab.get("chartId")) or "")
        resolved.extend(_chart_usage(effect, chart, chart_tab, datasets, operations))
    return tuple(resolved)
