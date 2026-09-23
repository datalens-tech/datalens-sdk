from __future__ import annotations

from dataclasses import asdict
import json
from typing import TYPE_CHECKING, Literal, cast

import httpx
from pydantic import ValidationError
import pytest
from typing_extensions import assert_type

import datalens_sdk as dl

ACL_LEVELS: tuple[Literal["acl_view", "acl_execute", "acl_edit", "acl_adm"], ...] = (
    "acl_view",
    "acl_execute",
    "acl_edit",
    "acl_adm",
)


class RecordedTransport:
    def __init__(self, *responses: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self.responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, f"Unexpected request: {request.url.path}"
        return self.responses.pop(0)

    def request_json(self, index: int = 0) -> dict[str, object]:
        body: object = json.loads(self.requests[index].content)
        assert isinstance(body, dict)
        return cast(dict[str, object], body)


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(
        auth=None,
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    )


def _invoke(client: dl.DataLensClientYC, operation: str, *, entry_id: str = "entry-1") -> None:
    if operation == "get":
        client.permissions.entry_acl.get(entry_id=entry_id)
    else:
        client.permissions.entry_acl.modify(entry_id=entry_id, diff=dl.EntryPermissionsDiff())


def _subject(name: str) -> dict[str, object]:
    return {
        "name": name,
        "title": f"Title of {name}",
        "type": "user-staff",
        "link": f"https://people.test/{name}",
        "icon": "https://people.test/icon.svg",
        "cloud_user_id": f"cloud-{name}",
        "cloud_icon": "https://cloud.test/icon.svg",
        "cloud_icon_data": "icon-data",
        "__rlsid": f"rls-{name}",
        "__source": "staff",
        "parent": {"link": "https://people.test/team", "title": "Analytics"},
    }


def _participant(name: str, *, pending: bool = False) -> dict[str, object]:
    return {
        "name": name,
        "kind": "user",
        "description": f"Description of {name}",
        "subject": _subject(name),
        "requester": _subject(f"requester-{name}"),
        "approver": None if pending else _subject(f"approver-{name}"),
        "extras": {"initial_on_create": False},
    }


def _permissions_response(grants: dict[str, list[str]]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "editable": True,
            "permissions": {
                level: [_participant(name) | {"subject": _subject(f"metadata-{name}")} for name in names]
                for level, names in grants.items()
            },
            "pendingPermissions": {level: [_participant(f"pending-{level}", pending=True)] for level in ACL_LEVELS},
        },
    )


def _assert_subject(subject: dl.EntryPermissionSubject | None, name: str) -> None:
    assert isinstance(subject, dl.EntryPermissionSubject)
    assert asdict(subject) == {
        "name": name,
        "title": f"Title of {name}",
        "type": "user-staff",
        "link": f"https://people.test/{name}",
        "icon": "https://people.test/icon.svg",
        "cloud_user_id": f"cloud-{name}",
        "cloud_icon": "https://cloud.test/icon.svg",
        "cloud_icon_data": "icon-data",
        "rls_id": f"rls-{name}",
        "source": "staff",
        "parent": {"link": "https://people.test/team", "title": "Analytics"},
    }


