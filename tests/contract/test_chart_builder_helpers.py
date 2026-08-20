from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast, get_type_hints

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.chart_types import MeasureFormat, PaletteId
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.fields import DatasetField, WizardAggregatedMeasure, WizardHierarchy, WizardLocalField
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_REFERENCE_CHARTS_DIR = Path(__file__).parent / "fixtures" / "reference_charts" / "wizard"


def _reference_chart(chart_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REFERENCE_CHARTS_DIR / f"{chart_id}.json").read_text()))


def _loc() -> EntryLocation:
    return EntryLocation.path("/Reports")


def _dataset(*guids: str) -> Dataset:
    schema = []
    for i, guid in enumerate(guids):
        is_measure = i % 2 == 1
        schema.append(
            {
                "guid": guid,
                "title": f"field_{guid}",
                "type": "MEASURE" if is_measure else "DIMENSION",
                "data_type": "float" if is_measure else "string",
                "calc_mode": "direct",
                "aggregation": "sum" if is_measure else "",
            }
        )
    return Dataset(
        id="ds1",
        name="ds",
        location=EntryLocation.path("/"),
        result_schema=tuple(schema),
    )


def _build(builder: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])


def _extra(builder: Any) -> dict[str, Any]:
    data = _build(builder)
    visualization = cast(dict[str, Any], data["visualization"])
    return cast(dict[str, Any], visualization.get("chartSettings", {}))


def _ph_settings(builder: Any, ph_id: str) -> dict[str, Any]:
    data = _build(builder)
    viz = cast(dict[str, Any], data["visualization"])
    slot = viz.get(ph_id)
    if not isinstance(slot, dict):
        return {}
    return cast(dict[str, Any], slot.get("settings", {}))


def _items_in_ph(data: dict[str, Any], ph_id: str) -> list[dict[str, Any]]:
    viz = cast(dict[str, Any], data["visualization"])
    slot_name = {
        "flat-table-columns": "columns",
        "pivot-table-columns": "columns",
    }.get(ph_id, ph_id)
    slot = viz.get(slot_name)
    if not isinstance(slot, dict):
        return []
    return cast(list[dict[str, Any]], slot.get("items", []))


def _slot_settings(data: dict[str, Any], slot_name: str) -> dict[str, Any]:
    visualization = cast(dict[str, Any], data["visualization"])
    slot = visualization.get(slot_name)
    if not isinstance(slot, dict):
        return {}
    return cast(dict[str, Any], slot.get("settings", {}))


def _source_items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    sources = cast(dict[str, Any], data["sources"])
    return cast(list[dict[str, Any]], sources.get(key, []))


_factory = WizardChartCreateFactory(cast(Any, None))


class TestChartTitleHelper:
    def test_chart_title_show_mode(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).chart_title(text="Sales Overview")
        extra = _extra(builder)
        assert extra["title"] == "Sales Overview"
        assert extra["titleMode"] == "show"

    def test_chart_title_hide_mode(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).chart_title(text="", mode="hide")
        extra = _extra(builder)
        assert extra["title"] == ""
        assert extra["titleMode"] == "hide"

    def test_chart_title_default_mode_is_show(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).chart_title(text="Hello")
        extra = _extra(builder)
        assert extra["titleMode"] == "show"


class TestNavigatorHelper:
    def test_navigator_show_writes_navigatorMode_show(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).navigator(mode="show")
        extra = _extra(builder)
        nav = cast(dict[str, Any], extra["navigatorSettings"])
        assert nav == {
            "linesMode": "all",
            "navigatorMode": "show",
            "periodSettings": {"period": "year", "type": "genericdatetime", "value": "1"},
            "selectedLines": [],
        }

    def test_navigator_hide_writes_navigatorMode_hide(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).navigator(mode="hide")
        extra = _extra(builder)
        nav = cast(dict[str, Any], extra["navigatorSettings"])
        assert nav == {
            "linesMode": "all",
            "navigatorMode": "hide",
            "periodSettings": {"period": "year", "type": "genericdatetime", "value": "1"},
            "selectedLines": [],
        }


