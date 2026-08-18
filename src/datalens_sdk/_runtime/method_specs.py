from __future__ import annotations

from typing import Literal, TypedDict

from datalens_sdk._runtime.wizard_semantics import (
    visualization_types_for_wizard_encoding,
    visualization_types_where,
    visualization_types_with_color_encoding,
    visualization_types_with_label_mode,
    visualization_types_with_slot,
)
from datalens_sdk.errors import DataLensConfigurationError

MethodKind = Literal["slot", "chart_setting", "slot_setting", "helper"]

MethodValueType = Literal["str", "bool", "literal", "fields"]


class MethodSpec(TypedDict, total=False):
    kind: MethodKind
    visualization_types: frozenset[str]
    slot_name: str
    setting_key: str
    value_type: MethodValueType
    literal_values: tuple[str, ...]
    value_map: dict[str, str]
    helper: str


_ALLOW_SORT = visualization_types_where("allows_sort")

_ALLOW_LABELS = visualization_types_where("allows_labels")

_ALLOW_FILTERS = visualization_types_where("allows_filters")

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

_SEGMENT_VISUALIZATIONS = visualization_types_with_slot("segments")

_LABEL_MODE_VISUALIZATIONS = visualization_types_with_label_mode("percent")

_TABLE_AND_CARTESIAN: frozenset[str] = _TABLE | _CARTESIAN

_BOOL_ON_OFF: dict[str, str] = {"true": "on", "false": "off"}

_BOOL_YES_NO: dict[str, str] = {"true": "yes", "false": "no"}


