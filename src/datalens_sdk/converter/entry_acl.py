from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, Protocol, TypeVar, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.permissions import (
    EntryPermissionExtras,
    EntryPermissionGrant,
    EntryPermissionModification,
    EntryPermissionParticipant,
    EntryPermissions,
    EntryPermissionsDiff,
    EntryPermissionSet,
    EntryPermissionsModificationResult,
    EntryPermissionSubject,
    EntryPermissionSubjectParent,
    EntryPermissionSubjectType,
    PendingEntryPermissionParticipant,
)


class EntryAclWriteDTOProtocol(Protocol):
    def model_dump(
        self,
        *,
        mode: Literal["json"],
        by_alias: bool,
        exclude_unset: bool,
    ) -> dict[str, object]: ...


class EntryAclArgsDTOClass(Protocol):
    def model_validate(self, obj: object) -> EntryAclWriteDTOProtocol: ...


class PermissionSubjectParentReadDTOProtocol(Protocol):
    link: str
    title: str


class PermissionSubjectReadDTOProtocol(Protocol):
    name: str | None
    title: str | None
    type: EntryPermissionSubjectType | None
    link: str | None
    icon: str | None
    cloud_user_id: str | None
    cloud_icon: str | None
    cloud_icon_data: str | None
    rls_id: str | None
    source: str | None
    parent: PermissionSubjectParentReadDTOProtocol | None


class PermissionExtrasReadDTOProtocol(Protocol):
    initial_on_create: bool | None


class PermissionParticipantReadDTOProtocol(Protocol):
    name: str
    kind: Literal["user", "group"]
    subject: PermissionSubjectReadDTOProtocol
    description: str | None
    requester: PermissionSubjectReadDTOProtocol | None
    approver: PermissionSubjectReadDTOProtocol | None
    extras: PermissionExtrasReadDTOProtocol | None


class PendingPermissionParticipantReadDTOProtocol(Protocol):
    name: str
    kind: Literal["user", "group"]
    subject: PermissionSubjectReadDTOProtocol
    description: str
    requester: PermissionSubjectReadDTOProtocol | None
    approver: None
    extras: PermissionExtrasReadDTOProtocol | None


ParticipantT_co = TypeVar("ParticipantT_co", covariant=True)
ParticipantT = TypeVar("ParticipantT")
DomainParticipantT = TypeVar("DomainParticipantT", EntryPermissionParticipant, PendingEntryPermissionParticipant)


class PermissionSetReadDTOProtocol(Protocol[ParticipantT_co]):
    @property
    def acl_view(self) -> Sequence[ParticipantT_co] | None: ...

    @property
    def acl_execute(self) -> Sequence[ParticipantT_co] | None: ...

    @property
    def acl_edit(self) -> Sequence[ParticipantT_co] | None: ...

    @property
    def acl_adm(self) -> Sequence[ParticipantT_co] | None: ...


class GetPermissionsResultReadDTOProtocol(Protocol):
    editable: bool
    permissions: PermissionSetReadDTOProtocol[PermissionParticipantReadDTOProtocol]
    pending_permissions: PermissionSetReadDTOProtocol[PendingPermissionParticipantReadDTOProtocol]


class GetPermissionsResultReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> GetPermissionsResultReadDTOProtocol: ...


class ModifyPermissionsResultReadDTOProtocol(Protocol):
    result: Literal["ok"]
    next_page_token: str | None


class ModifyPermissionsResultReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> ModifyPermissionsResultReadDTOProtocol: ...


class DlsSuggestResultReadDTOProtocol(Protocol):
    @property
    def root(self) -> Sequence[PermissionSubjectReadDTOProtocol]: ...


class DlsSuggestResultReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> DlsSuggestResultReadDTOProtocol: ...


class EntryAclDtoModule(Protocol):
    GetPermissionsArgsDTO: EntryAclArgsDTOClass
    GetPermissionsResultReadDTO: GetPermissionsResultReadDTOClass
    ModifyPermissionsArgsDTO: EntryAclArgsDTOClass
    ModifyPermissionsResultReadDTO: ModifyPermissionsResultReadDTOClass
    DlsSuggestArgsDTO: EntryAclArgsDTOClass
    DlsSuggestResultReadDTO: DlsSuggestResultReadDTOClass


def _dto_module(dto_module: EntryAclDtoModule | None) -> EntryAclDtoModule:
    return cast(EntryAclDtoModule, generated_dto if dto_module is None else dto_module)


def _subject(dto: PermissionSubjectReadDTOProtocol) -> EntryPermissionSubject:
    return EntryPermissionSubject(
        name=dto.name,
        title=dto.title,
        type=dto.type,
        link=dto.link,
        icon=dto.icon,
        cloud_user_id=dto.cloud_user_id,
        cloud_icon=dto.cloud_icon,
        cloud_icon_data=dto.cloud_icon_data,
        rls_id=dto.rls_id,
        source=dto.source,
        parent=(
            EntryPermissionSubjectParent(link=dto.parent.link, title=dto.parent.title)
            if dto.parent is not None
            else None
        ),
    )


