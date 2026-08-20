from __future__ import annotations

import inspect
from typing import Any, Literal, cast, get_args, get_origin, get_type_hints

import pytest

from datalens_sdk._generated.builders import charts as generated_charts
from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._generated.dto import WIZARD_VISUALIZATION_STRUCTURE
from datalens_sdk._runtime.chart_builder_base import (
    _CombinedWizardChartCreate,
    _GeolayerWizardChartCreate,
    _MetricWizardChartCreate,
    _PivotWizardChartCreate,
    _ScatterWizardChartCreate,
    _TableWizardChartCreate,
)
from datalens_sdk._runtime.method_specs import (
    METHOD_SPECS,
    MethodSpec,
    method_requires_generated_structure,
    method_specs_for_visualization,
)
from datalens_sdk._runtime.viz_specs import factory_method_name
from datalens_sdk._runtime.wizard_semantics import (
    WIZARD_VISUALIZATION_SEMANTICS,
    get_wizard_encoding,
    visualization_types_for_wizard_encoding,
)
from datalens_sdk.codegen import _HELPER_WRAPPERS, _method_is_supported_by_structure, _wizard_slot_methods
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.wizard_chart import WizardChartUpdate

CombinedChartWizardChartCreate = cast(Any, getattr(generated_charts, "CombinedChartWizardChartCreate", None))
FlatTableWizardChartCreate = cast(Any, getattr(generated_charts, "FlatTableWizardChartCreate", None))
GeolayerWizardChartCreate = cast(Any, getattr(generated_charts, "GeolayerWizardChartCreate", None))
LineWizardChartCreate = cast(Any, getattr(generated_charts, "LineWizardChartCreate", None))
MetricWizardChartCreate = cast(Any, getattr(generated_charts, "MetricWizardChartCreate", None))
PivotTableWizardChartCreate = cast(Any, getattr(generated_charts, "PivotTableWizardChartCreate", None))
ScatterWizardChartCreate = cast(Any, getattr(generated_charts, "ScatterWizardChartCreate", None))

pytestmark = pytest.mark.skipif(
    not WIZARD_VISUALIZATION_STRUCTURE,
    reason="The public installation has no generated Wizard v3 contract",
)

_KEY_FOR_KIND: dict[str, str] = {
    "slot": "slot_name",
    "chart_setting": "setting_key",
    "slot_setting": "setting_key",
}

_ALL_KINDS = frozenset(_KEY_FOR_KIND) | {"helper"}
_CREATE_INFRASTRUCTURE_METHODS = frozenset({"dataset", "build", "execute", "viz_id", "wire_type", "to_spec"})
_UPDATE_PARITY_HELPERS = frozenset(
    {
        "chart_title",
        "label_mode",
        "labels_position",
        "navigator",
        "axis_title",
        "axis_scale",
        "grid",
        "pagination",
        "table_size",
        "freeze_columns",
        "description",
        "palette",
        "color_by_dimension",
        "color_by_measure",
        "color_by_measure_name",
        "measure_format",
        "column_background",
        "column_bars",
        "subtotals",
        "column_title",
        "add_filter",
        "add_date_filter",
        "add_relative_date_filter",
        "add_sort",
        "add_hierarchy",
        "shape_by_dimension",
        "shape_by_measure_name",
        "shape",
        "point_size_range",
        "font_size",
        "font_color",
        "measure_title_mode",
        "add_local_field",
        "add_aggregated_measure",
    }
)
_UPDATE_HELPER_EXCEPTIONS: frozenset[str] = frozenset()

# Group-A parity exceptions (extra_setting / data_field / ph_setting):
#   - ``sort`` is permanent (D2): create-side offers both the ``sort`` overwrite
#     and the ``add_sort`` append helper, while update-side only exposes
#     ``add_sort`` — an overwrite on update would be destructive.
#   - ``labels`` was temporary: phase 3c added ``WizardChartUpdate.labels`` and
#     lifted it from this set; the data_field parity check now covers it.
_UPDATE_PARITY_GROUP_A_EXCEPTIONS = frozenset({"sort"})

_STRUCTURE_REQUIREMENT_FIELDS = frozenset(
    {
        "required_chart_settings",
        "required_chart_setting_enum",
        "required_slot_carrier",
        "required_slot_settings",
        "required_slot_settings_any",
    }
)

