from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from typing_extensions import Self

from datalens_sdk.domain.entry_location import (
    EntryLocation,
    resolve_entry_location,
    validate_entry_name,
)
from datalens_sdk.domain.navigation import (
    DirectoryListOptions,
    DirectoryPager,
    EntryOrderField,
    EntrySummary,
    SortDirection,
)
from datalens_sdk.domain.ports import FolderOperations
from datalens_sdk.domain.specs.folder import FolderCreateSpec, FolderUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


class FolderCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        operations: FolderOperations | None = None,
    ) -> None:
        resolved = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path"},
            context="Folder creation",
        )
        validate_entry_name(name=name, location=resolved)
        self._installation = installation
        self._name = name
        self._location = resolved
        self._operations = operations

    def to_spec(self) -> FolderCreateSpec:
        return FolderCreateSpec(name=self._name, location=self._location)

    def build(self) -> Folder:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.create_folder(self)


@dataclass(slots=True)
class Folder(EntryLocation):
    id: str | None
    name: str
    key: str
    installation: str = ""
    scope: str = "folder"
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    hidden: bool = False
    meta: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    _operations: FolderOperations | None = field(default=None, repr=False, compare=False)

    def _as_entry_location(self) -> EntryLocation:
        if not self.key:
            raise DataLensValidationError("Cannot use a folder without a key as a destination")
        return EntryLocation.path(self.key)

    @property
    def update(self) -> FolderUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a folder without an id")
        return FolderUpdate(folder=self, operations=self._operations)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a folder without an id")
        self._operations.delete_folder(self.id)

    def rename(self, name: str) -> Folder:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot rename a folder without an id")
        validate_entry_name(name=name, location=self)
        return self.update.name(name).execute()

    def move(self, location: EntryLocation, *, name: str | None = None) -> Folder:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot move a folder without an id")
        resolved_location = resolve_entry_location(
            location=location,
            installation=self.installation,
            allowed_kinds={"path"},
            context="Folder move",
        )
        if name is not None:
            validate_entry_name(name=name, location=resolved_location)
        return self._operations.move_folder(self, resolved_location, name=name)

    def list_entries(
        self,
        *,
        created_by: str | Sequence[str] | None = None,
        name: str | None = None,
        include_permissions_info: bool | None = None,
        order_by: EntryOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
    ) -> DirectoryPager[EntrySummary]:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.key:
            raise DataLensValidationError("Cannot list entries for a folder without a key")
        return self._operations.list_folder_entries(
            self.key,
            DirectoryListOptions.create(
                created_by=created_by,
                name=name,
                include_permissions_info=include_permissions_info,
                order_by=order_by,
                order_direction=order_direction,
                page_size=page_size,
            ),
        )


class FolderUpdate:
    def __init__(self, *, folder: Folder, operations: FolderOperations | None = None) -> None:
        self._folder = folder
        self._operations = operations
        self._name: str | None = None

    def name(self, value: str) -> Self:
        if not value:
            raise DataLensValidationError("name must not be empty")
        self._name = value
        return self

    def to_spec(self) -> FolderUpdateSpec:
        if not self._folder.id:
            raise DataLensValidationError("Cannot update a folder without an id")
        if self._name is None:
            raise DataLensValidationError("Folder update must contain a name change")
        return FolderUpdateSpec(folder_id=self._folder.id, name=self._name)

    def execute(self) -> Folder:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if self._name is None:
            raise DataLensValidationError("Folder update must contain a name change")
        return self._operations.update_folder(self)