def test_get_permissions_preserves_all_levels_and_participant_details() -> None:
    recorder = RecordedTransport(
        httpx.Response(
            200,
            json={
                "editable": True,
                "permissions": {level: [_participant(f"granted-{level}")] for level in ACL_LEVELS},
                "pendingPermissions": {level: [_participant(f"pending-{level}", pending=True)] for level in ACL_LEVELS},
                "futureField": "ignored",
            },
        )
    )

    result = _client(recorder).permissions.entry_acl.get(entry_id="entry-1")

    assert isinstance(result, dl.EntryPermissions)
    assert result.editable is True
    granted_groups = (
        result.permissions.acl_view,
        result.permissions.acl_execute,
        result.permissions.acl_edit,
        result.permissions.acl_adm,
    )
    pending_groups = (
        result.pending_permissions.acl_view,
        result.pending_permissions.acl_execute,
        result.pending_permissions.acl_edit,
        result.pending_permissions.acl_adm,
    )
    for level, granted, pending in zip(ACL_LEVELS, granted_groups, pending_groups, strict=True):
        assert isinstance(granted, tuple)
        assert isinstance(pending, tuple)
        assert len(granted) == len(pending) == 1
        assert isinstance(granted[0], dl.EntryPermissionParticipant)
        assert isinstance(pending[0], dl.PendingEntryPermissionParticipant)
        for participant, prefix in ((granted[0], "granted"), (pending[0], "pending")):
            name = f"{prefix}-{level}"
            assert participant.name == name
            assert participant.kind == "user"
            assert participant.description == f"Description of {name}"
            assert participant.extras == dl.EntryPermissionExtras(initial_on_create=False)
            _assert_subject(participant.subject, name)
            _assert_subject(participant.requester, f"requester-{name}")
        _assert_subject(granted[0].approver, f"approver-granted-{level}")
        assert pending[0].approver is None
    assert recorder.request_json() == {"entryId": "entry-1"}
    assert recorder.requests[0].url.path == "/rpc/getPermissions"


def test_get_permissions_preserves_omitted_granted_description_and_extras_as_none() -> None:
    participant = _participant("admin-1")
    del participant["description"]
    del participant["extras"]
    recorder = RecordedTransport(
        httpx.Response(
            200,
            json={
                "editable": True,
                "permissions": {"acl_adm": [participant]},
                "pendingPermissions": {"acl_view": [_participant("pending-1", pending=True)]},
            },
        )
    )

    result = _client(recorder).permissions.entry_acl.get(entry_id="folder-1")

    granted = result.permissions.acl_adm[0]
    assert granted.name == "admin-1"
    assert granted.description is None
    assert granted.extras is None
    _assert_subject(granted.subject, "admin-1")
    assert result.pending_permissions.acl_view[0].description == "Description of pending-1"
    assert result.pending_permissions.acl_view[0].extras == dl.EntryPermissionExtras(initial_on_create=False)


def test_get_permissions_accepts_omitted_optional_fields_and_explicit_nullable_values() -> None:
    participant: dict[str, object] = {
        "name": "group-1",
        "kind": "group",
        "description": "",
        "subject": {},
        "requester": None,
        "approver": None,
        "extras": None,
    }
    recorder = RecordedTransport(
        httpx.Response(
            200,
            json={"editable": False, "permissions": {"acl_view": [participant]}, "pendingPermissions": {}},
        )
    )

    result = _client(recorder).permissions.entry_acl.get(entry_id="entry-1")

    assert result == dl.EntryPermissions(
        editable=False,
        permissions=dl.EntryPermissionSet(
            acl_view=(
                dl.EntryPermissionParticipant(
                    name="group-1",
                    kind="group",
                    description="",
                    subject=dl.EntryPermissionSubject(),
                    requester=None,
                    approver=None,
                    extras=None,
                ),
            )
        ),
        pending_permissions=dl.EntryPermissionSet(),
    )


@pytest.mark.parametrize("missing", ["editable", "permissions", "pendingPermissions"])
def test_get_permissions_rejects_missing_required_result_fields(missing: str) -> None:
    response: dict[str, object] = {"editable": True, "permissions": {}, "pendingPermissions": {}}
    del response[missing]
    recorder = RecordedTransport(httpx.Response(200, json=response))

    with pytest.raises(dl.InvalidResponseError, match="getPermissions"):
        _client(recorder).permissions.entry_acl.get(entry_id="entry-1")


