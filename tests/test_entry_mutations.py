from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.chart import ChartUpdate
from datalens_sdk.domain.chart_types import ChartCategory
from datalens_sdk.domain.ports import (
    ChartOperations,
    CollectionOperations,
    ConnectionOperations,
    DashboardOperations,
    DatasetOperations,
    FolderOperations,
    WorkbookOperations,
)


class UnsupportedChart(dl.Chart):
    @property
    def category(self) -> ChartCategory:
        return "wizard"

    @property
    def update(self) -> ChartUpdate:
        raise NotImplementedError

    def delete(self) -> None:
        raise NotImplementedError


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


def _collection_response(*, name: str, parent_id: str | None) -> dict[str, object]:
    return {"collectionId": "collection-1", "title": name, "parentId": parent_id}


def _workbook_response(*, name: str, collection_id: str | None) -> dict[str, object]:
    return {"workbookId": "workbook-1", "title": name, "collectionId": collection_id}


def _folder_response(*, name: str, key: str) -> dict[str, object]:
    return {"entryId": "folder-1", "name": name, "key": key, "scope": "folder", "type": ""}


def _dashboard_response(*, key: str) -> dict[str, object]:
    return {"entry": {"entryId": "dashboard-1", "key": key, "data": {}}}


def _wizard_response(*, key: str) -> dict[str, object]:
    return {
        "entryId": "wizard-1",
        "key": key,
        "type": "d3_wizard_node",
        "data": {"visualization": {"id": "line", "placeholders": []}},
    }


def _editor_response(*, key: str) -> dict[str, object]:
    return {
        "entryId": "editor-1",
        "key": key,
        "type": "advanced-chart-node",
        "data": {"sources": "", "params": "", "controls": "", "meta": "", "prepare": ""},
    }


def _ql_response(*, key: str) -> dict[str, object]:
    return {
        "entryId": "ql-1",
        "key": key,
        "type": "d3_ql_node",
        "data": {"chartType": "sql", "type": "ql", "version": "7", "queryValue": "SELECT 1", "params": []},
    }


def test_collection_workbook_and_folder_moves_use_dedicated_routes() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getCollection": httpx.Response(
                200,
                json=_collection_response(name="Collection", parent_id="parent-1"),
            ),
            "/rpc/moveCollection": [
                httpx.Response(200, json=_collection_response(name="Collection moved", parent_id="parent-2")),
                httpx.Response(200, json=_collection_response(name="Collection moved", parent_id=None)),
            ],
            "/rpc/getWorkbook": httpx.Response(
                200,
                json=_workbook_response(name="Workbook", collection_id="parent-1"),
            ),
            "/rpc/moveWorkbook": [
                httpx.Response(200, json=_workbook_response(name="Workbook moved", collection_id="parent-2")),
                httpx.Response(200, json=_workbook_response(name="Workbook moved", collection_id=None)),
            ],
            "/rpc/listDirectory": httpx.Response(
                200,
                json={
                    "entries": [_folder_response(name="Folder", key="/Source/Folder")],
                    "breadCrumbs": [],
                    "hasNextPage": False,
                },
            ),
            "/rpc/moveFolderEntry": httpx.Response(200, json=[{"entryId": "folder-1"}]),
            "/rpc/getEntries": httpx.Response(
                200,
                json={"entries": [_folder_response(name="Folder moved", key="/Destination/Folder moved")]},
            ),
        }
    )
    client = _client(recorder)

    collection = client.get.collection(by_id="collection-1")
    collection = collection.move(dl.EntryLocation.collection("parent-2"), name="Collection moved")
    collection = collection.move(None)

    workbook = client.get.workbook(by_id="workbook-1")
    workbook = workbook.move(dl.EntryLocation.collection("parent-2"), name="Workbook moved")
    workbook = workbook.move(None)

    folder = client.get.folder(by_path="/Source/Folder")
    folder = folder.move(dl.EntryLocation.path("/Destination"), name="Folder moved")

    assert collection.parent_id is None
    assert workbook.collection_id is None
    assert folder.name == "Folder moved"
    assert folder.key == "/Destination/Folder moved"
    assert recorder.bodies("/rpc/moveCollection") == [
        {"collectionId": "collection-1", "parentId": "parent-2", "title": "Collection moved"},
        {"collectionId": "collection-1", "parentId": None},
    ]
    assert recorder.bodies("/rpc/moveWorkbook") == [
        {"workbookId": "workbook-1", "collectionId": "parent-2", "title": "Workbook moved"},
        {"workbookId": "workbook-1", "collectionId": None},
    ]
    assert recorder.bodies("/rpc/moveFolderEntry") == [
        {"entryId": "folder-1", "destination": "/Destination", "name": "Folder moved"}
    ]


