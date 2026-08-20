from __future__ import annotations

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
from datalens_sdk.domain.fields import DatasetField, WizardHierarchy
from datalens_sdk.domain.ports import NavigationOperations
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensAPIError, DataLensConfigurationError
from datalens_sdk.http import DataLensHTTPClient


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


def test_combined_builds_layers_with_shared_x_and_measure_colors() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.combined_chart(name="C", location=EntryLocation.path("/F")).dataset(dataset)
    builder.x(["Order Date"]).add_layer("column", y="Amount").add_layer(
        "line", y2="Amount", name="Trend"
    ).add_date_filter("Order Date", start="2026-01-01", end="2026-05-11")
    data = _payload_data(builder)
    viz = data["visualization"]
    assert viz["type"] == "combined-chart"
    layers = viz["layers"]
    assert [layer["type"] for layer in layers] == ["column", "line"]
    assert layers[1]["layerSettings"]["name"] == "Trend"
    assert viz["selectedLayerId"] == layers[-1]["layerSettings"]["id"]
    for layer in layers:
        assert layer["x"]["items"][0]["guid"] == "g_date"
    assert layers[0]["y"]["items"][0]["guid"] == "g_amt"
    assert layers[1]["y2"]["items"][0]["guid"] == "g_amt"
    assert layers[0]["colors"]["settings"] == {
        "colorMode": "palette",
        "coloredByMeasure": True,
        "mountedColors": {"g_amt": "0"},
        "palette": "datalens-classic-20",
        "polygonBorders": "show",
    }
    assert all(
        set(layer["colors"]["settings"])
        == {"colorMode", "coloredByMeasure", "mountedColors", "palette", "polygonBorders"}
        for layer in layers
    )
    assert data["sources"]["filters"][0]["filter"]["value"] == [
        "__interval_2026-01-01T00:00:00.000Z_2026-05-11T23:59:59.999Z"
    ]


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
    assert layers[0]["colors"]["settings"]["mountedColors"] == {"g_amt": "0"}
    assert layers[1]["colors"]["settings"]["mountedColors"] == {"g_qty": "1"}


def test_combined_measure_format_reaches_layer_slots() -> None:
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
    amount_item = layer["y"]["items"][0]
    assert amount_item["formatting"] == {"precision": 2, "unit": "k"}


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
    chart = WizardChart(id="chart-1", installation="yacloud", data=_payload_data(builder))

    payload = WizardChartConverter.from_domain_update(chart.update.x([dataset.fields.by_name("Region")])).to_payload()
    layers = cast(dict[str, Any], payload["data"])["visualization"]["layers"]
    assert all(layer["x"]["items"][0]["guid"] == "g_reg" for layer in layers)


def test_combined_update_targets_selected_layer_and_preserves_unknown_nested_data() -> None:
    dataset = _dataset()
    builder = (
        WizardChartCreateFactory(cast(Any, None))
        .combined_chart(name="C", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Order Date"])
        .add_layer("line", y="Amount", name="First")
        .add_layer("column", y="Amount", name="Selected")
    )
    data = _payload_data(builder)
    data["visualization"]["layers"][0]["futureLayerField"] = {"keep": True}
    selected_id = data["visualization"]["selectedLayerId"]
    chart = WizardChart(id="chart-1", installation="yacloud", data=data)

    update = (
        chart.update.labels([dataset.fields.by_name("Region")])
        .labels_position(mode="inside")
        .add_sort(dataset.fields.by_name("Order Date"))
    )
    visualization = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])[
        "visualization"
    ]
    layers = visualization["layers"]
    assert [layer["layerSettings"]["name"] for layer in layers] == ["First", "Selected"]
    assert visualization["selectedLayerId"] == selected_id
    assert layers[0]["futureLayerField"] == {"keep": True}
    assert layers[0]["labels"]["items"] == []
    assert layers[1]["labels"]["items"][0]["guid"] == "g_reg"
    assert layers[1]["labels"]["settings"] == {"labelsPosition": "inside"}
    assert layers[1]["sort"]["items"] == [{"guid": "g_date", "datasetId": "ds1", "direction": "ASC"}]


def test_combined_add_layer_requires_measure() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.combined_chart(name="C", location=EntryLocation.path("/F"))
    with pytest.raises(Exception, match="requires at least one"):
        builder.add_layer("line")


def test_geolayer_builds_layers_with_layer_local_fields() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(dataset)
    builder.add_layer("geopoint", geopoint="Region", color="Amount", tooltips=["Order Date"], labels=["Region"])
    data = _payload_data(builder)
    viz = data["visualization"]
    assert viz["type"] == "geolayer"
    layers = viz["layers"]
    assert len(layers) == 1
    layer = layers[0]
    assert layer["type"] == "geopoint"
    assert layer["layerSettings"]["name"] == "Layer 1"
    assert viz["selectedLayerId"] == layer["layerSettings"]["id"]
    assert layer["points"]["items"][0]["guid"] == "g_reg"
    assert layer["colors"]["items"][0]["guid"] == "g_amt"
    assert layer["tooltip"]["items"][0]["guid"] == "g_date"
    assert layer["labels"]["items"][0] == {
        "guid": "g_reg",
        "datasetId": "ds1",
        "formatting": {"labelMode": "absolute"},
    }
    assert "filters" not in data["sources"]


