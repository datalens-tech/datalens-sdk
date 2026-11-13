from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.api.screenshot import ScreenshotAPI, ScreenshotService
from datalens_sdk.converter.screenshot import ScreenshotDtoModule
from datalens_sdk.domain.screenshot import ScreenshotRequest
from datalens_sdk.http import DataLensHTTPClient

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(32))
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode()
S3_URL = "https://storage.example.test/screenshots/file.png"
ClientClass = type[dl.DataLensClientYC] | type[dl.DataLensClientEnterprise]
CLIENT_CLASSES: list[ClientClass] = [dl.DataLensClientYC, dl.DataLensClientEnterprise]


class RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: list(response) if isinstance(response, list) else [response] for path, response in routes.items()
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responses = self._routes.get(request.url.path)
        if not responses:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": f"Unexpected {request.url.path}"})
        response = responses.pop(0)
        response.request = request
        return response

    def calls(self, path: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == path]

    def bodies(self, path: str) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for request in self.calls(path):
            body: object = json.loads(request.content.decode())
            assert isinstance(body, dict)
            result.append(cast(dict[str, object], body))
        return result


def chart_entry() -> dict[str, object]:
    return {
        "entryId": "chart-1",
        "type": "d3_ql_node",
        "revId": "rev-chart",
        "savedId": "rev-chart",
        "publishedId": "rev-chart",
        "data": {
            "chartType": "sql",
            "type": "ql",
            "version": "7",
            "connection": {"entryId": "c1", "type": "ch_over_yt", "dataExportForbidden": False},
            "queryValue": "SELECT 1",
            "params": [],
            "queries": [],
            "order": None,
            "colors": [],
            "labels": [],
            "shapes": [],
            "tooltips": [],
            "colorsConfig": {},
            "shapesConfig": {},
            "extraSettings": {},
            "geopointsConfig": {},
            "visualization": {"id": "line", "type": "line", "placeholders": []},
        },
        "name": "Sales chart",
        "key": "/Users/me/Sales chart",
    }


def dashboard_entry() -> dict[str, object]:
    return {
        "version": 2,
        "entryId": "dash-1",
        "scope": "dash",
        "type": "",
        "key": "/Users/me/Sales dash",
        "revId": "rev-dash",
        "savedId": "rev-dash",
        "publishedId": "pub-dash",
        "data": {
            "tabs": [
                {"id": "tab-1", "title": "Overview", "items": [{"id": "i1", "type": "widget", "data": {"tabs": []}}]},
                {"id": "tab-2", "title": "Details", "items": [{"id": "i2", "type": "widget", "data": {"tabs": []}}]},
            ],
            "settings": {"globalParams": {"Region": []}},
        },
    }


def screenshot_routes(
    route: str, screenshots: list[httpx.Response] | httpx.Response
) -> dict[str, list[httpx.Response] | httpx.Response]:
    return {
        "/rpc/getQLChart": httpx.Response(200, json=chart_entry()),
        "/rpc/getDashboard": httpx.Response(200, json={"entry": dashboard_entry()}),
        route: screenshots,
    }


