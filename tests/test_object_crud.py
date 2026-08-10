from __future__ import annotations

import json
from typing import cast

import httpx
from pydantic import ValidationError
import pytest

import datalens_sdk as dl
from datalens_sdk._generated import dto
from datalens_sdk.domain.collection import CollectionCreate
from datalens_sdk.domain.folder import FolderCreate
from datalens_sdk.domain.specs import (
    CollectionCreateSpec,
    CollectionUpdateSpec,
    FolderCreateSpec,
    FolderUpdateSpec,
    WorkbookCreateSpec,
    WorkbookUpdateSpec,
)
from datalens_sdk.domain.workbook import WorkbookCreate


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
        bodies: list[dict[str, object]] = []
        for request in self.requests:
            if request.url.path != path:
                continue
            body: object = json.loads(request.content.decode())
            assert isinstance(body, dict)
            bodies.append(cast(dict[str, object], body))
        return bodies


def _collection_response(*, name: str, description: str = "") -> dict[str, object]:
    return {
        "collectionId": "collection-1",
        "title": name,
        "description": description,
        "parentId": None,
        "futureCollectionField": "preserved in raw",
    }


def _workbook_response(*, name: str, description: str = "") -> dict[str, object]:
    return {
        "workbookId": "workbook-1",
        "collectionId": "collection-1",
        "title": name,
        "description": description,
        "status": "active",
        "futureWorkbookField": "preserved in raw",
    }


def _folder_response(*, name: str, folder_id: str = "folder-1", scope: str = "folder") -> dict[str, object]:
    return {
        "entryId": folder_id,
        "name": name,
        "key": f"/Users/me/{name}",
        "scope": scope,
        "type": "",
        "hidden": False,
        "futureFolderField": "preserved in raw",
    }


def test_object_crud_specs_are_stable_builder_snapshots() -> None:
    collection_location = dl.EntryLocation.collection("collection-1")
    path_location = dl.EntryLocation.path("/Users/me")

    collection_create = CollectionCreate(
        installation="yacloud",
        name="Analytics",
        parent=collection_location,
    ).description("Initial")
    collection_create_spec = collection_create.to_spec()
    collection_create.description("Changed")
    assert collection_create_spec == CollectionCreateSpec(
        name="Analytics",
        parent=collection_location,
        description="Initial",
    )

    collection_update = dl.Collection(id="collection-1", name="Analytics").update.name("Analytics v2")
    collection_update_spec = collection_update.to_spec()
    collection_update.description("Changed")
    assert collection_update_spec == CollectionUpdateSpec(
        collection_id="collection-1",
        changes={"name": "Analytics v2"},
    )

    workbook_create = WorkbookCreate(
        installation="yacloud",
        name="Sales",
        collection=collection_location,
    ).description("Initial")
    workbook_create_spec = workbook_create.to_spec()
    workbook_create.description("Changed")
    assert workbook_create_spec == WorkbookCreateSpec(
        name="Sales",
        collection=collection_location,
        description="Initial",
    )

    workbook_update = dl.Workbook(id="workbook-1", name="Sales").update.name("Sales v2")
    workbook_update_spec = workbook_update.to_spec()
    workbook_update.description("Changed")
    assert workbook_update_spec == WorkbookUpdateSpec(
        workbook_id="workbook-1",
        changes={"name": "Sales v2"},
    )

    folder_create = FolderCreate(
        installation="yacloud",
        name="Archive",
        location=path_location,
    )
    assert folder_create.to_spec() == FolderCreateSpec(name="Archive", location=path_location)

    folder_update = dl.Folder(id="folder-1", name="Archive", key="/Users/me/Archive").update.name("Archive v2")
    folder_update_spec = folder_update.to_spec()
    folder_update.name("Changed")
    assert folder_update_spec == FolderUpdateSpec(folder_id="folder-1", name="Archive v2")


