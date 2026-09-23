from __future__ import annotations

from collections.abc import Mapping
from functools import partial
import json
from typing import TYPE_CHECKING, cast

import httpx
from pydantic import ValidationError
import pytest
from typing_extensions import assert_type

import datalens_sdk as dl


class Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self.responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, request.url.path
        return self.responses.pop(0)

    def body(self, i: int = 0) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.requests[i].content))


def client(recorder: Recorder) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(
        auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(recorder.handler)
    )


def binding(subject: str = "user-1") -> dict[str, object]:
    return {
        "subjectClaims": {"sub": subject, "subType": "USER_ACCOUNT", "email": "display@example.test"},
        "accessBindings": [{"roleId": "verified-role", "inheritedFrom": None}],
        "inheritedAccessBindings": [
            {"roleId": "inherited-role", "inheritedFrom": {"id": "ancestor", "type": "custom-kind"}}
        ],
    }


def page(*subjects: str, token: str = "") -> httpx.Response:
    return httpx.Response(200, json={"subjectsWithBindings": [binding(s) for s in subjects], "nextPageToken": token})


def receipt(done: bool = False) -> dict[str, object]:
    return {
        "id": "operation-1",
        "description": "Role change",
        "createdBy": "executor",
        "createdAt": {"seconds": "1720000000", "nanos": 123},
        "modifiedAt": {"seconds": "1720000001"},
        "metadata": {"opaque": {"nested": [1, False, None, "x"]}},
        "done": done,
    }


@pytest.mark.parametrize("family", ["workbook", "collection", "shared_entry"])
@pytest.mark.parametrize("inherited", [None, False, True])
def test_bindings_lazy_paging_preserves_options_and_claims(family: str, inherited: bool | None) -> None:
    recorder = Recorder(page("one", token="p2"), page(token="p3"), page("two"))
    api = client(recorder).permissions
    if family == "workbook":
        pager = api.workbook.list(workbook_id="resource", include_inherited=inherited, page_size=1)
        key, path = "workbookId", "listWorkbookAccessBindings"
    elif family == "collection":
        pager = api.collection.list(collection_id="resource", include_inherited=inherited, page_size=1)
        key, path = "collectionId", "listCollectionAccessBindings"
    else:
        pager = api.shared_entry.list(entry_id="resource", include_inherited=inherited, page_size=1)
        key, path = "entryId", "listSharedEntryAccessBindings"
    assert recorder.requests == []
    values = tuple(pager)
    assert [s.subject_claims.sub for s in values] == ["one", "two"]
    first = values[0]
    assert first.access_bindings == (dl.RoleAssignment(role_id="verified-role", inherited_from=None),)
    assert first.inherited_access_bindings[0].inherited_from == dl.BindingOrigin(id="ancestor", type="custom-kind")
    expected: dict[str, object] = {key: "resource", "pageSize": 1}
    if inherited is not None:
        expected["getInheritedBindings"] = inherited
    assert [recorder.body(i) for i in range(3)] == [
        expected,
        {**expected, "pageToken": "p2"},
        {**expected, "pageToken": "p3"},
    ]
    assert all(r.url.path == "/rpc/" + path for r in recorder.requests)


@pytest.mark.parametrize("tokens", [("repeat", "repeat"), ("first", "second", "first")])
def test_binding_page_token_cycle_rejected_before_bad_page_is_yielded(tokens: tuple[str, ...]) -> None:
    recorder = Recorder(*(page(str(i), token=t) for i, t in enumerate(tokens)))
    iterator = iter(client(recorder).permissions.workbook.list(workbook_id="w"))
    for i in range(len(tokens) - 1):
        assert next(iterator).subject_claims.sub == str(i)
    with pytest.raises(dl.InvalidResponseError, match="repeated") as error:
        next(iterator)
    assert error.value.context.status_code == 502
    assert len(recorder.requests) == len(tokens)


