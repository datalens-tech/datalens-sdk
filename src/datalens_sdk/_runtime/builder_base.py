from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from typing_extensions import Self

from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.ports import ConnectionOperations
from datalens_sdk.domain.specs.connection import ConnectionCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError, NotSupportedError

_LOCATION_FIELDS = frozenset({"name", "dir_path", "workbook_id", "collection_id"})
_BUILDER_MANAGED_FIELDS = _LOCATION_FIELDS | {"type"}


def _matches_scalar_type(value: object, schema_type: str) -> bool:
    if schema_type == "null":
        return value is None
    if schema_type == "string":
        return type(value) is str
    if schema_type == "boolean":
        return type(value) is bool
    if schema_type == "integer":
        return type(value) is int
    if schema_type == "number":
        return type(value) in (int, float)
    return False


@dataclass(frozen=True, slots=True)
class ConnectorMetadata:
    connector: str
    required: frozenset[str]
    available_fields: frozenset[str]
    defaults: dict[str, object]
    enum_restrictions: dict[str, list[object]]
    mapping_value_types: dict[str, tuple[bool, tuple[str, ...]]] = field(default_factory=dict)


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
        self._params: dict[str, object] = {
            field: value for field, value in metadata.defaults.items() if field not in _LOCATION_FIELDS
        }
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
        return sorted(self._metadata.required - _BUILDER_MANAGED_FIELDS)

    def missing_required(self) -> list[str]:
        return sorted(field for field in self._metadata.required if self._params.get(field) in (None, ""))

    def optional_fields(self) -> list[str]:
        return sorted(self._metadata.available_fields - self._metadata.required - _BUILDER_MANAGED_FIELDS)

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
            if field not in _BUILDER_MANAGED_FIELDS
        }

    def _set(self, field: str, value: object) -> Self:
        if field not in self._metadata.available_fields:
            raise NotSupportedError(f"{self._connector}.{field} is not available on {self._installation}")
        allowed = self._metadata.enum_restrictions.get(field)
        if allowed is not None and value not in allowed:
            raise NotSupportedError(f"{self._connector}.{field}={value!r} is not allowed. Allowed: {allowed}")
        mapping_types = self._metadata.mapping_value_types.get(field)
        if mapping_types is not None:
            nullable, value_types = mapping_types
            if value is None:
                if not nullable:
                    raise DataLensValidationError(f"{self._connector}.{field} cannot be null")
            elif not isinstance(value, Mapping):
                raise DataLensValidationError(f"{self._connector}.{field} must be a mapping")
            else:
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise DataLensValidationError(f"{self._connector}.{field} keys must be strings")
                    if not any(_matches_scalar_type(item, schema_type) for schema_type in value_types):
                        raise DataLensValidationError(f"{self._connector}.{field}[{key!r}] has an invalid value")
                value = dict(value)
        self._params[field] = value
        return self

    def build(self) -> Connection:
        if self._operations is None:
            raise DataLensConfigurationError("Builder is not bound to client operations")
        missing = self.missing_required()
        if missing:
            raise DataLensValidationError(f"Cannot build {self._connector!r}; missing required fields: {missing}")
        return self._operations.create_connection(self)