@pytest.mark.parametrize("missing", ["requester", "approver", "subject"])
def test_get_permissions_rejects_missing_required_participant_fields(missing: str) -> None:
    participant = _participant("user-1")
    del participant[missing]
    recorder = RecordedTransport(
        httpx.Response(
            200,
            json={"editable": True, "permissions": {"acl_view": [participant]}, "pendingPermissions": {}},
        )
    )

    with pytest.raises(dl.InvalidResponseError, match="getPermissions"):
        _client(recorder).permissions.entry_acl.get(entry_id="entry-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject", None),
        ("subject", {"title": None}),
        ("subject", {"parent": None}),
        ("subject", {"parent": {"title": "Missing link"}}),
        ("extras", {"initial_on_create": None}),
        ("kind", "invalid-kind"),
    ],
)
def test_get_permissions_rejects_invalid_participant_values(field: str, value: object) -> None:
    participant = _participant("user-1") | {field: value}
    recorder = RecordedTransport(
        httpx.Response(
            200,
            json={"editable": True, "permissions": {"acl_view": [participant]}, "pendingPermissions": {}},
        )
    )

    with pytest.raises(dl.InvalidResponseError, match="getPermissions"):
        _client(recorder).permissions.entry_acl.get(entry_id="entry-1")


def test_pending_permissions_reject_a_non_null_approver() -> None:
    recorder = RecordedTransport(
        httpx.Response(
            200,
            json={
                "editable": True,
                "permissions": {},
                "pendingPermissions": {"acl_view": [_participant("user-1")]},
            },
        )
    )

    with pytest.raises(dl.InvalidResponseError, match="getPermissions"):
        _client(recorder).permissions.entry_acl.get(entry_id="entry-1")


def test_modify_permissions_serializes_explicit_diff_for_all_four_levels() -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"result": "ok"}))
    diff = dl.EntryPermissionsDiff(
        added=tuple(dl.EntryPermissionGrant(subject=f"add-{level}", grant_type=level) for level in ACL_LEVELS),
        removed=tuple(
            dl.EntryPermissionGrant(subject=f"remove-{level}", grant_type=level, comment="") for level in ACL_LEVELS
        ),
        modified=tuple(
            dl.EntryPermissionModification(
                subject=f"before-{level}",
                grant_type=level,
                new_subject=f"after-{level}",
                new_grant_type=ACL_LEVELS[(index + 1) % len(ACL_LEVELS)],
                comment=f"Change {level}",
            )
            for index, level in enumerate(ACL_LEVELS)
        ),
    )

    result = _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=diff)

    assert result == dl.EntryPermissionsModificationResult(result="ok", next_page_token=None)
    assert result.continuation_required is False
    assert recorder.request_json() == {
        "entryId": "entry-1",
        "nested": False,
        "body": {
            "diff": {
                "added": {level: [{"subject": f"add-{level}"}] for level in ACL_LEVELS},
                "removed": {level: [{"subject": f"remove-{level}", "comment": ""}] for level in ACL_LEVELS},
                "modified": {
                    level: [
                        {
                            "subject": f"before-{level}",
                            "comment": f"Change {level}",
                            "new": {
                                "subject": f"after-{level}",
                                "grantType": ACL_LEVELS[(index + 1) % len(ACL_LEVELS)],
                            },
                        }
                    ]
                    for index, level in enumerate(ACL_LEVELS)
                },
            }
        },
    }
    assert recorder.requests[0].url.path == "/rpc/modifyPermissions"
    assert len(recorder.requests) == 1


def test_modify_permissions_omits_unset_comments_and_unused_diff_groups() -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"result": "ok"}))

    _client(recorder).permissions.entry_acl.modify(
        entry_id="entry-1",
        diff=dl.EntryPermissionsDiff(
            modified=(
                dl.EntryPermissionModification(
                    subject="old-user",
                    grant_type="acl_edit",
                    new_subject="new-user",
                    new_grant_type="acl_view",
                ),
            )
        ),
    )

    assert recorder.request_json() == {
        "entryId": "entry-1",
        "nested": False,
        "body": {
            "diff": {
                "modified": {
                    "acl_edit": [{"subject": "old-user", "new": {"subject": "new-user", "grantType": "acl_view"}}]
                }
            }
        },
    }