_ENCODING_METHODS = {
    ("color", "dimension"): "color_by_dimension",
    ("color", "measure"): "color_by_measure",
    ("color", "measure_name"): "color_by_measure_name",
    ("shape", "dimension"): "shape_by_dimension",
    ("shape", "measure_name"): "shape_by_measure_name",
}

_EXPECTED_ENCODING_METHODS_BY_VIZ: dict[str, frozenset[str]] = {
    "area": frozenset({"color_by_dimension"}),
    "area100p": frozenset({"color_by_dimension"}),
    "bar": frozenset({"color_by_dimension", "color_by_measure", "color_by_measure_name"}),
    "bar100p": frozenset({"color_by_dimension"}),
    "column": frozenset({"color_by_dimension", "color_by_measure", "color_by_measure_name"}),
    "column100p": frozenset({"color_by_dimension"}),
    "combined-chart": frozenset(),
    "donut": frozenset({"color_by_dimension"}),
    "flatTable": frozenset({"color_by_measure"}),
    "funnel": frozenset({"color_by_dimension"}),
    "geolayer": frozenset(),
    "line": frozenset(
        {
            "color_by_dimension",
            "color_by_measure_name",
            "shape_by_dimension",
            "shape_by_measure_name",
        }
    ),
    "metric": frozenset(),
    "pie": frozenset({"color_by_dimension"}),
    "pivotTable": frozenset({"color_by_measure"}),
    "scatter": frozenset({"color_by_dimension", "color_by_measure", "shape_by_dimension"}),
    "treemap": frozenset({"color_by_dimension", "color_by_measure"}),
}


def _supported_method_specs(viz_id: str) -> dict[str, MethodSpec]:
    return {
        name: spec
        for name, spec in method_specs_for_visualization(viz_id).items()
        if _method_is_supported_by_structure(name, spec, WIZARD_VISUALIZATION_STRUCTURE[viz_id])
    }


def test_every_spec_has_known_kind() -> None:
    for name, spec in METHOD_SPECS.items():
        assert spec["kind"] in _ALL_KINDS, f"{name} has unknown kind {spec['kind']!r}"


def test_every_non_helper_spec_declares_its_wire_or_setting_key() -> None:
    for name, spec in METHOD_SPECS.items():
        if spec["kind"] == "helper":
            continue
        required_key = _KEY_FOR_KIND[spec["kind"]]
        assert spec.get(required_key), f"{name} misses {required_key}"


def test_every_helper_spec_declares_helper_field() -> None:
    for name, spec in METHOD_SPECS.items():
        if spec["kind"] != "helper":
            continue
        helper = spec.get("helper")
        assert helper, f"helper spec {name!r} must declare a non-empty 'helper' field"
        assert isinstance(helper, str), f"helper spec {name!r}.helper must be a str"


def test_schema_derived_helper_carriers_live_in_method_specs() -> None:
    assert {
        name: spec["required_chart_settings"]
        for name, spec in METHOD_SPECS.items()
        if "required_chart_settings" in spec
    } == {
        "chart_title": frozenset({"title", "titleMode"}),
        "font_color": frozenset({"metricFontColor"}),
        "font_size": frozenset({"metricFontSize"}),
        "freeze_columns": frozenset({"pinnedColumns"}),
        "navigator": frozenset({"navigatorSettings"}),
        "pagination": frozenset({"limit", "pagination"}),
        "shape": frozenset({"shape"}),
        "table_size": frozenset({"size"}),
    }
    assert {
        name: spec["required_slot_settings"] for name, spec in METHOD_SPECS.items() if "required_slot_settings" in spec
    } == {
        "axis_scale": frozenset({"scale", "scaleValue", "type"}),
        "axis_title": frozenset({"title", "titleValue"}),
        "grid": frozenset({"grid", "gridStep", "gridStepValue"}),
        "point_size_range": frozenset({"maxRadius", "minRadius", "radius"}),
    }
    assert {
        name: spec["required_slot_settings_any"]
        for name, spec in METHOD_SPECS.items()
        if "required_slot_settings_any" in spec
    } == {"labels_position": frozenset({"labelsPosition", "position"})}
    assert {
        name: spec["required_slot_carrier"] for name, spec in METHOD_SPECS.items() if "required_slot_carrier" in spec
    } == {
        "add_sort": "sort",
        "label_mode": "labels",
        "labels_position": "labels",
        "point_size_range": "size",
    }


