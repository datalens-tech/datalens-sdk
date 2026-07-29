from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation

_REFERENCE_CHARTS_DIR = Path(__file__).parent / "fixtures" / "reference_charts" / "wizard"


def _reference_chart(chart_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REFERENCE_CHARTS_DIR / f"{chart_id}.json").read_text()))


def _dataset() -> Dataset:
    return Dataset(
        id="dataset-id",
        name="dataset",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "date", "title": "Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
            {
                "guid": "dimension",
                "title": "Dimension",
                "type": "DIMENSION",
                "data_type": "string",
                "calc_mode": "direct",
            },
            {"guid": "measure-1", "title": "Measure 1", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "measure-2", "title": "Measure 2", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ),
    )


def _payload(builder: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload())


def _payload_data(builder: Any) -> dict[str, Any]:
    return cast(dict[str, Any], _payload(builder)["data"])


def _placeholder(data: dict[str, Any], placeholder_id: str) -> dict[str, Any]:
    return next(item for item in data["visualization"]["placeholders"] if item["id"] == placeholder_id)


def _first_item(data: dict[str, Any], placeholder_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], _placeholder(data, placeholder_id)["items"][0])


def _reference_item_with_key(reference: dict[str, Any], key: str) -> dict[str, Any]:
    for placeholder in reference["data"]["visualization"].get("placeholders", []):
        for item in placeholder.get("items", []):
            if key in item:
                return cast(dict[str, Any], item)
    raise AssertionError(f"Reference fixture has no item with {key}")


def _reference_interval(reference: dict[str, Any]) -> str:
    for filter_item in reference["data"]["filters"]:
        values = filter_item["filter"]["value"]
        for value in values:
            if isinstance(value, str) and value.startswith("__interval_"):
                return value
    raise AssertionError("Reference fixture has no interval filter")


def _factory() -> WizardChartCreateFactory:
    return WizardChartCreateFactory(cast(Any, None))