def _optional_subject(dto: PermissionSubjectReadDTOProtocol | None) -> EntryPermissionSubject | None:
    return _subject(dto) if dto is not None else None


def _extras(dto: PermissionExtrasReadDTOProtocol | None) -> EntryPermissionExtras | None:
    return EntryPermissionExtras(initial_on_create=dto.initial_on_create) if dto is not None else None


def _participant(dto: PermissionParticipantReadDTOProtocol) -> EntryPermissionParticipant:
    return EntryPermissionParticipant(
        name=dto.name,
        kind=dto.kind,
        subject=_subject(dto.subject),
        description=dto.description,
        requester=_optional_subject(dto.requester),
        approver=_optional_subject(dto.approver),
        extras=_extras(dto.extras),
    )


def _pending_participant(dto: PendingPermissionParticipantReadDTOProtocol) -> PendingEntryPermissionParticipant:
    return PendingEntryPermissionParticipant(
        name=dto.name,
        kind=dto.kind,
        subject=_subject(dto.subject),
        description=dto.description,
        requester=_optional_subject(dto.requester),
        approver=dto.approver,
        extras=_extras(dto.extras),
    )


def _permission_set(
    dto: PermissionSetReadDTOProtocol[ParticipantT],
    convert: Callable[[ParticipantT], DomainParticipantT],
) -> EntryPermissionSet[DomainParticipantT]:
    return EntryPermissionSet(
        acl_view=tuple(convert(item) for item in dto.acl_view or ()),
        acl_execute=tuple(convert(item) for item in dto.acl_execute or ()),
        acl_edit=tuple(convert(item) for item in dto.acl_edit or ()),
        acl_adm=tuple(convert(item) for item in dto.acl_adm or ()),
    )


def _changes_payload(
    changes: Sequence[EntryPermissionGrant | EntryPermissionModification],
) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for change in changes:
        if not isinstance(change, (EntryPermissionGrant, EntryPermissionModification)):
            raise ValueError("ACL changes must be explicit EntryPermissionGrant or EntryPermissionModification values")
        item: dict[str, object] = {"subject": change.subject}
        if change.comment is not None:
            item["comment"] = change.comment
        if isinstance(change, EntryPermissionModification):
            item["new"] = {"subject": change.new_subject, "grantType": change.new_grant_type}
        groups.setdefault(change.grant_type, []).append(item)
    return groups


class EntryAclConverter:
    @staticmethod
    def get_payload(
        entry_id: str,
        *,
        dto_module: EntryAclDtoModule | None = None,
    ) -> dict[str, object]:
        return (
            _dto_module(dto_module)
            .GetPermissionsArgsDTO.model_validate({"entryId": entry_id})
            .model_dump(mode="json", by_alias=True, exclude_unset=True)
        )

    @staticmethod
    def get_result(
        raw: object,
        *,
        dto_module: EntryAclDtoModule | None = None,
    ) -> EntryPermissions:
        result = _dto_module(dto_module).GetPermissionsResultReadDTO.model_validate(raw)
        return EntryPermissions(
            editable=result.editable,
            permissions=_permission_set(result.permissions, _participant),
            pending_permissions=_permission_set(result.pending_permissions, _pending_participant),
        )

    @staticmethod
    def modify_payload(
        entry_id: str,
        diff: EntryPermissionsDiff,
        *,
        dto_module: EntryAclDtoModule | None = None,
    ) -> dict[str, object]:
        if not isinstance(diff, EntryPermissionsDiff):
            raise ValueError("diff must be an EntryPermissionsDiff")
        changes: dict[str, object] = {}
        if diff.added:
            changes["added"] = _changes_payload(diff.added)
        if diff.removed:
            changes["removed"] = _changes_payload(diff.removed)
        if diff.modified:
            changes["modified"] = _changes_payload(diff.modified)
        return (
            _dto_module(dto_module)
            .ModifyPermissionsArgsDTO.model_validate({"entryId": entry_id, "body": {"diff": changes}, "nested": False})
            .model_dump(mode="json", by_alias=True, exclude_unset=True)
        )

    @staticmethod
    def modify_result(
        raw: object,
        *,
        dto_module: EntryAclDtoModule | None = None,
    ) -> EntryPermissionsModificationResult:
        result = _dto_module(dto_module).ModifyPermissionsResultReadDTO.model_validate(raw)
        return EntryPermissionsModificationResult(result=result.result, next_page_token=result.next_page_token)


class EntryAclSuggestionsConverter:
    @staticmethod
    def payload(search_text: str, *, dto_module: EntryAclDtoModule | None = None) -> dict[str, object]:
        return (
            _dto_module(dto_module)
            .DlsSuggestArgsDTO.model_validate({"searchText": search_text})
            .model_dump(mode="json", by_alias=True, exclude_unset=True)
        )

    @staticmethod
    def result(raw: object, *, dto_module: EntryAclDtoModule | None = None) -> tuple[EntryPermissionSubject, ...]:
        dto = _dto_module(dto_module).DlsSuggestResultReadDTO.model_validate(raw)
        return tuple(_subject(item) for item in dto.root)
