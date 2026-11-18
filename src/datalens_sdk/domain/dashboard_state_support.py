"""Shared support for dashboard states: tolerant lookups over the loaded revision and the DashKit rules that the
state model, the builder and the effects agree on. Everything here is package-internal.

DashKit facts mirrored here (``@gravity-ui/dashkit``, ``shared/modules/helpers.ts``):

- an item with ``data.tabs`` (chart widget or tabs-control) shows ``data[id].state.tabId`` when that tab exists,
  else the tab marked ``isDefault``, else the first tab;
- a member of a global selector group takes part on a tab only when its ``impactType``/``impactTabsIds`` (or the
  group's, for ``asGroup``) include that tab.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import DashboardItemView, DashboardTabView
    from datalens_sdk.domain.entry_state import DashboardStateData

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
