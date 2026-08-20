from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from datalens_sdk._runtime.wizard_semantics import (
    visualization_types_for_wizard_encoding,
    visualization_types_with_color_encoding,
    visualization_types_with_label_mode,
)
from datalens_sdk._runtime.wizard_structure import WizardSlotStructure, WizardVisualizationStructure
from datalens_sdk.errors import DataLensConfigurationError

MethodKind = Literal["slot", "chart_setting", "slot_setting", "helper"]

MethodValueType = Literal["str", "bool", "literal", "fields"]
CarrierScope = Literal["builder_surface", "active_layer"]
CarrierFailureCode = Literal[
    "missing_chart_setting",
    "missing_chart_setting_enum",
    "missing_slot",
    "missing_slot_setting",
    "missing_any_slot_setting",
    "missing_active_layer",
    "unknown_active_layer",
]


@dataclass(frozen=True)
class CarrierFailure:
    code: CarrierFailureCode
    scope: CarrierScope
    carrier: str | None = None
    missing: tuple[str, ...] = ()
    layer_type: str | None = None


@dataclass(frozen=True)
class CarrierResolution:
    matched_slot_names: tuple[str, ...] = ()
    failure: CarrierFailure | None = None

    @property
    def supported(self) -> bool:
        return self.failure is None


class MethodSpec(TypedDict, total=False):
    kind: MethodKind
    visualization_types: frozenset[str]
    excluded_visualization_types: frozenset[str]
    slot_name: str
    setting_key: str
    required_chart_settings: frozenset[str]
    required_chart_setting_enum: tuple[str, frozenset[str]]
    required_slot_carrier: str
    required_slot_settings: frozenset[str]
    required_slot_settings_any: frozenset[str]
    value_type: MethodValueType
    literal_values: tuple[str, ...]
    value_map: dict[str, str]
    helper: str


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

_TABLE: frozenset[str] = frozenset({"flatTable", "pivotTable"})

