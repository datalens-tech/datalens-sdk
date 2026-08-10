from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import Self

from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.ports import ConnectionOperations
from datalens_sdk.domain.specs.connection import ConnectionCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError, NotSupportedError

_LOCATION_FIELDS = frozenset({"name", "dir_path", "workbook_id", "collection_id"})


@dataclass(frozen=True, slots=True)
class ConnectorMetadata:
    connector: str
    required: frozenset[str]
    available_fields: frozenset[str]
    defaults: dict[str, object]
    enum_restrictions: dict[str, list[object]]


@dataclass(frozen=True, slots=True)
class FieldHelp:
    name: str
    required: bool
    default: object | None
    allowed_values: tuple[object, ...] | None


class BaseConnectionCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        connector: str,
        metadata: ConnectorMetadata,
        operations: ConnectionOperations | None = None,
    ) -> None:
        self._installation = installation
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
        )
        validate_entry_name(name=name, location=self._location)
        self._name = name
        self._connector = connector
        self._metadata = metadata
        self._operations = operations
        self._params: dict[str, object] = dict(metadata.defaults)
        self._params["type"] = connector

    @property
    def installation(self) -> str:
        return self._installation

    @property
    def connector(self) -> str:
        return self._connector

    def to_spec(self) -> ConnectionCreateSpec:
        return ConnectionCreateSpec(
            installation=self._installation,
            connector=self._connector,
            name=self._name,
            params=dict(self._params),
            location=self._location,
        )

    def description(self, value: str) -> Self:
        return self._set("description", value)

    def required_fields(self) -> list[str]:
        return sorted(self._metadata.required)

    def missing_required(self) -> list[str]:
        return sorted(field for field in self._metadata.required if self._params.get(field) in (None, ""))

    def optional_fields(self) -> list[str]:
        return sorted(self._metadata.available_fields - self._metadata.required - _LOCATION_FIELDS)

    def allowed_values(self, field: str) -> list[object] | None:
        return self._metadata.enum_restrictions.get(field)

    def fields_help(self) -> dict[str, FieldHelp]:
        return {
            field: FieldHelp(
                name=field,
                required=field in self._metadata.required,
                default=self._metadata.defaults.get(field),
                allowed_values=(
                    tuple(self._metadata.enum_restrictions[field])
                    if field in self._metadata.enum_restrictions
                    else None
                ),
            )
            for field in sorted(self._metadata.available_fields)
            if field not in _LOCATION_FIELDS
        }

    def _set(self, field: str, value: object) -> Self:
        if field not in self._metadata.available_fields:
            raise NotSupportedError(f"{self._connector}.{field} is not available on {self._installation}")
        allowed = self._metadata.enum_restrictions.get(field)
        if allowed is not None and value not in allowed:
            raise NotSupportedError(f"{self._connector}.{field}={value!r} is not allowed. Allowed: {allowed}")
        self._params[field] = value
        return self

    def build(self) -> Connection:
        if self._operations is None:
            raise DataLensConfigurationError("Builder is not bound to client operations")
        missing = self.missing_required()
        if missing:
            raise DataLensValidationError(f"Cannot build {self._connector!r}; missing required fields: {missing}")
        return self._operations.create_connection(self)
