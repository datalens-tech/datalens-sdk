from __future__ import annotations

import json

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.collection import Collection
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.folder import Folder
from datalens_sdk.domain.navigation import CollectionSummary, EntrySummary, WorkbookSummary
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.domain.workbook import Workbook
from datalens_sdk.errors import DataLensConfigurationError


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
            return httpx.Response(404, json={"message": f"Unexpected {request.url.path}"})
        response = responses.pop(0)
        response.request = request
        return response

    def bodies(self, path: str) -> list[dict[str, object]]:
        return [json.loads(request.content) for request in self.requests if request.url.path == path]


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(
        auth=None,
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    )


def _entry(entry_id: str, *, name: str = "Entry", type: str = "chart_node") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "scope": "widget",
        "type": type,
        "name": name,
        "key": f"folder/{name}",
    }


def test_get_entries_is_lazy_typed_and_reiterable() -> None:
    responses = [
        httpx.Response(
            200,
            json={
                "entries": [
                    {
                        **_entry("entry-1"),
                        "data": {"visualization": "line"},
                        "links": {"self": "/entries/entry-1"},
                    }
                ],
                "nextPageToken": "next-1",
            },
        ),
        httpx.Response(200, json={"entries": [_entry("entry-2")]}),
        httpx.Response(200, json={"entries": [_entry("entry-1")], "nextPageToken": "next-1"}),
        httpx.Response(200, json={"entries": [_entry("entry-2")]}),
    ]
    recorder = RecordedTransport({"/rpc/getEntries": responses})
    pager = _client(recorder).navigation.get_entries(
        ids=["entry-1", "entry-2"],
        created_by=["user-1"],
        name="Entry",
        exclude_locked=True,
        ignore_shared_entries=False,
        ignore_workbook_entries=True,
        include_data=False,
        include_links=True,
        include_permissions_info=True,
        order_by="created_at",
        order_direction="desc",
        page_size=2,
        scope="widget",
        type="chart_node",
    )

    assert recorder.requests == []
    first_traversal = list(pager)
    second_traversal = list(pager)
    assert [entry.id for entry in first_traversal] == ["entry-1", "entry-2"]
    assert [entry.id for entry in second_traversal] == ["entry-1", "entry-2"]
    assert all(isinstance(entry, EntrySummary) for entry in first_traversal)
    assert first_traversal[0].data == {"visualization": "line"}
    assert first_traversal[0].links == {"self": "/entries/entry-1"}
    assert recorder.bodies("/rpc/getEntries")[:2] == [
        {
            "pageSize": 2,
            "ids": ["entry-1", "entry-2"],
            "createdBy": ["user-1"],
            "filters": {"name": "Entry"},
            "excludeLocked": True,
            "ignoreSharedEntries": False,
            "ignoreWorkbookEntries": True,
            "includeData": False,
            "includeLinks": True,
            "includePermissionsInfo": True,
            "orderBy": {"field": "createdAt", "direction": "desc"},
            "scope": "widget",
            "type": "chart_node",
        },
        {
            "pageSize": 2,
            "ids": ["entry-1", "entry-2"],
            "createdBy": ["user-1"],
            "filters": {"name": "Entry"},
            "excludeLocked": True,
            "ignoreSharedEntries": False,
            "ignoreWorkbookEntries": True,
            "includeData": False,
            "includeLinks": True,
            "includePermissionsInfo": True,
            "orderBy": {"field": "createdAt", "direction": "desc"},
            "pageToken": "next-1",
            "scope": "widget",
            "type": "chart_node",
        },
    ]


def test_folder_list_entries_exposes_directory_pages_and_breadcrumbs() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/listDirectory": [
                httpx.Response(
                    200,
                    json={
                        "entries": [_entry("entry-1")],
                        "breadCrumbs": [
                            {
                                "entryId": "folder-1",
                                "title": "Folder",
                                "path": "folder/",
                                "isLocked": False,
                                "permissions": {"read": True},
                            }
                        ],
                        "hasNextPage": True,
                    },
                ),
                httpx.Response(
                    200,
                    json={"entries": [_entry("entry-2")], "breadCrumbs": [], "hasNextPage": False},
                ),
            ]
        }
    )
    client = _client(recorder)
    folder = Folder(
        id="folder-1",
        name="Folder",
        key="folder/",
        installation="yacloud",
        _operations=client._folder_service,
    )

    pages = list(folder.list_entries(name="Entry", order_by="name", page_size=1).pages())

    assert [[entry.id for entry in page.items] for page in pages] == [["entry-1"], ["entry-2"]]
    assert pages[0].breadcrumbs[0].name == "Folder"
    assert recorder.bodies("/rpc/listDirectory") == [
        {
            "path": "folder/",
            "page": 0,
            "pageSize": 1,
            "filters": {"name": "Entry"},
            "orderBy": {"field": "name", "direction": "asc"},
        },
        {
            "path": "folder/",
            "page": 1,
            "pageSize": 1,
            "filters": {"name": "Entry"},
            "orderBy": {"field": "name", "direction": "asc"},
        },
    ]


