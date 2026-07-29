from __future__ import annotations

from typing import Literal, TypedDict, cast

from datalens_sdk._runtime.viz_specs import (
    VIZ_SPECS,
    viz_ids_for_wizard_encoding,
    viz_ids_with_color_encoding,
)
from datalens_sdk.errors import DatalensConfigurationError

MethodKind = Literal["placeholder", "data_field", "extra_setting", "ph_setting", "helper"]

MethodValueType = Literal["str", "bool", "literal", "fields"]


class MethodSpec(TypedDict, total=False):
    kind: MethodKind
    viz_ids: frozenset[str]
    wire_key: str
    setting_key: str
    value_type: MethodValueType
    literal_values: tuple[str, ...]
    value_map: dict[str, str]
    helper: str


def _viz_ids_where(flag: str, *, default: bool) -> frozenset[str]:
    """Compute frozenset of viz_ids where a viz-level flag is True."""
    result: set[str] = set()
    for viz_id, spec in VIZ_SPECS.items():
        viz = cast(dict[str, object], spec.get("viz", {}))
        if bool(viz.get(flag, default)):
            result.add(viz_id)
    return frozenset(result)


_ALLOW_SORT: frozenset[str] = _viz_ids_where("allowSort", default=True)

_ALLOW_LABELS: frozenset[str] = _viz_ids_where("allowLabels", default=True)

_ALLOW_FILTERS: frozenset[str] = _viz_ids_where("allowFilters", default=True)

_CARTESIAN: frozenset[str] = frozenset(
    {
        "line",
        "column",
        "bar",
        "area",
        "area100p",
        "column100p",
        "bar100p",
        "scatter",
    }
)

_CARTESIAN_LINEAR: frozenset[str] = frozenset(
    {
        "line",
        "column",
        "bar",
        "area",
        "area100p",
        "column100p",
        "bar100p",
    }
)

_TABLE: frozenset[str] = frozenset({"flatTable", "pivotTable"})

_SEGMENT_VIZ: frozenset[str] = frozenset(
    {
        "line",
        "column",
        "area",
        "area100p",
        "column100p",
    }
)

_LABEL_MODE_VIZ: frozenset[str] = frozenset(
    {
        "funnel",
        "pie",
        "donut",
        "area100p",
        "column100p",
        "bar100p",
    }
)

_TABLE_AND_CARTESIAN: frozenset[str] = _TABLE | _CARTESIAN

_BOOL_ON_OFF: dict[str, str] = {"true": "on", "false": "off"}

_BOOL_YES_NO: dict[str, str] = {"true": "yes", "false": "no"}