class TestAxisTitleHelper:
    def test_axis_title_off_writes_title_off(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_title("x", mode="off")
        settings = _ph_settings(builder, "x")
        assert settings.get("title") == "off"
        assert settings.get("titleValue") == ""

    def test_axis_title_auto_writes_title_auto(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_title("y", mode="auto")
        settings = _ph_settings(builder, "y")
        assert settings.get("title") == "auto"

    def test_axis_title_manual_with_text_writes_both_keys(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_title("x", mode="manual", text="Period")
        settings = _ph_settings(builder, "x")
        assert settings.get("title") == "manual"
        assert settings.get("titleValue") == "Period"

    def test_axis_title_manual_without_text_does_not_override_titleValue(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_title("x", mode="manual")
        settings = _ph_settings(builder, "x")
        assert settings.get("title") == "manual"
        assert settings.get("titleValue") == ""


class TestAxisScaleHelper:
    def test_axis_scale_auto_writes_scale_auto(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_scale("y", mode="auto")
        settings = _ph_settings(builder, "y")
        assert settings.get("scale") == "auto"
        assert settings.get("type") == "linear"

    def test_axis_scale_linear_logarithmic(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_scale("y", scale="logarithmic", mode="auto")
        settings = _ph_settings(builder, "y")
        assert settings.get("type") == "logarithmic"
        assert settings.get("scale") == "auto"

    def test_axis_scale_manual_with_bounds_writes_scaleValue(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).axis_scale("y", mode="manual", min="0", max="100")
        settings = _ph_settings(builder, "y")
        assert settings.get("scale") == "manual"
        assert settings.get("scaleValue") == ["0", "100"]

    def test_axis_scale_manual_with_only_min_is_rejected(self) -> None:
        with pytest.raises(DataLensConfigurationError, match="requires both"):
            _factory.line(name="Chart", location=_loc()).axis_scale("y", mode="manual", min="0")

    def test_axis_scale_manual_without_bounds_raises_error(self) -> None:
        with pytest.raises(DataLensConfigurationError, match="requires both"):
            _factory.line(name="Chart", location=_loc()).axis_scale("y", mode="manual")


class TestGridHelper:
    def test_grid_enabled_writes_on(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).grid("x", enabled=True)
        settings = _ph_settings(builder, "x")
        assert settings.get("grid") == "on"

    def test_grid_disabled_writes_off(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).grid("x", enabled=False)
        settings = _ph_settings(builder, "x")
        assert settings.get("grid") == "off"

    def test_grid_with_step_writes_manual_gridStep_and_gridStepValue(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).grid("y", enabled=True, step=50)
        settings = _ph_settings(builder, "y")
        assert settings.get("grid") == "on"
        assert settings.get("gridStep") == "manual"
        assert settings.get("gridStepValue") == 50

    def test_grid_without_step_does_not_set_gridStep_to_manual(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).grid("y", enabled=True)
        settings = _ph_settings(builder, "y")
        assert settings.get("gridStep") != "manual"


class TestPaginationHelper:
    def test_pagination_enabled_writes_on(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).pagination(enabled=True)
        extra = _extra(builder)
        assert extra.get("pagination") == "on"

    def test_pagination_disabled_writes_off(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).pagination(enabled=False)
        extra = _extra(builder)
        assert extra.get("pagination") == "off"

    def test_pagination_enabled_with_limit_writes_limit(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).pagination(enabled=True, limit=50)
        extra = _extra(builder)
        assert extra.get("pagination") == "on"
        assert extra.get("limit") == 50

    def test_pagination_disabled_does_not_write_limit(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).pagination(enabled=False)
        extra = _extra(builder)
        assert extra.get("pagination") == "off"
        assert "limit" not in extra

    def test_pagination_enabled_default_limit_is_100(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).pagination(enabled=True)
        extra = _extra(builder)
        assert extra.get("limit") == 100


class TestColumnBackgroundMutatesItem:
    def test_column_background_writes_backgroundSettings_to_item_not_colors_placeholder(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_background("meas")
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        assert "backgroundSettings" in meas_item
        colors = _items_in_ph(data, "colors")
        assert not any(isinstance(c, dict) and c.get("guid") == "meas" for c in cast(list[Any], colors)), (
            "column_background must not write to colors list"
        )

    def test_column_background_default_3_point_with_default_palette(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_background("meas")
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bg = cast(dict[str, Any], meas_item.get("backgroundSettings", {}))
        assert bg.get("enabled") is True
        assert bg.get("colorFieldGuid") == "meas"
        settings = cast(dict[str, Any], bg.get("settings", {}))
        grad = cast(dict[str, Any], settings.get("gradientState", {}))
        assert grad.get("gradientMode") == "3-point"
        assert grad.get("gradientPalette") == "red-orange-green"
        assert grad.get("reversed") is False
        assert grad.get("thresholdsMode") == "auto"

    def test_column_background_2_point_with_manual_thresholds(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_background("meas", mode="2-point", palette="blue", thresholds=(0.0, 100.0), reversed=True)
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bg = cast(dict[str, Any], meas_item.get("backgroundSettings", {}))
        settings = cast(dict[str, Any], bg.get("settings", {}))
        grad = cast(dict[str, Any], settings.get("gradientState", {}))
        assert grad.get("gradientMode") == "2-point"
        assert grad.get("gradientPalette") == "blue"
        assert grad.get("reversed") is True
        assert grad.get("thresholdsMode") == "manual"
        assert grad.get("leftThreshold") == "0.0"
        assert grad.get("rightThreshold") == "100.0"

    def test_column_background_3_point_with_manual_thresholds(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_background("meas", mode="3-point", thresholds=(10.0, 50.0, 90.0))
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bg = cast(dict[str, Any], meas_item.get("backgroundSettings", {}))
        settings = cast(dict[str, Any], bg.get("settings", {}))
        grad = cast(dict[str, Any], settings.get("gradientState", {}))
        assert grad.get("thresholdsMode") == "manual"
        assert grad.get("leftThreshold") == "10.0"
        assert grad.get("middleThreshold") == "50.0"
        assert grad.get("rightThreshold") == "90.0"

    def test_pivot_background_and_format_serialize_manual_thresholds_for_create(self) -> None:
        ds = _dataset("dim", "meas")
        data = _build(
            _factory.pivot_table(name="Chart", location=_loc())
            .dataset(ds)
            .columns(["dim"])
            .measures(["meas"])
            .column_background("meas", mode="3-point", thresholds=(0.0, 0.1, 0.3))
            .measure_format("meas", format="percent", precision=1)
        )

        item = _items_in_ph(data, "measures")[0]
        background = cast(dict[str, Any], item["backgroundSettings"])
        settings = cast(dict[str, Any], background["settings"])
        gradient = cast(dict[str, Any], settings["gradientState"])
        assert gradient["leftThreshold"] == "0.0"
        assert gradient["middleThreshold"] == "0.1"
        assert gradient["rightThreshold"] == "0.3"
        assert item["formatting"] == {"format": "percent", "precision": 1}

    def test_pivot_background_and_format_serialize_manual_thresholds_for_update(self) -> None:
        ds = _dataset("dim", "meas")
        original = _build(
            _factory.pivot_table(name="Chart", location=_loc()).dataset(ds).columns(["dim"]).measures(["meas"])
        )
        chart = WizardChart(id="chart-1", installation="yacloud", data=original)
        measure = ds.fields.by_name("field_meas")

        data = cast(
            dict[str, Any],
            WizardChartConverter.from_domain_update(
                chart.update.column_background(
                    measure,
                    mode="3-point",
                    thresholds=(0.0, 0.1, 0.3),
                ).measure_format(measure, format="percent", precision=1)
            ).to_payload()["data"],
        )

        item = _items_in_ph(data, "measures")[0]
        background = cast(dict[str, Any], item["backgroundSettings"])
        settings = cast(dict[str, Any], background["settings"])
        gradient = cast(dict[str, Any], settings["gradientState"])
        assert gradient["leftThreshold"] == "0.0"
        assert gradient["middleThreshold"] == "0.1"
        assert gradient["rightThreshold"] == "0.3"
        assert item["formatting"] == {"format": "percent", "precision": 1}

    def test_column_background_wrong_threshold_count_raises(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        with pytest.raises(DataLensConfigurationError, match="exactly 2 thresholds"):
            builder.column_background("meas", mode="2-point", thresholds=(1.0, 2.0, 3.0))

    def test_column_background_invalid_palette_raises(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        with pytest.raises(DataLensConfigurationError, match="gradient palette"):
            builder.column_background("meas", palette="classic20")  # type: ignore[arg-type]

    def test_column_background_works_on_pivot(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.pivot_table(name="Chart", location=_loc()).dataset(ds).columns(["dim"]).measures(["meas"])
        builder.column_background("meas", mode="2-point", palette="yellow")
        data = _build(builder)
        items = _items_in_ph(data, "measures")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bg = cast(dict[str, Any], meas_item.get("backgroundSettings", {}))
        settings = cast(dict[str, Any], bg.get("settings", {}))
        grad = cast(dict[str, Any], settings.get("gradientState", {}))
        assert grad.get("gradientMode") == "2-point"
        assert grad.get("gradientPalette") == "yellow"

    def test_live_background_fixture_links_color_field_guid(self) -> None:
        fixture = _reference_chart("lz47d8gnsa4q5")
        placeholders = cast(list[dict[str, Any]], fixture["data"]["visualization"]["placeholders"])
        background = next(
            item["backgroundSettings"]
            for placeholder in placeholders
            for item in cast(list[dict[str, Any]], placeholder.get("items", []))
            if "backgroundSettings" in item
        )
        assert set(background) == {"colorFieldGuid", "enabled", "settings", "settingsId"}


class TestColumnBarsHelper:
    def test_live_one_color_bars_fixture_has_nested_color_settings_and_scale(self) -> None:
        fixture = _reference_chart("guz2i7a315cg0")
        placeholders = cast(list[dict[str, Any]], fixture["data"]["visualization"]["placeholders"])
        bars = next(
            item["barsSettings"]
            for placeholder in placeholders
            for item in cast(list[dict[str, Any]], placeholder.get("items", []))
            if "barsSettings" in item and item["barsSettings"]["colorSettings"]["colorType"] == "one-color"
        )
        assert bars["colorSettings"] == {"colorType": "one-color", "settings": {"color": "#D3D3D3"}}
        assert bars["scale"] == {"mode": "auto"}

    def test_live_two_color_bars_fixture_has_nested_palette_indexes_and_scale(self) -> None:
        fixture = _reference_chart("lz47d8gnsa4q5")
        placeholders = cast(list[dict[str, Any]], fixture["data"]["visualization"]["placeholders"])
        bars = next(
            item["barsSettings"]
            for placeholder in placeholders
            for item in cast(list[dict[str, Any]], placeholder.get("items", []))
            if "barsSettings" in item and item["barsSettings"]["colorSettings"]["colorType"] == "two-color"
        )
        assert bars["colorSettings"] == {
            "colorType": "two-color",
            "settings": {"positiveColorIndex": 2, "negativeColorIndex": 1},
        }
        assert bars["scale"] == {"mode": "auto"}
        assert bars["showBarsInTotals"] is False

    def test_live_gradient_bars_fixture_has_nested_color_settings_and_scale(self) -> None:
        fixture = _reference_chart("lz47d8gnsa4q5")
        placeholders = cast(list[dict[str, Any]], fixture["data"]["visualization"]["placeholders"])
        bars = next(
            item["barsSettings"]
            for placeholder in placeholders
            for item in cast(list[dict[str, Any]], placeholder.get("items", []))
            if "barsSettings" in item and item["barsSettings"]["colorSettings"]["colorType"] == "gradient"
        )
        assert set(bars) == {"align", "colorSettings", "enabled", "scale", "showBarsInTotals", "showLabels"}
        assert bars["scale"] == {"mode": "auto"}

    def test_column_bars_enabled_writes_barsSettings_to_item(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars("meas", enabled=True)
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars.get("enabled") is True
        assert bars.get("showLabels") is True
        assert bars.get("showBarsInTotals") is False
        assert bars.get("scale") == {"mode": "auto"}
        assert bars.get("align") == "default"
        assert "showInTotals" not in bars

    def test_column_bars_default_enabled_is_true(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars("meas")
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars.get("enabled") is True

    def test_column_bars_one_color(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars("meas", color_type="one-color", color="#FF0000")
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars.get("colorSettings") == {"colorType": "one-color", "settings": {"color": "#FF0000"}}

    def test_column_bars_two_color_with_indexes(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars(
            "meas",
            color_type="two-color",
            positive_color_index=2,
            negative_color_index=1,
        )
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars.get("colorSettings") == {
            "colorType": "two-color",
            "settings": {"positiveColorIndex": 2, "negativeColorIndex": 1},
        }

    def test_column_bars_two_color_with_hex(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars(
            "meas",
            color_type="two-color",
            color_positive="#4DA2F1",
            color_negative="#FF3D64",
        )
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        color_settings = cast(dict[str, Any], bars.get("colorSettings", {}))
        assert color_settings.get("colorType") == "two-color"
        inner = cast(dict[str, Any], color_settings.get("settings", {}))
        assert inner.get("positiveColor") == "#4DA2F1"
        assert inner.get("negativeColor") == "#FF3D64"

    def test_column_bars_gradient(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars("meas", color_type="gradient", gradient_palette="blue", reversed=True)
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars.get("colorSettings") == {
            "colorType": "gradient",
            "settings": {
                "gradientType": "2-point",
                "thresholds": {"mode": "auto"},
                "palette": "blue",
                "reversed": True,
            },
        }

    def test_column_bars_gradient_wrong_type_raises(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        with pytest.raises(DataLensConfigurationError, match="does not support gradient_type"):
            builder.column_bars("meas", color_type="gradient", gradient_palette="blue", gradient_type="3-point")

    def test_column_bars_incompatible_params_raise(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        with pytest.raises(DataLensConfigurationError, match="does not accept"):
            builder.column_bars("meas", color_type="one-color", color_positive="#FF0000")

    def test_column_bars_one_color_no_color_arg_produces_empty_one_color_settings(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars("meas", color_type="one-color")
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars["colorSettings"] == {"colorType": "one-color", "settings": {}}

    def test_column_bars_show_labels_and_align(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.column_bars("meas", enabled=True, show_labels=False, show_in_totals=True, align="right")
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        bars = cast(dict[str, Any], meas_item.get("barsSettings", {}))
        assert bars.get("showLabels") is False
        assert bars.get("showBarsInTotals") is True
        assert bars.get("align") == "right"


class TestSubtotalsHelper:
    def test_subtotals_enabled_writes_subTotalsSettings_to_pivot_item(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.pivot_table(name="Chart", location=_loc()).dataset(ds).columns(["dim"]).measures(["meas"])
        builder.subtotals("dim", enabled=True)
        data = _build(builder)
        items = _items_in_ph(data, "pivot-table-columns")
        dim_item = next(it for it in items if it.get("guid") == "dim")
        subtotals = cast(dict[str, Any], dim_item.get("subTotalsSettings", {}))
        assert subtotals.get("enabled") is True

    def test_subtotals_uses_capital_T_wire_key(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.pivot_table(name="Chart", location=_loc()).dataset(ds).columns(["dim"]).measures(["meas"])
        builder.subtotals("dim", enabled=False)
        data = _build(builder)
        items = _items_in_ph(data, "pivot-table-columns")
        dim_item = next(it for it in items if it.get("guid") == "dim")
        assert "subTotalsSettings" in dim_item
        assert "subtotalsSettings" not in dim_item


class TestMutateItemByGuidErrors:
    def test_column_background_without_columns_raises_configuration_error(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc())
        with pytest.raises(DataLensConfigurationError, match="not found in any slot"):
            builder.column_background("nonexistent")

    def test_column_bars_without_columns_raises_configuration_error(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc())
        with pytest.raises(DataLensConfigurationError, match="not found in any slot"):
            builder.column_bars("nonexistent", enabled=True)

    def test_subtotals_without_columns_raises_configuration_error(self) -> None:
        builder = _factory.pivot_table(name="Chart", location=_loc())
        with pytest.raises(DataLensConfigurationError, match="not found in any slot"):
            builder.subtotals("nonexistent", enabled=True)

    def test_column_title_without_placed_field_raises_configuration_error(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc())
        with pytest.raises(DataLensConfigurationError, match="not found in any slot"):
            builder.column_title("nonexistent", title="Revenue")

    def test_measure_format_without_placed_field_raises_configuration_error(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).measure_format("nonexistent", format="number")
        with pytest.raises(DataLensValidationError, match="no dataset schema is available"):
            _build(builder)


class TestPaletteHelper:
    def test_valid_discrete_palette_writes_palette_to_colors_config(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_dimension("dim")
        )
        builder.palette(id="classic20")
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg.get("palette") == "classic20"
        assert "paletteId" not in cfg

    def test_valid_gradient_palette_writes_gradient_palette_to_colors_config(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.treemap(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_measure("meas")
        )
        builder.palette(id="blue")
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg.get("palette") == "blue"
        assert cfg.get("gradientPalette") == "blue"
        assert "gradientMode" in cfg

    def test_discrete_palette_rejects_measure_colors(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_measure("meas")
        )
        builder.palette(id="classic20")
        with pytest.raises(DataLensConfigurationError, match="requires a DIMENSION"):
            _build(builder)

    def test_gradient_palette_rejects_dimension_colors(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_dimension("dim")
        )
        builder.palette(id="blue")
        with pytest.raises(DataLensConfigurationError, match="requires a MEASURE"):
            _build(builder)

    def test_last_color_call_wins_before_palette_validation(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .color_by_dimension("dim")
            .color_by_measure("meas")
            .palette(id="blue")
        )
        data = _build(builder)
        assert _items_in_ph(data, "colors")[0]["guid"] == "meas"

    def test_palette_rejects_missing_colors(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).palette(id="classic20")
        with pytest.raises(DataLensConfigurationError, match="requires a field in the colors slot"):
            _build(builder)

    def test_update_palette_validates_existing_colors(self) -> None:
        ds = _dataset("dim", "meas")
        chart = WizardChart(
            id="chart-1",
            installation="yacloud",
            data=_build(
                _factory.line(name="Chart", location=_loc())
                .dataset(ds)
                .x(["dim"])
                .y(["meas"])
                .color_by_dimension("dim")
            ),
        )
        with pytest.raises(DataLensConfigurationError, match="requires a MEASURE"):
            WizardChartConverter.from_domain_update(chart.update.palette(id="blue"))

    def test_update_gradient_palette_writes_gradient_config_for_measure_colors(self) -> None:
        ds = _dataset("dim", "meas")
        chart = WizardChart(
            id="chart-1",
            installation="yacloud",
            data=_build(
                _factory.treemap(name="Chart", location=_loc())
                .dataset(ds)
                .x(["dim"])
                .y(["meas"])
                .color_by_measure("meas")
            ),
        )
        payload = WizardChartConverter.from_domain_update(chart.update.palette(id="blue")).to_payload()
        data = cast(dict[str, Any], payload["data"])
        cfg = _slot_settings(data, "colors")
        assert cfg["palette"] == "blue"
        assert cfg["gradientPalette"] == "blue"

    def test_dimension_colors_get_default_categorical_palette(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.pie(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_dimension("dim")
        )
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg.get("palette") == "datalens-classic-20"
        assert _items_in_ph(data, "colors")[0]["guid"] == "dim"

    def test_unknown_palette_raises_configuration_error(self) -> None:
        with pytest.raises(DataLensConfigurationError, match="Unknown palette"):
            _factory.line(name="Chart", location=_loc()).palette(id=cast(PaletteId, "nonexistent-palette-xyz"))


class TestSemanticColorRouting:
    @pytest.mark.parametrize("viz_method", ["line", "area", "column", "bar"])
    def test_dimension_color_routes_to_top_level_without_placeholder_leak(self, viz_method: str) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            getattr(_factory, viz_method)(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .color_by_dimension("dim")
        )
        data = _build(builder)
        top_level_colors = _items_in_ph(data, "colors")
        assert any(c.get("guid") == "dim" for c in top_level_colors)
        cfg = _slot_settings(data, "colors")
        assert cfg.get("palette") == "datalens-classic-20"
        assert "colors" in data["visualization"], f"{viz_method} must expose the named colors slot"

    def test_treemap_dimension_color_accepts_an_independent_dimension(self) -> None:
        ds = _dataset("dim", "meas", "other_dim")
        builder = (
            _factory.treemap(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .color_by_dimension("other_dim")
        )
        assert _items_in_ph(_build(builder), "colors")[0]["guid"] == "other_dim"

    def test_color_by_dimension_rejects_measure(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_dimension("meas")
        )
        with pytest.raises(DataLensConfigurationError, match="requires a DIMENSION"):
            _build(builder)

    def test_treemap_dimension_color_writes_placeholder_and_data(self) -> None:
        ds = _dataset("dim", "meas")
        data = _build(
            _factory.treemap(name="Chart", location=_loc()).dataset(ds).color_by_dimension("dim").y(["meas"]).x(["dim"])
        )
        assert _items_in_ph(data, "colors")[0]["guid"] == "dim"
        assert _items_in_ph(data, "colors")[0]["guid"] == "dim"

    @pytest.mark.parametrize("viz_method", ["pie", "donut"])
    def test_pie_family_explicit_dimension_color_keeps_dedicated_placeholder(self, viz_method: str) -> None:
        ds = _dataset("dim", "meas", "other_dim")
        builder = (
            getattr(_factory, viz_method)(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .color_by_dimension("other_dim")
        )
        data = _build(builder)
        assert _items_in_ph(data, "colors")[0]["guid"] == "other_dim"
        assert _slot_settings(data, "colors")["palette"] == "datalens-classic-20"

    @pytest.mark.parametrize("viz_method", ["pie", "donut"])
    def test_pie_family_implicit_color_uses_dimension_autofix(self, viz_method: str) -> None:
        ds = _dataset("dim", "meas")
        builder = getattr(_factory, viz_method)(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"])
        data = _build(builder)
        assert _items_in_ph(data, "colors") == [{"guid": "dim", "datasetId": "ds1"}]
        assert _slot_settings(data, "colors") == {}


class TestColorByMeasureNameHelper:
    def test_live_rgba_override_fixture_is_preserved_in_mounted_colors(self) -> None:
        fixture = _reference_chart("n1zb75lpkoq27")
        mounted_colors = fixture["data"]["colorsConfig"]["mountedColors"]
        assert "#4DA256FF" in mounted_colors.values()

    def test_multi_measure_colors_write_palette_configuration_and_pseudo_fields(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .color_by_measure_name(colors_map={"measure_2": "#001122"})
            .palette(id="classic20")
        )
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg["palette"] == "classic20"
        assert cfg["coloredByMeasure"] is True
        assert cfg["colorMode"] == "palette"
        assert cfg["polygonBorders"] == "show"
        assert cfg["mountedColors"] == {"measure_1": "0", "measure_2": "#001122"}
        assert "fieldGuid" not in cfg
        assert _items_in_ph(data, "colors")[0]["type"] == "PSEUDO"
        assert _items_in_ph(data, "x")[-1]["guid"] == "dim"

    def test_color_by_measure_name_accepts_rgba_override(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .color_by_measure_name(colors_map={"measure_1": "#4DA256FF"})
        )
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg["mountedColors"] == {"measure_1": "#4DA256FF", "measure_2": "1"}

    def test_color_by_measure_name_requires_two_measures(self) -> None:
        ds = _dataset("dim", "measure")
        builder = (
            _factory.line(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["measure"]).color_by_measure_name()
        )
        with pytest.raises(DataLensConfigurationError, match=r"requires at least two measures"):
            _build(builder)

    def test_color_by_measure_name_collects_line_y_and_y2(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        data = _build(
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1"])
            .y2(["measure_2"])
            .color_by_measure_name()
        )
        assert _items_in_ph(data, "colors")[0]["type"] == "PSEUDO"
        assert _slot_settings(data, "colors")["mountedColors"] == {
            "measure_1": "0",
            "measure_2": "1",
        }

    def test_bar_measure_names_are_added_to_category_placeholder(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        data = _build(
            _factory.bar(name="Chart", location=_loc())
            .dataset(ds)
            .x(["measure_1", "measure_2"])
            .y(["dim"])
            .color_by_measure_name()
        )
        assert _items_in_ph(data, "colors")[-1]["type"] == "PSEUDO"

    def test_pivot_measure_names_remain_layout_only(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        data = _build(
            _factory.pivot_table(name="Chart", location=_loc())
            .dataset(ds)
            .rows(["dim"])
            .measures(["measure_1", "measure_2"])
        )
        assert _items_in_ph(data, "measures")[-1]["guid"] == "measure_2"
        assert _items_in_ph(data, "colors") == []
        assert _slot_settings(data, "colors") == {}

    def test_color_by_measure_name_rejects_invalid_color(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .color_by_measure_name(colors_map={"measure_1": "red"})
        )
        with pytest.raises(DataLensConfigurationError, match="colors must be #RRGGBB"):
            _build(builder)


class TestAddFilterHelper:
    def test_add_filter_with_string_field_ref_writes_filter_to_payload(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .add_filter("dim", operation="EQ", values=["Moscow"])
        )
        data = _build(builder)
        filters = _source_items(data, "filters")
        assert len(filters) == 1
        assert filters[0]["guid"] == "dim"
        assert filters[0]["filter"]["operation"]["code"] == "EQ"
        assert filters[0]["filter"]["value"] == ["Moscow"]

    def test_add_filter_multiple_calls_accumulate_filters(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .add_filter("dim", operation="EQ", values=["Moscow"])
            .add_filter("meas", operation="GT", values=["1000"])
        )
        data = _build(builder)
        filters = _source_items(data, "filters")
        assert len(filters) == 2

    def test_add_filter_default_values_is_empty(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .add_filter("dim", operation="ISNULL")
        )
        data = _build(builder)
        filters = _source_items(data, "filters")
        assert len(filters) == 1
        assert "value" not in filters[0]["filter"]


class TestAddDateFilterHelper:
    def test_add_date_filter_produces_between_with_interval(self) -> None:
        ds = _dataset("date_dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["date_dim"])
            .y(["meas"])
            .add_date_filter("date_dim", start="2026-01-01", end="2026-01-31")
        )
        data = _build(builder)
        filters = _source_items(data, "filters")
        assert len(filters) == 1
        assert filters[0]["filter"]["operation"]["code"] == "BETWEEN"
        value = filters[0]["filter"]["value"]
        assert len(value) == 1
        assert value[0].startswith("__interval_")
        assert "2026-01-01" in value[0]

    def test_add_relative_date_filter_produces_between_with_relative_interval(self) -> None:
        ds = _dataset("date_dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["date_dim"])
            .y(["meas"])
            .add_relative_date_filter("date_dim", start_offset="-30d", end_offset="+0d")
        )
        data = _build(builder)
        filters = _source_items(data, "filters")
        assert len(filters) == 1
        assert filters[0]["filter"]["operation"]["code"] == "BETWEEN"
        value = filters[0]["filter"]["value"]
        assert len(value) == 1
        assert "__relative_-30d" in value[0]
        assert "__relative_+0d" in value[0]


class TestAddSortHelper:
    def test_add_sort_with_direction_writes_sort_item_with_direction(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .add_sort("meas", direction="desc")
        )
        data = _build(builder)
        sort = _items_in_ph(data, "sort")
        assert len(sort) == 1
        assert sort[0].get("direction") == "DESC"
        assert sort[0].get("guid") == "meas"

    def test_add_sort_default_direction_is_asc(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.column(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).add_sort("dim")
        data = _build(builder)
        sort = _items_in_ph(data, "sort")
        assert sort[0].get("direction") == "ASC"

    def test_add_sort_writes_minimal_reference_not_full_snapshot(self) -> None:
        # DataLens matches a sort entry to a placed field by guid and ignores the
        # rest. A full field snapshot (formula / aggregation / calc_mode /
        # placeholder ``id`` / ...) is rejected on create (400) and silently not
        # applied on update, so the sort item must carry only identity keys.
        ds = _dataset("dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .add_sort("meas", direction="desc")
        )
        data = _build(builder)
        sort = _items_in_ph(data, "sort")
        allowed = {"guid", "datasetId", "data_type", "title", "source", "type", "direction"}
        assert set(sort[0]) <= allowed, f"unexpected sort keys: {set(sort[0]) - allowed}"
        for forbidden in ("formula", "calc_mode", "aggregation", "autoaggregated", "id", "guid_formula"):
            assert forbidden not in sort[0], f"sort item must not carry {forbidden!r}"


class TestDescriptionHelper:
    def test_description_sets_annotation_on_create_dto(self) -> None:
        builder = _factory.line(name="Chart", location=_loc()).description("My chart description")
        dto = WizardChartConverter.from_domain_create(builder.to_spec())
        payload = cast(dict[str, Any], dto.to_payload())
        annotation = payload.get("annotation")
        assert annotation is not None
        assert cast(dict[str, Any], annotation).get("description") == "My chart description"

    def test_no_description_produces_no_annotation(self) -> None:
        builder = _factory.line(name="Chart", location=_loc())
        dto = WizardChartConverter.from_domain_create(builder.to_spec())
        payload = cast(dict[str, Any], dto.to_payload())
        assert payload.get("annotation") is None


class TestTableSizeHelper:
    def test_table_size_writes_size_to_extraSettings(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).table_size(size="s")
        extra = _extra(builder)
        assert extra.get("size") == "s"

    def test_table_size_m(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).table_size(size="m")
        extra = _extra(builder)
        assert extra.get("size") == "m"

    def test_pivot_table_size(self) -> None:
        builder = _factory.pivot_table(name="Chart", location=_loc()).table_size(size="l")
        extra = _extra(builder)
        assert extra.get("size") == "l"


class TestFreezeColumnsHelper:
    def test_flat_table_freezes_columns(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).freeze_columns(count=2)
        assert _extra(builder).get("pinnedColumns") == 2

    def test_flat_table_zero_unfreezes_columns(self) -> None:
        builder = _factory.flat_table(name="Chart", location=_loc()).freeze_columns(count=0)
        assert _extra(builder).get("pinnedColumns") == 0

    def test_pivot_table_freeze_columns_fails_before_payload_construction(self) -> None:
        builder = _factory.pivot_table(name="Chart", location=_loc())
        with pytest.raises(NotImplementedError, match=r"pivotTable.*pinnedColumns"):
            builder.freeze_columns()


class TestIndicatorHelpers:
    def test_font_size_maps_ui_to_payload(self) -> None:
        builder = _factory.indicator(name="Chart", location=_loc()).font_size(size="xs")
        extra = _extra(builder)
        assert extra.get("metricFontSize") == "s"

    def test_font_size_m_maps_to_l(self) -> None:
        builder = _factory.indicator(name="Chart", location=_loc()).font_size(size="m")
        extra = _extra(builder)
        assert extra.get("metricFontSize") == "l"

    def test_font_color_valid_hex_writes_to_extra(self) -> None:
        builder = _factory.indicator(name="Chart", location=_loc()).font_color(color="#FF0000")
        extra = _extra(builder)
        assert extra.get("metricFontColor") == "#FF0000"

    def test_measure_title_mode_manual(self) -> None:
        builder = _factory.indicator(name="Chart", location=_loc()).measure_title_mode(mode="manual")
        extra = _extra(builder)
        assert extra.get("titleMode") == "manual"

    def test_font_color_invalid_hex_raises_error(self) -> None:
        with pytest.raises(DataLensConfigurationError, match="hex string like #RRGGBB"):
            _factory.indicator(name="Chart", location=_loc()).font_color(color="red")

    def test_measure_title_mode_by_field(self) -> None:
        builder = _factory.indicator(name="Chart", location=_loc()).measure_title_mode(mode="by-field")
        extra = _extra(builder)
        assert extra.get("titleMode") == "by-field"

    def test_measure_title_mode_hide(self) -> None:
        builder = _factory.indicator(name="Chart", location=_loc()).measure_title_mode(mode="hide")
        extra = _extra(builder)
        assert extra.get("titleMode") == "hide"


class TestAddLocalFieldHelper:
    def test_local_field_factories_create_stable_hashable_handles(self) -> None:
        dimension = WizardLocalField.dimension(title="Bucket", formula="[Value] > 0", guid="dim-guid", cast="boolean")
        measure = WizardLocalField.measure(
            title="Revenue",
            formula="SUM([Sales])",
            guid="measure-guid",
            cast="integer",
            formatting={"precision": 0},
        )

        assert dimension.guid == "dim-guid"
        assert dimension.type == "DIMENSION"
        assert dimension.data_type == "boolean"
        assert dimension.autoaggregated is False
        assert measure.guid == "measure-guid"
        assert measure.type == "MEASURE"
        assert measure.data_type == "integer"
        assert measure.aggregation == "none"
        assert measure.autoaggregated is True
        assert {measure: "color"}[measure] == "color"
        with pytest.raises(TypeError):
            measure.formatting["precision"] = 2

        hints = get_type_hints(WizardLocalField.measure)
        assert hints["formatting"] == MeasureFormat | None

    def test_local_field_formatting_lives_on_carrier_not_source_update(self) -> None:
        ds = _dataset("dim")
        local = WizardLocalField.measure(
            title="Revenue",
            formula="SUM([Sales])",
            guid="formatted-local",
            formatting={"format": "number", "precision": 2, "prefix": "$"},
        )
        data = _build(
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .add_local_field(local)
            .columns([local])
            .add_sort(local, direction="desc")
        )

        source_field = cast(dict[str, Any], _source_items(data, "updates")[0]["field"])
        assert "formatting" not in source_field
        assert _items_in_ph(data, "flat-table-columns")[0]["formatting"] == {
            "format": "number",
            "precision": 2,
            "prefix": "$",
        }
        assert _items_in_ph(data, "sort") == [{"guid": local.guid, "datasetId": ds.id, "direction": "DESC"}]

    def test_create_rejects_local_and_aggregated_measure_guid_collision(self) -> None:
        ds = _dataset("dim")
        first = WizardLocalField.dimension(title="First", formula="[a]", guid="duplicate-guid")
        second = WizardAggregatedMeasure(
            field=ds.fields.by_guid("dim"),
            aggregation="countunique",
            title="Second",
            guid="duplicate-guid",
        )
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .add_local_field(first)
            .add_aggregated_measure(second)
        )

        with pytest.raises(DataLensValidationError, match=r"duplicate-guid.*First.*Second"):
            _build(builder)

    def test_create_rejects_local_field_and_hierarchy_guid_collision(self) -> None:
        ds = _dataset("dim")
        local = WizardLocalField.dimension(title="Local", formula="[dim]", guid="shared-guid")
        hierarchy = WizardHierarchy(title="Hierarchy", fields=[ds.fields.by_guid("dim")], guid="shared-guid")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .add_local_field(local)
            .add_hierarchy(hierarchy)
        )

        with pytest.raises(DataLensValidationError, match=r"shared-guid.*Local.*Hierarchy"):
            _build(builder)

    def test_create_rejects_dataset_parameter_and_local_field_guid_collision(self) -> None:
        ds = Dataset(
            id="ds1",
            name="ds",
            location=EntryLocation.path("/"),
            result_schema=(
                {
                    "guid": "parameter-guid",
                    "title": "Threshold",
                    "calc_mode": "parameter",
                    "data_type": "float",
                    "default_value": 1,
                },
            ),
        )
        local = WizardLocalField.measure(title="Local", formula="SUM([x])", guid="parameter-guid")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).add_local_field(local)

        with pytest.raises(DataLensValidationError, match=r"parameter-guid.*Threshold.*Local"):
            _build(builder)

    def test_create_rejects_dataset_field_and_local_field_guid_collision(self) -> None:
        ds = _dataset("direct-guid")
        local = WizardLocalField.dimension(title="Local", formula="[x]", guid="direct-guid")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).add_local_field(local)

        with pytest.raises(DataLensValidationError, match=r"direct-guid.*field_direct-guid.*Local"):
            _build(builder)

    def test_add_local_field_with_explicit_guid(self) -> None:
        local = WizardLocalField.measure(
            title="Revenue",
            formula="SUM([Sales])",
            guid="my-guid",
        )
        builder = _factory.line(name="Chart", location=_loc()).add_local_field(local)
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert len(updates) == 1
        field = cast(dict[str, Any], updates[0]["field"])
        assert field["guid"] == "my-guid"
        assert field["title"] == "Revenue"
        assert field["formula"] == "SUM([Sales])"

    def test_add_local_field_without_guid_auto_generates_guid(self) -> None:
        local = WizardLocalField.dimension(
            title="MyField",
            formula="[X] + 1",
        )
        builder = _factory.line(name="Chart", location=_loc()).add_local_field(local)
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert len(updates) == 1
        field = cast(dict[str, Any], updates[0]["field"])
        assert field.get("guid")

    def test_local_field_handle_requires_registration(self) -> None:
        ds = _dataset("dim", "meas")
        local = WizardLocalField.measure(title="Revenue", formula="SUM([Sales])", guid="lf-unregistered")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", local])

        with pytest.raises(DataLensValidationError, match=r"Call add_local_field\(field\)"):
            _build(builder)

    def test_add_aggregated_measure_creates_local_direct_field(self) -> None:
        ds = _dataset("dim", "meas")
        unique_dimension = WizardAggregatedMeasure(
            field=ds.fields.by_name("field_dim"),
            aggregation="countunique",
            title="Unique dimensions",
            guid="unique-dimensions",
        )
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .add_aggregated_measure(unique_dimension)
            .y([unique_dimension])
        )
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert len(updates) == 1
        field = cast(dict[str, Any], updates[0]["field"])
        assert field["calc_mode"] == "direct"
        assert field["aggregation"] == "countunique"
        assert field["type"] == "MEASURE"
        assert field["guid"] == unique_dimension.guid
        assert _items_in_ph(data, "y")[0]["guid"] == unique_dimension.guid

    def test_add_aggregated_measure_copies_formula_dimension(self) -> None:
        formula_dimension = DatasetField(
            guid="gmv_formula",
            title="GMV in currency",
            name="gmv_currency",
            calc_mode="formula",
            data_type="float",
            type="DIMENSION",
            formula="IF([flag], [gmv], [gmv] * [rate])",
        )
        measure = WizardAggregatedMeasure(
            field=formula_dimension,
            aggregation="sum",
            title="GMV",
            guid="gmv_sum",
        )
        builder = _factory.line(name="Chart", location=_loc()).add_aggregated_measure(measure)
        data = _build(builder)
        field = cast(dict[str, Any], _source_items(data, "updates")[0]["field"])
        assert field["title"] == "GMV"
        assert field["calc_mode"] == "formula"
        assert field["formula"] == "IF([flag], [gmv], [gmv] * [rate])"
        assert field["source"] == ""
        assert field["type"] == "MEASURE"
        assert field["aggregation"] == "sum"


class TestHierarchyHelper:
    def test_hierarchy_adds_to_hierarchies_in_data(self) -> None:
        ds = _dataset("region", "city", "meas")
        hierarchy = WizardHierarchy(
            title="Location",
            fields=[ds.fields.by_guid("region"), ds.fields.by_guid("city")],
            guid="location",
        )
        assert hierarchy.fields == (ds.fields.by_guid("region"), ds.fields.by_guid("city"))
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .columns(["region", "city", "meas"])
            .add_hierarchy(hierarchy)
        )
        data = _build(builder)
        hierarchies = _source_items(data, "hierarchies")
        assert len(hierarchies) == 1
        hier = hierarchies[0]
        assert hier["title"] == "Location"
        assert set(hier.keys()) == {"guid", "title", "fields"}
        assert isinstance(hier["fields"], list)
        assert len(hier["fields"]) == 2
        # Wizard v3 source hierarchies carry minimal field references.
        field0 = cast(dict[str, Any], hier["fields"][0])
        assert isinstance(field0, dict)
        assert field0["guid"] in {"region", "city"}
        assert field0.get("datasetId") == "ds1"
        assert set(field0) == {"guid", "datasetId"}

    def test_hierarchy_placed_via_placeholder_setter_mounts_seven_key_object(self) -> None:
        ds = _dataset("region", "city", "meas")
        hierarchy = WizardHierarchy(
            title="Location",
            fields=[ds.fields.by_guid("region"), ds.fields.by_guid("city")],
            guid="location",
        )
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .add_hierarchy(hierarchy)
            .columns([hierarchy, "meas"])
        )
        data = _build(builder)
        hierarchies = _source_items(data, "hierarchies")
        assert len(hierarchies) == 1
        hier = hierarchies[0]

        columns_items = _items_in_ph(data, "flat-table-columns")
        assert columns_items, "flat-table-columns placeholder must contain items"
        first = columns_items[0]
        # Mounted hierarchy uses the strict Wizard v3 item projection.
        assert first["data_type"] == "hierarchy"
        assert first["guid"] == hier["guid"]
        assert set(first.keys()) == {"guid", "title", "data_type", "fields"}


class TestPointSizeRangeHelper:
    def test_point_size_range_writes_geopointsConfig(self) -> None:
        builder = _factory.scatter(name="Chart", location=_loc()).point_size_range(min_radius=3.0, max_radius=12.0)
        data = _build(builder)
        config = _slot_settings(data, "size")
        assert config.get("minRadius") == 3.0
        assert config.get("maxRadius") == 12.0
        assert config.get("radius") == 7.5


class TestShapeByDimensionHelper:
    def test_shape_by_dimension_writes_shapesConfig(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .shape_by_dimension("dim", shapes_map={"Category A": "Solid", "Category B": "Dash"})
        )
        data = _build(builder)
        config = _slot_settings(data, "shapes")
        assert config.get("fieldGuid") == "dim"
        mounted = cast(dict[str, Any], config.get("mountedShapes", {}))
        assert mounted.get("Category A") == "Solid"
        assert mounted.get("Category B") == "Dash"

    def test_shape_by_dimension_without_map_sets_only_field_guid(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.line(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).shape_by_dimension("dim")
        )
        data = _build(builder)
        config = _slot_settings(data, "shapes")
        assert config.get("fieldGuid") == "dim"
        assert "mountedShapes" not in config

    def test_line_shape_by_measure_name_writes_measure_names_and_mounted_shapes(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .shape_by_measure_name(shapes_map={"measure_1": "Solid", "measure_2": "Dash"})
        )
        data = _build(builder)
        assert _items_in_ph(data, "shapes")[0]["type"] == "PSEUDO"
        assert _slot_settings(data, "shapes")["mountedShapes"] == {
            "measure_1": "Solid",
            "measure_2": "Dash",
        }

    def test_shape_by_measure_name_requires_two_measures(self) -> None:
        ds = _dataset("dim", "measure")
        builder = (
            _factory.line(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["measure"]).shape_by_measure_name()
        )
        with pytest.raises(DataLensConfigurationError, match="requires at least two measures"):
            _build(builder)

    def test_shape_by_measure_name_collects_line_y_and_y2(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        data = _build(
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1"])
            .y2(["measure_2"])
            .shape_by_measure_name(shapes_map={"measure_1": "Solid", "measure_2": "Dash"})
        )
        assert _items_in_ph(data, "shapes")[0]["type"] == "PSEUDO"
        assert _slot_settings(data, "shapes")["mountedShapes"] == {
            "measure_1": "Solid",
            "measure_2": "Dash",
        }

    def test_shape_by_measure_name_rejects_unplaced_measure(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2", "third_dim", "measure_3")
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .shape_by_measure_name(shapes_map={"measure_3": "Dash"})
        )
        with pytest.raises(DataLensConfigurationError, match="not placed as a measure"):
            _build(builder)

    def test_shape_by_dimension_rejects_measure(self) -> None:
        ds = _dataset("dim", "measure")
        builder = (
            _factory.scatter(name="Chart", location=_loc())
            .dataset(ds)
            .x(["measure"])
            .y(["measure"])
            .shape_by_dimension("measure")
        )
        with pytest.raises(DataLensConfigurationError, match="requires a DIMENSION"):
            _build(builder)


class TestUpdateVizApplicabilityGuard:
    def _wizard_chart(self, viz_id: str = "line") -> WizardChart:
        ds = _dataset("dim", "meas")
        builder: Any
        if viz_id == "flatTable":
            builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        elif viz_id == "pie":
            builder = _factory.pie(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"])
        else:
            builder = _factory.line(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"])
        return WizardChart(
            id="chart-1",
            installation="yacloud",
            data=_build(builder),
        )

    def test_totals_on_line_chart_raises_configuration_error(self) -> None:
        chart = self._wizard_chart("line")
        with pytest.raises(DataLensConfigurationError, match=r"totals.*line"):
            chart.update.totals(enabled=True)

    def test_totals_on_flat_table_does_not_raise(self) -> None:
        chart = self._wizard_chart("flatTable")
        update = chart.update.totals(enabled=True)
        assert update is not None

    def test_nulls_mode_on_pie_raises_configuration_error(self) -> None:
        chart = self._wizard_chart("pie")
        with pytest.raises(DataLensConfigurationError, match=r"nulls_mode.*pie"):
            chart.update.nulls_mode("x", mode="ignore")

    def test_axis_visibility_on_line_chart_does_not_raise(self) -> None:
        chart = self._wizard_chart("line")
        update = chart.update.axis_visibility("x", mode="show")
        assert update is not None


class TestColorByMeasureHelper:
    def test_default_measure_color_does_not_force_gradient_settings(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.color_by_measure("meas")
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg["fieldGuid"] == "meas"
        assert "gradientMode" not in cfg
        assert "gradientPalette" not in cfg

    def test_explicit_gradient_settings_write_field_guid(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.color_by_measure("meas", mode="2-point", palette="blue")
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg.get("fieldGuid") == "meas"
        assert cfg.get("gradientMode") == "2-point"
        assert cfg.get("gradientPalette") == "blue"
        assert cfg.get("reversed") is False
        assert cfg.get("thresholdsMode") == "auto"

    def test_measure_format_applies_to_semantic_color_placeholder_on_create(self) -> None:
        ds = _dataset("dim", "meas", "other_dim", "color_meas")
        data = _build(
            _factory.treemap(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .color_by_measure("color_meas")
            .measure_format("color_meas", format="number", unit="m", precision=1)
        )
        assert _items_in_ph(data, "colors")[0]["formatting"] == {
            "format": "number",
            "unit": "m",
            "precision": 1,
        }

    def test_color_by_measure_3_point_with_palette_and_reversed(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.color_by_measure("meas", mode="3-point", palette="red-orange-green", reversed=True)
        data = _build(builder)
        cfg = _slot_settings(data, "colors")
        assert cfg.get("gradientMode") == "3-point"
        assert cfg.get("gradientPalette") == "red-orange-green"
        assert cfg.get("reversed") is True

    def test_color_by_measure_invalid_palette_raises(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        with pytest.raises(DataLensConfigurationError, match="gradient palette"):
            builder.color_by_measure("meas", palette="classic20")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("mode", "palette"),
        [
            ("3-point", "blue"),
            ("2-point", "red-orange-green"),
        ],
    )
    def test_color_by_measure_rejects_incompatible_mode_and_palette_on_create(
        self,
        mode: Any,
        palette: Any,
    ) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])

        with pytest.raises(DataLensConfigurationError, match=r"does not support mode"):
            builder.color_by_measure("meas", mode=mode, palette=palette)

    @pytest.mark.parametrize(
        ("mode", "palette"),
        [
            ("3-point", "blue"),
            ("2-point", "red-orange-green"),
        ],
    )
    def test_color_by_measure_rejects_incompatible_mode_and_palette_on_update(
        self,
        mode: Any,
        palette: Any,
    ) -> None:
        ds = _dataset("dim", "meas")
        chart = WizardChart(
            id="chart-1",
            data=_build(_factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])),
        )

        with pytest.raises(DataLensConfigurationError, match=r"does not support mode"):
            chart.update.color_by_measure("meas", mode=mode, palette=palette)

    def test_color_by_measure_writes_measure_to_colors_list(self) -> None:
        ds = _dataset("dim", "meas")
        builder = _factory.flat_table(name="Chart", location=_loc()).dataset(ds).columns(["dim", "meas"])
        builder.color_by_measure("meas")
        data = _build(builder)
        colors = _items_in_ph(data, "colors")
        assert any(c.get("guid") == "meas" for c in colors)

    def test_color_by_measure_rejects_dimension(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .columns(["dim", "meas"])
            .color_by_measure("dim")
        )
        with pytest.raises(DataLensConfigurationError, match="requires a MEASURE"):
            _build(builder)


class TestSemanticEncodingUpdates:
    @staticmethod
    def _chart(data: dict[str, Any]) -> WizardChart:
        return WizardChart(id="chart-1", installation="yacloud", data=data)

    @staticmethod
    def _update_data(update: Any) -> dict[str, Any]:
        return cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    @staticmethod
    def _column_with_color(ds: Dataset, mode: str) -> dict[str, Any]:
        builder = _factory.column(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["measure_1", "measure_2"])
        if mode == "dimension":
            builder.color_by_dimension("dim")
        elif mode == "measure":
            builder.color_by_measure("measure_1", mode="2-point", palette="blue", reversed=True)
        elif mode == "measure_name":
            builder.color_by_measure_name(colors_map={"measure_2": "#001122"})
        else:
            raise AssertionError(f"unknown Color mode: {mode}")
        return _build(builder)

    @staticmethod
    def _set_color(update: Any, ds: Dataset, mode: str) -> Any:
        if mode == "dimension":
            return update.color_by_dimension(ds.fields.by_name("field_dim"))
        if mode == "measure":
            return update.color_by_measure(
                ds.fields.by_name("field_measure_1"), mode="2-point", palette="blue", reversed=True
            )
        if mode == "measure_name":
            return update.color_by_measure_name(colors_map={"measure_2": "#001122"})
        raise AssertionError(f"unknown Color mode: {mode}")

    @staticmethod
    def _encoding_fragment(data: dict[str, Any]) -> dict[str, Any]:
        visualization = cast(dict[str, Any], data["visualization"])
        x_slot = cast(dict[str, Any], visualization["x"])

        def normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            # ``id`` and ``datasetName`` are renderer/provenance details that
            # differ between create and an already-loaded update.  Encoding
            # semantics are determined by the field identity and type.
            return [
                {key: item[key] for key in ("guid", "title", "type", "data_type", "datasetId") if key in item}
                for item in items
            ]

        return {
            "colors": normalize_items(_items_in_ph(data, "colors")),
            "colorsConfig": _slot_settings(data, "colors"),
            "categoryItems": normalize_items(cast(list[dict[str, Any]], x_slot["items"])),
        }

    @pytest.mark.parametrize(
        ("source_mode", "target_mode"),
        [
            ("dimension", "measure"),
            ("measure", "dimension"),
            ("measure", "measure_name"),
            ("measure_name", "measure"),
            ("dimension", "measure_name"),
            ("measure_name", "dimension"),
            ("dimension", "dimension"),
            ("measure", "measure"),
            ("measure_name", "measure_name"),
        ],
    )
    def test_color_transitions_are_path_independent(self, source_mode: str, target_mode: str) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        expected = self._column_with_color(ds, target_mode)
        source = self._column_with_color(ds, source_mode)

        actual = self._update_data(self._set_color(self._chart(source).update, ds, target_mode))

        assert self._encoding_fragment(actual) == self._encoding_fragment(expected)

    def test_shape_transitions_are_path_independent_and_clear_field_binding(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        baseline = _build(
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .shape_by_measure_name(shapes_map={"measure_1": "Solid", "measure_2": "Dash"})
        )
        source = _build(
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .shape_by_dimension("dim", shapes_map={"North": "Dot"})
        )

        actual = self._update_data(
            self._chart(source).update.shape_by_measure_name(shapes_map={"measure_1": "Solid", "measure_2": "Dash"})
        )

        assert _items_in_ph(actual, "shapes") == _items_in_ph(baseline, "shapes")
        assert _slot_settings(actual, "shapes") == _slot_settings(baseline, "shapes")
        assert "fieldGuid" not in _slot_settings(actual, "shapes")

    def test_shape_dimension_replacement_clears_previous_mounted_shapes(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        source = _build(
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1", "measure_2"])
            .shape_by_dimension("dim", shapes_map={"North": "Dot"})
        )

        actual = self._update_data(self._chart(source).update.shape_by_dimension(ds.fields.by_name("field_other_dim")))

        assert _slot_settings(actual, "shapes") == {"fieldGuid": "other_dim"}

    def test_funnel_dimension_color_writes_a_data_encoding(self) -> None:
        ds = _dataset("dim", "meas")
        data = _build(
            _factory.funnel(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_dimension("dim")
        )

        assert _items_in_ph(data, "colors")[0]["guid"] == "dim"
        assert set(_items_in_ph(data, "colors")[0]) == {"guid", "datasetId"}
        assert _slot_settings(data, "colors") == {"palette": "datalens-classic-20"}

    def test_last_color_call_wins_on_update(self) -> None:
        ds = _dataset("dim", "meas")
        original = _build(
            _factory.column(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]).color_by_dimension("dim")
        )
        data = self._update_data(
            self._chart(original)
            .update.color_by_dimension(ds.fields.by_name("field_dim"))
            .color_by_measure(ds.fields.by_name("field_meas"))
        )
        assert _items_in_ph(data, "colors")[0]["guid"] == "meas"

    def test_measure_format_applies_to_semantic_color_placeholder_on_update(self) -> None:
        ds = _dataset("dim", "meas", "other_dim", "color_meas")
        original = _build(
            _factory.treemap(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .color_by_measure("color_meas")
        )
        data = self._update_data(
            self._chart(original)
            .update.color_by_measure(ds.fields.by_name("field_color_meas"))
            .measure_format(ds.fields.by_name("field_color_meas"), format="number", unit="m", precision=1)
        )
        assert _items_in_ph(data, "colors")[0]["formatting"] == {
            "format": "number",
            "unit": "m",
            "precision": 1,
        }

    def test_last_shape_call_wins_on_update(self) -> None:
        ds = _dataset("dim", "measure_1", "other_dim", "measure_2")
        original = _build(
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["measure_1"])
            .y2(["measure_2"])
            .shape_by_dimension("dim")
        )
        data = self._update_data(
            self._chart(original)
            .update.shape_by_dimension("dim")
            .shape_by_measure_name(shapes_map={"measure_1": "Solid", "measure_2": "Dash"})
        )
        assert _items_in_ph(data, "shapes")[0]["type"] == "PSEUDO"
        assert _slot_settings(data, "shapes")["mountedShapes"] == {
            "measure_1": "Solid",
            "measure_2": "Dash",
        }

    @pytest.mark.parametrize("viz_method", ["pie", "donut"])
    def test_pie_family_update_replaces_dedicated_color_placeholder(self, viz_method: str) -> None:
        ds = _dataset("dim", "meas", "other_dim")
        original = _build(
            getattr(_factory, viz_method)(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"])
        )
        data = self._update_data(self._chart(original).update.color_by_dimension(ds.fields.by_name("field_other_dim")))
        assert _items_in_ph(data, "colors")[0]["guid"] == "other_dim"
        assert _slot_settings(data, "colors")["palette"] == "datalens-classic-20"

    def test_treemap_accepts_an_independent_dimension_on_update(self) -> None:
        ds = _dataset("dim", "meas", "other_dim")
        original = _build(_factory.treemap(name="Chart", location=_loc()).dataset(ds).x(["dim"]).y(["meas"]))
        data = self._update_data(self._chart(original).update.color_by_dimension(ds.fields.by_name("field_other_dim")))
        assert _items_in_ph(data, "colors")[0]["guid"] == "other_dim"

    def test_metric_rejects_color_encoding_on_update(self) -> None:
        ds = _dataset("dim", "meas")
        original = _build(_factory.indicator(name="Chart", location=_loc()).dataset(ds).y(["meas"]))
        with pytest.raises(DataLensConfigurationError, match=r"color_by_measure.*not applicable.*metric"):
            self._chart(original).update.color_by_measure(ds.fields.by_name("field_meas"))


class TestMeasureFormatHelper:
    @pytest.mark.parametrize("unit", ["b", "t"])
    def test_measure_format_preserves_openapi_unit(self, unit: Literal["b", "t"]) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .columns(["dim", "meas"])
            .measure_format("meas", unit=unit)
        )

        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        assert cast(dict[str, Any], meas_item["formatting"])["unit"] == unit

    def test_measure_format_patches_item_formatting(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .columns(["dim", "meas"])
            .measure_format("meas", format="percent", precision=2)
        )
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        fmt = cast(dict[str, Any], meas_item.get("formatting", {}))
        assert fmt.get("format") == "percent"
        assert fmt.get("precision") == 2

    def test_measure_format_show_rank_delimiter_maps_to_camel_case(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .columns(["dim", "meas"])
            .measure_format("meas", show_rank_delimiter=True)
        )
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        fmt = cast(dict[str, Any], meas_item.get("formatting", {}))
        assert fmt.get("showRankDelimiter") is True

    def test_measure_format_patches_indicator_measure_item(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.indicator(name="Chart", location=_loc())
            .dataset(ds)
            .y(["meas"])
            .measure_format("meas", format="percent", precision=1)
        )
        data = _build(builder)
        items = _items_in_ph(data, "measures")
        meas_item = next(it for it in items if it.get("guid") == "meas")
        fmt = cast(dict[str, Any], meas_item.get("formatting", {}))
        assert fmt.get("format") == "percent"
        assert fmt.get("precision") == 1

    def test_measure_format_patches_local_field_in_updates(self) -> None:
        ds = _dataset("dim", "meas")
        revenue = WizardLocalField.measure(title="Revenue", formula="SUM([Sales])", guid="lf1")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .add_local_field(revenue)
            .columns([revenue])
            .measure_format(revenue, format="number", prefix="$")
        )
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert any(upd.get("field", {}).get("guid") == "lf1" for upd in updates)
        item = _items_in_ph(data, "flat-table-columns")[0]
        assert item["formatting"] == {"format": "number", "prefix": "$"}

    def test_measure_format_mirrors_to_labels(self) -> None:
        ds = _dataset("dim", "meas")
        builder = (
            _factory.column(name="Chart", location=_loc())
            .dataset(ds)
            .x(["dim"])
            .y(["meas"])
            .labels(["meas"])
            .measure_format("meas", format="number", prefix="$")
        )
        data = _build(builder)
        labels = _items_in_ph(data, "labels")
        label_item = next(it for it in labels if it.get("guid") == "meas")
        fmt = cast(dict[str, Any], label_item.get("formatting", {}))
        assert fmt.get("format") == "number"

    @staticmethod
    def _assert_format_stays_off_sort_reference(data: dict[str, Any], *, guid: str) -> None:
        expected = {"format": "number", "precision": 2}
        assert _items_in_ph(data, "x")[0]["formatting"] == expected
        assert _items_in_ph(data, "labels")[0]["formatting"] == expected
        sort_items = _items_in_ph(data, "sort")
        target = next(item for item in sort_items if item.get("guid") == guid)
        assert target == {"guid": guid, "datasetId": "ds1", "direction": "DESC"}
        assert all("formatting" not in item for item in sort_items)

    def test_direct_measure_format_and_sort_compose_on_create(self) -> None:
        ds = _dataset("dim", "meas")
        measure = ds.fields.by_name("field_meas")
        data = _build(
            _factory.bar(name="Chart", location=_loc())
            .dataset(ds)
            .x([measure])
            .y(["dim"])
            .labels([measure])
            .add_sort(measure, direction="desc")
            .measure_format(measure, format="number", precision=2)
        )

        self._assert_format_stays_off_sort_reference(data, guid="meas")

    def test_direct_measure_format_and_sort_compose_on_update(self) -> None:
        ds = _dataset("dim", "meas")
        measure = ds.fields.by_name("field_meas")
        original = _build(_factory.bar(name="Chart", location=_loc()).dataset(ds).x([measure]).y(["dim"]))
        chart = WizardChart(id="chart-1", installation="yacloud", data=original)
        update = (
            chart.update.labels([measure])
            .add_sort(measure, direction="desc")
            .measure_format(measure, format="number", precision=2)
        )
        data = cast(
            dict[str, Any],
            WizardChartConverter.from_domain_update(update).to_payload()["data"],
        )

        self._assert_format_stays_off_sort_reference(data, guid="meas")

    def test_local_measure_format_and_sort_compose_on_create(self) -> None:
        ds = _dataset("dim", "meas")
        local = WizardLocalField.measure(guid="lf1", title="Revenue", formula="SUM([field_meas])")
        data = _build(
            _factory.bar(name="Chart", location=_loc())
            .dataset(ds)
            .add_local_field(local)
            .x([local])
            .y(["dim"])
            .labels([local])
            .add_sort(local, direction="desc")
            .measure_format(local, format="number", precision=2)
        )

        self._assert_format_stays_off_sort_reference(data, guid="lf1")

    def test_local_measure_format_and_sort_compose_on_update(self) -> None:
        ds = _dataset("dim", "meas")
        local = WizardLocalField.measure(guid="lf1", title="Revenue", formula="SUM([field_meas])")
        original = _build(
            _factory.bar(name="Chart", location=_loc()).dataset(ds).add_local_field(local).x([local]).y(["dim"])
        )
        chart = WizardChart(id="chart-1", installation="yacloud", data=original)
        update = (
            chart.update.labels([local])
            .add_sort(local, direction="desc")
            .measure_format(local, format="number", precision=2)
        )
        data = cast(
            dict[str, Any],
            WizardChartConverter.from_domain_update(update).to_payload()["data"],
        )

        self._assert_format_stays_off_sort_reference(data, guid="lf1")


class TestLocalFieldDatasetIdRegression:
    def test_add_local_field_update_carries_dataset_id(self) -> None:
        ds = _dataset("dim", "meas")
        revenue = WizardLocalField.measure(title="Revenue", formula="SUM([Sales])", guid="lf1")
        builder = _factory.line(name="Chart", location=_loc()).dataset(ds).add_local_field(revenue)
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert len(updates) == 1
        field = cast(dict[str, Any], updates[0]["field"])
        assert field.get("datasetId") == "ds1"

    def test_add_aggregated_measure_carries_dataset_id(self) -> None:
        ds = _dataset("dim", "meas")
        unique_dimension = WizardAggregatedMeasure(
            field=ds.fields.by_name("field_dim"),
            aggregation="countunique",
            title="Unique dimensions",
        )
        builder = _factory.line(name="Chart", location=_loc()).dataset(ds).add_aggregated_measure(unique_dimension)
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert len(updates) == 1
        field = cast(dict[str, Any], updates[0]["field"])
        assert field.get("datasetId") == "ds1"

    def test_local_field_placeholder_item_carries_dataset_id(self) -> None:
        ds = _dataset("dim", "meas")
        revenue = WizardLocalField.measure(title="Revenue", formula="SUM([Sales])", guid="lf1")
        builder = (
            _factory.flat_table(name="Chart", location=_loc())
            .dataset(ds)
            .add_local_field(revenue)
            .columns(["dim", revenue])
        )
        data = _build(builder)
        items = _items_in_ph(data, "flat-table-columns")
        lf_item = next(it for it in items if it.get("guid") == "lf1")
        assert lf_item.get("datasetId") == "ds1"

    def test_add_aggregated_measure_preserves_avatar_id(self) -> None:
        avatar_field = DatasetField(
            guid="dim-guid",
            title="Dim",
            name="dim",
            calc_mode="direct",
            data_type="string",
            type="DIMENSION",
            aggregation="",
            cast="string",
            source="dim-src",
            avatar_id="avatar-42",
        )
        ds = Dataset(
            id="ds1",
            name="Chart",
            location=_loc(),
            result_schema=(
                {
                    "guid": "dim-guid",
                    "title": "Dim",
                    "calc_mode": "direct",
                    "data_type": "string",
                    "type": "DIMENSION",
                    "aggregation": "",
                    "cast": "string",
                    "source": "dim-src",
                    "avatar_id": "avatar-42",
                },
            ),
        )
        builder = (
            _factory.line(name="Chart", location=_loc())
            .dataset(ds)
            .add_aggregated_measure(
                WizardAggregatedMeasure(
                    field=avatar_field,
                    aggregation="countunique",
                    title="Unique dimensions",
                )
            )
        )
        data = _build(builder)
        updates = _source_items(data, "updates")
        assert len(updates) == 1
        field = cast(dict[str, Any], updates[0]["field"])
        assert field.get("avatar_id") == "avatar-42"
        assert field.get("source") == "dim-src"
