from __future__ import annotations

from collections.abc import Mapping
import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.api.data import DataAPI, DataService
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.converter.chart_data import ChartDataConverter
from datalens_sdk.converter.screenshot import ScreenshotConverter
from datalens_sdk.domain.chart_data import ChartDataQuery
from datalens_sdk.domain.screenshot import ScreenshotRequest
from datalens_sdk.http import HTTPClientProtocol

ClientClass = type[dl.DataLensClientYC] | type[dl.DataLensClientEnterprise]


class RecordedTransport:
    def __init__(self, responses: list[httpx.Response] | httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) if isinstance(responses, list) else [responses]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses.pop(0)

    def body(self, index: int = 0) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.requests[index].content))


def make_client(recorder: RecordedTransport, client_cls: ClientClass = dl.DataLensClientYC) -> DataLensClientBase:
    return client_cls(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def wizard_response() -> dict[str, object]:
    return {
        "chartType": "wizard",
        "results": [
            {
                "schema": [
                    {"name": "Duplicate", "type": "future_type", "guid": "field-1", "extra": "ignored"},
                    {"name": "Duplicate", "type": "string"},
                ],
                "rows": [[True, "123"], [None], [2**60, {"nested": ["☃", False, None]}, 3.5]],
                "extra": "ignored",
            },
            {"schema": [], "rows": []},
        ],
        "extra": "ignored",
    }


@pytest.mark.parametrize("client_cls", [dl.DataLensClientYC, dl.DataLensClientEnterprise])
def test_chart_data_preserves_tables_columns_and_json_values(client_cls: ClientClass) -> None:
    recorder = RecordedTransport(httpx.Response(200, json=wizard_response()))
    result = make_client(recorder, client_cls).data.get_chart_data(chart_id="chart-1")

    assert result == dl.WizardChartData(
        results=(
            dl.ChartDataTable(
                schema=(
                    dl.WizardChartDataColumn(name="Duplicate", type="future_type", guid="field-1"),
                    dl.WizardChartDataColumn(name="Duplicate", type="string"),
                ),
                rows=((True, "123"), (None,), (2**60, {"nested": ["☃", False, None]}, 3.5)),
            ),
            dl.ChartDataTable(schema=(), rows=()),
        )
    )
    assert [request.url.path for request in recorder.requests] == ["/rpc/getChartData"]
    assert recorder.body() == {"chartId": "chart-1"}


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"chartType": "wizard", "results": []}, dl.WizardChartData(results=())),
        ({"chartType": "ql", "results": []}, dl.QLChartData(results=())),
        ({"chartType": "editor", "results": []}, dl.EditorChartData(results=())),
        (
            {
                "chartType": "ql",
                "results": [{"schema": [{"name": "Number", "type": "decimal"}], "rows": [["123.40"]]}],
            },
            dl.QLChartData(
                results=(
                    dl.ChartDataTable(
                        schema=(dl.QLChartDataColumn(name="Number", type="decimal"),), rows=(("123.40",),)
                    ),
                )
            ),
        ),
        (
            {"chartType": "editor", "results": [{"schema": [{"name": "Value", "future": True}], "rows": [[7]]}]},
            dl.EditorChartData(
                results=(dl.ChartDataTable(schema=(dl.EditorChartDataColumn(name="Value"),), rows=((7,),)),)
            ),
        ),
    ],
)
def test_chart_data_parses_all_variants(response: dict[str, object], expected: dl.ChartData) -> None:
    recorder = RecordedTransport(httpx.Response(200, json=response))
    assert make_client(recorder).data.get_chart_data(chart_id="chart-1") == expected


@pytest.mark.parametrize("params", [None, {}, {"x": "", "y": [], "z": ["a", "b"]}])
def test_chart_data_omitted_empty_and_present_params_have_exact_payload(params: dl.RuntimeParams | None) -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"chartType": "editor", "results": []}))
    make_client(recorder).data.get_chart_data(chart_id="chart-1", params=params)
    expected: dict[str, object] = {"chartId": "chart-1"}
    if params is not None:
        expected["params"] = params
    assert recorder.body() == expected


