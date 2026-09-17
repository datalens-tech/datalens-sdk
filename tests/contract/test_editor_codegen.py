from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[2]


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _schemas() -> dict[str, dict[str, object]]:
    spec = _object(json.loads((ROOT / "spec" / "enterprise.json").read_text()))
    components = _object(spec["components"])
    return cast(dict[str, dict[str, object]], deepcopy(_object(components["schemas"])))


def _entry_discriminator(schemas: dict[str, dict[str, object]], operation: str) -> dict[str, object]:
    if operation == "read":
        schema = _object(schemas["GetEditorChartResult"])
        entry = _object(_object(schema["properties"])["entry"])
        return _object(entry["discriminator"])
    if operation == "create":
        schema = _object(schemas["CreateEditorChartArgs"])
        entry = _object(_object(schema["properties"])["entry"])
        all_of = entry["allOf"]
        assert isinstance(all_of, list)
        return _object(_object(all_of[0])["discriminator"])
    assert operation == "update"
    schema = _object(schemas["UpdateEditorChartArgs"])
    entry = _object(_object(schema["properties"])["entry"])
    return _object(entry["discriminator"])


def _add_optional_update_tab(schemas: dict[str, dict[str, object]], tab: str) -> None:
    update_schema = _object(schemas["UpdateEditorAdvancedChartNodeEntry"])
    data_schema = _object(_object(update_schema["properties"])["data"])
    _object(data_schema["properties"])[tab] = {"type": "string"}


def test_editor_metadata_allows_a_read_superset_without_opening_writes() -> None:
    schemas = _schemas()
    read_mapping = _object(_entry_discriminator(schemas, "read")["mapping"])
    read_mapping["legacy_read_only"] = "#/components/schemas/EditorTableNode"

    metadata = codegen._chart_meta(schemas)

    assert "legacy_read_only" in metadata["editor_read_nodes"]
    assert "legacy_read_only" not in metadata["editor_nodes"]
    assert "legacy_read_only" not in metadata["editor_update_nodes"]


def test_editor_update_tabs_remain_nested_by_installation() -> None:
    first_schemas = _schemas()
    second_schemas = _schemas()
    _add_optional_update_tab(first_schemas, "first_only")
    _add_optional_update_tab(second_schemas, "second_only")
    first = codegen._chart_meta(first_schemas)
    second = codegen._chart_meta(second_schemas)
    metadata = cast(
        codegen.Metadata,
        {
            "installations": {
                "first": {"charts": first},
                "second": {"charts": second},
            }
        },
    )

    emitted = codegen._emit_chart_dto(metadata)

    first_tabs = sorted(first["editor_update_nodes"]["advanced-chart_node"]["data_fields"])
    second_tabs = sorted(second["editor_update_nodes"]["advanced-chart_node"]["data_fields"])
    assert f"        'advanced-chart_node': frozenset({first_tabs!r})," in emitted
    assert f"        'advanced-chart_node': frozenset({second_tabs!r})," in emitted
    assert "'first': {" in emitted
    assert "'second': {" in emitted


def test_editor_discriminator_requires_type_property() -> None:
    schemas = _schemas()
    _entry_discriminator(schemas, "read")["propertyName"] = "kind"

    with pytest.raises(ValueError, match=r"propertyName must be 'type'"):
        codegen._chart_meta(schemas)


def test_editor_discriminator_rejects_missing_schema_reference() -> None:
    schemas = _schemas()
    mapping = _object(_entry_discriminator(schemas, "update")["mapping"])
    mapping["missing_node"] = "#/components/schemas/MissingEditorNode"

    with pytest.raises(ValueError, match="references missing schema 'MissingEditorNode'"):
        codegen._chart_meta(schemas)


def test_editor_create_and_update_types_must_be_readable() -> None:
    schemas = _schemas()
    read_mapping = _object(_entry_discriminator(schemas, "read")["mapping"])
    del read_mapping["advanced-chart_node"]

    with pytest.raises(ValueError, match="Editor create types are missing from the read discriminator"):
        codegen._chart_meta(schemas)
