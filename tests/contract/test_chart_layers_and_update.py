from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import pytest

from datalens_sdk import GeoLayerFilter
from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._runtime.wizard_semantics import WIZARD_GEO_LAYER_SEMANTICS
from datalens_sdk.api.chart import ChartAPI, ChartService
from datalens_sdk.api.entries import EntriesAPI, EntriesService
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.chart_types import GradientPaletteId
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.ports import NavigationOperations
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensAPIError, DataLensConfigurationError
from datalens_sdk.http import DataLensHTTPClient

_REFERENCE_CHARTS_DIR = Path(__file__).parent / "fixtures" / "reference_charts" / "wizard"
_PHASE_3B_PENDING = pytest.mark.xfail(
    strict=True,
    reason="Phase 3B: target combined/geolayer serialization is pending",
)


def _reference_chart(chart_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REFERENCE_CHARTS_DIR / f"{chart_id}.json").read_text()))


def _dataset() -> Dataset:
    return Dataset(
        id="ds1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_date", "title": "Order Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "g_reg", "title": "Region", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
            {"guid": "g_point", "title": "Point", "type": "DIMENSION", "data_type": "geopoint", "calc_mode": "direct"},
            {
                "guid": "g_currency",
                "title": "Currency",
                "type": "DIMENSION",
                "data_type": "string",
                "calc_mode": "direct",
            },
        ),
    )


def _payload_data(builder: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])


def test_combined_live_fixture_has_complete_per_layer_colors_config() -> None:
    fixture = _reference_chart("zenewka5dvwij")
    layers = cast(list[dict[str, Any]], fixture["data"]["visualization"]["layers"])
    expected_keys = {"colorMode", "coloredByMeasure", "fieldGuid", "mountedColors", "palette", "polygonBorders"}
    assert all(set(layer["commonPlaceholders"]["colorsConfig"]) == expected_keys for layer in layers)


@_PHASE_3B_PENDING
def test_combined_builds_layers_with_shared_x_and_measure_colors() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.combined_chart(name="C", location=EntryLocation.path("/F")).dataset(dataset)
    builder.x(["Order Date"]).add_layer("column", y="Amount").add_layer("line", y2="Amount", name="Trend")
    data = _payload_data(builder)
    viz = data["visualization"]
    assert viz["id"] == "combined-chart"
    assert viz["placeholders"] == []
    layers = viz["layers"]
    assert [layer["id"] for layer in layers] == ["column", "line"]
    assert layers[1]["layerSettings"]["name"] == "Trend"
    assert viz["selectedLayerId"] == layers[-1]["layerSettings"]["id"]
    for layer in layers:
        x_ph = next(p for p in layer["placeholders"] if p["id"] == "x")
        assert x_ph["items"][0]["guid"] == "g_date"
    column_y = next(p for p in layers[0]["placeholders"] if p["id"] == "y")
    line_y2 = next(p for p in layers[1]["placeholders"] if p["id"] == "y2")
    assert column_y["items"][0]["guid"] == "g_amt"
    assert line_y2["items"][0]["guid"] == "g_amt"
    assert layers[0]["commonPlaceholders"]["colorsConfig"] == {
        "colorMode": "palette",
        "coloredByMeasure": True,
        "fieldGuid": "g_amt",
        "mountedColors": {"Amount": "0"},
        "palette": "",
        "polygonBorders": "show",
    }


@_PHASE_3B_PENDING
def test_combined_layers_get_distinct_palette_indices() -> None:
    """Distinct measures across layers map to distinct palette indices.

    Regression for the per-layer ``enumerate`` that mapped every single-measure
    layer to palette index 0 -> all layers rendered in the same color.
    """
    dataset = Dataset(
        id="ds1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_date", "title": "Order Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "g_qty", "title": "Quantity", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ),
    )
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.combined_chart(name="C", location=EntryLocation.path("/F")).dataset(dataset)
    builder.x(["Order Date"]).add_layer("column", y="Amount").add_layer("line", y2="Quantity", name="Trend")
    data = _payload_data(builder)
    layers = data["visualization"]["layers"]
    assert layers[0]["commonPlaceholders"]["colorsConfig"]["mountedColors"] == {"Amount": "0"}
    assert layers[1]["commonPlaceholders"]["colorsConfig"]["mountedColors"] == {"Quantity": "1"}


