from __future__ import annotations

import json
from pathlib import Path
from typing import cast
import warnings

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.ports import ChartOperations, DashboardOperations, DatasetOperations


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


def _dashboard_entry(*, entry_id: str = "dash-1", key: str | None = "/Users/me/Sales dash") -> dict[str, object]:
    entry: dict[str, object] = {
        "version": 2,
        "entryId": entry_id,
        "scope": "dash",
        "type": "",
        "revId": "rev-1",
        "savedId": "saved-1",
        "publishedId": "pub-1",
        "data": {
            "tabs": [
                {
                    "id": "tab-1",
                    "title": "Overview",
                    "items": [{"id": "item-1", "type": "widget", "data": {"tabs": []}}],
                }
            ]
        },
    }
    if key is not None:
        entry["key"] = key
    return entry


def _client(recorder: _RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def test_get_dashboard_sends_args_and_unwraps_entry_envelope() -> None:
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()})})
    client = _client(recorder)

    dashboard = client.get.dashboard(by_id="dash-1", branch="published")

    assert recorder.request_json(0) == {"dashboardId": "dash-1", "branch": "published"}
    assert isinstance(dashboard, dl.Dashboard)
    assert dashboard.id == "dash-1"
    assert dashboard.name == "Sales dash"
    assert dashboard.location == dl.EntryLocation.path("/Users/me")
    assert dashboard.key == "/Users/me/Sales dash"
    assert dashboard.rev_id == "rev-1"
    assert dashboard.saved_id == "saved-1"
    assert dashboard.published_id == "pub-1"
    assert dashboard.is_draft is True
    assert dashboard.tabs[0].title == "Overview"
    assert dashboard.tabs[0].items[0].item_type == "widget"


def test_get_dashboard_accepts_bare_entry_response() -> None:
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json=_dashboard_entry())})
    client = _client(recorder)

    dashboard = client.get.dashboard(by_id="dash-1")

    assert recorder.request_json(0) == {"dashboardId": "dash-1"}
    assert dashboard.id == "dash-1"
    assert dashboard.name == "Sales dash"


def test_get_dashboard_explicit_rev_id_suppresses_branch_with_warning() -> None:
    recorder = _RecordedTransport(
        {"/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()})},
    )
    client = _client(recorder)

    with pytest.warns(UserWarning, match="branch is ignored") as warning_records:
        client.get.dashboard(by_id="dash-1", branch="saved", rev_id="rev-7")

    payload = recorder.request_json(0)
    assert payload == {"dashboardId": "dash-1", "revId": "rev-7"}
    assert "branch" not in payload
    # The warning must point at the user callsite, not at SDK internals.
    assert warning_records[0].filename == __file__


def test_get_dashboard_rev_id_alone_does_not_warn() -> None:
    recorder = _RecordedTransport(
        {"/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()})},
    )
    client = _client(recorder)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        client.get.dashboard(by_id="dash-1", rev_id="rev-7")

    assert recorder.request_json(0) == {"dashboardId": "dash-1", "revId": "rev-7"}


def test_get_dashboard_in_workbook_maps_workbook_location() -> None:
    entry = _dashboard_entry(key=None)
    entry["name"] = "Sales dash"
    entry["workbookId"] = "workbook-1"
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json={"entry": entry})})
    client = _client(recorder)

    dashboard = client.get.dashboard(by_id="dash-1", workbook_id="workbook-1")

    assert recorder.request_json(0) == {"dashboardId": "dash-1", "workbookId": "workbook-1"}
    assert dashboard.workbook_id == "workbook-1"
    assert dashboard.location == dl.EntryLocation.workbook("workbook-1")
    assert dashboard.name == "Sales dash"


def test_dashboard_delete_sends_lock_token() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()}),
            "/rpc/deleteDashboard": httpx.Response(200),
        }
    )
    client = _client(recorder)

    dashboard = client.get.dashboard(by_id="dash-1")
    dashboard.delete(lock_token="lock-1")

    assert recorder.paths() == ["/rpc/getDashboard", "/rpc/deleteDashboard"]
    assert recorder.request_json(1) == {"dashboardId": "dash-1", "lockToken": "lock-1"}


def test_dashboard_delete_without_lock_token_sends_only_id() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()}),
            "/rpc/deleteDashboard": httpx.Response(200),
        }
    )
    client = _client(recorder)

    client.get.dashboard(by_id="dash-1").delete()

    assert recorder.request_json(1) == {"dashboardId": "dash-1"}


