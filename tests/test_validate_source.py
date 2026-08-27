from __future__ import annotations

import json
from typing import cast
import warnings

import httpx
import pytest

from datalens_sdk.api.data import DataAPI
from datalens_sdk.api.dataset import DatasetAPI, DatasetService
from datalens_sdk.api.entries import EntriesAPI, EntriesService
from datalens_sdk.converter.dataset import DatasetConverter
from datalens_sdk.domain.dataset import Source
from datalens_sdk.domain.dataset_types import RawSchemaColumnPayload
from datalens_sdk.domain.ports import NavigationOperations
from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.http import DataLensHTTPClient

SOURCE_ID = "src-test-1"


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


def _source_response(valid: bool = True, raw_schema: list[dict[str, object]] | None = None) -> dict[str, object]:
    schema = raw_schema or (
        [{"name": "order_date", "title": "Order Date", "user_type": "date", "nullable": True}] if valid else []
    )
    return {
        "dataset": {
            "sources": [
                {
                    "id": SOURCE_ID,
                    "source_type": "PG_TABLE",
                    "valid": valid,
                    "raw_schema": schema,
                }
            ]
        }
    }


def _make_service(routes: dict[str, list[httpx.Response] | httpx.Response]) -> tuple[DatasetService, RecordedTransport]:
    recorder = RecordedTransport(routes)
    transport = httpx.MockTransport(handler=recorder.handler)
    client = DataLensHTTPClient(
        installation="test",
        sdk_version="1.2.3",
        api_version="2",
        base_url="https://datalens.test",
        transport=transport,
    )
    api = DatasetAPI(client)
    service = DatasetService(
        installation="test",
        api=api,
        data_api=DataAPI(client),
        entries_service=EntriesService(api=EntriesAPI(client)),
        navigation_operations=cast(NavigationOperations, object()),
    )
    return service, recorder


def test_validate_source_valid_returns_schema() -> None:
    source = Source(
        id=SOURCE_ID,
        source_type="PG_TABLE",
        title="orders",
        connection_id="conn-1",
        connection_type="postgres",
        parameters={"schema_name": "public", "table_name": "orders"},
    )
    service, recorder = _make_service({"/rpc/validateDataset": httpx.Response(200, json=_source_response(valid=True))})

    schema, valid = service.validate_source(source)

    assert valid is True
    assert len(schema) > 0
    assert schema[0]["name"] == "order_date"

    assert len(recorder.requests) == 1
    body = json.loads(recorder.requests[0].content.decode())
    updates = body["data"]["updates"]
    actions = [u["action"] for u in updates]
    assert actions == ["add_source", "add_source_avatar", "refresh_source"]
    assert updates[0]["source"]["id"] == SOURCE_ID
    assert updates[0]["source"]["raw_schema"] == []


def test_validate_source_invalid_strict_raises() -> None:
    source = Source(
        id=SOURCE_ID,
        source_type="PG_TABLE",
        title="t",
        connection_id="c",
        connection_type="postgres",
        parameters={},
    )
    service, _ = _make_service({"/rpc/validateDataset": httpx.Response(200, json=_source_response(valid=False))})

    with pytest.raises(DataLensValidationError, match=SOURCE_ID):
        service.validate_source(source, strict=True)


def test_validate_source_invalid_non_strict_warns() -> None:
    source = Source(
        id=SOURCE_ID,
        source_type="PG_TABLE",
        title="t",
        connection_id="c",
        connection_type="postgres",
        parameters={},
    )
    service, _ = _make_service({"/rpc/validateDataset": httpx.Response(200, json=_source_response(valid=False))})

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema, valid = service.validate_source(source, strict=False)

    assert valid is False
    assert schema == ()
    assert len(caught) == 1
    assert SOURCE_ID in str(caught[0].message)


def test_build_validate_source_payload_structure() -> None:
    source = Source(
        id="s1",
        source_type="PG_TABLE",
        title="t",
        connection_id="c",
        connection_type="postgres",
        parameters={},
    )
    payload = DatasetConverter.build_validate_source_payload(source)

    data = payload["data"]
    assert isinstance(data, dict)
    updates = data["updates"]
    assert len(updates) == 3
    assert updates[0]["action"] == "add_source"
    assert updates[0]["source"]["id"] == "s1"
    assert updates[0]["source"]["raw_schema"] == []
    assert updates[1]["action"] == "add_source_avatar"
    assert updates[2]["action"] == "refresh_source"


def test_from_domain_create_validate_step_reuses_raw_schema_skips_refresh() -> None:
    source = Source(
        id="s1",
        source_type="PG_TABLE",
        title="t",
        connection_id="c",
        connection_type="postgres",
        parameters={},
        raw_schema=(
            RawSchemaColumnPayload(
                name="col1",
                title="Col 1",
                user_type="string",
                nullable=True,
                description=None,
                has_auto_aggregation=None,
                lock_aggregation=None,
                native_type=None,
            ),
        ),
    )
    payload = DatasetConverter.from_domain_create_validate_step(
        sources=[source],
        relations=[],
        existing_state=None,
        refresh_sources=True,
    )

    data = payload["data"]
    assert isinstance(data, dict)
    updates = data["updates"]
    actions = [u["action"] for u in updates]
    assert "refresh_source" not in actions, "refresh_source must be skipped when source already has raw_schema"
    assert updates[0]["action"] == "add_source"
    sent_raw_schema = updates[0]["source"]["raw_schema"]
    assert len(sent_raw_schema) == 1
    assert sent_raw_schema[0]["name"] == "col1"


def test_parse_validate_source_response_valid() -> None:
    response = {
        "dataset": {
            "sources": [
                {
                    "id": "s1",
                    "valid": True,
                    "raw_schema": [{"name": "col1", "title": "Col 1", "user_type": "string", "nullable": True}],
                }
            ]
        }
    }
    schema, valid = DatasetConverter.parse_validate_source_response(response, "s1")
    assert valid is True
    assert len(schema) == 1
    assert schema[0]["name"] == "col1"


def test_parse_validate_source_response_invalid() -> None:
    response: dict[str, object] = {"dataset": {"sources": [{"id": "s1", "valid": False, "raw_schema": []}]}}
    schema, valid = DatasetConverter.parse_validate_source_response(response, "s1")
    assert valid is False
    assert schema == ()


def test_parse_validate_source_response_source_not_found() -> None:
    response: dict[str, object] = {"dataset": {"sources": []}}
    schema, valid = DatasetConverter.parse_validate_source_response(response, "s1")
    assert schema == ()
    assert valid is False
