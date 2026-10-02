from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import ValidationError

from datalens_sdk.converter.sql_query import SqlQueryConverter, SqlQueryDtoModule
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import GetEntriesOptions
from datalens_sdk.domain.ports import NavigationOperations, SqlQueryOperations
from datalens_sdk.domain.sql_query import SqlQuery, SqlQueryCreate, SqlQueryRun, SqlQueryRunValue, SqlQueryUpdate
from datalens_sdk.errors import DataLensValidationError, translate_dto_validation_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class SqlQueryAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createSqlQuery", payload)

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getSqlQuery", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/updateSqlQuery", payload)

    def delete(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/deleteSqlQuery", payload)

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/runSqlQuery", payload)


class SqlQueryService(SqlQueryOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: SqlQueryAPI,
        navigation_operations: NavigationOperations,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    def create_sql_query(self, builder: SqlQueryCreate) -> SqlQuery:
        spec = builder.to_spec()
        try:
            dto = SqlQueryConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createSqlQuery", reason=str(exc)) from exc
        return self._to_query(
            self._api.create(dto.to_payload()),
            operation="createSqlQuery",
            name=spec.name,
            location=spec.location,
        )

    def get_sql_query(
        self,
        sql_query_id: str,
        *,
        rev_id: str | None = None,
        include_favorite: bool | None = None,
        include_permissions: bool | None = None,
    ) -> SqlQuery:
        try:
            dto = SqlQueryConverter.from_domain_get(
                sql_query_id,
                rev_id=rev_id,
                include_favorite=include_favorite,
                include_permissions=include_permissions,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getSqlQuery", reason=str(exc)) from exc
        query = self._to_query(self._api.get(dto.to_payload()), operation="getSqlQuery", expected_id=sql_query_id)
        if query.name is None:
            entries = self._navigation_operations.get_entries(
                GetEntriesOptions(ids=(sql_query_id,), ignore_workbook_entries=False, page_size=1)
            )
            entry = next((entry for entry in entries if entry.id == sql_query_id), None)
            if entry is not None:
                query.name = entry.name
        return query

    def update_sql_query(self, builder: SqlQueryUpdate) -> SqlQuery:
        spec = builder.to_spec()
        try:
            dto = SqlQueryConverter.from_domain_update(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateSqlQuery", reason=str(exc)) from exc
        return self._to_query(
            self._api.update(dto.to_payload()),
            operation="updateSqlQuery",
            expected_id=spec.sql_query_id,
            name=spec.name,
            location=spec.location,
        )

    def delete_sql_query(self, sql_query_id: str) -> None:
        try:
            dto = SqlQueryConverter.from_domain_delete(sql_query_id, dto_module=self._dto_module)
            response = self._api.delete(dto.to_payload())
            SqlQueryConverter.validate_delete(response, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="deleteSqlQuery", reason=str(exc)) from exc

    def run_sql_query(
        self,
        sql_query_id: str,
        *,
        params: Mapping[str, SqlQueryRunValue] | None = None,
    ) -> SqlQueryRun:
        try:
            dto = SqlQueryConverter.from_domain_run(sql_query_id, params=params, dto_module=self._dto_module)
            response = self._api.run(dto.to_payload())
            return SqlQueryConverter.to_run(response, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="runSqlQuery", reason=str(exc)) from exc

    def _to_query(
        self,
        response: dict[str, object],
        *,
        operation: Literal["createSqlQuery", "getSqlQuery", "updateSqlQuery"],
        expected_id: str | None = None,
        name: str | None = None,
        location: EntryLocation | None = None,
    ) -> SqlQuery:
        try:
            return SqlQueryConverter.to_query(
                response,
                installation=self._installation,
                operations=self,
                operation=operation,
                expected_id=expected_id,
                name=name,
                location=location,
                dto_module=self._dto_module,
            )
        except (ValidationError, DataLensValidationError) as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
