"""Wire emission for dashboard items (create path and update appliers).

Split out of :mod:`datalens_sdk.converter.dashboard` as a leaf module so both
the create converter and the update RMW appliers can build item/tab wire
dicts without import cycles.
"""

from __future__ import annotations

from datalens_sdk.converter.dashboard_control import _external_control_wire, _group_control_data
from datalens_sdk.domain.dashboard_layout import GRID_COLUMNS
from datalens_sdk.domain.dashboard_types import ThemedColor
from datalens_sdk.domain.specs.dashboard import (
    AutoLayoutItemSpec,
    DashboardItemSpec,
    ExternalControlItem,
    GroupControlItem,
    ImageItem,
    LayoutItemSpec,
    TabSpec,
    TextItem,
    TitleItem,
    WidgetItem,
)
from datalens_sdk.errors import DataLensValidationError

_ITEM_NAMESPACE_VALUE = "default"


def _wire_color(value: str | ThemedColor) -> object:
    if isinstance(value, ThemedColor):
        return {"light": value.light, "dark": value.dark}
    # Ordinary Dashboard V2 tab items require theme-aware colors. Dashboard,
    # control, and group-control contexts that still accept strings do not use
    # this item-only helper.
    return {"light": value, "dark": value}


def _apply_styling(
    data: dict[str, object],
    *,
    background: str | ThemedColor | None,
    text_color: str | ThemedColor | None = None,
    hint: str | None = None,
    border_radius: int | None = None,
) -> None:
    if background is not None:
        data["backgroundSettings"] = {"color": _wire_color(background)}
    if text_color is not None:
        data["textSettings"] = {"color": _wire_color(text_color)}
    if hint is not None:
        data["hint"] = {"enabled": True, "text": hint}
    if border_radius is not None:
        data["borderRadius"] = border_radius


def _widget_data(item: WidgetItem) -> dict[str, object]:
    tabs: list[dict[str, object]] = []
    for chart_tab in item.tabs:
        tab_data: dict[str, object] = {
            "id": chart_tab.id,
            "title": chart_tab.title,
            "chartId": chart_tab.chart_id,
            "params": {key: list(values) for key, values in chart_tab.params.items()},
            "isDefault": chart_tab.is_default,
            "autoHeight": chart_tab.auto_height,
        }
        if chart_tab.description is not None:
            tab_data["description"] = chart_tab.description
            tab_data["enableDescription"] = True
        if chart_tab.hint is not None:
            tab_data["hint"] = chart_tab.hint
            tab_data["enableHint"] = True
        if chart_tab.enable_action_params:
            tab_data["enableActionParams"] = True
        tabs.append(tab_data)
    data: dict[str, object] = {"hideTitle": not item.show_title, "tabs": tabs}
    _apply_styling(data, background=item.background, border_radius=item.border_radius)
    return data


def _text_data(item: TextItem) -> dict[str, object]:
    data: dict[str, object] = {"text": item.text, "autoHeight": item.auto_height}
    _apply_styling(data, background=item.background, border_radius=item.border_radius)
    return data


def _title_data(item: TitleItem) -> dict[str, object]:
    data: dict[str, object] = {
        "text": item.text,
        "size": item.size,
        "showInTOC": item.show_in_toc,
        "autoHeight": item.auto_height,
    }
    _apply_styling(
        data,
        background=item.background,
        text_color=item.text_color,
        hint=item.hint,
        border_radius=item.border_radius,
    )
    return data


def _image_data(item: ImageItem) -> dict[str, object]:
    data: dict[str, object] = {"src": item.src, "preserveAspectRatio": item.preserve_aspect_ratio}
    if item.alt is not None:
        data["alt"] = item.alt
    _apply_styling(data, background=item.background, border_radius=item.border_radius)
    return data


