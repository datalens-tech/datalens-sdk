from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from datalens_sdk import DataLensClientYC
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
from datalens_sdk.domain.wizard_chart import WizardChart, WizardChartUpdate
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError


class _RecordedTransport:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=_response())

    def request_json(self, index: int) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.requests[index].content))

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


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
            {
                "guid": "parameter-guid",
                "title": "Scale",
                "type": "DIMENSION",
                "data_type": "string",
                "calc_mode": "parameter",
                "default_value": "month",
                "avatar_id": None,
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

    assert set(payload) == {"data", "key"}
    assert payload["key"] == "/Charts/Line"
    data = cast(dict[str, object], payload["data"])
    assert set(data) == {"sources", "visualization"}
    sources = cast(dict[str, object], data["sources"])
    assert sources["datasetsIds"] == ["dataset-1"]
    updates = cast(list[dict[str, object]], sources["updates"])
    parameter_field = cast(dict[str, object], updates[0]["field"])
    assert parameter_field["guid"] == "parameter-guid"
    assert parameter_field["default_value"] == "month"
    assert "avatar_id" not in parameter_field
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


def test_line_create_uses_name_only_for_workbook_location() -> None:
    builder = WizardChartCreateFactory(cast(Any, None)).line(
        name="Line",
        location=EntryLocation.workbook("workbook-1"),
    )

    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()

    assert set(payload) == {"data", "name", "workbookId"}
    assert payload["name"] == "Line"
    assert payload["workbookId"] == "workbook-1"


def test_line_read_uses_api_v3_envelope_and_document_v1_paths() -> None:
    response = _response()
    chart = WizardChartConverter.to_domain(response, installation="yacloud")

    assert chart.id == "chart-1"
    assert chart.rev_id == "revision-1"
    assert chart.visualization_id == "line"
    assert chart.dataset_ids == ("dataset-1",)
    assert chart.raw == response["entry"]
    assert chart.response_snapshot == response


def test_line_noop_update_preserves_open_document_v1_snapshot() -> None:
    chart = WizardChartConverter.to_domain(_response(), installation="yacloud")

    save_payload = WizardChartConverter.from_domain_update(chart.update).to_payload()
    publish_payload = WizardChartConverter.from_domain_update(chart.update.mode("publish")).to_payload()

    assert save_payload["chartId"] == "chart-1"
    assert save_payload["mode"] == "save"
    assert "revId" not in save_payload
    assert save_payload["data"] == chart.data
    assert set(save_payload) == {"chartId", "mode", "data"}
    assert publish_payload["mode"] == "publish"
    assert "revId" not in publish_payload


def test_publish_revision_defaults_to_loaded_rev_id() -> None:
    recorder = _RecordedTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    chart = client.get.wizard_chart(by_id="chart-1")

    result = chart.publish_revision()

    assert recorder.paths() == ["/rpc/getWizardChart", "/rpc/updateWizardChart"]
    payload = recorder.request_json(1)
    assert payload["chartId"] == "chart-1"
    assert payload["mode"] == "publish"
    assert payload["revId"] == "revision-1"
    assert payload["data"] == chart.data
    assert result.rev_id == "revision-1"


def test_publish_revision_accepts_an_explicit_revision() -> None:
    recorder = _RecordedTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    chart = client.get.wizard_chart(by_id="chart-1")

    chart.publish_revision(rev_id="revision-old")

    assert recorder.request_json(1)["revId"] == "revision-old"


def test_publish_revision_requires_a_bound_chart_and_revision() -> None:
    with pytest.raises(DataLensConfigurationError):
        WizardChart(id="chart-1").publish_revision(rev_id="revision-1")

    chart = WizardChart(id="chart-1", _operations=cast(Any, object()))
    with pytest.raises(DataLensValidationError, match="no rev_id given"):
        chart.publish_revision()


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


def test_wizard_v1_exposes_only_the_verified_tooltip_mode_surface() -> None:
    assert not hasattr(LineWizardChartCreate, "tooltips")
    assert hasattr(LineWizardChartCreate, "tooltip")
    assert hasattr(WizardChartUpdate, "change_visualization_to")
