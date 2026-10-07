from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, get_args

from typing_extensions import Self

from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.ports import SqlQueryOperations
from datalens_sdk.domain.specs.sql_query import SqlQueryCreateSpec, SqlQueryUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_UNBOUND = "Object is not bound to client operations. Use a client namespace."

SqlQueryParameterType: TypeAlias = Literal[
    "string", "number", "boolean", "date", "datetime", "date-interval", "datetime-interval"
]
SqlQueryScalar: TypeAlias = str | int | float | bool
SqlQueryStatementPosition: TypeAlias = tuple[int | float, int | float]
SqlQueryCell: TypeAlias = str | int | float | bool | None
SqlQueryRunStatus: TypeAlias = Literal["success", "error", "pending", "partial_success"]


def _validate_string(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise DataLensValidationError(f"{field_name} must be a string")
    return value


def _validate_id(value: str | None, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DataLensValidationError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class SqlQueryInterval:
    start: str
    end: str

    def __post_init__(self) -> None:
        _validate_string(self.start, field_name="start")
        _validate_string(self.end, field_name="end")


SqlQueryRunValue: TypeAlias = SqlQueryScalar | Sequence[SqlQueryScalar] | SqlQueryInterval


@dataclass(frozen=True, slots=True)
class SqlQueryParameter:
    name: str
    type: SqlQueryParameterType
    default_value: SqlQueryScalar | SqlQueryInterval | None = None

    def __post_init__(self) -> None:
        _validate_id(self.name, field_name="parameter name")
        if self.type not in get_args(SqlQueryParameterType):
            raise DataLensValidationError(f"Unsupported SQL query parameter type: {self.type!r}")
        if self.default_value is None:
            return
        if self.type in ("string", "number", "boolean"):
            valid = isinstance(self.default_value, (str, int, float, bool))
        elif self.type in ("date", "datetime"):
            valid = isinstance(self.default_value, str)
        elif self.type in ("date-interval", "datetime-interval"):
            valid = isinstance(self.default_value, SqlQueryInterval)
        else:
            valid = False
        if not valid:
            raise DataLensValidationError(f"SQL query parameter {self.type!r} has an incompatible default_value")

    @classmethod
    def string(cls, name: str, default: SqlQueryScalar | None = None) -> Self:
        return cls(name=name, type="string", default_value=default)

    @classmethod
    def number(cls, name: str, default: SqlQueryScalar | None = None) -> Self:
        return cls(name=name, type="number", default_value=default)

    @classmethod
    def boolean(cls, name: str, default: SqlQueryScalar | None = None) -> Self:
        return cls(name=name, type="boolean", default_value=default)

    @classmethod
    def date(cls, name: str, default: str | None = None) -> Self:
        return cls(name=name, type="date", default_value=default)

    @classmethod
    def datetime(cls, name: str, default: str | None = None) -> Self:
        return cls(name=name, type="datetime", default_value=default)

    @classmethod
    def date_interval(cls, name: str, default: SqlQueryInterval | None = None) -> Self:
        return cls(name=name, type="date-interval", default_value=default)

    @classmethod
    def datetime_interval(cls, name: str, default: SqlQueryInterval | None = None) -> Self:
        return cls(name=name, type="datetime-interval", default_value=default)


@dataclass(frozen=True, slots=True)
class SqlQueryPermissions:
    execute: bool
    read: bool
    edit: bool
    admin: bool


@dataclass(frozen=True, slots=True)
class SqlQueryRunColumn:
    name: str


@dataclass(frozen=True, slots=True)
class SqlQueryStatementSuccess:
    status: Literal["success"]
    columns: tuple[SqlQueryRunColumn, ...]
    rows: tuple[tuple[SqlQueryCell, ...], ...]
    affected_rows: int | float | None = None


@dataclass(frozen=True, slots=True)
class SqlQueryStatementError:
    status: Literal["error"]
    code: str
    message: str
    database_message: str | None = None


SqlQueryStatementResult: TypeAlias = SqlQueryStatementSuccess | SqlQueryStatementError


@dataclass(frozen=True, slots=True)
class SqlQueryRun:
    id: str
    connection_id: str
    tenant_id: str
    status: SqlQueryRunStatus
    query: str
    statement_positions: tuple[SqlQueryStatementPosition, ...]
    results: tuple[SqlQueryStatementResult, ...]
    created_by: str
    created_at: str
    updated_at: str
    raw: Mapping[str, object] = field(default_factory=dict)


def _connection_id(value: Connection | str, *, installation: str) -> str:
    if isinstance(value, Connection):
        if value.installation and value.installation != installation:
            raise DataLensValidationError(
                f"Cannot use a {value.installation!r} connection on installation {installation!r}"
            )
        return _validate_id(value.id, field_name="connection id")
    return _validate_id(value, field_name="connection id")


def _parameters(values: object) -> tuple[SqlQueryParameter, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise DataLensValidationError("parameters must be a sequence of SqlQueryParameter values")
    result: list[SqlQueryParameter] = []
    for value in values:
        if not isinstance(value, SqlQueryParameter):
            raise DataLensValidationError("parameters must contain only SqlQueryParameter values")
        result.append(value)
    return tuple(result)


class SqlQueryCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        operations: SqlQueryOperations | None = None,
    ) -> None:
        resolved = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"workbook"},
            context="SQL query creation",
        )
        validate_entry_name(name=name, location=resolved)
        self._installation = installation
        self._name = name
        self._location = resolved
        self._operations = operations
        self._connection_id: str | None = None
        self._query: str | None = None
        self._description: str | None = None
        self._parameters: tuple[SqlQueryParameter, ...] | None = None

    def connection(self, value: Connection | str) -> Self:
        self._connection_id = _connection_id(value, installation=self._installation)
        return self

    def query(self, value: str) -> Self:
        self._query = _validate_string(value, field_name="query")
        return self

    def description(self, value: str) -> Self:
        self._description = _validate_string(value, field_name="description")
        return self

    def parameters(self, values: Sequence[SqlQueryParameter]) -> Self:
        self._parameters = _parameters(values)
        return self

    def to_spec(self) -> SqlQueryCreateSpec:
        if self._connection_id is None or self._query is None:
            raise DataLensValidationError("SQL query creation requires connection and query")
        return SqlQueryCreateSpec(
            name=self._name,
            location=self._location,
            connection_id=self._connection_id,
            query=self._query,
            description=self._description,
            parameters=self._parameters,
        )

    def build(self) -> SqlQuery:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        self.to_spec()
        return self._operations.create_sql_query(self)


