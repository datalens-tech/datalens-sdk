from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from typing_extensions import Self

from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.navigation import (
    CollectionContentMode,
    CollectionListOptions,
    Pager,
    StructureOrderField,
    StructureSummary,
)
from datalens_sdk.domain.ports import CollectionOperations
from datalens_sdk.domain.specs.collection import CollectionCreateSpec, CollectionUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


class CollectionCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        parent: EntryLocation | None = None,
        operations: CollectionOperations | None = None,
    ) -> None:
        if not name:
            raise DataLensValidationError("name must not be empty")
        resolved_parent = None
        if parent is not None:
            resolved_parent = resolve_entry_location(
                location=parent,
                installation=installation,
                allowed_kinds={"collection"},
                context="Collection creation",
            )
        self._installation = installation
        self._name = name
        self._parent = resolved_parent
        self._description: str | None = None
        self._operations = operations

    def description(self, value: str) -> Self:
        self._description = value
        return self

    def to_spec(self) -> CollectionCreateSpec:
        return CollectionCreateSpec(
            name=self._name,
            parent=self._parent,
            description=self._description,
        )

    def build(self) -> Collection:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.create_collection(self)


@dataclass(slots=True)
class Collection(EntryLocation):
    id: str | None
    name: str
    installation: str = ""
    description: str | None = None
    parent_id: str | None = None
    tenant_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    meta: Mapping[str, object] = field(default_factory=dict)
    permissions: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    _operations: CollectionOperations | None = field(default=None, repr=False, compare=False)

    def _as_entry_location(self) -> EntryLocation:
        if not self.id:
            raise DataLensValidationError("Cannot use a collection without an id as a destination")
        return EntryLocation.collection(self.id)

    @property
    def update(self) -> CollectionUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a collection without an id")
        return CollectionUpdate(collection=self, operations=self._operations)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a collection without an id")
        self._operations.delete_collection(self.id)

    def rename(self, name: str) -> Collection:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot rename a collection without an id")
        validate_entry_name(name=name)
        return self.update.name(name).execute()

    def move(self, location: EntryLocation | None, *, name: str | None = None) -> Collection:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot move a collection without an id")
        resolved_location = None
        if location is not None:
            resolved_location = resolve_entry_location(
                location=location,
                installation=self.installation,
                allowed_kinds={"collection"},
                context="Collection move",
            )
        if name is not None and not name:
            raise DataLensValidationError("name must not be empty")
        return self._operations.move_collection(self, resolved_location, name=name)

    def list_entries(
        self,
        *,
        filter_string: str | None = None,
        include_permissions_info: bool | None = None,
        mode: CollectionContentMode = "all",
        only_my: bool | None = None,
        order_by: StructureOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
    ) -> Pager[StructureSummary]:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot list entries for a collection without an id")
        return self._operations.list_collection_entries(
            self.id,
            CollectionListOptions(
                filter_string=filter_string,
                include_permissions_info=include_permissions_info,
                mode=mode,
                only_my=only_my,
                order_by=order_by,
                order_direction=order_direction,
                page_size=page_size,
            ),
        )


class CollectionUpdate:
    def __init__(self, *, collection: Collection, operations: CollectionOperations | None = None) -> None:
        self._collection = collection
        self._operations = operations
        self._changes: dict[str, str] = {}

    def name(self, value: str) -> Self:
        if not value:
            raise DataLensValidationError("name must not be empty")
        self._changes["name"] = value
        return self

    def description(self, value: str) -> Self:
        self._changes["description"] = value
        return self

    def to_spec(self) -> CollectionUpdateSpec:
        if not self._collection.id:
            raise DataLensValidationError("Cannot update a collection without an id")
        return CollectionUpdateSpec(
            collection_id=self._collection.id,
            changes=dict(self._changes),
        )

    def execute(self) -> Collection:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self._changes:
            raise DataLensValidationError("Collection update must contain at least one change")
        return self._operations.update_collection(self)