@_PHASE_3B_PENDING
def test_combined_measure_format_reaches_layer_placeholders() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    amount = dataset.fields.by_name("Amount")
    builder = cast(
        Any,
        factory.combined_chart(name="C", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Order Date"])
        .add_layer("column", y=amount),
    )
    builder.measure_format(amount, precision=2, unit="k")

    layer = _payload_data(builder)["visualization"]["layers"][0]
    amount_item = next(
        item
        for placeholder in layer["placeholders"]
        for item in placeholder["items"]
        if item.get("guid") == amount.guid
    )
    assert amount_item["formatting"] == {"precision": 2, "unit": "k"}


@_PHASE_3B_PENDING
def test_combined_update_x_reaches_every_layer() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.combined_chart(name="C", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Order Date"])
        .add_layer("column", y="Amount")
        .add_layer("line", y2="Amount")
    )
    chart = WizardChartConverter.to_domain(
        {"entryId": "chart-1", "data": _payload_data(builder)},
        installation="yacloud",
    )

    payload = WizardChartConverter.from_domain_update(chart.update.x([dataset.fields.by_name("Region")])).to_payload()
    layers = cast(dict[str, Any], payload["data"])["visualization"]["layers"]
    assert all(
        next(placeholder for placeholder in layer["placeholders"] if placeholder["id"] == "x")["items"][0]["guid"]
        == "g_reg"
        for layer in layers
    )


def test_combined_add_layer_requires_measure() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.combined_chart(name="C", location=EntryLocation.path("/F"))
    with pytest.raises(Exception, match="requires at least one"):
        builder.add_layer("line")


def test_geolayer_live_heatmap_fixture_has_confirmed_common_placeholders() -> None:
    fixture = _reference_chart("35prkj7b9xnun")
    layer = fixture["data"]["visualization"]["layers"][0]
    assert set(layer["commonPlaceholders"]) == {
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


@_PHASE_3B_PENDING
def test_geolayer_builds_layers_with_layer_local_fields() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(dataset)
    builder.add_layer("geopoint", geopoint="Region", color="Amount", tooltips=["Order Date"], labels=["Region"])
    data = _payload_data(builder)
    viz = data["visualization"]
    assert viz["id"] == "geolayer"
    assert viz["placeholders"] == []
    layers = viz["layers"]
    assert len(layers) == 1
    layer = layers[0]
    assert layer["id"] == "geopoint"
    assert layer["layerSettings"]["name"] == "Layer 1"
    assert viz["selectedLayerId"] == layer["layerSettings"]["id"]
    geopoint_ph = next(p for p in layer["placeholders"] if p["id"] == "geopoint")
    assert geopoint_ph["items"][0]["guid"] == "g_reg"
    common = layer["commonPlaceholders"]
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
    assert common["colors"][0]["guid"] == "g_amt"
    assert common["tooltips"][0]["guid"] == "g_date"
    assert common["labels"][0]["guid"] == "g_reg"
    assert common["labels"][0]["mode"] == "absolute"
    assert {key: data[key] for key in common if key != "filters"} == {
        key: value for key, value in common.items() if key != "filters"
    }
    assert data["filters"] == []


@_PHASE_3B_PENDING
def test_geolayer_generic_labels_and_tooltips_update_selected_layer() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(
        Any,
        builder.add_layer(
            "geopoint",
            geopoint="Point",
            labels=["Region"],
            tooltips=["Order Date"],
        ).labels(["Amount"]),
    ).tooltips(["Currency"])

    data = _payload_data(builder)
    common = data["visualization"]["layers"][0]["commonPlaceholders"]
    assert [(item["guid"], item["mode"]) for item in common["labels"]] == [("g_amt", "absolute")]
    assert [item["guid"] for item in common["tooltips"]] == ["g_currency"]
    assert data["labels"] == common["labels"]
    assert data["tooltips"] == common["tooltips"]


@_PHASE_3B_PENDING
def test_geolayer_measure_format_updates_layer_and_root_labels() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(Any, builder.add_layer("geopoint", geopoint="Point", labels=["Amount"])).measure_format(
        "Amount",
        format="number",
        prefix="$",
    )

    data = _payload_data(builder)
    common = data["visualization"]["layers"][0]["commonPlaceholders"]
    assert common["labels"][0]["formatting"] == {"format": "number", "prefix": "$"}
    assert data["labels"] == common["labels"]


@pytest.mark.parametrize(
    ("layer_type", "geometry", "method_name"),
    [
        ("geopolygon", {"polygon": "Region"}, "labels"),
        ("heatmap", {"geopoint": "Point"}, "tooltips"),
    ],
)
def test_geolayer_generic_fields_reject_unsupported_selected_layer(
    layer_type: str,
    geometry: dict[str, str],
    method_name: str,
) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    with pytest.raises(DataLensConfigurationError, match=rf"does not support {method_name}"):
        cast(Any, builder).add_layer(layer_type, **geometry, **{method_name: ["Amount"]})


@pytest.mark.parametrize(
    ("layer_type", "field_argument", "field_name", "placeholder_id"),
    [
        ("geopoint", "geopoint", "Point", "geopoint"),
        ("geopoint-with-cluster", "geopoint", "Point", "geopoint"),
        ("heatmap", "geopoint", "Point", "heatmap"),
        ("geopolygon", "polygon", "Region", "geopolygon"),
        ("polyline", "polyline", "Region", "polyline"),
    ],
)
@_PHASE_3B_PENDING
def test_geolayer_supports_each_layer_type(
    layer_type: str,
    field_argument: str,
    field_name: str,
    placeholder_id: str,
) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(Any, builder).add_layer(layer_type, **{field_argument: field_name})
    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    assert layer["id"] == layer_type
    placeholder = next(item for item in layer["placeholders"] if item["id"] == placeholder_id)
    expected_guid = "g_point" if field_name == "Point" else "g_reg"
    assert placeholder["items"][0]["guid"] == expected_guid


@_PHASE_3B_PENDING
def test_polyline_builds_live_reference_grouping_color_and_sort_contract() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer(
        "polyline",
        polyline="Point",
        grouping="Region",
        color="Amount",
        color_mode="3-point",
        color_palette="red-orange-green",
        color_reversed=False,
        sort_by="Order Date",
    )

    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    placeholders = {placeholder["id"]: placeholder for placeholder in layer["placeholders"]}
    assert [item["guid"] for item in placeholders["polyline"]["items"]] == ["g_point"]
    assert placeholders["polyline"]["settings"] == {"polylinePoints": "off"}
    assert placeholders["measures"]["items"] == []
    assert [item["guid"] for item in placeholders["grouping"]["items"]] == ["g_reg"]
    common = layer["commonPlaceholders"]
    assert set(common) == {
        "colors",
        "colorsConfig",
        "filters",
        "geopointsConfig",
        "labels",
        "sort",
        "tooltips",
    }
    assert [item["guid"] for item in common["colors"]] == ["g_amt"]
    assert common["colorsConfig"] == {
        "gradientMode": "3-point",
        "gradientPalette": "red-orange-green",
        "polygonBorders": "show",
        "reversed": False,
        "thresholdsMode": "auto",
    }
    assert common["sort"] == [
        {
            "guid": "g_date",
            "datasetId": "ds1",
            "datasetName": "sales",
            "data_type": "date",
            "id": "dimension-0",
            "title": "Order Date",
            "type": "DIMENSION",
            "calc_mode": "direct",
            "direction": "ASC",
        }
    ]
    assert data["colors"] == common["colors"]
    assert data["colorsConfig"] == common["colorsConfig"]
    assert data["sort"] == common["sort"]
    assert "segments" not in data
    assert "allowedFinalTypes" in placeholders["measures"]
    assert "allowedDataTypes" not in placeholders["measures"]


@pytest.mark.parametrize(
    "layer_type",
    ["geopoint", "geopoint-with-cluster", "heatmap", "geopolygon"],
)
@_PHASE_3B_PENDING
def test_non_polyline_geo_layers_keep_their_live_common_placeholder_contract(layer_type: str) -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(dataset)
    argument = "polygon" if layer_type == "geopolygon" else "geopoint"
    field = "Region" if layer_type == "geopolygon" else "Point"
    cast(Any, builder).add_layer(layer_type, **{argument: field})

    data = _payload_data(builder)
    common = data["visualization"]["layers"][0]["commonPlaceholders"]
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
    assert data["segments"] == []


_GEO_LAYER_GEOMETRY: dict[str, dict[str, str]] = {
    "geopoint": {"geopoint": "Point"},
    "geopoint-with-cluster": {"geopoint": "Point"},
    "heatmap": {"geopoint": "Point"},
    "geopolygon": {"polygon": "Region"},
    "polyline": {"polyline": "Point"},
}


def _unsupported_geo_layer_inputs() -> list[tuple[str, str, object]]:
    input_values: dict[str, object] = {
        "geopoint": "Point",
        "polygon": "Region",
        "polyline": "Point",
        "size": "Amount",
        "grouping": "Region",
        "color": "Amount",
        "filters": [GeoLayerFilter(field="Region", operation="IN", values=["North"])],
        "labels": ["Amount"],
        "tooltips": ["Amount"],
        "sort_by": "Order Date",
    }
    cases: list[tuple[str, str, object]] = []
    for layer_type in _GEO_LAYER_GEOMETRY:
        supported_inputs = set(WIZARD_GEO_LAYER_SEMANTICS[layer_type]["supported_inputs"])
        cases.extend(
            (layer_type, argument, value)
            for argument, value in input_values.items()
            if argument not in supported_inputs
        )
    return cases


@pytest.mark.parametrize(("layer_type", "argument", "value"), _unsupported_geo_layer_inputs())
def test_geolayer_rejects_unsupported_layer_inputs(layer_type: str, argument: str, value: object) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    kwargs: dict[str, object] = {**_GEO_LAYER_GEOMETRY[layer_type], argument: value}
    with pytest.raises(DataLensConfigurationError, match=argument):
        cast(Any, builder).add_layer(layer_type, **kwargs)


@pytest.mark.parametrize(("layer_type", "geometry"), _GEO_LAYER_GEOMETRY.items())
def test_geolayer_rejects_sort_direction_without_sort_by(layer_type: str, geometry: dict[str, str]) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    with pytest.raises(DataLensConfigurationError, match="sort_direction"):
        cast(Any, builder).add_layer(layer_type, **geometry, sort_direction="desc")


@_PHASE_3B_PENDING
def test_geolayer_builds_confirmed_mixed_heatmap_and_cluster_topology() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer("heatmap", geopoint="Point", name="Density").add_layer(
        "geopoint-with-cluster",
        geopoint="Point",
        name="Clusters",
    )

    visualization = _payload_data(builder)["visualization"]
    assert [layer["id"] for layer in visualization["layers"]] == ["heatmap", "geopoint-with-cluster"]
    assert [layer["layerSettings"]["type"] for layer in visualization["layers"]] == [
        "heatmap",
        "geopoint-with-cluster",
    ]
    assert [placeholder["id"] for placeholder in visualization["layers"][0]["placeholders"]] == ["heatmap"]
    assert [placeholder["id"] for placeholder in visualization["layers"][1]["placeholders"]] == [
        "geopoint",
        "size",
    ]
    assert visualization["selectedLayerId"] == visualization["layers"][1]["layerSettings"]["id"]


@_PHASE_3B_PENDING
def test_geolayer_builds_chart_level_filters_from_confirmed_reference_shape() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.geolayer(name="G", location=EntryLocation.path("/F"))
        .dataset(_dataset())
        .add_filter("Region", operation="IN", values=["North"])
        .add_relative_date_filter("Order Date", start_offset="-1d", end_offset="-0d")
        .add_layer("geopoint", geopoint="Point")
    )

    filters = _payload_data(builder)["filters"]
    assert [item["filter"]["operation"]["code"] for item in filters] == ["IN", "BETWEEN"]
    assert filters[0]["filter"]["value"] == ["North"]
    assert filters[1]["filter"]["value"] == ["__interval___relative_-1d___relative_-0d"]


@pytest.mark.parametrize(
    ("layer_type", "geometry"),
    [
        ("geopoint", {"geopoint": "Point"}),
        ("geopoint-with-cluster", {"geopoint": "Point"}),
        ("heatmap", {"geopoint": "Point"}),
        ("geopolygon", {"polygon": "Region"}),
        ("polyline", {"polyline": "Region"}),
    ],
)
@_PHASE_3B_PENDING
def test_geolayer_builds_layer_local_filters_for_every_layer_type(
    layer_type: str,
    geometry: dict[str, str],
) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(Any, builder).add_layer(
        layer_type,
        **geometry,
        filters=[GeoLayerFilter(field="Currency", operation="IN", values=["RUB"])],
    )

    data = _payload_data(builder)
    assert data["filters"] == []
    layer_filter = data["visualization"]["layers"][0]["commonPlaceholders"]["filters"][0]
    assert layer_filter == {
        "calc_mode": "direct",
        "datasetId": "ds1",
        "datasetName": "sales",
        "data_type": "string",
        "filter": {"operation": {"code": "IN"}, "value": ["RUB"]},
        "guid": "g_currency",
        "id": "dimension-0",
        "title": "Currency",
        "type": "DIMENSION",
    }


@_PHASE_3B_PENDING
def test_geopolygon_builds_live_reference_gradient_contract() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer(
        "geopolygon",
        polygon="Region",
        color="Amount",
        color_mode="2-point",
        color_palette="orange-yellow",
        color_reversed=True,
    )

    common = _payload_data(builder)["visualization"]["layers"][0]["commonPlaceholders"]
    assert common["colors"][0]["guid"] == "g_amt"
    assert common["colorsConfig"] == {
        "colorMode": "gradient",
        "gradientMode": "2-point",
        "gradientPalette": "orange-yellow",
        "polygonBorders": "show",
        "reversed": True,
        "thresholdsMode": "auto",
    }


@pytest.mark.parametrize(
    ("palette", "expected_mode"),
    [
        ("orange-yellow", "2-point"),
        ("orange-gray-blue", "3-point"),
    ],
)
@_PHASE_3B_PENDING
def test_geolayer_infers_gradient_mode_from_palette(
    palette: GradientPaletteId,
    expected_mode: Literal["2-point", "3-point"],
) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer(
        "geopolygon",
        polygon="Region",
        color="Amount",
        color_palette=palette,
    )

    data = _payload_data(builder)
    common = data["visualization"]["layers"][0]["commonPlaceholders"]
    assert common["colorsConfig"]["gradientMode"] == expected_mode
    assert data["colorsConfig"] == common["colorsConfig"]


@pytest.mark.parametrize(
    "gradient_settings",
    [
        {"color_mode": "2-point"},
        {"color_palette": "orange-yellow"},
        {"color_reversed": False},
    ],
)
def test_geolayer_rejects_gradient_settings_for_dimension_color(
    gradient_settings: dict[str, object],
) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    with pytest.raises(DataLensConfigurationError, match="requires a MEASURE"):
        cast(Any, builder).add_layer(
            "geopoint",
            geopoint="Point",
            color="Region",
            **gradient_settings,
        )


@_PHASE_3B_PENDING
def test_geolayer_accepts_dimension_color_without_gradient_settings() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer("geopoint", geopoint="Point", color="Region")

    common = _payload_data(builder)["visualization"]["layers"][0]["commonPlaceholders"]
    assert [(item["guid"], item["type"]) for item in common["colors"]] == [("g_reg", "DIMENSION")]
    assert common["colorsConfig"] == {}


@_PHASE_3B_PENDING
def test_geopoint_builds_all_live_reference_field_sections() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_filter("Region", operation="IN", values=["North"]).add_layer(
        "geopoint",
        geopoint="Point",
        size="Amount",
        color="Amount",
        color_mode="3-point",
        color_palette="orange-gray-blue",
        color_reversed=False,
        filters=[GeoLayerFilter(field="Currency", operation="IN", values=["RUB"])],
        tooltips=["Amount"],
        labels=["Amount"],
    )

    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    size = next(placeholder for placeholder in layer["placeholders"] if placeholder["id"] == "size")["items"]
    common = layer["commonPlaceholders"]
    assert [item["guid"] for item in size] == ["g_amt"]
    assert [item["guid"] for item in common["colors"]] == ["g_amt"]
    assert [item["guid"] for item in common["tooltips"]] == ["g_amt"]
    assert [(item["guid"], item["mode"]) for item in common["labels"]] == [("g_amt", "absolute")]
    assert data["colors"] == common["colors"]
    assert data["colorsConfig"] == common["colorsConfig"]
    assert data["labels"] == common["labels"]
    assert data["tooltips"] == common["tooltips"]
    assert [item["guid"] for item in data["filters"]] == ["g_reg"]
    assert [item["guid"] for item in common["filters"]] == ["g_currency"]


def test_geolayer_gradient_settings_require_color() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F"))
    with pytest.raises(DataLensConfigurationError, match="require color"):
        builder.add_layer("geopolygon", polygon="Region", color_palette="orange-yellow")


def test_geolayer_rejects_unknown_gradient_palette_without_mode() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F"))
    with pytest.raises(DataLensConfigurationError, match="color_palette"):
        cast(Any, builder).add_layer(
            "geopolygon",
            polygon="Region",
            color="Amount",
            color_palette="unknown",
        )


def test_geolayer_rejects_unknown_gradient_mode_without_palette() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F"))
    with pytest.raises(DataLensConfigurationError, match="color_mode"):
        cast(Any, builder).add_layer(
            "geopolygon",
            polygon="Region",
            color="Amount",
            color_mode="4-point",
        )


def test_geolayer_rejects_incompatible_gradient_mode_and_palette() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F"))
    with pytest.raises(DataLensConfigurationError, match="does not support"):
        builder.add_layer(
            "geopolygon",
            polygon="Region",
            color="Amount",
            color_mode="3-point",
            color_palette="orange-yellow",
        )


@_PHASE_3B_PENDING
def test_geolayer_adds_multiple_datasets() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    secondary = Dataset(
        id="ds2",
        name="secondary",
        location=EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_secondary", "title": "Secondary region", "type": "DIMENSION", "data_type": "string"},
        ),
    )
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_dataset(secondary).add_layer("geopoint", geopoint="Secondary region", dataset=secondary)
    data = _payload_data(builder)
    assert data["datasetsIds"] == ["ds1", "ds2"]
    geopoint_ph = data["visualization"]["layers"][0]["placeholders"][0]
    assert geopoint_ph["items"][0]["guid"] == "g_secondary"


