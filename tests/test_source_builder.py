from __future__ import annotations

from collections.abc import Callable
import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk import JoinCondition
from datalens_sdk.domain.dataset import Source, SourceCreate


class RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {path: list(r) if isinstance(r, list) else [r] for path, r in (routes or {}).items()}
        self._handler_func: Callable[[httpx.Request], httpx.Response] | None = None

    def set_handler(self, func: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler_func = func

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._handler_func:
            return self._handler_func(request)
        responses = self._routes.get(request.url.path)
        if not responses:
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        response = responses.pop(0)
        response.request = request
        return response

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)


def test_source_build_fires_validate_and_returns_enriched_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/validateDataset":
            body = json.loads(request.content.decode())
            updates = body["data"]["updates"]
            source_id = updates[0]["source"]["id"]
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "sources": [
                            {
                                "id": source_id,
                                "source_type": "PG_TABLE",
                                "valid": True,
                                "raw_schema": [
                                    {"name": "order_date", "title": "Order Date", "user_type": "date", "nullable": True}
                                ],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    recorder = RecordedTransport()
    recorder.set_handler(handler)
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    connection = client.domain_connection(id="conn-1", type="postgres", name="PG")
    source_create = client.create.source(using=connection).pg_table(
        alias="orders", schema_name="public", table_name="orders"
    )

    assert isinstance(source_create, dl.SourceCreate)

    source = source_create.build()

    assert isinstance(source, dl.Source)
    assert len(source.raw_schema) == 1
    assert source.raw_schema[0]["name"] == "order_date"
    assert source.fields.by_name("Order Date").name == "order_date"
    assert len(recorder.requests) == 1
    body = recorder.request_json(0)
    updates = cast(list[dict[str, object]], cast(dict[str, object], body["data"])["updates"])
    assert [u["action"] for u in updates] == ["add_source", "add_source_avatar", "refresh_source"]


def test_built_source_raw_schema_is_reused_in_graph_validate_without_refresh() -> None:
    source_id_holder: dict[str, str | None] = {"id": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/validateDataset":
            body = json.loads(request.content.decode())
            updates = body["data"]["updates"]
            source_id = updates[0]["source"]["id"]
            source_id_holder["id"] = source_id
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "sources": [
                            {
                                "id": source_id,
                                "source_type": "PG_TABLE",
                                "valid": True,
                                "raw_schema": [
                                    {"name": "order_date", "title": "Order Date", "user_type": "date", "nullable": True}
                                ],
                            }
                        ],
                        "source_avatars": [{"id": source_id, "source_id": source_id, "title": "orders"}],
                        "avatar_relations": [],
                        "result_schema": [
                            {
                                "guid": "field-1",
                                "title": "Order Date",
                                "source": "order_date",
                                "data_type": "date",
                                "cast": "date",
                                "type": "DIMENSION",
                                "avatar_id": source_id,
                            }
                        ],
                    }
                },
            )
        if request.url.path == "/rpc/createDataset":
            source_id = source_id_holder["id"]
            return httpx.Response(
                200,
                json={
                    "id": "ds-new",
                    "name": "test_ds",
                    "dataset": {
                        "description": "",
                        "sources": [
                            {
                                "id": source_id,
                                "title": "orders",
                                "source_type": "PG_TABLE",
                                "connection_id": "conn-1",
                                "connection_type": "postgres",
                                "parameters": {"schema_name": "public", "table_name": "orders"},
                                "raw_schema": [{"name": "order_date", "title": "Order Date", "user_type": "date"}],
                            }
                        ],
                        "source_avatars": [],
                        "avatar_relations": [],
                        "result_schema": [],
                    },
                },
            )
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    recorder = RecordedTransport()
    recorder.set_handler(handler)
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    connection = client.domain_connection(id="conn-1", type="postgres", name="PG")
    source = (
        client.create.source(using=connection)
        .pg_table(alias="orders", schema_name="public", table_name="orders")
        .build()
    )

    assert len(source.raw_schema) == 1, "source.build() must populate raw_schema"

    dataset = (
        client.create.dataset(name="test_ds", location=dl.EntryLocation.path("/Users/me")).add_source(source).build()
    )

    assert isinstance(dataset, dl.Dataset)
    assert dataset.id == "ds-new"

    graph_validate_body = recorder.request_json(1)
    graph_updates = cast(list[dict[str, object]], cast(dict[str, object], graph_validate_body["data"])["updates"])
    graph_actions = [u["action"] for u in graph_updates]
    assert "refresh_source" not in graph_actions, "graph-validate must not refresh when raw_schema is already populated"
    source_in_graph_validate = cast(dict[str, object], graph_updates[0]["source"])
    assert len(cast(list[object], source_in_graph_validate["raw_schema"])) == 1