@pytest.mark.parametrize("next_page_token", [None, "continue-1", ""])
def test_modify_permissions_preserves_continuation_without_repeating_mutation(next_page_token: str | None) -> None:
    response = {"result": "ok"}
    if next_page_token is not None:
        response["nextPageToken"] = next_page_token
    recorder = RecordedTransport(httpx.Response(200, json=response))

    result = _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff())

    assert result.result == "ok"
    assert result.next_page_token == next_page_token
    assert result.continuation_required is (next_page_token is not None)
    assert recorder.request_json() == {"entryId": "entry-1", "nested": False, "body": {"diff": {}}}
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "response", [{}, {"result": "failed"}, {"result": None}, {"result": "ok", "nextPageToken": None}]
)
def test_modify_permissions_rejects_invalid_success_responses(response: dict[str, object]) -> None:
    recorder = RecordedTransport(httpx.Response(200, json=response))

    with pytest.raises(dl.InvalidResponseError, match="modifyPermissions"):
        _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff())
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("operation", ["get", "modify"])
@pytest.mark.parametrize("response", [[], None, "ok"])
def test_permissions_reject_non_object_response_roots(operation: str, response: object) -> None:
    recorder = RecordedTransport(httpx.Response(200, json=response))
    client = _client(recorder)

    with pytest.raises(dl.InvalidResponseError):
        _invoke(client, operation)
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("operation", ["get", "modify"])
def test_permissions_preserve_access_denied_error_context(operation: str) -> None:
    recorder = RecordedTransport(
        httpx.Response(
            403,
            json={"code": "ERR.US.ACCESS_DENIED", "message": "Insufficient permissions"},
            headers={"x-request-id": "permissions-denied-1"},
        )
    )
    client = _client(recorder)

    with pytest.raises(dl.ForbiddenError, match="Insufficient permissions") as exc_info:
        _invoke(client, operation)

    assert exc_info.value.context.status_code == 403
    assert exc_info.value.context.code == "ERR.US.ACCESS_DENIED"
    assert exc_info.value.context.request_id == "permissions-denied-1"
    assert len(recorder.requests) == 1


def test_modify_permissions_does_not_retry_transient_failure() -> None:
    recorder = RecordedTransport(
        httpx.Response(503, json={"message": "temporarily unavailable"}),
        httpx.Response(200, json={"result": "ok"}),
    )

    with pytest.raises(dl.ServerError, match="temporarily unavailable"):
        _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff())
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("mode", ["replace", "merge"])
def test_copy_permissions_applies_only_granted_subject_level_differences(
    mode: Literal["replace", "merge"],
) -> None:
    recorder = RecordedTransport(
        _permissions_response(
            {
                "acl_view": ["shared", "source-view", "multi-level"],
                "acl_execute": ["source-execute", "multi-level"],
                "acl_edit": ["level-change", "source-edit"],
                "acl_adm": ["source-admin"],
            }
        ),
        _permissions_response(
            {
                "acl_view": ["shared", "target-view", "level-change"],
                "acl_execute": ["target-execute", "multi-level"],
                "acl_edit": ["target-edit"],
                "acl_adm": ["target-admin"],
            }
        ),
        httpx.Response(200, json={"result": "ok", "nextPageToken": "continue-copy"}),
    )

    result = _client(recorder).permissions.entry_acl.copy(
        source_entry_id="source-1", target_entry_id="target-1", mode=mode
    )

    diff: dict[str, object] = {
        "added": {
            "acl_view": [{"subject": "multi-level"}, {"subject": "source-view"}],
            "acl_execute": [{"subject": "source-execute"}],
            "acl_edit": (
                [{"subject": "source-edit"}]
                if mode == "replace"
                else [{"subject": "level-change"}, {"subject": "source-edit"}]
            ),
            "acl_adm": [{"subject": "source-admin"}],
        }
    }
    if mode == "replace":
        diff["removed"] = {
            "acl_view": [{"subject": "target-view"}],
            "acl_execute": [{"subject": "target-execute"}],
            "acl_edit": [{"subject": "target-edit"}],
            "acl_adm": [{"subject": "target-admin"}],
        }
        diff["modified"] = {
            "acl_view": [{"subject": "level-change", "new": {"subject": "level-change", "grantType": "acl_edit"}}]
        }
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getPermissions",
        "/rpc/getPermissions",
        "/rpc/modifyPermissions",
    ]
    assert [recorder.request_json(index) for index in range(3)] == [
        {"entryId": "source-1"},
        {"entryId": "target-1"},
        {"entryId": "target-1", "nested": False, "body": {"diff": diff}},
    ]
    assert result.modification == dl.EntryPermissionsModificationResult(result="ok", next_page_token="continue-copy")
    assert result.modification is not None
    assert result.modification.continuation_required is True


