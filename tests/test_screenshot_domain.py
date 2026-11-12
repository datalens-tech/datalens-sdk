from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

import datalens_sdk as dl
from datalens_sdk.domain.ports import ChartOperations, DashboardOperations, ScreenshotOperations
from datalens_sdk.domain.screenshot import ScreenshotParams, ScreenshotRequest

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class RecordingOperations:
    def __init__(self) -> None:
        self.requests: list[ScreenshotRequest] = []
        self.url_requests: list[ScreenshotRequest] = []

    def get_screenshot(self, request: ScreenshotRequest) -> dl.EntityScreenshot:
        self.requests.append(request)
        return dl.EntityScreenshot(
            image=PNG_BYTES,
            width=request.width,
            height=request.height,
            params=request.params,
            entity_id=request.entity_id,
            _request=request,
            _operations=cast(ScreenshotOperations, self),
        )

    def get_screenshot_url(self, request: ScreenshotRequest) -> str:
        self.url_requests.append(request)
        return "https://storage.example.test/screenshot.png"


def chart_request(**overrides: object) -> ScreenshotRequest:
    arguments: dict[str, object] = {"entity_kind": "chart", "entity_id": "chart-1", **overrides}
    return ScreenshotRequest.create(**arguments)  # type: ignore[arg-type]


def test_request_merges_params_with_sdk_owned_view_revision_and_tab() -> None:
    request = ScreenshotRequest.create(
        entity_kind="dashboard",
        entity_id="dash-1",
        params={"City": ["Moscow", "Kazan"], "Year": "2026"},
        rev_id="rev-2",
        tab="tab-2",
    )

    assert request.params == {"City": ("Moscow", "Kazan"), "Year": "2026"}
    assert request.query_params() == {
        "City": ["Moscow", "Kazan"],
        "Year": "2026",
        "_embedded": "1",
        "revId": "rev-2",
        "tab": "tab-2",
    }


def test_request_always_renders_the_embedded_page_without_chart_controls() -> None:
    dashboard_request = ScreenshotRequest.create(entity_kind="dashboard", entity_id="dash-1")

    assert chart_request().query_params() == {"_embedded": "1", "_no_controls": "1"}
    assert dashboard_request.query_params() == {"_embedded": "1"}


def test_request_maps_view_arguments_to_page_parameters() -> None:
    request = ScreenshotRequest.create(
        entity_kind="dashboard", entity_id="dash-1", theme="dark", show_title=False, show_tabs=False
    )

    assert chart_request(theme="light").query_params() == {"_embedded": "1", "_no_controls": "1", "_theme": "light"}
    assert request.query_params() == {"_embedded": "1", "_theme": "dark", "_no_title": "1", "_no_tabs": "1"}


