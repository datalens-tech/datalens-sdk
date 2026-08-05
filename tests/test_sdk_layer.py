from __future__ import annotations

from dataclasses import fields
import json
import logging
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
from pydantic import ValidationError
import pytest

import datalens_sdk as dl
from datalens_sdk._generated import dto
from datalens_sdk.converter.connection import ConnectionConverter
from datalens_sdk.converter.dataset import DatasetConverter
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Source
from datalens_sdk.domain.entry_location import resolve_entry_location_from_api_fields
from datalens_sdk.domain.specs.connection import ConnectionCreateSpec, ConnectionUpdateSpec


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

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)


def _empty_dataset_response(*, dataset_id: str = "ds-1") -> dict[str, object]:
    return {
        "id": dataset_id,
        "name": "sales",
        "dataset": {
            "description": "",
            "sources": [],
            "source_avatars": [],
            "avatar_relations": [],
        },
    }


def _connection_metadata_response(
    *,
    connection_id: str,
    name: str,
    description: str,
    dir_path: str,
) -> dict[str, object]:
    return {
        "id": connection_id,
        "type": "postgres",
        "name": name,
        "description": description,
        "dir_path": dir_path,
        "key": f"{dir_path.rstrip('/')}/{name}",
    }


def _assert_connection_top_level_metadata(
    connection: dl.Connection,
    *,
    connection_id: str,
    name: str,
    description: str,
    dir_path: str,
) -> None:
    assert connection.id == connection_id
    assert connection.installation == "yacloud"
    assert connection.name == name
    assert connection.description == description
    assert connection.dir_path == dir_path
    assert connection.key == f"{dir_path.rstrip('/')}/{name}"


def _dataset_metadata_response(
    *,
    dataset_id: str,
    name: str,
    description: str,
    dir_path: str,
    revision: str,
) -> dict[str, object]:
    return {
        "id": dataset_id,
        "name": name,
        "dir_path": dir_path,
        "key": f"{dir_path.rstrip('/')}/{name}",
        "is_favorite": True,
        "permissions": {"read": True, "edit": False},
        "full_permissions": {"read": True, "edit": False, "admin": False},
        "options": {"disable_export": True},
        "publishedId": f"published-{revision}",
        "revId": f"rev-{revision}",
        "savedId": f"saved-{revision}",
        "dataset": {
            "description": description,
            "sources": [],
            "source_avatars": [],
            "avatar_relations": [],
            "result_schema": [],
        },
    }


def _assert_dataset_top_level_metadata(
    dataset: dl.Dataset,
    *,
    dataset_id: str,
    name: str,
    description: str,
    dir_path: str,
    revision: str,
) -> None:
    assert dataset.id == dataset_id
    assert dataset.installation == "yacloud"
    assert dataset.name == name
    assert dataset.description == description
    assert dataset.dir_path == dir_path
    assert dataset.key == f"{dir_path.rstrip('/')}/{name}"
    assert dataset.is_favorite is True
    assert dataset.permissions == {"read": True, "edit": False}
    assert dataset.full_permissions == {"read": True, "edit": False, "admin": False}
    assert dataset.options == {"disable_export": True}
    assert dataset.published_id == f"published-{revision}"
    assert dataset.rev_id == f"rev-{revision}"
    assert dataset.saved_id == f"saved-{revision}"