@pytest.mark.parametrize(
    ("layer_type", "kwargs", "message"),
    [
        ("geopoint", {}, "geopoint"),
        ("geopoint-with-cluster", {}, "geopoint"),
        ("heatmap", {}, "geopoint"),
        ("geopolygon", {}, "polygon"),
        ("polyline", {}, "polyline"),
    ],
)
def test_geolayer_add_layer_requires_its_geo_field(layer_type: str, kwargs: dict[str, str], message: str) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F"))
    with pytest.raises(Exception, match=message):
        cast(Any, builder).add_layer(layer_type, **kwargs)


def _chart_for_update() -> WizardChart:
    return WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "sources": {"datasetsIds": ["ds1"], "filters": [{"guid": "f1"}, {"guid": "f2"}]},
            "visualization": {
                "type": "line",
                "colors": {"items": []},
                "labels": {"items": []},
                "segments": {"items": []},
                "shapes": {"items": []},
                "sort": {"items": []},
                "x": {"items": [{"guid": "g_date", "datasetId": "ds1"}]},
                "y": {"items": [{"guid": "g_amt", "datasetId": "ds1", "title": "Amount"}]},
                "y2": {"items": []},
            },
        },
    )


def test_update_replace_field_and_delete_field() -> None:
    chart = _chart_for_update()
    replacement = DatasetField(
        guid="g_new",
        title="New date",
        name="New date",
        calc_mode="direct",
        data_type="date",
        type="DIMENSION",
        dataset_id="ds1",
    )
    update = chart.update.replace_field("g_date", replacement).delete_field("g_amt")
    dto = WizardChartConverter.from_domain_update(update)
    data = cast(dict[str, Any], dto.to_payload()["data"])
    x_items = data["visualization"]["x"]["items"]
    y_items = data["visualization"]["y"]["items"]
    assert x_items[0]["guid"] == "g_new"
    assert y_items == []


