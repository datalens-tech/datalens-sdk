from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from importlib import import_module
import json
from types import ModuleType
from typing import ClassVar, cast

import httpx
from pydantic import BaseModel, ValidationError
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk.api.collection import CollectionAPI
from datalens_sdk.api.entries import EntriesAPI, EntriesService
from datalens_sdk.api.navigation import NavigationService
from datalens_sdk.api.sql_query import SqlQueryService
from datalens_sdk.api.workbook import WorkbookAPI
from datalens_sdk.converter.sql_query import SqlQueryConverter, SqlQueryDtoModule
from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.ports import SqlQueryOperations
from datalens_sdk.domain.specs.sql_query import SqlQueryCreateSpec, SqlQueryUpdateSpec
from datalens_sdk.domain.sql_query import (
    SqlQuery,
    SqlQueryCreate,
    SqlQueryInterval,
    SqlQueryParameter,
    SqlQueryParameterType,
    SqlQueryPermissions,
    SqlQueryRun,
    SqlQueryRunColumn,
    SqlQueryRunStatus,
    SqlQueryRunValue,
    SqlQueryScalar,
    SqlQueryStatementError,
    SqlQueryStatementSuccess,
    SqlQueryUpdate,
)
from datalens_sdk.errors import (
    DataLensConfigurationError,
    DataLensValidationError,
    DTOValidationError,
    ForbiddenError,
    InvalidResponseError,
    ServerError,
)
from datalens_sdk.http import DataLensHTTPClient


class RecordedTransport:
    def __init__(self, routes: Mapping[str, httpx.Response | list[httpx.Response]]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: responses if isinstance(responses, list) else [responses] for path, responses in routes.items()
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
        bodies: list[dict[str, object]] = []
        for request in self.requests:
            if request.url.path == path:
                body: object = json.loads(request.content)
                assert isinstance(body, dict)
                bodies.append(cast(dict[str, object], body))
        return bodies


def _sql_query_service(
    http_client: DataLensHTTPClient, *, dto_module: SqlQueryDtoModule | None = None
) -> SqlQueryOperations:
    sql_query_api = import_module("datalens_sdk.api.sql_query")
    entries_api = EntriesAPI(http_client)
    navigation = NavigationService(
        entries_api=entries_api,
        entries_service=EntriesService(api=entries_api),
        collection_api=CollectionAPI(http_client),
        workbook_api=WorkbookAPI(http_client),
    )
    return cast(
        SqlQueryOperations,
        sql_query_api.SqlQueryService(
            installation="yacloud",
            api=sql_query_api.SqlQueryAPI(http_client),
            navigation_operations=navigation,
            dto_module=dto_module,
        ),
    )


def _sql_query_entry(*, nullable_metadata: bool = False) -> dict[str, object]:
    entry: dict[str, object] = {
        "entryId": "query-1",
        "scope": "sql_query",
        "type": "sql_query",
        "key": "",
        "workbookId": "workbook-1",
        "collectionId": "collection-1",
        "revId": "rev-2",
        "savedId": "saved-1",
        "publishedId": "published-1",
        "version": 1.5,
        "revUpdatedBy": "revision-user",
        "revUpdatedAt": "2026-09-30T12:00:00Z",
        "data": {
            "connectionId": "connection-1",
            "query": "select :day",
            "params": [
                {"name": "text", "type": "string", "defaultValue": "Revenue"},
                {"name": "amount", "type": "number", "defaultValue": 1.5},
                {"name": "active", "type": "boolean", "defaultValue": False},
                {"name": "day", "type": "date", "defaultValue": "2026-09-29"},
                {"name": "time", "type": "datetime", "defaultValue": "2026-09-29T10:00:00"},
                {
                    "name": "days",
                    "type": "date-interval",
                    "defaultValue": {"from": "2026-09-01", "to": "2026-09-30"},
                },
                {
                    "name": "times",
                    "type": "datetime-interval",
                    "defaultValue": {"from": "2026-09-29T00:00:00", "to": "2026-09-30T00:00:00"},
                },
                {"name": "optional", "type": "string"},
            ],
            "statementPositions": [[0, 1.5], [2.5, 11]],
        },
        "annotation": {"description": "Revenue query"},
        "createdBy": "creator-user",
        "createdAt": "2026-09-29T00:00:00Z",
        "updatedBy": "editor-user",
        "updatedAt": "2026-09-30T00:00:00Z",
        "tenantId": "tenant-1",
        "hidden": True,
        "links": {"connection": "connection-1"},
    }
    if nullable_metadata:
        entry.update(collectionId=None, publishedId=None, version=None, annotation=None, links=None)
        del entry["revUpdatedBy"]
        del entry["revUpdatedAt"]
    return entry


def _navigation_entry(entry_id: str, name: str) -> dict[str, object]:
    return {"entryId": entry_id, "scope": "sql_query", "type": "sql_query", "key": "", "name": name}


def test_yc_sql_lakehouse_and_spark_actions_dispatch_without_metadata_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installations = client_module._load_installations("datalens_sdk._generated")
    installations["yacloud"]["namespaces"] = [
        name
        for name in installations["yacloud"]["namespaces"]
        if name not in {"sql_queries", "lakehouse_operations", "spark_clusters"}
    ]
    monkeypatch.setattr(client_module, "_load_installations", lambda package: installations)
    recorder = RecordedTransport(
        {
            "/rpc/createSqlQuery": httpx.Response(200, json={"entry": _sql_query_entry()}),
            "/rpc/getSqlQuery": httpx.Response(200, json={"entry": _sql_query_entry()}),
            "/rpc/getEntries": httpx.Response(200, json={"entries": [_navigation_entry("query-1", "Saved revenue")]}),
            "/rpc/deleteSqlQuery": httpx.Response(200, json={}),
            "/rpc/runSqlQuery": httpx.Response(200, json=_sql_query_run_result()),
            "/rpc/getLakehouseOperation": [
                httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}}),
                httpx.Response(200, json={"id": "operation-1", "done": True, "metadata": {"phase": "done"}}),
            ],
            "/rpc/getSparkCluster": httpx.Response(
                200,
                json={
                    "id": "spark-public-1",
                    "clusterId": "spark-managed-1",
                    "collectionId": "collection-1",
                    "cloudEnvironmentId": "environment-1",
                    "name": "Spark analytics",
                    "description": "",
                    "labels": {},
                    "health": "ALIVE",
                    "status": "RUNNING",
                    "entryId": "",
                    "config": {
                        "sparkVersion": "3.5",
                        "dependencies": None,
                        "logging": None,
                        "resourcePools": {
                            "driver": {
                                "resourcePresetId": "driver-1",
                                "scalePolicy": {"scaleType": "fixedScale", "fixedScale": {"size": "1"}},
                            },
                            "executor": {
                                "resourcePresetId": "executor-1",
                                "scalePolicy": {
                                    "scaleType": "autoScale",
                                    "autoScale": {"minSize": "0", "initialSize": "1", "maxSize": "10"},
                                },
                            },
                        },
                    },
                },
            ),
        }
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    with client:
        created = (
            client.create.sql_query(name="Revenue", location=EntryLocation.workbook("workbook-1"))
            .connection(client.domain_connection(id="connection-1", type="postgres"))
            .query("select :day")
            .parameters([SqlQueryParameter.date("day")])
            .build()
        )
        loaded = client.get.sql_query(by_id="query-1", rev_id="rev-2", include_favorite=False, include_permissions=True)
        assert created.name == "Revenue"
        assert created.location == EntryLocation.workbook("workbook-1")
        assert loaded.name == "Saved revenue"
        assert loaded.run().status == "partial_success"
        created.delete()
        operation = client.get.lakehouse_operation(by_id="operation-1")
        refreshed = operation.refresh()
        spark_cluster = client.get.spark_cluster(by_id="spark-public-1")

    assert operation == LakehouseOperation(
        id="operation-1",
        done=False,
        metadata={},
        raw={"id": "operation-1", "done": False, "metadata": {}},
    )
    assert refreshed == LakehouseOperation(
        id="operation-1",
        done=True,
        metadata={"phase": "done"},
        raw={"id": "operation-1", "done": True, "metadata": {"phase": "done"}},
    )
    assert refreshed is not operation
    assert recorder.bodies("/rpc/getLakehouseOperation") == [{"operationId": "operation-1"}] * 2
    assert spark_cluster.id == "spark-public-1"
    assert spark_cluster.cluster_id == "spark-managed-1"
    assert recorder.bodies("/rpc/getSparkCluster") == [{"id": "spark-public-1"}]

    assert recorder.bodies("/rpc/createSqlQuery") == [
        {
            "name": "Revenue",
            "workbookId": "workbook-1",
            "connectionId": "connection-1",
            "query": "select :day",
            "params": [{"name": "day", "type": "date"}],
        }
    ]
    assert recorder.bodies("/rpc/getSqlQuery") == [
        {
            "sqlQueryId": "query-1",
            "revId": "rev-2",
            "includeFavorite": False,
            "includePermissions": True,
        }
    ]
    assert recorder.bodies("/rpc/getEntries") == [
        {
            "ids": ["query-1"],
            "ignoreWorkbookEntries": False,
            "pageSize": 1,
        }
    ]