def test_create_entry_payloads_use_entry_location() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": [
                httpx.Response(200, json={"id": "conn-path", "type": "postgres", "name": "PG path"}),
                httpx.Response(200, json={"id": "conn-workbook", "type": "postgres", "name": "PG workbook"}),
                httpx.Response(200, json={"id": "conn-collection", "type": "postgres", "name": "PG collection"}),
            ],
            "/rpc/createDataset": [
                httpx.Response(200, json=_empty_dataset_response(dataset_id="ds-path")),
                httpx.Response(200, json=_empty_dataset_response(dataset_id="ds-workbook")),
                httpx.Response(200, json=_empty_dataset_response(dataset_id="ds-collection")),
            ],
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    client.create.connection.postgres(name="PG path", location=dl.EntryLocation.path("/Users/me")).host("h").port(
        5432
    ).build()
    client.create.connection.postgres(name="PG workbook", location=dl.EntryLocation.workbook("wb-1")).host("h").port(
        5432
    ).build()
    client.create.connection.postgres(name="PG collection", location=dl.EntryLocation.collection("coll-1")).host(
        "h"
    ).port(5432).build()
    client.create.dataset(name="DS path", location=dl.EntryLocation.path("/Users/me")).build()
    client.create.dataset(name="DS workbook", location=dl.EntryLocation.workbook("wb-1")).build()
    client.create.dataset(name="DS collection", location=dl.EntryLocation.collection("coll-1")).build()

    connection_path = recorder.request_json(0)
    assert connection_path["name"] == "PG path"
    assert connection_path["dir_path"] == "/Users/me"
    assert "workbook_id" not in connection_path
    assert "collection_id" not in connection_path

    connection_workbook = recorder.request_json(1)
    assert connection_workbook["name"] == "PG workbook"
    assert connection_workbook["workbook_id"] == "wb-1"
    assert "dir_path" not in connection_workbook
    assert "collection_id" not in connection_workbook

    connection_collection = recorder.request_json(2)
    assert connection_collection["name"] == "PG collection"
    assert connection_collection["collection_id"] == "coll-1"
    assert "dir_path" not in connection_collection
    assert "workbook_id" not in connection_collection

    dataset_path = recorder.request_json(3)
    assert dataset_path["name"] == "DS path"
    assert dataset_path["dir_path"] == "/Users/me"
    assert "workbook_id" not in dataset_path
    assert "collection_id" not in dataset_path

    dataset_workbook = recorder.request_json(4)
    assert dataset_workbook["name"] == "DS workbook"
    assert dataset_workbook["workbook_id"] == "wb-1"
    assert "dir_path" not in dataset_workbook
    assert "collection_id" not in dataset_workbook

    dataset_collection = recorder.request_json(5)
    assert dataset_collection["name"] == "DS collection"
    assert dataset_collection["collection_id"] == "coll-1"
    assert "dir_path" not in dataset_collection
    assert "workbook_id" not in dataset_collection


def test_domain_models_store_name_separately_from_destination_location() -> None:
    location_fields = {"key", "dir_path", "workbook_id", "collection_id"}

    assert "location" in {item.name for item in fields(dl.Connection)}
    assert "location" in {item.name for item in fields(dl.Dataset)}
    assert "name" in {item.name for item in fields(dl.Connection)}
    assert "name" in {item.name for item in fields(dl.Dataset)}
    assert not (location_fields & {item.name for item in fields(dl.Connection)})
    assert not (location_fields & {item.name for item in fields(dl.Dataset)})


def test_read_converters_resolve_entry_location_metadata() -> None:
    connection = ConnectionConverter.to_domain(
        {
            "id": "conn-1",
            "type": "postgres",
            "name": "PG",
            "workbook_id": "wb-1",
        },
        installation="yacloud",
    )
    dataset = DatasetConverter.to_domain(
        {
            "id": "ds-1",
            "name": "Sales",
            "collection_id": "coll-1",
            "dataset": {
                "description": "",
                "sources": [],
                "source_avatars": [],
                "avatar_relations": [],
            },
        },
        installation="yacloud",
    )

    assert connection.name == "PG"
    assert connection.location == dl.EntryLocation.workbook("wb-1")
    assert connection.workbook_id == "wb-1"
    assert connection.collection_id is None
    assert dataset.name == "Sales"
    assert dataset.location == dl.EntryLocation.collection("coll-1")
    assert dataset.workbook_id is None
    assert dataset.collection_id == "coll-1"


def test_entry_location_resolver_builds_destination_only_locations() -> None:
    assert resolve_entry_location_from_api_fields(
        dir_path="/Users/me",
        key=None,
        collection_id=None,
        workbook_id=None,
    ) == dl.EntryLocation.path("/Users/me")
    assert resolve_entry_location_from_api_fields(
        dir_path="/Users/me",
        key=None,
        collection_id=None,
        workbook_id="wb-1",
    ) == dl.EntryLocation.workbook("wb-1")
    assert resolve_entry_location_from_api_fields(
        dir_path="/Users/me",
        key=None,
        collection_id="coll-1",
        workbook_id=None,
    ) == dl.EntryLocation.collection("coll-1")

    with pytest.raises(dl.DatalensValidationError, match="collection_id and workbook_id"):
        resolve_entry_location_from_api_fields(
            dir_path="/Users/me",
            key=None,
            collection_id="coll-1",
            workbook_id="wb-1",
        )


def test_entry_location_factories_validate_destination_values() -> None:
    assert dl.EntryLocation.path("/Users/me/") == dl.EntryLocation.path("/Users/me")
    assert dl.EntryLocation.workbook("wb-1") == dl.EntryLocation.workbook("wb-1")
    assert dl.EntryLocation.collection("coll-1") == dl.EntryLocation.collection("coll-1")
    with pytest.raises(dl.DatalensValidationError, match="dir_path must not be empty"):
        dl.EntryLocation.path("")
    with pytest.raises(dl.DatalensValidationError, match="workbook_id must not be empty"):
        dl.EntryLocation.workbook("")


