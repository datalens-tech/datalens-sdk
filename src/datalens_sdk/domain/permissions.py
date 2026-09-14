from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeAlias, TypeVar

PermissionGrantType: TypeAlias = Literal["acl_view", "acl_execute", "acl_edit", "acl_adm"]
PermissionSubjectType: TypeAlias = Literal[
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
class PermissionSubjectParent:
    link: str
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionSubject:
    """Subject metadata as returned by the API; an empty subject is valid."""

    name: str | None = None
    title: str | None = None
    type: PermissionSubjectType | None = None
    link: str | None = None
    icon: str | None = None
    cloud_user_id: str | None = None
    cloud_icon: str | None = None
    cloud_icon_data: str | None = None
    rls_id: str | None = None
    source: str | None = None
    parent: PermissionSubjectParent | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionExtras:
    initial_on_create: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionParticipant:
    """A granted participant; ``name`` is the subject ID to use in mutations."""

    name: str
    kind: Literal["user", "group"]
    subject: PermissionSubject
    description: str | None
    requester: PermissionSubject | None
    approver: PermissionSubject | None
    extras: PermissionExtras | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingPermissionParticipant:
    """A pending request; ``name`` is the subject ID and ``approver`` is always None."""

    name: str
    kind: Literal["user", "group"]
    subject: PermissionSubject
    description: str
    requester: PermissionSubject | None
    approver: None
    extras: PermissionExtras | None


_ParticipantT = TypeVar("_ParticipantT", PermissionParticipant, PendingPermissionParticipant)


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionSet(Generic[_ParticipantT]):
    acl_view: tuple[_ParticipantT, ...] = ()
    acl_execute: tuple[_ParticipantT, ...] = ()
    acl_edit: tuple[_ParticipantT, ...] = ()
    acl_adm: tuple[_ParticipantT, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPermissions:
    editable: bool
    permissions: PermissionSet[PermissionParticipant]
    pending_permissions: PermissionSet[PendingPermissionParticipant]


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionGrant:
    """An explicit grant to add or remove; subject is an opaque identifier."""

    subject: str
    grant_type: PermissionGrantType
    comment: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionModification:
    """Modify the existing grant identified by ``subject`` and ``grant_type``.

    Keep ``new_subject`` equal to ``subject`` to change only the ACL level.
    """

    subject: str
    grant_type: PermissionGrantType
    new_subject: str
    new_grant_type: PermissionGrantType
    comment: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionDiff:
    added: tuple[PermissionGrant, ...] = ()
    removed: tuple[PermissionGrant, ...] = ()
    modified: tuple[PermissionModification, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionModificationResult:
    result: Literal["ok"]
    next_page_token: str | None = None

    @property
    def continuation_required(self) -> bool:
        """The server supplied continuation information, including an empty token.

        The API has no documented input token for resuming this mutation.
        Do not repeat a successful diff to attempt continuation.
        """
        return self.next_page_token is not None
