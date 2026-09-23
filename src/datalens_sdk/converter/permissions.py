from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, cast, runtime_checkable

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.permissions import (
    BindingOrigin,
    BindingSubjectClaims,
    BindingSubjectType,
    BulkEntryEffectivePermissionResult,
    BulkPermissionsResult,
    CollectionEffectivePermissionResult,
    CollectionEffectivePermissions,
    DataLensOperation,
    DirectorySubject,
    DirectorySubjectType,
    EffectivePermissionError,
    EntryEffectivePermissionResult,
    EntryEffectivePermissions,
    FullEntryEffectivePermissions,
    OperationTimestamp,
    RoleAssignment,
    RoleBindingDelta,
    RoleSubject,
    RootCollectionPermissions,
    SubjectRoleAssignments,
    WorkbookEffectivePermissionResult,
    WorkbookEffectivePermissions,
)
from datalens_sdk.serialization.json_types import JsonValue

_ResultT_co = TypeVar("_ResultT_co", covariant=True)


class PermissionsWriteDTOProtocol(Protocol):
    def model_dump(
        self,
        *,
        mode: Literal["json"],
        by_alias: bool,
        exclude_unset: bool,
    ) -> dict[str, object]: ...


class PermissionsArgsDTOClass(Protocol):
    def model_validate(self, obj: object) -> PermissionsWriteDTOProtocol: ...


class ReadDTOClass(Protocol[_ResultT_co]):
    def model_validate(self, obj: object) -> _ResultT_co: ...


class RootReadDTO(Protocol[_ResultT_co]):
    @property
    def root(self) -> _ResultT_co: ...


class BindingClaimsReadDTO(Protocol):
    sub: str
    sub_type: BindingSubjectType
    email: str


class BindingOriginReadDTO(Protocol):
    id: str
    type: str


class RoleAssignmentReadDTO(Protocol):
    role_id: str
    inherited_from: BindingOriginReadDTO | None


class SubjectRoleAssignmentsReadDTO(Protocol):
    subject_claims: BindingClaimsReadDTO
    access_bindings: Sequence[RoleAssignmentReadDTO]
    inherited_access_bindings: Sequence[RoleAssignmentReadDTO]


class AccessBindingsReadDTO(Protocol):
    subjects_with_bindings: Sequence[SubjectRoleAssignmentsReadDTO]
    next_page_token: str


class DirectorySubjectReadDTO(Protocol):
    sub: str
    sub_type: DirectorySubjectType
    email: str
    name: str
    given_name: str
    family_name: str
    preferred_username: str
    federation: JsonValue
    idp_type: str | None
    picture: str | None
    picture_data: str | None


class DirectorySubjectsReadDTO(Protocol):
    members: Sequence[DirectorySubjectReadDTO]
    next_page_token: str


class OperationTimestampReadDTO(Protocol):
    seconds: str
    nanos: int | float | None


class OperationReadDTO(Protocol):
    id: str
    description: str
    created_by: str
    created_at: OperationTimestampReadDTO
    modified_at: OperationTimestampReadDTO
    metadata: Mapping[str, JsonValue]
    done: bool


class EntryEffectiveReadDTO(Protocol):
    execute: bool
    read: bool
    edit: bool
    admin: bool


class FullEntryEffectiveReadDTO(Protocol):
    list_access_bindings: bool
    update_access_bindings: bool
    limited_view: bool
    view: bool
    update: bool
    can_copy: bool
    move: bool
    delete: bool
    create_entry_binding: bool
    create_limited_entry_binding: bool


class WorkbookEffectiveReadDTO(Protocol):
    list_access_bindings: bool
    update_access_bindings: bool
    limited_view: bool
    view: bool
    update: bool
    can_copy: bool
    move: bool
    publish: bool
    embed: bool
    delete: bool


class CollectionEffectiveReadDTO(Protocol):
    list_access_bindings: bool
    update_access_bindings: bool
    create_shared_entry: bool
    create_collection: bool
    create_workbook: bool
    limited_view: bool
    browse: bool
    view: bool
    update: bool
    can_copy: bool
    move: bool
    delete: bool


class RootCollectionReadDTO(Protocol):
    create_collection_in_root: bool
    create_workbook_in_root: bool


@runtime_checkable
class EffectiveErrorReadDTO(Protocol):
    error: Literal["NOT_FOUND"]


class EntryEffectiveResultReadDTO(Protocol):
    permissions: EntryEffectiveReadDTO