def make_client(
    recorder: RecordedTransport, client_cls: ClientClass = dl.DataLensClientYC
) -> dl.DataLensClientYC | dl.DataLensClientEnterprise:
    return client_cls(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


@pytest.mark.parametrize("client_cls", CLIENT_CLASSES)
def test_chart_screenshot_requests_inline_png_of_the_loaded_revision(client_cls: ClientClass) -> None:
    recorder = RecordedTransport(
        screenshot_routes("/rpc/getChartScreenshot", httpx.Response(200, json={"data": PNG_BASE64, "future": 1}))
    )
    chart = make_client(recorder, client_cls).get.ql_chart(by_id="chart-1")

    screenshot = chart.screenshot(params={"City": ["Moscow", "Kazan"], "Year": "2026"})

    assert recorder.bodies("/rpc/getChartScreenshot") == [
        {
            "chartId": "chart-1",
            "type": "png",
            "base64": True,
            "width": 1024,
            "height": 768,
            "queryParams": {
                "City": ["Moscow", "Kazan"],
                "Year": "2026",
                "_embedded": "1",
                "_no_controls": "1",
                "revId": "rev-chart",
            },
        }
    ]
    assert screenshot.image == PNG_BYTES
    assert (screenshot.width, screenshot.height, screenshot.entity_id) == (1024, 768, "chart-1")
    assert screenshot.params == {"City": ("Moscow", "Kazan"), "Year": "2026"}


@pytest.mark.parametrize("client_cls", CLIENT_CLASSES)
def test_dashboard_screenshot_sends_embedded_full_page_view_tab_state_and_revision(client_cls: ClientClass) -> None:
    recorder = RecordedTransport(
        screenshot_routes("/rpc/getDashScreenshot", [httpx.Response(200, json={"data": PNG_BASE64})] * 3)
    )
    dashboard = make_client(recorder, client_cls).get.dashboard(by_id="dash-1")

    default_screenshot = dashboard.screenshot()
    styled_screenshot = dashboard.screenshot(
        width=1600,
        tab="tab-2",
        state="a1b2c3",
        theme="dark",
        show_title=False,
        show_tabs=False,
        params={"Region": "East"},
    )
    dashboard.screenshot(height=900)

    assert recorder.bodies("/rpc/getDashScreenshot") == [
        {
            "dashId": "dash-1",
            "type": "png",
            "base64": True,
            "width": 1280,
            "fullPage": True,
            "queryParams": {"_embedded": "1", "revId": "rev-dash"},
        },
        {
            "dashId": "dash-1",
            "type": "png",
            "base64": True,
            "width": 1600,
            "fullPage": True,
            "queryParams": {
                "Region": "East",
                "_embedded": "1",
                "_theme": "dark",
                "_no_title": "1",
                "_no_tabs": "1",
                "revId": "rev-dash",
                "tab": "tab-2",
                "state": "a1b2c3",
            },
        },
        {
            "dashId": "dash-1",
            "type": "png",
            "base64": True,
            "width": 1280,
            "height": 900,
            "fullPage": False,
            "queryParams": {"_embedded": "1", "revId": "rev-dash"},
        },
    ]
    assert (default_screenshot.width, default_screenshot.height) == (1280, None)
    assert (styled_screenshot.width, styled_screenshot.height) == (1600, None)
    assert styled_screenshot.image == PNG_BYTES


def test_screenshot_save_writes_the_decoded_png(tmp_path: Path) -> None:
    recorder = RecordedTransport(
        screenshot_routes("/rpc/getChartScreenshot", httpx.Response(200, json={"data": PNG_BASE64}))
    )
    chart = make_client(recorder).get.ql_chart(by_id="chart-1")

    saved = chart.screenshot().save(tmp_path / "out" / "chart.png")

    assert saved.read_bytes() == PNG_BYTES


def test_temp_s3_url_repeats_the_request_with_s3_upload_instead_of_base64() -> None:
    recorder = RecordedTransport(
        screenshot_routes(
            "/rpc/getDashScreenshot",
            [httpx.Response(200, json={"data": PNG_BASE64}), httpx.Response(200, json={"data": S3_URL})],
        )
    )
    dashboard = make_client(recorder).get.dashboard(by_id="dash-1")
    screenshot = dashboard.screenshot(width=1280, height=900, tab="tab-1", params={"Region": "East"}, timeout=45)

    url = screenshot.get_temp_s3_url()

    inline_body, s3_body = recorder.bodies("/rpc/getDashScreenshot")
    shared = {
        "dashId": "dash-1",
        "type": "png",
        "width": 1280,
        "height": 900,
        "fullPage": False,
        "queryParams": {"Region": "East", "_embedded": "1", "revId": "rev-dash", "tab": "tab-1"},
    }
    assert inline_body == {**shared, "base64": True}
    assert s3_body == {**shared, "s3": True}
    assert url == S3_URL
    assert screenshot.image == PNG_BYTES
    timeouts = [request.extensions["timeout"]["read"] for request in recorder.calls("/rpc/getDashScreenshot")]
    assert timeouts == [45, 45]


def test_screenshot_timeout_is_applied_and_a_failed_render_is_not_retried() -> None:
    recorder = RecordedTransport(
        screenshot_routes(
            "/rpc/getChartScreenshot",
            [httpx.Response(503, json={"code": "UNAVAILABLE", "message": "render failed"})] * 3,
        )
    )
    chart = make_client(recorder).get.ql_chart(by_id="chart-1")

    with pytest.raises(dl.ServerError):
        chart.screenshot(timeout=7)

    (request,) = recorder.calls("/rpc/getChartScreenshot")
    assert request.extensions["timeout"]["read"] == 7


def test_default_screenshot_timeout_is_longer_than_the_default_request_timeout() -> None:
    recorder = RecordedTransport(
        screenshot_routes("/rpc/getChartScreenshot", httpx.Response(200, json={"data": PNG_BASE64}))
    )
    chart = make_client(recorder).get.ql_chart(by_id="chart-1")

    chart.screenshot()

    (request,) = recorder.calls("/rpc/getChartScreenshot")
    assert request.extensions["timeout"]["read"] == 120


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({}, dl.DTOValidationError),
        ({"data": 123}, dl.DTOValidationError),
        ({"data": "not base64 !!"}, dl.InvalidResponseError),
    ],
)
def test_screenshot_rejects_invalid_responses(response: dict[str, object], error: type[Exception]) -> None:
    recorder = RecordedTransport(screenshot_routes("/rpc/getChartScreenshot", httpx.Response(200, json=response)))
    chart = make_client(recorder).get.ql_chart(by_id="chart-1")

    with pytest.raises(error, match="getChartScreenshot"):
        chart.screenshot()