def test_dataset_converter_uses_location_as_single_sparse_response_fallback() -> None:
    dataset = DatasetConverter.to_domain(
        {
            "id": "ds-1",
            "name": "New Sales",
            "dataset": {"description": "", "sources": [], "source_avatars": [], "avatar_relations": []},
        },
        installation="yacloud",
        location=dl.EntryLocation.path("/Users/me"),
        name="Old Sales",
    )

    assert dataset.name == "New Sales"
    assert dataset.dir_path == "/Users/me"
    assert dataset.key == "/Users/me/New Sales"
    assert dataset.location == dl.EntryLocation.path("/Users/me")


def test_connection_create_read_update_map_top_level_metadata_when_response_contains_it() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": httpx.Response(
                200,
                json=_connection_metadata_response(
                    connection_id="conn-create",
                    name="Created PG",
                    description="Created connection",
                    dir_path="/sdk/create",
                ),
            ),
            "/rpc/getConnection": httpx.Response(
                200,
                json=_connection_metadata_response(
                    connection_id="conn-read",
                    name="Read PG",
                    description="Read connection",
                    dir_path="/sdk/read",
                ),
            ),
            "/rpc/updateConnection": httpx.Response(
                200,
                json=_connection_metadata_response(
                    connection_id="conn-read",
                    name="Updated PG",
                    description="Updated connection",
                    dir_path="/sdk/update",
                ),
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    created = (
        client.create.connection.postgres(name="Builder PG", location=dl.EntryLocation.path("/builder"))
        .host("h")
        .port(5432)
        .build()
    )
    fetched = client.get.connection(by_id="conn-read")
    updated = fetched.update.name("Updated PG").execute()

    _assert_connection_top_level_metadata(
        created,
        connection_id="conn-create",
        name="Created PG",
        description="Created connection",
        dir_path="/sdk/create",
    )
    _assert_connection_top_level_metadata(
        fetched,
        connection_id="conn-read",
        name="Read PG",
        description="Read connection",
        dir_path="/sdk/read",
    )
    _assert_connection_top_level_metadata(
        updated,
        connection_id="conn-read",
        name="Updated PG",
        description="Updated connection",
        dir_path="/sdk/update",
    )

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createConnection",
        "/rpc/getConnection",
        "/rpc/updateConnection",
    ]


def test_connection_update_preserves_target_name_and_location_for_sparse_response() -> None:
    recorder = RecordedTransport({"/rpc/updateConnection": httpx.Response(200, json={"id": "conn-1"})})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    target = client.domain_connection(id="conn-1", type="postgres", name="Target Connection")
    target.location = dl.EntryLocation.workbook("workbook-1")

    updated = target.update.description("Updated").execute()

    assert updated.name == "Target Connection"
    assert updated.location == dl.EntryLocation.workbook("workbook-1")


def test_dataset_create_read_update_validate_map_top_level_metadata_when_response_contains_it() -> None:
    validate_response = _dataset_metadata_response(
        dataset_id="ds-validate",
        name="Validated dataset",
        description="Validated description",
        dir_path="/sdk/validate",
        revision="validate",
    )
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": httpx.Response(
                200,
                json=_dataset_metadata_response(
                    dataset_id="ds-create",
                    name="Created dataset",
                    description="Created description",
                    dir_path="/sdk/create",
                    revision="create",
                ),
            ),
            "/rpc/getDataset": httpx.Response(
                200,
                json=_dataset_metadata_response(
                    dataset_id="ds-read",
                    name="Read dataset",
                    description="Read description",
                    dir_path="/sdk/read",
                    revision="read",
                ),
            ),
            "/rpc/validateDataset": httpx.Response(200, json=validate_response),
            "/rpc/updateDataset": httpx.Response(
                200,
                json=_dataset_metadata_response(
                    dataset_id="ds-read",
                    name="Updated dataset",
                    description="Updated description",
                    dir_path="/sdk/update",
                    revision="update",
                ),
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    created = client.create.dataset(name="Builder dataset", location=dl.EntryLocation.path("/builder")).build()
    fetched = client.get.dataset(by_id="ds-read")
    updated = fetched.update.description("Updated description").execute()
    validated = DatasetConverter.to_domain(validate_response, installation="yacloud")

    _assert_dataset_top_level_metadata(
        created,
        dataset_id="ds-create",
        name="Created dataset",
        description="Created description",
        dir_path="/sdk/create",
        revision="create",
    )
    _assert_dataset_top_level_metadata(
        fetched,
        dataset_id="ds-read",
        name="Read dataset",
        description="Read description",
        dir_path="/sdk/read",
        revision="read",
    )
    _assert_dataset_top_level_metadata(
        updated,
        dataset_id="ds-read",
        name="Updated dataset",
        description="Updated description",
        dir_path="/sdk/update",
        revision="update",
    )
    _assert_dataset_top_level_metadata(
        validated,
        dataset_id="ds-validate",
        name="Validated dataset",
        description="Validated description",
        dir_path="/sdk/validate",
        revision="validate",
    )

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createDataset",
        "/rpc/getDataset",
        "/rpc/validateDataset",
        "/rpc/updateDataset",
    ]