def test_dashboard_refresh_rereads_without_branch_or_rev_id() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": [
                httpx.Response(200, json={"entry": _dashboard_entry()}),
                httpx.Response(200, json={"entry": _dashboard_entry()}),
            ]
        }
    )
    client = _client(recorder)

    with pytest.warns(UserWarning, match="branch is ignored"):
        dashboard = client.get.dashboard(by_id="dash-1", branch="published", rev_id="rev-7")
    refreshed = dashboard.refresh()

    assert isinstance(refreshed, dl.Dashboard)
    assert recorder.request_json(1) == {"dashboardId": "dash-1"}


@pytest.mark.parametrize(
    "payload",
    [
        {"entry": None},
        {"entry": {}},
        {"entry": "not-an-object"},
        {"entry": [{"entryId": "dash-1"}]},
        {},
    ],
)
def test_get_dashboard_malformed_envelope_translates_to_invalid_response_error(payload: object) -> None:
    # GetDashboardV2Result requires entry with entryId/data: a malformed 200 must
    # not masquerade as a successfully loaded dashboard.
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json=payload)})
    client = _client(recorder)

    with pytest.raises(dl.InvalidResponseError, match="getDashboard"):
        client.get.dashboard(by_id="dash-1")


@pytest.mark.parametrize("id_key", ["id", "entry_id"])
def test_get_dashboard_non_canonical_id_key_translates_to_invalid_response_error(id_key: str) -> None:
    # DashboardV2 identity is the canonical entryId; a generic id/entry_id must
    # not bind a malformed 200 into a working Dashboard (PR review finding).
    entry = _dashboard_entry()
    entry[id_key] = entry.pop("entryId")
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json={"entry": entry})})
    client = _client(recorder)

    with pytest.raises(dl.InvalidResponseError, match="dashboard id"):
        client.get.dashboard(by_id="dash-1")


def test_get_dashboard_entry_without_data_translates_to_invalid_response_error() -> None:
    recorder = _RecordedTransport(
        {"/rpc/getDashboard": httpx.Response(200, json={"entry": {"entryId": "dash-1", "key": "/Users/me/Dash"}})}
    )
    client = _client(recorder)

    with pytest.raises(dl.InvalidResponseError, match="dashboard data"):
        client.get.dashboard(by_id="dash-1")


def test_get_dashboard_corrupt_entry_translates_to_dto_validation_error() -> None:
    recorder = _RecordedTransport(
        {"/rpc/getDashboard": httpx.Response(200, json={"entry": {"entryId": 123, "data": "not-a-dict"}})}
    )
    client = _client(recorder)

    with pytest.raises(dl.DTOValidationError, match="getDashboard"):
        client.get.dashboard(by_id="dash-1")


def test_dashboard_get_relations_delegates_to_navigation() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()}),
            "/rpc/getEntriesRelations": httpx.Response(
                200,
                json={
                    "relations": [
                        {"entryId": "chart-1", "scope": "widget", "type": "graph_wizard_node", "key": "folder/Chart"}
                    ]
                },
            ),
        }
    )
    client = _client(recorder)
    dashboard = client.get.dashboard(by_id="dash-1")

    relations = list(dashboard.get_relations(link_direction="from", page_size=20, scope="widget"))

    assert [relation.id for relation in relations] == ["chart-1"]
    body = recorder.request_json(1)
    assert body["entryIds"] == ["dash-1"]
    assert body["limit"] == 20
    assert body["linkDirection"] == "from"
    assert body["scope"] == "widget"


# 409/423 bodies below mirror live /rpc v2 responses captured 2026-07-18.
# On v2 the only observed dashboard 409 is a duplicate key on create
# (ERR.US.ENTRY_ALREADY_EXISTS); a stale revId on update returns 200 with a
# new revision, so there is no revision-mismatch 409 to translate.
_LIVE_CONFLICT_BODY: dict[str, object] = {
    "status": 409,
    "code": "ERR.US.ENTRY_ALREADY_EXISTS",
    "message": "The entry already exists",
    "requestId": "26e14972-f26f-4e8a-b105-85ff8128224a",
    "details": {
        "title": "ERR.US.ENTRY_ALREADY_EXISTS",
        "description": "The entry already exists",
        "entryId": "dash-1",
    },
}