@dataclass(slots=True)
class SqlQuery:
    id: str | None
    name: str | None
    installation: str
    location: EntryLocation
    collection_id: str | None
    type: str
    key: str
    rev_id: str
    saved_id: str
    published_id: str | None
    version: int | float | None
    rev_updated_by: str | None
    rev_updated_at: str | None
    connection_id: str
    query: str
    parameters: tuple[SqlQueryParameter, ...]
    statement_positions: tuple[SqlQueryStatementPosition, ...]
    description: str | None
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    tenant_id: str
    hidden: bool
    links: Mapping[str, str] | None
    is_favorite: bool | None
    permissions: SqlQueryPermissions | None
    scope: Literal["sql_query"] = "sql_query"
    raw: Mapping[str, object] = field(default_factory=dict)
    _operations: SqlQueryOperations | None = field(default=None, repr=False, compare=False)

    @property
    def update(self) -> SqlQueryUpdate:
        return SqlQueryUpdate(sql_query=self, operations=self._operations)

    def run(self, *, params: Mapping[str, SqlQueryRunValue] | None = None) -> SqlQueryRun:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        sql_query_id = _validate_id(self.id, field_name="SQL query id")
        if params is not None and not isinstance(params, Mapping):
            raise DataLensValidationError("params must be a mapping")
        return self._operations.run_sql_query(sql_query_id, params=params)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        sql_query_id = _validate_id(self.id, field_name="SQL query id")
        self._operations.delete_sql_query(sql_query_id)


class SqlQueryUpdate:
    def __init__(self, *, sql_query: SqlQuery, operations: SqlQueryOperations | None = None) -> None:
        self._sql_query = sql_query
        self._operations = operations
        self._connection_id = sql_query.connection_id
        self._query = sql_query.query
        self._description = sql_query.description
        data = sql_query.raw.get("data")
        self._parameters = sql_query.parameters if isinstance(data, Mapping) and "params" in data else None

    @property
    def sql_query(self) -> SqlQuery:
        return self._sql_query

    def connection(self, value: Connection | str) -> Self:
        self._connection_id = _connection_id(value, installation=self._sql_query.installation)
        return self

    def query(self, value: str) -> Self:
        self._query = _validate_string(value, field_name="query")
        return self

    def description(self, value: str) -> Self:
        self._description = _validate_string(value, field_name="description")
        return self

    def parameters(self, values: Sequence[SqlQueryParameter]) -> Self:
        self._parameters = _parameters(values)
        return self

    def clear_parameters(self) -> Self:
        self._parameters = ()
        return self

    def to_spec(self) -> SqlQueryUpdateSpec:
        return SqlQueryUpdateSpec(
            sql_query_id=_validate_id(self._sql_query.id, field_name="SQL query id"),
            name=self._sql_query.name,
            location=self._sql_query.location,
            connection_id=_validate_id(self._connection_id, field_name="connection id"),
            query=_validate_string(self._query, field_name="query"),
            description=self._description,
            parameters=self._parameters,
        )

    def execute(self) -> SqlQuery:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        self.to_spec()
        return self._operations.update_sql_query(self)