def test_connection_create_update_delete_flow_uses_foreign_rpc_shape() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": httpx.Response(200, json={"id": "conn-1"}),
            "/rpc/getConnection": [
                httpx.Response(
                    200,
                    json={
                        "id": "conn-1",
                        "db_type": "postgres",
                        "name": "My PG",
                        "description": "A test connection",
                        "host": "db.local",
                        "port": 6432,
                        "future_server_field": {"preserved": True},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "id": "conn-1",
                        "db_type": "postgres",
                        "name": "Old Name",
                        "host": "db.local",
                        "port": 6432,
                    },
                ),
            ],
            "/rpc/updateConnection": httpx.Response(
                200,
                json={"id": "conn-1", "db_type": "postgres", "name": "New Name", "host": "db.local", "port": 6432},
            ),
            "/rpc/deleteConnection": httpx.Response(200),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    created = (
        client.create.connection.postgres(name="My PG", location=dl.EntryLocation.path("/Users/me"))
        .description("A test connection")
        .host("db.local")
        .port(6432)
        .db_name("analytics")
        .username("robot")
        .build()
    )
    fetched = client.get.connection(by_id="conn-1", workbook_id="wb-1")
    updated = fetched.update.name("New Name").execute()
    updated.delete()

    assert isinstance(created, dl.Connection)
    assert created.id == "conn-1"
    assert created.type == "postgres"
    assert created.host == "db.local"
    assert created.future_server_field == {"preserved": True}
    assert fetched.name == "Old Name"
    assert updated.name == "New Name"

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createConnection",
        "/rpc/getConnection",
        "/rpc/getConnection",
        "/rpc/updateConnection",
        "/rpc/deleteConnection",
    ]
    assert recorder.request_json(0) == {
        "data_export_forbidden": "off",
        "db_name": "analytics",
        "description": "A test connection",
        "dir_path": "/Users/me",
        "enforce_collate": "auto",
        "host": "db.local",
        "name": "My PG",
        "port": 6432,
        "raw_sql_level": "off",
        "ssl_enable": "off",
        "type": "postgres",
        "username": "robot",
    }
    assert "db_type" not in recorder.request_json(0)
    assert recorder.request_json(2) == {"connectionId": "conn-1", "workbookId": "wb-1"}
    assert recorder.request_json(3) == {"connectionId": "conn-1", "data": {"name": "New Name"}}
    assert recorder.request_json(4) == {"connectionId": "conn-1"}