def test_method_requires_generated_structure_covers_every_carrier_descriptor() -> None:
    expected = {name for name, spec in METHOD_SPECS.items() if _STRUCTURE_REQUIREMENT_FIELDS & spec.keys()}
    actual = {name for name in METHOD_SPECS if method_requires_generated_structure(name)}

    assert actual == expected
    assert method_requires_generated_structure("freeze_columns")
    assert not method_requires_generated_structure("unknown")


def test_literal_specs_declare_literal_values() -> None:
    for name, spec in METHOD_SPECS.items():
        if spec.get("value_type") == "literal":
            values = spec.get("literal_values")
            assert values, f"{name} is literal but declares no literal_values"
            assert all(isinstance(v, str) and v for v in values)


def test_bool_specs_declare_value_map() -> None:
    for name, spec in METHOD_SPECS.items():
        if spec.get("value_type") == "bool":
            value_map = spec.get("value_map")
            assert value_map, f"{name} is bool but declares no value_map"
            assert set(value_map) == {"true", "false"}


def test_viz_ids_reference_existing_viz() -> None:
    for name, spec in METHOD_SPECS.items():
        visualization_types = spec.get("visualization_types")
        if visualization_types:
            unknown = visualization_types - set(WIZARD_VISUALIZATION_SEMANTICS)
            assert not unknown, f"{name} references unknown viz: {sorted(unknown)}"


def test_method_specs_for_visualization_returns_universal_methods() -> None:
    universal = {
        name
        for name, spec in METHOD_SPECS.items()
        if not spec.get("visualization_types") and not spec.get("excluded_visualization_types")
    }
    for viz_id in WIZARD_VISUALIZATION_SEMANTICS:
        applicable = method_specs_for_visualization(viz_id)
        assert universal <= set(applicable)


def test_method_specs_for_visualization_filters_by_sdk_policy() -> None:
    assert "add_hierarchy" in method_specs_for_visualization("line")
    assert "add_hierarchy" not in method_specs_for_visualization("geolayer")
    assert "chart_title" in method_specs_for_visualization("line")
    assert "chart_title" not in method_specs_for_visualization("metric")


def test_methodspec_typeddict_import() -> None:
    spec: MethodSpec = {"kind": "chart_setting", "setting_key": "legendMode"}
    assert spec["kind"] == "chart_setting"


def test_sort_excluded_from_no_sort_viz() -> None:
    assert "sort" not in _supported_method_specs("metric")
    assert "sort" not in _supported_method_specs("treemap")


def test_sort_included_for_sortable_viz() -> None:
    assert "sort" in _supported_method_specs("column")
    assert "sort" in _supported_method_specs("bar")
    assert "sort" in _supported_method_specs("flatTable")
    assert "sort" in _supported_method_specs("scatter")


def test_sort_included_for_line_area_area100p() -> None:
    """line/area/area100p declare allowSort=True in the spec (see fixtures/) and
    must accept sort/add_sort. A prior SDK-only ``supports_sort=False`` flag wrongly
    excluded them; that flag is gone, so sortability follows ``allowSort`` alone."""
    for viz in ("line", "area", "area100p"):
        assert "sort" in _supported_method_specs(viz)
        assert "add_sort" in _supported_method_specs(viz)


def test_labels_excluded_from_metric() -> None:
    assert "labels" not in _supported_method_specs("metric")


def test_labels_included_for_viz_with_allow_labels() -> None:
    assert "labels" in _supported_method_specs("line")
    assert "labels" in _supported_method_specs("column")
    assert "labels" in _supported_method_specs("pie")
    assert "labels" in _supported_method_specs("donut")


def test_add_sort_excluded_from_no_sort_viz() -> None:
    assert "add_sort" not in _supported_method_specs("metric")
    assert "add_sort" not in _supported_method_specs("treemap")


def test_add_filter_included_for_geolayer() -> None:
    assert "add_filter" in _supported_method_specs("geolayer")
    assert "add_date_filter" in _supported_method_specs("geolayer")
    assert "add_relative_date_filter" in _supported_method_specs("geolayer")


def test_add_filter_included_for_combined() -> None:
    assert "add_filter" in _supported_method_specs("combined-chart")
    assert "add_date_filter" in _supported_method_specs("combined-chart")


