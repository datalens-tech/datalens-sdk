from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[1]


def _load_spec(installation: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{installation}.json").read_text()))


def _update_data_schema(spec: dict[str, object]) -> dict[str, object]:
    paths = cast(dict[str, object], spec["paths"])
    route = cast(dict[str, object], paths["/rpc/updateDataset"])
    post = cast(dict[str, object], route["post"])
    request = cast(dict[str, object], post["requestBody"])
    content = cast(dict[str, object], request["content"])
    json_content = cast(dict[str, object], content["application/json"])
    schema = cast(dict[str, object], json_content["schema"])
    properties = cast(dict[str, object], schema["properties"])
    return cast(dict[str, object], properties["data"])


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
def test_dataset_update_codegen_recovers_exported_optional_mode_without_mutating_spec(installation: str) -> None:
    spec = _load_spec(installation)
    original = deepcopy(spec)

    assert codegen.dataset_update_modes(spec) == ["publish", "save"]
    assert spec == original


@pytest.mark.parametrize("inline", [False, True])
def test_dataset_update_codegen_accepts_corrected_openapi_mode_property(inline: bool) -> None:
    spec = _load_spec("yacloud")
    data = _update_data_schema(spec)
    data.pop("mode")
    components = cast(dict[str, object], spec["components"])
    schemas = cast(dict[str, object], components["schemas"])
    dataset_update = cast(dict[str, object], schemas["DatasetUpdate"])
    properties = cast(dict[str, object], dataset_update["properties"])
    properties["mode"] = {"type": "string", "enum": ["save", "publish"]}
    if inline:
        data.clear()
        data.update(dataset_update)

    assert codegen.dataset_update_modes(spec) == ["publish", "save"]


def test_dataset_update_codegen_rejects_unrecognized_mode_contract() -> None:
    spec = _load_spec("yacloud")
    data = _update_data_schema(spec)
    data["mode"] = {"type": "string", "enum": ["save", "invalid"]}

    with pytest.raises(ValueError, match="must support save and publish"):
        codegen.dataset_update_modes(spec)


def test_generated_dataset_update_data_envelope_preserves_optional_mode(tmp_path: Path) -> None:
    spec = _load_spec("yacloud")
    path = tmp_path / "yacloud.json"
    path.write_text(json.dumps(spec))
    metadata = codegen.build_metadata({"yacloud": path})

    assert metadata["dataset_update_modes"] == ["publish", "save"]
    generated = codegen.emit_dto(metadata)
    update_data = generated.split("class DatasetUpdateDataDTO", 1)[1].split("class EntryMoveDTO", 1)[0]
    assert "mode: Literal['publish', 'save'] | None = None" in update_data
    assert "if self.mode is not None:" in update_data
    assert 'payload["mode"] = self.mode' in update_data
    assert 'extra="forbid"' in update_data
    assert "data: DatasetUpdateDataDTO" in update_data