def test_self_join_with_explicit_sources_succeeds() -> None:
    source_id_holder = {"id": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/validateDataset":
            body = json.loads(request.content.decode())
            updates = body["data"]["updates"]
            source_id = updates[0]["source"]["id"]
            source_id_holder["id"] = source_id
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "sources": [
                            {
                                "id": source_id,
                                "source_type": "PG_TABLE",
                                "valid": True,
                                "raw_schema": [
                                    {"name": "order_date", "title": "Order Date", "user_type": "date", "nullable": True}
                                ],
                            }
                        ]
                    }
                },
            )
        if request.url.path == "/rpc/createDataset":
            return httpx.Response(200, json={"id": "ds-new", "dataset": {"sources": [], "result_schema": []}})
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    recorder = RecordedTransport()
    recorder.set_handler(handler)
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    connection = client.domain_connection(id="conn-1", type="postgres", name="PG")
    source = (
        client.create.source(using=connection)
        .pg_table(alias="orders", schema_name="public", table_name="orders")
        .build()
    )

    dataset = (
        client.create.dataset(name="test_ds", location=dl.EntryLocation.path("/Users/me"))
        .add_source(source)
        .add_relation(
            type="left",
            conditions=[JoinCondition(left="order_date", right="order_date")],
            left_source=source,
            right_source=source,
        )
        .build()
    )

    assert dataset.id == "ds-new"


def test_dataset_create_with_explicit_sources_and_join() -> None:
    source_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/validateDataset":
            body = json.loads(request.content.decode())
            updates = body["data"]["updates"]
            source_id = updates[0]["source"]["id"]
            source_ids.append(source_id)
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "sources": [
                            {
                                "id": source_id,
                                "source_type": "PG_TABLE",
                                "valid": True,
                                "raw_schema": [
                                    {"name": "order_date", "title": "Order Date", "user_type": "date", "nullable": True}
                                ],
                            }
                        ]
                    }
                },
            )
        if request.url.path == "/rpc/createDataset":
            return httpx.Response(200, json={"id": "ds-new", "dataset": {}})
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    recorder = RecordedTransport()
    recorder.set_handler(handler)
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    connection = client.domain_connection(id="conn-1", type="postgres", name="PG")
    source_a = client.create.source(using=connection).pg_table(alias="a", table_name="a").build()
    source_b = client.create.source(using=connection).pg_table(alias="b", table_name="b").build()

    dataset = (
        client.create.dataset(name="test_ds", location=dl.EntryLocation.path("/Users/me"))
        .add_source(source_a)
        .add_source(source_b)
        .add_relation(
            type="left",
            conditions=[JoinCondition(left="order_date", right="order_date")],
            left_source=source_a,
            right_source=source_b,
        )
        .build()
    )

    assert dataset.id == "ds-new"


def test_source_create_build_without_operations_raises_configuration_error() -> None:
    source = Source(
        id="s1",
        source_type="PG_TABLE",
        title="t",
        connection_id="c",
        connection_type="postgres",
        parameters={},
    )
    unbound = SourceCreate(source=source, operations=None)

    with pytest.raises(dl.DatalensConfigurationError):
        unbound.build()
