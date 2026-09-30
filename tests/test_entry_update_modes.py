from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Literal, cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dashboard_update import DashboardUpdate
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.raw_dashboard import RawDashboardReplace

Client = dl.DataLensClientYC | dl.DataLensClientEnterprise
DashboardBoundary = Literal["typed", "raw"]


class RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: list(response) if isinstance(response, list) else [response] for path, response in routes.items()
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responses = self._routes.get(request.url.path)
        assert responses, f"Unexpected request {request.url.path}"
        response = responses.pop(0)
        response.request = request
        return response

    def bodies(self, path: str) -> list[dict[str, object]]:
        return [
            cast(dict[str, object], json.loads(request.content))
            for request in self.requests
            if request.url.path == path
        ]


def _client(recorder: RecordedTransport, installation: str = "yacloud") -> Client:
    client_type = dl.DataLensClientYC if installation == "yacloud" else dl.DataLensClientEnterprise
    return client_type(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(recorder.handler))


def _dashboard_entry(*, entry_id: str = "target", title: str = "Target A") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "key": f"/Synthetic/{entry_id}",
        "revId": "loaded-revision",
        "savedId": "saved-revision",
        "publishedId": "published-revision",
        "data": {"tabs": [{"id": "tab-1", "title": title, "items": [], "layout": []}]},
    }


def _dashboard_builder(
    client: Client, boundary: DashboardBoundary, *, target: dl.Dashboard | None = None
) -> DashboardUpdate | RawDashboardReplace:
    dashboard = target or dl.Dashboard(
        id="target", installation=client.INSTALLATION, data={"tabs": []}, _operations=client._dashboard_service
    )
    if boundary == "typed":
        return dashboard.update
    return client.raw.replace.dashboard(
        target=dashboard,
        response_snapshot=cast(
            Mapping[str, dl.JsonValue], {"entry": _dashboard_entry(entry_id="source", title="Source B")}
        ),
    )


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
@pytest.mark.parametrize("boundary", ["typed", "raw"])
@pytest.mark.parametrize("mode", ["save", "publish"])
def test_dashboard_mode_and_legacy_publish_serialize_new_content_without_revision_selector(
    installation: str, boundary: DashboardBoundary, mode: EntryUpdateMode
) -> None:
    entry = _dashboard_entry()
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json={"entry": entry}),
            "/rpc/updateDashboard": [httpx.Response(200, json={"entry": entry}) for _ in range(3)],
        }
    )
    client = _client(recorder, installation)
    target = client.get.dashboard(by_id="target")

    _dashboard_builder(client, boundary, target=target).mode(mode).execute(lock_token="lock-token")
    _dashboard_builder(client, boundary, target=target).execute(publish=mode == "publish", lock_token="lock-token")
    _dashboard_builder(client, boundary, target=target).mode(mode).execute(
        publish=mode == "publish", lock_token="lock-token"
    )

    bodies = recorder.bodies("/rpc/updateDashboard")
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["mode"] == mode
    assert bodies[0]["lockToken"] == "lock-token"
    wire_entry = cast(dict[str, object], bodies[0]["entry"])
    assert wire_entry["entryId"] == "target"
    assert not ({"revId", "savedId", "publishedId"} & wire_entry.keys())
    wire_data = cast(dict[str, object], wire_entry["data"])
    expected_title = "Source B" if boundary == "raw" else "Target A"
    assert cast(list[dict[str, object]], wire_data["tabs"])[0]["title"] == expected_title


@pytest.mark.parametrize("boundary", ["typed", "raw"])
@pytest.mark.parametrize("publish", [0, 1, "save", "publish", None, [], {}])
def test_dashboard_publish_rejects_non_bools_before_http(boundary: DashboardBoundary, publish: object) -> None:
    recorder = RecordedTransport({})
    builder = _dashboard_builder(_client(recorder), boundary)

    with pytest.raises(dl.DataLensValidationError, match="publish must be a bool"):
        builder.mode("save").execute(publish=cast(bool, publish))
    assert recorder.requests == []