def test_connection_get_sends_rev_id_as_snake_case() -> None:
    recorder = RecordedTransport(
        {"/rpc/getConnection": httpx.Response(200, json={"id": "c1", "type": "postgres", "name": "PG"})}
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    client.get.connection(by_id="c1", rev_id="r5")

    assert recorder.request_json(0) == {"connectionId": "c1", "rev_id": "r5"}


def test_dataset_get_sends_rev_id_as_snake_case() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(
                200,
                json=_dataset_metadata_response(
                    dataset_id="d1", name="DS", description="", dir_path="/x", revision="1"
                ),
            )
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    client.get.dataset(by_id="d1", rev_id="r5")

    assert recorder.request_json(0) == {"datasetId": "d1", "rev_id": "r5"}


def test_dataset_create_flow_serializes_generated_sources_and_read_model() -> None:
    validate_response = httpx.Response(
        200,
        json={
            "dataset": {
                "description": "Sales mart",
                "sources": [
                    {
                        "id": "source-from-server",
                        "title": "orders",
                        "source_type": "PG_TABLE",
                        "connection_id": "conn-1",
                        "connection_type": "postgres",
                        "parameters": {"schema_name": "public", "table_name": "orders"},
                    }
                ],
                "source_avatars": [],
                "avatar_relations": [],
                "result_schema": [],
            },
        },
    )
    recorder = RecordedTransport(
        {
            "/rpc/validateDataset": [validate_response, validate_response],
            "/rpc/createDataset": httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "name": "sales",
                    "future_top_level": "ignored-by-dto-but-preserved-in-raw",
                    "dataset": {
                        "description": "Sales mart",
                        "future_dataset_field": {"keep": True},
                        "sources": [
                            {
                                "id": "source-from-server",
                                "title": "orders",
                                "source_type": "PG_TABLE",
                                "connection_id": "conn-1",
                                "connection_type": "postgres",
                                "parameters": {"schema_name": "public", "table_name": "orders"},
                            }
                        ],
                        "source_avatars": [],
                        "avatar_relations": [],
                    },
                },
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    connection = client.domain_connection(id="conn-1", type="postgres", name="PG")
    source_factory = client.create.source(using=connection)
    source = source_factory.pg_table(
        alias="orders",
        schema_name="public",
        table_name="orders",
    ).build()

    dataset = (
        client.create.dataset(name="sales", location=dl.EntryLocation.path("/Users/me"))
        .description("Sales mart")
        .add_source(source)
        .build()
    )

    assert isinstance(dataset, dl.Dataset)
    assert dataset.id == "ds-1"
    assert dataset.name == "sales"
    assert dataset.raw["future_top_level"] == "ignored-by-dto-but-preserved-in-raw"
    assert dataset.sources[0].source_type == "PG_TABLE"
    assert dataset.sources[0].connection_id == "conn-1"
    assert dataset.sources[0].parameters == {"schema_name": "public", "table_name": "orders"}

    assert len(recorder.requests) == 3
    validate_payload = recorder.request_json(0)
    assert "data" in validate_payload
    validate_data = cast(dict[str, object], validate_payload["data"])
    assert "updates" in validate_data

    create_payload = recorder.request_json(2)
    assert create_payload["name"] == "sales"
    assert create_payload["dir_path"] == "/Users/me"
    create_dataset = cast(dict[str, object], create_payload["dataset"])
    assert create_dataset["description"] == "Sales mart"


def test_converters_are_the_dto_boundary_for_connection_and_dataset_create() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    connection_builder = (
        client.create.connection.postgres(name="PG", location=dl.EntryLocation.path("/sdk")).host("h").port(5432)
    )
    connection_dto = ConnectionConverter.from_domain_create(connection_builder.to_spec())

    assert isinstance(connection_dto, dto.ConnectionCreateDTO)
    assert connection_dto.connection_type == "postgres"
    assert connection_dto.to_payload()["type"] == "postgres"
    assert "connectionType" not in connection_dto.to_payload()

    source = Source(
        id=str(uuid4()),
        source_type="PG_TABLE",
        title="orders",
        connection_id="conn-1",
        connection_type="postgres",
        parameters={"table_name": "orders"},
    )
    dataset_builder = client.create.dataset(name="DS", location=dl.EntryLocation.path("/sdk")).sources([source])
    dataset_dto = DatasetConverter.from_domain_create(dataset_builder.to_spec())

    assert isinstance(dataset_dto, dto.DatasetCreateDTO)
    assert dataset_dto.dataset.sources[0].source_type == "PG_TABLE"
    assert dataset_dto.dataset.sources[0].connection_id == "conn-1"
    dataset_payload = cast(dict[str, object], dataset_dto.to_payload()["dataset"])
    sent_sources = cast(list[dict[str, object]], dataset_payload["sources"])
    assert sent_sources[0]["parameters"] == {"table_name": "orders"}


def test_generated_builders_validate_fields_before_transport() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    builder = client.create.connection.postgres(name="PG", location=dl.EntryLocation.path("/sdk"))

    assert not (builder._metadata.required & {"name", "dir_path", "workbook_id", "collection_id"})
    assert builder.required_fields() == ["host", "port"]
    assert builder.missing_required() == ["host", "port"]
    assert builder.allowed_values("raw_sql_level") == ["off", "subselect", "template", "dashsql"]
    assert "username" in builder.optional_fields()
    assert "dir_path" not in builder.optional_fields()
    assert "workbook_id" not in builder.optional_fields()

    with pytest.raises(dl.DatalensValidationError, match="missing required fields"):
        builder.build()
    with pytest.raises(dl.NotSupportedError, match=r"postgres\.raw_sql_level='bad' is not allowed"):
        builder._set("raw_sql_level", "bad")
    with pytest.raises(dl.NotSupportedError, match=r"postgres\.unknown is not available"):
        builder._set("unknown", "value")

    assert seen == []


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
def test_clickhouse_secure_is_consistent_across_installations(installation: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "conn-1", "type": "clickhouse", "name": "CH"})

    transport = httpx.MockTransport(handler)
    client: dl.DataLensClientYC | dl.DataLensClientEnterprise
    if installation == "yacloud":
        client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=transport)
    else:
        client = dl.DataLensClientEnterprise(auth=None, base_url="http://test", transport=transport)
    builder = (
        client.create.connection.clickhouse(name="CH", location=dl.EntryLocation.path("/sdk"))
        .host("ch.local")
        .port(8443)
    )

    assert builder.allowed_values("secure") == ["on", "off"]
    with pytest.raises(dl.NotSupportedError, match=r"clickhouse\.secure=True is not allowed"):
        builder.secure(True)  # type: ignore[arg-type]
    assert seen == []

    builder.secure("on").build()

    assert len(seen) == 1
    payload: object = json.loads(seen[0].content.decode())
    assert isinstance(payload, dict)
    assert payload["secure"] == "on"


