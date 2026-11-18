from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl

FIXTURES = Path(__file__).parent / "contract" / "fixtures" / "dashboard_state"
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

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def bodies(self, path: str) -> list[dict[str, object]]:
        return [
            cast(dict[str, object], json.loads(request.content))
            for request in self.requests
            if request.url.path == path
        ]


def _load(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((FIXTURES / f"{name}.json").read_text()))


def _client(
    client_class: ClientClass, recorder: RecordedTransport
) -> dl.DataLensClientYC | dl.DataLensClientEnterprise:
    return client_class(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(recorder.handler))


@pytest.mark.parametrize("client_class", CLIENT_CLASSES)
def test_get_state_reads_dashboard_and_state(client_class: ClientClass) -> None:
    state_response = _load("state_group_interval_widget_tab")
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _load("dashboard_group_interval_widget_tab")}),
            "/rpc/getEntryState": httpx.Response(200, json=state_response),
        }
    )
    dashboard = _client(client_class, recorder).get.dashboard(by_id="hcnbhimzpyg63")

    state = dashboard.get_state("21e04f18384")

    assert recorder.paths() == ["/rpc/getDashboard", "/rpc/getEntryState"]
    assert recorder.bodies("/rpc/getEntryState") == [{"entryId": "hcnbhimzpyg63", "hash": "21e04f18384"}]
    assert isinstance(state, dl.DashboardState)
    assert state.hash == "21e04f18384"
    assert state.tab_id == "Mk"
    assert state.rev_id == dashboard.rev_id
    assert state.created_at == datetime(2026, 11, 16, 9, 31, 13, 600000, tzinfo=timezone.utc)
    assert [_.item_id for _ in state.selections] == ["6n", "6n", "Wyk", "LEN"]
    assert state.raw == state_response["data"]


def test_get_state_passes_tab_and_strict() -> None:
    state_response = _load("state_group_interval_widget_tab")
    data = cast(dict[str, object], state_response["data"])
    data["__meta__"] = {"queue": [{"id": "Gone"}], "version": 2}
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _load("dashboard_group_interval_widget_tab")}),
            "/rpc/getEntryState": [httpx.Response(200, json=state_response), httpx.Response(200, json=state_response)],
        }
    )
    dashboard = _client(dl.DataLensClientYC, recorder).get.dashboard(by_id="hcnbhimzpyg63")

    with pytest.raises(dl.DataLensValidationError, match="Item 'Gone' is not on tab 'Mk'"):
        dashboard.get_state("21e04f18384", tab="Overview", strict=True)
    with pytest.warns(UserWarning, match="unknown_state_item") as record:
        state = dashboard.get_state("21e04f18384", tab="Mk")

    assert record[0].filename == __file__
    assert state.selections[0].is_orphan


@pytest.mark.parametrize("client_class", CLIENT_CLASSES)
def test_get_state_maps_unknown_hash(client_class: ClientClass) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _load("dashboard_action_params")}),
            "/rpc/getEntryState": httpx.Response(
                404,
                json={"status": 404, "code": "NOT_EXIST_STATE_BY_HASH", "message": "The state by this hash..."},
            ),
        }
    )
    dashboard = _client(client_class, recorder).get.dashboard(by_id="rmxuwz8j1mqmd")

    with pytest.raises(dl.DashboardStateNotFoundError):
        dashboard.get_state("00000000000")


def test_unbound_dashboard_cannot_read_state() -> None:
    dashboard = dl.Dashboard(id="dash-1", data=cast(dict[str, object], _load("dashboard_action_params")["data"]))

    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dashboard.get_state("h")


def test_dashboard_without_id_cannot_read_state() -> None:
    recorder = RecordedTransport({})
    client = _client(dl.DataLensClientYC, recorder)
    dashboard = dl.Dashboard(id=None, _operations=client._dashboard_service)

    with pytest.raises(dl.DataLensValidationError, match="without an id"):
        dashboard.get_state("h")
    assert recorder.requests == []


PNG_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(range(8))).decode()


