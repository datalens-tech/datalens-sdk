from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, Literal, TypeAlias, TypeVar

from datalens_sdk.serialization.json_types import JsonValue

EntryPermissionGrantType: TypeAlias = Literal["acl_view", "acl_execute", "acl_edit", "acl_adm"]
_PERMISSION_LEVELS: tuple[EntryPermissionGrantType, ...] = ("acl_view", "acl_execute", "acl_edit", "acl_adm")
EntryPermissionSubjectType: TypeAlias = Literal[
    "user",
    "user-staff",
    "user-system",
    "group-system",
    "group-staff-servicerole",
    "group-staff-service",
    "group-staff-wiki",
    "group-staff-department",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionSubjectParent:
    link: str
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionSubject:
    """Subject metadata as returned by the API; an empty subject is valid."""

    name: str | None = None
    title: str | None = None
    type: EntryPermissionSubjectType | None = None
    link: str | None = None
    icon: str | None = None
    cloud_user_id: str | None = None
    cloud_icon: str | None = None
    cloud_icon_data: str | None = None
    rls_id: str | None = None
    source: str | None = None
    parent: EntryPermissionSubjectParent | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionExtras:
    initial_on_create: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionParticipant:
    """A granted participant; ``name`` is the subject ID to use in mutations."""

    name: str
    kind: Literal["user", "group"]
    subject: EntryPermissionSubject
    description: str | None
    requester: EntryPermissionSubject | None
    approver: EntryPermissionSubject | None
    extras: EntryPermissionExtras | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingEntryPermissionParticipant:
    """A pending request; ``name`` is the subject ID and ``approver`` is always None."""

    name: str
    kind: Literal["user", "group"]
    subject: EntryPermissionSubject
    description: str
    requester: EntryPermissionSubject | None
    approver: None
    extras: EntryPermissionExtras | None


_ParticipantT = TypeVar("_ParticipantT", EntryPermissionParticipant, PendingEntryPermissionParticipant)


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionSet(Generic[_ParticipantT]):
    acl_view: tuple[_ParticipantT, ...] = ()
    acl_execute: tuple[_ParticipantT, ...] = ()
    acl_edit: tuple[_ParticipantT, ...] = ()
    acl_adm: tuple[_ParticipantT, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissions:
    editable: bool
    permissions: EntryPermissionSet[EntryPermissionParticipant]
    pending_permissions: EntryPermissionSet[PendingEntryPermissionParticipant]


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionGrant:
    """An explicit grant to add or remove; subject is an opaque identifier."""

    subject: str
    grant_type: EntryPermissionGrantType
    comment: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionModification:
    """Modify the existing grant identified by ``subject`` and ``grant_type``.

    Keep ``new_subject`` equal to ``subject`` to change only the ACL level.
    """

    subject: str
    grant_type: EntryPermissionGrantType
    new_subject: str
    new_grant_type: EntryPermissionGrantType
    comment: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionsDiff:
    added: tuple[EntryPermissionGrant, ...] = ()
    removed: tuple[EntryPermissionGrant, ...] = ()
    modified: tuple[EntryPermissionModification, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionsModificationResult:
    result: Literal["ok"]
    next_page_token: str | None = None

    @property
    def continuation_required(self) -> bool:
        """The server supplied continuation information, including an empty token.

        The API has no documented input token for resuming this mutation.
        Do not repeat a successful diff to attempt continuation.
        """
        return self.next_page_token is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissionsCopyResult:
    """None records matching snapshots; otherwise preserve the actual write receipt."""

    modification: EntryPermissionsModificationResult | None


BindingSubjectType: TypeAlias = Literal[
    "SUBJECT_TYPE_UNSPECIFIED", "USER_ACCOUNT", "SERVICE_ACCOUNT", "GROUP", "INVITEE"
]
DirectorySubjectType: TypeAlias = Literal[
    "SUBJECT_TYPE_UNSPECIFIED", "USER_ACCOUNT", "SERVICE_ACCOUNT", "GROUP", "INVITEE", "_system"
]
RoleSubjectType: TypeAlias = Literal["system", "userAccount", "federatedUser", "serviceAccount", "group", "invitee"]


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingSubjectClaims:
    sub: str
    sub_type: BindingSubjectType
    email: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingOrigin:
    id: str
    type: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleAssignment:
    role_id: str
    inherited_from: BindingOrigin | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SubjectRoleAssignments:
    subject_claims: BindingSubjectClaims
    access_bindings: tuple[RoleAssignment, ...]
    inherited_access_bindings: tuple[RoleAssignment, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleSubject:
    """Explicit verified write identity; read claims do not imply this identity."""

    id: str
    type: RoleSubjectType


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleBindingDelta:
    action: Literal["ADD", "REMOVE"]
    role_id: str
    subject: RoleSubject


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectorySubject:
    sub: str
    sub_type: DirectorySubjectType
    email: str
    name: str
    given_name: str
    family_name: str
    preferred_username: str
    federation: JsonValue = None
    idp_type: str | None = None
    picture: str | None = None
    picture_data: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationTimestamp:
    """Preserve the wire seconds and nanoseconds without datetime truncation."""

    seconds: str
    nanos: int | float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DataLensOperation:
    """Operation receipt; done reports completion without a separate success result."""

    id: str
    description: str
    created_by: str
    created_at: OperationTimestamp
    modified_at: OperationTimestamp
    metadata: Mapping[str, JsonValue]
    done: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryEffectivePermissions:
    execute: bool
    read: bool
    edit: bool
    admin: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class FullEntryEffectivePermissions:
    list_access_bindings: bool
    update_access_bindings: bool
    limited_view: bool
    view: bool
    update: bool
    copy: bool
    move: bool
    delete: bool
    create_entry_binding: bool
    create_limited_entry_binding: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkbookEffectivePermissions:
    list_access_bindings: bool
    update_access_bindings: bool
    limited_view: bool
    view: bool
    update: bool
    copy: bool
    move: bool
    publish: bool
    embed: bool
    delete: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionEffectivePermissions:
    list_access_bindings: bool
    update_access_bindings: bool
    create_shared_entry: bool
    create_collection: bool
    create_workbook: bool
    limited_view: bool
    view: bool
    update: bool
    copy: bool
    move: bool
    delete: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RootCollectionPermissions:
    create_collection_in_root: bool
    create_workbook_in_root: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectivePermissionError:
    error: Literal["NOT_FOUND"]


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryEffectivePermissionResult:
    permissions: EntryEffectivePermissions


@dataclass(frozen=True, slots=True, kw_only=True)
class BulkEntryEffectivePermissionResult:
    permissions: EntryEffectivePermissions | None = None
    full_permissions: FullEntryEffectivePermissions | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkbookEffectivePermissionResult:
    permissions: WorkbookEffectivePermissions | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionEffectivePermissionResult:
    permissions: CollectionEffectivePermissions | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BulkPermissionsResult:
    entries: Mapping[str, BulkEntryEffectivePermissionResult | EffectivePermissionError]
    workbooks: Mapping[str, WorkbookEffectivePermissionResult | EffectivePermissionError]
    collections: Mapping[str, CollectionEffectivePermissionResult | EffectivePermissionError]


def _grant_keys(
    permissions: EntryPermissionSet[EntryPermissionParticipant],
) -> set[tuple[EntryPermissionGrantType, str]]:
    groups: dict[EntryPermissionGrantType, tuple[EntryPermissionParticipant, ...]] = {
        "acl_view": permissions.acl_view,
        "acl_execute": permissions.acl_execute,
        "acl_edit": permissions.acl_edit,
        "acl_adm": permissions.acl_adm,
    }
    return {(level, participant.name) for level, participants in groups.items() for participant in participants}


def _copy_permissions_diff(
    source: EntryPermissionSet[EntryPermissionParticipant],
    target: EntryPermissionSet[EntryPermissionParticipant],
    *,
    mode: Literal["replace", "merge"],
) -> EntryPermissionsDiff:
    source_grants = _grant_keys(source)
    target_grants = _grant_keys(target)
    added = source_grants - target_grants
    removed = target_grants - source_grants if mode == "replace" else set()
    modified: list[EntryPermissionModification] = []
    if mode == "replace":
        # Adding a lower level can be ignored while the old grant still exists.
        # Express same-subject level changes as modifications, not add/remove.
        # Pair unmatched levels in ACL field order so multi-level participants
        # produce a stable diff independent of lexical or set ordering.
        changed_subjects = {subject for _, subject in added} & {subject for _, subject in removed}
        for subject in sorted(changed_subjects):
            old_levels = [level for level in _PERMISSION_LEVELS if (level, subject) in removed]
            new_levels = [level for level in _PERMISSION_LEVELS if (level, subject) in added]
            for old_level, new_level in zip(old_levels, new_levels, strict=False):
                modified.append(
                    EntryPermissionModification(
                        subject=subject,
                        grant_type=old_level,
                        new_subject=subject,
                        new_grant_type=new_level,
                    )
                )
                added.remove((new_level, subject))
                removed.remove((old_level, subject))
    return EntryPermissionsDiff(
        added=tuple(EntryPermissionGrant(subject=subject, grant_type=level) for level, subject in sorted(added)),
        removed=tuple(EntryPermissionGrant(subject=subject, grant_type=level) for level, subject in sorted(removed)),
        modified=tuple(modified),
    )