def test_source_factory_rejects_wrong_or_unbound_connections_before_transport() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    bigquery_connection = client.domain_connection(id="bq-1", type="bigquery")
    bigquery_source_factory = client.create.source(using=bigquery_connection)
    with pytest.raises(dl.NotSupportedError, match="requires 'postgres', got 'bigquery'"):
        bigquery_source_factory.pg_table(alias="orders", table_name="orders")

    connection_without_id = client.domain_connection(id="", type="postgres")
    unbound_source_factory = client.create.source(using=connection_without_id)
    with pytest.raises(dl.DatalensValidationError, match="requires a connection with an id"):
        unbound_source_factory.pg_table(alias="orders", table_name="orders")


def test_read_dtos_ignore_unknown_fields_while_domain_raw_preserves_response(tmp_path: Path) -> None:
    connection_payload = {
        "id": "conn-1",
        "db_type": "postgres",
        "name": "PG",
        "server_added": {"keep": True},
    }
    connection_dto = dto.ConnectionReadDTO.model_validate(connection_payload)
    connection = ConnectionConverter.to_domain(connection_dto, installation="yacloud")

    assert "server_added" not in connection_dto.model_dump()
    assert connection.raw["server_added"] == {"keep": True}
    assert connection.server_added == {"keep": True}

    dataset_payload = {
        "id": "ds-1",
        "dataset": {"description": "", "sources": [], "future_nested": 1},
        "future_top_level": 2,
    }
    dataset_dto = dto.DatasetReadDTO.model_validate(dataset_payload)
    dataset = DatasetConverter.to_domain(dataset_dto, installation="yacloud")

    assert "future_top_level" not in dataset_dto.model_dump()
    assert dataset.raw["future_top_level"] == 2
    assert dataset.response_snapshot == {}
    raw_dataset = cast(dict[str, object], dataset.raw["dataset"])
    assert raw_dataset["future_nested"] == 1
    with pytest.raises(dl.DatalensValidationError, match=r"client\.get\.dataset"):
        dataset.to_file(tmp_path)


def test_connection_read_maps_top_level_navigation_fields() -> None:
    connection_payload = {
        "id": "conn-1",
        "type": "postgres",
        "key": "Users/me/PG",
    }

    connection = ConnectionConverter.to_domain(connection_payload, installation="yacloud")

    assert connection.key == "Users/me/PG"
    assert connection.name == "PG"
    assert connection.dir_path == "Users/me"


def test_dataset_update_preserves_entry_metadata_when_response_omits_it() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "key": "Users/me/Sales",
                    "dataset": {
                        "description": "Old description",
                        "sources": [],
                        "source_avatars": [],
                        "avatar_relations": [],
                    },
                },
            ),
            "/rpc/validateDataset": httpx.Response(
                200,
                json={
                    "dataset": {
                        "description": "New description",
                        "sources": [],
                        "source_avatars": [],
                        "avatar_relations": [],
                    },
                },
            ),
            "/rpc/updateDataset": httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "publishedId": "pub-1",
                    "revId": "rev-1",
                    "savedId": "saved-1",
                    "dataset": {
                        "description": "New description",
                        "sources": [],
                        "source_avatars": [],
                        "avatar_relations": [],
                    },
                },
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    dataset = client.get.dataset(by_id="ds-1").update.description("New description").execute()

    assert dataset.name == "Sales"
    assert dataset.dir_path == "Users/me"
    assert dataset.key == "Users/me/Sales"
    assert dataset.location == dl.EntryLocation.path("Users/me")
    assert dataset.description == "New description"
    assert dataset.published_id == "pub-1"


