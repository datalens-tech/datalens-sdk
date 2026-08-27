import ast
import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[1]


def _load_spec(name: str = "yacloud") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _dataset_data_schemas(spec: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    paths = cast(dict[str, object], spec["paths"])
    route = cast(dict[str, object], paths["/rpc/getDatasetData"])
    post = cast(dict[str, object], route["post"])
    request_body = cast(dict[str, object], post["requestBody"])
    request_content = cast(dict[str, object], request_body["content"])
    request_json = cast(dict[str, object], request_content["application/json"])
    responses = cast(dict[str, object], post["responses"])
    response = cast(dict[str, object], responses["200"])
    response_content = cast(dict[str, object], response["content"])
    response_json = cast(dict[str, object], response_content["application/json"])
    return cast(dict[str, object], request_json["schema"]), cast(dict[str, object], response_json["schema"])


def _write_spec(tmp_path: Path, spec: dict[str, object], name: str = "yacloud") -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


def _dataset_data_block(spec_path: Path) -> str:
    emitted = codegen.emit_dto(codegen.build_metadata({"yacloud": spec_path}))
    return emitted.split("class DatasetDataArgs", 1)[1].split("class DatasetValidateDTO", 1)[0]


def test_dataset_data_dto_fields_and_types_follow_openapi(tmp_path: Path) -> None:
    spec = _load_spec()
    request_schema, response_schema = _dataset_data_schemas(spec)
    request_properties = cast(dict[str, dict[str, object]], request_schema["properties"])
    request_properties["traceId"] = {"type": "string"}

    response_properties = cast(dict[str, dict[str, object]], response_schema["properties"])
    column_schema = cast(dict[str, object], response_properties["schema"]["items"])
    column_properties = cast(dict[str, dict[str, object]], column_schema["properties"])
    column_properties["formatHint"] = {"type": ["string", "null"]}
    cast(list[str], column_properties["type"]["enum"]).append("future_type")

    block = _dataset_data_block(_write_spec(tmp_path, spec))

    assert "DTO(BaseModel):" in block
    assert "trace_id: str" in block
    assert "format_hint: None | str" in block or "format_hint: str | None" in block
    assert "type: str" in block
    assert "'future_type'" not in block
    assert "workbook_id" not in block
    assert "le=100000" in block
    assert "columns: list[" in block
    assert "alias='schema'" in block


def test_dataset_data_codegen_resolves_local_schema_refs(tmp_path: Path) -> None:
    spec = _load_spec()
    _, response_schema = _dataset_data_schemas(spec)
    response_properties = cast(dict[str, dict[str, object]], response_schema["properties"])
    schema_array = response_properties["schema"]
    column_schema = cast(dict[str, object], schema_array["items"])
    components = cast(dict[str, object], spec["components"])
    schemas = cast(dict[str, object], components["schemas"])
    schemas["DatasetDataColumn"] = column_schema
    schema_array["items"] = {"$ref": "#/components/schemas/DatasetDataColumn"}

    block = _dataset_data_block(_write_spec(tmp_path, spec))

    assert "class DatasetDataColumnReadDTO(BaseModel):" in block
    assert "guid: Annotated[str, Field(min_length=1)]" in block
    assert "type: str" in block


@pytest.mark.parametrize(
    ("reference", "component", "message"),
    [
        ("#/components/schemas/MissingDatasetDataColumn", None, "missing"),
        ("https://example.test/schemas.json#DatasetDataColumn", None, "local"),
        (
            "#/components/schemas/DatasetDataColumn",
            {"$ref": "#/components/schemas/DatasetDataColumn"},
            "Recursive",
        ),
    ],
)
def test_dataset_data_codegen_rejects_unresolvable_schema_refs(
    tmp_path: Path,
    reference: str,
    component: dict[str, object] | None,
    message: str,
) -> None:
    spec = _load_spec()
    _, response_schema = _dataset_data_schemas(spec)
    response_properties = cast(dict[str, dict[str, object]], response_schema["properties"])
    response_properties["schema"]["items"] = {"$ref": reference}
    if component is not None:
        components = cast(dict[str, object], spec["components"])
        schemas = cast(dict[str, object], components["schemas"])
        schemas["DatasetDataColumn"] = component

    spec_path = _write_spec(tmp_path, spec)
    with pytest.raises(ValueError, match=message):
        codegen.emit_dto(codegen.build_metadata({"yacloud": spec_path}))


def test_dataset_data_codegen_rejects_installation_schema_drift(tmp_path: Path) -> None:
    installations: dict[str, Path] = {}
    for name in ("enterprise", "yacloud"):
        spec = _load_spec(name)
        if name == "enterprise":
            request_schema, _ = _dataset_data_schemas(spec)
            properties = cast(dict[str, dict[str, object]], request_schema["properties"])
            properties["future"] = {"type": "string"}
        installations[name] = _write_spec(tmp_path, spec, name)

    with pytest.raises(ValueError, match="getDatasetData schemas differ"):
        codegen.build_metadata(installations)


def test_dataset_data_codegen_uses_shared_pydantic_emitter() -> None:
    source = ast.parse((ROOT / "src" / "datalens_sdk" / "codegen.py").read_text())
    emitter_classes = [
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and "DatasetData" in node.name and "Emitter" in node.name
    ]
    assert emitter_classes == []