@pytest.mark.parametrize("client_type", [DataLensClientYC, DataLensClientEnterprise])
def test_sql_queries_are_not_exposed_as_a_root_client_namespace(
    client_type: type[DataLensClientYC] | type[DataLensClientEnterprise],
) -> None:
    client = client_type(
        auth=None,
        base_url="https://datalens.test",
        transport=httpx.MockTransport(RecordedTransport({}).handler),
    )

    with client, pytest.raises(AttributeError) as exc_info:
        _ = client.sql_queries

    assert type(exc_info.value) is AttributeError


def test_enterprise_sql_query_actions_are_absent_without_service_or_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("SqlQueryService initialized for Enterprise")

    monkeypatch.setattr(SqlQueryService, "__init__", unexpected_service)
    recorder = RecordedTransport({})
    with DataLensClientEnterprise(
        auth=None, base_url="https://enterprise.test", transport=httpx.MockTransport(recorder.handler)
    ) as client:
        action_name = "sql_query"
        unknown_name = "unknown_action"
        for namespace in (client.create, client.get):
            with pytest.raises(AttributeError) as exc_info:
                _ = getattr(namespace, action_name)
            assert type(exc_info.value) is AttributeError
            with pytest.raises(AttributeError) as unknown:
                _ = getattr(namespace, unknown_name)
            assert type(unknown.value) is AttributeError
    assert recorder.requests == []


def test_yateam_style_base_sql_query_actions_are_absent_without_dto_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class YaTeamStyleClient(client_module.DataLensClientBase):
        INSTALLATION = "yateam"
        GENERATED_PACKAGE = "test_yateam_generated"
        DEFAULT_BASE_URL = "https://yateam.test"

    class DtoStub(ModuleType):
        INSTALLATION_EDITOR_READ_NODE_TYPES: ClassVar[dict[str, frozenset[str]]] = {"yateam": frozenset()}

        def __getattr__(self, name: str) -> object:
            if "SqlQuery" in name:
                raise AssertionError(f"Unexpected SqlQueries DTO access: {name}")
            return getattr(import_module("datalens_sdk._generated.dto"), name)

    installations: dict[str, client_module.InstallationInfo] = {
        "yateam": {
            "connectors": {},
            "dataset_sources": {},
            "namespaces": [],
            "chart_factories": {"wizard": [], "ql": [], "editor": []},
        }
    }
    sources = import_module("datalens_sdk._generated.builders.dataset_sources")
    charts = import_module("datalens_sdk._generated.builders.charts")
    monkeypatch.setattr(sources, "YateamSourceCreateFactory", sources.EnterpriseSourceCreateFactory, raising=False)
    monkeypatch.setattr(
        charts, "YateamEditorChartCreateFactory", charts.EnterpriseEditorChartCreateFactory, raising=False
    )
    modules = {
        "test_yateam_generated.dto": DtoStub("test_yateam_generated.dto"),
        "test_yateam_generated.builders.yateam": import_module("datalens_sdk._generated.builders.enterprise"),
        "test_yateam_generated.builders.dataset_sources": sources,
        "test_yateam_generated.builders.charts": charts,
    }
    monkeypatch.setattr(client_module, "_load_installations", lambda package: installations)
    monkeypatch.setattr(client_module, "import_module", modules.__getitem__)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("SqlQueryService initialized for an unsupported installation")

    monkeypatch.setattr(SqlQueryService, "__init__", unexpected_service)
    recorder = RecordedTransport({})
    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(recorder.handler)) as client:
        action_name = "sql_query"
        for namespace in (client.create, client.get):
            with pytest.raises(AttributeError) as exc_info:
                _ = getattr(namespace, action_name)
            assert type(exc_info.value) is AttributeError
    assert recorder.requests == []