def test_update_replace_dataset() -> None:
    chart = _chart_for_update()
    update = chart.update.replace_dataset(old="ds1", new="ds2")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert data["sources"]["datasetsIds"] == ["ds2"]
    x_items = data["visualization"]["x"]["items"]
    assert x_items[0]["datasetId"] == "ds2"


def test_update_delete_filter() -> None:
    chart = _chart_for_update()
    update = chart.update.delete_filter("f1")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert [f["guid"] for f in data["sources"]["filters"]] == ["f2"]


def test_update_delete_field_accepts_dataset_field() -> None:
    """``delete_field`` extracts ``.guid`` from a ``DatasetField``."""
    chart = _chart_for_update()
    field = DatasetField(guid="g_amt", title="Amount", name="Amount", calc_mode="direct", dataset_id="ds1")
    update = chart.update.delete_field(field)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    y_items = data["visualization"]["y"]["items"]
    assert y_items == [], "delete_field(DatasetField) must clear y-placeholder items"


def test_update_delete_filter_accepts_dataset_field() -> None:
    """``delete_filter`` extracts ``.guid`` from a ``DatasetField`` (filter guid == field guid)."""
    chart = _chart_for_update()
    field = DatasetField(guid="f1", title="F1", name="F1", calc_mode="direct")
    update = chart.update.delete_filter(field)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert [f["guid"] for f in data["sources"]["filters"]] == ["f2"]