def test_collection_and_workbook_list_entries_return_canonical_summaries() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getCollectionContent": httpx.Response(
                200,
                json={
                    "items": [
                        {"entity": "collection", "collectionId": "collection-2", "title": "Child"},
                        {
                            "entity": "workbook",
                            "workbookId": "workbook-2",
                            "collectionId": "collection-1",
                            "title": "Workbook",
                        },
                        {
                            "entity": "entry",
                            "entryId": "entry-1",
                            "scope": "dataset",
                            "type": "dataset",
                            "title": "Dataset",
                        },
                    ]
                },
            ),
            "/rpc/getWorkbookEntries": httpx.Response(
                200,
                json={"entries": [_entry("entry-2", name="Workbook chart")]},
            ),
        }
    )
    client = _client(recorder)
    collection = Collection(
        id="collection-1",
        name="Collection",
        installation="yacloud",
        _operations=client._collection_service,
    )
    workbook = Workbook(
        id="workbook-1",
        name="Workbook",
        installation="yacloud",
        _operations=client._workbook_service,
    )

    collection_items = list(
        collection.list_entries(
            filter_string="report",
            mode="all",
            order_by="name",
            order_direction="desc",
            page_size=25,
        )
    )
    workbook_items = list(workbook.list_entries(scope=["widget", "dataset"], page_size=10))

    assert [type(item) for item in collection_items] == [CollectionSummary, WorkbookSummary, EntrySummary]
    assert collection_items[0].name == "Child"
    assert workbook_items[0].name == "Workbook chart"
    assert recorder.bodies("/rpc/getCollectionContent") == [
        {
            "collectionId": "collection-1",
            "mode": "all",
            "pageSize": 25,
            "filterString": "report",
            "orderField": "title",
            "orderDirection": "desc",
        }
    ]
    assert recorder.bodies("/rpc/getWorkbookEntries") == [
        {
            "workbookId": "workbook-1",
            "page": 0,
            "pageSize": 10,
            "scope": ["widget", "dataset"],
        }
    ]


def test_entry_objects_get_paginated_relations() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getEntriesRelations": [
                httpx.Response(
                    200,
                    json={
                        "relations": [
                            {
                                "entryId": "dataset-1",
                                "scope": "dataset",
                                "type": "dataset",
                                "key": "folder/Dataset",
                            }
                        ],
                        "nextPageToken": "relations-2",
                    },
                ),
                httpx.Response(200, json={"relations": []}),
            ]
        }
    )
    connection = _client(recorder).domain_connection(id="connection-1", type="postgres")

    relations = list(
        connection.get_relations(
            include_permissions_info=True,
            link_direction="from",
            page_size=20,
            scope="dataset",
        )
    )

    assert [relation.id for relation in relations] == ["dataset-1"]
    assert recorder.bodies("/rpc/getEntriesRelations") == [
        {
            "entryIds": ["connection-1"],
            "limit": 20,
            "includePermissionsInfo": True,
            "linkDirection": "from",
            "scope": "dataset",
        },
        {
            "entryIds": ["connection-1"],
            "limit": 20,
            "includePermissionsInfo": True,
            "linkDirection": "from",
            "pageToken": "relations-2",
            "scope": "dataset",
        },
    ]


def test_supported_entry_objects_bind_relations_to_navigation() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getEntriesRelations": [
                httpx.Response(200, json={"relations": []}),
                httpx.Response(200, json={"relations": []}),
                httpx.Response(200, json={"relations": []}),
            ]
        }
    )
    client = _client(recorder)
    objects = (
        client.domain_connection(id="connection-1", type="postgres"),
        Dataset(id="dataset-1", installation="yacloud", _operations=client._dataset_service),
        WizardChart(id="chart-1", installation="yacloud", _operations=client._chart_service),
    )

    for entry in objects:
        assert list(entry.get_relations()) == []

    assert recorder.bodies("/rpc/getEntriesRelations") == [
        {"entryIds": ["connection-1"], "limit": 100},
        {"entryIds": ["dataset-1"], "limit": 100},
        {"entryIds": ["chart-1"], "limit": 100},
    ]


def test_unbound_domain_navigation_fails_before_request() -> None:
    folder = Folder(id="folder-1", name="Folder", key="folder/")
    collection = Collection(id="collection-1", name="Collection")
    workbook = Workbook(id="workbook-1", name="Workbook")

    with pytest.raises(DataLensConfigurationError):
        folder.list_entries()
    with pytest.raises(DataLensConfigurationError):
        collection.list_entries()
    with pytest.raises(DataLensConfigurationError):
        workbook.list_entries()
