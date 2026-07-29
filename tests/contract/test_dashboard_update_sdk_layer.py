"""SDK-layer contract of the update vertical (D3.4): one-phase publish, meta
and annotation verbatim, lock_token pass-through, immediate LockedError on 423, and the
publish-existing-revision instance method."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"


class _RecordedTransport:
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

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def _fixture_entry() -> dict[str, object]:
    entry: object = json.loads((_FIXTURES_DIR / "global_items_shared_selectors.json").read_text())
    assert isinstance(entry, dict)
    return cast(dict[str, object], entry)


def _updated_entry(entry: dict[str, object]) -> dict[str, object]:
    updated = cast("dict[str, object]", json.loads(json.dumps(entry)))
    updated["revId"] = "rev-new"
    updated["savedId"] = "rev-new"
    updated["publishedId"] = "rev-new"
    return updated


def _client(recorder: _RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def _loaded_dashboard(
    recorder_routes: dict[str, list[httpx.Response] | httpx.Response],
) -> tuple[dl.Dashboard, _RecordedTransport]:
    routes: dict[str, list[httpx.Response] | httpx.Response] = {
        "/rpc/getDashboard": httpx.Response(200, json={"entry": _fixture_entry()}),
    }
    routes.update(recorder_routes)
    recorder = _RecordedTransport(routes)
    dashboard = _client(recorder).get.dashboard(by_id=cast(str, _fixture_entry()["entryId"]))
    return dashboard, recorder


def _entry_payload(recorder: _RecordedTransport, index: int) -> dict[str, object]:
    payload = recorder.request_json(index)
    entry = payload["entry"]
    assert isinstance(entry, dict)
    return cast(dict[str, object], entry)


def test_execute_publish_true_is_one_phase_without_rev_id() -> None:
    entry = _fixture_entry()
    dashboard, recorder = _loaded_dashboard(
        {"/rpc/updateDashboard": httpx.Response(200, json={"entry": _updated_entry(entry)})}
    )

    first_tab_id = cast(str, cast("list[dict[str, object]]", cast("dict[str, object]", entry["data"])["tabs"])[0]["id"])
    result = dashboard.update.hide_tab(first_tab_id).execute(publish=True)

    # exactly ONE update POST — the one-phase nail (D0.4)
    assert recorder.paths() == ["/rpc/getDashboard", "/rpc/updateDashboard"]
    payload = recorder.request_json(1)
    assert payload["mode"] == "publish"
    wire_entry = _entry_payload(recorder, 1)
    assert "revId" not in wire_entry
    assert "lockToken" not in payload
    assert isinstance(result, dl.Dashboard)
    assert result.rev_id == "rev-new"
    assert result.published_id == "rev-new"


def test_execute_publish_false_saves_draft_with_verbatim_data() -> None:
    entry = _fixture_entry()
    dashboard, recorder = _loaded_dashboard(
        {"/rpc/updateDashboard": httpx.Response(200, json={"entry": _updated_entry(entry)})}
    )

    dashboard.update.execute(publish=False)  # empty builder: pure no-op save

    payload = recorder.request_json(1)
    assert payload["mode"] == "save"
    wire_entry = _entry_payload(recorder, 1)
    assert json.dumps(wire_entry["data"], sort_keys=True) == json.dumps(entry["data"], sort_keys=True)
    assert json.dumps(wire_entry["meta"], sort_keys=True) == json.dumps(entry["meta"], sort_keys=True)
    # annotation no-op regression: omission would WIPE it server-side (P0.5b)
    assert json.dumps(wire_entry["annotation"], sort_keys=True) == json.dumps(entry["annotation"], sort_keys=True)


def test_execute_requires_explicit_publish_kwarg() -> None:
    dashboard, _ = _loaded_dashboard({})
    with pytest.raises(TypeError):
        dashboard.update.execute()  # type: ignore[call-arg]


def test_locked_update_raises_immediately_without_retries() -> None:
    # No retry machinery: the lock signal surfaces to the caller as-is
    # (lock acquisition is not exposed by the public API yet).
    dashboard, recorder = _loaded_dashboard(
        {"/rpc/updateDashboard": httpx.Response(423, json={"code": "ERR.US.ENTRY_IS_LOCKED"})}
    )

    with pytest.raises(dl.LockedError):
        dashboard.update.execute(publish=False)

    assert recorder.paths().count("/rpc/updateDashboard") == 1


def test_lock_token_passes_through() -> None:
    dashboard, recorder = _loaded_dashboard(
        {"/rpc/updateDashboard": httpx.Response(423, json={"code": "ERR.US.ENTRY_IS_LOCKED"})}
    )

    with pytest.raises(dl.LockedError):
        dashboard.update.execute(publish=False, lock_token="tok-1")

    assert recorder.request_json(1)["lockToken"] == "tok-1"


def test_publish_existing_revision_sends_rev_id_and_current_data() -> None:
    entry = _fixture_entry()
    dashboard, recorder = _loaded_dashboard(
        {"/rpc/updateDashboard": httpx.Response(200, json={"entry": _updated_entry(entry)})}
    )

    result = dashboard.publish_revision(rev_id="rev-old")

    assert recorder.paths() == ["/rpc/getDashboard", "/rpc/updateDashboard"]
    payload = recorder.request_json(1)
    assert payload["mode"] == "publish"
    wire_entry = _entry_payload(recorder, 1)
    assert wire_entry["revId"] == "rev-old"
    assert json.dumps(wire_entry["data"], sort_keys=True) == json.dumps(entry["data"], sort_keys=True)
    assert isinstance(result, dl.Dashboard)


def test_publish_defaults_to_loaded_rev_id() -> None:
    entry = _fixture_entry()
    dashboard, recorder = _loaded_dashboard(
        {"/rpc/updateDashboard": httpx.Response(200, json={"entry": _updated_entry(entry)})}
    )

    dashboard.publish_revision()

    assert _entry_payload(recorder, 1)["revId"] == entry["revId"]


def test_returned_dashboard_is_bound_and_chainable() -> None:
    entry = _fixture_entry()
    dashboard, recorder = _loaded_dashboard(
        {
            "/rpc/updateDashboard": [
                httpx.Response(200, json={"entry": _updated_entry(entry)}),
                httpx.Response(200, json={"entry": _updated_entry(entry)}),
            ]
        }
    )

    result = dashboard.update.execute(publish=False)
    result.update.execute(publish=True)  # bound: a second update chains

    assert recorder.paths().count("/rpc/updateDashboard") == 2


def test_workbook_dashboard_keeps_name_and_location_after_update() -> None:
    entry = _fixture_entry()
    entry.pop("key", None)
    entry["workbookId"] = "wb-1"
    updated = _updated_entry(entry)
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": entry}),
            "/rpc/updateDashboard": [
                httpx.Response(200, json={"entry": updated}),
                httpx.Response(200, json={"entry": updated}),
            ],
        }
    )
    dashboard = _client(recorder).get.dashboard(by_id=cast(str, entry["entryId"]), workbook_id="wb-1")
    assert dashboard.location is not None

    after_update = dashboard.update.execute(publish=False)
    assert after_update.location == dashboard.location
    assert after_update.name == dashboard.name

    after_publish = dashboard.publish_revision()
    assert after_publish.location == dashboard.location
    assert after_publish.name == dashboard.name


def test_to_spec_then_execute_produces_identical_payloads() -> None:
    entry = _fixture_entry()
    dashboard, recorder = _loaded_dashboard(
        {
            "/rpc/updateDashboard": [
                httpx.Response(200, json={"entry": _updated_entry(entry)}),
                httpx.Response(200, json={"entry": _updated_entry(entry)}),
            ]
        }
    )
    update = dashboard.update.access_description("hello")
    update.to_spec()  # dry-run must not disturb execution

    update.execute(publish=False)
    update.execute(publish=False)

    assert recorder.request_json(1) == recorder.request_json(2)


def test_publish_without_any_rev_id_fails_loud() -> None:
    entry = _fixture_entry()
    entry.pop("revId", None)
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json={"entry": entry})})
    dashboard = _client(recorder).get.dashboard(by_id=cast(str, entry["entryId"]))
    assert dashboard.rev_id is None
    with pytest.raises(dl.DatalensValidationError, match="no rev_id given"):
        dashboard.publish_revision()
    assert recorder.paths() == ["/rpc/getDashboard"]  # nothing was posted


def test_unbound_update_and_publish_raise_configuration_error() -> None:
    entry = _fixture_entry()
    dashboard = dl.Dashboard(
        id="dash-x",
        installation="yacloud",
        data=cast("dict[str, object]", entry["data"]),
        raw=entry,
    )
    with pytest.raises(dl.DatalensConfigurationError):
        dashboard.update.execute(publish=False)
    with pytest.raises(dl.DatalensConfigurationError):
        dashboard.publish_revision(rev_id="rev-1")
