from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from datalens_sdk.domain.navigation import Pager
from datalens_sdk.domain.permissions import (
    BulkPermissionsResult,
    DataLensOperation,
    DirectorySubject,
    DirectorySubjectType,
    EffectivePermissionError,
    EntryEffectivePermissionResult,
    EntryPermissions,
    EntryPermissionsCopyResult,
    EntryPermissionsDiff,
    EntryPermissionsModificationResult,
    EntryPermissionSubject,
    RoleBindingDelta,
    RootCollectionPermissions,
    SubjectRoleAssignments,
    _copy_permissions_diff,
)
from datalens_sdk.domain.ports import AccessPermissionsOperations, PermissionsOperations
from datalens_sdk.errors import DataLensValidationError


class EntryAclPermissionsNamespace:
    def __init__(self, operations: PermissionsOperations) -> None:
        self._operations = operations

    def get(self, *, entry_id: str) -> EntryPermissions:
        return self._operations.get_permissions(entry_id=entry_id)

    def modify(self, *, entry_id: str, diff: EntryPermissionsDiff) -> EntryPermissionsModificationResult:
        """Apply one non-recursive diff, preserving the acknowledgement and continuation."""
        return self._operations.modify_permissions(entry_id=entry_id, diff=diff)

    def suggest_subjects(self, *, search_text: str) -> tuple[EntryPermissionSubject, ...]:
        return self._operations.suggest_permission_subjects(search_text=search_text)

    def copy(
        self, *, source_entry_id: str, target_entry_id: str, mode: Literal["replace", "merge"]
    ) -> EntryPermissionsCopyResult:
        """Compare two ACL snapshots and send at most one non-recursive mutation.

        Replace may remove administrative grants. Merge adds missing grant pairs;
        the server may normalize levels. Pending requests and display metadata
        are not copied. Concurrent changes can affect the resulting ACL.
        """
        if mode not in ("replace", "merge"):
            raise DataLensValidationError("copy: mode must be 'replace' or 'merge'")
        if not isinstance(source_entry_id, str) or not isinstance(target_entry_id, str):
            raise DataLensValidationError("copy: source_entry_id and target_entry_id must be strings")
        if source_entry_id == target_entry_id:
            raise DataLensValidationError("copy: source_entry_id and target_entry_id must differ")
        source = self.get(entry_id=source_entry_id)
        target = self.get(entry_id=target_entry_id)
        diff = _copy_permissions_diff(source.permissions, target.permissions, mode=mode)
        if not (diff.added or diff.removed or diff.modified):
            return EntryPermissionsCopyResult(modification=None)
        return EntryPermissionsCopyResult(modification=self.modify(entry_id=target_entry_id, diff=diff))


class WorkbookPermissionsNamespace:
    def __init__(self, operations: AccessPermissionsOperations) -> None:
        self._operations = operations

    def list(
        self, *, workbook_id: str, include_inherited: bool | None = None, page_size: int | None = None
    ) -> Pager[SubjectRoleAssignments]:
        return self._operations.list_workbook(
            workbook_id=workbook_id, include_inherited=include_inherited, page_size=page_size
        )

    def modify(self, *, workbook_id: str, deltas: Sequence[RoleBindingDelta]) -> DataLensOperation:
        """Send the ordered deltas once; return an operation receipt without polling."""
        return self._operations.modify_workbook(workbook_id=workbook_id, deltas=deltas)


class CollectionPermissionsNamespace:
    def __init__(self, operations: AccessPermissionsOperations) -> None:
        self._operations = operations

    def list(
        self, *, collection_id: str, include_inherited: bool | None = None, page_size: int | None = None
    ) -> Pager[SubjectRoleAssignments]:
        return self._operations.list_collection(
            collection_id=collection_id, include_inherited=include_inherited, page_size=page_size
        )

    def modify(self, *, collection_id: str, deltas: Sequence[RoleBindingDelta]) -> DataLensOperation:
        """Remove affects the supplied direct binding; other access may remain."""
        return self._operations.modify_collection(collection_id=collection_id, deltas=deltas)


class SharedEntryPermissionsNamespace:
    def __init__(self, operations: AccessPermissionsOperations) -> None:
        self._operations = operations

    def list(
        self, *, entry_id: str, include_inherited: bool | None = None, page_size: int | None = None
    ) -> Pager[SubjectRoleAssignments]:
        return self._operations.list_shared_entry(
            entry_id=entry_id, include_inherited=include_inherited, page_size=page_size
        )


class EffectivePermissionsNamespace:
    def __init__(self, operations: AccessPermissionsOperations) -> None:
        self._operations = operations

    def get_entries(
        self, *, entry_ids: Sequence[str]
    ) -> Mapping[str, EntryEffectivePermissionResult | EffectivePermissionError]:
        return self._operations.get_entries(entry_ids=entry_ids)

    def get_bulk(
        self,
        *,
        entry_ids: Sequence[str] | None = None,
        workbook_ids: Sequence[str] | None = None,
        collection_ids: Sequence[str] | None = None,
    ) -> BulkPermissionsResult:
        return self._operations.get_bulk(entry_ids=entry_ids, workbook_ids=workbook_ids, collection_ids=collection_ids)

    def get_root_collection(self) -> RootCollectionPermissions:
        return self._operations.get_root_collection()


class PermissionsNamespace:
    """Explicit ACL, role assignment and effective permission operations by ID."""

    def __init__(self, operations: PermissionsOperations, access_operations: AccessPermissionsOperations) -> None:
        self.entry_acl = EntryAclPermissionsNamespace(operations)
        self.workbook = WorkbookPermissionsNamespace(access_operations)
        self.collection = CollectionPermissionsNamespace(access_operations)
        self.shared_entry = SharedEntryPermissionsNamespace(access_operations)
        self.effective = EffectivePermissionsNamespace(access_operations)
        self._access_operations = access_operations

    def list_subjects(
        self,
        *,
        search: str | None = None,
        filter: str | None = None,
        language: Literal["en", "ru"] | None = None,
        subject_type: DirectorySubjectType | None = None,
        page_size: int | None = None,
    ) -> Pager[DirectorySubject]:
        """Search the identity directory; returned claims are not role-write identities."""
        return self._access_operations.list_subjects(
            search=search, filter=filter, language=language, subject_type=subject_type, page_size=page_size
        )