def test_update_replace_field_accepts_dataset_field_pair() -> None:
    """``replace_field`` resolves both args via ``DatasetField.guid``."""
    chart = _chart_for_update()
    old = DatasetField(guid="g_date", title="Order Date", name="Order Date", calc_mode="direct")
    new = DatasetField(guid="g_new", title="New", name="New", calc_mode="direct")
    update = chart.update.replace_field(old, new)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    x_items = data["visualization"]["x"]["items"]
    assert x_items[0]["guid"] == "g_new"


def test_update_replace_formula_accepts_dataset_field() -> None:
    """``replace_formula`` extracts ``.guid`` from a ``DatasetField``."""
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    chart.data["sources"] = dict(cast(dict[str, Any], chart.data["sources"]))
    cast(dict[str, Any], chart.data["sources"])["updates"] = [
        {"action": "add_field", "field": {"guid": "local-field", "formula": "[Revenue]", "local": True}}
    ]
    field = DatasetField(guid="local-field", title="Local", name="Local", calc_mode="formula", formula="[Revenue]")
    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(
            chart.update.replace_formula(field, formula="[Revenue] * 2")
        ).to_payload()["data"],
    )
    assert data["sources"]["updates"][0]["field"]["formula"] == "[Revenue] * 2"


def test_update_structural_ops_resolve_via_chart_fields_proxy() -> None:
    """End-to-end: ``chart.fields.by_guid(...)`` (placed-field FieldsProxy) feeds every structural op."""
    chart = _chart_for_update()
    placed_date = chart.fields.by_guid("g_date")
    placed_amt = chart.fields.by_guid("g_amt")
    assert isinstance(placed_date, DatasetField)
    assert isinstance(placed_amt, DatasetField)
    replaced = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(chart.update.replace_field(placed_date, placed_amt)).to_payload()[
            "data"
        ],
    )
    x_items = replaced["visualization"]["x"]["items"]
    assert x_items[0]["guid"] == "g_amt"

    deleted = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(_chart_for_update().update.delete_field(placed_amt)).to_payload()[
            "data"
        ],
    )
    y_items = deleted["visualization"]["y"]["items"]
    assert y_items == []


