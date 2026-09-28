from __future__ import annotations

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
ROUTE = "/rpc/getRevisions"


def _load_spec(name: str = "yacloud") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _schemas(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], cast(dict[str, object], spec["components"])["schemas"])


def _properties(schema: dict[str, object]) -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], schema["properties"])


def _write_spec(tmp_path: Path, spec: dict[str, object], name: str = "yacloud") -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


def _generate(spec: dict[str, object], tmp_path: Path) -> str:
    return codegen.emit_dto(codegen.build_metadata({"yacloud": _write_spec(tmp_path, spec)}))


@pytest.fixture(scope="module")
def revision_dto_module(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    path = tmp_path_factory.mktemp("entry-revisions-dto") / "dto.py"
    path.write_text(
        codegen.emit_dto(
            codegen.build_metadata({name: ROOT / "spec" / f"{name}.json" for name in ("enterprise", "yacloud")})
        )
    )
    module_name = "_entry_revisions_codegen_test_dto"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_entry_revisions_dto_fields_and_constraints_follow_openapi(tmp_path: Path) -> None:
    spec = _load_spec()
    schemas = _schemas(spec)
    request = _properties(schemas["GetRevisionsArgs"])
    request["pageSize"]["maximum"] = 500
    request["pageSize"]["default"] = 250
    request["traceId"] = {"type": "string"}
    entries = _properties(schemas["GetRevisionsResult"])["entries"]
    item = cast(dict[str, object], entries["items"])
    _properties(item)["futureFlag"] = {"type": "boolean"}

    block = _generate(spec, tmp_path).split("class EntryRevisionsRequestDTO", 1)[1]

    assert "page_size: Annotated[int, Field(ge=1, le=500, alias='pageSize')] = 250" in block
    assert "trace_id: str" in block
    assert "class EntryRevisionReadDTO(BaseModel):" in block
    assert "future_flag: bool" in block
    assert "rev_ids: Annotated[list[str], Field(min_length=1, max_length=1000, alias='revIds')]" in block


@pytest.mark.parametrize("published_limit", [200, 1000])
def test_entry_revisions_page_size_compatibility_preserves_source_contract(
    tmp_path: Path, published_limit: int
) -> None:
    spec = _load_spec()
    page_size = _properties(_schemas(spec)["GetRevisionsArgs"])["pageSize"]
    page_size.update(default=published_limit, maximum=published_limit)
    metadata = codegen.build_metadata({"yacloud": _write_spec(tmp_path, spec)})
    original_metadata = json.dumps(metadata, sort_keys=True)

    block = codegen.emit_dto(metadata).split("class EntryRevisionsRequestDTO", 1)[1]

    assert "page_size: Annotated[int, Field(ge=1, le=200, alias='pageSize')] = 200" in block
    assert json.dumps(metadata, sort_keys=True) == original_metadata


@pytest.mark.parametrize("name", ["enterprise", "yacloud"])
def test_entry_revisions_codegen_requires_route(tmp_path: Path, name: str) -> None:
    spec = _load_spec(name)
    del cast(dict[str, object], spec["paths"])[ROUTE]

    with pytest.raises(ValueError, match="getRevisions is missing"):
        codegen.build_metadata({name: _write_spec(tmp_path, spec, name)})


@pytest.mark.parametrize("schema_name", ["GetRevisionsArgs", "GetRevisionsResult"])
def test_entry_revisions_codegen_requires_schema_roots(tmp_path: Path, schema_name: str) -> None:
    spec = _load_spec()
    del _schemas(spec)[schema_name]

    with pytest.raises(ValueError, match=f"getRevisions schema graph references missing component '{schema_name}'"):
        codegen.build_metadata({"yacloud": _write_spec(tmp_path, spec)})


def test_entry_revisions_codegen_requires_expected_route_roots(tmp_path: Path) -> None:
    spec = _load_spec()
    route = cast(dict[str, object], cast(dict[str, object], spec["paths"])[ROUTE])
    post = cast(dict[str, object], route["post"])
    body = cast(dict[str, object], post["requestBody"])
    content = cast(dict[str, dict[str, object]], body["content"])
    content["application/json"]["schema"] = {"$ref": "#/components/schemas/GetEntriesRelationsArgs"}

    with pytest.raises(ValueError, match="/rpc/getRevisions must use"):
        codegen.build_metadata({"yacloud": _write_spec(tmp_path, spec)})


def test_entry_revisions_codegen_rejects_installation_schema_drift(tmp_path: Path) -> None:
    enterprise = _load_spec("enterprise")
    _properties(_schemas(enterprise)["GetRevisionsArgs"])["pageSize"]["maximum"] = 500
    installations = {
        "enterprise": _write_spec(tmp_path, enterprise, "enterprise"),
        "yacloud": _write_spec(tmp_path, _load_spec(), "yacloud"),
    }

    with pytest.raises(ValueError, match="getRevisions schemas differ"):
        codegen.build_metadata(installations)


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("#/components/schemas/MissingRevision", "missing component 'MissingRevision'"),
        ("https://example.test/revision.json", "local"),
    ],
)
def test_entry_revisions_codegen_rejects_unresolvable_schema_refs(
    tmp_path: Path,
    reference: str,
    message: str,
) -> None:
    spec = _load_spec()
    _properties(_schemas(spec)["GetRevisionsResult"])["entries"]["items"] = {"$ref": reference}

    with pytest.raises(ValueError, match=message):
        _generate(spec, tmp_path)