def _wire_item(tab: TabSpec, item: DashboardItemSpec) -> dict[str, object]:
    if isinstance(item, WidgetItem):
        wire_type, data = "widget", _widget_data(item)
    elif isinstance(item, TextItem):
        wire_type, data = "text", _text_data(item)
    elif isinstance(item, TitleItem):
        wire_type, data = "title", _title_data(item)
    elif isinstance(item, ImageItem):
        wire_type, data = "image", _image_data(item)
    elif isinstance(item, GroupControlItem):
        wire_type, data = "group_control", _group_control_data(item)
    elif isinstance(item, ExternalControlItem):
        # standalone control format: defaults live at item level (P017)
        return _external_control_wire(item, namespace=_ITEM_NAMESPACE_VALUE)
    else:
        raise DataLensValidationError(f"Tab {tab.id!r} carries an unsupported item spec {type(item).__name__!r}")
    return {"id": item.id, "type": wire_type, "namespace": _ITEM_NAMESPACE_VALUE, "data": data}


def _concrete_layout(entry: LayoutItemSpec | AutoLayoutItemSpec, tab_id: str) -> LayoutItemSpec:
    """Narrow a layout entry to a resolved one. A deferred (at=None) entry must be
    resolved before wiring/validation reaches it; this fails loud if one leaks."""
    if isinstance(entry, AutoLayoutItemSpec):
        raise DataLensValidationError(f"Tab {tab_id!r} item {entry.i!r}: auto layout position was not resolved")
    return entry


def _wire_layout_entry(entry: LayoutItemSpec) -> dict[str, object]:
    wire: dict[str, object] = {"i": entry.i, "x": entry.x, "y": entry.y, "w": entry.w, "h": entry.h}
    if entry.parent is not None:
        wire["parent"] = entry.parent
    return wire


def _wire_tab(tab: TabSpec) -> dict[str, object]:
    wire_tab: dict[str, object] = {
        "id": tab.id,
        "title": tab.title,
        # shared selectors move to globalItems of their target tabs
        "items": [_wire_item(tab, item) for item in tab.items if not _is_shared_group(item)],
        "layout": [
            _wire_layout_entry(_concrete_layout(entry, tab.id))
            for entry in tab.layout
            if entry.i not in {item.id for item in tab.items if _is_shared_group(item)}
        ],
        "connections": [{"from": edge.from_id, "to": edge.to_id, "kind": "ignore"} for edge in tab.connections],
        "aliases": {"default": [list(group) for group in tab.aliases]},
    }
    if tab.hidden:
        wire_tab["hidden"] = True
    return wire_tab


_CANONICAL_SETTINGS: dict[str, object] = {
    "autoupdateInterval": None,
    "maxConcurrentRequests": None,
    "silentLoading": False,
    "dependentSelectors": True,
    "expandTOC": False,
    "globalParams": {},
    "hideDashTitle": False,
    "hideTabs": False,
}


def _is_shared_group(item: DashboardItemSpec) -> bool:
    return isinstance(item, GroupControlItem) and item.show_on_tabs != "current"


def _validate_grid(tab: TabSpec) -> None:
    for raw_entry in tab.layout:
        entry = _concrete_layout(raw_entry, tab.id)
        values = {"x": entry.x, "y": entry.y, "w": entry.w, "h": entry.h}
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise DataLensValidationError(
                    f"Tab {tab.id!r} item {entry.i!r}: layout {name} must be an int, got {value!r}"
                )
        if entry.x < 0 or entry.y < 0:
            raise DataLensValidationError(f"Tab {tab.id!r} item {entry.i!r}: layout x and y must be >= 0")
        if entry.w <= 0 or entry.h <= 0:
            raise DataLensValidationError(f"Tab {tab.id!r} item {entry.i!r}: layout w and h must be > 0")
        if entry.x + entry.w > GRID_COLUMNS:
            raise DataLensValidationError(
                f"Tab {tab.id!r} item {entry.i!r}: x + w must be <= {GRID_COLUMNS}, got {entry.x + entry.w}"
            )


def _validate_items_layout_bijection(tab: TabSpec) -> None:
    item_ids = [item.id for item in tab.items]
    layout_ids = [entry.i for entry in tab.layout]
    if len(set(layout_ids)) != len(layout_ids):
        raise DataLensValidationError(f"Tab {tab.id!r} layout references an item more than once")
    if set(item_ids) != set(layout_ids):
        missing = sorted(set(item_ids) - set(layout_ids))
        orphaned = sorted(set(layout_ids) - set(item_ids))
        raise DataLensValidationError(
            f"Tab {tab.id!r} items and layout must match exactly: "
            f"items without layout {missing!r}, layout without items {orphaned!r}"
        )