@pytest.mark.parametrize("by_id", ["", 123, None])
def test_yc_get_sql_query_rejects_invalid_ids_before_service_dispatch(
    by_id: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_get(*args: object, **kwargs: object) -> SqlQuery:
        raise AssertionError("Invalid query ID reached the service")

    monkeypatch.setattr(SqlQueryService, "get_sql_query", unexpected_get)
    recorder = RecordedTransport({})
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    with client, pytest.raises(DataLensValidationError):
        client.get.sql_query(by_id=cast(str, by_id))
    assert recorder.requests == []


def test_create_and_get_sql_query_preserve_parameters_metadata_and_matching_navigation_name() -> None:
    entry = _sql_query_entry()
    recorder = RecordedTransport(
        {
            "/rpc/createSqlQuery": httpx.Response(200, json={"entry": entry}),
            "/rpc/getSqlQuery": httpx.Response(
                200,
                json={
                    "entry": entry,
                    "isFavorite": False,
                    "permissions": {"execute": True, "read": True, "edit": False, "admin": False},
                },
            ),
            "/rpc/getEntries": httpx.Response(
                200,
                json={
                    "entries": [
                        _navigation_entry("other-query", "Unrelated query"),
                        _navigation_entry("query-1", "Saved revenue"),
                    ]
                },
            ),
        }
    )
    parameters = (
        SqlQueryParameter.string("text", "Revenue"),
        SqlQueryParameter.number("amount", 1.5),
        SqlQueryParameter.boolean("active", False),
        SqlQueryParameter.date("day", "2026-09-29"),
        SqlQueryParameter.datetime("time", "2026-09-29T10:00:00"),
        SqlQueryParameter.date_interval("days", SqlQueryInterval("2026-09-01", "2026-09-30")),
        SqlQueryParameter.datetime_interval("times", SqlQueryInterval("2026-09-29T00:00:00", "2026-09-30T00:00:00")),
        SqlQueryParameter.string("optional"),
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        service = _sql_query_service(http_client)
        created = (
            _builder(service)
            .connection("connection-1")
            .query("select :day")
            .description("Revenue query")
            .parameters(parameters)
            .build()
        )
        loaded = service.get_sql_query("query-1", rev_id="rev-2", include_favorite=False, include_permissions=True)

    assert created.name == "Revenue"
    assert created.location == EntryLocation.workbook("workbook-1")
    assert created._operations is service
    assert created.parameters == parameters
    assert created.is_favorite is None
    assert created.permissions is None
    assert loaded.id == "query-1"
    assert loaded.name == "Saved revenue"
    assert loaded.installation == "yacloud"
    assert loaded.location == EntryLocation.workbook("workbook-1")
    assert loaded.collection_id == "collection-1"
    assert loaded.scope == "sql_query"
    assert loaded.type == "sql_query"
    assert loaded.key == ""
    assert loaded.rev_id == "rev-2"
    assert loaded.saved_id == "saved-1"
    assert loaded.published_id == "published-1"
    assert loaded.version == 1.5
    assert loaded.rev_updated_by == "revision-user"
    assert loaded.rev_updated_at == "2026-09-30T12:00:00Z"
    assert loaded.connection_id == "connection-1"
    assert loaded.query == "select :day"
    assert loaded.parameters == parameters
    assert loaded.statement_positions == ((0, 1.5), (2.5, 11))
    assert loaded.description == "Revenue query"
    assert loaded.created_by == "creator-user"
    assert loaded.created_at == "2026-09-29T00:00:00Z"
    assert loaded.updated_by == "editor-user"
    assert loaded.updated_at == "2026-09-30T00:00:00Z"
    assert loaded.tenant_id == "tenant-1"
    assert loaded.hidden is True
    assert loaded.links == {"connection": "connection-1"}
    assert loaded.is_favorite is False
    assert loaded.permissions == SqlQueryPermissions(execute=True, read=True, edit=False, admin=False)
    assert loaded.raw == entry
    assert loaded._operations is service
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createSqlQuery",
        "/rpc/getSqlQuery",
        "/rpc/getEntries",
    ]
    assert all(request.method == "POST" for request in recorder.requests)
    assert recorder.bodies("/rpc/createSqlQuery") == [
        {
            "workbookId": "workbook-1",
            "name": "Revenue",
            "connectionId": "connection-1",
            "query": "select :day",
            "description": "Revenue query",
            "params": [
                {"name": "text", "type": "string", "defaultValue": "Revenue"},
                {"name": "amount", "type": "number", "defaultValue": 1.5},
                {"name": "active", "type": "boolean", "defaultValue": False},
                {"name": "day", "type": "date", "defaultValue": "2026-09-29"},
                {"name": "time", "type": "datetime", "defaultValue": "2026-09-29T10:00:00"},
                {
                    "name": "days",
                    "type": "date-interval",
                    "defaultValue": {"from": "2026-09-01", "to": "2026-09-30"},
                },
                {
                    "name": "times",
                    "type": "datetime-interval",
                    "defaultValue": {"from": "2026-09-29T00:00:00", "to": "2026-09-30T00:00:00"},
                },
                {"name": "optional", "type": "string"},
            ],
        }
    ]
    assert recorder.bodies("/rpc/getSqlQuery") == [
        {"sqlQueryId": "query-1", "revId": "rev-2", "includeFavorite": False, "includePermissions": True}
    ]
    assert recorder.bodies("/rpc/getEntries") == [{"ids": ["query-1"], "ignoreWorkbookEntries": False, "pageSize": 1}]


def test_get_sql_query_uses_matching_navigation_name_over_out_of_schema_response_name() -> None:
    entry = {**_sql_query_entry(), "name": "Stale response name"}
    recorder = RecordedTransport(
        {
            "/rpc/getSqlQuery": httpx.Response(200, json={"entry": entry}),
            "/rpc/getEntries": httpx.Response(
                200, json={"entries": [_navigation_entry("query-1", "Current navigation name")]}
            ),
        }
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        loaded = _sql_query_service(http_client).get_sql_query("query-1")

    assert loaded.name == "Current navigation name"
    assert [request.url.path for request in recorder.requests] == ["/rpc/getSqlQuery", "/rpc/getEntries"]
    assert recorder.bodies("/rpc/getEntries") == [{"ids": ["query-1"], "ignoreWorkbookEntries": False, "pageSize": 1}]


def test_create_and_get_sql_query_omit_none_options_preserve_nulls_and_ignore_unrelated_name() -> None:
    entry = _sql_query_entry(nullable_metadata=True)
    entry["data"] = {"connectionId": "connection-1", "query": "select 1", "statementPositions": [[0, 8]]}
    recorder = RecordedTransport(
        {
            "/rpc/createSqlQuery": httpx.Response(200, json={"entry": entry}),
            "/rpc/getSqlQuery": httpx.Response(200, json={"entry": entry}),
            "/rpc/getEntries": httpx.Response(
                200, json={"entries": [_navigation_entry("other-query", "Unrelated query")]}
            ),
        }
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        service = _sql_query_service(http_client)
        created = _builder(service).connection("connection-1").query("select 1").build()
        loaded = service.get_sql_query("query-1", rev_id=None, include_favorite=None, include_permissions=None)

    assert created.name == "Revenue"
    assert loaded.id == "query-1"
    assert loaded.name is None
    assert loaded.location == EntryLocation.workbook("workbook-1")
    assert loaded.collection_id is None
    assert loaded.published_id is None
    assert loaded.version is None
    assert loaded.description is None
    assert loaded.links is None
    assert loaded.rev_updated_by is None
    assert loaded.rev_updated_at is None
    assert loaded.parameters == ()
    assert loaded.statement_positions == ((0, 8),)
    assert loaded.is_favorite is None
    assert loaded.permissions is None
    assert loaded.raw == entry
    assert loaded.update.to_spec().parameters is None
    assert recorder.bodies("/rpc/createSqlQuery") == [
        {"workbookId": "workbook-1", "name": "Revenue", "connectionId": "connection-1", "query": "select 1"}
    ]
    assert recorder.bodies("/rpc/getSqlQuery") == [{"sqlQueryId": "query-1"}]
    assert recorder.bodies("/rpc/getEntries") == [{"ids": ["query-1"], "ignoreWorkbookEntries": False, "pageSize": 1}]


def _query(*, operations: SqlQueryOperations | None = None) -> SqlQuery:
    return SqlQuery(
        id="query-1",
        name="Revenue",
        installation="yacloud",
        location=EntryLocation.workbook("workbook-1"),
        collection_id="collection-1",
        scope="sql_query",
        type="sql_query",
        key="",
        rev_id="rev-1",
        saved_id="rev-1",
        published_id=None,
        version=1.5,
        rev_updated_by=None,
        rev_updated_at=None,
        connection_id="connection-1",
        query="select :day",
        parameters=(SqlQueryParameter.date("day", "2026-09-29"),),
        statement_positions=((0, 1.5),),
        description="Revenue query",
        created_by="user-1",
        created_at="2026-09-29T00:00:00Z",
        updated_by="user-1",
        updated_at="2026-09-29T00:00:00Z",
        tenant_id="tenant-1",
        hidden=False,
        links=None,
        is_favorite=None,
        permissions=None,
        raw={"data": {"params": [{"name": "day", "type": "date", "defaultValue": "2026-09-29"}]}},
        _operations=operations,
    )


@pytest.mark.parametrize("parameters_present", [False, True])
def test_sql_query_update_preserves_absent_or_empty_parameters(parameters_present: bool) -> None:
    entry = _sql_query_entry(nullable_metadata=True)
    data: dict[str, object] = {"connectionId": "connection-1", "query": "select 1", "statementPositions": [[0, 8]]}
    if parameters_present:
        data["params"] = []
    entry["data"] = data
    recorder = RecordedTransport({"/rpc/updateSqlQuery": httpx.Response(200, json={"entry": entry})})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        source = SqlQueryConverter.to_query(
            {"entry": entry},
            installation="yacloud",
            operations=_sql_query_service(http_client),
            operation="getSqlQuery",
            name="Revenue",
        )
        updated = source.update.execute()

    expected: dict[str, object] = {"sqlQueryId": "query-1", "connectionId": "connection-1", "query": "select 1"}
    if parameters_present:
        expected["params"] = []
    assert recorder.bodies("/rpc/updateSqlQuery") == [expected]
    assert updated.name == source.name
    assert updated.location is source.location
    assert updated.update.to_spec().parameters == (() if parameters_present else None)


@pytest.mark.parametrize("replacement", ["connection", "query", "parameters", "clear"])
def test_sql_query_update_replaces_selected_fields_and_preserves_current_values(replacement: str) -> None:
    entry = _sql_query_entry()
    expected: dict[str, object] = {
        "sqlQueryId": "query-1",
        "connectionId": "connection-1",
        "query": "select :day",
        "description": "Revenue query",
        "params": [{"name": "day", "type": "date", "defaultValue": "2026-09-29"}],
    }
    if replacement == "connection":
        expected["connectionId"] = "connection-2"
    elif replacement == "query":
        expected["query"] = ""
    elif replacement == "parameters":
        expected["params"] = [
            {"name": "period", "type": "date-interval", "defaultValue": {"from": "start", "to": "end"}},
            {"name": "active", "type": "boolean", "defaultValue": False},
            {"name": "optional", "type": "string"},
        ]
    else:
        expected.update(params=[], description="")
    entry["data"] = {
        "connectionId": expected["connectionId"],
        "query": expected["query"],
        "params": expected["params"],
        "statementPositions": [],
    }
    entry["annotation"] = {"description": expected["description"]}
    recorder = RecordedTransport({"/rpc/updateSqlQuery": httpx.Response(200, json={"entry": entry})})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        source = _query(operations=_sql_query_service(http_client))
        builder = source.update
        if replacement == "connection":
            builder.connection(Connection(id="connection-2", type="postgres", installation="yacloud"))
        elif replacement == "query":
            builder.query("")
        elif replacement == "parameters":
            builder.parameters(
                [
                    SqlQueryParameter.date_interval("period", SqlQueryInterval("start", "end")),
                    SqlQueryParameter.boolean("active", False),
                    SqlQueryParameter.string("optional"),
                ]
            )
        else:
            builder.clear_parameters().description("")
        updated = builder.execute()

    assert recorder.bodies("/rpc/updateSqlQuery") == [expected]
    assert [request.url.path for request in recorder.requests] == ["/rpc/updateSqlQuery"]
    assert updated.name == "Revenue"
    assert updated.location is source.location
    assert updated.connection_id == expected["connectionId"]
    assert updated.query == expected["query"]
    assert updated.description == expected["description"]
    assert updated.parameters == builder.to_spec().parameters
    assert updated.raw == entry
    assert updated._operations is source._operations


def test_sql_query_delete_sends_only_id_and_returns_none_for_empty_result() -> None:
    recorder = RecordedTransport({"/rpc/deleteSqlQuery": httpx.Response(200, json={})})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        delete: Callable[[], object] = _query(operations=_sql_query_service(http_client)).delete
        result = delete()

    assert result is None
    assert recorder.bodies("/rpc/deleteSqlQuery") == [{"sqlQueryId": "query-1"}]


def _sql_query_run_result(status: SqlQueryRunStatus = "partial_success") -> dict[str, object]:
    return {
        "id": "run-1",
        "connectionId": "connection-1",
        "tenantId": "tenant-1",
        "status": status,
        "query": "select :day; invalid sql",
        "statementPositions": [[0, 10.5], [11.5, 24]],
        "results": [
            {
                "status": "success",
                "columns": [{"name": "value"}, {"name": "missing"}],
                "rows": [["text", None], [1.5, True], [0, False]],
            },
            {"status": "error", "code": "INVALID_SQL", "message": "Invalid SQL", "databaseMessage": "syntax error"},
        ],
        "createdBy": "user-1",
        "createdAt": "2026-09-29T00:00:00Z",
        "updatedAt": "2026-09-29T01:00:00Z",
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (None, {"sqlQueryId": "query-1"}),
        ({}, {"sqlQueryId": "query-1", "params": {}}),
        (
            {
                "text": "abc",
                "number": 1.5,
                "boolean": False,
                "values": ("abc", 1, True),
                "interval": SqlQueryInterval("start", "end"),
            },
            {
                "sqlQueryId": "query-1",
                "params": {
                    "text": "abc",
                    "number": 1.5,
                    "boolean": False,
                    "values": ["abc", 1, True],
                    "interval": {"from": "start", "to": "end"},
                },
            },
        ),
    ],
)
def test_sql_query_run_serializes_overrides_without_splitting_scalar_strings(
    params: Mapping[str, SqlQueryRunValue] | None,
    expected: dict[str, object],
) -> None:
    recorder = RecordedTransport({"/rpc/runSqlQuery": httpx.Response(200, json=_sql_query_run_result())})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        _query(operations=_sql_query_service(http_client)).run(params=params)

    assert recorder.bodies("/rpc/runSqlQuery") == [expected]


@pytest.mark.parametrize("params", [[], "invalid", 1])
def test_sql_query_run_rejects_non_mapping_params_before_http(params: object) -> None:
    recorder = RecordedTransport({})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        query = _query(operations=_sql_query_service(http_client))
        with pytest.raises(DataLensValidationError):
            query.run(params=cast(Mapping[str, SqlQueryRunValue], params))

    assert recorder.requests == []


@pytest.mark.parametrize(
    ("wire_name", "python_name"),
    [
        ("connectionId", "connection_id"),
        ("tenantId", "tenant_id"),
        ("statementPositions", "statement_positions"),
        ("createdBy", "created_by"),
        ("createdAt", "created_at"),
        ("updatedAt", "updated_at"),
    ],
)
def test_sql_query_run_rejects_python_names_in_place_of_required_wire_fields(
    wire_name: str,
    python_name: str,
) -> None:
    raw = _sql_query_run_result()
    raw[python_name] = raw.pop(wire_name)
    recorder = RecordedTransport({"/rpc/runSqlQuery": httpx.Response(200, json=raw)})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(InvalidResponseError, match="runSqlQuery") as exc_info,
    ):
        _query(operations=_sql_query_service(http_client)).run()

    assert wire_name in str(exc_info.value)
    assert [request.url.path for request in recorder.requests] == ["/rpc/runSqlQuery"]


@pytest.mark.parametrize("positions", [[[0]], [[0, 1, 2]]])
def test_sql_query_run_rejects_statement_positions_without_two_offsets(positions: list[list[int]]) -> None:
    raw = _sql_query_run_result()
    raw["statementPositions"] = positions
    recorder = RecordedTransport({"/rpc/runSqlQuery": httpx.Response(200, json=raw)})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(InvalidResponseError, match=r"runSqlQuery.*statementPositions\[0\]"),
    ):
        _query(operations=_sql_query_service(http_client)).run()

    assert [request.url.path for request in recorder.requests] == ["/rpc/runSqlQuery"]


