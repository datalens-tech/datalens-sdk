from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk.api.chart import ChartAPI, ChartService
from datalens_sdk.api.entries import EntriesAPI, EntriesService
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.ports import NavigationOperations
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensAPIError
from datalens_sdk.http import DataLensHTTPClient

_REFERENCE_CHARTS_DIR = Path(__file__).parent / "fixtures" / "reference_charts" / "wizard"


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
        ),
    )


def _payload_data(builder: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()["data"])


def test_combined_live_fixture_has_complete_per_layer_colors_config() -> None:
    fixture = _reference_chart("zenewka5dvwij")
    layers = cast(list[dict[str, Any]], fixture["data"]["visualization"]["layers"])
    expected_keys = {"colorMode", "coloredByMeasure", "fieldGuid", "mountedColors", "palette", "polygonBorders"}
    assert all(set(layer["commonPlaceholders"]["colorsConfig"]) == expected_keys for layer in layers)


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


def test_combined_measure_format_reaches_layer_placeholders() -> None:
    dataset = _dataset()
    factory = WizardChartCreateFactory(cast(Any, None))
    amount = dataset.fields.by_name("Amount")
    builder = (
        factory.combined_chart(name="C", location=EntryLocation.path("/F"))
        .dataset(dataset)
        .x(["Order Date"])
        .add_layer("column", y=amount)
        .measure_format(amount, precision=2, unit="k")
    )

    layer = _payload_data(builder)["visualization"]["layers"][0]
    amount_item = next(
        item
        for placeholder in layer["placeholders"]
        for item in placeholder["items"]
        if item.get("guid") == amount.guid
    )
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


@pytest.mark.parametrize(
    ("layer_type", "field_argument", "field_name"),
    [
        ("geopoint", "geopoint", "Region"),
        ("heatmap", "geopoint", "Region"),
        ("geopolygon", "polygon", "Region"),
        ("polyline", "polyline", "Region"),
    ],
)
def test_geolayer_supports_each_layer_type(layer_type: str, field_argument: str, field_name: str) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="G", location=EntryLocation.path("/F")).dataset(_dataset())
    cast(Any, builder).add_layer(layer_type, **{field_argument: field_name})
    data = _payload_data(builder)
    layer = data["visualization"]["layers"][0]
    assert layer["id"] == layer_type
    required_placeholder = "geopolygon" if layer_type == "geopolygon" else field_argument
    placeholder = next(item for item in layer["placeholders"] if item["id"] == required_placeholder)
    assert placeholder["items"][0]["guid"] == "g_reg"


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
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "filters": [{"guid": "f1"}, {"guid": "f2"}],
                "visualization": {
                    "id": "line",
                    "placeholders": [
                        {"id": "x", "items": [{"guid": "g_date", "datasetId": "ds1"}]},
                        {"id": "y", "items": [{"guid": "g_amt", "datasetId": "ds1", "title": "Amount"}]},
                    ],
                },
            },
        },
        installation="yacloud",
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
    x_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "x")["items"]
    y_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "y")["items"]
    assert x_items[0]["guid"] == "g_new"
    assert y_items == []


def test_update_replace_dataset() -> None:
    chart = _chart_for_update()
    update = chart.update.replace_dataset(old="ds1", new="ds2")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert data["datasetsIds"] == ["ds2"]
    x_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "x")["items"]
    assert x_items[0]["datasetId"] == "ds2"


def test_update_delete_filter() -> None:
    chart = _chart_for_update()
    update = chart.update.delete_filter("f1")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert [f["guid"] for f in data["filters"]] == ["f2"]


def test_update_delete_field_accepts_dataset_field() -> None:
    """``delete_field`` extracts ``.guid`` from a ``DatasetField``."""
    chart = _chart_for_update()
    field = DatasetField(guid="g_amt", title="Amount", name="Amount", calc_mode="direct", dataset_id="ds1")
    update = chart.update.delete_field(field)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    y_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "y")["items"]
    assert y_items == [], "delete_field(DatasetField) must clear y-placeholder items"


def test_update_delete_filter_accepts_dataset_field() -> None:
    """``delete_filter`` extracts ``.guid`` from a ``DatasetField`` (filter guid == field guid)."""
    chart = _chart_for_update()
    field = DatasetField(guid="f1", title="F1", name="F1", calc_mode="direct")
    update = chart.update.delete_filter(field)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    assert [f["guid"] for f in data["filters"]] == ["f2"]


def test_update_replace_field_accepts_dataset_field_pair() -> None:
    """``replace_field`` resolves both args via ``DatasetField.guid``."""
    chart = _chart_for_update()
    old = DatasetField(guid="g_date", title="Order Date", name="Order Date", calc_mode="direct")
    new = DatasetField(guid="g_new", title="New", name="New", calc_mode="direct")
    update = chart.update.replace_field(old, new)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    x_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "x")["items"]
    assert x_items[0]["guid"] == "g_new"


def test_update_replace_formula_accepts_dataset_field() -> None:
    """``replace_formula`` extracts ``.guid`` from a ``DatasetField``."""
    chart = _chart_for_update()
    chart.data = dict(chart.data)
    chart.data["updates"] = [
        {"action": "add_field", "field": {"guid": "local-field", "formula": "[Revenue]", "local": True}}
    ]
    field = DatasetField(guid="local-field", title="Local", name="Local", calc_mode="formula", formula="[Revenue]")
    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(
            chart.update.replace_formula(field, formula="[Revenue] * 2")
        ).to_payload()["data"],
    )
    assert data["updates"][0]["field"]["formula"] == "[Revenue] * 2"


