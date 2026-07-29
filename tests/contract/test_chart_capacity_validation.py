from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._runtime.viz_specs import VIZ_SPECS, factory_method_name, get_viz_spec
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation


def _dataset() -> Dataset:
    return Dataset(
        id="ds1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_d1", "title": "Dim1", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
            {"guid": "g_d2", "title": "Dim2", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
            {"guid": "g_m1", "title": "Meas1", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "g_m2", "title": "Meas2", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ),
    )


# ---------------------------------------------------------------------------
# G3a: Leaf facades expose only applicable placeholder methods (no drift)
# ---------------------------------------------------------------------------


def test_line_has_x_y_y2_but_not_columns_or_rows() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.line(name="T", location=EntryLocation.path("/F"))
    assert hasattr(builder, "x")
    assert hasattr(builder, "y")
    assert hasattr(builder, "y2")
    assert not hasattr(builder, "columns")
    assert not hasattr(builder, "rows")


def test_pie_has_x_y_and_semantic_color_but_not_raw_colors_y2_or_points() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.pie(name="T", location=EntryLocation.path("/F"))
    assert hasattr(builder, "x")
    assert hasattr(builder, "y")
    assert hasattr(builder, "color_by_dimension")
    assert not hasattr(builder, "colors")
    assert not hasattr(builder, "y2")
    assert not hasattr(builder, "points")
    assert not hasattr(builder, "size")


def test_funnel_exposes_its_fields_color_and_specific_settings() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.funnel(name="T", location=EntryLocation.path("/F"))
    for method in ("x", "y", "color_by_dimension", "label_mode", "shape", "tooltip_percentage_base"):
        assert hasattr(builder, method), f"funnel missing method: {method}"
    assert not hasattr(builder, "color_by_measure")
    assert not hasattr(builder, "axis_scale")
    assert not hasattr(builder, "y2")


def test_scatter_has_axes_points_size_and_semantic_color_methods() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.scatter(name="T", location=EntryLocation.path("/F"))
    for method in ("x", "y", "points", "size", "color_by_dimension", "color_by_measure"):
        assert hasattr(builder, method), f"scatter missing method: {method}"
    assert not hasattr(builder, "colors")


def test_flat_table_has_columns_but_not_x_or_y2() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.flat_table(name="T", location=EntryLocation.path("/F"))
    assert hasattr(builder, "columns")
    assert not hasattr(builder, "y2")


def test_pivot_has_columns_rows_y_but_not_x() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.pivot_table(name="T", location=EntryLocation.path("/F"))
    assert hasattr(builder, "columns")
    assert hasattr(builder, "rows")
    assert hasattr(builder, "y")
    assert not hasattr(builder, "x")


def test_metric_has_y_and_font_color_but_no_color_encoding_or_axes() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.indicator(name="T", location=EntryLocation.path("/F"))
    assert hasattr(builder, "y")
    assert hasattr(builder, "font_color")
    assert not hasattr(builder, "color_by_measure")
    assert not hasattr(builder, "palette")
    assert not hasattr(builder, "colors")
    assert not hasattr(builder, "x")
    assert not hasattr(builder, "y2")
    assert not hasattr(builder, "columns")


def test_combined_has_x_and_add_layer_but_not_y() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.combined_chart(name="T", location=EntryLocation.path("/F"))
    assert hasattr(builder, "x")
    assert hasattr(builder, "add_layer")
    assert not hasattr(builder, "layer")
    assert not hasattr(builder, "y")


# ---------------------------------------------------------------------------
# G3b: capacity spec — formalise the contract (no hard-error, tracks state)
# ---------------------------------------------------------------------------

_CAPACITY_ONE_VIZZES = [
    ("metric", "y"),
    ("pie", "y"),
    ("donut", "y"),
    ("funnel", "x"),
    ("pie", "x"),
    ("donut", "x"),
]


@pytest.mark.parametrize(("viz_id", "ph_name"), _CAPACITY_ONE_VIZZES)
def test_capacity_one_placeholder_accepts_single_field(viz_id: str, ph_name: str) -> None:
    spec = get_viz_spec(viz_id)
    actual_ph_id_map = {
        "x": "dimensions",
        "y": "measures",
    }
    actual_ph_id = actual_ph_id_map.get(ph_name, ph_name)
    ph_spec = cast(dict[str, object], spec.get("placeholders", {})).get(actual_ph_id)
    if ph_spec is None:
        pytest.skip(f"{viz_id} has no placeholder '{actual_ph_id}' in spec")
    assert cast(dict[str, object], ph_spec).get("capacity") == 1, f"Expected capacity=1 for {viz_id}.{actual_ph_id}"


# ---------------------------------------------------------------------------
# G3c: converter builds correct number of placeholder items (not limited in converter)
# ---------------------------------------------------------------------------


def test_metric_single_measure_builds_correctly() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.indicator(name="I", location=EntryLocation.path("/F")).dataset(dataset).y(["Meas1"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    viz = cast(dict[str, Any], data["visualization"])
    y_ph = next((p for p in viz["placeholders"] if p["id"] == "measures"), None)
    assert y_ph is not None, "metric payload must have 'measures' placeholder"
    assert len(cast(list[Any], y_ph["items"])) == 1


def test_pie_single_dim_and_measure_builds_correctly() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.pie(name="P", location=EntryLocation.path("/F")).dataset(dataset).x(["Dim1"]).y(["Meas1"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    viz = cast(dict[str, Any], data["visualization"])
    phs = {p["id"]: p for p in viz["placeholders"]}
    assert "dimensions" in phs
    assert "measures" in phs
    assert len(cast(list[Any], phs["dimensions"]["items"])) == 1
    assert len(cast(list[Any], phs["measures"]["items"])) == 1


def test_line_multiple_measures_on_y_accepted_no_exception() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.line(name="L", location=EntryLocation.path("/F")).dataset(dataset).x(["Dim1"]).y(["Meas1", "Meas2"])
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    viz = cast(dict[str, Any], data["visualization"])
    y_ph = next((p for p in viz["placeholders"] if p["id"] == "y"), None)
    assert y_ph is not None
    assert len(cast(list[Any], y_ph["items"])) == 2


# ---------------------------------------------------------------------------
# G3d: all viz in VIZ_SPECS have a factory method
# ---------------------------------------------------------------------------


def test_all_viz_specs_have_factory_method() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    missing = []
    for viz_id in VIZ_SPECS:
        if not hasattr(factory, factory_method_name(viz_id)):
            missing.append(viz_id)
    assert not missing, f"WizardChartCreateFactory missing methods for viz: {missing}"
