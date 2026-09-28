from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl


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

    def bodies(self, path: str) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for request in self.requests:
            if request.url.path != path:
                continue
            body: object = json.loads(request.content.decode())
            assert isinstance(body, dict)
            result.append(cast(dict[str, object], body))
        return result


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def _entry(*, key: str = "/Pages/Example", rev_id: str = "rev-1", workbook_id: str | None = None) -> dict[str, object]:
    return {
        "entryId": "page-1",
        "scope": "artifact",
        "type": "html-page",
        "key": key,
        "workbookId": workbook_id,
        "collectionId": None,
        "revId": rev_id,
        "savedId": "saved-1",
        "publishedId": "published-1",
        "data": {},
        "meta": {"objectId": "object-1", "policyVersion": 1},
        "annotation": {"description": "Example page"},
        "createdBy": "user-1",
        "createdAt": "2026-01-01T00:00:00.000Z",
        "updatedBy": "user-1",
        "updatedAt": "2026-01-02T00:00:00.000Z",
        "tenantId": "tenant-1",
        "hidden": False,
        "version": None,
        "public": False,
        "isFavorite": True,
        "permissions": {"execute": True, "read": True, "edit": True, "admin": False},
    }


def test_html_page_create_get_update_and_delete_use_contract_routes() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createHtmlPage": [
                httpx.Response(200, json={"entry": _entry(), "warnings": ["HTML_CSP_INJECTED"]}),
                httpx.Response(200, json={"entry": _entry(key="", workbook_id="workbook-1"), "warnings": []}),
            ],
            "/rpc/getHtmlPage": [
                httpx.Response(200, json=_entry()),
                httpx.Response(200, json=_entry(rev_id="rev-2")),
            ],
            "/rpc/updateHtmlPage": [
                httpx.Response(200, json={"entry": _entry(rev_id="rev-3"), "warnings": ["HTML_REWRITTEN"]}),
                httpx.Response(200, json={"entry": _entry(rev_id="rev-4"), "warnings": []}),
            ],
            "/rpc/deleteHtmlPage": httpx.Response(200, json={}),
        }
    )
    client = _client(recorder)

    page = (
        client.create.html_page(name="Example", location=dl.EntryLocation.path("/Pages"))
        .content("<h1>Example</h1>")
        .description("Example page")
        .build()
    )
    workbook_page = (
        client.create.html_page(name="Workbook page", location=dl.EntryLocation.workbook("workbook-1"))
        .content("<h1>Workbook</h1>")
        .build()
    )
    loaded = client.get.html_page(
        by_id="page-1",
        branch="published",
        include_favorite=True,
        include_permissions=True,
    )
    with pytest.warns(UserWarning, match="branch is ignored"):
        pinned = client.get.html_page(by_id="page-1", branch="saved", rev_id="rev-2")
    content_update = page.update.content("<h1>Changed</h1>").description("Changed").mode("publish").execute()
    revision_update = page.update.revision("rev-2").mode("save").execute()
    page.delete()

    assert isinstance(page, dl.HtmlPage)
    assert page.name == "Example"
    assert page.location == dl.EntryLocation.path("/Pages")
    assert page.dir_path == "/Pages"
    assert page.key == "/Pages/Example"
    assert page.warnings == ("HTML_CSP_INJECTED",)
    assert page.object_id == "object-1"
    assert page.policy_version == 1.0
    assert page.version is None
    assert page.data == {}
    assert not hasattr(page, "content")
    assert workbook_page.name == "Workbook page"
    assert workbook_page.workbook_id == "workbook-1"
    assert loaded.rev_id == "rev-1"
    assert loaded.saved_id == "saved-1"
    assert loaded.published_id == "published-1"
    assert loaded.is_favorite is True
    assert loaded.permissions == dl.HtmlPagePermissions(execute=True, read=True, edit=True, admin=False)
    assert pinned.rev_id == "rev-2"
    assert content_update.warnings == ("HTML_REWRITTEN",)
    assert revision_update.warnings == ()
    assert recorder.bodies("/rpc/createHtmlPage") == [
        {"key": "/Pages/Example", "content": "<h1>Example</h1>", "annotation": {"description": "Example page"}},
        {"name": "Workbook page", "workbookId": "workbook-1", "content": "<h1>Workbook</h1>"},
    ]
    assert recorder.bodies("/rpc/getHtmlPage") == [
        {"entryId": "page-1", "branch": "published", "includeFavorite": True, "includePermissions": True},
        {"entryId": "page-1", "revId": "rev-2"},
    ]
    assert recorder.bodies("/rpc/updateHtmlPage") == [
        {
            "entryId": "page-1",
            "content": "<h1>Changed</h1>",
            "mode": "publish",
            "annotation": {"description": "Changed"},
        },
        {"entryId": "page-1", "revId": "rev-2", "mode": "save"},
    ]
    assert recorder.bodies("/rpc/deleteHtmlPage") == [{"entryId": "page-1"}]


def test_html_page_builder_rejects_unsupported_locations_and_mixed_update_branches() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    with pytest.raises(dl.DataLensValidationError, match="requires location kind"):
        client.create.html_page(name="Page", location=dl.EntryLocation.collection("collection-1"))
    with pytest.raises(dl.DataLensValidationError, match="requires content"):
        client.create.html_page(name="Page", location=dl.EntryLocation.path("/Pages")).build()
    with pytest.raises(dl.DataLensValidationError, match="UTF-8 content"):
        client.create.html_page(name="Page", location=dl.EntryLocation.path("/Pages")).content("é" * 5242881)

    page = dl.HtmlPage(id="page-1", name="Page", location=dl.EntryLocation.path("/Pages"))
    with pytest.raises(dl.DataLensValidationError, match="cannot combine"):
        page.update.content("<p>x</p>").revision("rev-1")
    with pytest.raises(dl.DataLensValidationError, match="cannot combine"):
        page.update.revision("rev-1").content("<p>x</p>")
    with pytest.raises(dl.DataLensValidationError, match="cannot combine"):
        page.update.description("Notes").revision("rev-1")
    with pytest.raises(dl.DataLensValidationError, match="cannot include description"):
        page.update.revision("rev-1").description("Notes")
    with pytest.raises(dl.DataLensValidationError, match="requires content or rev_id"):
        page.update.to_spec()
    assert recorder.requests == []