def test_runtime_parameters_snapshot_values_and_share_screenshot_serialization() -> None:
    cities = ["Moscow", "Казань & a=b/☃"]
    params: dict[str, str | list[str]] = {"city": cities, "year": "2026", "empty": [], "blank": ""}
    query = ChartDataQuery(chart_id="chart-1", params=params)
    screenshot = ScreenshotRequest.create(entity_kind="chart", entity_id="chart-1", params=params, rev_id="loaded")
    cities.append("Later")
    params["year"] = "later"
    params["added"] = "later"

    expected = {"city": ["Moscow", "Казань & a=b/☃"], "year": "2026", "empty": [], "blank": ""}
    assert ChartDataConverter.request_payload(query) == {"chartId": "chart-1", "params": expected}
    assert ScreenshotConverter.query_params(screenshot) == {
        **expected,
        "_embedded": "1",
        "_no_controls": "1",
        "revId": "loaded",
    }
    assert query.params is not params
    assert isinstance(query.params, Mapping)
    assert query.params["city"] == ("Moscow", "Казань & a=b/☃")
    assert params["city"] == ["Moscow", "Казань & a=b/☃", "Later"]


def test_chart_data_accepts_names_without_screenshot_policy() -> None:
    # This is a synthetic name; it is not a documented pagination parameter.
    params = {"": "value", "_synthetic": ["x"], "revId": "caller-value", "tab": "a", "state": "b"}
    assert ChartDataConverter.request_payload(ChartDataQuery(chart_id="chart-1", params=params)) == {
        "chartId": "chart-1",
        "params": params,
    }
    with pytest.raises(dl.DataLensValidationError, match="non-empty"):
        ScreenshotRequest.create(entity_kind="chart", entity_id="chart-1", params={"": "value"})
    with pytest.raises(dl.DataLensValidationError, match="page view"):
        ScreenshotRequest.create(entity_kind="chart", entity_id="chart-1", params={"_synthetic": "x"})
    with pytest.raises(dl.DataLensValidationError, match="set by the SDK"):
        ScreenshotRequest.create(entity_kind="chart", entity_id="chart-1", params={"revId": "x"})


@pytest.mark.parametrize(
    "params",
    [
        [],
        "x",
        {1: "x"},
        {"x": 1},
        {"x": True},
        {"x": None},
        {"x": b"x"},
        {"x": bytearray(b"x")},
        {"x": {"y": "z"}},
        {"x": ["x", 1]},
    ],
)
def test_chart_data_invalid_params_fail_before_http(params: object) -> None:
    recorder = RecordedTransport([])
    with pytest.raises(dl.DataLensValidationError):
        make_client(recorder).data.get_chart_data(chart_id="chart-1", params=cast(dl.RuntimeParams, params))
    assert recorder.requests == []


@pytest.mark.parametrize("chart_id", ["", None, 1, True])
def test_chart_data_invalid_id_fails_before_http(chart_id: object) -> None:
    recorder = RecordedTransport([])
    with pytest.raises(dl.DataLensValidationError, match="non-empty string"):
        make_client(recorder).data.get_chart_data(chart_id=cast(str, chart_id))
    assert recorder.requests == []


@pytest.mark.parametrize("chart_class", [dl.WizardChart, dl.QLChart, dl.EditorChart])
def test_bound_chart_executes_by_id_and_returns_server_variant(chart_class: type[dl.Chart]) -> None:
    recorder = RecordedTransport(
        [
            httpx.Response(200, json={"chartType": "editor", "results": []}),
            httpx.Response(200, json={"chartType": "editor", "results": []}),
        ]
    )
    client = make_client(recorder)
    chart = chart_class(
        id="chart-1",
        raw={"revId": "historical", "savedId": "saved", "publishedId": "published"},
        data={"local": "unsaved"},
        _operations=client.chart_ops,
    )
    namespace = client.data.get_chart_data(chart_id="chart-1", params={"region": ["East", "West"]})
    bound = chart.get_chart_data(params={"region": ["East", "West"]})
    assert namespace == bound == dl.EditorChartData(results=())
    assert [request.url.path for request in recorder.requests] == ["/rpc/getChartData", "/rpc/getChartData"]
    assert recorder.body(0) == recorder.body(1) == {"chartId": "chart-1", "params": {"region": ["East", "West"]}}