_LABEL_MODE_VISUALIZATIONS = visualization_types_with_label_mode("absolute") | visualization_types_with_label_mode(
    "percent"
)

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
    "tooltip": {
        "kind": "chart_setting",
        "setting_key": "tooltip",
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
    },
    "label_mode": {
        "kind": "helper",
        "helper": "label_mode",
        "visualization_types": _LABEL_MODE_VISUALIZATIONS,
        "required_slot_carrier": "labels",
    },
    "labels_position": {
        "kind": "helper",
        "helper": "labels_position",
        "required_slot_carrier": "labels",
        "required_slot_settings_any": frozenset({"labelsPosition", "position"}),
    },
    "tooltip_percentage_base": {
        "kind": "chart_setting",
        "setting_key": "tooltipPercentageBase",
        "value_type": "literal",
        "literal_values": ("auto", "first", "previous"),
    },
    "axis_visibility": {
        "kind": "slot_setting",
        "setting_key": "axisVisibility",
        "value_type": "literal",
        "literal_values": ("show", "hide"),
    },
    "hide_labels": {
        "kind": "slot_setting",
        "setting_key": "hideLabels",
        "value_type": "bool",
        "value_map": _BOOL_YES_NO,
    },
    "nulls_mode": {
        "kind": "slot_setting",
        "setting_key": "nulls",
        "value_type": "literal",
        "literal_values": ("ignore", "connect", "as-0"),
    },
    "segments": {
        "kind": "slot",
        "slot_name": "segments",
        "value_type": "fields",
    },
    "sort": {
        "kind": "slot",
        "slot_name": "sort",
        "value_type": "fields",
    },
    "labels": {
        "kind": "slot",
        "slot_name": "labels",
        "value_type": "fields",
    },
    # Group B — helper methods (richer logic in category base classes;
    # these declarations drive codegen applicability and update-guard only).
    "chart_title": {
        "kind": "helper",
        "helper": "chart_title",
        "excluded_visualization_types": frozenset({"metric"}),
        "required_chart_settings": frozenset({"title", "titleMode"}),
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
    },
    "add_date_filter": {
        "kind": "helper",
        "helper": "add_date_filter",
    },
    "add_relative_date_filter": {
        "kind": "helper",
        "helper": "add_relative_date_filter",
    },
    "add_sort": {
        "kind": "helper",
        "helper": "add_sort",
        "required_slot_carrier": "sort",
    },
    "navigator": {
        "kind": "helper",
        "helper": "navigator",
        "required_chart_settings": frozenset({"navigatorSettings"}),
    },
    "axis_title": {
        "kind": "helper",
        "helper": "axis_title",
        "required_slot_settings": frozenset({"title", "titleValue"}),
    },
    "axis_scale": {
        "kind": "helper",
        "helper": "axis_scale",
        "required_slot_settings": frozenset({"scale", "scaleValue", "type"}),
    },
    "grid": {
        "kind": "helper",
        "helper": "grid",
        "required_slot_settings": frozenset({"grid", "gridStep", "gridStepValue"}),
    },
    "pagination": {
        "kind": "helper",
        "helper": "pagination",
        "required_chart_settings": frozenset({"limit", "pagination"}),
    },
    "table_size": {
        "kind": "helper",
        "helper": "table_size",
        "required_chart_settings": frozenset({"size"}),
    },
    "freeze_columns": {
        "kind": "helper",
        "helper": "freeze_columns",
        "required_chart_settings": frozenset({"pinnedColumns"}),
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
        "required_chart_settings": frozenset({"shape"}),
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
        "required_slot_carrier": "size",
        "required_slot_settings": frozenset({"maxRadius", "minRadius", "radius"}),
    },
    "font_size": {
        "kind": "helper",
        "helper": "font_size",
        "required_chart_settings": frozenset({"metricFontSize"}),
    },
    "font_color": {
        "kind": "helper",
        "helper": "font_color",
        "required_chart_settings": frozenset({"metricFontColor"}),
    },
    "measure_title_mode": {
        "kind": "helper",
        "helper": "measure_title_mode",
        "required_chart_setting_enum": ("titleMode", frozenset({"by-field", "hide", "manual"})),
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
    excluded_visualization_types = spec.get("excluded_visualization_types") if spec is not None else None
    if visualization_type and (
        (visualization_types and visualization_type not in visualization_types)
        or (excluded_visualization_types and visualization_type in excluded_visualization_types)
    ):
        applicability = (
            f"Applicable visualizations: {sorted(visualization_types)}"
            if visualization_types
            else f"Excluded visualizations: {sorted(excluded_visualization_types or ())}"
        )
        raise DataLensConfigurationError(
            f"Method {method_name!r} is not applicable to visualization {visualization_type!r}. {applicability}"
        )


def method_requires_generated_structure(method_name: str) -> bool:
    spec = METHOD_SPECS.get(method_name)
    return spec is not None and any(
        requirement in spec
        for requirement in (
            "required_chart_settings",
            "required_chart_setting_enum",
            "required_slot_carrier",
            "required_slot_settings",
            "required_slot_settings_any",
        )
    )


_SLOT_ADDRESSABLE_METHODS = frozenset(
    {"axis_scale", "axis_title", "axis_visibility", "grid", "hide_labels", "nulls_mode"}
)


def _carrier_failure(
    code: CarrierFailureCode,
    scope: CarrierScope,
    *,
    carrier: str | None = None,
    missing: tuple[str, ...] = (),
    layer_type: str | None = None,
) -> CarrierResolution:
    return CarrierResolution(
        failure=CarrierFailure(
            code=code,
            scope=scope,
            carrier=carrier,
            missing=missing,
            layer_type=layer_type,
        )
    )


def resolve_method_carriers(
    method_name: str,
    spec: MethodSpec,
    structure: WizardVisualizationStructure,
    *,
    scope: CarrierScope,
    active_layer_type: str | None = None,
) -> CarrierResolution:
    """Resolve generated carriers for builder generation or one active update layer."""

    chart_settings = structure["chart_settings"]
    root_slots = structure["slots"]
    layers = structure["layers"]

    kind = spec.get("kind")
    setting_key = spec.get("setting_key")
    if kind == "chart_setting":
        if not isinstance(setting_key, str) or setting_key not in chart_settings:
            return _carrier_failure(
                "missing_chart_setting",
                scope,
                carrier=setting_key if isinstance(setting_key, str) else None,
            )
        return CarrierResolution()

    required_chart_settings = spec.get("required_chart_settings", frozenset())
    missing_chart_settings = tuple(sorted(required_chart_settings - chart_settings.keys()))
    if missing_chart_settings:
        return _carrier_failure("missing_chart_setting", scope, missing=missing_chart_settings)
    required_chart_setting_enum = spec.get("required_chart_setting_enum")
    if required_chart_setting_enum is not None:
        chart_setting, required_values = required_chart_setting_enum
        setting = chart_settings.get(chart_setting)
        enum = set(setting.get("enum", ())) if setting is not None else set()
        missing_values = tuple(sorted(required_values - enum))
        if missing_values:
            return _carrier_failure(
                "missing_chart_setting_enum",
                scope,
                carrier=chart_setting,
                missing=missing_values,
            )

    slot_maps: list[dict[str, WizardSlotStructure]]
    if scope == "active_layer" and layers:
        if active_layer_type is None:
            return _carrier_failure("missing_active_layer", scope)
        layer = layers.get(active_layer_type)
        if layer is None:
            return _carrier_failure("unknown_active_layer", scope, layer_type=active_layer_type)
        slot_maps = [layer["slots"]]
    elif scope == "builder_surface" and method_name in _SLOT_ADDRESSABLE_METHODS:
        slot_maps = [root_slots]
    elif scope == "builder_surface":
        slot_maps = [root_slots, *(layer["slots"] for layer in layers.values())]
    else:
        slot_maps = [root_slots]

    slot_name = spec.get("slot_name") if kind == "slot" else spec.get("required_slot_carrier")
    if slot_name == "sort" and scope == "builder_surface" and layers:
        if "sort" not in root_slots and not all("sort" in layer["slots"] for layer in layers.values()):
            return _carrier_failure("missing_slot", scope, carrier="sort")
        return CarrierResolution(matched_slot_names=("sort",))

    if isinstance(slot_name, str):
        matching_slots = [(slot_name, slots[slot_name]) for slots in slot_maps if slot_name in slots]
        if not matching_slots:
            return _carrier_failure("missing_slot", scope, carrier=slot_name)
    else:
        matching_slots = [(name, slot) for slots in slot_maps for name, slot in slots.items()]

    if kind == "slot":
        return CarrierResolution(matched_slot_names=tuple(sorted({name for name, _ in matching_slots})))

    required_slot_settings = spec.get("required_slot_settings", frozenset())
    required_slot_settings_any = spec.get("required_slot_settings_any", frozenset())
    if kind == "slot_setting" and isinstance(setting_key, str):
        required_slot_settings = frozenset({setting_key})

    matching_names: set[str] = set()
    closest_missing: tuple[str, ...] = ()
    for name, slot in matching_slots:
        settings = slot["settings"]
        missing = required_slot_settings - settings.keys()
        if missing:
            closest_missing = tuple(sorted(missing))
            continue
        if required_slot_settings_any and not required_slot_settings_any & settings.keys():
            closest_missing = tuple(sorted(required_slot_settings_any))
            continue
        matching_names.add(name)

    if (required_slot_settings or required_slot_settings_any) and not matching_names:
        code: CarrierFailureCode = (
            "missing_any_slot_setting"
            if required_slot_settings_any and not required_slot_settings
            else "missing_slot_setting"
        )
        return _carrier_failure(code, scope, carrier=slot_name, missing=closest_missing)
    return CarrierResolution(matched_slot_names=tuple(sorted(matching_names)))


def method_specs_for_visualization(visualization_type: str) -> dict[str, MethodSpec]:
    """Return the generated methods applicable to the visualization type.

    A method with no ``visualization_types`` (or an empty one) is universal and applies to
    every visualization. Otherwise the method applies only when ``visualization_type`` is a member of
    its ``visualization_types`` set.
    """
    out: dict[str, MethodSpec] = {}
    for name, spec in METHOD_SPECS.items():
        visualization_types = spec.get("visualization_types")
        excluded_visualization_types = spec.get("excluded_visualization_types")
        if (not visualization_types or visualization_type in visualization_types) and (
            not excluded_visualization_types or visualization_type not in excluded_visualization_types
        ):
            out[name] = spec
    return out
