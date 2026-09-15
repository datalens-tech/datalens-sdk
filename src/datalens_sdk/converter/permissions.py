from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, Protocol, TypeVar, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.permissions import (
    EntryPermissions,
    PendingPermissionParticipant,
    PermissionDiff,
    PermissionExtras,
    PermissionGrant,
    PermissionModification,
    PermissionModificationResult,
    PermissionParticipant,
    PermissionSet,
    PermissionSubject,
    PermissionSubjectParent,
    PermissionSubjectType,
)


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


class PermissionSubjectParentReadDTOProtocol(Protocol):
    link: str
    title: str


class PermissionSubjectReadDTOProtocol(Protocol):
    name: str | None
    title: str | None
    type: PermissionSubjectType | None
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
DomainParticipantT = TypeVar("DomainParticipantT", PermissionParticipant, PendingPermissionParticipant)


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


class PermissionsDtoModule(Protocol):
    GetPermissionsArgsDTO: PermissionsArgsDTOClass
    GetPermissionsResultReadDTO: GetPermissionsResultReadDTOClass
    ModifyPermissionsArgsDTO: PermissionsArgsDTOClass
    ModifyPermissionsResultReadDTO: ModifyPermissionsResultReadDTOClass


def _dto_module(dto_module: PermissionsDtoModule | None) -> PermissionsDtoModule:
    return cast(PermissionsDtoModule, generated_dto if dto_module is None else dto_module)


def _subject(dto: PermissionSubjectReadDTOProtocol) -> PermissionSubject:
    return PermissionSubject(
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
            PermissionSubjectParent(link=dto.parent.link, title=dto.parent.title) if dto.parent is not None else None
        ),
    )


def _optional_subject(dto: PermissionSubjectReadDTOProtocol | None) -> PermissionSubject | None:
    return _subject(dto) if dto is not None else None


def _extras(dto: PermissionExtrasReadDTOProtocol | None) -> PermissionExtras | None:
    return PermissionExtras(initial_on_create=dto.initial_on_create) if dto is not None else None


def _participant(dto: PermissionParticipantReadDTOProtocol) -> PermissionParticipant:
    return PermissionParticipant(
        name=dto.name,
        kind=dto.kind,
        subject=_subject(dto.subject),
        description=dto.description,
        requester=_optional_subject(dto.requester),
        approver=_optional_subject(dto.approver),
        extras=_extras(dto.extras),
    )


def _pending_participant(dto: PendingPermissionParticipantReadDTOProtocol) -> PendingPermissionParticipant:
    return PendingPermissionParticipant(
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
) -> PermissionSet[DomainParticipantT]:
    return PermissionSet(
        acl_view=tuple(convert(item) for item in dto.acl_view or ()),
        acl_execute=tuple(convert(item) for item in dto.acl_execute or ()),
        acl_edit=tuple(convert(item) for item in dto.acl_edit or ()),
        acl_adm=tuple(convert(item) for item in dto.acl_adm or ()),
    )


def _changes_payload(
    changes: Sequence[PermissionGrant | PermissionModification],
) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for change in changes:
        item: dict[str, object] = {"subject": change.subject}
        if change.comment is not None:
            item["comment"] = change.comment
        if isinstance(change, PermissionModification):
            item["new"] = {"subject": change.new_subject, "grantType": change.new_grant_type}
        groups.setdefault(change.grant_type, []).append(item)
    return groups


class PermissionsConverter:
    @staticmethod
    def get_payload(
        entry_id: str,
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
        return (
            _dto_module(dto_module)
            .GetPermissionsArgsDTO.model_validate({"entryId": entry_id})
            .model_dump(mode="json", by_alias=True, exclude_unset=True)
        )

    @staticmethod
    def get_result(
        raw: Mapping[str, object],
        *,
        dto_module: PermissionsDtoModule | None = None,
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
        diff: PermissionDiff,
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> dict[str, object]:
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
        raw: Mapping[str, object],
        *,
        dto_module: PermissionsDtoModule | None = None,
    ) -> PermissionModificationResult:
        result = _dto_module(dto_module).ModifyPermissionsResultReadDTO.model_validate(raw)
        return PermissionModificationResult(result=result.result, next_page_token=result.next_page_token)
