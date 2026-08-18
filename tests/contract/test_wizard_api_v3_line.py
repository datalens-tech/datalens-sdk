from __future__ import annotations

from typing import Any, cast

from datalens_sdk._generated.builders.charts import LineWizardChartCreate, WizardChartCreateFactory
from datalens_sdk._generated.dto import (
    WizardChartCreateDTO,
    WizardChartDeleteArgsDTO,
    WizardChartGetArgsDTO,
    WizardChartUpdateDTO,
)
from datalens_sdk.converter.raw.chart import RawWizardChartCreateEnvelope, RawWizardChartReplaceEnvelope
from datalens_sdk.converter.wizard.converter import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.wizard_chart import WizardChartUpdate


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
                "guid": "amount-guid",
                "title": "Amount",
                "type": "MEASURE",
                "data_type": "float",
                "calc_mode": "direct",
            },
        ),
    )


def _response() -> dict[str, object]:
    return {
        "entry": {
            "version": 1,
            "entryId": "chart-1",
            "revId": "revision-1",
            "type": "d3_wizard_node",
            "key": "/Charts/Line",
            "futureEntry": {"kept": True},
            "data": {
                "futureRoot": {"kept": True},
                "sources": {
                    "datasetsIds": ["dataset-1"],
                    "filters": [],
                    "futureSources": {"kept": True},
                },
                "visualization": {
                    "type": "line",
                    "futureVisualization": {"kept": True},
                    "x": {
                        "items": [{"guid": "date-guid", "datasetId": "dataset-1", "futureItem": True}],
                        "settings": {"axisVisibility": "show", "futureSetting": True},
                        "futureSlot": True,
                    },
                    "y": {
                        "items": [{"guid": "amount-guid", "datasetId": "dataset-1"}],
                    },
                },
            },
        },
        "isFavorite": False,
        "permissions": {"update": True},
        "futureEnvelope": {"kept": True},
    }


def test_line_create_builds_wizard_v1_config_for_api_v3() -> None:
    builder = (
        WizardChartCreateFactory(cast(Any, None))
        .line(name="Line", location=EntryLocation.path("/Charts"))
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
    )

    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()

    assert set(payload) == {"data", "key", "name"}
    data = cast(dict[str, object], payload["data"])
    assert set(data) == {"sources", "visualization"}
    sources = cast(dict[str, object], data["sources"])
    assert sources["datasetsIds"] == ["dataset-1"]
    visualization = cast(dict[str, object], data["visualization"])
    assert set(visualization) == {
        "colors",
        "labels",
        "segments",
        "shapes",
        "sort",
        "type",
        "x",
        "y",
        "y2",
    }
    assert visualization["type"] == "line"
    x = cast(dict[str, object], visualization["x"])
    y = cast(dict[str, object], visualization["y"])
    assert x["items"] == [{"guid": "date-guid", "datasetId": "dataset-1"}]
    assert y["items"] == [{"guid": "amount-guid", "datasetId": "dataset-1"}]


def test_line_read_uses_api_v3_envelope_and_document_v1_paths() -> None:
    response = _response()
    chart = WizardChartConverter.to_domain(response, installation="yacloud")

    assert chart.id == "chart-1"
    assert chart.visualization_id == "line"
    assert chart.dataset_ids == ("dataset-1",)
    assert chart.raw == response["entry"]
    assert chart.response_snapshot == response


def test_line_noop_update_preserves_open_document_v1_snapshot() -> None:
    chart = WizardChartConverter.to_domain(_response(), installation="yacloud")

    payload = WizardChartConverter.from_domain_update(chart.update).to_payload()

    assert payload["chartId"] == "chart-1"
    assert payload["revId"] == "revision-1"
    assert payload["data"] == chart.data
    assert set(payload) == {"chartId", "mode", "data", "revId"}


def test_line_targeted_update_preserves_unknown_server_fields() -> None:
    chart = WizardChartConverter.to_domain(_response(), installation="yacloud")

    payload = WizardChartConverter.from_domain_update(chart.update.axis_visibility("x", mode="hide")).to_payload()

    data = cast(dict[str, object], payload["data"])
    sources = cast(dict[str, object], data["sources"])
    visualization = cast(dict[str, object], data["visualization"])
    x = cast(dict[str, object], visualization["x"])
    settings = cast(dict[str, object], x["settings"])
    items = cast(list[dict[str, object]], x["items"])
    assert data["futureRoot"] == {"kept": True}
    assert sources["futureSources"] == {"kept": True}
    assert visualization["futureVisualization"] == {"kept": True}
    assert x["futureSlot"] is True
    assert settings == {"axisVisibility": "hide", "futureSetting": True}
    assert items[0]["futureItem"] is True


def test_raw_wizard_envelopes_serialize_document_v1_data() -> None:
    data = cast(dict[str, Any], cast(dict[str, object], _response()["entry"])["data"])

    create_payload = RawWizardChartCreateEnvelope(data=data, name="Copy").to_payload()
    replace_payload = RawWizardChartReplaceEnvelope(
        chart_id="target-chart",
        mode="save",
        data=data,
        rev_id="target-revision",
    ).to_payload()

    assert create_payload == {"data": data, "name": "Copy"}
    assert replace_payload == {
        "chartId": "target-chart",
        "mode": "save",
        "data": data,
        "revId": "target-revision",
    }


def test_generated_wizard_operations_expose_the_api_v3_surface() -> None:
    assert set(WizardChartCreateDTO.model_fields) == {"data", "key", "name", "workbook_id", "annotation"}
    assert set(WizardChartUpdateDTO.model_fields) == {"chart_id", "mode", "data", "annotation", "rev_id"}
    assert set(WizardChartGetArgsDTO.model_fields) == {"chart_id", "workbook_id"}
    assert set(WizardChartDeleteArgsDTO.model_fields) == {"chart_id"}


def test_phase1_preserves_deferred_public_surface_for_phase3() -> None:
    assert hasattr(LineWizardChartCreate, "tooltips")
    assert hasattr(WizardChartUpdate, "change_visualization_to")