def test_update_structural_ops_resolve_via_chart_fields_proxy() -> None:
    """End-to-end: ``chart.fields.by_guid(...)`` (placed-field FieldsProxy) feeds every structural op."""
    chart = _chart_for_update()
    placed_date = chart.fields.by_guid("g_date")
    placed_amt = chart.fields.by_guid("g_amt")
    assert isinstance(placed_date, DatasetField)
    assert isinstance(placed_amt, DatasetField)
    update = chart.update.delete_field(placed_amt).replace_field(placed_date, placed_amt)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    x_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "x")["items"]
    y_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "y")["items"]
    assert x_items[0]["guid"] == "g_amt"
    assert y_items == []


def test_chart_fields_surfaces_color_only_field_from_data_colors() -> None:
    """A field placed only through semantic Color on a cartesian chart lives in
    ``data.colors``. It must still
    be reachable via ``chart.fields.by_name(...)`` so a subsequent
    ``replace_field``/``delete_field`` can target it."""
    chart = WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "colors": [{"guid": "g_country", "title": "Country", "type": "DIMENSION", "datasetId": "ds1"}],
                "visualization": {
                    "id": "line",
                    "placeholders": [
                        {"id": "x", "items": [{"guid": "g_date", "title": "Date", "datasetId": "ds1"}]},
                        {"id": "y", "items": [{"guid": "g_amt", "title": "Amount", "datasetId": "ds1"}]},
                    ],
                },
            },
        },
        installation="yacloud",
    )
    country = chart.fields.by_name("Country")
    assert isinstance(country, DatasetField)
    assert country.guid == "g_country"
    assert chart.fields.by_guid("g_date").guid == "g_date"
    assert chart.fields.by_guid("g_amt").guid == "g_amt"


def test_chart_fields_dedups_by_guid_across_placeholder_and_data_colors() -> None:
    """A field present both in a placeholder and in ``data.colors`` appears once."""
    chart = WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "colors": [{"guid": "g_amt", "title": "Amount", "type": "MEASURE", "datasetId": "ds1"}],
                "visualization": {
                    "id": "line",
                    "placeholders": [{"id": "y", "items": [{"guid": "g_amt", "title": "Amount", "datasetId": "ds1"}]}],
                },
            },
        },
        installation="yacloud",
    )
    guids = [f.guid for f in chart.fields]
    assert guids.count("g_amt") == 1


def test_update_placeholder_edit() -> None:
    chart = _chart_for_update()
    update = chart.update.y(["g_amt"]).x(["g_date"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    x_items = next(p for p in data["visualization"]["placeholders"] if p["id"] == "x")["items"]
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
        data={"visualization": {"id": "line", "placeholders": []}},
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
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "visualization": {
                    "id": "line",
                    "placeholders": [
                        {
                            "id": "x",
                            "items": [
                                {
                                    "guid": "g_date",
                                    "title": "Order Date",
                                    "type": "DIMENSION",
                                    "data_type": "date",
                                    "calc_mode": "direct",
                                    "datasetId": "ds1",
                                }
                            ],
                        },
                        {
                            "id": "y",
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
                    ],
                },
            },
        },
        installation="yacloud",
    )


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

    assert data["datasetsIds"] == ["ds2"], "datasetsIds must be updated"
    sort_items = cast(list[dict[str, Any]], data.get("sort", []))
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

    assert data["datasetsIds"] == ["ds2"], "datasetsIds must be updated"
    filters = cast(list[dict[str, Any]], data.get("filters", []))
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

    assert data["datasetsIds"] == ["ds2"]
    sort_items = cast(list[dict[str, Any]], data.get("sort", []))
    assert sort_items[0]["datasetId"] == "ds2", "sort must use new dataset id"
    filters = cast(list[dict[str, Any]], data.get("filters", []))
    assert filters[0]["datasetId"] == "ds2", "filter must use new dataset id"


def test_replace_dataset_then_add_hierarchy_uses_new_dataset_id() -> None:
    chart = _chart_for_replace_dataset_regression()

    update = chart.update.replace_dataset(old="ds1", new="ds2").add_hierarchy(
        "Date hierarchy",
        ["g_date"],
        guid="h-date",
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["hierarchies"][0]["fields"][0]["datasetId"] == "ds2"


def test_replace_dataset_then_color_by_dimension_uses_new_dataset_id() -> None:
    chart = _chart_for_replace_dataset_regression()

    update = chart.update.replace_dataset(old="ds1", new="ds2").color_by_dimension("g_date")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])

    assert data["colors"][0]["datasetId"] == "ds2"


# ---------------------------------------------------------------------------
# Regression: labels([]) must be a no-op (clear labels, no extraSettings side
# effect)
# ---------------------------------------------------------------------------


def _bar_chart_with_labels() -> WizardChart:
    """bar chart that already has labels set."""
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-2",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "labels": [{"guid": "g_amt", "title": "Amount", "type": "MEASURE", "datasetId": "ds1"}],
                "visualization": {
                    "id": "bar",
                    "placeholders": [
                        {
                            "id": "x",
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
                        }
                    ],
                },
            },
        },
        installation="yacloud",
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

    assert data.get("labels") == [], "labels must be cleared to [] by labels([])"
    extras = cast(dict[str, Any], data.get("extraSettings", {}))
    assert "labelsPosition" not in extras, "labelsPosition must NOT be written when labels are cleared"


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
                "entryId": "chart-1",
                "type": "d3_wizard_node",
                "data": {"visualization": {"id": "line", "placeholders": []}},
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
        data={"visualization": {"id": "line", "placeholders": []}},
        _operations=service,
    )
    update = chart.update.chart_title(text="Changed")
    with pytest.raises(DataLensAPIError):
        service.update_wizard_chart(update)