def test_dataset_update_continues_with_validation_result_from_http_400(
    caplog: pytest.LogCaptureFixture,
) -> None:
    component_errors = {
        "items": [
            {
                "type": "field",
                "id": "field-1",
                "errors": [
                    {
                        "code": "ERR.DS_API.FORMULA.UNKNOWN_FIELD_IN_FORMULA",
                        "message": "Unknown field found in formula: missing",
                    }
                ],
            }
        ]
    }
    validated_dataset = {
        "description": "New description",
        "sources": [],
        "source_avatars": [],
        "avatar_relations": [],
        "component_errors": component_errors,
    }
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "key": "Users/me/Sales",
                    "dataset": {
                        "description": "Old description",
                        "sources": [],
                        "source_avatars": [],
                        "avatar_relations": [],
                    },
                },
            ),
            "/rpc/validateDataset": httpx.Response(
                400,
                json={
                    "code": "ERR.DS_API.VALIDATION.ERROR",
                    "message": "Validation finished with errors.",
                    "details": {
                        "data": {
                            "savedId": "ds-1",
                            "revId": "ds-1",
                            "dataset": validated_dataset,
                        }
                    },
                },
            ),
            "/rpc/updateDataset": httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "key": "Users/me/Sales",
                    "dataset": validated_dataset,
                },
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    caplog.set_level(logging.WARNING, logger="datalens_sdk.http")

    dataset = client.get.dataset(by_id="ds-1").update.description("New description").execute()

    assert dataset.description == "New description"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getDataset",
        "/rpc/validateDataset",
        "/rpc/updateDataset",
    ]
    assert recorder.request_json(2)["data"] == {"dataset": validated_dataset}
    assert caplog.text.count("Accepting DataLens error response as API payload") == 1
    assert caplog.text.count("DataLens dataset component errors") == 1
    assert "DataLens dataset component errors: operation=validateDataset" in caplog.text
    assert "DataLens dataset component errors: operation=updateDataset" not in caplog.text