def test_collection_workbook_and_folder_rename_use_existing_mutation_routes() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getCollection": httpx.Response(
                200,
                json=_collection_response(name="Collection", parent_id="parent-1"),
            ),
            "/rpc/updateCollection": httpx.Response(
                200,
                json=_collection_response(name="Collection renamed", parent_id="parent-1"),
            ),
            "/rpc/getWorkbook": httpx.Response(
                200,
                json=_workbook_response(name="Workbook", collection_id="parent-1"),
            ),
            "/rpc/updateWorkbook": httpx.Response(
                200,
                json=_workbook_response(name="Workbook renamed", collection_id="parent-1"),
            ),
            "/rpc/listDirectory": httpx.Response(
                200,
                json={
                    "entries": [_folder_response(name="Folder", key="/Source/Folder")],
                    "breadCrumbs": [],
                    "hasNextPage": False,
                },
            ),
            "/rpc/renameEntry": httpx.Response(200, json=[{"entryId": "folder-1"}]),
            "/rpc/getEntries": httpx.Response(
                200,
                json={"entries": [_folder_response(name="Folder renamed", key="/Source/Folder renamed")]},
            ),
        }
    )
    client = _client(recorder)

    collection = client.get.collection(by_id="collection-1").rename("Collection renamed")
    workbook = client.get.workbook(by_id="workbook-1").rename("Workbook renamed")
    folder = client.get.folder(by_path="/Source/Folder").rename("Folder renamed")

    assert collection.name == "Collection renamed"
    assert workbook.name == "Workbook renamed"
    assert folder.name == "Folder renamed"
    assert folder.key == "/Source/Folder renamed"
    assert recorder.bodies("/rpc/updateCollection") == [{"collectionId": "collection-1", "title": "Collection renamed"}]
    assert recorder.bodies("/rpc/updateWorkbook") == [{"workbookId": "workbook-1", "title": "Workbook renamed"}]
    assert recorder.bodies("/rpc/renameEntry") == [{"entryId": "folder-1", "name": "Folder renamed"}]
    assert recorder.bodies("/rpc/getEntries") == [{"pageSize": 1, "ids": ["folder-1"], "scope": "folder"}]


def test_entry_rename_refetches_each_concrete_resource_type() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getConnection": [
                httpx.Response(200, json={"id": "connection-1", "type": "postgres", "name": "Connection"}),
                httpx.Response(200, json={"id": "connection-1", "type": "postgres", "name": "Connection renamed"}),
            ],
            "/rpc/getDataset": [
                httpx.Response(
                    200,
                    json={"id": "dataset-1", "name": "Dataset", "workbook_id": "workbook-1", "dataset": {}},
                ),
                httpx.Response(
                    200,
                    json={
                        "id": "dataset-1",
                        "name": "Dataset renamed",
                        "workbook_id": "workbook-1",
                        "dataset": {},
                    },
                ),
            ],
            "/rpc/getDashboard": [
                httpx.Response(200, json=_dashboard_response(key="/Dashboards/Dashboard")),
                httpx.Response(200, json=_dashboard_response(key="/Dashboards/Dashboard renamed")),
            ],
            "/rpc/getWizardChart": [
                httpx.Response(200, json=_wizard_response(key="/Charts/Wizard")),
                httpx.Response(200, json=_wizard_response(key="/Charts/Wizard renamed")),
            ],
            "/rpc/getEditorChart": [
                httpx.Response(200, json=_editor_response(key="/Charts/Editor")),
                httpx.Response(200, json=_editor_response(key="/Charts/Editor renamed")),
            ],
            "/rpc/getQLChart": [
                httpx.Response(200, json=_ql_response(key="/Charts/QL")),
                httpx.Response(200, json=_ql_response(key="/Charts/QL renamed")),
            ],
            "/rpc/renameEntry": [
                httpx.Response(200, json=[{"entryId": entry_id}])
                for entry_id in ("connection-1", "dataset-1", "dashboard-1", "wizard-1", "editor-1", "ql-1")
            ],
        }
    )
    client = _client(recorder)

    connection = client.get.connection(by_id="connection-1").rename("Connection renamed")
    dataset = client.get.dataset(by_id="dataset-1", workbook_id="workbook-1").rename("Dataset renamed")
    dashboard = client.get.dashboard(by_id="dashboard-1").rename("Dashboard renamed")
    wizard = client.get.wizard_chart(by_id="wizard-1").rename("Wizard renamed")
    editor = client.get.editor_chart(by_id="editor-1").rename("Editor renamed")
    ql = client.get.ql_chart(by_id="ql-1").rename("QL renamed")

    assert connection.name == "Connection renamed"
    assert dataset.name == "Dataset renamed"
    assert dashboard.name == "Dashboard renamed"
    assert isinstance(wizard, dl.WizardChart)
    assert wizard.name == "Wizard renamed"
    assert isinstance(editor, dl.EditorChart)
    assert editor.name == "Editor renamed"
    assert isinstance(ql, dl.QLChart)
    assert ql.name == "QL renamed"
    assert recorder.bodies("/rpc/renameEntry") == [
        {"entryId": "connection-1", "name": "Connection renamed"},
        {"entryId": "dataset-1", "name": "Dataset renamed"},
        {"entryId": "dashboard-1", "name": "Dashboard renamed"},
        {"entryId": "wizard-1", "name": "Wizard renamed"},
        {"entryId": "editor-1", "name": "Editor renamed"},
        {"entryId": "ql-1", "name": "QL renamed"},
    ]
    assert recorder.bodies("/rpc/getDataset")[-1] == {"datasetId": "dataset-1", "workbookId": "workbook-1"}
    for entry in (connection, dataset, dashboard, wizard, editor, ql):
        assert not hasattr(entry, "move")


