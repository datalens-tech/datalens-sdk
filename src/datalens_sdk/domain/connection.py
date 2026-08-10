from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    dir_path_from_location,
    key_from_location,
    validate_entry_name,
    workbook_id_from_location,
)
from datalens_sdk.domain.navigation import EntryRelation, EntryScope, LinkDirection, Pager, RelationOptions
from datalens_sdk.domain.ports import ConnectionOperations
from datalens_sdk.domain.specs.connection import ConnectionUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.artifacts import ArtifactPath, write_connection_artifact
from datalens_sdk.serialization.json_types import JsonValue

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(slots=True)
class Connection:
    id: str | None
    type: str
    name: str | None = None
    installation: str = ""
    description: str = ""
    location: EntryLocation | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    response_snapshot: Mapping[str, JsonValue] = field(default_factory=dict, repr=False, compare=False)
    _operations: ConnectionOperations | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.name is None:
            self.name = _optional_str(self.raw.get("name"))

    def __getattr__(self, name: str) -> object:
        if name in self.raw:
            return self.raw[name]
        raise AttributeError(name)

    @property
    def key(self) -> str | None:
        return _optional_str(self.raw.get("key")) or key_from_location(self.location, name=self.name)

    @property
    def dir_path(self) -> str | None:
        return dir_path_from_location(self.location) or _optional_str(self.raw.get("dir_path"))

    @property
    def workbook_id(self) -> str | None:
        return workbook_id_from_location(self.location) or _optional_str(self.raw.get("workbook_id"))

    @property
    def collection_id(self) -> str | None:
        return collection_id_from_location(self.location) or _optional_str(self.raw.get("collection_id"))

    @property
    def update(self) -> ConnectionUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a connection without an id")
        return ConnectionUpdate(
            connection_id=self.id,
            connection_type=self.type,
            connection_name=self.name,
            connection_location=self.location,
            operations=self._operations,
        )

    def to_file(self, path: ArtifactPath) -> Path:
        return write_connection_artifact(
            path,
            self.response_snapshot,
            name=self.name,
            resource_id=self.id,
        )

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a connection without an id")
        self._operations.delete_connection(self.id)

    def rename(self, name: str) -> Connection:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot rename a connection without an id")
        validate_entry_name(name=name, location=self.location)
        return self._operations.rename_connection(self, name)

    def get_relations(
        self,
        *,
        include_permissions_info: bool | None = None,
        link_direction: LinkDirection | None = None,
        page_size: int = 100,
        scope: EntryScope | None = None,
    ) -> Pager[EntryRelation]:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot get relations for a connection without an id")
        return self._operations.get_entry_relations(
            self.id,
            RelationOptions(
                include_permissions_info=include_permissions_info,
                link_direction=link_direction,
                page_size=page_size,
                scope=scope,
            ),
        )


class ConnectionUpdate:
    def __init__(
        self,
        *,
        connection_id: str,
        connection_type: str,
        connection_name: str | None = None,
        connection_location: EntryLocation | None = None,
        operations: ConnectionOperations | None = None,
    ) -> None:
        self._connection_id = connection_id
        self._connection_type = connection_type
        self._connection_name = connection_name
        self._connection_location = connection_location
        self._operations = operations
        self._changes: dict[str, object] = {}

    def name(self, value: str) -> ConnectionUpdate:
        return self._set("name", value)

    def description(self, value: str) -> ConnectionUpdate:
        return self._set("description", value)

    def set(self, field: str, value: object) -> ConnectionUpdate:
        return self._set(field, value)

    def _set(self, field: str, value: object) -> ConnectionUpdate:
        self._changes[field] = value
        return self

    def __getattr__(self, name: str) -> Callable[[object], ConnectionUpdate]:
        def setter(value: object) -> ConnectionUpdate:
            return self.set(name, value)

        return setter

    def to_spec(self) -> ConnectionUpdateSpec:
        return ConnectionUpdateSpec(
            connection_id=self._connection_id,
            changes=dict(self._changes),
            connection_name=self._connection_name,
            connection_location=self._connection_location,
        )

    def execute(self) -> Connection:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_connection(self)