def test_write_dtos_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        dto.ConnectionCreateDTO.model_validate(
            {
                "installation": "yacloud",
                "connection_type": "postgres",
                "params": {"name": "PG", "dir_path": "/sdk", "host": "h", "port": 5432, "type": "postgres"},
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        dto.DatasetCreateDTO.model_validate(
            {
                "installation": "yacloud",
                "name": "DS",
                "dir_path": "/sdk",
                "dataset": {"description": "", "sources": [], "source_avatars": [], "avatar_relations": []},
                "unexpected": True,
            }
        )


def test_http_errors_and_invalid_responses_are_typed() -> None:
    not_found = RecordedTransport(
        {"/rpc/getConnection": httpx.Response(404, json={"code": "ERR.NOT_FOUND", "message": "missing"})}
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(not_found.handler))

    with pytest.raises(dl.NotFoundError) as not_found_exc:
        client.get.connection(by_id="missing")

    assert not_found_exc.value.context.status_code == 404
    assert not_found_exc.value.context.code == "ERR.NOT_FOUND"
    assert not_found_exc.value.context.message == "missing"
    assert not_found_exc.value.context.request_url == "http://test/rpc/getConnection"

    server_error = RecordedTransport(
        {
            "/rpc/getDataset": [
                httpx.Response(500, json={"message": "Internal Server Error"}, headers={"x-request-id": "req-500"})
                for _ in range(3)
            ]
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(server_error.handler))

    with pytest.raises(dl.ServerError) as server_error_exc:
        client.get.dataset(by_id="broken")

    assert server_error_exc.value.context.request_id == "req-500"
    assert server_error_exc.value.context.attempts == 3
    assert "x-request-id=req-500" in str(server_error_exc.value)

    invalid = RecordedTransport({"/rpc/getDataset": httpx.Response(200, text="not-json")})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(invalid.handler))

    with pytest.raises(dl.InvalidResponseError, match="not valid JSON"):
        client.get.dataset(by_id="ds-1")


def test_chart_create_get_delete_flow_uses_wizard_rpc() -> None:
    # create-response deliberately omits data.visualization.id, so the returned chart's
    # visualization_id can only come from the create-spec fallback
    # (api/chart.py: visualization_id_fallback=spec.viz_id). The assertion below then
    # protects that fallback end-to-end through builder.build() -> service -> converter.
    created_response = {
        "entryId": "chart-1",
        "key": "/Users/me/Sales",
        "type": "d3_wizard_node",
        "data": {"visualization": {"placeholders": []}},
    }
    get_response = {
        "entryId": "chart-1",
        "key": "/Users/me/Sales",
        "type": "d3_wizard_node",
        "data": {"visualization": {"id": "line", "placeholders": []}},
    }
    recorder = RecordedTransport(
        {
            "/rpc/createWizardChart": httpx.Response(200, json=created_response),
            "/rpc/getWizardChart": httpx.Response(200, json=get_response),
            "/rpc/deleteWizardChart": httpx.Response(200),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    dataset = dl.Dataset(
        id="ds-1",
        name="sales",
        location=dl.EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_date", "title": "Order Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ),
    )

    chart = (
        client.create.wizard_chart.line(name="Sales", location=dl.EntryLocation.path("/Users/me"))
        .dataset(dataset)
        .x(["Order Date"])
        .y(["Amount"])
        .build()
    )

    fetched = client.get.wizard_chart(by_id="chart-1")
    fetched.delete()

    assert isinstance(chart, dl.Chart)
    assert chart.id == "chart-1"
    # Sourced from the create-spec fallback (created_response has no visualization.id).
    assert chart.visualization_id == "line"
    assert chart.wire_type == "d3_wizard_node"

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createWizardChart",
        "/rpc/getWizardChart",
        "/rpc/deleteWizardChart",
    ]
    create_payload = recorder.request_json(0)
    assert create_payload["template"] == "datalens"
    assert create_payload["key"] == "/Users/me/Sales"
    # API requires either 'key' (folder entry) OR 'workbookId'+'name' (workbook entry) — not both.
    # When key is set, name must not be sent to avoid VALIDATION_ERROR.
    assert "name" not in create_payload
    create_data = cast(dict[str, object], create_payload["data"])
    viz = cast(dict[str, object], create_data["visualization"])
    assert viz["id"] == "line"
    placeholder_ids = [cast(dict[str, object], p)["id"] for p in cast(list[object], viz["placeholders"])]
    assert placeholder_ids == ["x", "y", "y2", "shapes"]
    assert create_data["datasetsIds"] == ["ds-1"]
    assert recorder.request_json(2) == {"chartId": "chart-1"}


def test_chart_converter_is_dto_boundary() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    dataset = dl.Dataset(
        id="ds-1",
        name="sales",
        location=dl.EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ),
    )
    builder = (
        client.create.wizard_chart.indicator(name="I", location=dl.EntryLocation.path("/sdk"))
        .dataset(dataset)
        .y(["Amount"])
    )
    chart_dto = WizardChartConverter.from_domain_create(builder.to_spec())

    assert isinstance(chart_dto, dto.WizardChartCreateDTO)
    payload = chart_dto.to_payload()
    assert payload["template"] == "datalens"
    assert "data" in payload


def test_public_exports_cover_user_visible_errors() -> None:
    public_names = set(dl.__all__)

    assert len(public_names) == len(dl.__all__)
    for name in dl.__all__:
        assert hasattr(dl, name)

    missing = {
        name
        for name, value in vars(dl).items()
        if isinstance(value, type)
        and issubclass(value, dl.DatalensError)
        and value.__module__.startswith("datalens_sdk")
        and not name.startswith("_")
        and name not in public_names
    }
    assert missing == set()


def test_connection_create_to_spec_snapshots_builder_state() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    location = dl.EntryLocation.path("/sdk")
    builder = client.create.connection.postgres(name="PG", location=location).host("db.local").port(5432)

    spec = builder.to_spec()

    assert isinstance(spec, ConnectionCreateSpec)
    assert spec.installation == "yacloud"
    assert spec.connector == "postgres"
    assert spec.name == "PG"
    assert spec.location is location
    assert spec.params["type"] == "postgres"
    assert spec.params["host"] == "db.local"
    assert spec.params["port"] == 5432
    assert "name" not in spec.params
    assert "dir_path" not in spec.params

    # Spec is a frozen snapshot: mutating the builder afterwards must not affect it.
    builder.host("other.host")
    assert spec.params["host"] == "db.local"

    # Spec itself is immutable.
    with pytest.raises((AttributeError, Exception)):
        spec.connector = "clickhouse"  # type: ignore[misc]


def test_connection_update_to_spec_snapshots_changes() -> None:
    update = (
        dl.ConnectionUpdate(connection_id="conn-1", connection_type="postgres")
        .name("New Name")
        .set("host", "db.remote")
    )

    spec = update.to_spec()

    assert isinstance(spec, ConnectionUpdateSpec)
    assert spec.connection_id == "conn-1"
    assert spec.changes["name"] == "New Name"
    assert spec.changes["host"] == "db.remote"

    # Spec is a frozen snapshot: mutating the builder afterwards must not affect it.
    update.name("Another")
    assert spec.changes["name"] == "New Name"

    # Spec itself is immutable.
    with pytest.raises((AttributeError, Exception)):
        spec.connection_id = "conn-2"  # type: ignore[misc]


def test_connection_representations_hide_credentials_without_changing_payloads() -> None:
    secret = "repr-secret-sentinel"
    location = dl.EntryLocation.path("/sdk")
    create_spec = ConnectionCreateSpec(
        installation="yacloud",
        connector="postgres",
        name="PG",
        params={"password": secret},
        location=location,
    )
    update_spec = ConnectionUpdateSpec(connection_id="conn-1", changes={"password": secret})
    create_dto = dto.ConnectionCreateDTO(
        installation="yacloud",
        connection_type="postgres",
        params={"name": "PG", "password": secret},
    )
    for value in (create_spec, update_spec, create_dto):
        assert secret not in repr(value)

    assert create_dto.to_payload()["password"] == secret
    assert ConnectionConverter.from_domain_update(update_spec)["data"] == {"password": secret}