METHOD_SPECS: dict[str, MethodSpec] = {
    "legend": {
        "kind": "chart_setting",
        "setting_key": "legendMode",
        "value_type": "literal",
        "literal_values": ("show", "hide"),
    },
    "tooltip_sum": {
        "kind": "chart_setting",
        "setting_key": "tooltipSum",
        "value_type": "bool",
        "value_map": _BOOL_ON_OFF,
    },
    "totals": {
        "kind": "chart_setting",
        "setting_key": "totals",
        "value_type": "bool",
        "value_map": _BOOL_ON_OFF,
        "visualization_types": frozenset({"flatTable"}),
    },
    "label_mode": {
        "kind": "chart_setting",
        "setting_key": "labelMode",
        "value_type": "literal",
        "literal_values": ("absolute", "percent"),
        "visualization_types": _LABEL_MODE_VISUALIZATIONS,
    },
    "labels_position": {
        "kind": "chart_setting",
        "setting_key": "labelsPosition",
        "value_type": "literal",
        "literal_values": ("inside", "outside", "auto"),
        "visualization_types": _ALLOW_LABELS,
    },
    "tooltip_percentage_base": {
        "kind": "chart_setting",
        "setting_key": "tooltipPercentageBase",
        "value_type": "literal",
        "literal_values": ("auto", "first", "previous"),
        "visualization_types": frozenset({"funnel"}),
    },
    "axis_visibility": {
        "kind": "slot_setting",
        "setting_key": "axisVisibility",
        "value_type": "literal",
        "literal_values": ("show", "hide"),
        "visualization_types": _CARTESIAN,
    },
    "hide_labels": {
        "kind": "slot_setting",
        "setting_key": "hideLabels",
        "value_type": "bool",
        "value_map": _BOOL_YES_NO,
        "visualization_types": _CARTESIAN,
    },
    "nulls_mode": {
        "kind": "slot_setting",
        "setting_key": "nulls",
        "value_type": "literal",
        "literal_values": ("ignore", "connect", "as-0"),
        "visualization_types": _CARTESIAN,
    },
    "segments": {
        "kind": "slot",
        "slot_name": "segments",
        "value_type": "fields",
        "visualization_types": _SEGMENT_VISUALIZATIONS,
    },
    "sort": {
        "kind": "slot",
        "slot_name": "sort",
        "value_type": "fields",
        "visualization_types": _ALLOW_SORT,
    },
    "labels": {
        "kind": "slot",
        "slot_name": "labels",
        "value_type": "fields",
        "visualization_types": _ALLOW_LABELS,
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
        "visualization_types": _ALLOW_FILTERS,
    },
    "add_date_filter": {
        "kind": "helper",
        "helper": "add_date_filter",
        "visualization_types": _ALLOW_FILTERS,
    },
    "add_relative_date_filter": {
        "kind": "helper",
        "helper": "add_relative_date_filter",
        "visualization_types": _ALLOW_FILTERS,
    },
    "add_sort": {
        "kind": "helper",
        "helper": "add_sort",
        "visualization_types": _ALLOW_SORT,
    },
    "navigator": {
        "kind": "helper",
        "helper": "navigator",
        "visualization_types": _CARTESIAN_LINEAR,
    },
    "axis_title": {
        "kind": "helper",
        "helper": "axis_title",
        "visualization_types": _CARTESIAN,
    },
    "axis_scale": {
        "kind": "helper",
        "helper": "axis_scale",
        "visualization_types": _CARTESIAN,
    },
    "grid": {
        "kind": "helper",
        "helper": "grid",
        "visualization_types": _CARTESIAN,
    },
    "pagination": {
        "kind": "helper",
        "helper": "pagination",
        "visualization_types": _TABLE,
    },
    "table_size": {
        "kind": "helper",
        "helper": "table_size",
        "visualization_types": _TABLE,
    },
    "freeze_columns": {
        "kind": "helper",
        "helper": "freeze_columns",
        "visualization_types": _TABLE,
    },
    "column_background": {
        "kind": "helper",
        "helper": "column_background",
        "visualization_types": _TABLE,
    },
    "column_bars": {
        "kind": "helper",
        "helper": "column_bars",
        "visualization_types": _TABLE,
    },
    "column_title": {
        "kind": "helper",
        "helper": "column_title",
        "visualization_types": _TABLE,
    },
    "subtotals": {
        "kind": "helper",
        "helper": "subtotals",
        "visualization_types": frozenset({"pivotTable"}),
    },
    "measure_format": {
        "kind": "helper",
        "helper": "measure_format",
    },
    "shape": {
        "kind": "helper",
        "helper": "shape",
        "visualization_types": frozenset({"funnel"}),
    },
    "palette": {
        "kind": "helper",
        "helper": "palette",
        "visualization_types": visualization_types_with_color_encoding(),
    },
    "color_by_dimension": {
        "kind": "helper",
        "helper": "color_by_dimension",
        "visualization_types": visualization_types_for_wizard_encoding("color", "dimension"),
    },
    "color_by_measure": {
        "kind": "helper",
        "helper": "color_by_measure",
        "visualization_types": visualization_types_for_wizard_encoding("color", "measure"),
    },
    "color_by_measure_name": {
        "kind": "helper",
        "helper": "color_by_measure_name",
        "visualization_types": visualization_types_for_wizard_encoding("color", "measure_name"),
    },
    "shape_by_dimension": {
        "kind": "helper",
        "helper": "shape_by_dimension",
        "visualization_types": visualization_types_for_wizard_encoding("shape", "dimension"),
    },
    "shape_by_measure_name": {
        "kind": "helper",
        "helper": "shape_by_measure_name",
        "visualization_types": visualization_types_for_wizard_encoding("shape", "measure_name"),
    },
    "point_size_range": {
        "kind": "helper",
        "helper": "point_size_range",
        "visualization_types": frozenset({"scatter"}),
    },
    "font_size": {
        "kind": "helper",
        "helper": "font_size",
        "visualization_types": frozenset({"metric"}),
    },
    "font_color": {
        "kind": "helper",
        "helper": "font_color",
        "visualization_types": frozenset({"metric"}),
    },
    "measure_title_mode": {
        "kind": "helper",
        "helper": "measure_title_mode",
        "visualization_types": frozenset({"metric"}),
    },
    "add_hierarchy": {
        "kind": "helper",
        "helper": "add_hierarchy",
        "visualization_types": _TABLE_AND_CARTESIAN,
    },
}


def validate_method_applicability(method_name: str, visualization_type: str) -> None:
    spec = METHOD_SPECS.get(method_name)
    visualization_types = spec.get("visualization_types") if spec is not None else None
    if visualization_type and visualization_types and visualization_type not in visualization_types:
        raise DataLensConfigurationError(
            f"Method {method_name!r} is not applicable to visualization {visualization_type!r}. "
            f"Applicable visualizations: {sorted(visualization_types)}"
        )


def method_specs_for_visualization(visualization_type: str) -> dict[str, MethodSpec]:
    """Return the generated methods applicable to the visualization type.

    A method with no ``visualization_types`` (or an empty one) is universal and applies to
    every visualization. Otherwise the method applies only when ``visualization_type`` is a member of
    its ``visualization_types`` set.
    """
    out: dict[str, MethodSpec] = {}
    for name, spec in METHOD_SPECS.items():
        visualization_types = spec.get("visualization_types")
        if not visualization_types or visualization_type in visualization_types:
            out[name] = spec
    return out