_LIVE_LOCKED_BODY: dict[str, object] = {
    "status": 423,
    "code": "ERR.US.ENTRY_IS_LOCKED",
    "message": "The entry is locked",
    "requestId": "d86cf3b2-a6d4-4462-841c-0a94aa8f3f25",
    "details": {
        "title": "ERR.US.ENTRY_IS_LOCKED",
        "description": "The entry is locked",
        "entryId": "dash-1",
        "loginOrId": "robot-user",
        "expiryDate": "2026-07-18T10:12:31.000Z",
    },
}


def test_dashboard_conflict_translates_to_conflict_error() -> None:
    recorder = _RecordedTransport({"/rpc/getDashboard": httpx.Response(409, json=_LIVE_CONFLICT_BODY)})
    client = _client(recorder)

    with pytest.raises(dl.ConflictError) as conflict_exc:
        client.get.dashboard(by_id="dash-1")

    assert conflict_exc.value.context.status_code == 409
    assert conflict_exc.value.context.code == "ERR.US.ENTRY_ALREADY_EXISTS"
    assert conflict_exc.value.context.details == _LIVE_CONFLICT_BODY["details"]


def test_dashboard_delete_conflict_translates_to_conflict_error() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()}),
            "/rpc/deleteDashboard": httpx.Response(409, json=_LIVE_CONFLICT_BODY),
        }
    )
    client = _client(recorder)
    dashboard = client.get.dashboard(by_id="dash-1")

    with pytest.raises(dl.ConflictError) as conflict_exc:
        dashboard.delete(lock_token="lock-1")

    assert conflict_exc.value.context.status_code == 409


def test_dashboard_locked_translates_to_locked_error() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": _dashboard_entry()}),
            "/rpc/deleteDashboard": httpx.Response(
                423,
                json=_LIVE_LOCKED_BODY,
                headers={"x-request-id": "d86cf3b2-a6d4-4462-841c-0a94aa8f3f25"},
            ),
        }
    )
    client = _client(recorder)
    dashboard = client.get.dashboard(by_id="dash-1")

    with pytest.raises(dl.LockedError) as locked_exc:
        dashboard.delete()

    assert locked_exc.value.context.status_code == 423
    assert locked_exc.value.context.code == "ERR.US.ENTRY_IS_LOCKED"
    assert locked_exc.value.context.request_id == "d86cf3b2-a6d4-4462-841c-0a94aa8f3f25"
    assert locked_exc.value.context.details == _LIVE_LOCKED_BODY["details"]


# -- create vertical (D2.5) ---------------------------------------------------------


def _created_entry(*, entry_id: str = "dash-new", key: str | None = "/Users/me/New dash") -> dict[str, object]:
    entry = _dashboard_entry(entry_id=entry_id, key=key)
    entry["revId"] = entry["savedId"] = entry["publishedId"] = "rev-created"
    return entry


def test_create_dashboard_posts_payload_and_returns_dashboard() -> None:
    recorder = _RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json={"entry": _created_entry()})})
    client = _client(recorder)

    dashboard = (
        client.create.dashboard(name="New dash", location=dl.EntryLocation.path("/Users/me"))
        .add_tab(dl.DashboardTab("Tab 1").add_text("hello", at=(0, 0, 12, 6)))
        .build()
    )

    assert recorder.paths() == ["/rpc/createDashboard"]
    payload = recorder.request_json(0)
    entry = cast(dict[str, object], payload["entry"])
    assert entry["key"] == "/Users/me/New dash"
    assert "name" not in entry
    assert "workbookId" not in entry
    assert isinstance(dashboard, dl.Dashboard)
    assert dashboard.id == "dash-new"
    assert dashboard.rev_id == "rev-created"


def test_create_dashboard_wire_keeps_required_nullable_nulls() -> None:
    recorder = _RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json={"entry": _created_entry()})})
    client = _client(recorder)

    client.create.dashboard(name="New dash", location=dl.EntryLocation.path("/Users/me")).build()

    entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    assert "meta" in entry
    assert entry["meta"] is None
    data = cast(dict[str, object], entry["data"])
    settings = cast(dict[str, object], data["settings"])
    assert settings["autoupdateInterval"] is None
    assert settings["maxConcurrentRequests"] is None