@pytest.mark.parametrize("boundary", ["typed", "raw"])
@pytest.mark.parametrize("mode", ["save", "publish"])
def test_dashboard_publish_rejects_conflicting_mode_before_http(
    boundary: DashboardBoundary, mode: EntryUpdateMode
) -> None:
    recorder = RecordedTransport({})
    builder = _dashboard_builder(_client(recorder), boundary)

    with pytest.raises(dl.DataLensValidationError, match="conflicts"):
        builder.mode(mode).execute(publish=mode != "publish")
    assert recorder.requests == []


@pytest.mark.parametrize("boundary", ["typed", "raw"])
def test_dashboard_execute_still_requires_an_explicit_choice(boundary: DashboardBoundary) -> None:
    recorder = RecordedTransport({})

    with pytest.raises(TypeError, match="requires"):
        _dashboard_builder(_client(recorder), boundary).execute()
    assert recorder.requests == []


@pytest.mark.parametrize("boundary", ["typed", "raw"])
@pytest.mark.parametrize("mode", ["", "SAVE", True, None])
def test_dashboard_rejects_invalid_mode_before_http(boundary: DashboardBoundary, mode: object) -> None:
    recorder = RecordedTransport({})

    with pytest.raises(dl.DataLensValidationError, match="mode must be"):
        _dashboard_builder(_client(recorder), boundary).mode(cast(EntryUpdateMode, mode))
    assert recorder.requests == []


@pytest.mark.parametrize("through_set", [False, True])
@pytest.mark.parametrize("mode", ["save", "publish"])
def test_connection_rejects_unsupported_mode_before_http(through_set: bool, mode: str) -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    update = dl.Connection(id="connection", type="postgres", _operations=client._connection_service).update

    if through_set:
        with pytest.raises(dl.NotSupportedError, match="Connections do not support"):
            update.set("mode", mode)
    else:
        with pytest.raises(dl.NotSupportedError, match="Connections do not support"):
            update.mode(mode)
    assert recorder.requests == []


EDITOR_TABS = {
    "advanced-chart_node": ("controls", "meta", "params", "prepare", "sources"),
    "control_node": ("controls", "meta", "params", "sources"),
    "d3_node": ("config", "controls", "meta", "params", "prepare", "sources"),
    "markdown_node": ("controls", "meta", "params", "prepare", "sources"),
    "table_node": ("config", "controls", "meta", "params", "prepare", "sources"),
}


def _editor_entry(wire_type: str, *, rev_id: str = "loaded-revision") -> dict[str, object]:
    return {
        "entryId": "editor",
        "type": wire_type,
        "key": "/Synthetic/Editor",
        "revId": rev_id,
        "data": {tab: f"loaded {tab}" for tab in EDITOR_TABS[wire_type]},
        "annotation": {"description": "Loaded description", "future": "preserved"},
    }


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
@pytest.mark.parametrize("wire_type", EDITOR_TABS)
def test_editor_publish_revision_selects_older_revision_and_preserves_loaded_tabs(
    installation: str, wire_type: str
) -> None:
    selected_rev_id = "historical-revision"
    recorder = RecordedTransport(
        {
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_entry(wire_type)),
            "/rpc/updateEditorChart": httpx.Response(200, json=_editor_entry(wire_type, rev_id=selected_rev_id)),
        }
    )
    chart = _client(recorder, installation).get.editor_chart(by_id="editor")

    result = chart.publish_revision(rev_id=selected_rev_id)

    body = recorder.bodies("/rpc/updateEditorChart")[0]
    assert body["mode"] == "publish"
    assert "revId" not in body
    entry = cast(dict[str, object], body["entry"])
    assert entry["entryId"] == "editor"
    assert entry["revId"] == selected_rev_id
    assert entry["type"] == wire_type
    assert entry["data"] == _editor_entry(wire_type)["data"]
    assert entry["annotation"] == _editor_entry(wire_type)["annotation"]
    assert chart.rev_id == "loaded-revision"
    assert result.rev_id == selected_rev_id


@pytest.mark.parametrize("wire_type", EDITOR_TABS)
@pytest.mark.parametrize("edit_content", [False, True])
def test_editor_content_publish_never_includes_revision_selector(wire_type: str, edit_content: bool) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_entry(wire_type)),
            "/rpc/updateEditorChart": httpx.Response(200, json=_editor_entry(wire_type, rev_id="new-revision")),
        }
    )
    chart = _client(recorder).get.editor_chart(by_id="editor")

    update = chart.update
    if edit_content:
        update.sources("new source content")
    result = update.mode("publish").execute()

    body = recorder.bodies("/rpc/updateEditorChart")[0]
    entry = cast(dict[str, object], body["entry"])
    assert body["mode"] == "publish"
    assert "revId" not in entry
    expected_sources = "new source content" if edit_content else "loaded sources"
    assert cast(dict[str, object], entry["data"])["sources"] == expected_sources
    assert result.rev_id == "new-revision"