def test_chart_rename_rejects_unknown_subtype_before_mutation() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    chart = UnsupportedChart(id="unsupported-1", _operations=client._chart_service)

    with pytest.raises(dl.NotSupportedError, match="UnsupportedChart"):
        chart.rename("Renamed")

    assert recorder.requests == []


def test_move_and_rename_validate_names_and_destination_kinds_before_requests() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getCollection": httpx.Response(
                200,
                json=_collection_response(name="Collection", parent_id=None),
            ),
            "/rpc/getWorkbook": httpx.Response(
                200,
                json=_workbook_response(name="Workbook", collection_id=None),
            ),
            "/rpc/getConnection": httpx.Response(
                200,
                json={"id": "connection-1", "type": "postgres", "name": "Connection", "key": "/Path/Connection"},
            ),
            "/rpc/listDirectory": httpx.Response(
                200,
                json={
                    "entries": [_folder_response(name="Folder", key="/Source/Folder")],
                    "breadCrumbs": [],
                    "hasNextPage": False,
                },
            ),
        }
    )
    client = _client(recorder)
    collection = client.get.collection(by_id="collection-1")
    workbook = client.get.workbook(by_id="workbook-1")
    connection = client.get.connection(by_id="connection-1")
    folder = client.get.folder(by_path="/Source/Folder")

    with pytest.raises(dl.DataLensValidationError, match="Collection move requires location kind 'collection'"):
        collection.move(dl.EntryLocation.path("/Destination"))
    with pytest.raises(dl.DataLensValidationError, match="Workbook move requires location kind 'collection'"):
        workbook.move(dl.EntryLocation.workbook("other-workbook"))
    with pytest.raises(dl.DataLensValidationError, match="Folder move requires location kind 'path'"):
        folder.move(dl.EntryLocation.collection("collection-2"))
    with pytest.raises(dl.NotSupportedError, match="destination"):
        folder.move(dl.Folder(id="other", name="Other", key="/Other", installation="enterprise"))
    with pytest.raises(dl.DataLensValidationError, match="name must not be empty"):
        collection.move(None, name="")
    with pytest.raises(dl.DataLensValidationError, match="name must not be empty"):
        collection.rename("")
    with pytest.raises(dl.DataLensValidationError, match="name must not be empty"):
        workbook.rename("")
    with pytest.raises(dl.DataLensValidationError, match="must not contain"):
        folder.move(dl.EntryLocation.path("/Destination"), name="nested/name")
    with pytest.raises(dl.DataLensValidationError, match="must not contain"):
        folder.rename("nested/name")
    with pytest.raises(dl.DataLensValidationError, match="must not contain"):
        connection.rename("nested/name")

    assert recorder.bodies("/rpc/moveCollection") == []
    assert recorder.bodies("/rpc/moveWorkbook") == []
    assert recorder.bodies("/rpc/updateCollection") == []
    assert recorder.bodies("/rpc/updateWorkbook") == []
    assert recorder.bodies("/rpc/moveFolderEntry") == []
    assert recorder.bodies("/rpc/renameEntry") == []