@pytest.mark.parametrize("positions", [[[0]], [[0, 1, 2]]])
def test_sql_query_get_rejects_statement_positions_without_two_offsets(positions: list[list[int]]) -> None:
    entry = _sql_query_entry()
    cast(dict[str, object], entry["data"])["statementPositions"] = positions
    recorder = RecordedTransport({"/rpc/getSqlQuery": httpx.Response(200, json={"entry": entry})})
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    with (
        client,
        pytest.raises(InvalidResponseError, match=r"getSqlQuery.*statementPositions\[0\]"),
    ):
        client.get.sql_query(by_id="query-1")

    assert [request.url.path for request in recorder.requests] == ["/rpc/getSqlQuery"]


@pytest.mark.parametrize("status", ["success", "error", "pending", "partial_success"])
def test_sql_query_run_preserves_status_and_ordered_statement_results_without_polling(
    status: SqlQueryRunStatus,
) -> None:
    raw = _sql_query_run_result(status)
    recorder = RecordedTransport({"/rpc/runSqlQuery": httpx.Response(200, json=raw)})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        result = _query(operations=_sql_query_service(http_client)).run()

    assert result == SqlQueryRun(
        id="run-1",
        connection_id="connection-1",
        tenant_id="tenant-1",
        status=status,
        query="select :day; invalid sql",
        statement_positions=((0, 10.5), (11.5, 24)),
        results=(
            SqlQueryStatementSuccess(
                status="success",
                columns=(SqlQueryRunColumn("value"), SqlQueryRunColumn("missing")),
                rows=(("text", None), (1.5, True), (0, False)),
            ),
            SqlQueryStatementError(
                status="error", code="INVALID_SQL", message="Invalid SQL", database_message="syntax error"
            ),
        ),
        created_by="user-1",
        created_at="2026-09-29T00:00:00Z",
        updated_at="2026-09-29T01:00:00Z",
        raw=raw,
    )
    assert [request.url.path for request in recorder.requests] == ["/rpc/runSqlQuery"]