def test_bindings_later_page_failure_stays_partial_and_reiteration_starts_over() -> None:
    recorder = Recorder(
        page("first", token="next"),
        httpx.Response(403, json={"message": "denied"}, headers={"x-request-id": "later-page"}),
        page("fresh"),
    )
    pager = client(recorder).permissions.collection.list(collection_id="c")
    iterator = iter(pager)
    assert next(iterator).subject_claims.sub == "first"
    with pytest.raises(dl.ForbiddenError) as error:
        next(iterator)
    assert error.value.context.request_id == "later-page"
    assert [s.subject_claims.sub for s in pager] == ["fresh"]
    assert recorder.body(2) == {"collectionId": "c"}


@pytest.mark.parametrize(
    "response", [{}, {"subjectsWithBindings": []}, {"subjectsWithBindings": [], "nextPageToken": None}]
)
def test_binding_malformed_page_raises_dto_validation_error(response: object) -> None:
    recorder = Recorder(httpx.Response(200, json=response))
    with pytest.raises(dl.DTOValidationError, match="listWorkbookAccessBindings") as error:
        tuple(client(recorder).permissions.workbook.list(workbook_id="w"))
    assert error.value.context.status_code == 502
    assert isinstance(error.value.__cause__, ValidationError)
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("done", [False, True])
@pytest.mark.parametrize("family", ["workbook", "collection"])
def test_role_write_preserves_order_duplicates_and_operation_receipt(family: str, done: bool) -> None:
    recorder = Recorder(httpx.Response(200, json=receipt(done)))
    api = client(recorder).permissions
    subject = dl.RoleSubject(id="verified-id", type="federatedUser")
    add = dl.RoleBindingDelta(action="ADD", role_id="opaque.role", subject=subject)
    remove = dl.RoleBindingDelta(action="REMOVE", role_id="opaque.role", subject=subject)
    if family == "workbook":
        result = api.workbook.modify(workbook_id="w", deltas=[add, remove, add])
        key, identity = "workbookId", "w"
    else:
        result = api.collection.modify(collection_id="c", deltas=[add, remove, add])
        key, identity = "collectionId", "c"
    assert result.done is done
    assert result.created_at == dl.OperationTimestamp(seconds="1720000000", nanos=123)
    assert result.modified_at.nanos is None
    assert result.metadata == {"opaque": {"nested": [1, False, None, "x"]}}
    assert recorder.body() == {
        key: identity,
        "deltas": [
            {
                "action": action,
                "accessBinding": {"roleId": "opaque.role", "subject": {"id": "verified-id", "type": "federatedUser"}},
            }
            for action in ["ADD", "REMOVE", "ADD"]
        ],
    }
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "500", "malformed"])
@pytest.mark.parametrize("family", ["workbook", "collection"])
def test_role_write_errors_do_not_repeat(family: str, failure: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("response lost after dispatch", request=request)
        if failure == "500":
            return httpx.Response(
                500,
                json={"code": "SERVER.ORIGINAL", "message": "opaque", "details": {"key": "value"}},
                headers={"x-request-id": "write-500"},
            )
        return httpx.Response(200, json={"done": True})

    sdk = dl.DataLensClientYC(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(handler))
    if family == "workbook":
        modify = partial(sdk.permissions.workbook.modify, workbook_id="w", deltas=[])
    else:
        modify = partial(sdk.permissions.collection.modify, collection_id="c", deltas=[])
    with pytest.raises(dl.DataLensError) as error:
        modify()
    assert len(requests) == 1
    if failure == "timeout":
        assert isinstance(error.value, dl.DataLensTransportError)
        assert isinstance(error.value.__cause__, httpx.ReadTimeout)
    elif failure == "500":
        assert isinstance(error.value, dl.ServerError)
        assert error.value.context.status_code == 500
        assert error.value.context.code == "SERVER.ORIGINAL"
        assert error.value.context.details == {"key": "value"}
        assert error.value.context.request_id == "write-500"
        assert isinstance(error.value.__cause__, httpx.HTTPStatusError)
    else:
        assert isinstance(error.value, dl.DTOValidationError)
        assert error.value.context.status_code == 502
        assert isinstance(error.value.__cause__, ValidationError)


def test_local_invalid_role_subject_and_binding_id_rejected_without_http() -> None:
    recorder = Recorder()
    api = client(recorder).permissions
    with pytest.raises(dl.DataLensValidationError, match="listWorkbookAccessBindings"):
        api.workbook.list(workbook_id=cast(str, None))
    bad = dl.RoleSubject(id="x", type=cast(dl.RoleSubjectType, "USER_ACCOUNT"))
    with pytest.raises(dl.DataLensValidationError, match="updateCollectionAccessBindings"):
        api.collection.modify(
            collection_id="c", deltas=[dl.RoleBindingDelta(action="ADD", role_id="role", subject=bad)]
        )
    assert recorder.requests == []


def test_effective_entries_keep_false_error_and_missing_id_distinct() -> None:
    raw = {
        "yes": {"permissions": {"read": False, "edit": False, "admin": False, "execute": False}},
        "gone": {"error": "NOT_FOUND"},
    }
    recorder = Recorder(httpx.Response(200, json=raw))
    api = client(recorder).permissions.effective
    ids = ["yes", "gone", "omitted"]
    result = api.get_entries(entry_ids=ids)
    assert result["gone"] == dl.EffectivePermissionError(error="NOT_FOUND")
    actual = result["yes"]
    assert isinstance(actual, dl.EntryEffectivePermissionResult)
    assert actual.permissions.read is False
    assert "omitted" not in result
    assert recorder.body() == {"entryIds": ids}


def test_effective_bulk_preserves_independent_maps_and_absent_projections() -> None:
    recorder = Recorder(
        httpx.Response(
            200,
            json={
                "entries": {"same": {}, "error": {"error": "NOT_FOUND"}},
                "workbooks": {"same": {}},
                "collections": {"same": {"error": "NOT_FOUND"}},
            },
        )
    )
    result = client(recorder).permissions.effective.get_bulk(entry_ids=["same", "error", "missing"])
    assert result.entries["same"] == dl.BulkEntryEffectivePermissionResult()
    assert result.workbooks["same"] == dl.WorkbookEffectivePermissionResult()
    assert result.collections["same"] == dl.EffectivePermissionError(error="NOT_FOUND")
    assert "missing" not in result.entries
    assert recorder.body() == {"entryIds": ["same", "error", "missing"]}


@pytest.mark.parametrize("family", ["entries", "workbooks", "collections"])
@pytest.mark.parametrize("item", [{"error": "OTHER"}, {"error": "OTHER", "permissions": {}}, {"permissions": None}])
def test_effective_bulk_rejects_unknown_errors_and_explicit_null(family: str, item: object) -> None:
    response: dict[str, object] = {"entries": {}, "workbooks": {}, "collections": {}}
    response[family] = {"id": item}
    recorder = Recorder(httpx.Response(200, json=response))
    with pytest.raises(dl.DTOValidationError, match="getPermissionsBulk"):
        client(recorder).permissions.effective.get_bulk()
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("ids", [[], ["id"] * 1001])
@pytest.mark.parametrize("family", ["entry_ids", "workbook_ids", "collection_ids"])
def test_bulk_limits_are_local_validation(family: str, ids: list[str]) -> None:
    recorder = Recorder()
    api = client(recorder).permissions.effective
    with pytest.raises(dl.DataLensValidationError):
        api.get_bulk(**{family: ids})
    assert recorder.requests == []


def test_bulk_empty_query_and_basic_empty_list_are_preserved() -> None:
    recorder = Recorder(
        httpx.Response(200, json={"entries": {}, "workbooks": {}, "collections": {}}), httpx.Response(200, json={})
    )
    api = client(recorder).permissions.effective
    api.get_bulk()
    api.get_entries(entry_ids=[])
    assert [recorder.body(i) for i in range(2)] == [{}, {"entryIds": []}]


def test_root_and_suggestions_have_distinct_wire_roots() -> None:
    recorder = Recorder(
        httpx.Response(200, json={"createCollectionInRoot": False, "createWorkbookInRoot": True}),
        httpx.Response(200, json=[{}, {"title": "Display only"}, {"name": "opaque-id"}]),
    )
    api = client(recorder).permissions
    assert api.effective.get_root_collection() == dl.RootCollectionPermissions(
        create_collection_in_root=False, create_workbook_in_root=True
    )
    suggestions = api.entry_acl.suggest_subjects(search_text="text")
    assert suggestions == (
        dl.EntryPermissionSubject(),
        dl.EntryPermissionSubject(title="Display only"),
        dl.EntryPermissionSubject(name="opaque-id"),
    )
    assert recorder.body(1) == {"searchText": "text"}


def test_directory_is_lazy_paginated_and_preserves_opaque_federation() -> None:
    member = {
        "sub": "system-id",
        "subType": "_system",
        "email": "",
        "name": "Display",
        "givenName": "",
        "familyName": "",
        "preferredUsername": "",
        "federation": {"opaque": [True, None]},
        "idpType": None,
    }
    recorder = Recorder(
        httpx.Response(200, json={"members": [], "nextPageToken": "next"}),
        httpx.Response(200, json={"members": [member], "nextPageToken": ""}),
    )
    pager = client(recorder).permissions.list_subjects(
        search="", filter="opaque filter", language="ru", subject_type="_system", page_size=1
    )
    assert recorder.requests == []
    subjects = tuple(pager)
    assert subjects[0].federation == {"opaque": [True, None]}
    assert subjects[0].sub_type == "_system"
    assert recorder.body() == {
        "search": "",
        "filter": "opaque filter",
        "language": "ru",
        "tabId": "_system",
        "pageSize": 1,
    }
    assert recorder.body(1) == {**recorder.body(), "pageToken": "next"}


if TYPE_CHECKING:

    def assert_signatures(sdk: dl.DataLensClientYC | dl.DataLensClientEnterprise) -> None:
        assert_type(sdk.permissions.workbook.list(workbook_id="id"), dl.Pager[dl.SubjectRoleAssignments])
        assert_type(sdk.permissions.collection.list(collection_id="id"), dl.Pager[dl.SubjectRoleAssignments])
        assert_type(sdk.permissions.shared_entry.list(entry_id="id"), dl.Pager[dl.SubjectRoleAssignments])
        assert_type(sdk.permissions.list_subjects(), dl.Pager[dl.DirectorySubject])
        assert_type(
            sdk.permissions.entry_acl.suggest_subjects(search_text="name"), tuple[dl.EntryPermissionSubject, ...]
        )
        assert_type(sdk.permissions.workbook.modify(workbook_id="id", deltas=[]), dl.DataLensOperation)
        assert_type(
            sdk.permissions.effective.get_entries(entry_ids=[]),
            Mapping[str, dl.EntryEffectivePermissionResult | dl.EffectivePermissionError],
        )
        assert_type(sdk.permissions.effective.get_bulk(), dl.BulkPermissionsResult)
        assert_type(sdk.permissions.effective.get_root_collection(), dl.RootCollectionPermissions)


@pytest.mark.parametrize("invalid_id", [None, 123])
@pytest.mark.parametrize("invalid_target", [False, True])
def test_acl_copy_validates_both_ids_before_reading_either(invalid_id: object, invalid_target: bool) -> None:
    recorder = Recorder()
    with pytest.raises(dl.DataLensValidationError, match="must be strings"):
        client(recorder).permissions.entry_acl.copy(
            source_entry_id="source" if invalid_target else cast(str, invalid_id),
            target_entry_id=cast(str, invalid_id) if invalid_target else "target",
            mode="merge",
        )
    assert recorder.requests == []


def test_bindings_preserve_duplicate_subjects_across_pages() -> None:
    recorder = Recorder(page("same", token="next"), page("same"))
    subjects = tuple(client(recorder).permissions.workbook.list(workbook_id="w"))
    assert [subject.subject_claims.sub for subject in subjects] == ["same", "same"]
    assert len(recorder.requests) == 2


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (None, dl.DTOValidationError),
        ([], dl.InvalidResponseError),
        ({}, dl.DTOValidationError),
        ({"members": []}, dl.DTOValidationError),
    ],
)
def test_directory_rejects_malformed_page(response: object, error_type: type[dl.DataLensAPIError]) -> None:
    recorder = Recorder(httpx.Response(200, json=response))
    with pytest.raises(error_type):
        tuple(client(recorder).permissions.list_subjects())
    assert len(recorder.requests) == 1