def test_geolayer_generic_labels_update_selected_layer_without_mirroring_tooltip() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer(
        "geopoint",
        geopoint="Point",
        labels=["Region"],
        tooltips=["Order Date"],
    ).labels(["Amount"])

    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    assert [item["guid"] for item in layer["labels"]["items"]] == ["g_amt"]
    assert [item["guid"] for item in layer["tooltip"]["items"]] == ["g_date"]
    assert "labels" not in data["visualization"]
    assert "tooltip" not in data["visualization"]


def test_geolayer_measure_format_updates_layer_labels() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(Any, builder.add_layer("geopoint", geopoint="Point", labels=["Amount"])).measure_format(
        "Amount",
        format="number",
        prefix="$",
    )

    data = _payload_data(builder)
    labels = data["visualization"]["layers"][0]["labels"]["items"]
    assert labels[0]["formatting"] == {"format": "number", "labelMode": "absolute", "prefix": "$"}


def test_geolayer_measure_format_skips_layer_filter_reference() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(
        Any,
        builder.add_layer(
            "geopoint",
            geopoint="Point",
            size="Amount",
            filters=[GeoLayerFilter(field="Amount", operation="GT", values=["0"])],
        ),
    ).measure_format("Amount", precision=1)

    layer = _payload_data(builder)["visualization"]["layers"][0]
    assert layer["size"]["items"][0]["formatting"] == {"precision": 1}
    assert layer["filters"]["items"][0] == {
        "datasetId": "ds1",
        "filter": {"operation": {"code": "GT"}, "value": ["0"]},
        "guid": "g_amt",
    }


def test_geolayer_update_targets_only_selected_layer() -> None:
    dataset = _dataset()
    builder = (
        WizardChartCreateFactory(cast(Any, None))
        .geolayer(name="G", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .add_layer("heatmap", geopoint="Point", name="Density")
        .add_layer("geopoint", geopoint="Point", labels=["Region"], name="Selected")
    )
    data = _payload_data(builder)
    selected_id = data["visualization"]["selectedLayerId"]
    chart = WizardChart(id="chart-1", installation="yacloud", data=data)

    update = chart.update.labels([dataset.fields.by_name("Amount")]).measure_format(
        dataset.fields.by_name("Amount"),
        precision=1,
    )
    visualization = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])[
        "visualization"
    ]
    assert visualization["selectedLayerId"] == selected_id
    assert [layer["type"] for layer in visualization["layers"]] == ["heatmap", "geopoint"]
    assert "labels" not in visualization["layers"][0]
    label = visualization["layers"][1]["labels"]["items"][0]
    assert label == {"guid": "g_amt", "datasetId": "ds1", "formatting": {"precision": 1}}


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
    ("layer_type", "field_argument", "field_name", "slot_name"),
    [
        ("geopoint", "geopoint", "Point", "points"),
        ("geopoint-with-cluster", "geopoint", "Point", "points"),
        ("heatmap", "geopoint", "Point", "points"),
        ("geopolygon", "polygon", "Region", "polygons"),
        ("polyline", "polyline", "Region", "polylines"),
    ],
)
def test_geolayer_supports_each_layer_type(
    layer_type: str,
    field_argument: str,
    field_name: str,
    slot_name: str,
) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(Any, builder).add_layer(layer_type, **{field_argument: field_name})
    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    assert layer["type"] == layer_type
    slot = layer[slot_name]
    expected_guid = "g_point" if field_name == "Point" else "g_reg"
    assert slot["items"][0]["guid"] == expected_guid


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
    assert [item["guid"] for item in layer["polylines"]["items"]] == ["g_point"]
    assert layer["polylines"]["settings"] == {"polylinePoints": "off"}
    assert layer["measures"]["items"] == []
    assert [item["guid"] for item in layer["grouping"]["items"]] == ["g_reg"]
    assert [item["guid"] for item in layer["colors"]["items"]] == ["g_amt"]
    assert layer["colors"]["settings"] == {
        "colorMode": "gradient",
        "fieldGuid": "g_amt",
        "gradientMode": "3-point",
        "gradientPalette": "red-orange-green",
        "polygonBorders": "show",
        "reversed": False,
        "thresholdsMode": "auto",
    }
    assert layer["sort"]["items"] == [{"guid": "g_date", "datasetId": "ds1", "direction": "ASC"}]
    assert "colors" not in data["visualization"]
    assert "sort" not in data["visualization"]