def test_sql_query_run_preserves_affected_rows_and_absent_database_message() -> None:
    raw = _sql_query_run_result()
    raw["results"] = [
        {"status": "success", "columns": [], "rows": [], "affectedRows": 2.5},
        {"status": "error", "code": "FAILED", "message": "Failed"},
    ]
    recorder = RecordedTransport({"/rpc/runSqlQuery": httpx.Response(200, json=raw)})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        result = _query(operations=_sql_query_service(http_client)).run()

    assert result.results == (
        SqlQueryStatementSuccess(status="success", columns=(), rows=(), affected_rows=2.5),
        SqlQueryStatementError(status="error", code="FAILED", message="Failed"),
    )


@pytest.mark.parametrize("extras", [{"permissions": {}}, {"isFavorite": "unexpected"}])
def test_sql_query_create_ignores_get_only_response_enrichments(extras: dict[str, object]) -> None:
    recorder = RecordedTransport(
        {"/rpc/createSqlQuery": httpx.Response(200, json={"entry": _sql_query_entry(), **extras})}
    )
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        service = _sql_query_service(http_client)
        created = _builder(service).connection("connection-1").query("select 1").build()

    assert created.id == "query-1"
    assert created.name == "Revenue"
    assert created.is_favorite is None
    assert created.permissions is None


@pytest.mark.parametrize("extras", [{"permissions": {}}, {"isFavorite": "unexpected"}])
def test_sql_query_update_response_ignores_get_only_response_enrichments(extras: dict[str, object]) -> None:
    updated = SqlQueryConverter.to_query(
        {"entry": _sql_query_entry(), **extras},
        installation="yacloud",
        operations=None,
        operation="updateSqlQuery",
        name="Revenue",
    )

    assert updated.id == "query-1"
    assert updated.name == "Revenue"
    assert updated.is_favorite is None
    assert updated.permissions is None


def _invoke_sql_query_operation(operation: str, service: SqlQueryOperations) -> object:
    if operation == "createSqlQuery":
        return _builder(service).connection("connection-1").query("select 1").build()
    if operation == "getSqlQuery":
        return service.get_sql_query("query-1")
    query = _query(operations=service)
    if operation == "updateSqlQuery":
        return query.update.execute()
    if operation == "deleteSqlQuery":
        query.delete()
        return None
    if operation == "runSqlQuery":
        return query.run()
    raise AssertionError(f"Unexpected SQL query operation: {operation}")


def test_sql_query_get_retries_transient_failure_then_resolves_name() -> None:
    requests: list[httpx.Request] = []
    responses = iter(
        [
            httpx.Response(503, json={"code": "UNAVAILABLE", "message": "Try again"}),
            httpx.Response(200, json={"entry": _sql_query_entry()}),
            httpx.Response(200, json={"entries": [_navigation_entry("query-1", "Saved revenue")]}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return next(responses)

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handler))
    with client:
        loaded = client.get.sql_query(by_id="query-1")

    assert loaded.id == "query-1"
    assert loaded.name == "Saved revenue"
    assert [request.url.path for request in requests] == ["/rpc/getSqlQuery", "/rpc/getSqlQuery", "/rpc/getEntries"]
    assert [json.loads(request.content) for request in requests] == [
        {"sqlQueryId": "query-1"},
        {"sqlQueryId": "query-1"},
        {"ids": ["query-1"], "ignoreWorkbookEntries": False, "pageSize": 1},
    ]


@pytest.mark.parametrize("operation", ["createSqlQuery", "updateSqlQuery", "deleteSqlQuery", "runSqlQuery"])
def test_sql_query_mutations_are_not_retried(operation: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            503, headers={"x-request-id": "mutation-failure"}, json={"code": "UNAVAILABLE", "message": "Try again"}
        )

    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(handler),
        ) as http_client,
        pytest.raises(ServerError) as exc_info,
    ):
        _invoke_sql_query_operation(operation, _sql_query_service(http_client))

    assert [request.url.path for request in requests] == [f"/rpc/{operation}"]
    assert exc_info.value.context.attempts == 1
    assert exc_info.value.context.code == "UNAVAILABLE"
    assert exc_info.value.context.request_id == "mutation-failure"