def test_chart_fields_surfaces_color_only_field_from_colors_slot() -> None:
    """A field placed only through semantic Color on a cartesian chart lives in
    ``data.colors``. It must still
    be reachable via ``chart.fields.by_name(...)`` so a subsequent
    ``replace_field``/``delete_field`` can target it."""
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    visualization = dict(cast(dict[str, Any], chart.data["visualization"]))
    visualization["colors"] = {
        "items": [{"guid": "g_country", "title": "Country", "type": "DIMENSION", "datasetId": "ds1"}]
    }
    visualization["x"] = {"items": [{"guid": "g_date", "title": "Date", "datasetId": "ds1"}]}
    chart.data["visualization"] = visualization
    country = chart.fields.by_name("Country")
    assert isinstance(country, DatasetField)
    assert country.guid == "g_country"
    assert chart.fields.by_guid("g_date").guid == "g_date"
    assert chart.fields.by_guid("g_amt").guid == "g_amt"


def test_chart_fields_dedups_by_guid_across_named_slots() -> None:
    """A field present both in a placeholder and in ``data.colors`` appears once."""
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    visualization = dict(cast(dict[str, Any], chart.data["visualization"]))
    visualization["colors"] = {"items": [{"guid": "g_amt", "title": "Amount", "type": "MEASURE", "datasetId": "ds1"}]}
    chart.data["visualization"] = visualization
    guids = [f.guid for f in chart.fields]
    assert guids.count("g_amt") == 1


