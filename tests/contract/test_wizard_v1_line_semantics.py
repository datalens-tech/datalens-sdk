from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk.converter.wizard.converter import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.errors import DataLensConfigurationError


def _dataset() -> Dataset:
    return Dataset(
        id="dataset-1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {
                "guid": "date-guid",
                "title": "Date",
                "type": "DIMENSION",
                "data_type": "date",
                "calc_mode": "direct",
            },
            {
                "guid": "region-guid",
                "title": "Region",
                "type": "DIMENSION",
                "data_type": "string",
                "calc_mode": "direct",
            },
            {
                "guid": "amount-guid",
                "title": "Amount",
                "type": "MEASURE",
                "data_type": "float",
                "calc_mode": "direct",
            },
            {
                "guid": "count-guid",
                "title": "Count",
                "type": "MEASURE",
                "data_type": "integer",
                "calc_mode": "direct",
            },
            {
                "guid": "unused-guid",
                "title": "Unused",
                "type": "MEASURE",
                "data_type": "float",
                "calc_mode": "direct",
            },
            {
                "guid": "threshold-guid",
                "title": "Threshold",
                "calc_mode": "parameter",
                "data_type": "float",
            },
        ),
    )


def _line_builder() -> Any:
    return WizardChartCreateFactory(cast(Any, None)).line(
        name="Line",
        location=EntryLocation.path("/Charts"),
    )


def _create_data(builder: Any) -> dict[str, Any]:
    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()
    return cast(dict[str, Any], payload["data"])


def _line_response() -> dict[str, object]:
    return {
        "entry": {
            "version": 1,
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "sources": {"datasetsIds": ["dataset-1"]},
                "visualization": {
                    "type": "line",
                    "x": {
                        "items": [
                            {
                                "guid": "date-guid",
                                "datasetId": "dataset-1",
                                "fakeTitle": "Date",
                                "type": "DIMENSION",
                                "data_type": "date",
                            }
                        ]
                    },
                    "y": {
                        "items": [
                            {
                                "guid": "amount-guid",
                                "datasetId": "dataset-1",
                                "fakeTitle": "Amount",
                                "type": "MEASURE",
                                "data_type": "float",
                            }
                        ]
                    },
                    "y2": {
                        "items": [
                            {
                                "guid": "count-guid",
                                "datasetId": "dataset-1",
                                "fakeTitle": "Count",
                                "type": "MEASURE",
                                "data_type": "integer",
                            }
                        ]
                    },
                    "colors": {
                        "items": [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}],
                        "settings": {
                            "coloredByMeasure": True,
                            "mountedColors": {"amount-guid": "#111111", "count-guid": "#222222"},
                            "futureSetting": {"kept": True},
                        },
                        "futureSlot": {"kept": True},
                    },
                },
            },
        }
    }


def test_measure_name_color_and_shape_bind_only_placed_line_measures() -> None:
    data = _create_data(
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .y2(["Count"])
        .color_by_measure_name(colors_map={"Amount": "#001122", "Count": "#334455"})
        .shape_by_measure_name(shapes_map={"Amount": "Solid", "Count": "Dash"})
    )

    visualization = data["visualization"]
    assert visualization["colors"]["items"] == [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}]
    assert visualization["colors"]["settings"]["mountedColors"] == {
        "amount-guid": "#001122",
        "count-guid": "#334455",
    }
    assert visualization["shapes"]["items"] == [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}]
    assert visualization["shapes"]["settings"]["mountedShapes"] == {
        "amount-guid": "Solid",
        "count-guid": "Dash",
    }


@pytest.mark.parametrize("encoding", ["color", "shape"])
def test_measure_name_encoding_requires_two_placed_measures(encoding: str) -> None:
    builder = _line_builder().dataset(_dataset()).x(["Date"]).y(["Amount"])
    if encoding == "color":
        builder.color_by_measure_name()
    else:
        builder.shape_by_measure_name()

    with pytest.raises(DataLensConfigurationError, match="at least two measures"):
        _create_data(builder)


@pytest.mark.parametrize("encoding", ["color", "shape"])
def test_measure_name_encoding_rejects_unplaced_measure_mapping(encoding: str) -> None:
    builder = _line_builder().dataset(_dataset()).x(["Date"]).y(["Amount", "Count"])
    if encoding == "color":
        builder.color_by_measure_name(colors_map={"Unused": "#001122"})
    else:
        builder.shape_by_measure_name(shapes_map={"Unused": "Dash"})

    with pytest.raises(DataLensConfigurationError, match="not placed as a measure"):
        _create_data(builder)


def test_measure_name_color_rejects_non_hex_value() -> None:
    builder = (
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount", "Count"])
        .color_by_measure_name(colors_map={"Amount": "red"})
    )

    with pytest.raises(DataLensConfigurationError, match="#RRGGBB"):
        _create_data(builder)


def test_dimension_shape_mapping_keeps_dimension_values_as_map_keys() -> None:
    data = _create_data(
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .shape_by_dimension("Region", shapes_map={"North": "Solid", "South": "Dash"})
    )

    settings = data["visualization"]["shapes"]["settings"]
    assert settings["fieldGuid"] == "region-guid"
    assert settings["mountedShapes"] == {"North": "Solid", "South": "Dash"}


def test_encoding_update_preserves_unknown_document_v1_slot_and_settings() -> None:
    chart = WizardChartConverter.to_domain(_line_response(), installation="yacloud")

    payload = WizardChartConverter.from_domain_update(
        chart.update.color_by_measure_name(colors_map={"Amount": "#001122", "Count": "#334455"})
    ).to_payload()

    data = cast(dict[str, Any], payload["data"])
    colors = data["visualization"]["colors"]
    assert colors["futureSlot"] == {"kept": True}
    assert colors["settings"]["futureSetting"] == {"kept": True}
    assert colors["settings"]["mountedColors"] == {
        "amount-guid": "#001122",
        "count-guid": "#334455",
    }


def test_measure_format_update_merges_existing_document_v1_formatting() -> None:
    response = _line_response()
    entry = cast(dict[str, Any], response["entry"])
    data = cast(dict[str, Any], entry["data"])
    amount = data["visualization"]["y"]["items"][0]
    amount["formatting"] = {
        "format": "number",
        "unit": "k",
        "futureFormatting": {"kept": True},
    }
    chart = WizardChartConverter.to_domain(response, installation="yacloud")

    payload = WizardChartConverter.from_domain_update(chart.update.measure_format("Amount", precision=2)).to_payload()

    updated_data = cast(dict[str, Any], payload["data"])
    updated_amount = updated_data["visualization"]["y"]["items"][0]
    assert updated_amount["formatting"] == {
        "format": "number",
        "unit": "k",
        "futureFormatting": {"kept": True},
        "precision": 2,
    }


def test_dataset_parameter_is_emitted_under_document_v1_sources_updates() -> None:
    data = _create_data(_line_builder().dataset(_dataset()).x(["Date"]).y(["Amount"]))

    updates = data["sources"]["updates"]
    parameter_update = next(update for update in updates if update["field"]["guid"] == "threshold-guid")
    assert parameter_update["action"] == "update_field"
    assert parameter_update["field"]["datasetId"] == "dataset-1"


def test_unmatched_line_item_decoration_fails_closed() -> None:
    builder = (
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .measure_format("Unused", format="number", precision=2)
    )

    with pytest.raises(DataLensConfigurationError, match="not placed"):
        _create_data(builder)