def _html_entry(*, rev_id: str = "loaded-revision") -> dict[str, object]:
    return {
        "entryId": "html",
        "scope": "artifact",
        "type": "html-page",
        "key": "/Synthetic/HTML",
        "revId": rev_id,
        "savedId": "saved-revision",
        "publishedId": "published-revision",
        "workbookId": None,
        "collectionId": None,
        "data": {},
        "meta": {"objectId": "object", "policyVersion": 1},
        "annotation": {},
        "createdBy": "user",
        "createdAt": "2026-09-30T00:00:00Z",
        "updatedBy": "user",
        "updatedAt": "2026-09-30T00:00:00Z",
        "tenantId": "tenant",
        "hidden": False,
        "version": None,
        "public": False,
    }


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
def test_html_publish_revision_sends_only_older_revision_selector(installation: str) -> None:
    selected_rev_id = "historical-revision"
    recorder = RecordedTransport(
        {
            "/rpc/getHtmlPage": httpx.Response(200, json=_html_entry()),
            "/rpc/updateHtmlPage": httpx.Response(
                200, json={"entry": _html_entry(rev_id=selected_rev_id), "warnings": []}
            ),
        }
    )
    page = _client(recorder, installation).get.html_page(by_id="html")

    result = page.publish_revision(rev_id=selected_rev_id)

    assert recorder.bodies("/rpc/updateHtmlPage") == [{"entryId": "html", "revId": selected_rev_id, "mode": "publish"}]
    assert page.rev_id == "loaded-revision"
    assert result.rev_id == selected_rev_id


@pytest.mark.parametrize("kind", ["editor", "html"])
@pytest.mark.parametrize("rev_id", [None, "", 1])
def test_publish_revision_rejects_absent_or_invalid_revision_before_http(kind: str, rev_id: object) -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    resource = (
        dl.EditorChart(id="editor", _operations=client._chart_service)
        if kind == "editor"
        else dl.HtmlPage(id="html", _operations=client._html_page_service)
    )

    with pytest.raises(dl.DataLensValidationError, match="rev_id must be a non-empty string"):
        resource.publish_revision(rev_id=cast(str, rev_id))
    assert recorder.requests == []


@pytest.mark.parametrize("kind", ["editor", "html"])
def test_publish_revision_unbound_resource_raises_configuration_error(kind: str) -> None:
    resource = dl.EditorChart(id="editor") if kind == "editor" else dl.HtmlPage(id="html")

    with pytest.raises(dl.DataLensConfigurationError):
        resource.publish_revision(rev_id="existing-revision")


@pytest.mark.parametrize("kind", ["editor", "html"])
def test_publish_revision_requires_explicit_id_even_when_current_revision_is_loaded(kind: str) -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    resource = (
        dl.EditorChart(id="editor", raw={"revId": "loaded-revision"}, _operations=client._chart_service)
        if kind == "editor"
        else dl.HtmlPage(id="html", rev_id="loaded-revision", _operations=client._html_page_service)
    )

    with pytest.raises(TypeError, match="rev_id"):
        resource.publish_revision()  # type: ignore[call-arg]
    assert recorder.requests == []


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
def test_html_current_content_publish_has_no_revision_selector(installation: str) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getHtmlPage": httpx.Response(200, json=_html_entry()),
            "/rpc/updateHtmlPage": httpx.Response(
                200, json={"entry": _html_entry(rev_id="new-revision"), "warnings": []}
            ),
        }
    )
    page = _client(recorder, installation).get.html_page(by_id="html")

    result = page.update.content("<p>Authored current content</p>").mode("publish").execute()

    assert recorder.bodies("/rpc/updateHtmlPage") == [
        {"entryId": "html", "content": "<p>Authored current content</p>", "mode": "publish"}
    ]
    assert result.rev_id == "new-revision"