@pytest.mark.parametrize(
    ("source_level", "target_level"),
    [("acl_edit", "acl_view"), ("acl_view", "acl_edit")],
    ids=["raise-to-edit", "lower-to-view"],
)
def test_copy_permissions_pairs_multiple_target_levels_in_acl_order(
    source_level: Literal["acl_view", "acl_edit"],
    target_level: Literal["acl_view", "acl_edit"],
) -> None:
    recorder = RecordedTransport(
        _permissions_response({source_level: ["multi-level"]}),
        _permissions_response({target_level: ["multi-level"], "acl_adm": ["multi-level"]}),
        httpx.Response(200, json={"result": "ok"}),
    )

    result = _client(recorder).permissions.entry_acl.copy(
        source_entry_id="source-1",
        target_entry_id="target-1",
        mode="replace",
    )

    assert recorder.request_json(2) == {
        "entryId": "target-1",
        "nested": False,
        "body": {
            "diff": {
                "removed": {"acl_adm": [{"subject": "multi-level"}]},
                "modified": {
                    target_level: [
                        {"subject": "multi-level", "new": {"subject": "multi-level", "grantType": source_level}}
                    ]
                },
            }
        },
    }
    assert result.modification == dl.EntryPermissionsModificationResult(result="ok")


@pytest.mark.parametrize("mode", ["replace", "merge"])
def test_copy_permissions_skips_mutation_when_grants_already_match(
    mode: Literal["replace", "merge"],
) -> None:
    recorder = RecordedTransport(
        _permissions_response({"acl_view": ["shared"]}),
        _permissions_response({"acl_view": ["shared"]}),
    )

    result = _client(recorder).permissions.entry_acl.copy(
        source_entry_id="source-1", target_entry_id="target-1", mode=mode
    )

    assert [request.url.path for request in recorder.requests] == ["/rpc/getPermissions", "/rpc/getPermissions"]
    assert result == dl.EntryPermissionsCopyResult(modification=None)


@pytest.mark.parametrize("failed_read", ["source", "target"])
def test_copy_permissions_does_not_mutate_after_a_read_failure(failed_read: str) -> None:
    responses = []
    if failed_read == "target":
        responses.append(_permissions_response({"acl_view": ["source-user"]}))
    responses.append(httpx.Response(403, json={"code": "ERR.US.ACCESS_DENIED", "message": "Insufficient permissions"}))
    recorder = RecordedTransport(*responses)

    with pytest.raises(dl.ForbiddenError, match="Insufficient permissions"):
        _client(recorder).permissions.entry_acl.copy(
            source_entry_id="source-1", target_entry_id="target-1", mode="replace"
        )

    expected_entries = ["source-1"] if failed_read == "source" else ["source-1", "target-1"]
    assert [request.url.path for request in recorder.requests] == ["/rpc/getPermissions"] * len(expected_entries)
    assert [recorder.request_json(index) for index in range(len(recorder.requests))] == [
        {"entryId": entry_id} for entry_id in expected_entries
    ]