def test_screenshot_validates_arguments_before_http() -> None:
    recorder = RecordedTransport(screenshot_routes("/rpc/getDashScreenshot", httpx.Response(200, json={})))
    dashboard = make_client(recorder).get.dashboard(by_id="dash-1")

    with pytest.raises(dl.DataLensValidationError, match="'tab' is set by the SDK"):
        dashboard.screenshot(params={"tab": "tab-2"})
    with pytest.raises(dl.DataLensValidationError, match="'revId' is set by the SDK"):
        dashboard.screenshot(params={"revId": "rev-old"})
    with pytest.raises(dl.DataLensValidationError, match="width must be between 1 and 6000"):
        dashboard.screenshot(width=7000)
    with pytest.raises(dl.DataLensValidationError, match="'_embedded' is a page view setting owned by the SDK"):
        dashboard.screenshot(params={"_embedded": "0"})
    with pytest.raises(dl.DataLensValidationError, match="Unknown dashboard tab id 'Details'"):
        dashboard.screenshot(tab="Details")
    with pytest.raises(dl.DataLensValidationError, match=r"do not declare parameters \['Segment'\]"):
        dashboard.screenshot(params={"Region": "East", "Segment": "Consumer"})
    assert recorder.calls("/rpc/getDashScreenshot") == []


def test_screenshot_is_not_supported_when_the_generated_contract_has_no_screenshot_dtos() -> None:
    recorder = RecordedTransport({})
    http = DataLensHTTPClient(
        installation="custom",
        sdk_version="test",
        base_url="http://test",
        transport=httpx.MockTransport(recorder.handler),
    )
    service = ScreenshotService(api=ScreenshotAPI(http), dto_module=cast(ScreenshotDtoModule, object()))
    request = ScreenshotRequest.create(entity_kind="chart", entity_id="chart-1")

    with pytest.raises(dl.NotSupportedError, match="Screenshots are not part of the API contract"):
        service.get_screenshot(request)
    with pytest.raises(dl.NotSupportedError, match="Screenshots are not part of the API contract"):
        service.get_screenshot_url(request)
    assert recorder.requests == []


def rate_limited(retry_after: str | None) -> httpx.Response:
    headers = {} if retry_after is None else {"retry-after": retry_after}
    return httpx.Response(429, headers=headers, json={"message": "Too many requests, please try again later."})


@pytest.mark.parametrize(("retry_after", "expected_wait"), [("7", 7.0), ("0", 1.0)])
def test_screenshot_waits_out_the_rate_limit_named_by_the_server(
    monkeypatch: pytest.MonkeyPatch, retry_after: str, expected_wait: float
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.api.screenshot.time.sleep", sleeps.append)
    recorder = RecordedTransport(
        screenshot_routes(
            "/rpc/getChartScreenshot",
            [rate_limited(retry_after), httpx.Response(200, json={"data": PNG_BASE64})],
        )
    )
    chart = make_client(recorder).get.ql_chart(by_id="chart-1")

    screenshot = chart.screenshot()

    assert screenshot.image == PNG_BYTES
    assert sleeps == [expected_wait]
    first, second = recorder.bodies("/rpc/getChartScreenshot")
    assert first == second


def test_temp_s3_url_waits_out_the_rate_limit_too(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.api.screenshot.time.sleep", sleeps.append)
    recorder = RecordedTransport(
        screenshot_routes(
            "/rpc/getChartScreenshot",
            [
                httpx.Response(200, json={"data": PNG_BASE64}),
                rate_limited("53"),
                httpx.Response(200, json={"data": S3_URL}),
            ],
        )
    )
    chart = make_client(recorder).get.ql_chart(by_id="chart-1")

    assert chart.screenshot().get_temp_s3_url() == S3_URL
    assert sleeps == [53.0]


@pytest.mark.parametrize(
    ("retry_after", "expected_retry_after"),
    [(None, None), ("soon", None), ("500", 500.0)],
)
def test_screenshot_raises_rate_limit_error_when_the_wait_is_unknown_or_exceeds_the_timeout(
    monkeypatch: pytest.MonkeyPatch, retry_after: str | None, expected_retry_after: float | None
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.api.screenshot.time.sleep", sleeps.append)
    recorder = RecordedTransport(
        screenshot_routes(
            "/rpc/getDashScreenshot",
            [rate_limited(retry_after), httpx.Response(200, json={"data": PNG_BASE64})],
        )
    )
    dashboard = make_client(recorder).get.dashboard(by_id="dash-1")

    with pytest.raises(dl.RateLimitError) as raised:
        dashboard.screenshot(timeout=30)

    assert raised.value.context.retry_after == expected_retry_after
    assert sleeps == []
    assert len(recorder.calls("/rpc/getDashScreenshot")) == 1
