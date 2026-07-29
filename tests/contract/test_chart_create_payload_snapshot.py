from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._runtime.viz_specs import VIZ_SPECS, factory_method_name
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DatalensConfigurationError

_FIXED_DATASET = Dataset(
    id="ds-snap",
    name="snapshot",
    location=EntryLocation.path("/"),
    result_schema=(
        {"guid": "g_date", "title": "Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
        {"guid": "g_dim1", "title": "Category", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
        {
            "guid": "g_meas1",
            "title": "Revenue",
            "type": "MEASURE",
            "data_type": "float",
            "calc_mode": "direct",
            "aggregation": "sum",
        },
        {
            "guid": "g_meas2",
            "title": "Count",
            "type": "MEASURE",
            "data_type": "integer",
            "calc_mode": "direct",
            "aggregation": "count",
        },
    ),
)

_REQUIRED_DATA_KEYS = frozenset(
    {
        "visualization",
        "type",
        "version",
        "colors",
        "colorsConfig",
        "filters",
        "labels",
        "sort",
        "tooltips",
        "updates",
    }
)

_VIZ_BUILDER_SETUP: dict[str, dict[str, list[str]]] = {
    "line": {"x": ["g_date"], "y": ["g_meas1"]},
    "area": {"x": ["g_date"], "y": ["g_meas1"]},
    "area100p": {"x": ["g_date"], "y": ["g_meas1"]},
    "column": {"x": ["g_dim1"], "y": ["g_meas1"]},
    "column100p": {"x": ["g_dim1"], "y": ["g_meas1"]},
    "bar": {"x": ["g_meas1"], "y": ["g_dim1"]},
    "bar100p": {"x": ["g_meas1"], "y": ["g_dim1"]},
    "pie": {"x": ["g_dim1"], "y": ["g_meas1"]},
    "donut": {"x": ["g_dim1"], "y": ["g_meas1"]},
    "funnel": {"x": ["g_dim1"], "y": ["g_meas1"]},
    "treemap": {"x": ["g_dim1"], "y": ["g_meas1"]},
    "scatter": {"x": ["g_meas1"], "y": ["g_meas2"], "points": ["g_dim1"]},
    "metric": {"y": ["g_meas1"]},
    "flatTable": {"columns": ["g_dim1", "g_meas1"]},
    "pivotTable": {"columns": ["g_dim1"], "rows": ["g_dim1"], "y": ["g_meas1"]},
}


def _build_data(viz_id: str) -> dict[str, Any]:
    method_name = factory_method_name(viz_id)
    placeholders = _VIZ_BUILDER_SETUP[viz_id]
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, method_name)(name="snapshot", location=EntryLocation.path("/snap"))
    builder.dataset(_FIXED_DATASET)
    for ph, fields in placeholders.items():
        getattr(builder, ph)(fields)
    payload = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload())
    return cast(dict[str, Any], payload["data"])


@pytest.mark.parametrize("viz_id", sorted(_VIZ_BUILDER_SETUP.keys()))
def test_create_data_has_all_required_top_level_keys(viz_id: str) -> None:
    data = _build_data(viz_id)
    missing = _REQUIRED_DATA_KEYS - set(data.keys())
    assert not missing, f"{viz_id}: missing top-level keys {sorted(missing)}"


@pytest.mark.parametrize("viz_id", sorted(_VIZ_BUILDER_SETUP.keys()))
def test_create_data_type_is_datalens(viz_id: str) -> None:
    data = _build_data(viz_id)
    assert data["type"] == "datalens", f"{viz_id}: data.type should be 'datalens'"


@pytest.mark.parametrize("viz_id", sorted(_VIZ_BUILDER_SETUP.keys()))
def test_create_data_has_correct_datasets_ids(viz_id: str) -> None:
    data = _build_data(viz_id)
    assert data.get("datasetsIds") == ["ds-snap"], f"{viz_id}: datasetsIds mismatch"


@pytest.mark.parametrize("viz_id", sorted(_VIZ_BUILDER_SETUP.keys()))
def test_create_data_visualization_id_matches_spec(viz_id: str) -> None:
    data = _build_data(viz_id)
    viz = cast(dict[str, Any], data["visualization"])
    spec_viz_id = cast(dict[str, Any], VIZ_SPECS[viz_id].get("viz", {})).get("id", viz_id)
    assert viz["id"] == spec_viz_id, (
        f"{viz_id}: visualization.id mismatch (got {viz['id']!r}, expected {spec_viz_id!r})"
    )


