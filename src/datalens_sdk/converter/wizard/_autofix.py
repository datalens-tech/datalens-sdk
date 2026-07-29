from __future__ import annotations

from datalens_sdk._runtime.chart_wire import (
    build_pseudo_measure_names_for_data_colors,
    build_pseudo_measure_names_for_placeholder,
)
from datalens_sdk._runtime.viz_specs import get_wizard_encoding, requires_x_measure_autofix
from datalens_sdk.converter.wizard._common import _collect_measures, _items_list, _placeholders_list


def _auto_fix_multi_measure(data: dict[str, object], explicit_colors: bool) -> None:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    viz_id = viz.get("id", "")
    if not isinstance(viz_id, str):
        return
    is_pivot = viz_id == "pivotTable"
    rule = None if is_pivot else get_wizard_encoding(viz_id, "color", "measure_name")
    if not is_pivot and rule is None:
        return
    if not is_pivot and explicit_colors:
        return
    if not is_pivot and data.get("colors"):
        return
    measure_placeholders = ("measures",) if is_pivot else rule.get("measure_placeholders", ()) if rule else ()
    measures = _collect_measures(data, list(measure_placeholders))
    if len(measures) < 2:
        return
    if not is_pivot:
        data["colors"] = [build_pseudo_measure_names_for_data_colors()]
        data["colorsConfig"] = {}
    category_ph_id = "pivot-table-columns" if is_pivot else rule.get("category_placeholder") if rule else None
    if category_ph_id is None:
        return
    for ph in _placeholders_list(viz):
        if ph.get("id") != category_ph_id:
            continue
        items = ph.setdefault("items", [])
        if not isinstance(items, list):
            continue
        if any(isinstance(it, dict) and it.get("type") == "PSEUDO" for it in items):
            return
        items.append(build_pseudo_measure_names_for_placeholder())
        return


def _apply_auto_fix_pie_dimension_color(data: dict[str, object]) -> None:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    viz_id = viz.get("id")
    if not isinstance(viz_id, str):
        return
    rule = get_wizard_encoding(viz_id, "color", "dimension")
    if rule is None:
        return
    source_placeholder_id = rule.get("implicit_from")
    color_placeholder_id = rule.get("placeholder")
    if not isinstance(source_placeholder_id, str) or not isinstance(color_placeholder_id, str):
        return
    placeholders = _placeholders_list(viz)
    dims_ph = next((p for p in placeholders if p.get("id") == source_placeholder_id), None)
    if dims_ph is None:
        return
    dim_items = _items_list(dims_ph)
    if not dim_items:
        return
    first_dim = dim_items[0]
    if first_dim.get("type") != "DIMENSION":
        return
    colors_ph = next((p for p in placeholders if p.get("id") == color_placeholder_id), None)
    if colors_ph is not None and _items_list(colors_ph):
        return
    if data.get("colors"):
        return
    data["colors"] = [dict(first_dim)]
    if colors_ph is None:
        colors_ph = {"id": color_placeholder_id, "items": []}
        placeholders.append(colors_ph)
        viz["placeholders"] = placeholders
    colors_ph["items"] = [dict(first_dim)]
    guid = first_dim.get("guid")
    if isinstance(guid, str) and guid:
        existing_cfg = data.get("colorsConfig")
        cfg = dict(existing_cfg) if isinstance(existing_cfg, dict) else {}
        if not cfg.get("fieldGuid"):
            cfg["fieldGuid"] = guid
            data["colorsConfig"] = cfg


def _apply_smart_labels_position(data: dict[str, object], spec_key: str, *, has_colors: bool) -> None:
    if spec_key not in ("bar", "bar100p", "column"):
        return
    if not data.get("labels"):
        return
    extras = data.get("extraSettings")
    if isinstance(extras, dict) and "labelsPosition" in extras:
        return
    position = "inside" if spec_key == "bar100p" or has_colors else "outside"
    merged = dict(extras) if isinstance(extras, dict) else {}
    merged["labelsPosition"] = position
    data["extraSettings"] = merged


def _apply_bar_auto_defaults(data: dict[str, object], spec_key: str) -> None:
    viz = data.get("visualization")
    if not isinstance(viz, dict) or not spec_key:
        return
    if not requires_x_measure_autofix(spec_key):
        return
    x_ph = next((p for p in _placeholders_list(viz) if p.get("id") == "x"), None)
    if x_ph is None:
        return
    x_items = _items_list(x_ph)
    if not x_items:
        return
    first = x_items[0]
    if first.get("type") != "MEASURE":
        return
    if not data.get("sort"):
        sort_item = dict(first)
        sort_item["direction"] = "DESC"
        data["sort"] = [sort_item]
    if spec_key != "bar":
        return
    if not data.get("labels"):
        data["labels"] = [dict(first)]