def test_request_params_do_not_follow_later_changes_of_the_source_mapping() -> None:
    source = {"City": ["Moscow"]}
    request = chart_request(params=source)
    source["City"].append("Kazan")
    source["Year"] = ["2026"]

    assert request.params == {"City": ("Moscow",)}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"entity_id": None}, "without an id"),
        ({"entity_id": ""}, "without an id"),
        ({"width": 0}, "width must be between 1 and 6000"),
        ({"width": 6001}, "width must be between 1 and 6000"),
        ({"height": -5}, "height must be between 1 and 6000"),
        ({"height": 10.5}, "height must be an integer"),
        ({"width": True}, "width must be an integer"),
        ({"full_page": "yes"}, "full_page must be a boolean"),
        ({"timeout": 0}, "timeout must be a positive"),
        ({"timeout": float("inf")}, "timeout must be a positive"),
        ({"timeout": "120"}, "timeout must be a number"),
        ({"tab": "tab-1"}, "tab must be a non-empty dashboard tab id"),
        ({"params": {"revId": "rev-9"}}, "'revId' is set by the SDK"),
        ({"params": {"_embedded": "0"}}, "'_embedded' is a page view setting owned by the SDK"),
        ({"params": {"_theme": "dark"}}, "'_theme' is a page view setting owned by the SDK"),
        ({"theme": "sepia"}, "theme must be one of"),
        ({"show_title": False}, "apply only to dashboards"),
        ({"show_tabs": "no"}, "must be booleans"),
        ({"params": {"": "x"}}, "names must be non-empty strings"),
        ({"params": {"City": 5}}, "must be a string or a sequence of strings"),
        ({"params": {"City": b"Moscow"}}, "must be a string or a sequence of strings"),
        ({"params": {"City": ["Moscow", 5]}}, "must contain only strings"),
        ({"params": [("City", "Moscow")]}, "params must be a mapping"),
    ],
)
def test_request_rejects_invalid_arguments(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(dl.DataLensValidationError, match=message):
        chart_request(**overrides)


def test_dashboard_request_reserves_tab_but_chart_request_does_not() -> None:
    assert chart_request(params={"tab": "sales"}).query_params()["tab"] == "sales"
    with pytest.raises(dl.DataLensValidationError, match="'tab' is set by the SDK"):
        ScreenshotRequest.create(entity_kind="dashboard", entity_id="dash-1", params={"tab": "tab-1"})
    with pytest.raises(dl.DataLensValidationError, match="tab must be a non-empty dashboard tab id"):
        ScreenshotRequest.create(entity_kind="dashboard", entity_id="dash-1", tab="")


def test_chart_screenshot_uses_default_viewport_and_loaded_revision() -> None:
    operations = RecordingOperations()
    chart = dl.QLChart(id="chart-1", raw={"revId": "rev-7"}, _operations=cast(ChartOperations, operations))
    params: ScreenshotParams = {"Region": "East"}

    screenshot = chart.screenshot(params=params)

    assert operations.requests == [
        ScreenshotRequest(
            entity_kind="chart",
            entity_id="chart-1",
            width=1024,
            height=768,
            params={"Region": "East"},
            rev_id="rev-7",
            timeout=120.0,
        )
    ]
    assert (screenshot.image, screenshot.width, screenshot.height) == (PNG_BYTES, 1024, 768)
    assert screenshot.params == {"Region": "East"}
    assert screenshot.entity_id == "chart-1"


def loaded_dashboard(operations: RecordingOperations) -> dl.Dashboard:
    return dl.Dashboard(
        id="dash-1",
        data={
            "tabs": [{"id": "tab-1", "title": "Overview"}, {"id": "tab-2", "title": "Details"}],
            "settings": {"globalParams": {"region_guid": [], "env": ["prod"]}},
        },
        rev_id="rev-3",
        _operations=cast(DashboardOperations, operations),
    )


def test_dashboard_screenshot_captures_the_full_page_at_default_width() -> None:
    operations = RecordingOperations()

    screenshot = loaded_dashboard(operations).screenshot()

    assert operations.requests == [
        ScreenshotRequest(entity_kind="dashboard", entity_id="dash-1", width=1280, full_page=True, rev_id="rev-3")
    ]
    assert (screenshot.width, screenshot.height) == (1280, None)


def test_dashboard_screenshot_passes_tab_view_and_explicit_options() -> None:
    operations = RecordingOperations()

    loaded_dashboard(operations).screenshot(
        width=1600, tab="tab-2", theme="dark", show_title=False, show_tabs=False, timeout=300
    )

    assert operations.requests == [
        ScreenshotRequest(
            entity_kind="dashboard",
            entity_id="dash-1",
            width=1600,
            full_page=True,
            rev_id="rev-3",
            tab="tab-2",
            theme="dark",
            show_title=False,
            show_tabs=False,
            timeout=300,
        )
    ]


def test_dashboard_screenshot_with_height_cuts_to_the_viewport_unless_full_page_is_requested() -> None:
    operations = RecordingOperations()
    dashboard = loaded_dashboard(operations)

    dashboard.screenshot(height=900)
    dashboard.screenshot(height=900, full_page=True)

    assert [(_.height, _.full_page) for _ in operations.requests] == [(900, False), (900, True)]


def test_dashboard_screenshot_rejects_an_unknown_tab_id_before_http() -> None:
    operations = RecordingOperations()

    with pytest.raises(dl.DataLensValidationError, match=r"Unknown dashboard tab id 'Details'.*'tab-1', 'tab-2'"):
        loaded_dashboard(operations).screenshot(tab="Details")
    assert operations.requests == []


def test_dashboard_screenshot_accepts_only_parameters_declared_in_its_settings() -> None:
    operations = RecordingOperations()
    dashboard = loaded_dashboard(operations)

    dashboard.screenshot(params={"region_guid": ["West", "East"], "env": "test"})

    assert [dict(_.params) for _ in operations.requests] == [{"region_guid": ("West", "East"), "env": "test"}]
    with pytest.raises(
        dl.DataLensValidationError,
        match=r"do not declare parameters \['Region', 'segment'\].*declared parameters: \['env', 'region_guid'\]",
    ):
        dashboard.screenshot(params={"region_guid": "West", "Region": "West", "segment": "Consumer"})
    assert len(operations.requests) == 1


def test_dashboard_screenshot_passes_page_names_reserved_by_datalens_without_declaration() -> None:
    operations = RecordingOperations()
    dashboard = dl.Dashboard(
        id="dash-1", data={"tabs": [{"id": "tab-1"}]}, _operations=cast(DashboardOperations, operations)
    )

    dashboard.screenshot(params={"state": "a1b2c3", "scale": "d", "tz": "UTC"})

    assert [dict(_.params) for _ in operations.requests] == [{"state": "a1b2c3", "scale": "d", "tz": "UTC"}]
    with pytest.raises(dl.DataLensValidationError, match=r"do not declare parameters \['Region'\]"):
        dashboard.screenshot(params={"state": "a1b2c3", "Region": "West"})


def test_dashboard_without_declared_parameters_rejects_any_params_but_reserved_names_fail_first() -> None:
    operations = RecordingOperations()
    dashboard = dl.Dashboard(
        id="dash-1", data={"tabs": [{"id": "tab-1"}]}, _operations=cast(DashboardOperations, operations)
    )

    with pytest.raises(dl.DataLensValidationError, match=r"declared parameters: \[\]"):
        dashboard.screenshot(params={"Region": "West"})
    with pytest.raises(dl.DataLensValidationError, match="'tab' is set by the SDK"):
        dashboard.screenshot(params={"tab": "tab-1"})
    assert dashboard.screenshot().entity_id == "dash-1"
    assert len(operations.requests) == 1


def test_chart_screenshot_passes_the_theme() -> None:
    operations = RecordingOperations()
    chart = dl.QLChart(id="chart-1", _operations=cast(ChartOperations, operations))

    chart.screenshot(width=600, height=320, theme="dark")

    assert operations.requests == [
        ScreenshotRequest(entity_kind="chart", entity_id="chart-1", width=600, height=320, theme="dark")
    ]


def test_unbound_or_unsaved_resources_cannot_take_screenshots() -> None:
    operations = RecordingOperations()

    with pytest.raises(dl.DataLensConfigurationError, match="not bound to client operations"):
        dl.QLChart(id="chart-1").screenshot()
    with pytest.raises(dl.DataLensConfigurationError, match="not bound to client operations"):
        dl.Dashboard(id="dash-1").screenshot()
    with pytest.raises(dl.DataLensValidationError, match="chart without an id"):
        dl.QLChart(id=None, _operations=cast(ChartOperations, operations)).screenshot()
    with pytest.raises(dl.DataLensValidationError, match="dashboard without an id"):
        dl.Dashboard(id=None, _operations=cast(DashboardOperations, operations)).screenshot()
    assert operations.requests == []


def test_screenshot_save_writes_bytes_and_creates_parent_directories(tmp_path: Path) -> None:
    screenshot = RecordingOperations().get_screenshot(chart_request())
    target = tmp_path / "nested" / "out" / "chart.png"

    assert screenshot.save(target) == target
    assert target.read_bytes() == PNG_BYTES
    assert screenshot.save(str(target)) == target


def test_temp_s3_url_repeats_the_original_request_on_every_call() -> None:
    operations = RecordingOperations()
    request = chart_request(width=800, params={"Region": "East"})
    screenshot = operations.get_screenshot(request)

    assert screenshot.get_temp_s3_url() == "https://storage.example.test/screenshot.png"
    assert screenshot.get_temp_s3_url() == "https://storage.example.test/screenshot.png"
    assert operations.url_requests == [request, request]


def test_unbound_screenshot_cannot_request_a_temp_s3_url() -> None:
    request = chart_request()
    screenshot = dl.EntityScreenshot(
        image=PNG_BYTES, width=None, height=None, params={}, entity_id="chart-1", _request=request
    )

    with pytest.raises(dl.DataLensConfigurationError, match="not bound to client operations"):
        screenshot.get_temp_s3_url()


def test_screenshot_repr_does_not_dump_image_bytes() -> None:
    screenshot = RecordingOperations().get_screenshot(chart_request())

    assert "PNG" not in repr(screenshot)
    assert "chart-1" in repr(screenshot)