@pytest.mark.parametrize("chart_class", [dl.WizardChart, dl.QLChart, dl.EditorChart])
def test_bound_chart_requires_binding_and_saved_id(chart_class: type[dl.Chart]) -> None:
    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        chart_class(id="chart-1").get_chart_data()
    recorder = RecordedTransport([])
    chart = chart_class(id=None, _operations=make_client(recorder).chart_ops)
    with pytest.raises(dl.DataLensValidationError, match="without an id"):
        chart.get_chart_data()
    assert recorder.requests == []


@pytest.mark.parametrize(
    "response",
    [
        {"results": []},
        {"chartType": "future", "results": []},
        {"chartType": "wizard"},
        {"chartType": "editor", "results": [{"schema": [], "rows": ["bad"]}]},
        {"chartType": "editor", "results": [{"schema": [], "rows": {"bad": []}}]},
        {"chartType": "ql", "results": [{"schema": [{"name": "x"}], "rows": []}]},
        {"chartType": "wizard", "results": [{"schema": [{"type": "string"}], "rows": []}]},
    ],
)
def test_chart_data_rejects_malformed_responses(response: dict[str, object]) -> None:
    recorder = RecordedTransport(httpx.Response(200, json=response))
    with pytest.raises(dl.DTOValidationError, match="getChartData"):
        make_client(recorder).data.get_chart_data(chart_id="chart-1")


def test_chart_data_invalid_json_cell_is_a_response_error() -> None:
    recorder = RecordedTransport(
        httpx.Response(200, content=b'{"chartType":"editor","results":[{"schema":[],"rows":[[NaN]]}]}')
    )
    with pytest.raises(dl.InvalidResponseError, match="non-finite"):
        make_client(recorder).data.get_chart_data(chart_id="chart-1")


class InvalidCellAPI(DataAPI):
    def get_chart_data(self, payload: dict[str, object]) -> dict[str, object]:
        return {"chartType": "editor", "results": [{"schema": [], "rows": [[object()]]}]}


def test_chart_data_unsupported_python_cell_is_a_response_error() -> None:
    service = DataService(api=InvalidCellAPI(cast(HTTPClientProtocol, object())))
    with pytest.raises(dl.DTOValidationError, match="getChartData"):
        service.get_chart_data(ChartDataQuery(chart_id="chart-1"))


def test_chart_data_owns_nested_json_cells() -> None:
    nested: dict[str, object] = {"items": [1, {"x": "original"}]}
    raw = {"chartType": "editor", "results": [{"schema": [], "rows": [[nested]]}]}
    result = ChartDataConverter.result(raw)
    nested["items"] = ["changed"]
    assert result.results[0].rows == (({"items": [1, {"x": "original"}]},),)


def test_chart_data_retries_transient_failure() -> None:
    recorder = RecordedTransport(
        [
            httpx.Response(503, json={"message": "transient"}),
            httpx.Response(200, json={"chartType": "ql", "results": []}),
        ]
    )
    assert make_client(recorder).data.get_chart_data(chart_id="chart-1") == dl.QLChartData(results=())
    assert [request.url.path for request in recorder.requests] == ["/rpc/getChartData", "/rpc/getChartData"]
    assert recorder.body(0) == recorder.body(1) == {"chartId": "chart-1"}


def test_chart_data_does_not_retry_422_and_preserves_error_context() -> None:
    recorder = RecordedTransport(
        httpx.Response(
            422,
            json={"code": "SYNTHETIC_TEST_ERROR", "message": "test failure", "details": {"kind": "fixture"}},
            headers={"x-request-id": "request-422"},
        )
    )
    with pytest.raises(dl.DataLensAPIError) as caught:
        make_client(recorder).data.get_chart_data(chart_id="chart-1")
    assert caught.value.context.status_code == 422
    assert caught.value.context.code == "SYNTHETIC_TEST_ERROR"
    assert caught.value.context.details == {"kind": "fixture"}
    assert caught.value.context.request_id == "request-422"
    assert len(recorder.requests) == 1