class BulkEntryEffectiveResultReadDTO(Protocol):
    permissions: EntryEffectiveReadDTO | None
    full_permissions: FullEntryEffectiveReadDTO | None


class WorkbookEffectiveResultReadDTO(Protocol):
    permissions: WorkbookEffectiveReadDTO | None


class CollectionEffectiveResultReadDTO(Protocol):
    permissions: CollectionEffectiveReadDTO | None


class BulkPermissionsReadDTO(Protocol):
    entries: Mapping[str, BulkEntryEffectiveResultReadDTO | EffectiveErrorReadDTO]
    workbooks: Mapping[str, WorkbookEffectiveResultReadDTO | EffectiveErrorReadDTO]
    collections: Mapping[str, CollectionEffectiveResultReadDTO | EffectiveErrorReadDTO]


class PermissionsDtoModule(Protocol):
    ListWorkbookAccessBindingsArgsDTO: PermissionsArgsDTOClass
    ListCollectionAccessBindingsArgsDTO: PermissionsArgsDTOClass
    ListSharedEntryAccessBindingsArgsDTO: PermissionsArgsDTOClass
    ListIamAccessBindingsResultReadDTO: ReadDTOClass[AccessBindingsReadDTO]
    UpdateWorkbookAccessBindingsArgsDTO: PermissionsArgsDTOClass
    UpdateCollectionAccessBindingsArgsDTO: PermissionsArgsDTOClass
    DatalensOperationReadDTO: ReadDTOClass[OperationReadDTO]
    AccessExtBatchListMembersArgsDTO: PermissionsArgsDTOClass
    AccessExtBatchListMembersResultReadDTO: ReadDTOClass[DirectorySubjectsReadDTO]
    GetEntriesPermissionsArgsDTO: PermissionsArgsDTOClass
    GetEntriesPermissionsResultReadDTO: ReadDTOClass[
        RootReadDTO[Mapping[str, EntryEffectiveResultReadDTO | EffectiveErrorReadDTO]]
    ]
    GetPermissionsBulkArgsDTO: PermissionsArgsDTOClass
    GetPermissionsBulkResultReadDTO: ReadDTOClass[BulkPermissionsReadDTO]
    GetRootCollectionPermissionsResultReadDTO: ReadDTOClass[RootCollectionReadDTO]


def _dto_module(dto_module: PermissionsDtoModule | None) -> PermissionsDtoModule:
    return cast(PermissionsDtoModule, generated_dto if dto_module is None else dto_module)


def _payload(dto: PermissionsArgsDTOClass, fields: dict[str, object]) -> dict[str, object]:
    page_size = fields.get("pageSize")
    if page_size is not None and (not isinstance(page_size, int) or isinstance(page_size, bool)):
        raise ValueError("page_size must be an integer")
    return dto.model_validate({key: value for key, value in fields.items() if value is not None}).model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )


def _assignment(dto: RoleAssignmentReadDTO) -> RoleAssignment:
    origin = dto.inherited_from
    return RoleAssignment(
        role_id=dto.role_id,
        inherited_from=BindingOrigin(id=origin.id, type=origin.type) if origin is not None else None,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessBindingsPage:
    subjects: tuple[SubjectRoleAssignments, ...]
    next_page_token: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectorySubjectsPage:
    subjects: tuple[DirectorySubject, ...]
    next_page_token: str


class AccessBindingsConverter:
    @staticmethod
    def list_workbook_payload(
        workbook_id: str,
        *,
        include_inherited: bool | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).ListWorkbookAccessBindingsArgsDTO,
            {
                "workbookId": workbook_id,
                "getInheritedBindings": include_inherited,
                "pageSize": page_size,
                "pageToken": page_token,
            },
        )

    @staticmethod
    def list_collection_payload(
        collection_id: str,
        *,
        include_inherited: bool | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).ListCollectionAccessBindingsArgsDTO,
            {
                "collectionId": collection_id,
                "getInheritedBindings": include_inherited,
                "pageSize": page_size,
                "pageToken": page_token,
            },
        )

    @staticmethod
    def list_shared_entry_payload(
        entry_id: str,
        *,
        include_inherited: bool | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).ListSharedEntryAccessBindingsArgsDTO,
            {
                "entryId": entry_id,
                "getInheritedBindings": include_inherited,
                "pageSize": page_size,
                "pageToken": page_token,
            },
        )

    @staticmethod
    def list_result(raw: object, *, dto_module: PermissionsDtoModule | None = None) -> AccessBindingsPage:
        dto = _dto_module(dto_module).ListIamAccessBindingsResultReadDTO.model_validate(raw)
        return AccessBindingsPage(
            subjects=tuple(
                SubjectRoleAssignments(
                    subject_claims=BindingSubjectClaims(
                        sub=item.subject_claims.sub,
                        sub_type=item.subject_claims.sub_type,
                        email=item.subject_claims.email,
                    ),
                    access_bindings=tuple(_assignment(binding) for binding in item.access_bindings),
                    inherited_access_bindings=tuple(_assignment(binding) for binding in item.inherited_access_bindings),
                )
                for item in dto.subjects_with_bindings
            ),
            next_page_token=dto.next_page_token,
        )

    @staticmethod
    def modify_workbook_payload(
        workbook_id: str,
        deltas: Sequence[RoleBindingDelta],
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).UpdateWorkbookAccessBindingsArgsDTO,
            {
                "workbookId": workbook_id,
                "deltas": _deltas(deltas),
            },
        )

    @staticmethod
    def modify_collection_payload(
        collection_id: str,
        deltas: Sequence[RoleBindingDelta],
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).UpdateCollectionAccessBindingsArgsDTO,
            {
                "collectionId": collection_id,
                "deltas": _deltas(deltas),
            },
        )

    @staticmethod
    def modify_result(raw: object, *, dto_module: PermissionsDtoModule | None = None) -> DataLensOperation:
        dto = _dto_module(dto_module).DatalensOperationReadDTO.model_validate(raw)
        return DataLensOperation(
            id=dto.id,
            description=dto.description,
            created_by=dto.created_by,
            created_at=OperationTimestamp(seconds=dto.created_at.seconds, nanos=dto.created_at.nanos),
            modified_at=OperationTimestamp(seconds=dto.modified_at.seconds, nanos=dto.modified_at.nanos),
            metadata=dto.metadata,
            done=dto.done,
        )


def _deltas(deltas: Sequence[RoleBindingDelta]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for delta in deltas:
        if not isinstance(delta, RoleBindingDelta):
            raise ValueError("deltas must contain RoleBindingDelta values")
        if not isinstance(delta.subject, RoleSubject):
            raise ValueError("Each role delta requires an explicit RoleSubject")
        result.append(
            {
                "action": delta.action,
                "accessBinding": {
                    "roleId": delta.role_id,
                    "subject": {"id": delta.subject.id, "type": delta.subject.type},
                },
            }
        )
    return result


class DirectorySubjectsConverter:
    @staticmethod
    def list_payload(
        *,
        search: str | None = None,
        filter: str | None = None,
        language: Literal["en", "ru"] | None = None,
        subject_type: DirectorySubjectType | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).AccessExtBatchListMembersArgsDTO,
            {
                "search": search,
                "filter": filter,
                "language": language,
                "tabId": subject_type,
                "pageSize": page_size,
                "pageToken": page_token,
            },
        )

    @staticmethod
    def list_result(raw: object, *, dto_module: PermissionsDtoModule | None = None) -> DirectorySubjectsPage:
        dto = _dto_module(dto_module).AccessExtBatchListMembersResultReadDTO.model_validate(raw)
        return DirectorySubjectsPage(
            subjects=tuple(
                DirectorySubject(
                    sub=item.sub,
                    sub_type=item.sub_type,
                    email=item.email,
                    name=item.name,
                    given_name=item.given_name,
                    family_name=item.family_name,
                    preferred_username=item.preferred_username,
                    federation=item.federation,
                    idp_type=item.idp_type,
                    picture=item.picture,
                    picture_data=item.picture_data,
                )
                for item in dto.members
            ),
            next_page_token=dto.next_page_token,
        )


def _entry_effective(dto: EntryEffectiveReadDTO) -> EntryEffectivePermissions:
    return EntryEffectivePermissions(execute=dto.execute, read=dto.read, edit=dto.edit, admin=dto.admin)


def _full_entry_effective(dto: FullEntryEffectiveReadDTO) -> FullEntryEffectivePermissions:
    return FullEntryEffectivePermissions(
        list_access_bindings=dto.list_access_bindings,
        update_access_bindings=dto.update_access_bindings,
        limited_view=dto.limited_view,
        view=dto.view,
        update=dto.update,
        copy=dto.can_copy,
        move=dto.move,
        delete=dto.delete,
        create_entry_binding=dto.create_entry_binding,
        create_limited_entry_binding=dto.create_limited_entry_binding,
    )