def test_directory_repeated_token_does_not_yield_malformed_page() -> None:
    recorder = Recorder(
        httpx.Response(200, json={"members": [], "nextPageToken": "same"}),
        httpx.Response(200, json={"members": [], "nextPageToken": "same"}),
    )
    pages = client(recorder).permissions.list_subjects().pages()
    assert next(pages).next_page_token == "same"
    with pytest.raises(dl.InvalidResponseError, match="repeated nextPageToken") as error:
        next(pages)
    assert error.value.context.status_code == 502
    assert len(recorder.requests) == 2


@pytest.mark.parametrize("bad_delta", [None, {"action": "ADD", "role_id": "role"}])
@pytest.mark.parametrize("family", ["workbook", "collection"])
def test_invalid_delta_shape_is_local_validation(family: str, bad_delta: object) -> None:
    recorder = Recorder()
    api = client(recorder).permissions
    deltas = [cast(dl.RoleBindingDelta, bad_delta)]
    if family == "workbook":
        modify = partial(api.workbook.modify, workbook_id="w", deltas=deltas)
    else:
        modify = partial(api.collection.modify, collection_id="c", deltas=deltas)
    with pytest.raises(dl.DataLensValidationError, match="AccessBindings") as error:
        modify()
    assert error.value.__cause__ is not None
    assert recorder.requests == []