@pytest.mark.parametrize("viz_id", sorted(_VIZ_BUILDER_SETUP.keys()))
def test_create_data_datasets_partial_fields_populated(viz_id: str) -> None:
    data = _build_data(viz_id)
    partial = data.get("datasetsPartialFields")
    assert partial, f"{viz_id}: datasetsPartialFields should be non-empty when dataset is bound"
    first_group = cast(list[dict[str, Any]], partial[0])
    guids = [f["guid"] for f in first_group]
    assert "g_date" in guids or "g_dim1" in guids, f"{viz_id}: datasetsPartialFields missing expected guids"


def test_create_bar_has_auto_sort_desc() -> None:
    data = _build_data("bar")
    assert data.get("sort"), "bar auto-fix must set sort"
    sort_items = cast(list[dict[str, Any]], data["sort"])
    assert sort_items[0]["direction"] == "DESC"
    assert data.get("labels"), "bar auto-fix must set labels"


def test_create_pie_auto_colors_from_dimension() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.pie(name="T", location=EntryLocation.path("/F")).dataset(_FIXED_DATASET).x(["g_dim1"]).y(["g_meas1"])
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    assert data.get("colors"), "pie without explicit colors must auto-populate data.colors from x-dimension"
    colors = cast(list[dict[str, Any]], data["colors"])
    assert colors[0]["guid"] == "g_dim1"


def test_create_line_multi_measure_injects_pseudo() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.line(name="T", location=EntryLocation.path("/F"))
        .dataset(_FIXED_DATASET)
        .x(["g_date"])
        .y(["g_meas1", "g_meas2"])
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])
    colors = cast(list[dict[str, Any]], data.get("colors", []))
    assert any(c.get("type") == "PSEUDO" for c in colors), (
        "multi-measure line must inject PSEUDO Measure Names into data.colors"
    )


def test_create_line_x_date_gets_axis_mode_map_continuous() -> None:
    data = _build_data("line")
    viz = cast(dict[str, Any], data["visualization"])
    x_ph = next(p for p in cast(list[dict[str, Any]], viz["placeholders"]) if p["id"] == "x")
    axis_mode_map = cast(dict[str, Any], x_ph.get("settings", {})).get("axisModeMap", {})
    assert axis_mode_map.get("g_date") == "continuous", "date dimension on x-axis must have axisModeMap='continuous'"


# ---------------------------------------------------------------------------
# G5: update payload invariants (deep-merge semantics)
# ---------------------------------------------------------------------------


def _chart_for_update() -> WizardChart:
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-snap",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds-snap"],
                "type": "datalens",
                "version": "15",
                "colors": [],
                "colorsConfig": {},
                "filters": [{"guid": "f1"}, {"guid": "f2"}],
                "labels": [],
                "sort": [],
                "tooltips": [],
                "updates": [],
                "visualization": {
                    "id": "line",
                    "placeholders": [
                        {"id": "x", "items": [{"guid": "g_date", "datasetId": "ds-snap"}]},
                        {
                            "id": "y",
                            "items": [
                                {
                                    "guid": "g_meas1",
                                    "datasetId": "ds-snap",
                                    "title": "Revenue",
                                    "type": "MEASURE",
                                }
                            ],
                        },
                        {"id": "y2", "items": []},
                    ],
                },
            },
        },
        installation="yacloud",
    )


def test_update_payload_has_required_top_level_keys() -> None:
    chart = _chart_for_update()
    update = chart.update.y(["g_meas1"]).mode("save")
    dto = WizardChartConverter.from_domain_update(update)
    payload = cast(dict[str, Any], dto.to_payload())
    assert payload["entryId"] == "chart-snap"
    assert payload["mode"] == "save"
    assert payload["template"] == "datalens"
    data = cast(dict[str, Any], payload["data"])
    missing = _REQUIRED_DATA_KEYS - set(data.keys())
    assert not missing, f"update payload missing data keys: {sorted(missing)}"


def test_update_payload_deep_merge_preserves_untouched_data_fields() -> None:
    chart = _chart_for_update()
    update = chart.update.y(["g_meas1"])
    dto = WizardChartConverter.from_domain_update(update)
    payload = cast(dict[str, Any], dto.to_payload())
    data = cast(dict[str, Any], payload["data"])
    assert data.get("datasetsIds") == ["ds-snap"], "deep-merge must preserve datasetsIds"
    assert data.get("type") == "datalens", "deep-merge must preserve data.type"
    assert data.get("version") == "15", "deep-merge must preserve data.version"