def _assert_pagination(reference: dict[str, Any]) -> None:
    extra = reference["data"]["extraSettings"]
    assert set(extra) == {"limit", "pagination"}
    assert extra["pagination"] in {"on", "off"}
    assert isinstance(extra["limit"], int)
    data = _payload_data(
        _factory()
        .flat_table(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .pagination(enabled=True, limit=20)
    )
    assert data["extraSettings"] == {"pagination": "on", "limit": 20}


def _assert_table_size(reference: dict[str, Any]) -> None:
    extra = reference["data"]["extraSettings"]
    assert extra["size"] in {"s", "m", "l"}
    data = _payload_data(
        _factory().flat_table(name="chart", location=EntryLocation.path("/")).dataset(_dataset()).table_size(size="s")
    )
    assert data["extraSettings"]["size"] == "s"


def _assert_table_bars(reference: dict[str, Any]) -> None:
    bars = _reference_item_with_key(reference, "barsSettings")["barsSettings"]
    assert set(bars) == {"align", "colorSettings", "enabled", "scale", "showBarsInTotals", "showLabels"}
    assert bars["align"] in {"default", "left", "right"}
    assert bars["colorSettings"]["colorType"] in {"one-color", "two-color", "gradient"}
    assert bars["scale"]["mode"] == "auto"
    data = _payload_data(
        _factory()
        .pivot_table(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .columns(["Measure 1"])
        .column_bars(
            "Measure 1",
            color_type="gradient",
            gradient_palette="red-orange-green",
            gradient_type="3-point",
        )
    )
    produced = _first_item(data, "pivot-table-columns")["barsSettings"]
    assert set(produced) == set(bars)
    assert produced["colorSettings"]["colorType"] == "gradient"
    assert produced["scale"] == {"mode": "auto"}


def _assert_pivot_background_and_subtotals(reference: dict[str, Any]) -> None:
    background = _reference_item_with_key(reference, "backgroundSettings")["backgroundSettings"]
    assert set(background) == {"colorFieldGuid", "enabled", "settings", "settingsId"}
    assert {"gradientState", "isContinuous", "paletteState"} <= set(background["settings"])
    gradient = background["settings"]["gradientState"]
    assert set(gradient) <= {
        "gradientMode",
        "gradientPalette",
        "leftThreshold",
        "middleThreshold",
        "reversed",
        "rightThreshold",
        "thresholdsMode",
    }
    subtotal_item = next(
        item
        for placeholder in reference["data"]["visualization"]["placeholders"]
        for item in placeholder.get("items", [])
        if "subTotalsSettings" in item
    )
    assert subtotal_item["subTotalsSettings"]["enabled"] in {True, False}
    data = _payload_data(
        _factory()
        .pivot_table(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .columns(["Measure 1"])
        .column_background("Measure 1", mode="2-point", palette="blue")
        .subtotals("Measure 1", enabled=True)
    )
    produced = _first_item(data, "pivot-table-columns")
    assert set(produced["backgroundSettings"]) == set(background)
    assert produced["backgroundSettings"]["colorFieldGuid"] == "measure-1"
    assert produced["subTotalsSettings"] == {"enabled": True}


def _assert_line_axes(reference: dict[str, Any]) -> None:
    settings = next(
        placeholder["settings"]
        for placeholder in reference["data"]["visualization"]["placeholders"]
        if {"type", "scale", "scaleValue", "title", "titleValue"} <= set(placeholder.get("settings", {}))
    )
    assert settings["type"] in {"linear", "logarithmic"}
    assert settings["scale"] in {"auto", "manual"}
    assert isinstance(settings["scaleValue"], list)
    assert isinstance(settings["title"], str)
    data = _payload_data(
        _factory()
        .line(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .x(["Date"])
        .y(["Measure 1"])
        .axis_scale("y", scale="logarithmic", mode="manual", min="0.001", max="100")
        .axis_title("y", mode="manual", text="Revenue")
    )
    produced = _placeholder(data, "y")["settings"]
    assert {"type", "scale", "scaleValue", "title", "titleValue"} <= set(produced)


def _assert_palette(reference: dict[str, Any]) -> None:
    colors_config = reference["data"]["colorsConfig"]
    assert set(colors_config) == {"coloredByMeasure", "fieldGuid", "mountedColors", "palette", "polygonBorders"}
    assert isinstance(colors_config["palette"], str)
    assert "paletteId" not in colors_config
    data = _payload_data(
        _factory()
        .pie(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .x(["Dimension"])
        .y(["Measure 1"])
        .color_by_dimension("Dimension")
        .palette(id="taxi9")
    )
    assert "palette" in data["colorsConfig"]
    assert "paletteId" not in data["colorsConfig"]


def _assert_rgba_colors_and_description(reference: dict[str, Any]) -> None:
    mounted_colors = reference["data"]["colorsConfig"]["mountedColors"]
    assert any(
        isinstance(value, str) and len(value) == 9 and value.startswith("#") for value in mounted_colors.values()
    )
    assert set(reference["annotation"]) == {"description"}
    payload = _payload(
        _factory()
        .column(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .x(["Dimension"])
        .y(["Measure 1", "Measure 2"])
        .color_by_measure_name(colors_map={"Measure 2": "#4DA256FF"})
        .description("Structural contract")
    )
    assert payload["data"]["colorsConfig"]["mountedColors"]["Measure 2"] == "#4DA256FF"
    assert payload["data"]["colorsConfig"]["colorMode"] == "palette"
    assert payload["annotation"] == {"description": "Structural contract"}


def _assert_column_multi_measure(reference: dict[str, Any]) -> None:
    config = reference["data"]["colorsConfig"]
    assert set(config) == {"colorMode", "coloredByMeasure", "mountedColors", "palette", "polygonBorders"}
    assert config["coloredByMeasure"] is True
    assert config["colorMode"] == "palette"
    assert config["palette"] == ""
    assert any(item.get("type") == "PSEUDO" for item in reference["data"]["colors"])
    data = _payload_data(
        _factory()
        .column(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .x(["Dimension"])
        .y(["Measure 1", "Measure 2"])
        .color_by_measure_name()
    )
    assert {"colorMode", "coloredByMeasure", "mountedColors", "polygonBorders"} <= set(data["colorsConfig"])
    assert any(item.get("type") == "PSEUDO" for item in data["colors"])


def _assert_indicator(reference: dict[str, Any]) -> None:
    extra = reference["data"]["extraSettings"]
    assert extra["metricFontSize"] in {"xs", "s", "m", "l", "xl"}
    assert extra["indicatorTitleMode"] in {"by-field", "manual", "hide"}
    data = _payload_data(
        _factory()
        .indicator(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .y(["Measure 1"])
        .font_size(size="l")
        .font_color(color="#FF4444")
        .measure_title_mode(mode="manual")
    )
    assert data["extraSettings"] == {
        "metricFontSize": "xl",
        "metricFontColor": "#FF4444",
        "indicatorTitleMode": "manual",
    }


def _assert_combined(reference: dict[str, Any]) -> None:
    visualization = reference["data"]["visualization"]
    layers = visualization["layers"]
    assert len(layers) == 2
    assert isinstance(visualization["selectedLayerId"], str)
    for layer in layers:
        config = layer["commonPlaceholders"]["colorsConfig"]
        assert set(config) == {
            "colorMode",
            "coloredByMeasure",
            "fieldGuid",
            "mountedColors",
            "palette",
            "polygonBorders",
        }
        assert config["coloredByMeasure"] is True
    assert _reference_interval(reference).startswith("__interval_")
    data = _payload_data(
        _factory()
        .combined_chart(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .x(["Date"])
        .add_layer("column", y="Measure 1")
        .add_layer("line", y2="Measure 2")
        .add_date_filter("Date", start="2026-01-01", end="2026-05-11")
    )
    produced_layers = data["visualization"]["layers"]
    assert len(produced_layers) == 2
    assert data["visualization"]["selectedLayerId"] == produced_layers[-1]["layerSettings"]["id"]
    assert all(
        set(layer["commonPlaceholders"]["colorsConfig"])
        == {"colorMode", "coloredByMeasure", "fieldGuid", "mountedColors", "palette", "polygonBorders"}
        for layer in produced_layers
    )
    assert data["filters"][0]["filter"]["value"][0] == "__interval_2026-01-01T00:00:00.000Z_2026-05-11T23:59:59.999Z"


def _assert_geo_heatmap(reference: dict[str, Any]) -> None:
    visualization = reference["data"]["visualization"]
    assert len(visualization["layers"]) == 1
    common = visualization["layers"][0]["commonPlaceholders"]
    assert set(common) == {
        "colors",
        "colorsConfig",
        "filters",
        "geopointsConfig",
        "labels",
        "segments",
        "shapes",
        "shapesConfig",
        "sort",
        "tooltips",
    }
    data = _payload_data(
        _factory()
        .geolayer(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .add_layer("heatmap", geopoint="Dimension", color="Measure 1")
    )
    layer = data["visualization"]["layers"][0]
    assert layer["id"] == "heatmap"
    assert set(layer["commonPlaceholders"]) == set(common)
    assert data["visualization"]["selectedLayerId"] == layer["layerSettings"]["id"]


def _assert_relative_interval(reference: dict[str, Any]) -> None:
    interval = _reference_interval(reference)
    assert interval.startswith("__interval___relative_")
    data = _payload_data(
        _factory()
        .pie(name="chart", location=EntryLocation.path("/"))
        .dataset(_dataset())
        .add_relative_date_filter("Date", start_offset="-1M", end_offset="-0d")
    )
    assert data["filters"][0]["filter"]["value"] == [interval]


_REFERENCE_SCENARIOS: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
    ("6lul1r2vkr5kq", _assert_pagination),
    ("iw14j1bzsvf02", _assert_table_size),
    ("5ktk0gab36rip", _assert_pivot_background_and_subtotals),
    ("vajaiz1nh2daf", _assert_line_axes),
    ("ydmdqvu9s34si", _assert_palette),
    ("vajai7xrxaa6f", _assert_column_multi_measure),
    ("n1zb75lpkoq27", _assert_rgba_colors_and_description),
    ("p4d4ls7744xi9", _assert_indicator),
    ("7mv82x84lga6r", _assert_indicator),
    ("p4dqkd01l3ty9", _assert_indicator),
    ("zenewka5dvwij", _assert_combined),
    ("35prkj7b9xnun", _assert_geo_heatmap),
    ("kz8zd49v19704", _assert_relative_interval),
    ("lz47d8gnsa4q5", _assert_table_bars),
    ("guz2i7a315cg0", _assert_table_bars),
)


@pytest.mark.parametrize(
    ("chart_id", "assert_shape"), _REFERENCE_SCENARIOS, ids=[scenario[0] for scenario in _REFERENCE_SCENARIOS]
)
def test_reference_chart_shapes(chart_id: str, assert_shape: Callable[[dict[str, Any]], None]) -> None:
    """Locks 15 safe live scenarios; snh82x2nbnx8k is excluded because map settings are unconfirmed."""
    assert_shape(_reference_chart(chart_id))