def test_collection_workbook_and_folder_full_crud_is_bound_to_client() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createCollection": httpx.Response(
                200, json=_collection_response(name="Analytics", description="Root")
            ),
            "/rpc/getCollection": httpx.Response(200, json=_collection_response(name="Analytics", description="Root")),
            "/rpc/updateCollection": httpx.Response(
                200, json=_collection_response(name="Analytics v2", description="Updated")
            ),
            "/rpc/deleteCollection": httpx.Response(200, json={"collections": []}),
            "/rpc/createWorkbook": httpx.Response(200, json=_workbook_response(name="Sales", description="Main")),
            "/rpc/getWorkbook": httpx.Response(200, json=_workbook_response(name="Sales", description="Main")),
            "/rpc/updateWorkbook": httpx.Response(200, json=_workbook_response(name="Sales v2", description="Updated")),
            "/rpc/deleteWorkbook": httpx.Response(200, json=_workbook_response(name="Sales v2")),
            "/rpc/createFolder": httpx.Response(
                200,
                json={"entryId": "folder-1", "key": "/Users/me/Archive", "scope": "folder", "hidden": False},
            ),
            "/rpc/listDirectory": httpx.Response(
                200,
                json={
                    "entries": [_folder_response(name="Archive")],
                    "breadCrumbs": [],
                    "hasNextPage": False,
                },
            ),
            "/rpc/getEntries": httpx.Response(200, json={"entries": [_folder_response(name="Archive v2")]}),
            "/rpc/renameEntry": httpx.Response(
                200,
                json=[
                    {
                        "entryId": "folder-1",
                        "key": "/Users/me/Archive v2",
                        "scope": "folder",
                        "type": "",
                        "updatedAt": "2026-07-13T00:00:00Z",
                        "updatedBy": "user-1",
                    }
                ],
            ),
            "/rpc/deleteFolder": httpx.Response(200, json={}),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    collection = client.create.collection(name="Analytics").description("Root").build()
    fetched_collection = client.get.collection(by_id="collection-1")
    updated_collection = fetched_collection.update.name("Analytics v2").description("Updated").execute()

    workbook = client.create.workbook(name="Sales", collection=collection).description("Main").build()
    fetched_workbook = client.get.workbook(by_id="workbook-1")
    updated_workbook = fetched_workbook.update.name("Sales v2").description("Updated").execute()

    folder = client.create.folder(name="Archive", location=dl.EntryLocation.path("/Users/me")).build()
    fetched_folder = client.get.folder(by_path="/Users/me/Archive")
    updated_folder = fetched_folder.update.name("Archive v2").execute()

    updated_collection.delete()
    updated_workbook.delete()
    updated_folder.delete()

    assert collection.name == "Analytics"
    assert not hasattr(collection, "title")
    assert collection.raw["futureCollectionField"] == "preserved in raw"
    assert updated_collection.name == "Analytics v2"
    assert workbook.name == "Sales"
    assert not hasattr(workbook, "title")
    assert workbook.raw["futureWorkbookField"] == "preserved in raw"
    assert updated_workbook.name == "Sales v2"
    assert folder.name == "Archive"
    assert folder.key == "/Users/me/Archive"
    assert updated_folder.name == "Archive v2"

    assert recorder.bodies("/rpc/createCollection") == [{"title": "Analytics", "parentId": None, "description": "Root"}]
    assert recorder.bodies("/rpc/getCollection") == [{"collectionId": "collection-1"}]
    assert recorder.bodies("/rpc/updateCollection") == [
        {"collectionId": "collection-1", "title": "Analytics v2", "description": "Updated"}
    ]
    assert recorder.bodies("/rpc/deleteCollection") == [{"collectionId": "collection-1"}]
    assert recorder.bodies("/rpc/createWorkbook") == [
        {"title": "Sales", "collectionId": "collection-1", "description": "Main"}
    ]
    assert recorder.bodies("/rpc/getWorkbook") == [{"workbookId": "workbook-1"}]
    assert recorder.bodies("/rpc/updateWorkbook") == [
        {"workbookId": "workbook-1", "title": "Sales v2", "description": "Updated"}
    ]
    assert recorder.bodies("/rpc/deleteWorkbook") == [{"workbookId": "workbook-1"}]
    assert recorder.bodies("/rpc/createFolder") == [{"key": "/Users/me/Archive"}]
    assert recorder.bodies("/rpc/listDirectory") == [
        {"path": "Users/me/", "filters": {"name": "Archive"}, "page": 0, "pageSize": 200}
    ]
    assert recorder.bodies("/rpc/getEntries") == [{"pageSize": 1, "ids": ["folder-1"], "scope": "folder"}]
    assert recorder.bodies("/rpc/renameEntry") == [{"entryId": "folder-1", "name": "Archive v2"}]
    assert recorder.bodies("/rpc/deleteFolder") == [{"folderId": "folder-1"}]
    assert {request.headers["x-dl-api-version"] for request in recorder.requests} == {"2"}