@pytest.mark.parametrize("client_type", [dl.DataLensClientEnterprise, dl.DataLensClientYC])
def test_workbook_html_page_preserves_name_and_location_across_reads_and_updates(
    client_type: type[dl.DataLensClientEnterprise] | type[dl.DataLensClientYC],
) -> None:
    entry = _entry(key="", workbook_id="workbook-1")
    updated_entry = _entry(key="", rev_id="rev-2")
    recorder = RecordedTransport(
        {
            "/rpc/createHtmlPage": httpx.Response(200, json={"entry": entry, "warnings": []}),
            "/rpc/getHtmlPage": httpx.Response(200, json=entry),
            "/rpc/getEntries": httpx.Response(200, json={"entries": [{**entry, "name": "Workbook page"}]}),
            "/rpc/updateHtmlPage": [
                httpx.Response(200, json={"entry": updated_entry, "warnings": []}),
                httpx.Response(200, json={"entry": updated_entry, "warnings": []}),
            ],
        }
    )
    with client_type(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler)) as client:
        created = (
            client.create.html_page(name="Workbook page", location=dl.EntryLocation.workbook("workbook-1"))
            .content("<h1>Initial</h1>")
            .build()
        )
        loaded = client.get.html_page(by_id=created.id, branch="saved")
        updated = loaded.update.content("<h1>Updated</h1>").execute()
        published = updated.update.revision("rev-2").mode("publish").execute()

    for page in (created, loaded, updated, published):
        assert page.name == "Workbook page"
        assert page.key is None
        assert page.dir_path is None
        assert page.location == dl.EntryLocation.workbook("workbook-1")
        assert page.workbook_id == "workbook-1"
        assert page.collection_id is None
    assert recorder.bodies("/rpc/createHtmlPage") == [
        {"name": "Workbook page", "workbookId": "workbook-1", "content": "<h1>Initial</h1>"}
    ]
    assert recorder.bodies("/rpc/getHtmlPage") == [
        {"entryId": "page-1", "branch": "saved"},
    ]
    assert recorder.bodies("/rpc/getEntries") == [{"ids": ["page-1"], "ignoreWorkbookEntries": False, "pageSize": 1}]
    assert recorder.bodies("/rpc/updateHtmlPage") == [
        {"entryId": "page-1", "content": "<h1>Updated</h1>", "mode": "save"},
        {"entryId": "page-1", "revId": "rev-2", "mode": "publish"},
    ]


@pytest.mark.parametrize(("key", "workbook_id"), [("/Pages/Old name", None), ("", "workbook-1")])
def test_html_page_read_uses_response_name_without_navigation(key: str, workbook_id: str | None) -> None:
    entry = {**_entry(key=key, workbook_id=workbook_id), "name": "Current name"}
    recorder = RecordedTransport({"/rpc/getHtmlPage": httpx.Response(200, json=entry)})
    with _client(recorder) as client:
        page = client.get.html_page(by_id="page-1")
    assert page.name == "Current name"
    assert recorder.bodies("/rpc/getHtmlPage") == [{"entryId": "page-1"}]
    assert recorder.bodies("/rpc/getEntries") == []


@pytest.mark.parametrize("entry_id", [None, "unrelated-page"])
def test_html_page_read_does_not_invent_a_missing_workbook_name(entry_id: str | None) -> None:
    entries = (
        [] if entry_id is None else [{"entryId": entry_id, "scope": "artifact", "type": "html-page", "name": "Other"}]
    )
    recorder = RecordedTransport(
        {
            "/rpc/getHtmlPage": httpx.Response(200, json=_entry(key="", workbook_id="workbook-1")),
            "/rpc/getEntries": httpx.Response(200, json={"entries": entries}),
        }
    )
    with _client(recorder) as client:
        page = client.get.html_page(by_id="page-1")
    assert page.name is None
    assert page.workbook_id == "workbook-1"


@pytest.mark.parametrize("operation", ["createHtmlPage", "getHtmlPage", "updateHtmlPage"])
@pytest.mark.parametrize(("field", "value"), [("scope", "widget"), ("type", "other-artifact")])
def test_html_page_rejects_responses_for_other_entry_types(operation: str, field: str, value: str) -> None:
    entry = _entry()
    entry[field] = value
    response = entry if operation == "getHtmlPage" else {"entry": entry, "warnings": []}
    routes: dict[str, list[httpx.Response] | httpx.Response] = {f"/rpc/{operation}": httpx.Response(200, json=response)}
    if operation == "updateHtmlPage":
        routes["/rpc/getHtmlPage"] = httpx.Response(200, json=_entry())
    recorder = RecordedTransport(routes)
    with _client(recorder) as client:
        if operation == "createHtmlPage":
            with pytest.raises(dl.DTOValidationError):
                client.create.html_page(name="Page", location=dl.EntryLocation.path("/Pages")).content(
                    "<p>x</p>"
                ).build()
        elif operation == "getHtmlPage":
            with pytest.raises(dl.DTOValidationError):
                client.get.html_page(by_id="page-1")
        else:
            page = client.get.html_page(by_id="page-1")
            with pytest.raises(dl.DTOValidationError):
                page.update.content("<p>x</p>").execute()