def test_update_placeholder_edit() -> None:
    chart = _chart_for_update()
    update = chart.update.y(["g_amt"]).x(["g_date"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    x_items = data["visualization"]["x"]["items"]
    assert x_items[0]["guid"] == "g_date"


def test_update_mode_validation() -> None:
    chart = _chart_for_update()
    with pytest.raises(Exception, match="mode must be"):
        chart.update.mode(cast(Any, "invalid"))


def test_update_raises_on_conflict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/updateWizardChart":
            return httpx.Response(423, json={"message": "locked"})
        return httpx.Response(404, json={})

    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="2",
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    service = ChartService(
        installation="yacloud",
        api=ChartAPI(client),
        entries_service=EntriesService(api=EntriesAPI(client)),
        navigation_operations=cast(NavigationOperations, object()),
    )
    chart = WizardChart(
        id="chart-1",
        installation="yacloud",
        wire_type="d3_wizard_node",
        data=_chart_for_update().data,
        _operations=service,
    )
    update = chart.update.chart_title(text="Changed")
    with pytest.raises(DataLensAPIError):
        service.update_wizard_chart(update)


# ---------------------------------------------------------------------------
# Regression: stale dataset_id in replace_dataset + add_sort/add_filter
# ---------------------------------------------------------------------------


def _chart_for_replace_dataset_regression() -> WizardChart:
    """Chart with datasetsIds=['ds1'] and a placed field resolvable by DatasetField."""
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    chart.data["sources"] = {"datasetsIds": ["ds1"]}
    visualization = dict(cast(dict[str, Any], chart.data["visualization"]))
    visualization["x"] = {
        "items": [
            {
                "guid": "g_date",
                "title": "Order Date",
                "type": "DIMENSION",
                "data_type": "date",
                "calc_mode": "direct",
                "datasetId": "ds1",
            }
        ]
    }
    visualization["y"] = {
        "items": [
            {
                "guid": "g_amt",
                "title": "Amount",
                "type": "MEASURE",
                "data_type": "float",
                "calc_mode": "direct",
                "datasetId": "ds1",
            }
        ]
    }
    chart.data["visualization"] = visualization
    return chart


def test_replace_dataset_then_add_sort_uses_new_dataset_id() -> None:
    """Regression A-1: replace_dataset + add_sort in one update must produce
    sort items referencing the NEW dataset id, not the stale old one.

    Previously dataset_id was snapshotted before _apply_dataset_replacement so
    _apply_sort_direction_items received the old 'ds1' id, causing a stale
    reference in the final payload even though datasetsIds was already ['ds2'].
    """
    chart = _chart_for_replace_dataset_regression()
    field = DatasetField(
        guid="g_date",
        title="Order Date",
        name="Order Date",
        calc_mode="direct",
        dataset_id="ds1",
    )
    update = chart.update.replace_dataset(old="ds1", new="ds2").add_sort(field)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["sources"]["datasetsIds"] == ["ds2"], "sources.datasetsIds must be updated"
    sort_items = cast(list[dict[str, Any]], data["visualization"]["sort"]["items"])
    assert len(sort_items) == 1, "one sort item expected"
    assert sort_items[0]["datasetId"] == "ds2", "sort item must reference the NEW dataset id after replace_dataset"


def test_replace_dataset_then_add_filter_uses_new_dataset_id() -> None:
    """Regression A-2: replace_dataset + add_filter must reference the new dataset id."""
    chart = _chart_for_replace_dataset_regression()
    field = DatasetField(
        guid="g_amt",
        title="Amount",
        name="Amount",
        calc_mode="direct",
        dataset_id="ds1",
    )
    update = chart.update.replace_dataset(old="ds1", new="ds2").add_filter(field, operation="GT", values=["100"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["sources"]["datasetsIds"] == ["ds2"], "sources.datasetsIds must be updated"
    filters = cast(list[dict[str, Any]], data["sources"].get("filters", []))
    assert len(filters) == 1, "one filter item expected"
    assert filters[0]["datasetId"] == "ds2", "filter item must reference the NEW dataset id after replace_dataset"


def test_replace_dataset_then_add_sort_and_filter_both_use_new_id() -> None:
    """Regression A-3: combined replace_dataset + add_sort + add_filter in one execute."""
    chart = _chart_for_replace_dataset_regression()
    date_field = DatasetField(
        guid="g_date", title="Order Date", name="Order Date", calc_mode="direct", dataset_id="ds1"
    )
    amt_field = DatasetField(guid="g_amt", title="Amount", name="Amount", calc_mode="direct", dataset_id="ds1")
    update = (
        chart.update.replace_dataset(old="ds1", new="ds2")
        .add_sort(date_field)
        .add_filter(amt_field, operation="GT", values=["0"])
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["sources"]["datasetsIds"] == ["ds2"]
    sort_items = cast(list[dict[str, Any]], data["visualization"]["sort"]["items"])
    assert sort_items[0]["datasetId"] == "ds2", "sort must use new dataset id"
    filters = cast(list[dict[str, Any]], data["sources"].get("filters", []))
    assert filters[0]["datasetId"] == "ds2", "filter must use new dataset id"


def test_replace_dataset_then_add_hierarchy_uses_new_dataset_id() -> None:
    chart = _chart_for_replace_dataset_regression()

    update = chart.update.replace_dataset(old="ds1", new="ds2").add_hierarchy(
        "Date hierarchy",
        ["g_date"],
        guid="h-date",
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["sources"]["hierarchies"][0]["fields"][0]["datasetId"] == "ds2"


def test_replace_dataset_then_color_by_dimension_uses_new_dataset_id() -> None:
    chart = _chart_for_replace_dataset_regression()

    update = chart.update.replace_dataset(old="ds1", new="ds2").color_by_dimension("g_date")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["visualization"]["colors"]["items"][0]["datasetId"] == "ds2"


# ---------------------------------------------------------------------------
# Regression: labels([]) must be a no-op (clear labels, no extraSettings side
# effect)
# ---------------------------------------------------------------------------


def _bar_chart_with_labels() -> WizardChart:
    """bar chart that already has labels set."""
    return WizardChart(
        id="chart-2",
        installation="yacloud",
        data={
            "sources": {"datasetsIds": ["ds1"]},
            "visualization": {
                "type": "bar",
                "colors": {"items": []},
                "labels": {"items": [{"guid": "g_amt", "datasetId": "ds1"}]},
                "sort": {"items": []},
                "x": {
                    "items": [
                        {
                            "guid": "g_amt",
                            "title": "Amount",
                            "type": "MEASURE",
                            "data_type": "float",
                            "calc_mode": "direct",
                            "datasetId": "ds1",
                        }
                    ],
                },
                "y": {"items": []},
            },
        },
    )


def test_labels_empty_list_clears_labels_without_labels_position_side_effect() -> None:
    """Regression E3: chart.update.labels([]) must clear labels and must NOT
    trigger _apply_smart_labels_position writing a labelsPosition to extraSettings.

    Previously data_fields_edits with an empty labels list was a no-op (the
    empty normalized result was not written), leaving the old labels in the wire
    payload. _apply_smart_labels_position then fired on those stale labels and
    wrote extraSettings.labelsPosition as an unexpected side effect.
    """
    chart = _bar_chart_with_labels()
    update = chart.update.labels([])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    labels = cast(dict[str, Any], data["visualization"]["labels"])
    assert labels["items"] == [], "labels must be cleared to [] by labels([])"
    assert "labelsPosition" not in cast(dict[str, Any], labels.get("settings", {}))


# ---------------------------------------------------------------------------
# Regression: DatasetField direct constructor with unhashable default_value
# ---------------------------------------------------------------------------


def test_dataset_field_direct_ctor_with_list_default_value_is_hashable() -> None:
    """Regression E4: DatasetField(default_value=[...]) via direct constructor
    must be hashable.  Previously only field_from_mapping applied the coercion;
    direct construction bypassed it, making hash() raise TypeError.
    """
    df = DatasetField(
        guid="g1",
        title="t1",
        name="t1",
        calc_mode="direct",
        default_value=[1, 2, 3],
    )
    assert hash(df) is not None
    overrides: dict[DatasetField, str] = {df: "#color"}
    assert overrides[df] == "#color"


def test_dataset_field_direct_ctor_with_dict_default_value_is_hashable() -> None:
    """Regression E4: DatasetField(default_value={...}) via direct constructor."""
    df = DatasetField(
        guid="g1",
        title="t1",
        name="t1",
        calc_mode="direct",
        default_value={"from": "2025-01-01", "to": "2025-12-31"},
    )
    assert hash(df) is not None
    overrides: dict[DatasetField, str] = {df: "#color"}
    assert overrides[df] == "#color"


def test_update_raises_on_409() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/updateWizardChart":
            return httpx.Response(409, json={"message": "conflict"})
        return httpx.Response(
            200,
            json={
                "entry": {
                    "version": 1,
                    "entryId": "chart-1",
                    "type": "d3_wizard_node",
                    "data": _chart_for_update().data,
                },
            },
        )

    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="2",
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    service = ChartService(
        installation="yacloud",
        api=ChartAPI(client),
        entries_service=EntriesService(api=EntriesAPI(client)),
        navigation_operations=cast(NavigationOperations, object()),
    )
    chart = WizardChart(
        id="chart-1",
        installation="yacloud",
        wire_type="d3_wizard_node",
        data=_chart_for_update().data,
        _operations=service,
    )
    update = chart.update.chart_title(text="Changed")
    with pytest.raises(DataLensAPIError):
        service.update_wizard_chart(update)
