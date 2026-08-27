from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from typing_extensions import Self

from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.navigation import (
    EntryOrderField,
    EntrySummary,
    Pager,
    WorkbookListOptions,
)
from datalens_sdk.domain.ports import WorkbookOperations
from datalens_sdk.domain.specs.workbook import WorkbookCreateSpec, WorkbookUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_UNBOUND = "Object is not bound to client operations. Use a client namespace."

WorkbookStatus: TypeAlias = Literal["creating", "deleting", "active", "deleted"]


class WorkbookCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        collection: EntryLocation | None = None,
        operations: WorkbookOperations | None = None,
    ) -> None:
        if not name:
            raise DataLensValidationError("name must not be empty")
        resolved_collection = None
        if collection is not None:
            resolved_collection = resolve_entry_location(
                location=collection,
                installation=installation,
                allowed_kinds={"collection"},
                context="Workbook creation",
            )
        self._installation = installation
        self._name = name
        self._collection = resolved_collection
        self._description: str | None = None
        self._operations = operations

    def description(self, value: str) -> Self:
        self._description = value
        return self

    def to_spec(self) -> WorkbookCreateSpec:
        return WorkbookCreateSpec(
            name=self._name,
            collection=self._collection,
            description=self._description,
        )

    def build(self) -> Workbook:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.create_workbook(self)


@dataclass(slots=True)
class Workbook(EntryLocation):
    id: str | None
    name: str
    installation: str = ""
    description: str | None = None
    collection_id: str | None = None
    status: WorkbookStatus | None = None
    tenant_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    meta: Mapping[str, object] = field(default_factory=dict)
    permissions: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    _operations: WorkbookOperations | None = field(default=None, repr=False, compare=False)

    def _as_entry_location(self) -> EntryLocation:
        if not self.id:
            raise DataLensValidationError("Cannot use a workbook without an id as a destination")
        return EntryLocation.workbook(self.id)

    @property
    def update(self) -> WorkbookUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a workbook without an id")
        return WorkbookUpdate(workbook=self, operations=self._operations)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a workbook without an id")
        self._operations.delete_workbook(self.id)

    def rename(self, name: str) -> Workbook:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot rename a workbook without an id")
        validate_entry_name(name=name)
        return self.update.name(name).execute()

    def move(self, location: EntryLocation | None, *, name: str | None = None) -> Workbook:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot move a workbook without an id")
        resolved_location = None
        if location is not None:
            resolved_location = resolve_entry_location(
                location=location,
                installation=self.installation,
                allowed_kinds={"collection"},
                context="Workbook move",
            )
        if name is not None and not name:
            raise DataLensValidationError("name must not be empty")
        return self._operations.move_workbook(self, resolved_location, name=name)

    def list_entries(
        self,
        *,
        created_by: str | None = None,
        name: str | None = None,
        include_permissions_info: bool | None = None,
        order_by: EntryOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
        scope: str | Sequence[str] | None = None,
    ) -> Pager[EntrySummary]:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot list entries for a workbook without an id")
        return self._operations.list_workbook_entries(
            self.id,
            WorkbookListOptions.create(
                created_by=created_by,
                name=name,
                include_permissions_info=include_permissions_info,
                order_by=order_by,
                order_direction=order_direction,
                page_size=page_size,
                scope=scope,
            ),
        )


class WorkbookUpdate:
    def __init__(self, *, workbook: Workbook, operations: WorkbookOperations | None = None) -> None:
        self._workbook = workbook
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

    def to_spec(self) -> WorkbookUpdateSpec:
        if not self._workbook.id:
            raise DataLensValidationError("Cannot update a workbook without an id")
        return WorkbookUpdateSpec(
            workbook_id=self._workbook.id,
            changes=dict(self._changes),
        )

    def execute(self) -> Workbook:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self._changes:
            raise DataLensValidationError("Workbook update must contain at least one change")
        return self._operations.update_workbook(self)