def test_helper_methods_returned_for_applicable_viz() -> None:
    assert "chart_title" in _supported_method_specs("line")
    assert "chart_title" in _supported_method_specs("flatTable")
    assert "chart_title" not in _supported_method_specs("metric")
    assert "description" in _supported_method_specs("column")
    assert "measure_format" in _supported_method_specs("scatter")


def test_table_helpers_scoped_to_table_viz() -> None:
    assert "pagination" in _supported_method_specs("flatTable")
    assert "pagination" in _supported_method_specs("pivotTable")
    assert "pagination" not in _supported_method_specs("line")
    assert "column_background" in _supported_method_specs("pivotTable")
    assert "column_background" not in _supported_method_specs("scatter")
    assert "color_by_measure" in _supported_method_specs("flatTable")
    assert "subtotals" in _supported_method_specs("pivotTable")
    assert "subtotals" not in _supported_method_specs("flatTable")


def test_freeze_columns_generated_owners_match_pinned_columns_carriers() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    generated_owners = {
        viz_id
        for viz_id in WIZARD_VISUALIZATION_STRUCTURE
        if callable(
            getattr(
                getattr(factory, factory_method_name(viz_id))(name="Chart", location=location),
                "freeze_columns",
                None,
            )
        )
    }
    descriptor_owners = {
        viz_id for viz_id in WIZARD_VISUALIZATION_STRUCTURE if "freeze_columns" in _supported_method_specs(viz_id)
    }
    carrier_owners = {
        viz_id
        for viz_id, structure in WIZARD_VISUALIZATION_STRUCTURE.items()
        if "pinnedColumns" in structure["chart_settings"]
    }

    assert generated_owners == descriptor_owners == carrier_owners == {"flatTable", "pivotTable"}


def test_metric_helpers_scoped_to_metric() -> None:
    assert "font_size" in _supported_method_specs("metric")
    assert "font_color" in _supported_method_specs("metric")
    assert "measure_title_mode" in _supported_method_specs("metric")
    assert "font_size" not in _supported_method_specs("line")
    assert "font_color" not in _supported_method_specs("column")


def test_navigator_scoped_to_cartesian_linear() -> None:
    assert "navigator" in _supported_method_specs("line")
    assert "navigator" in _supported_method_specs("column")
    assert "navigator" not in _supported_method_specs("scatter")
    assert "navigator" not in _supported_method_specs("metric")


def test_shape_helpers_have_explicit_dimension_and_measure_scopes() -> None:
    assert "shapes" not in _wizard_slot_methods("line", WIZARD_VISUALIZATION_STRUCTURE["line"])
    assert "shapes" not in _wizard_slot_methods("scatter", WIZARD_VISUALIZATION_STRUCTURE["scatter"])
    assert "shape_by_dimension" in _supported_method_specs("line")
    assert "shape_by_dimension" in _supported_method_specs("scatter")
    assert "shape_by_dimension" not in _supported_method_specs("bar")
    assert "shape_by_measure_name" in _supported_method_specs("line")
    assert "shape_by_measure_name" not in _supported_method_specs("scatter")


def test_point_size_range_scoped_to_scatter() -> None:
    assert "point_size_range" in _supported_method_specs("scatter")
    assert "point_size_range" not in _supported_method_specs("line")


def test_color_helpers_are_scoped_to_explicit_encoding_capabilities() -> None:
    assert "palette" in _supported_method_specs("line")
    assert "palette" in _supported_method_specs("column")
    assert "palette" in _supported_method_specs("scatter")
    assert "palette" in _supported_method_specs("pie")
    assert "palette" in _supported_method_specs("donut")
    assert "palette" not in _supported_method_specs("metric")
    assert "color_by_dimension" in _supported_method_specs("treemap")
    assert "color_by_measure" in _supported_method_specs("treemap")
    assert "color_by_measure_name" not in _supported_method_specs("treemap")


def test_wizard_encoding_compatibility_matrix_is_exact() -> None:
    assert set(_EXPECTED_ENCODING_METHODS_BY_VIZ) == set(WIZARD_VISUALIZATION_SEMANTICS)
    for viz_id, expected_methods in _EXPECTED_ENCODING_METHODS_BY_VIZ.items():
        actual_methods = {
            method_name
            for (encoding, binding), method_name in _ENCODING_METHODS.items()
            if get_wizard_encoding(viz_id, cast(Any, encoding), cast(Any, binding)) is not None
        }
        assert actual_methods == expected_methods, viz_id