def test_create_dashboard_description_goes_to_annotation() -> None:
    recorder = _RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json={"entry": _created_entry()})})
    client = _client(recorder)

    client.create.dashboard(name="New dash", location=dl.EntryLocation.path("/Users/me")).description(
        "Main channel"
    ).build()

    entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    assert entry["annotation"] == {"description": "Main channel"}
    assert "description" not in cast(dict[str, object], entry["data"])


def test_create_dashboard_workbook_location_sends_name_and_workbook_id() -> None:
    recorder = _RecordedTransport(
        {"/rpc/createDashboard": httpx.Response(200, json={"entry": _created_entry(key=None)})}
    )
    client = _client(recorder)

    dashboard = client.create.dashboard(name="New dash", location=dl.EntryLocation.workbook("wb-1")).build()

    entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    assert "key" not in entry
    assert entry["name"] == "New dash"
    assert entry["workbookId"] == "wb-1"
    # keyless workbook entry falls back to the builder's name and location
    assert dashboard.name == "New dash"
    assert dashboard.location == dl.EntryLocation.workbook("wb-1")


def test_create_dashboard_rejects_collection_location_before_http() -> None:
    recorder = _RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(dl.DataLensValidationError, match="location kind"):
        client.create.dashboard(name="New dash", location=dl.EntryLocation.collection("col-1"))

    assert recorder.paths() == []


def test_create_dashboard_malformed_200_raises_invalid_response() -> None:
    recorder = _RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json={"entry": {"scope": "dash"}})})
    client = _client(recorder)

    with pytest.raises(dl.InvalidResponseError, match="createDashboard"):
        client.create.dashboard(name="New dash", location=dl.EntryLocation.path("/Users/me")).build()


def test_create_dashboard_conflict_translates_to_conflict_error() -> None:
    recorder = _RecordedTransport({"/rpc/createDashboard": httpx.Response(409, json=_LIVE_CONFLICT_BODY)})
    client = _client(recorder)

    with pytest.raises(dl.ConflictError) as conflict_exc:
        client.create.dashboard(name="New dash", location=dl.EntryLocation.path("/Users/me")).build()

    assert conflict_exc.value.context.status_code == 409
    assert conflict_exc.value.context.code == "ERR.US.ENTRY_ALREADY_EXISTS"


def test_create_dashboard_full_scenario_matches_golden_payload() -> None:
    recorder = _RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json={"entry": _created_entry()})})
    client = _client(recorder)

    overview = (
        dl.DashboardTab("Overview")
        .add_title("Sales overview", at=(0, 0, 36, 2), show_in_toc=True, text_color="#027bfeb3")
        .add_chart(
            "ch-single",
            title="Sales dynamics",
            at=(0, 2, 24, 12),
            params={"region": "RU"},
            description="Weekly numbers",
        )
        .add_chart_group(
            [
                dl.DashboardChartTab(chart="ch-plan", title="Plan"),
                dl.DashboardChartTab(
                    chart="ch-fact",
                    title="Fact",
                    default=True,
                    auto_height=True,
                    params={"mode": ["fact", "raw"]},
                ),
            ],
            at=(24, 2, 12, 12),
            show_title=False,
            background=dl.ThemedColor(light="#ffffff", dark="#000000"),
        )
        .add_text("**Notes** for the overview", at=(0, 14, 36, 4), background="#E0F7FA")
    )
    details = (
        dl.DashboardTab("Details")
        .add_section_divider("Raw data", at=(0, 0, 36, 2))
        .add_image(src="https://img.test/logo.png", alt="Logo", at=(0, 2, 12, 6), pinned=True)
    )
    builder = client.create.dashboard(name="Snapshot Dash", location=dl.EntryLocation.path("/Users/me"))
    (
        builder.add_tab(overview)
        .add_tab(details)
        .description("Snapshot dashboard")
        .access_description("Ask BI team")
        .support_description("Contact support")
        .settings(hide_tabs=True)
    )
    builder.build()

    golden_path = Path(__file__).parent / "fixtures" / "dashboard_create" / "full_scenario_payload.json"
    golden = json.loads(golden_path.read_text())
    assert recorder.request_json(0) == golden


# -- typed port accessors (epic D4, stage 18) ---------------------------------------


def test_client_port_accessors_satisfy_runtime_checkable_protocols() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    assert isinstance(client.dashboard_ops, DashboardOperations)
    assert isinstance(client.chart_ops, ChartOperations)
    assert isinstance(client.dataset_ops, DatasetOperations)
