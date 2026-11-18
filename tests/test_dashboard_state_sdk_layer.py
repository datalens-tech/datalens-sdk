from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dashboard_state import DashboardState
from datalens_sdk.errors import DashboardStateNotFoundError

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
    assert isinstance(state, DashboardState)
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

    with pytest.raises(DashboardStateNotFoundError):
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
