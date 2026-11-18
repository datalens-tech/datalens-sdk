"""Lookups over dashboard views shared by the state model, builder and effects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import DashboardItemView, DashboardTabView


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def tab_item_ids(tab: DashboardTabView) -> set[str]:
    return {item.id for item in (*tab.items, *tab.global_items) if item.id}


def find_item(tab: DashboardTabView, item_id: str) -> DashboardItemView | None:
    for item in (*tab.items, *tab.global_items):
        if item.id == item_id:
            return item
    return None


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