def test_move_and_rename_reject_unbound_objects_and_missing_ids() -> None:
    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dl.Collection(id="collection-1", name="Collection").move(None)
    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dl.Collection(id="collection-1", name="Collection").rename("Renamed")
    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dl.Workbook(id="workbook-1", name="Workbook").rename("Renamed")
    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dl.Folder(id="folder-1", name="Folder", key="/Folder").rename("Renamed")
    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dl.Connection(id="connection-1", type="postgres").rename("Renamed")

    with pytest.raises(dl.DataLensValidationError, match="collection without an id"):
        dl.Collection(
            id=None,
            name="Collection",
            _operations=cast(CollectionOperations, object()),
        ).move(None)
    with pytest.raises(dl.DataLensValidationError, match="collection without an id"):
        dl.Collection(
            id=None,
            name="Collection",
            _operations=cast(CollectionOperations, object()),
        ).rename("Renamed")
    with pytest.raises(dl.DataLensValidationError, match="workbook without an id"):
        dl.Workbook(
            id=None,
            name="Workbook",
            _operations=cast(WorkbookOperations, object()),
        ).move(None)
    with pytest.raises(dl.DataLensValidationError, match="workbook without an id"):
        dl.Workbook(
            id=None,
            name="Workbook",
            _operations=cast(WorkbookOperations, object()),
        ).rename("Renamed")
    with pytest.raises(dl.DataLensValidationError, match="folder without an id"):
        dl.Folder(
            id=None,
            name="Folder",
            key="/Folder",
            _operations=cast(FolderOperations, object()),
        ).move(dl.EntryLocation.path("/Destination"))
    with pytest.raises(dl.DataLensValidationError, match="folder without an id"):
        dl.Folder(
            id=None,
            name="Folder",
            key="/Folder",
            _operations=cast(FolderOperations, object()),
        ).rename("Renamed")
    with pytest.raises(dl.DataLensValidationError, match="connection without an id"):
        dl.Connection(
            id=None,
            type="postgres",
            _operations=cast(ConnectionOperations, object()),
        ).rename("Renamed")
    with pytest.raises(dl.DataLensValidationError, match="dataset without an id"):
        dl.Dataset(
            id=None,
            _operations=cast(DatasetOperations, object()),
        ).rename("Renamed")
    with pytest.raises(dl.DataLensValidationError, match="dashboard without an id"):
        dl.Dashboard(
            id=None,
            _operations=cast(DashboardOperations, object()),
        ).rename("Renamed")
    with pytest.raises(dl.DataLensValidationError, match="chart without an id"):
        dl.WizardChart(
            id=None,
            _operations=cast(ChartOperations, object()),
        ).rename("Renamed")


@pytest.mark.parametrize(
    ("route", "action"),
    [
        ("/rpc/moveFolderEntry", "move"),
        ("/rpc/renameEntry", "rename"),
    ],
)
def test_entry_mutations_reject_non_array_responses(route: str, action: str) -> None:
    routes: dict[str, list[httpx.Response] | httpx.Response] = {
        "/rpc/listDirectory": httpx.Response(
            200,
            json={
                "entries": [_folder_response(name="Folder", key="/Source/Folder")],
                "breadCrumbs": [],
                "hasNextPage": False,
            },
        ),
        "/rpc/getConnection": httpx.Response(
            200,
            json={"id": "connection-1", "type": "postgres", "name": "Connection"},
        ),
        route: httpx.Response(200, json={"entryId": "not-an-array"}),
    }
    client = _client(RecordedTransport(routes))

    if action == "move":
        with pytest.raises(dl.InvalidResponseError, match="response root is not an array"):
            client.get.folder(by_path="/Source/Folder").move(dl.EntryLocation.path("/Destination"))
    else:
        with pytest.raises(dl.InvalidResponseError, match="response root is not an array"):
            client.get.connection(by_id="connection-1").rename("Renamed")
