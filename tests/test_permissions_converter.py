from __future__ import annotations

from typing import cast

from pydantic import ValidationError
import pytest

from datalens_sdk.converter.permissions import (
    AccessBindingsConverter,
    DirectorySubjectsConverter,
    EffectivePermissionsConverter,
)
from datalens_sdk.domain.permissions import (
    BindingOrigin,
    BulkEntryEffectivePermissionResult,
    CollectionEffectivePermissionResult,
    EffectivePermissionError,
    EntryEffectivePermissionResult,
    EntryEffectivePermissions,
    RoleAssignment,
    RoleBindingDelta,
    RoleSubject,
    RoleSubjectType,
    WorkbookEffectivePermissionResult,
)


def test_bindings_keep_claims_direct_inherited_and_unknown_origin_type() -> None:
    page = AccessBindingsConverter.list_result(
        {
            "subjectsWithBindings": [
                {
                    "subjectClaims": {"sub": "claim-id", "subType": "USER_ACCOUNT", "email": "", "future": True},
                    "accessBindings": [{"roleId": "role-direct", "inheritedFrom": None}],
                    "inheritedAccessBindings": [
                        {"roleId": "role-parent", "inheritedFrom": {"id": "ancestor", "type": "future-container"}}
                    ],
                }
            ],
            "nextPageToken": "continuation",
        }
    )
    assert page.next_page_token == "continuation"
    subject = page.subjects[0]
    assert subject.subject_claims.sub == "claim-id"
    assert subject.subject_claims.email == ""
    assert subject.access_bindings == (RoleAssignment(role_id="role-direct", inherited_from=None),)
    assert subject.inherited_access_bindings == (
        RoleAssignment(role_id="role-parent", inherited_from=BindingOrigin(id="ancestor", type="future-container")),
    )


@pytest.mark.parametrize("missing", ["sub", "subType", "email"])
def test_binding_claims_require_authoritative_fields(missing: str) -> None:
    claims = {"sub": "id", "subType": "USER_ACCOUNT", "email": ""}
    del claims[missing]
    with pytest.raises(ValidationError):
        AccessBindingsConverter.list_result(
            {
                "subjectsWithBindings": [
                    {"subjectClaims": claims, "accessBindings": [], "inheritedAccessBindings": []}
                ],
                "nextPageToken": "",
            }
        )


@pytest.mark.parametrize("include", [None, False, True])
def test_binding_payload_preserves_omission_and_false(include: bool | None) -> None:
    options = {} if include is None else {"getInheritedBindings": include}
    assert AccessBindingsConverter.list_workbook_payload("wb", include_inherited=include) == {
        "workbookId": "wb",
        **options,
    }
    assert AccessBindingsConverter.list_collection_payload("col", include_inherited=include) == {
        "collectionId": "col",
        **options,
    }
    assert AccessBindingsConverter.list_shared_entry_payload("entry", include_inherited=include) == {
        "entryId": "entry",
        **options,
    }
    assert AccessBindingsConverter.list_workbook_payload("wb", page_token="", page_size=0) == {
        "workbookId": "wb",
        "pageToken": "",
        "pageSize": 0,
    }


def test_role_deltas_preserve_order_duplicates_and_explicit_write_identity() -> None:
    subject = RoleSubject(id="verified-id", type="federatedUser")
    add = RoleBindingDelta(action="ADD", role_id="custom-role", subject=subject)
    remove = RoleBindingDelta(action="REMOVE", role_id="custom-role", subject=subject)
    deltas = [add, remove, add]
    expected = [
        {
            "action": action,
            "accessBinding": {
                "roleId": "custom-role",
                "subject": {"id": "verified-id", "type": "federatedUser"},
            },
        }
        for action in ("ADD", "REMOVE", "ADD")
    ]
    assert AccessBindingsConverter.modify_workbook_payload("wb", deltas) == {"workbookId": "wb", "deltas": expected}
    assert AccessBindingsConverter.modify_collection_payload("col", deltas) == {
        "collectionId": "col",
        "deltas": expected,
    }


