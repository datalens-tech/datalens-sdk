from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_location import EntryLocation, workbook_id_from_location
from datalens_sdk.domain.ports import SqlQueryOperations
from datalens_sdk.domain.specs.sql_query import SqlQueryCreateSpec, SqlQueryUpdateSpec
from datalens_sdk.domain.sql_query import (
    SqlQuery,
    SqlQueryCell,
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
    SqlQueryStatementPosition,
    SqlQueryStatementResult,
    SqlQueryStatementSuccess,
)
from datalens_sdk.errors import translate_invalid_response_error


class SqlQueryWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class SqlQueryWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> SqlQueryWriteDTOProtocol: ...


class SqlQueryReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> object: ...


class SqlQueryDtoModule(Protocol):
    CreateSqlQueryArgsDTO: SqlQueryWriteDTOClass
    GetSqlQueryArgsDTO: SqlQueryWriteDTOClass
    UpdateSqlQueryArgsDTO: SqlQueryWriteDTOClass
    DeleteSqlQueryArgsDTO: SqlQueryWriteDTOClass
    RunSqlQueryArgsDTO: SqlQueryWriteDTOClass
    CreateSqlQueryResultReadDTO: SqlQueryReadDTOClass
    GetSqlQueryResultReadDTO: SqlQueryReadDTOClass
    UpdateSqlQueryResultReadDTO: SqlQueryReadDTOClass
    DeleteSqlQueryResultReadDTO: SqlQueryReadDTOClass
    RunSqlQueryResultReadDTO: SqlQueryReadDTOClass


def _dto_module(dto_module: SqlQueryDtoModule | None) -> SqlQueryDtoModule:
    return cast(SqlQueryDtoModule, generated_dto if dto_module is None else dto_module)


def _parameter_payload(parameter: SqlQueryParameter) -> dict[str, object]:
    payload: dict[str, object] = {"name": parameter.name, "type": parameter.type}
    default = parameter.default_value
    if isinstance(default, SqlQueryInterval):
        payload["defaultValue"] = {"from": default.start, "to": default.end}
    elif default is not None:
        payload["defaultValue"] = default
    return payload


def _require_wire_fields(raw: Mapping[str, object], fields: tuple[str, ...], *, operation: str) -> None:
    for key in fields:
        if key not in raw:
            raise translate_invalid_response_error(operation=operation, reason=f"response is missing {key}")


def _statement_positions(raw: object, *, operation: str) -> tuple[SqlQueryStatementPosition, ...]:
    positions = cast(Sequence[Sequence[int | float]], raw)
    result: list[SqlQueryStatementPosition] = []
    for index, position in enumerate(positions):
        if len(position) != 2:
            raise translate_invalid_response_error(
                operation=operation,
                reason=f"statementPositions[{index}] must contain exactly two offsets",
            )
        result.append((position[0], position[1]))
    return tuple(result)


def _parameter(raw: Mapping[str, object], *, operation: str) -> SqlQueryParameter:
    default = raw.get("defaultValue")
    if isinstance(default, Mapping):
        _require_wire_fields(default, ("from", "to"), operation=operation)
        default = SqlQueryInterval(start=cast(str, default["from"]), end=cast(str, default["to"]))
    return SqlQueryParameter(
        name=cast(str, raw["name"]),
        type=cast(SqlQueryParameterType, raw["type"]),
        default_value=cast(SqlQueryScalar | SqlQueryInterval | None, default),
    )


def _run_value_payload(value: SqlQueryRunValue) -> object:
    if isinstance(value, SqlQueryInterval):
        return {"from": value.start, "to": value.end}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return value


def _statement_result(raw: Mapping[str, object]) -> SqlQueryStatementResult:
    if raw["status"] == "success":
        columns = cast(Sequence[Mapping[str, object]], raw["columns"])
        rows = cast(Sequence[Sequence[SqlQueryCell]], raw["rows"])
        return SqlQueryStatementSuccess(
            status="success",
            columns=tuple(SqlQueryRunColumn(name=cast(str, column["name"])) for column in columns),
            rows=tuple(tuple(row) for row in rows),
            affected_rows=cast(int | float | None, raw.get("affectedRows")),
        )
    return SqlQueryStatementError(
        status="error",
        code=cast(str, raw["code"]),
        message=cast(str, raw["message"]),
        database_message=cast(str | None, raw.get("databaseMessage")),
    )