def test_update_payload_delete_filter_removes_exactly_one() -> None:
    chart = _chart_for_update()
    update = chart.update.delete_filter("f1")
    dto = WizardChartConverter.from_domain_update(update)
    data = cast(dict[str, Any], dto.to_payload()["data"])
    filter_guids = [f["guid"] for f in cast(list[dict[str, Any]], data["filters"])]
    assert filter_guids == ["f2"], "delete_filter('f1') must remove only f1, keep f2"


def test_update_payload_replace_field_updates_all_placeholder_items() -> None:
    chart = _chart_for_update()
    replacement = DatasetField(
        guid="g_new_date",
        title="New date",
        name="New date",
        calc_mode="direct",
        data_type="date",
        type="DIMENSION",
        dataset_id="ds-snap",
    )
    update = chart.update.replace_field("g_date", replacement)
    dto = WizardChartConverter.from_domain_update(update)
    data = cast(dict[str, Any], dto.to_payload()["data"])
    viz = cast(dict[str, Any], data["visualization"])
    x_ph = next(p for p in cast(list[dict[str, Any]], viz["placeholders"]) if p["id"] == "x")
    x_items = cast(list[dict[str, Any]], x_ph["items"])
    assert x_items[0]["guid"] == "g_new_date", "replace_field must update guid in all placeholder items"


def test_update_payload_delete_field_removes_items() -> None:
    chart = _chart_for_update()
    update = chart.update.delete_field("g_meas1")
    dto = WizardChartConverter.from_domain_update(update)
    data = cast(dict[str, Any], dto.to_payload()["data"])
    viz = cast(dict[str, Any], data["visualization"])
    y_ph = next(p for p in cast(list[dict[str, Any]], viz["placeholders"]) if p["id"] == "y")
    y_items = cast(list[dict[str, Any]], y_ph["items"])
    assert y_items == [], "delete_field('g_meas1') must clear y-placeholder items"


def test_update_payload_replace_dataset_updates_datasets_ids_and_items() -> None:
    chart = _chart_for_update()
    update = chart.update.replace_dataset(old="ds-snap", new="ds-new")
    dto = WizardChartConverter.from_domain_update(update)
    data = cast(dict[str, Any], dto.to_payload()["data"])
    assert data["datasetsIds"] == ["ds-new"], "replace_dataset must update datasetsIds"
    viz = cast(dict[str, Any], data["visualization"])
    x_ph = next(p for p in cast(list[dict[str, Any]], viz["placeholders"]) if p["id"] == "x")
    x_items = cast(list[dict[str, Any]], x_ph["items"])
    assert x_items[0]["datasetId"] == "ds-new", "replace_dataset must update datasetId in placeholder items"


def test_update_placeholder_edit_sets_new_items_by_guid() -> None:
    chart = _chart_for_update()
    update = chart.update.y(["g_meas1"])
    dto = WizardChartConverter.from_domain_update(update)
    data = cast(dict[str, Any], dto.to_payload()["data"])
    viz = cast(dict[str, Any], data["visualization"])
    y_ph = next(p for p in cast(list[dict[str, Any]], viz["placeholders"]) if p["id"] == "y")
    y_items = cast(list[dict[str, Any]], y_ph["items"])
    assert y_items[0]["guid"] == "g_meas1", "y() setter must set new items in y-placeholder"


def test_update_applies_mutations_to_loaded_chart_data() -> None:
    chart = _chart_for_update()
    update = (
        chart.update.chart_title(text="Updated")
        .axis_scale("y", mode="manual", min="0", max="10")
        .add_filter("g_date", operation="EQ", values=("2026-01-01",))
        .measure_format("g_meas1", format="percent", precision=1)
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert data["extraSettings"]["title"] == "Updated"
    assert data["filters"][-1]["filter"]["operation"]["code"] == "EQ"
    viz = cast(dict[str, Any], data["visualization"])
    y_ph = next(p for p in cast(list[dict[str, Any]], viz["placeholders"]) if p["id"] == "y")
    assert y_ph["settings"]["scaleValue"] == ["0", "10"]
    assert y_ph["items"][0]["formatting"] == {"format": "percent", "precision": 1}


def test_update_replaces_chart_local_formula() -> None:
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    chart.data["updates"] = [
        {"action": "add_field", "field": {"guid": "local-field", "formula": "[Revenue]", "local": True}}
    ]
    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(
            chart.update.replace_formula("local-field", formula="[Revenue] * 2")
        ).to_payload()["data"],
    )
    assert data["updates"][0]["field"]["formula"] == "[Revenue] * 2"


def test_update_publish_without_changes_allows_loaded_saved_draft() -> None:
    chart = _chart_for_update()
    chart.raw = {"publishedId": "published", "savedId": "draft", "revId": "draft"}

    payload = WizardChartConverter.from_domain_update(chart.update.mode("publish")).to_payload()

    assert payload["mode"] == "publish"