@pytest.mark.parametrize(
    "subject",
    [
        None,
        {"id": "user", "type": "userAccount"},
        dl.BindingSubjectClaims(sub="claim", sub_type="USER_ACCOUNT", email="display@example.test"),
    ],
)
def test_role_write_requires_explicit_role_subject(subject: object) -> None:
    recorder = Recorder()
    delta = dl.RoleBindingDelta(action="ADD", role_id="role", subject=cast(dl.RoleSubject, subject))
    with pytest.raises(dl.DataLensValidationError, match="RoleSubject"):
        client(recorder).permissions.workbook.modify(workbook_id="w", deltas=[delta])
    assert recorder.requests == []


def test_missing_delta_sequence_is_local_validation() -> None:
    recorder = Recorder()
    with pytest.raises(dl.DataLensValidationError, match="updateCollectionAccessBindings") as error:
        client(recorder).permissions.collection.modify(collection_id="c", deltas=cast(list[dl.RoleBindingDelta], None))
    assert isinstance(error.value.__cause__, TypeError)
    assert recorder.requests == []


@pytest.mark.parametrize("ids", [None, "singleton-is-not-a-sequence-of-ids", 123])
def test_effective_invalid_id_sequence_is_local_validation(ids: object) -> None:
    recorder = Recorder()
    api = client(recorder).permissions.effective
    with pytest.raises(dl.DataLensValidationError) as error:
        api.get_entries(entry_ids=cast(list[str], ids))
    assert error.value.__cause__ is not None
    assert recorder.requests == []


class _InjectedHTTPClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def post_json(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: dl.RetryPolicy = dl.DEFAULT_RETRY_POLICY,
        accept_response: dl.ResponseAcceptancePredicate | None = None,
    ) -> object | None:
        self.paths.append(path)
        return [{"name": "user-1"}]

    def post_json_object(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: dl.RetryPolicy = dl.DEFAULT_RETRY_POLICY,
        accept_response: dl.ResponseAcceptancePredicate | None = None,
    ) -> dict[str, object]:
        raise AssertionError("Subject suggestions return an array")


def test_subject_suggestions_support_injected_http_client() -> None:
    injected = _InjectedHTTPClient()
    with dl.DataLensClientYC(http_client=injected) as sdk:
        subjects = sdk.permissions.entry_acl.suggest_subjects(search_text="user")

    assert subjects == (dl.EntryPermissionSubject(name="user-1"),)
    assert injected.paths == ["/rpc/dlsSuggest"]
