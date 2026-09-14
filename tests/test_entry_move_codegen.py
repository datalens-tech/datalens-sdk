import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[1]


def _load_spec(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _write_spec(tmp_path: Path, spec: dict[str, object], name: str) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


def _move_result_schema(spec: dict[str, object]) -> dict[str, object]:
    schemas = cast(dict[str, dict[str, object]], cast(dict[str, object], spec["components"])["schemas"])
    return schemas["MoveEntryResultEntry"]


def test_entry_move_read_dto_follows_openapi(tmp_path: Path) -> None:
    spec = _load_spec("yacloud")
    properties = cast(dict[str, dict[str, object]], _move_result_schema(spec)["properties"])
    properties["futureField"] = {"type": "string"}
    generated = codegen.emit_dto(codegen.build_metadata({"yacloud": _write_spec(tmp_path, spec, "yacloud")}))
    block = generated.split("class MoveEntryResultEntryReadDTO", 1)[1].split("class EntryRenameDTO", 1)[0]

    assert "future_field: str" in block
    assert "scope: str" in block
    assert "Literal[" not in block
    assert "extra='ignore'" in block


def test_entry_move_codegen_rejects_installation_schema_drift(tmp_path: Path) -> None:
    installations: dict[str, Path] = {}
    for name in ("enterprise", "yacloud"):
        spec = _load_spec(name)
        if name == "enterprise":
            properties = cast(dict[str, dict[str, object]], _move_result_schema(spec)["properties"])
            properties["futureField"] = {"type": "string"}
        installations[name] = _write_spec(tmp_path, spec, name)

    with pytest.raises(ValueError, match="moveFolderEntry schemas differ"):
        codegen.build_metadata(installations)


def test_entry_move_codegen_rejects_missing_installation_route(tmp_path: Path) -> None:
    spec = _load_spec("yacloud")
    paths = cast(dict[str, object], spec["paths"])
    del paths["/rpc/moveFolderEntry"]

    with pytest.raises(ValueError, match="moveFolderEntry is missing"):
        codegen.build_metadata({"yacloud": _write_spec(tmp_path, spec, "yacloud")})