def test_method_specs_are_derived_from_wizard_encoding_matrix() -> None:
    for (encoding, binding), method_name in _ENCODING_METHODS.items():
        expected_viz_ids = visualization_types_for_wizard_encoding(cast(Any, encoding), cast(Any, binding))
        assert METHOD_SPECS[method_name]["visualization_types"] == expected_viz_ids


def test_add_hierarchy_scoped_to_table_and_cartesian() -> None:
    assert "add_hierarchy" in _supported_method_specs("flatTable")
    assert "add_hierarchy" in _supported_method_specs("pivotTable")
    assert "add_hierarchy" in _supported_method_specs("line")
    assert "add_hierarchy" in _supported_method_specs("column")
    assert "add_hierarchy" not in _supported_method_specs("metric")
    assert "add_hierarchy" not in _supported_method_specs("combined-chart")
    assert "add_hierarchy" not in _supported_method_specs("geolayer")


def test_generated_wizard_leaves_inherit_their_category_base() -> None:
    assert issubclass(CombinedChartWizardChartCreate, _CombinedWizardChartCreate)
    assert issubclass(GeolayerWizardChartCreate, _GeolayerWizardChartCreate)
    assert issubclass(MetricWizardChartCreate, _MetricWizardChartCreate)
    assert issubclass(FlatTableWizardChartCreate, _TableWizardChartCreate)
    assert issubclass(PivotTableWizardChartCreate, _PivotWizardChartCreate)
    assert issubclass(ScatterWizardChartCreate, _ScatterWizardChartCreate)


def test_generated_axis_helpers_use_leaf_axis_slot_literals() -> None:
    for method_name in ("axis_title", "axis_scale", "grid"):
        assert method_name in LineWizardChartCreate.__dict__
        annotation = get_type_hints(LineWizardChartCreate.__dict__[method_name])["slot_name"]
        assert set(get_args(annotation)) == {"x", "y", "y2"}


def _expected_create_capabilities(viz_id: str) -> set[str]:
    capabilities = set(_supported_method_specs(viz_id))
    if viz_id not in {"combined-chart", "geolayer"}:
        capabilities.update(_wizard_slot_methods(viz_id, WIZARD_VISUALIZATION_STRUCTURE[viz_id]))
    if viz_id == "combined-chart":
        capabilities.update({"x", "add_layer"})
    if viz_id == "geolayer":
        capabilities.update({"add_dataset", "add_layer", "map_center"})
    return capabilities


def _actual_create_capabilities(builder: object) -> set[str]:
    return {
        name
        for name in dir(builder)
        if not name.startswith("_") and callable(getattr(builder, name)) and name not in _CREATE_INFRASTRUCTURE_METHODS
    }


def test_create_leaf_capabilities_exactly_match_method_specs() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    for viz_id in WIZARD_VISUALIZATION_SEMANTICS:
        actual = _actual_create_capabilities(
            getattr(factory, factory_method_name(viz_id))(name="Chart", location=location)
        )
        expected = _expected_create_capabilities(viz_id)
        assert actual == expected, f"{viz_id}: extra={sorted(actual - expected)}, missing={sorted(expected - actual)}"


def test_raw_wizard_color_and_shape_slot_methods_are_not_generated() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    for viz_id in WIZARD_VISUALIZATION_SEMANTICS:
        builder = getattr(factory, factory_method_name(viz_id))(name="Chart", location=location)
        for raw_method in ("colors", "color", "shapes"):
            assert not hasattr(builder, raw_method), f"{viz_id} unexpectedly exposes {raw_method}()"


def test_combined_exposes_layer_and_chart_capabilities_without_raw_slots() -> None:
    builder = WizardChartCreateFactory(cast(Any, None)).combined_chart(
        name="Chart", location=EntryLocation.path("/Reports")
    )
    for method_name in (
        "description",
        "add_filter",
        "add_sort",
        "labels",
        "labels_position",
        "legend",
        "tooltip",
        "chart_title",
        "measure_format",
    ):
        assert callable(getattr(builder, method_name, None))
    for method_name in (
        "y",
        "segments",
        "axis_title",
        "axis_scale",
        "grid",
        "tooltip_sum",
    ):
        assert not hasattr(builder, method_name)