class SqlQueryConverter:
    @staticmethod
    def from_domain_create(
        spec: SqlQueryCreateSpec,
        *,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQueryWriteDTOProtocol:
        payload: dict[str, object] = {
            "workbookId": workbook_id_from_location(spec.location),
            "name": spec.name,
            "connectionId": spec.connection_id,
            "query": spec.query,
        }
        if spec.description is not None:
            payload["description"] = spec.description
        if spec.parameters is not None:
            payload["params"] = [_parameter_payload(parameter) for parameter in spec.parameters]
        return _dto_module(dto_module).CreateSqlQueryArgsDTO.model_validate(payload)

    @staticmethod
    def from_domain_get(
        sql_query_id: str,
        *,
        rev_id: str | None,
        include_favorite: bool | None,
        include_permissions: bool | None,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQueryWriteDTOProtocol:
        payload: dict[str, object] = {"sqlQueryId": sql_query_id}
        if rev_id is not None:
            payload["revId"] = rev_id
        if include_favorite is not None:
            payload["includeFavorite"] = include_favorite
        if include_permissions is not None:
            payload["includePermissions"] = include_permissions
        return _dto_module(dto_module).GetSqlQueryArgsDTO.model_validate(payload)

    @staticmethod
    def from_domain_update(
        spec: SqlQueryUpdateSpec,
        *,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQueryWriteDTOProtocol:
        payload: dict[str, object] = {
            "sqlQueryId": spec.sql_query_id,
            "connectionId": spec.connection_id,
            "query": spec.query,
        }
        if spec.description is not None:
            payload["description"] = spec.description
        if spec.parameters is not None:
            payload["params"] = [_parameter_payload(parameter) for parameter in spec.parameters]
        return _dto_module(dto_module).UpdateSqlQueryArgsDTO.model_validate(payload)

    @staticmethod
    def from_domain_delete(
        sql_query_id: str,
        *,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQueryWriteDTOProtocol:
        return _dto_module(dto_module).DeleteSqlQueryArgsDTO.model_validate({"sqlQueryId": sql_query_id})

    @staticmethod
    def from_domain_run(
        sql_query_id: str,
        *,
        params: Mapping[str, SqlQueryRunValue] | None,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQueryWriteDTOProtocol:
        payload: dict[str, object] = {"sqlQueryId": sql_query_id}
        if params is not None:
            payload["params"] = {name: _run_value_payload(value) for name, value in params.items()}
        return _dto_module(dto_module).RunSqlQueryArgsDTO.model_validate(payload)

    @staticmethod
    def to_run(
        raw: Mapping[str, object],
        *,
        operation: Literal["runSqlQuery"] = "runSqlQuery",
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQueryRun:
        _dto_module(dto_module).RunSqlQueryResultReadDTO.model_validate(raw)
        # DTOs also accept Python attribute names; raw conversion requires wire keys.
        for key in ("connectionId", "tenantId", "statementPositions", "createdBy", "createdAt", "updatedAt"):
            if key not in raw:
                raise translate_invalid_response_error(operation=operation, reason=f"run is missing {key}")
        results = cast(Sequence[Mapping[str, object]], raw["results"])
        return SqlQueryRun(
            id=cast(str, raw["id"]),
            connection_id=cast(str, raw["connectionId"]),
            tenant_id=cast(str, raw["tenantId"]),
            status=cast(SqlQueryRunStatus, raw["status"]),
            query=cast(str, raw["query"]),
            statement_positions=_statement_positions(raw["statementPositions"], operation=operation),
            results=tuple(_statement_result(result) for result in results),
            created_by=cast(str, raw["createdBy"]),
            created_at=cast(str, raw["createdAt"]),
            updated_at=cast(str, raw["updatedAt"]),
            raw=dict(raw),
        )

    @staticmethod
    def validate_delete(
        raw: Mapping[str, object],
        *,
        operation: Literal["deleteSqlQuery"] = "deleteSqlQuery",
        dto_module: SqlQueryDtoModule | None = None,
    ) -> None:
        _dto_module(dto_module).DeleteSqlQueryResultReadDTO.model_validate(raw)

    @staticmethod
    def to_query(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: SqlQueryOperations | None,
        operation: Literal["createSqlQuery", "getSqlQuery", "updateSqlQuery"],
        expected_id: str | None = None,
        name: str | None = None,
        location: EntryLocation | None = None,
        dto_module: SqlQueryDtoModule | None = None,
    ) -> SqlQuery:
        generated = _dto_module(dto_module)
        if operation == "createSqlQuery":
            read_class = generated.CreateSqlQueryResultReadDTO
        elif operation == "getSqlQuery":
            read_class = generated.GetSqlQueryResultReadDTO
        else:
            read_class = generated.UpdateSqlQueryResultReadDTO
        read_class.model_validate(raw)
        # The generated strict DTO validates all wire types before these casts.
        # Read the original entry to retain unknown fields and optional-field presence.
        entry = cast(Mapping[str, object], raw["entry"])
        # DTOs also accept Python attribute names; conversion requires wire keys.
        _require_wire_fields(
            entry,
            (
                "entryId",
                "workbookId",
                "collectionId",
                "revId",
                "savedId",
                "publishedId",
                "createdBy",
                "createdAt",
                "updatedBy",
                "updatedAt",
                "tenantId",
            ),
            operation=operation,
        )
        entry_id = entry["entryId"]
        if not isinstance(entry_id, str) or not entry_id:
            raise translate_invalid_response_error(operation=operation, reason="entry is missing a SQL query id")
        if expected_id is not None and entry_id != expected_id:
            raise translate_invalid_response_error(
                operation=operation,
                reason=f"entry id {entry_id!r} does not match requested SQL query id {expected_id!r}",
            )
        if entry["scope"] != "sql_query":
            raise translate_invalid_response_error(operation=operation, reason="entry is not a SQL query")
        workbook_id = cast(str, entry["workbookId"])
        domain_location = EntryLocation.workbook(workbook_id)
        if location is not None and workbook_id_from_location(location) == workbook_id:
            domain_location = location
        data = cast(Mapping[str, object], entry["data"])
        _require_wire_fields(data, ("connectionId", "statementPositions"), operation=operation)
        annotation = cast(Mapping[str, object] | None, entry["annotation"])
        parameters = cast(Sequence[Mapping[str, object]], data.get("params", ()))
        # Only get validates these enrichments; other response DTOs ignore them as extras.
        permission_values = (
            cast(Mapping[str, bool] | None, raw.get("permissions")) if operation == "getSqlQuery" else None
        )
        permissions = (
            SqlQueryPermissions(
                execute=permission_values["execute"],
                read=permission_values["read"],
                edit=permission_values["edit"],
                admin=permission_values["admin"],
            )
            if permission_values is not None
            else None
        )
        # Get resolves names through the matching navigation entry; its SQL response
        # schema does not own a name, even if one arrives as an extra field.
        entry_name = entry.get("name") if operation != "getSqlQuery" else None
        return SqlQuery(
            id=entry_id,
            name=entry_name if isinstance(entry_name, str) else name,
            installation=installation,
            location=domain_location,
            collection_id=cast(str | None, entry["collectionId"]),
            type=cast(str, entry["type"]),
            key=cast(str, entry["key"]),
            rev_id=cast(str, entry["revId"]),
            saved_id=cast(str, entry["savedId"]),
            published_id=cast(str | None, entry["publishedId"]),
            version=cast(int | float | None, entry["version"]),
            rev_updated_by=cast(str | None, entry.get("revUpdatedBy")),
            rev_updated_at=cast(str | None, entry.get("revUpdatedAt")),
            connection_id=cast(str, data["connectionId"]),
            query=cast(str, data["query"]),
            parameters=tuple(_parameter(parameter, operation=operation) for parameter in parameters),
            statement_positions=_statement_positions(data["statementPositions"], operation=operation),
            description=cast(str | None, annotation.get("description")) if annotation is not None else None,
            created_by=cast(str, entry["createdBy"]),
            created_at=cast(str, entry["createdAt"]),
            updated_by=cast(str, entry["updatedBy"]),
            updated_at=cast(str, entry["updatedAt"]),
            tenant_id=cast(str, entry["tenantId"]),
            hidden=cast(bool, entry["hidden"]),
            links=cast(Mapping[str, str] | None, entry.get("links")),
            is_favorite=cast(bool | None, raw.get("isFavorite")) if operation == "getSqlQuery" else None,
            permissions=permissions,
            raw=dict(entry),
            _operations=operations,
        )