@pytest.mark.parametrize("subject_type", ["USER_ACCOUNT", "_system", "user", ""])
def test_read_subject_types_cannot_be_used_as_write_types(subject_type: str) -> None:
    with pytest.raises(ValidationError):
        AccessBindingsConverter.modify_workbook_payload(
            "wb",
            [
                RoleBindingDelta(
                    action="ADD",
                    role_id="role",
                    subject=RoleSubject(id="id", type=cast(RoleSubjectType, subject_type)),
                )
            ],
        )


@pytest.mark.parametrize("done", [False, True])
def test_operation_receipt_preserves_opaque_metadata_and_timestamp_precision(done: bool) -> None:
    metadata = {"nested": {"items": [None, 9007199254740993, False, 0.25, "value"]}, "empty": {}}
    result = AccessBindingsConverter.modify_result(
        {
            "id": "operation",
            "description": "",
            "createdBy": "creator",
            "createdAt": {"seconds": "9007199254740993", "nanos": 999999999},
            "modifiedAt": {"seconds": "9007199254740994"},
            "metadata": metadata,
            "done": done,
            "future": True,
        }
    )
    assert result.metadata == metadata
    assert result.created_at.seconds == "9007199254740993"
    assert result.created_at.nanos == 999999999
    assert isinstance(result.created_at.nanos, int)
    assert result.modified_at.nanos is None
    assert result.done is done


def test_directory_preserves_opaque_federation_and_distinct_system_claim() -> None:
    page = DirectorySubjectsConverter.list_result(
        {
            "members": [
                {
                    "sub": "id",
                    "subType": "_system",
                    "email": "",
                    "name": "display",
                    "givenName": "",
                    "familyName": "",
                    "preferredUsername": "",
                    "federation": {"id": "federation", "extension": [False, None]},
                    "idpType": None,
                }
            ],
            "nextPageToken": "",
        }
    )
    assert page.subjects[0].sub_type == "_system"
    assert page.subjects[0].federation == {"id": "federation", "extension": [False, None]}
    assert page.subjects[0].picture is None
    assert DirectorySubjectsConverter.list_payload(
        search="", filter="opaque", language="ru", subject_type="_system"
    ) == {
        "search": "",
        "filter": "opaque",
        "language": "ru",
        "tabId": "_system",
    }
    assert DirectorySubjectsConverter.list_payload() == {}


def test_effective_basic_preserves_false_errors_and_omitted_ids() -> None:
    payload = {
        "present": {"permissions": {"execute": False, "read": False, "edit": False, "admin": False}, "future": True},
        "missing": {"error": "NOT_FOUND", "permissions": {"execute": True, "read": True, "edit": True, "admin": True}},
    }
    expected = {
        "present": EntryEffectivePermissionResult(
            permissions=EntryEffectivePermissions(execute=False, read=False, edit=False, admin=False)
        ),
        "missing": EffectivePermissionError(error="NOT_FOUND"),
    }
    assert EffectivePermissionsConverter.entries_result(payload) == expected
    assert EffectivePermissionsConverter.entries_payload([]) == {"entryIds": []}


def test_bulk_effective_preserves_absent_projections_errors_and_maps() -> None:
    result = EffectivePermissionsConverter.bulk_result(
        {
            "entries": {"same-id": {}, "missing": {"error": "NOT_FOUND"}},
            "workbooks": {"same-id": {}, "missing": {"error": "NOT_FOUND"}},
            "collections": {"same-id": {}, "missing": {"error": "NOT_FOUND"}},
        }
    )
    assert result.entries["same-id"] == BulkEntryEffectivePermissionResult()
    assert result.workbooks["same-id"] == WorkbookEffectivePermissionResult()
    assert result.collections["same-id"] == CollectionEffectivePermissionResult()
    assert (
        result.entries["missing"]
        == result.workbooks["missing"]
        == result.collections["missing"]
        == EffectivePermissionError(error="NOT_FOUND")
    )
    assert "omitted" not in result.entries