def test_entry_revisions_codegen_rejects_unsupported_constraints(tmp_path: Path) -> None:
    spec = _load_spec()
    _properties(_schemas(spec)["GetRevisionsArgs"])["revIds"]["uniqueItems"] = True

    with pytest.raises(ValueError, match=r"Unsupported behavior-bearing getRevisions schema feature.*uniqueItems"):
        _generate(spec, tmp_path)


@pytest.mark.parametrize("page_size", [1, 200])
def test_entry_revisions_request_dto_preserves_defaults_and_wire_fields(
    revision_dto_module: ModuleType,
    page_size: int,
) -> None:
    request = revision_dto_module.EntryRevisionsRequestDTO.model_validate({"entryId": "entry-1"})
    assert request.page_size == 200
    assert request.model_dump(by_alias=True, exclude_none=True) == {"entryId": "entry-1", "pageSize": 200}
    request = revision_dto_module.EntryRevisionsRequestDTO.model_validate(
        {"entryId": "entry-1", "pageSize": page_size, "pageToken": "", "revIds": ["revision-1"]}
    )
    assert request.model_dump(by_alias=True, exclude_unset=True) == {
        "entryId": "entry-1",
        "pageSize": page_size,
        "pageToken": "",
        "revIds": ["revision-1"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"entryId": "entry-1", "pageSize": True},
        {"entryId": "entry-1", "pageSize": 0},
        {"entryId": "entry-1", "pageSize": 201},
        {"entryId": "entry-1", "pageSize": 1000},
        {"entryId": "entry-1", "pageSize": 1001},
        {"entryId": "entry-1", "pageSize": "100"},
        {"entryId": "entry-1", "pageToken": None},
        {"entryId": "entry-1", "revIds": []},
        {"entryId": "entry-1", "revIds": ["revision-1"] * 1001},
        {"entryId": "entry-1", "revIds": [123]},
        {"entryId": "entry-1", "revIds": "revision-1"},
        {"entryId": "entry-1", "revIds": None},
        {"entryId": "entry-1", "unknown": True},
    ],
)
def test_entry_revisions_request_dto_rejects_invalid_wire_values(
    revision_dto_module: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        revision_dto_module.EntryRevisionsRequestDTO.model_validate(payload)


def _revision() -> dict[str, object]:
    return {
        "revId": "revision-1",
        "updatedAt": "not a datetime",
        "updatedBy": "user-1",
        "isSaved": True,
        "isPublished": True,
    }


def test_entry_revisions_read_dto_ignores_unknown_fields_and_preserves_values(revision_dto_module: ModuleType) -> None:
    result = revision_dto_module.EntryRevisionsReadDTO.model_validate(
        {"entries": [{**_revision(), "unknown": "ignored"}], "unknown": "ignored"}
    )
    assert result.next_page_token is None
    assert result.entries[0].updated_at == "not a datetime"
    assert result.entries[0].is_saved is True
    assert result.entries[0].is_published is True
    assert result.entries[0].model_dump(by_alias=True) == _revision()


@pytest.mark.parametrize("field", ["revId", "updatedAt", "updatedBy", "isSaved", "isPublished"])
@pytest.mark.parametrize("invalid_value", ["missing", None, 0])
def test_entry_revisions_read_dto_requires_typed_revision_fields(
    revision_dto_module: ModuleType,
    field: str,
    invalid_value: object,
) -> None:
    item = _revision()
    if invalid_value == "missing":
        del item[field]
    else:
        item[field] = invalid_value
    with pytest.raises(ValidationError):
        revision_dto_module.EntryRevisionsReadDTO.model_validate({"entries": [item]})


@pytest.mark.parametrize("payload", [{}, {"entries": None}, {"entries": [], "nextPageToken": None}])
def test_entry_revisions_read_dto_rejects_invalid_envelopes(
    revision_dto_module: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        revision_dto_module.EntryRevisionsReadDTO.model_validate(payload)