def test_domain_objects_are_typed_entry_destinations_for_existing_create_apis() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": [
                httpx.Response(200, json={"id": "dataset-collection", "name": "Collection DS", "dataset": {}}),
                httpx.Response(200, json={"id": "dataset-workbook", "name": "Workbook DS", "dataset": {}}),
                httpx.Response(200, json={"id": "dataset-folder", "name": "Folder DS", "dataset": {}}),
                httpx.Response(200, json={"id": "dataset-collection-ref", "name": "Collection Ref", "dataset": {}}),
                httpx.Response(200, json={"id": "dataset-workbook-ref", "name": "Workbook Ref", "dataset": {}}),
                httpx.Response(200, json={"id": "dataset-path-ref", "name": "Path Ref", "dataset": {}}),
            ],
            "/rpc/createConnection": httpx.Response(
                200,
                json={"id": "connection-1", "type": "postgres", "name": "Workbook PG"},
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    collection = dl.Collection(id="collection-1", name="Analytics", installation="yacloud")
    workbook = dl.Workbook(id="workbook-1", name="Sales", installation="yacloud")
    folder = dl.Folder(id="folder-1", name="Archive", key="/Users/me/Archive", installation="yacloud")

    client.create.dataset(location=collection, name="Collection DS").build()
    client.create.dataset(location=workbook, name="Workbook DS").build()
    client.create.dataset(location=folder, name="Folder DS").build()
    client.create.dataset(name="Collection Ref", location=dl.EntryLocation.collection("collection-1")).build()
    client.create.dataset(name="Workbook Ref", location=dl.EntryLocation.workbook("workbook-1")).build()
    client.create.dataset(name="Path Ref", location=dl.EntryLocation.path("/Users/me/Archive")).build()
    client.create.connection.postgres(location=workbook, name="Workbook PG").host("db").port(5432).build()

    dataset_bodies = recorder.bodies("/rpc/createDataset")
    assert dataset_bodies[0]["collection_id"] == "collection-1"
    assert dataset_bodies[0]["name"] == "Collection DS"
    assert dataset_bodies[1]["workbook_id"] == "workbook-1"
    assert dataset_bodies[1]["name"] == "Workbook DS"
    assert dataset_bodies[2]["dir_path"] == "/Users/me/Archive"
    assert dataset_bodies[2]["name"] == "Folder DS"
    assert dataset_bodies[3]["collection_id"] == dataset_bodies[0]["collection_id"]
    assert dataset_bodies[4]["workbook_id"] == dataset_bodies[1]["workbook_id"]
    assert dataset_bodies[5]["dir_path"] == dataset_bodies[2]["dir_path"]
    connection_body = recorder.bodies("/rpc/createConnection")[0]
    assert connection_body["host"] == "db"
    assert connection_body["port"] == 5432
    assert connection_body["name"] == "Workbook PG"
    assert connection_body["workbook_id"] == "workbook-1"
    assert connection_body["type"] == "postgres"

    with pytest.raises(dl.DataLensValidationError, match="name must not be empty"):
        client.create.dataset(name="", location=workbook)
    with pytest.raises(dl.DataLensValidationError, match="must not contain"):
        client.create.dataset(name="nested/DS", location=dl.EntryLocation.path("/Users/me"))
    with pytest.raises(dl.NotSupportedError, match="destination"):
        client.create.dataset(
            location=dl.Workbook(id="workbook-2", name="Other", installation="enterprise"),
            name="DS",
        )


def test_collection_references_and_objects_are_interchangeable_for_parenting() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createCollection": [
                httpx.Response(200, json={"collectionId": "child-object", "title": "Child object"}),
                httpx.Response(200, json={"collectionId": "child-ref", "title": "Child ref"}),
            ],
            "/rpc/createWorkbook": [
                httpx.Response(200, json={"workbookId": "workbook-object", "title": "Workbook object"}),
                httpx.Response(200, json={"workbookId": "workbook-ref", "title": "Workbook ref"}),
            ],
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    collection = dl.Collection(id="collection-1", name="Analytics", installation="yacloud")
    collection_ref = dl.EntryLocation.collection("collection-1")

    client.create.collection(name="Child object", parent=collection).build()
    client.create.collection(name="Child ref", parent=collection_ref).build()
    client.create.workbook(name="Workbook object", collection=collection).build()
    client.create.workbook(name="Workbook ref", collection=collection_ref).build()

    collection_bodies = recorder.bodies("/rpc/createCollection")
    workbook_bodies = recorder.bodies("/rpc/createWorkbook")
    assert collection_bodies[0]["parentId"] == collection_bodies[1]["parentId"] == "collection-1"
    assert workbook_bodies[0]["collectionId"] == workbook_bodies[1]["collectionId"] == "collection-1"


