import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import cast

from pydantic import ValidationError
import pytest

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ("/rpc/getPermissions", "/rpc/modifyPermissions")


def _load_spec(name: str = "yacloud") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _schemas(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    components = cast(dict[str, object], spec["components"])
    return cast(dict[str, dict[str, object]], components["schemas"])


def _write_spec(tmp_path: Path, spec: dict[str, object], name: str = "yacloud") -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


@pytest.mark.parametrize("missing_routes", [(ROUTES[0],), (ROUTES[1],), ROUTES])
def test_permissions_codegen_requires_both_routes(missing_routes: tuple[str, ...]) -> None:
    spec = _load_spec()
    for route in missing_routes:
        del cast(dict[str, object], spec["paths"])[route]

    with pytest.raises(ValueError, match="Permissions contract is missing routes"):
        codegen.build_permissions_contract_meta(spec)


@pytest.mark.parametrize("schema_name", ["GetPermissionsArgs", "DlsPermissionParticipant"])
def test_permissions_codegen_rejects_missing_schema_components(schema_name: str) -> None:
    spec = _load_spec()
    del _schemas(spec)[schema_name]

    with pytest.raises(ValueError, match=f"missing component '{schema_name}'"):
        codegen.build_permissions_contract_meta(spec)


def test_permissions_codegen_rejects_wrong_route_roots() -> None:
    spec = _load_spec()
    paths = cast(dict[str, object], spec["paths"])
    route = cast(dict[str, object], paths[ROUTES[0]])
    operation = cast(dict[str, object], route["post"])
    body = cast(dict[str, object], operation["requestBody"])
    content = cast(dict[str, object], body["content"])
    media = cast(dict[str, object], content["application/json"])
    media["schema"] = {"$ref": "#/components/schemas/ModifyPermissionsArgs"}

    with pytest.raises(ValueError, match=r"Permissions route .* must reference"):
        codegen.build_permissions_contract_meta(spec)


def test_permissions_codegen_rejects_installation_schema_drift(tmp_path: Path) -> None:
    enterprise = _load_spec("enterprise")
    participant = _schemas(enterprise)["DlsPermissionParticipant"]
    properties = cast(dict[str, dict[str, object]], participant["properties"])
    properties["futureFlag"] = {"type": "boolean"}

    with pytest.raises(ValueError, match="Permissions schemas differ"):
        codegen.build_metadata(
            {
                "enterprise": _write_spec(tmp_path, enterprise, "enterprise"),
                "yacloud": ROOT / "spec" / "yacloud.json",
            }
        )


def test_permissions_codegen_preserves_upstream_required_metadata() -> None:
    metadata = codegen.build_metadata(
        {installation: ROOT / "spec" / f"{installation}.json" for installation in ("enterprise", "yacloud")}
    )
    expected_required = ["approver", "description", "extras", "kind", "name", "requester", "subject"]
    for installation in ("enterprise", "yacloud"):
        assert _schemas(_load_spec(installation))["DlsPermissionParticipant"]["required"] == expected_required
    participant = cast(dict[str, object], metadata["permissions"]["schemas"]["DlsPermissionParticipant"])
    assert participant["required"] == expected_required
    original = json.dumps(metadata, sort_keys=True)

    codegen.emit_dto(metadata)

    assert json.dumps(metadata, sort_keys=True) == original


def test_permissions_codegen_rejects_unimplemented_schema_semantics() -> None:
    spec = _load_spec()
    args = _schemas(spec)["ModifyPermissionsArgs"]
    properties = cast(dict[str, dict[str, object]], args["properties"])
    properties["entryId"]["pattern"] = "^[a-z]+$"

    with pytest.raises(ValueError, match=r"Unsupported behavior-bearing Permissions schema feature .*pattern"):
        codegen.build_permissions_contract_meta(spec)


@pytest.fixture(scope="module")
def permissions_dto_module(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    path = tmp_path_factory.mktemp("permissions-dto") / "synthetic_permissions_dto.py"
    metadata = codegen.build_metadata({"yacloud": ROOT / "spec" / "yacloud.json"})
    path.write_text(codegen.emit_dto(metadata))
    name = f"synthetic_permissions_dto_{path.parent.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_permissions_generated_requests_preserve_wire_diff(permissions_dto_module: ModuleType) -> None:
    payload = {
        "entryId": "entry-1",
        "nested": False,
        "body": {
            "diff": {
                "added": {"acl_execute": [{"subject": "group", "comment": ""}]},
                "removed": {"acl_adm": [{"subject": "former-admin"}]},
                "modified": {
                    "acl_view": [
                        {
                            "subject": "previous-subject",
                            "comment": "reason",
                            "new": {"subject": "replacement-subject", "grantType": "acl_edit"},
                        }
                    ]
                },
            }
        },
    }
    parsed = permissions_dto_module.ModifyPermissionsArgsDTO.model_validate(payload)

    assert parsed.model_dump(mode="json", by_alias=True, exclude_unset=True) == payload
    assert permissions_dto_module.GetPermissionsArgsDTO(entry_id="entry-1").model_dump(
        mode="json", by_alias=True, exclude_unset=True
    ) == {"entryId": "entry-1"}


@pytest.mark.parametrize(
    "payload",
    [
        {"entryId": "entry", "body": {"diff": {}}, "future": True},
        {"entryId": "entry", "body": {"diff": {"future": {}}}},
        {"entryId": "entry", "body": {"diff": {"added": {"acl_view": [{"subject": 42}]}}}},
        {
            "entryId": "entry",
            "body": {"diff": {"added": {"acl_view": [{"subject": "user", "comment": None}]}}},
        },
        {
            "entryId": "entry",
            "body": {"diff": {"modified": {"acl_view": [{"subject": "user", "new": {"grantType": "acl_edit"}}]}}},
        },
        {
            "entryId": "entry",
            "body": {
                "diff": {
                    "modified": {"acl_view": [{"subject": "user", "new": {"subject": "user", "grantType": "admin"}}]}
                }
            },
        },
    ],
)
def test_permissions_generated_requests_reject_invalid_nested_writes(
    permissions_dto_module: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        permissions_dto_module.ModifyPermissionsArgsDTO.model_validate(payload)


def test_permissions_generated_reads_keep_subject_aliases_and_ignore_extras(
    permissions_dto_module: ModuleType,
) -> None:
    subject = {
        "name": "subject-profile-id",
        "__rlsid": "rls-id",
        "__source": "staff",
        "parent": {"link": "parent-link", "title": "parent-title", "future": True},
        "future": "value",
    }
    participant = {
        "name": "permission-subject-id",
        "kind": "group",
        "description": "requested access",
        "extras": {"initial_on_create": False, "future": True},
        "subject": subject,
        "requester": subject,
        "approver": subject,
        "future": True,
    }
    parsed = permissions_dto_module.GetPermissionsResultReadDTO.model_validate(
        {
            "editable": False,
            "permissions": {"acl_adm": [participant], "future": []},
            "pendingPermissions": {"acl_adm": [{**participant, "approver": None}]},
            "future": True,
        }
    )

    granted = parsed.permissions.acl_adm[0]
    pending = parsed.pending_permissions.acl_adm[0]
    assert granted.name == "permission-subject-id"
    assert granted.subject.name == "subject-profile-id"
    assert granted.subject.rls_id == "rls-id"
    assert granted.subject.source == "staff"
    assert granted.requester.rls_id == "rls-id"
    assert granted.approver.source == "staff"
    assert granted.extras.initial_on_create is False
    assert pending.approver is None
    assert pending.requester.rls_id == "rls-id"
    assert granted.subject.model_dump(by_alias=True, exclude_unset=True) == {
        "name": "subject-profile-id",
        "__rlsid": "rls-id",
        "__source": "staff",
        "parent": {"link": "parent-link", "title": "parent-title"},
    }


def test_permissions_generated_reads_distinguish_optional_and_required_fields(
    permissions_dto_module: ModuleType,
) -> None:
    payload = {"editable": False, "permissions": {}, "pendingPermissions": {}}
    parsed = permissions_dto_module.GetPermissionsResultReadDTO.model_validate(payload)
    assert parsed.model_dump(by_alias=True, exclude_unset=True) == payload

    with pytest.raises(ValidationError):
        permissions_dto_module.GetPermissionsResultReadDTO.model_validate({"editable": False})
    with pytest.raises(ValidationError):
        permissions_dto_module.DlsPermissionPendingParticipantReadDTO.model_validate(
            {
                "name": "user",
                "kind": "user",
                "description": "",
                "extras": None,
                "subject": {},
                "requester": None,
                "approver": {},
            }
        )


def test_permissions_generated_reads_allow_only_omitted_granted_metadata(
    permissions_dto_module: ModuleType,
) -> None:
    participant: dict[str, object] = {
        "name": "user",
        "kind": "user",
        "subject": {},
        "requester": None,
        "approver": None,
    }
    granted = permissions_dto_module.DlsPermissionParticipantReadDTO.model_validate(participant)
    assert granted.description is None
    assert granted.extras is None
    assert granted.model_dump(by_alias=True, exclude_unset=True) == participant

    for invalid_metadata in (
        {"description": None},
        {"description": 42},
        {"extras": "invalid"},
        {"extras": {"initial_on_create": None}},
    ):
        with pytest.raises(ValidationError):
            permissions_dto_module.DlsPermissionParticipantReadDTO.model_validate(participant | invalid_metadata)

    with pytest.raises(ValidationError) as error:
        permissions_dto_module.DlsPermissionPendingParticipantReadDTO.model_validate(participant)
    assert {item["loc"] for item in error.value.errors()} == {("description",), ("extras",)}


@pytest.mark.parametrize("token", [None, "next-page", ""])
def test_permissions_generated_result_preserves_continuation(
    permissions_dto_module: ModuleType,
    token: str | None,
) -> None:
    payload = {"result": "ok", **({"nextPageToken": token} if token is not None else {})}
    parsed = permissions_dto_module.ModifyPermissionsResultReadDTO.model_validate(payload)
    assert parsed.model_dump(by_alias=True, exclude_unset=True) == payload

    with pytest.raises(ValidationError):
        permissions_dto_module.ModifyPermissionsResultReadDTO.model_validate({"result": "error"})