def _state_client(
    client_class: ClientClass = dl.DataLensClientYC,
    *,
    ui_base_url: str | None = None,
    screenshots: int = 0,
) -> tuple[dl.Dashboard, RecordedTransport]:
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _load("dashboard_action_params")}),
            "/rpc/getEntryState": httpx.Response(200, json=_load("state_action_params")),
            "/rpc/getDashScreenshot": [httpx.Response(200, json={"data": PNG_BASE64}) for _ in range(screenshots)],
        }
    )
    client = client_class(
        auth=None,
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
        ui_base_url=ui_base_url,
    )
    return client.get.dashboard(by_id="rmxuwz8j1mqmd"), recorder


def test_url_uses_yacloud_default_ui_address() -> None:
    dashboard, _ = _state_client()

    assert dashboard.get_state("298725dd251").url() == "https://datalens.ru/rmxuwz8j1mqmd?tab=Ab&state=298725dd251"


@pytest.mark.parametrize("client_class", CLIENT_CLASSES)
def test_url_uses_configured_ui_base_url(client_class: ClientClass) -> None:
    dashboard, _ = _state_client(client_class, ui_base_url="https://datalens.example.test/")

    assert dashboard.get_state("298725dd251").url() == (
        "https://datalens.example.test/rmxuwz8j1mqmd?tab=Ab&state=298725dd251"
    )


def test_url_base_argument_overrides_client_setting() -> None:
    dashboard, _ = _state_client()

    assert dashboard.get_state("298725dd251").url(base="https://ui.test") == (
        "https://ui.test/rmxuwz8j1mqmd?tab=Ab&state=298725dd251"
    )


def test_enterprise_url_requires_ui_base_url() -> None:
    dashboard, _ = _state_client(dl.DataLensClientEnterprise)
    state = dashboard.get_state("298725dd251")

    with pytest.raises(dl.DataLensConfigurationError, match="ui_base_url"):
        state.url()


def test_url_requires_hash() -> None:
    dashboard, _ = _state_client()
    state = dl.DashboardState.from_data(dashboard, cast(dict[str, object], _load("state_action_params")["data"]))

    with pytest.raises(dl.DataLensValidationError, match="no hash"):
        state.url()


def _screenshot_query(recorder: RecordedTransport) -> dict[str, object]:
    return cast(dict[str, object], recorder.bodies("/rpc/getDashScreenshot")[-1]["queryParams"])


def test_screenshot_takes_tab_and_hash_from_state() -> None:
    dashboard, recorder = _state_client(screenshots=2)
    state = dashboard.get_state("298725dd251")

    dashboard.screenshot(state=state)
    assert _screenshot_query(recorder) == {
        "_embedded": "1",
        "revId": "rmxuwz8j1rev1",
        "tab": "Ab",
        "state": "298725dd251",
    }
    dashboard.screenshot(state=state, tab="Ab")
    assert _screenshot_query(recorder)["tab"] == "Ab"


def test_screenshot_rejects_conflicting_tab_and_foreign_state() -> None:
    dashboard, recorder = _state_client()
    state = dashboard.get_state("298725dd251")
    other = dl.Dashboard(id="other-dash", data=dashboard.data, _operations=dashboard._operations)

    with pytest.raises(dl.DataLensValidationError, match="State is for tab 'Ab'"):
        dashboard.screenshot(state=state, tab="Other")
    with pytest.raises(dl.DataLensValidationError, match="belongs to dashboard 'rmxuwz8j1mqmd'"):
        other.screenshot(state=state)
    assert recorder.bodies("/rpc/getDashScreenshot") == []


def test_screenshot_rejects_state_without_hash() -> None:
    dashboard, _ = _state_client()
    state = dl.DashboardState.from_data(dashboard, cast(dict[str, object], _load("state_action_params")["data"]))

    with pytest.raises(dl.DataLensValidationError, match="no hash"):
        dashboard.screenshot(state=state)


def test_screenshot_keeps_string_state() -> None:
    dashboard, recorder = _state_client(screenshots=1)

    dashboard.screenshot(state="abc", tab="Ab")

    assert _screenshot_query(recorder)["state"] == "abc"
