from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._runtime.wizard_semantics import WIZARD_VISUALIZATION_SEMANTICS
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.wizard_chart import resolve_field_snapshot
from datalens_sdk.errors import DataLensValidationError


def _dataset() -> Dataset:
    return Dataset(
        id="ds1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_date", "title": "Order Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "g_reg", "title": "Region", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
            {"guid": "g_cnt", "title": "Count", "type": "MEASURE", "data_type": "integer", "calc_mode": "direct"},
        ),
    )


def _fields(dataset: Dataset) -> list[DatasetField]:
    return list(dataset.fields)


def test_resolve_by_guid() -> None:
    dataset = _dataset()
    snap = resolve_field_snapshot("g_amt", fields=_fields(dataset))
    assert snap["guid"] == "g_amt"
    assert snap["title"] == "Amount"


def test_resolve_by_title() -> None:
    dataset = _dataset()
    snap = resolve_field_snapshot("Order Date", fields=_fields(dataset))
    assert snap["guid"] == "g_date"


def test_resolve_fuzzy_error_suggests_close_match() -> None:
    dataset = _dataset()
    with pytest.raises(DataLensValidationError, match="Did you mean: Amount"):
        resolve_field_snapshot("Amout", fields=_fields(dataset))


def test_resolve_without_dataset_raises() -> None:
    with pytest.raises(DataLensValidationError, match="no dataset schema is available"):
        resolve_field_snapshot("g_x", fields=[])


def test_resolve_from_local_field_map() -> None:
    local = {"lf_1": {"guid": "lf_1", "title": "Ratio", "type": "MEASURE"}}
    snap = resolve_field_snapshot("lf_1", fields=[], local_fields=local)
    assert snap["title"] == "Ratio"


def test_merge_chart_defaults_fills_all_collections() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.line(name="L", location=EntryLocation.path("/F"))
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data["sources"] == {"datasetsIds": []}
    assert set(data["visualization"]) == {"type", *WIZARD_VISUALIZATION_SEMANTICS["line"]["slots"]}


def test_wire_type_mapping_per_viz() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    assert factory.line(name="a", location=EntryLocation.path("/b")).to_spec().visualization_type == "line"
    assert factory.funnel(name="a", location=EntryLocation.path("/b")).to_spec().visualization_type == "funnel"
    assert factory.pivot_table(name="a", location=EntryLocation.path("/b")).to_spec().visualization_type == "pivotTable"
    assert factory.indicator(name="a", location=EntryLocation.path("/b")).to_spec().visualization_type == "metric"
    assert factory.geolayer(name="a", location=EntryLocation.path("/b")).to_spec().visualization_type == "geolayer"


def test_funnel_specific_settings_land_in_extra_settings() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.funnel(name="F", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Region"])
        .y(["Amount"])
        .shape(value="rectangle")
        .tooltip_percentage_base(mode="previous")
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data["visualization"]["chartSettings"] == {
        "shape": "rectangle",
        "tooltipPercentageBase": "previous",
    }


def test_bar_autofix_injects_desc_sort_and_measure_labels() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.bar(name="B", location=EntryLocation.path("/F")).dataset(dataset).x(["Amount"]).y(["Region"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data["visualization"]["sort"]["items"] == [{"guid": "g_reg", "datasetId": "ds1", "direction": "DESC"}]
    assert data["visualization"]["labels"]["items"] == [{"guid": "g_amt", "datasetId": "ds1"}]


def test_multi_measure_pseudo_for_line() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.line(name="L", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Order Date"])
        .y(["Amount", "Count"])
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    colors = data["visualization"]["colors"]["items"]
    assert any(c.get("type") == "PSEUDO" for c in colors), "multi-measure line must inject PSEUDO Measure Names"


def test_multi_measure_pseudo_for_column_uses_colors_slot() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.column(name="C", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Region"])
        .y(["Amount", "Count"])
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    viz = data["visualization"]
    assert any(it.get("type") == "PSEUDO" for it in viz["colors"]["items"])
    assert all(it.get("type") != "PSEUDO" for it in viz["x"]["items"])


def test_fill_missing_named_slots_adds_empty_semantic_slots() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.line(name="L", location=EntryLocation.path("/F")).dataset(dataset).x(["Order Date"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    visualization = data["visualization"]
    assert set(visualization) == {"type", *WIZARD_VISUALIZATION_SEMANTICS["line"]["slots"]}
    assert visualization["y"]["items"] == []
    assert visualization["y2"]["items"] == []


def test_axis_mode_map_continuous_for_date_dimension() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.line(name="L", location=EntryLocation.path("/F")).dataset(dataset).x(["Order Date"]).y(["Amount"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data["visualization"]["x"]["settings"]["axisModeMap"].get("g_date") == "continuous"


def test_pie_dimension_color_uses_explicit_semantic_method() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.pie(name="P", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Region"])
        .y(["Amount"])
        .color_by_dimension("Region")
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data["visualization"]["colors"]["items"][0]["guid"] == "g_reg"


def test_explicit_labels_position_column_inside() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.column(name="C", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Region"])
        .y(["Amount", "Count"])
    )
    builder.labels(["Amount"]).labels_position(mode="inside")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data["visualization"]["labels"]["settings"]["labelsPosition"] == "inside"


def test_labels_column_without_position_has_no_position_carrier() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.column(name="C", location=EntryLocation.path("/F")).dataset(dataset).x(["Region"]).y(["Amount"])
    builder.labels(["Amount"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert "labelsPosition" not in data["visualization"]["labels"].get("settings", {})


def test_bar_100p_does_not_expose_labels_position() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.bar_100p(name="B", location=EntryLocation.path("/F")).dataset(dataset).x(["Amount"]).y(["Region"])
    assert not hasattr(builder, "labels_position")


def test_dataset_parameters_injected_to_updates() -> None:
    dataset = Dataset(
        id="ds1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "p_thr", "title": "Threshold", "calc_mode": "parameter", "data_type": "float"},
        ),
    )
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.indicator(name="I", location=EntryLocation.path("/F")).dataset(dataset).y(["Amount"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    param_updates = [u for u in data["sources"]["updates"] if u.get("action") == "update_field"]
    assert any(u["field"]["guid"] == "p_thr" for u in param_updates)