@pytest.mark.parametrize("family", ["entries", "workbooks", "collections"])
@pytest.mark.parametrize("error", ["FUTURE_ERROR", None, False])
def test_bulk_effective_rejects_unknown_error_before_tolerant_success(family: str, error: object) -> None:
    payload: dict[str, object] = {"entries": {}, "workbooks": {}, "collections": {}}
    payload[family] = {"id": {"error": error}}
    with pytest.raises(ValidationError):
        EffectivePermissionsConverter.bulk_result(payload)


@pytest.mark.parametrize("family", ["entry_ids", "workbook_ids", "collection_ids"])
@pytest.mark.parametrize("size", [0, 1001])
def test_bulk_limits_apply_to_each_supplied_array(family: str, size: int) -> None:
    if family == "entry_ids":
        with pytest.raises(ValidationError):
            EffectivePermissionsConverter.bulk_payload(entry_ids=["id"] * size)
    elif family == "workbook_ids":
        with pytest.raises(ValidationError):
            EffectivePermissionsConverter.bulk_payload(workbook_ids=["id"] * size)
    else:
        with pytest.raises(ValidationError):
            EffectivePermissionsConverter.bulk_payload(collection_ids=["id"] * size)


def test_bulk_accepts_omitted_and_independently_bounded_arrays() -> None:
    assert EffectivePermissionsConverter.bulk_payload() == {}
    ids = ["id"] * 1000
    assert EffectivePermissionsConverter.bulk_payload(entry_ids=ids, workbook_ids=ids, collection_ids=ids) == {
        "entryIds": ids,
        "workbookIds": ids,
        "collectionIds": ids,
    }
    assert EffectivePermissionsConverter.entries_payload([*ids, "extra"])["entryIds"] == [*ids, "extra"]


def test_root_projection_has_only_creation_flags() -> None:
    result = EffectivePermissionsConverter.root_result(
        {"createCollectionInRoot": False, "createWorkbookInRoot": True, "future": True}
    )
    assert result.create_collection_in_root is False
    assert result.create_workbook_in_root is True


def test_bulk_projects_all_resource_specific_flags() -> None:
    common = {
        "listAccessBindings": False,
        "updateAccessBindings": True,
        "limitedView": False,
        "view": True,
        "update": False,
        "copy": True,
        "move": False,
        "delete": True,
    }
    result = EffectivePermissionsConverter.bulk_result(
        {
            "entries": {
                "id": {"fullPermissions": {**common, "createEntryBinding": False, "createLimitedEntryBinding": True}}
            },
            "workbooks": {"id": {"permissions": {**common, "publish": True, "embed": False}}},
            "collections": {
                "id": {
                    "permissions": {
                        **common,
                        "createSharedEntry": False,
                        "createCollection": True,
                        "createWorkbook": False,
                    }
                }
            },
        }
    )
    entry = result.entries["id"]
    workbook = result.workbooks["id"]
    collection = result.collections["id"]
    assert isinstance(entry, BulkEntryEffectivePermissionResult)
    assert isinstance(workbook, WorkbookEffectivePermissionResult)
    assert isinstance(collection, CollectionEffectivePermissionResult)
    assert entry.permissions is None
    assert entry.full_permissions is not None
    assert entry.full_permissions.copy is True
    assert entry.full_permissions.create_limited_entry_binding is True
    assert workbook.permissions is not None
    assert workbook.permissions.copy is True
    assert workbook.permissions.embed is False
    assert collection.permissions is not None
    assert collection.permissions.copy is True
    assert collection.permissions.create_collection is True


@pytest.mark.parametrize("page_size", [0.5, "2", True])
def test_public_pagination_size_rejects_non_integer_counts(page_size: object) -> None:
    with pytest.raises(ValueError, match="page_size must be an integer"):
        AccessBindingsConverter.list_workbook_payload("wb", page_size=cast(int, page_size))
    with pytest.raises(ValueError, match="page_size must be an integer"):
        DirectorySubjectsConverter.list_payload(page_size=cast(int, page_size))


@pytest.mark.parametrize("page_size", [0, -1, 1000001])
def test_public_pagination_size_does_not_invent_schema_bounds(page_size: int) -> None:
    assert DirectorySubjectsConverter.list_payload(page_size=page_size) == {"pageSize": page_size}
