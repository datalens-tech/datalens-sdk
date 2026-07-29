from __future__ import annotations

import inspect
from typing import Any, Literal, cast, get_args, get_origin, get_type_hints

from datalens_sdk._generated.builders.charts import (
    CombinedChartWizardChartCreate,
    FlatTableWizardChartCreate,
    GeolayerWizardChartCreate,
    LineWizardChartCreate,
    MetricWizardChartCreate,
    PivotTableWizardChartCreate,
    ScatterWizardChartCreate,
    WizardChartCreateFactory,
)
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
    method_specs_for_viz,
)
from datalens_sdk._runtime.viz_specs import (
    VIZ_SPECS,
    factory_method_name,
    get_wizard_encoding,
    viz_ids_for_wizard_encoding,
)
from datalens_sdk.codegen import _HELPER_WRAPPERS, _viz_methods
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.wizard_chart import WizardChartUpdate

_KEY_FOR_KIND: dict[str, str] = {
    "placeholder": "wire_key",
    "data_field": "wire_key",
    "extra_setting": "wire_key",
    "ph_setting": "setting_key",
}

_ALL_KINDS = frozenset(_KEY_FOR_KIND) | {"helper"}
_CREATE_INFRASTRUCTURE_METHODS = frozenset({"dataset", "build", "execute", "viz_id", "wire_type", "to_spec"})
_UPDATE_PARITY_HELPERS = frozenset(
    {
        "chart_title",
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
        viz_ids = spec.get("viz_ids")
        if viz_ids:
            unknown = viz_ids - set(VIZ_SPECS)
            assert not unknown, f"{name} references unknown viz: {sorted(unknown)}"


def test_method_specs_for_viz_returns_universal_methods() -> None:
    universal = {name for name, spec in METHOD_SPECS.items() if not spec.get("viz_ids")}
    for viz_id in VIZ_SPECS:
        applicable = method_specs_for_viz(viz_id)
        assert universal <= set(applicable)


def test_method_specs_for_viz_filters_by_membership() -> None:
    assert "segments" in method_specs_for_viz("line")
    assert "segments" not in method_specs_for_viz("bar")
    assert "totals" in method_specs_for_viz("flatTable")
    assert "totals" not in method_specs_for_viz("line")


def test_method_specs_for_viz_returns_only_declared_methods() -> None:
    for viz_id in VIZ_SPECS:
        applicable = method_specs_for_viz(viz_id)
        assert set(applicable) <= set(METHOD_SPECS)


def test_methodspec_typeddict_import() -> None:
    spec: MethodSpec = {"kind": "extra_setting", "wire_key": "legendMode"}
    assert spec["kind"] == "extra_setting"


def test_sort_excluded_from_no_sort_viz() -> None:
    assert "sort" not in method_specs_for_viz("metric")
    assert "sort" not in method_specs_for_viz("treemap")


def test_sort_included_for_sortable_viz() -> None:
    assert "sort" in method_specs_for_viz("column")
    assert "sort" in method_specs_for_viz("bar")
    assert "sort" in method_specs_for_viz("flatTable")
    assert "sort" in method_specs_for_viz("scatter")


def test_sort_included_for_line_area_area100p() -> None:
    """line/area/area100p declare allowSort=True in the spec (see fixtures/) and
    must accept sort/add_sort. A prior SDK-only ``supports_sort=False`` flag wrongly
    excluded them; that flag is gone, so sortability follows ``allowSort`` alone."""
    for viz in ("line", "area", "area100p"):
        assert "sort" in method_specs_for_viz(viz)
        assert "add_sort" in method_specs_for_viz(viz)


def test_labels_excluded_from_metric() -> None:
    assert "labels" not in method_specs_for_viz("metric")


def test_labels_included_for_viz_with_allow_labels() -> None:
    assert "labels" in method_specs_for_viz("line")
    assert "labels" in method_specs_for_viz("column")
    assert "labels" in method_specs_for_viz("pie")
    assert "labels" in method_specs_for_viz("donut")


def test_add_sort_excluded_from_no_sort_viz() -> None:
    assert "add_sort" not in method_specs_for_viz("metric")
    assert "add_sort" not in method_specs_for_viz("treemap")


def test_add_filter_excluded_from_geolayer() -> None:
    assert "add_filter" not in method_specs_for_viz("geolayer")
    assert "add_date_filter" not in method_specs_for_viz("geolayer")
    assert "add_relative_date_filter" not in method_specs_for_viz("geolayer")


def test_add_filter_included_for_combined() -> None:
    assert "add_filter" in method_specs_for_viz("combined-chart")
    assert "add_date_filter" in method_specs_for_viz("combined-chart")


def test_helper_methods_returned_for_applicable_viz() -> None:
    assert "chart_title" in method_specs_for_viz("line")
    assert "chart_title" in method_specs_for_viz("flatTable")
    assert "chart_title" in method_specs_for_viz("metric")
    assert "description" in method_specs_for_viz("column")
    assert "measure_format" in method_specs_for_viz("scatter")


def test_table_helpers_scoped_to_table_viz() -> None:
    assert "pagination" in method_specs_for_viz("flatTable")
    assert "pagination" in method_specs_for_viz("pivotTable")
    assert "pagination" not in method_specs_for_viz("line")
    assert "freeze_columns" in method_specs_for_viz("flatTable")
    assert "freeze_columns" in method_specs_for_viz("pivotTable")
    assert "freeze_columns" not in method_specs_for_viz("line")
    assert "column_background" in method_specs_for_viz("pivotTable")
    assert "column_background" not in method_specs_for_viz("scatter")
    assert "color_by_measure" in method_specs_for_viz("flatTable")
    assert "subtotals" in method_specs_for_viz("pivotTable")
    assert "subtotals" not in method_specs_for_viz("flatTable")


def test_metric_helpers_scoped_to_metric() -> None:
    assert "font_size" in method_specs_for_viz("metric")
    assert "font_color" in method_specs_for_viz("metric")
    assert "measure_title_mode" in method_specs_for_viz("metric")
    assert "font_size" not in method_specs_for_viz("line")
    assert "font_color" not in method_specs_for_viz("column")


def test_navigator_scoped_to_cartesian_linear() -> None:
    assert "navigator" in method_specs_for_viz("line")
    assert "navigator" in method_specs_for_viz("column")
    assert "navigator" not in method_specs_for_viz("scatter")
    assert "navigator" not in method_specs_for_viz("metric")


def test_shape_helpers_have_explicit_dimension_and_measure_scopes() -> None:
    assert "shapes" not in _viz_methods("line")
    assert "shapes" not in _viz_methods("scatter")
    assert "shape_by_dimension" in method_specs_for_viz("line")
    assert "shape_by_dimension" in method_specs_for_viz("scatter")
    assert "shape_by_dimension" not in method_specs_for_viz("bar")
    assert "shape_by_measure_name" in method_specs_for_viz("line")
    assert "shape_by_measure_name" not in method_specs_for_viz("scatter")


def test_point_size_range_scoped_to_scatter() -> None:
    assert "point_size_range" in method_specs_for_viz("scatter")
    assert "point_size_range" not in method_specs_for_viz("line")


def test_color_helpers_are_scoped_to_explicit_encoding_capabilities() -> None:
    assert "palette" in method_specs_for_viz("line")
    assert "palette" in method_specs_for_viz("column")
    assert "palette" in method_specs_for_viz("scatter")
    assert "palette" in method_specs_for_viz("pie")
    assert "palette" in method_specs_for_viz("donut")
    assert "palette" not in method_specs_for_viz("metric")
    assert "color_by_dimension" in method_specs_for_viz("treemap")
    assert "color_by_measure" in method_specs_for_viz("treemap")
    assert "color_by_measure_name" not in method_specs_for_viz("treemap")


def test_wizard_encoding_compatibility_matrix_is_exact() -> None:
    assert set(_EXPECTED_ENCODING_METHODS_BY_VIZ) == set(VIZ_SPECS)
    for viz_id, expected_methods in _EXPECTED_ENCODING_METHODS_BY_VIZ.items():
        actual_methods = {
            method_name
            for (encoding, binding), method_name in _ENCODING_METHODS.items()
            if get_wizard_encoding(viz_id, cast(Any, encoding), cast(Any, binding)) is not None
        }
        assert actual_methods == expected_methods, viz_id


def test_method_specs_are_derived_from_wizard_encoding_matrix() -> None:
    for (encoding, binding), method_name in _ENCODING_METHODS.items():
        expected_viz_ids = viz_ids_for_wizard_encoding(cast(Any, encoding), cast(Any, binding))
        assert METHOD_SPECS[method_name]["viz_ids"] == expected_viz_ids


def test_encoding_placeholder_references_are_valid() -> None:
    for viz_id, spec in VIZ_SPECS.items():
        placeholders = cast(dict[str, object], spec.get("placeholders", {}))
        for encoding, binding in _ENCODING_METHODS:
            rule = get_wizard_encoding(viz_id, cast(Any, encoding), cast(Any, binding))
            if rule is None:
                continue
            for key in ("placeholder", "requires_field_in", "implicit_from", "category_placeholder"):
                placeholder_id = rule.get(key)
                if placeholder_id is not None:
                    assert placeholder_id in placeholders, f"{viz_id}.{encoding}.{binding}.{key}"
            for placeholder_id in rule.get("measure_placeholders", ()):
                assert placeholder_id in placeholders, f"{viz_id}.{encoding}.{binding}.measure_placeholders"


def test_add_hierarchy_scoped_to_table_and_cartesian() -> None:
    assert "add_hierarchy" in method_specs_for_viz("flatTable")
    assert "add_hierarchy" in method_specs_for_viz("pivotTable")
    assert "add_hierarchy" in method_specs_for_viz("line")
    assert "add_hierarchy" in method_specs_for_viz("column")
    assert "add_hierarchy" not in method_specs_for_viz("metric")
    assert "add_hierarchy" not in method_specs_for_viz("combined-chart")
    assert "add_hierarchy" not in method_specs_for_viz("geolayer")


def test_generated_wizard_leaves_inherit_their_category_base() -> None:
    assert issubclass(CombinedChartWizardChartCreate, _CombinedWizardChartCreate)
    assert issubclass(GeolayerWizardChartCreate, _GeolayerWizardChartCreate)
    assert issubclass(MetricWizardChartCreate, _MetricWizardChartCreate)
    assert issubclass(FlatTableWizardChartCreate, _TableWizardChartCreate)
    assert issubclass(PivotTableWizardChartCreate, _PivotWizardChartCreate)
    assert issubclass(ScatterWizardChartCreate, _ScatterWizardChartCreate)


def test_generated_axis_helpers_use_leaf_axis_placeholder_literals() -> None:
    for method_name in ("axis_title", "axis_scale", "grid"):
        assert method_name in LineWizardChartCreate.__dict__
        annotation = get_type_hints(LineWizardChartCreate.__dict__[method_name])["ph_id"]
        assert set(get_args(annotation)) == {"x", "y", "y2"}


def _expected_create_capabilities(viz_id: str) -> set[str]:
    capabilities = set(method_specs_for_viz(viz_id))
    if viz_id not in {"combined-chart", "geolayer"}:
        capabilities.update(_viz_methods(viz_id))
    if viz_id == "combined-chart":
        capabilities.update({"x", "add_layer"})
    if viz_id == "geolayer":
        capabilities.update({"add_dataset", "add_layer", "map_type", "map_center"})
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
    for viz_id in VIZ_SPECS:
        actual = _actual_create_capabilities(
            getattr(factory, factory_method_name(viz_id))(name="Chart", location=location)
        )
        expected = _expected_create_capabilities(viz_id)
        assert actual == expected, f"{viz_id}: extra={sorted(actual - expected)}, missing={sorted(expected - actual)}"


def test_raw_wizard_color_and_shape_placeholder_methods_are_not_generated() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    for viz_id in VIZ_SPECS:
        builder = getattr(factory, factory_method_name(viz_id))(name="Chart", location=location)
        for raw_method in ("colors", "color", "shapes"):
            assert not hasattr(builder, raw_method), f"{viz_id} unexpectedly exposes {raw_method}()"


def test_combined_exposes_group_a_without_placeholder_methods() -> None:
    builder = WizardChartCreateFactory(cast(Any, None)).combined_chart(
        name="Chart", location=EntryLocation.path("/Reports")
    )
    for method_name in (
        "legend",
        "tooltip_sum",
        "chart_title",
        "description",
        "add_filter",
        "add_sort",
        "measure_format",
    ):
        assert callable(getattr(builder, method_name, None))
    for method_name in ("y", "segments", "axis_title", "axis_scale", "grid"):
        assert not hasattr(builder, method_name)


def test_every_applicable_helper_is_exposed_by_its_create_leaf() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")

    for viz_id in VIZ_SPECS:
        builder = getattr(factory, factory_method_name(viz_id))(name="Chart", location=location)
        applicable_helpers = {name for name, spec in method_specs_for_viz(viz_id).items() if spec["kind"] == "helper"}
        missing = sorted(name for name in applicable_helpers if not callable(getattr(builder, name, None)))
        assert not missing, f"{viz_id}: missing applicable helper methods {missing}"


def test_helper_capabilities_are_generated_from_the_code_generation_matrix() -> None:
    declared_helpers = {name for name, spec in METHOD_SPECS.items() if spec["kind"] == "helper"}
    assert declared_helpers == set(_HELPER_WRAPPERS) | {"axis_title", "axis_scale", "grid"}


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
        viz_id = next(viz_id for viz_id in VIZ_SPECS if name in method_specs_for_viz(viz_id))
        create_method = getattr(getattr(factory, factory_method_name(viz_id))(name="Chart", location=location), name)
        assert _parameter_shape(update_method) == _parameter_shape(create_method), name
        if METHOD_SPECS[name].get("viz_ids"):
            assert "_check_viz_applicability" in inspect.getsource(update_method), name


def test_update_group_a_methods_match_create_signatures() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    group_a_kinds = {"extra_setting", "data_field", "ph_setting"}
    for name, spec in METHOD_SPECS.items():
        if spec.get("kind") not in group_a_kinds:
            continue
        if name in _UPDATE_PARITY_GROUP_A_EXCEPTIONS:
            continue
        update_method = WizardChartUpdate.__dict__.get(name)
        assert update_method is not None, f"group-A method {name!r} missing on WizardChartUpdate"
        viz_id = next(v for v in VIZ_SPECS if name in method_specs_for_viz(v))
        create_method = getattr(getattr(factory, factory_method_name(viz_id))(name="Chart", location=location), name)
        assert _parameter_shape(update_method) == _parameter_shape(create_method), name


def _is_bool_or_literal(hint: object) -> bool:
    return hint is bool or get_origin(hint) is Literal


def test_update_bool_and_literal_annotations_match_create() -> None:
    # Catches drift that ``_parameter_shape`` cannot see: Literal value sets
    # (e.g. ``'on'/'off'`` vs ``'yes'/'no'``) and bool flags. Two parameters are
    # intentionally NOT checked — both are known cosmetic gaps:
    #   - ``ph_id`` carries a per-viz ``Literal[...]`` on create but ``str`` on
    #     update;
    #   - ``fields`` (Sequence[...]) carries ``FieldRef`` on update vs
    #     ``FieldLike | str`` on create.
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/Reports")
    group_a_kinds = {"extra_setting", "data_field", "ph_setting"}
    for name, spec in METHOD_SPECS.items():
        if spec.get("kind") not in group_a_kinds or name in _UPDATE_PARITY_GROUP_A_EXCEPTIONS:
            continue
        update_method = WizardChartUpdate.__dict__.get(name)
        assert update_method is not None, name
        viz_id = next(v for v in VIZ_SPECS if name in method_specs_for_viz(v))
        create_method = getattr(getattr(factory, factory_method_name(viz_id))(name="Chart", location=location), name)
        create_hints = get_type_hints(create_method)
        update_hints = get_type_hints(update_method)
        for param in create_hints:
            if param in ("self", "ph_id") or param not in update_hints:
                continue
            if _is_bool_or_literal(create_hints[param]) or _is_bool_or_literal(update_hints[param]):
                assert create_hints[param] == update_hints[param], (
                    f"{name}.{param}: {create_hints[param]!r} != {update_hints[param]!r}"
                )