def test_every_applicable_helper_is_exposed_by_its_create_leaf() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")

    for viz_id in WIZARD_VISUALIZATION_SEMANTICS:
        builder = getattr(factory, factory_method_name(viz_id))(name="Chart", location=location)
        applicable_helpers = {
            name for name, spec in _supported_method_specs(viz_id).items() if spec["kind"] == "helper"
        }
        missing = sorted(name for name in applicable_helpers if not callable(getattr(builder, name, None)))
        assert not missing, f"{viz_id}: missing applicable helper methods {missing}"


def test_helper_capabilities_are_generated_from_the_code_generation_matrix() -> None:
    declared_helpers = {name for name, spec in METHOD_SPECS.items() if spec["kind"] == "helper"}
    assert declared_helpers == set(_HELPER_WRAPPERS) | {"axis_title", "axis_scale", "grid", "label_mode"}


def _parameter_shape(method: Any) -> tuple[tuple[str, object, object], ...]:
    return tuple(
        (parameter.name, parameter.kind, parameter.default)
        for parameter in inspect.signature(method).parameters.values()
        if parameter.name != "self"
    )


def test_update_helper_parity_has_explicit_exceptions_and_guards() -> None:
    declared_helpers = {name for name, spec in METHOD_SPECS.items() if spec["kind"] == "helper"}
    assert declared_helpers == _UPDATE_PARITY_HELPERS | _UPDATE_HELPER_EXCEPTIONS

    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    for name in _UPDATE_PARITY_HELPERS:
        update_method = WizardChartUpdate.__dict__[name]
        assert callable(update_method)
        viz_id = next(viz_id for viz_id in WIZARD_VISUALIZATION_SEMANTICS if name in _supported_method_specs(viz_id))
        create_method = getattr(getattr(factory, factory_method_name(viz_id))(name="Chart", location=location), name)
        assert _parameter_shape(update_method) == _parameter_shape(create_method), name
        if METHOD_SPECS[name].get("visualization_types"):
            assert "_check_viz_applicability" in inspect.getsource(update_method), name


def test_update_group_a_methods_match_create_signatures() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    group_a_kinds = {"slot", "chart_setting", "slot_setting"}
    for name, spec in METHOD_SPECS.items():
        if spec.get("kind") not in group_a_kinds:
            continue
        if name in _UPDATE_PARITY_GROUP_A_EXCEPTIONS:
            continue
        update_method = WizardChartUpdate.__dict__.get(name)
        assert update_method is not None, f"group-A method {name!r} missing on WizardChartUpdate"
        viz_id = next(v for v in WIZARD_VISUALIZATION_SEMANTICS if name in _supported_method_specs(v))
        create_method = getattr(getattr(factory, factory_method_name(viz_id))(name="Chart", location=location), name)
        assert _parameter_shape(update_method) == _parameter_shape(create_method), name


def _is_bool_or_literal(hint: object) -> bool:
    return hint is bool or get_origin(hint) is Literal


def test_update_bool_and_literal_annotations_match_create() -> None:
    # Catches drift that ``_parameter_shape`` cannot see: Literal value sets
    # (e.g. ``'on'/'off'`` vs ``'yes'/'no'``) and bool flags. Two parameters are
    # intentionally NOT checked — both are known cosmetic gaps:
    #   - ``slot_name`` carries a per-viz ``Literal[...]`` on create but ``str`` on
    #     update;
    #   - ``fields`` (Sequence[...]) carries ``FieldRef`` on update vs
    #     ``FieldLike | str`` on create.
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    group_a_kinds = {"slot", "chart_setting", "slot_setting"}
    for name, spec in METHOD_SPECS.items():
        if spec.get("kind") not in group_a_kinds or name in _UPDATE_PARITY_GROUP_A_EXCEPTIONS:
            continue
        update_method = WizardChartUpdate.__dict__.get(name)
        assert update_method is not None, name
        viz_id = next(v for v in WIZARD_VISUALIZATION_SEMANTICS if name in _supported_method_specs(v))
        create_method = getattr(getattr(factory, factory_method_name(viz_id))(name="Chart", location=location), name)
        create_hints = get_type_hints(create_method)
        update_hints = get_type_hints(update_method)
        for param in create_hints:
            if param in ("self", "slot_name") or param not in update_hints:
                continue
            if _is_bool_or_literal(create_hints[param]) or _is_bool_or_literal(update_hints[param]):
                assert create_hints[param] == update_hints[param], (
                    f"{name}.{param}: {create_hints[param]!r} != {update_hints[param]!r}"
                )