def test_sql_query_read_ignores_unknown_fields() -> None:
    entry = _sql_query_entry()
    entry["futureEntryField"] = {"revision": 3}
    data = cast(dict[str, object], entry["data"])
    data["futureDataField"] = ["new"]
    parameter = cast(list[dict[str, object]], data["params"])[0]
    parameter["futureParameterField"] = True
    run = _sql_query_run_result()
    statements = cast(list[dict[str, object]], run["results"])
    statements[0]["futureStatementField"] = {"duration": 5}
    statements[1]["futureStatementField"] = "diagnostic"
    cast(list[dict[str, object]], statements[0]["columns"])[0]["futureColumnField"] = "string"
    run["futureRunField"] = True
    recorder = RecordedTransport(
        {
            "/rpc/getSqlQuery": httpx.Response(
                200,
                json={
                    "entry": entry,
                    "permissions": {"execute": True, "read": True, "edit": False, "admin": False, "share": True},
                    "futureResponseField": "new",
                },
            ),
            "/rpc/getEntries": httpx.Response(200, json={"entries": [_navigation_entry("query-1", "Revenue")]}),
            "/rpc/runSqlQuery": httpx.Response(200, json=run),
        }
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    with client:
        loaded = client.get.sql_query(by_id="query-1", include_permissions=True)
        result = loaded.run()

    assert loaded.connection_id == "connection-1"
    assert loaded.parameters[0] == SqlQueryParameter.string("text", "Revenue")
    assert loaded.permissions == SqlQueryPermissions(execute=True, read=True, edit=False, admin=False)
    assert loaded.raw == entry
    assert result.raw == run
    assert result.results == (
        SqlQueryStatementSuccess(
            status="success",
            columns=(SqlQueryRunColumn("value"), SqlQueryRunColumn("missing")),
            rows=(("text", None), (1.5, True), (0, False)),
        ),
        SqlQueryStatementError(
            status="error", code="INVALID_SQL", message="Invalid SQL", database_message="syntax error"
        ),
    )


@pytest.mark.parametrize("operation", ["createSqlQuery", "getSqlQuery", "updateSqlQuery", "runSqlQuery"])
@pytest.mark.parametrize("defect", ["missing", "wrong_type"])
def test_sql_query_required_field_failures_identify_operation(operation: str, defect: str) -> None:
    if operation == "runSqlQuery":
        response = _sql_query_run_result()
        container = response
    else:
        entry = _sql_query_entry()
        response = {"entry": entry}
        container = cast(dict[str, object], entry["data"])
    if defect == "missing":
        del container["query"]
    else:
        container["query"] = 123
    recorder = RecordedTransport({f"/rpc/{operation}": httpx.Response(200, json=response)})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(DTOValidationError, match=operation) as exc_info,
    ):
        _invoke_sql_query_operation(operation, _sql_query_service(http_client))

    assert "query" in exc_info.value.context.message
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert [request.url.path for request in recorder.requests] == [f"/rpc/{operation}"]


@pytest.mark.parametrize(
    "statement",
    [
        {"status": "pending", "columns": [], "rows": []},
        {"status": "success", "columns": []},
        {"status": "error", "code": "FAILED"},
        {"status": "success", "columns": [], "rows": [[{"invalid": "cell"}]]},
    ],
)
def test_sql_query_invalid_statement_union_identifies_run_operation(statement: dict[str, object]) -> None:
    response = _sql_query_run_result()
    response["results"] = [statement]
    recorder = RecordedTransport({"/rpc/runSqlQuery": httpx.Response(200, json=response)})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(DTOValidationError, match="runSqlQuery") as exc_info,
    ):
        _query(operations=_sql_query_service(http_client)).run()

    assert "results" in exc_info.value.context.message
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert [request.url.path for request in recorder.requests] == ["/rpc/runSqlQuery"]


@pytest.mark.parametrize("operation", ["createSqlQuery", "getSqlQuery", "updateSqlQuery"])
def test_sql_query_empty_entry_id_identifies_operation(operation: str) -> None:
    entry = _sql_query_entry()
    entry["entryId"] = ""
    recorder = RecordedTransport({f"/rpc/{operation}": httpx.Response(200, json={"entry": entry})})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(InvalidResponseError, match=operation),
    ):
        _invoke_sql_query_operation(operation, _sql_query_service(http_client))

    assert [request.url.path for request in recorder.requests] == [f"/rpc/{operation}"]


def test_get_sql_query_rejects_another_entry_before_navigation() -> None:
    entry = _sql_query_entry()
    entry["entryId"] = "query-2"
    recorder = RecordedTransport({"/rpc/getSqlQuery": httpx.Response(200, json={"entry": entry})})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(InvalidResponseError, match="getSqlQuery") as exc_info,
    ):
        _sql_query_service(http_client).get_sql_query("query-1")

    assert "query-1" in exc_info.value.context.message
    assert "query-2" in exc_info.value.context.message
    assert recorder.bodies("/rpc/getSqlQuery") == [{"sqlQueryId": "query-1"}]
    assert [request.url.path for request in recorder.requests] == ["/rpc/getSqlQuery"]


def test_update_sql_query_rejects_another_entry_without_changing_source() -> None:
    entry = _sql_query_entry()
    entry["entryId"] = "query-2"
    recorder = RecordedTransport({"/rpc/updateSqlQuery": httpx.Response(200, json={"entry": entry})})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        source = _query(operations=_sql_query_service(http_client))
        with pytest.raises(InvalidResponseError, match="updateSqlQuery") as exc_info:
            source.update.query("select 2").execute()

    assert "query-1" in exc_info.value.context.message
    assert "query-2" in exc_info.value.context.message
    assert source.id == "query-1"
    assert source.query == "select :day"
    assert recorder.bodies("/rpc/updateSqlQuery") == [
        {
            "sqlQueryId": "query-1",
            "connectionId": "connection-1",
            "query": "select 2",
            "description": "Revenue query",
            "params": [{"name": "day", "type": "date", "defaultValue": "2026-09-29"}],
        }
    ]
    assert [request.url.path for request in recorder.requests] == ["/rpc/updateSqlQuery"]


@pytest.mark.parametrize(
    "operation", ["createSqlQuery", "getSqlQuery", "updateSqlQuery", "deleteSqlQuery", "runSqlQuery"]
)
def test_sql_query_malformed_request_dto_is_translated_before_http(operation: str) -> None:
    class MalformedRequestDTO(BaseModel):
        missing_field: str

    class DtoStub(ModuleType):
        def __getattr__(self, name: str) -> object:
            return getattr(import_module("datalens_sdk._generated.dto"), name)

    dto_stub = DtoStub("malformed_request_dto")
    setattr(dto_stub, f"{operation[0].upper()}{operation[1:]}ArgsDTO", MalformedRequestDTO)
    recorder = RecordedTransport({})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(DTOValidationError, match=operation) as exc_info,
    ):
        _invoke_sql_query_operation(
            operation, _sql_query_service(http_client, dto_module=cast(SqlQueryDtoModule, dto_stub))
        )

    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert "missing_field" in exc_info.value.context.message
    assert recorder.requests == []


def test_sql_query_navigation_failure_is_not_swallowed() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getSqlQuery": httpx.Response(200, json={"entry": _sql_query_entry()}),
            "/rpc/getEntries": httpx.Response(
                403,
                headers={"x-request-id": "navigation-failure"},
                json={"code": "ACCESS_DENIED", "message": "Cannot read entries"},
            ),
        }
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    with client, pytest.raises(ForbiddenError) as exc_info:
        client.get.sql_query(by_id="query-1")

    assert exc_info.value.context.code == "ACCESS_DENIED"
    assert exc_info.value.context.request_id == "navigation-failure"
    assert exc_info.value.context.request_url == "https://api.datalens.tech/rpc/getEntries"
    assert [request.url.path for request in recorder.requests] == ["/rpc/getSqlQuery", "/rpc/getEntries"]