def test_destination_kind_validation_uses_one_entry_location_type() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    with pytest.raises(dl.DataLensValidationError, match="Folder creation requires location kind 'path'"):
        client.create.folder(name="Folder", location=dl.EntryLocation.workbook("workbook-1"))
    with pytest.raises(dl.DataLensValidationError, match="Collection creation requires location kind 'collection'"):
        client.create.collection(name="Child", parent=dl.EntryLocation.path("/Users/me"))
    with pytest.raises(dl.DataLensValidationError, match="Workbook creation requires location kind 'collection'"):
        client.create.workbook(name="Workbook", collection=dl.EntryLocation.workbook("workbook-1"))


def test_only_entry_location_facade_is_exported() -> None:
    for removed_name in (
        "EntryPlacement",
        "EntryDestination",
        "PathEntryLocation",
        "WorkbookEntryLocation",
        "CollectionEntryLocation",
    ):
        assert removed_name not in dl.__all__
        assert not hasattr(dl, removed_name)


@pytest.mark.parametrize(
    ("entries", "error_type", "message"),
    [
        ([], dl.NotFoundError, "was not found"),
        (
            [_folder_response(name="One"), _folder_response(name="One", folder_id="folder-2")],
            dl.InvalidResponseError,
            "exactly one folder",
        ),
        ([_folder_response(name="One", scope="dataset")], dl.InvalidResponseError, "scope"),
    ],
)
def test_folder_get_validates_exactly_one_folder(
    entries: list[dict[str, object]],
    error_type: type[Exception],
    message: str,
) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/listDirectory": httpx.Response(
                200,
                json={"entries": entries, "breadCrumbs": [], "hasNextPage": False},
            )
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    with pytest.raises(error_type, match=message):
        client.get.folder(by_path="Users/me/One/")

    assert recorder.bodies("/rpc/listDirectory") == [
        {"path": "Users/me/", "filters": {"name": "One"}, "page": 0, "pageSize": 200}
    ]


def test_generated_object_dtos_use_name_and_enforce_write_read_extra_rules() -> None:
    collection_create = dto.CollectionCreateDTO(name="Analytics", parent_id=None, description=None)
    workbook_read = dto.WorkbookReadDTO.model_validate({"workbookId": "workbook-1", "title": "Sales", "future": True})

    assert collection_create.to_payload() == {"title": "Analytics", "parentId": None}
    assert not hasattr(collection_create, "title")
    assert workbook_read.name == "Sales"
    assert "future" not in workbook_read.model_dump()
    assert workbook_read.raw["future"] is True
    with pytest.raises(ValidationError):
        dto.CollectionCreateDTO.model_validate({"name": "Analytics", "parent_id": None, "unexpected": True})