@pytest.mark.parametrize("mode", ["invalid", None])
def test_copy_permissions_rejects_invalid_mode_before_http(mode: object) -> None:
    recorder = RecordedTransport()

    with pytest.raises(dl.DataLensValidationError, match="mode"):
        _client(recorder).permissions.entry_acl.copy(
            source_entry_id="source-1",
            target_entry_id="target-1",
            mode=cast(Literal["replace", "merge"], mode),
        )

    assert recorder.requests == []


def test_copy_permissions_does_not_repeat_mutation_after_transient_failure() -> None:
    recorder = RecordedTransport(
        _permissions_response({"acl_view": ["source-user"]}),
        _permissions_response({}),
        httpx.Response(
            503,
            json={"message": "temporarily unavailable"},
            headers={"x-request-id": "copy-failed-1"},
        ),
        httpx.Response(200, json={"result": "ok"}),
    )

    with pytest.raises(dl.ServerError, match="temporarily unavailable") as exc_info:
        _client(recorder).permissions.entry_acl.copy(
            source_entry_id="source-1", target_entry_id="target-1", mode="merge"
        )

    assert exc_info.value.context.status_code == 503
    assert exc_info.value.context.request_id == "copy-failed-1"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getPermissions",
        "/rpc/getPermissions",
        "/rpc/modifyPermissions",
    ]
    assert recorder.request_json(2) == {
        "entryId": "target-1",
        "nested": False,
        "body": {"diff": {"added": {"acl_view": [{"subject": "source-user"}]}}},
    }


@pytest.mark.parametrize("client_class", [dl.DataLensClientEnterprise, dl.DataLensClientYC])
def test_public_installations_share_permissions_namespace_and_transport_headers(
    client_class: type[dl.DataLensClientEnterprise] | type[dl.DataLensClientYC],
) -> None:
    recorder = RecordedTransport(
        httpx.Response(200, json={"editable": False, "permissions": {}, "pendingPermissions": {}}),
        httpx.Response(200, json={"result": "ok"}),
    )
    client = client_class(
        auth=dl.StaticYCIAMAuthProvider(org_id="org-1", token="test-token"),
        base_url="https://datalens.test",
        transport=httpx.MockTransport(recorder.handler),
    )

    assert "permissions" in client.capabilities["namespaces"]
    assert client.permissions.entry_acl.get(entry_id="entry-1").editable is False
    assert client.permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff()).result == "ok"

    assert [request.url.path for request in recorder.requests] == ["/rpc/getPermissions", "/rpc/modifyPermissions"]
    for request in recorder.requests:
        assert request.headers["x-dl-api-version"] == "3"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["x-dl-org-id"] == "org-1"


@pytest.mark.parametrize("operation", ["get", "modify"])
@pytest.mark.parametrize("entry_id", [None, 123])
def test_permissions_validate_entry_id_before_http(operation: str, entry_id: object) -> None:
    recorder = RecordedTransport()
    client = _client(recorder)

    with pytest.raises(dl.DataLensValidationError):
        _invoke(client, operation, entry_id=cast(str, entry_id))
    assert recorder.requests == []


@pytest.mark.parametrize("case", ["added", "removed", "modified_grant", "modified_new_grant", "comment"])
def test_modify_permissions_validates_grant_types_before_http(case: str) -> None:
    recorder = RecordedTransport()
    invalid = cast(dl.EntryPermissionGrantType, "read")
    if case == "added":
        diff = dl.EntryPermissionsDiff(added=(dl.EntryPermissionGrant(subject="user-1", grant_type=invalid),))
    elif case == "removed":
        diff = dl.EntryPermissionsDiff(removed=(dl.EntryPermissionGrant(subject="user-1", grant_type=invalid),))
    elif case == "comment":
        diff = dl.EntryPermissionsDiff(
            added=(dl.EntryPermissionGrant(subject="user-1", grant_type="acl_view", comment=cast(str, 123)),)
        )
    else:
        diff = dl.EntryPermissionsDiff(
            modified=(
                dl.EntryPermissionModification(
                    subject="user-1",
                    grant_type=invalid if case == "modified_grant" else "acl_view",
                    new_subject="user-2",
                    new_grant_type=invalid if case == "modified_new_grant" else "acl_edit",
                ),
            )
        )

    with pytest.raises(dl.DataLensValidationError, match="modifyPermissions"):
        _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=diff)
    assert recorder.requests == []