def test_update_publish_without_changes_rejects_loaded_published_revision_with_newer_draft() -> None:
    chart = _chart_for_update()
    chart.raw = {"publishedId": "published", "savedId": "draft", "revId": "published"}

    with pytest.raises(DatalensConfigurationError, match="newer saved draft"):
        WizardChartConverter.from_domain_update(chart.update.mode("publish"))


def test_update_preserves_nested_navigator_settings() -> None:
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    chart.data["extraSettings"] = {"navigatorSettings": {"navigatorMode": "hide", "range": "all"}}

    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(chart.update.navigator(mode="show")).to_payload()["data"],
    )

    assert data["extraSettings"]["navigatorSettings"] == {"navigatorMode": "show", "range": "all"}


def _set_chart_visualization(chart: WizardChart, visualization_id: str) -> None:
    """Override ``data.visualization.id`` in place (wire-id source of truth)."""
    cast(dict[str, Any], chart.data["visualization"])["id"] = visualization_id


@pytest.mark.parametrize(
    ("method_name", "kwargs", "message"),
    [
        ("column_background", {"palette": "classic20"}, "gradient palette"),
        ("column_background", {"mode": "2-point", "thresholds": (1.0, 2.0, 3.0)}, "exactly 2 thresholds"),
        (
            "column_bars",
            {"color_type": "gradient", "gradient_palette": "classic20"},
            "not supported for gradient bars",
        ),
        ("color_by_measure", {"palette": "classic20"}, "gradient palette"),
    ],
)
def test_update_table_mutations_match_create_validation(method_name: str, kwargs: dict[str, Any], message: str) -> None:
    chart = _chart_for_update()
    _set_chart_visualization(chart, "flatTable")

    with pytest.raises(DatalensConfigurationError, match=message):
        getattr(chart.update, method_name)("g_meas1", **kwargs)


def test_update_rejects_non_applicable_data_field_and_placeholder_mutations() -> None:
    chart = _chart_for_update()
    _set_chart_visualization(chart, "scatter")
    with pytest.raises(DatalensConfigurationError, match="segments"):
        chart.update.segments(["g_date"])

    _set_chart_visualization(chart, "flatTable")
    with pytest.raises(DatalensConfigurationError, match="shape_by_measure_name"):
        chart.update.shape_by_measure_name()


def test_update_funnel_specific_settings_land_in_extra_settings() -> None:
    chart = _chart_for_update()
    _set_chart_visualization(chart, "funnel")

    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(
            chart.update.shape(value="auto").tooltip_percentage_base(mode="first")
        ).to_payload()["data"],
    )

    assert data["extraSettings"]["shape"] == "auto"
    assert data["extraSettings"]["tooltipPercentageBase"] == "first"


@pytest.mark.parametrize("visualization_id", ["flatTable", "pivotTable"])
def test_update_freeze_columns_lands_in_extra_settings(visualization_id: str) -> None:
    chart = _chart_for_update()
    _set_chart_visualization(chart, visualization_id)

    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(chart.update.freeze_columns(count=2)).to_payload()["data"],
    )

    assert data["extraSettings"]["pinnedColumns"] == 2


def test_unrelated_update_does_not_mutate_colors_config() -> None:
    chart = _chart_for_update()
    visualization = cast(dict[str, Any], chart.data["visualization"])
    visualization["placeholders"].append(
        {"id": "colors", "items": [{"guid": "g_date", "type": "DIMENSION", "datasetId": "ds-snap"}]}
    )

    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(chart.update.chart_title(text="Updated")).to_payload()["data"],
    )

    assert data["colorsConfig"] == {}


def test_update_color_by_measure_name_uses_changed_visualization_spec() -> None:
    chart = _chart_for_update()
    visualization = cast(dict[str, Any], chart.data["visualization"])
    y_placeholder = next(
        placeholder
        for placeholder in cast(list[dict[str, Any]], visualization["placeholders"])
        if placeholder["id"] == "y"
    )
    cast(list[dict[str, Any]], y_placeholder["items"]).append(
        {
            "guid": "g_meas2",
            "datasetId": "ds-snap",
            "title": "Count",
            "type": "MEASURE",
        }
    )

    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(
            chart.update.change_visualization_to(visualization_id="column").color_by_measure_name()
        ).to_payload()["data"],
    )

    assert data["visualization"]["id"] == "column"
    assert data["colorsConfig"]["coloredByMeasure"] is True
    assert "fieldGuid" not in data["colorsConfig"]
    assert data["colors"][0]["type"] == "PSEUDO"