@pytest.mark.parametrize("operation", ["createSqlQuery", "getSqlQuery", "updateSqlQuery"])
@pytest.mark.parametrize("container_name", ["entry", "data", "interval"])
def test_sql_query_required_field_wire_spelling_does_not_leak_key_error(operation: str, container_name: str) -> None:
    entry = _sql_query_entry()
    if container_name == "entry":
        container = entry
        wire_name, python_name = "entryId", "entry_id"
    else:
        data = cast(dict[str, object], entry["data"])
        if container_name == "data":
            container = data
            wire_name, python_name = "connectionId", "connection_id"
        else:
            parameters = cast(list[dict[str, object]], data["params"])
            container = cast(dict[str, object], parameters[5]["defaultValue"])
            wire_name, python_name = "from", "from_"
    container[python_name] = container.pop(wire_name)
    recorder = RecordedTransport({f"/rpc/{operation}": httpx.Response(200, json={"entry": entry})})
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="test",
            base_url="https://datalens.test",
            transport=httpx.MockTransport(recorder.handler),
        ) as http_client,
        pytest.raises(InvalidResponseError, match=operation) as exc_info,
    ):
        _invoke_sql_query_operation(operation, _sql_query_service(http_client))

    assert wire_name in exc_info.value.context.message
    assert [request.url.path for request in recorder.requests] == [f"/rpc/{operation}"]


class _SqlQueryOperations:
    def __init__(self) -> None:
        self.creates: list[SqlQueryCreateSpec] = []
        self.updates: list[SqlQueryUpdateSpec] = []
        self.deletes: list[str] = []
        self.runs: list[tuple[str, Mapping[str, SqlQueryRunValue] | None]] = []

    def create_sql_query(self, builder: SqlQueryCreate) -> SqlQuery:
        self.creates.append(builder.to_spec())
        return _query(operations=self)

    def get_sql_query(
        self,
        sql_query_id: str,
        *,
        rev_id: str | None = None,
        include_favorite: bool | None = None,
        include_permissions: bool | None = None,
    ) -> SqlQuery:
        raise AssertionError("Domain builders must not fetch queries")

    def update_sql_query(self, builder: SqlQueryUpdate) -> SqlQuery:
        self.updates.append(builder.to_spec())
        return _query(operations=self)

    def delete_sql_query(self, sql_query_id: str) -> None:
        self.deletes.append(sql_query_id)

    def run_sql_query(
        self,
        sql_query_id: str,
        *,
        params: Mapping[str, SqlQueryRunValue] | None = None,
    ) -> SqlQueryRun:
        self.runs.append((sql_query_id, params))
        return SqlQueryRun(
            id="run-1",
            connection_id="connection-1",
            tenant_id="tenant-1",
            status="partial_success",
            query="select :day",
            statement_positions=((0, 1.5),),
            results=(
                SqlQueryStatementSuccess(status="success", columns=(), rows=((None, True, 1.5),)),
                SqlQueryStatementError(status="error", code="INVALID_SQL", message="Invalid SQL"),
            ),
            created_by="user-1",
            created_at="2026-09-29T00:00:00Z",
            updated_at="2026-09-29T00:00:00Z",
            raw={},
        )


def _builder(operations: SqlQueryOperations | None = None) -> SqlQueryCreate:
    return SqlQueryCreate(
        installation="yacloud",
        name="Revenue",
        location=EntryLocation.workbook("workbook-1"),
        operations=operations,
    )


@pytest.mark.parametrize(
    ("parameter", "expected_type", "expected_default"),
    [
        (SqlQueryParameter.string("p", "text"), "string", "text"),
        (SqlQueryParameter.number("p", 1.5), "number", 1.5),
        (SqlQueryParameter.boolean("p", False), "boolean", False),
        (SqlQueryParameter.date("p", "2026-09-29"), "date", "2026-09-29"),
        (SqlQueryParameter.datetime("p", "2026-09-29T10:00:00"), "datetime", "2026-09-29T10:00:00"),
        (
            SqlQueryParameter.date_interval("p", SqlQueryInterval("start", "end")),
            "date-interval",
            SqlQueryInterval("start", "end"),
        ),
        (
            SqlQueryParameter.datetime_interval("p", SqlQueryInterval("start", "end")),
            "datetime-interval",
            SqlQueryInterval("start", "end"),
        ),
    ],
)
def test_parameter_factories_preserve_discriminator_and_default(
    parameter: SqlQueryParameter, expected_type: str, expected_default: object
) -> None:
    assert parameter.name == "p"
    assert parameter.type == expected_type
    assert parameter.default_value == expected_default


def test_parameter_factories_omit_unspecified_defaults() -> None:
    parameters = (
        SqlQueryParameter.string("p"),
        SqlQueryParameter.number("p"),
        SqlQueryParameter.boolean("p"),
        SqlQueryParameter.date("p"),
        SqlQueryParameter.datetime("p"),
        SqlQueryParameter.date_interval("p"),
        SqlQueryParameter.datetime_interval("p"),
    )
    assert all(parameter.default_value is None for parameter in parameters)


@pytest.mark.parametrize(
    ("parameter_type", "default"),
    [
        ("date", SqlQueryInterval("start", "end")),
        ("datetime", 1),
        ("date-interval", "start"),
        ("datetime-interval", False),
        ("unsupported", None),
    ],
)
def test_parameter_direct_construction_rejects_defaults_outside_the_schema(
    parameter_type: str, default: object
) -> None:
    with pytest.raises(DataLensValidationError):
        SqlQueryParameter(
            name="p",
            type=cast(SqlQueryParameterType, parameter_type),
            default_value=cast(SqlQueryScalar | SqlQueryInterval | None, default),
        )


@pytest.mark.parametrize("name", ["", None, 1])
def test_parameter_direct_construction_rejects_invalid_names(name: object) -> None:
    with pytest.raises(DataLensValidationError):
        SqlQueryParameter(name=cast(str, name), type="string")


@pytest.mark.parametrize("default", [0, 1, -1, 1.5])
def test_parameter_number_accepts_integer_and_float_defaults(default: int | float) -> None:
    assert SqlQueryParameter.number("p", default).default_value == default


def test_parameter_number_factory_accepts_boolean_default_allowed_by_the_api_schema() -> None:
    assert SqlQueryParameter.number("p", True) == SqlQueryParameter(name="p", type="number", default_value=True)


@pytest.mark.parametrize(
    ("parameter_type", "default"),
    [("number", "1"), ("boolean", 1), ("string", 1)],
)
@pytest.mark.parametrize("operation", ["createSqlQuery", "getSqlQuery", "updateSqlQuery"])
def test_sql_query_responses_preserve_schema_valid_scalar_defaults(
    parameter_type: SqlQueryParameterType,
    default: SqlQueryScalar,
    operation: str,
) -> None:
    entry = _sql_query_entry()
    data = cast(dict[str, object], entry["data"])
    data["params"] = [{"name": "p", "type": parameter_type, "defaultValue": default}]
    routes = {f"/rpc/{operation}": httpx.Response(200, json={"entry": entry})}
    if operation == "getSqlQuery":
        routes["/rpc/getEntries"] = httpx.Response(200, json={"entries": [_navigation_entry("query-1", "Revenue")]})
    recorder = RecordedTransport(routes)

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    ) as http_client:
        query = _invoke_sql_query_operation(operation, _sql_query_service(http_client))

    assert isinstance(query, SqlQuery)
    assert query.parameters == (SqlQueryParameter(name="p", type=parameter_type, default_value=default),)