if TYPE_CHECKING:
    from datalens_sdk.client import PermissionsNamespace

    def _assert_permissions_types(client: dl.DataLensClientYC | dl.DataLensClientEnterprise) -> None:
        assert_type(client.permissions, PermissionsNamespace)
        permissions = client.permissions.entry_acl.get(entry_id="entry-1")
        assert_type(permissions, dl.EntryPermissions)
        assert_type(permissions.permissions, dl.EntryPermissionSet[dl.EntryPermissionParticipant])
        assert_type(permissions.pending_permissions, dl.EntryPermissionSet[dl.PendingEntryPermissionParticipant])
        assert_type(permissions.permissions.acl_view, tuple[dl.EntryPermissionParticipant, ...])
        assert_type(permissions.pending_permissions.acl_view, tuple[dl.PendingEntryPermissionParticipant, ...])
        result = client.permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff())
        assert_type(result, dl.EntryPermissionsModificationResult)
        assert_type(result.next_page_token, str | None)
        assert_type(result.continuation_required, bool)


@pytest.mark.parametrize("mode", ["replace", "merge"])
def test_copy_permissions_rejects_identical_ids_before_any_read(mode: Literal["replace", "merge"]) -> None:
    recorder = RecordedTransport()
    with pytest.raises(dl.DataLensValidationError, match="must differ"):
        _client(recorder).permissions.entry_acl.copy(source_entry_id="same", target_entry_id="same", mode=mode)
    assert recorder.requests == []


@pytest.mark.parametrize("operation", ["get", "modify"])
def test_permissions_reject_malformed_response(operation: str) -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(dl.InvalidResponseError) as error:
        _invoke(_client(recorder), operation)
    assert error.value.context.status_code == 502
    assert isinstance(error.value.__cause__, ValidationError)
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("diff", [None, {}, dl.EntryPermissionsDiff(added=(cast(dl.EntryPermissionGrant, {}),))])
def test_modify_permissions_rejects_untyped_diff_before_http(diff: object) -> None:
    recorder = RecordedTransport()
    with pytest.raises(dl.DataLensValidationError, match="modifyPermissions"):
        _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=cast(dl.EntryPermissionsDiff, diff))
    assert recorder.requests == []


def test_modify_permissions_does_not_repeat_after_invalid_json_response() -> None:
    recorder = RecordedTransport(
        httpx.Response(200, content=b"not JSON", headers={"x-request-id": "invalid-json"}),
        httpx.Response(200, json={"result": "ok"}),
    )
    with pytest.raises(dl.InvalidResponseError, match="not valid JSON") as error:
        _client(recorder).permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff())

    assert len(recorder.requests) == 1
    assert error.value.context.request_id == "invalid-json"
    assert isinstance(error.value.__cause__, ValueError)


def test_modify_permissions_does_not_repeat_after_timeout() -> None:
    requests: list[httpx.Request] = []
    original = httpx.ReadTimeout("response lost after dispatch")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise original

    with (
        dl.DataLensClientYC(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(handler)) as sdk,
        pytest.raises(dl.DataLensTransportError) as error,
    ):
        sdk.permissions.entry_acl.modify(entry_id="entry-1", diff=dl.EntryPermissionsDiff())

    assert len(requests) == 1
    assert error.value.__cause__ is original
    assert error.value.attempts == 1