METHOD_SPECS: dict[str, MethodSpec] = {
    "legend": {
        "kind": "extra_setting",
        "wire_key": "legendMode",
        "value_type": "literal",
        "literal_values": ("show", "hide"),
    },
    "tooltip_sum": {
        "kind": "extra_setting",
        "wire_key": "tooltipSum",
        "value_type": "bool",
        "value_map": _BOOL_ON_OFF,
    },
    "totals": {
        "kind": "extra_setting",
        "wire_key": "totals",
        "value_type": "bool",
        "value_map": _BOOL_ON_OFF,
        "viz_ids": frozenset({"flatTable"}),
    },
    "label_mode": {
        "kind": "extra_setting",
        "wire_key": "labelMode",
        "value_type": "literal",
        "literal_values": ("absolute", "percent"),
        "viz_ids": _LABEL_MODE_VIZ,
    },
    "labels_position": {
        "kind": "extra_setting",
        "wire_key": "labelsPosition",
        "value_type": "literal",
        "literal_values": ("inside", "outside", "auto"),
    },
    "tooltip_percentage_base": {
        "kind": "extra_setting",
        "wire_key": "tooltipPercentageBase",
        "value_type": "literal",
        "literal_values": ("auto", "first", "previous"),
        "viz_ids": frozenset({"funnel"}),
    },
    "axis_visibility": {
        "kind": "ph_setting",
        "setting_key": "axisVisibility",
        "value_type": "literal",
        "literal_values": ("show", "hide"),
        "viz_ids": _CARTESIAN,
    },
    "hide_labels": {
        "kind": "ph_setting",
        "setting_key": "hideLabels",
        "value_type": "bool",
        "value_map": _BOOL_YES_NO,
        "viz_ids": _CARTESIAN,
    },
    "nulls_mode": {
        "kind": "ph_setting",
        "setting_key": "nulls",
        "value_type": "literal",
        "literal_values": ("ignore", "connect", "as-0"),
        "viz_ids": _CARTESIAN,
    },
    "segments": {
        "kind": "data_field",
        "wire_key": "segments",
        "value_type": "fields",
        "viz_ids": _SEGMENT_VIZ,
    },
    "sort": {
        "kind": "data_field",
        "wire_key": "sort",
        "value_type": "fields",
        "viz_ids": _ALLOW_SORT,
    },
    "labels": {
        "kind": "data_field",
        "wire_key": "labels",
        "value_type": "fields",
        "viz_ids": _ALLOW_LABELS,
    },
    "tooltips": {
        "kind": "data_field",
        "wire_key": "tooltips",
        "value_type": "fields",
    },
    # Group B — helper methods (richer logic in category base classes;
    # these declarations drive codegen applicability and update-guard only).
    "chart_title": {
        "kind": "helper",
        "helper": "chart_title",
    },
    "description": {
        "kind": "helper",
        "helper": "description",
    },
    "add_local_field": {
        "kind": "helper",
        "helper": "add_local_field",
    },
    "add_aggregated_measure": {
        "kind": "helper",
        "helper": "add_aggregated_measure",
    },
    "add_filter": {
        "kind": "helper",
        "helper": "add_filter",
        "viz_ids": _ALLOW_FILTERS,
    },
    "add_date_filter": {
        "kind": "helper",
        "helper": "add_date_filter",
        "viz_ids": _ALLOW_FILTERS,
    },
    "add_relative_date_filter": {
        "kind": "helper",
        "helper": "add_relative_date_filter",
        "viz_ids": _ALLOW_FILTERS,
    },
    "add_sort": {
        "kind": "helper",
        "helper": "add_sort",
        "viz_ids": _ALLOW_SORT,
    },
    "navigator": {
        "kind": "helper",
        "helper": "navigator",
        "viz_ids": _CARTESIAN_LINEAR,
    },
    "axis_title": {
        "kind": "helper",
        "helper": "axis_title",
        "viz_ids": _CARTESIAN,
    },
    "axis_scale": {
        "kind": "helper",
        "helper": "axis_scale",
        "viz_ids": _CARTESIAN,
    },
    "grid": {
        "kind": "helper",
        "helper": "grid",
        "viz_ids": _CARTESIAN,
    },
    "pagination": {
        "kind": "helper",
        "helper": "pagination",
        "viz_ids": _TABLE,
    },
    "table_size": {
        "kind": "helper",
        "helper": "table_size",
        "viz_ids": _TABLE,
    },
    "freeze_columns": {
        "kind": "helper",
        "helper": "freeze_columns",
        "viz_ids": _TABLE,
    },
    "column_background": {
        "kind": "helper",
        "helper": "column_background",
        "viz_ids": _TABLE,
    },
    "column_bars": {
        "kind": "helper",
        "helper": "column_bars",
        "viz_ids": _TABLE,
    },
    "column_title": {
        "kind": "helper",
        "helper": "column_title",
        "viz_ids": _TABLE,
    },
    "subtotals": {
        "kind": "helper",
        "helper": "subtotals",
        "viz_ids": frozenset({"pivotTable"}),
    },
    "measure_format": {
        "kind": "helper",
        "helper": "measure_format",
    },
    "shape": {
        "kind": "helper",
        "helper": "shape",
        "viz_ids": frozenset({"funnel"}),
    },
    "palette": {
        "kind": "helper",
        "helper": "palette",
        "viz_ids": viz_ids_with_color_encoding(),
    },
    "color_by_dimension": {
        "kind": "helper",
        "helper": "color_by_dimension",
        "viz_ids": viz_ids_for_wizard_encoding("color", "dimension"),
    },
    "color_by_measure": {
        "kind": "helper",
        "helper": "color_by_measure",
        "viz_ids": viz_ids_for_wizard_encoding("color", "measure"),
    },
    "color_by_measure_name": {
        "kind": "helper",
        "helper": "color_by_measure_name",
        "viz_ids": viz_ids_for_wizard_encoding("color", "measure_name"),
    },
    "shape_by_dimension": {
        "kind": "helper",
        "helper": "shape_by_dimension",
        "viz_ids": viz_ids_for_wizard_encoding("shape", "dimension"),
    },
    "shape_by_measure_name": {
        "kind": "helper",
        "helper": "shape_by_measure_name",
        "viz_ids": viz_ids_for_wizard_encoding("shape", "measure_name"),
    },
    "point_size_range": {
        "kind": "helper",
        "helper": "point_size_range",
        "viz_ids": frozenset({"scatter"}),
    },
    "font_size": {
        "kind": "helper",
        "helper": "font_size",
        "viz_ids": frozenset({"metric"}),
    },
    "font_color": {
        "kind": "helper",
        "helper": "font_color",
        "viz_ids": frozenset({"metric"}),
    },
    "measure_title_mode": {
        "kind": "helper",
        "helper": "measure_title_mode",
        "viz_ids": frozenset({"metric"}),
    },
    "add_hierarchy": {
        "kind": "helper",
        "helper": "add_hierarchy",
        "viz_ids": _TABLE_AND_CARTESIAN,
    },
}


def validate_method_applicability(method_name: str, visualization_id: str) -> None:
    spec = METHOD_SPECS.get(method_name)
    viz_ids = spec.get("viz_ids") if spec is not None else None
    if visualization_id and viz_ids and visualization_id not in viz_ids:
        raise DatalensConfigurationError(
            f"Method {method_name!r} is not applicable to viz {visualization_id!r}. Applicable vizs: {sorted(viz_ids)}"
        )


def method_specs_for_viz(viz_id: str) -> dict[str, MethodSpec]:
    """Return the group-A and helper methods applicable to the given viz.

    A method with no ``viz_ids`` (or an empty one) is universal and applies to
    every viz. Otherwise the method applies only when ``viz_id`` is a member of
    its ``viz_ids`` set.
    """
    out: dict[str, MethodSpec] = {}
    for name, spec in METHOD_SPECS.items():
        viz_ids = spec.get("viz_ids")
        if not viz_ids or viz_id in viz_ids:
            out[name] = spec
    return out