@pytest.mark.parametrize(
    "layer_type",
    ["geopoint", "geopoint-with-cluster", "heatmap", "geopolygon"],
)
def test_non_polyline_geo_layers_use_their_exact_v1_slot_contract(layer_type: str) -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(dataset)
    argument = "polygon" if layer_type == "geopolygon" else "geopoint"
    field = "Region" if layer_type == "geopolygon" else "Point"
    kwargs = {argument: field}
    if layer_type == "heatmap":
        kwargs["color"] = "Amount"
    cast(Any, builder).add_layer(layer_type, **kwargs)

    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    expected_slots = {
        "geopoint": {"colors", "filters", "labels", "points", "size", "tooltip"},
        "geopoint-with-cluster": {"colors", "filters", "labels", "points", "size", "tooltip"},
        "heatmap": {"colors", "filters", "points"},
        "geopolygon": {"colors", "filters", "polygons", "tooltip"},
    }
    assert set(layer) == {"type", "layerSettings", *expected_slots[layer_type]}
    if layer_type == "heatmap":
        assert layer["colors"]["items"][0]["guid"] == "g_amt"
    assert "segments" not in data["visualization"]


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


def test_geolayer_builds_confirmed_mixed_heatmap_and_cluster_topology() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer("heatmap", geopoint="Point", name="Density").add_layer(
        "geopoint-with-cluster",
        geopoint="Point",
        name="Clusters",
    )

    visualization = _payload_data(builder)["visualization"]
    assert [layer["type"] for layer in visualization["layers"]] == ["heatmap", "geopoint-with-cluster"]
    assert visualization["layers"][0]["points"]["items"][0]["guid"] == "g_point"
    assert visualization["layers"][1]["points"]["items"][0]["guid"] == "g_point"
    assert visualization["selectedLayerId"] == visualization["layers"][1]["layerSettings"]["id"]


def test_geolayer_builds_chart_level_filters_in_wizard_v1_shape() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = (
        factory.geolayer(name="G", location=EntryLocation.path("/F"))
        .dataset(_dataset())
        .add_filter("Region", operation="IN", values=["North"])
        .add_relative_date_filter("Order Date", start_offset="-1d", end_offset="-0d")
        .add_layer("geopoint", geopoint="Point")
    )

    filters = _payload_data(builder)["sources"]["filters"]
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
    assert "filters" not in data["sources"]
    layer_filter = data["visualization"]["layers"][0]["filters"]["items"][0]
    assert layer_filter == {
        "datasetId": "ds1",
        "filter": {"operation": {"code": "IN"}, "value": ["RUB"]},
        "guid": "g_currency",
    }


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

    colors = _payload_data(builder)["visualization"]["layers"][0]["colors"]
    assert colors["items"][0]["guid"] == "g_amt"
    assert colors["settings"] == {
        "colorMode": "gradient",
        "fieldGuid": "g_amt",
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
    settings = data["visualization"]["layers"][0]["colors"]["settings"]
    assert settings["gradientMode"] == expected_mode
    assert "colors" not in data["visualization"]


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


def test_geolayer_accepts_dimension_color_without_gradient_settings() -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    builder.add_layer("geopoint", geopoint="Point", color="Region")

    colors = _payload_data(builder)["visualization"]["layers"][0]["colors"]
    assert [item["guid"] for item in colors["items"]] == ["g_reg"]
    assert colors["settings"] == {}


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
    assert [item["guid"] for item in layer["size"]["items"]] == ["g_amt"]
    assert [item["guid"] for item in layer["colors"]["items"]] == ["g_amt"]
    assert [item["guid"] for item in layer["tooltip"]["items"]] == ["g_amt"]
    assert [item["guid"] for item in layer["labels"]["items"]] == ["g_amt"]
    assert [item["guid"] for item in data["sources"]["filters"]] == ["g_reg"]
    assert [item["guid"] for item in layer["filters"]["items"]] == ["g_currency"]


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
    assert data["sources"]["datasetsIds"] == ["ds1", "ds2"]
    geopoint_ph = data["visualization"]["layers"][0]["points"]
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
    assert y_items == [], "delete_field(DatasetField) must clear y-slot items"


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
    """A field present in a named slot and ``data.colors`` appears once."""
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    visualization = dict(cast(dict[str, Any], chart.data["visualization"]))
    visualization["colors"] = {"items": [{"guid": "g_amt", "title": "Amount", "type": "MEASURE", "datasetId": "ds1"}]}
    chart.data["visualization"] = visualization
    guids = [f.guid for f in chart.fields]
    assert guids.count("g_amt") == 1


def test_update_named_slot_edit() -> None:
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
        WizardHierarchy(
            title="Date hierarchy",
            fields=["g_date"],
            guid="h-date",
        )
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