def _workbook_effective(dto: WorkbookEffectiveReadDTO) -> WorkbookEffectivePermissions:
    return WorkbookEffectivePermissions(
        list_access_bindings=dto.list_access_bindings,
        update_access_bindings=dto.update_access_bindings,
        limited_view=dto.limited_view,
        view=dto.view,
        update=dto.update,
        copy=dto.can_copy,
        move=dto.move,
        delete=dto.delete,
        publish=dto.publish,
        embed=dto.embed,
    )


def _collection_effective(dto: CollectionEffectiveReadDTO) -> CollectionEffectivePermissions:
    return CollectionEffectivePermissions(
        list_access_bindings=dto.list_access_bindings,
        update_access_bindings=dto.update_access_bindings,
        limited_view=dto.limited_view,
        browse=dto.browse,
        view=dto.view,
        update=dto.update,
        copy=dto.can_copy,
        move=dto.move,
        delete=dto.delete,
        create_shared_entry=dto.create_shared_entry,
        create_collection=dto.create_collection,
        create_workbook=dto.create_workbook,
    )


def _entries_result(
    entries: Mapping[str, EntryEffectiveResultReadDTO | EffectiveErrorReadDTO],
) -> dict[str, EntryEffectivePermissionResult | EffectivePermissionError]:
    return {
        key: EffectivePermissionError(error=dto.error)
        if isinstance(dto, EffectiveErrorReadDTO)
        else EntryEffectivePermissionResult(permissions=_entry_effective(dto.permissions))
        for key, dto in entries.items()
    }


def _ids(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("Resource IDs must be a sequence of strings")
    return list(values)


class EffectivePermissionsConverter:
    @staticmethod
    def entries_payload(
        entry_ids: Sequence[str],
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(_dto_module(dto_module).GetEntriesPermissionsArgsDTO, {"entryIds": _ids(entry_ids)})

    @staticmethod
    def bulk_payload(
        *,
        entry_ids: Sequence[str] | None = None,
        workbook_ids: Sequence[str] | None = None,
        collection_ids: Sequence[str] | None = None,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return _payload(
            _dto_module(dto_module).GetPermissionsBulkArgsDTO,
            {
                "entryIds": _ids(entry_ids) if entry_ids is not None else None,
                "workbookIds": _ids(workbook_ids) if workbook_ids is not None else None,
                "collectionIds": _ids(collection_ids) if collection_ids is not None else None,
            },
        )

    @staticmethod
    def entries_result(
        raw: object,
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, EntryEffectivePermissionResult | EffectivePermissionError]:
        return _entries_result(_dto_module(dto_module).GetEntriesPermissionsResultReadDTO.model_validate(raw).root)

    @staticmethod
    def bulk_result(raw: object, *, dto_module: PermissionsDtoModule | None = None) -> BulkPermissionsResult:
        result = _dto_module(dto_module).GetPermissionsBulkResultReadDTO.model_validate(raw)
        return BulkPermissionsResult(
            entries={
                key: EffectivePermissionError(error=item.error)
                if isinstance(item, EffectiveErrorReadDTO)
                else BulkEntryEffectivePermissionResult(
                    permissions=_entry_effective(item.permissions) if item.permissions is not None else None,
                    full_permissions=_full_entry_effective(item.full_permissions)
                    if item.full_permissions is not None
                    else None,
                )
                for key, item in result.entries.items()
            },
            workbooks={
                key: EffectivePermissionError(error=item.error)
                if isinstance(item, EffectiveErrorReadDTO)
                else WorkbookEffectivePermissionResult(
                    permissions=_workbook_effective(item.permissions) if item.permissions is not None else None,
                )
                for key, item in result.workbooks.items()
            },
            collections={
                key: EffectivePermissionError(error=item.error)
                if isinstance(item, EffectiveErrorReadDTO)
                else CollectionEffectivePermissionResult(
                    permissions=_collection_effective(item.permissions) if item.permissions is not None else None,
                )
                for key, item in result.collections.items()
            },
        )

    @staticmethod
    def root_result(raw: object, *, dto_module: PermissionsDtoModule | None = None) -> RootCollectionPermissions:
        dto = _dto_module(dto_module).GetRootCollectionPermissionsResultReadDTO.model_validate(raw)
        return RootCollectionPermissions(
            create_collection_in_root=dto.create_collection_in_root,
            create_workbook_in_root=dto.create_workbook_in_root,
        )