def test_parameter_interval_accepts_arbitrary_strings_without_date_syntax() -> None:
    assert SqlQueryParameter.date_interval("p", SqlQueryInterval("start", "end")).default_value == SqlQueryInterval(
        "start", "end"
    )


@pytest.mark.parametrize("location", [EntryLocation.path("/Queries"), EntryLocation.collection("collection-1")])
def test_builder_create_requires_workbook_location(location: EntryLocation) -> None:
    with pytest.raises(DataLensValidationError):
        SqlQueryCreate(installation="yacloud", name="Revenue", location=location)


@pytest.mark.parametrize("missing", ["connection", "query", "both"])
def test_builder_create_requires_connection_and_query_before_operations(missing: str) -> None:
    operations = _SqlQueryOperations()
    builder = _builder(operations)
    if missing != "connection" and missing != "both":
        builder.connection("connection-1")
    if missing != "query" and missing != "both":
        builder.query("select 1")
    with pytest.raises(DataLensValidationError):
        builder.build()
    assert operations.creates == []


@pytest.mark.parametrize(
    "connection", ["connection-1", Connection(id="connection-1", type="postgres", installation="yacloud")]
)
def test_builder_create_accepts_connection_or_id_and_preserves_empty_strings(connection: Connection | str) -> None:
    operations = _SqlQueryOperations()
    result = _builder(operations).connection(connection).query("").description("").build()
    assert result.id == "query-1"
    assert operations.creates == [
        SqlQueryCreateSpec("Revenue", EntryLocation.workbook("workbook-1"), "connection-1", "", "", None)
    ]


@pytest.mark.parametrize(
    "connection", ["", None, 1, Connection(id=None, type="postgres"), Connection(id="", type="postgres")]
)
def test_builder_connection_rejects_empty_and_non_string_ids_before_operations(connection: object) -> None:
    operations = _SqlQueryOperations()
    with pytest.raises(DataLensValidationError):
        _builder(operations).connection(cast(Connection | str, connection))
    with pytest.raises(DataLensValidationError):
        _query(operations=operations).update.connection(cast(Connection | str, connection))
    assert operations.creates == []
    assert operations.updates == []


def test_installation_foreign_connection_is_rejected_by_create_and_update_before_operations() -> None:
    operations = _SqlQueryOperations()
    connection = Connection(id="connection-1", type="postgres", installation="enterprise")
    with pytest.raises(DataLensValidationError):
        _builder(operations).connection(connection)
    with pytest.raises(DataLensValidationError):
        _query(operations=operations).update.connection(connection)
    assert operations.creates == []
    assert operations.updates == []


def test_installation_empty_connection_installation_remains_accepted() -> None:
    operations = _SqlQueryOperations()
    connection = Connection(id="connection-2", type="postgres", installation="")
    _builder(operations).connection(connection).query("select 1").build()
    _query(operations=operations).update.connection(connection).execute()
    assert operations.creates[0].connection_id == "connection-2"
    assert operations.updates[0].connection_id == "connection-2"


def test_builder_create_preserves_omitted_and_explicit_empty_parameters() -> None:
    builder = _builder().connection("connection-1").query("select 1")
    assert builder.to_spec().parameters is None
    assert builder.parameters([]).to_spec().parameters == ()


def test_builder_create_snapshots_parameter_sequence() -> None:
    parameters = [SqlQueryParameter.number("p", 1)]
    builder = _builder().connection("connection-1").query("select :p").parameters(parameters)
    parameters.clear()
    assert builder.to_spec().parameters == (SqlQueryParameter.number("p", 1),)


def test_builder_update_preloads_current_state_and_preserves_parameter_presence() -> None:
    query = _query()
    spec = query.update.to_spec()
    assert spec == SqlQueryUpdateSpec(
        "query-1",
        "Revenue",
        EntryLocation.workbook("workbook-1"),
        "connection-1",
        "select :day",
        "Revenue query",
        (SqlQueryParameter.date("day", "2026-09-29"),),
    )
    assert replace(query, parameters=(), raw={"data": {"params": []}}).update.to_spec().parameters == ()
    assert replace(query, parameters=(), raw={"data": {}}).update.to_spec().parameters is None
    assert replace(query, parameters=(), raw={}).update.to_spec().parameters is None


def test_builder_update_replaces_fields_and_clears_description_and_parameters() -> None:
    operations = _SqlQueryOperations()
    query = _query(operations=operations)
    builder = (
        query.update.connection("connection-2")
        .query("")
        .description("")
        .parameters([SqlQueryParameter.string("p", "v")])
    )
    assert builder.to_spec().parameters == (SqlQueryParameter.string("p", "v"),)
    result = builder.clear_parameters().execute()
    assert result.id == "query-1"
    assert operations.updates == [
        SqlQueryUpdateSpec("query-1", "Revenue", EntryLocation.workbook("workbook-1"), "connection-2", "", "", ())
    ]


def test_unbound_build_and_bound_mutations_require_operations() -> None:
    with pytest.raises(DataLensConfigurationError):
        _builder().connection("connection-1").query("select 1").build()
    query = _query()
    with pytest.raises(DataLensConfigurationError):
        query.update.execute()
    with pytest.raises(DataLensConfigurationError):
        query.run()
    with pytest.raises(DataLensConfigurationError):
        query.delete()


@pytest.mark.parametrize("query_id", [None, ""])
def test_builder_bound_mutations_without_id_fail_before_operations(query_id: str | None) -> None:
    operations = _SqlQueryOperations()
    query = replace(_query(operations=operations), id=query_id)
    with pytest.raises(DataLensValidationError):
        query.update.execute()
    with pytest.raises(DataLensValidationError):
        query.run()
    with pytest.raises(DataLensValidationError):
        query.delete()
    assert operations.updates == []
    assert operations.runs == []
    assert operations.deletes == []


def test_parameter_run_overrides_preserve_scalar_sequence_and_interval_values() -> None:
    operations = _SqlQueryOperations()
    query = _query(operations=operations)
    params: Mapping[str, SqlQueryRunValue] = {
        "text": "abc",
        "number": 1.5,
        "boolean": True,
        "values": ["abc", 1],
        "interval": SqlQueryInterval("start", "end"),
    }
    result = query.run(params=params)
    query.run()
    query.run(params={})
    query.delete()
    assert operations.runs == [("query-1", params), ("query-1", None), ("query-1", {})]
    assert operations.runs[0][1] is params
    assert operations.deletes == ["query-1"]
    assert result.status == "partial_success"
    assert result.statement_positions == ((0, 1.5),)
    assert result.results == (
        SqlQueryStatementSuccess(status="success", columns=(), rows=((None, True, 1.5),)),
        SqlQueryStatementError(status="error", code="INVALID_SQL", message="Invalid SQL"),
    )
