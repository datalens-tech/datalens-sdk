from __future__ import annotations

from collections.abc import Callable
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


def _create_node_schema(
    schemas: dict[str, dict[str, object]],
    wire_type: str,
) -> dict[str, object]:
    mapping = _object(_entry_discriminator(schemas, "create")["mapping"])
    schema_ref = mapping[wire_type]
    assert isinstance(schema_ref, str)
    return _object(schemas[schema_ref.rsplit("/", 1)[-1]])


def _add_optional_create_tab(
    schemas: dict[str, dict[str, object]],
    tab: str,
    *,
    wire_type: str = "advanced-chart_node",
) -> None:
    create_schema = _create_node_schema(schemas, wire_type)
    data_schema = _object(_object(create_schema["properties"])["data"])
    _object(data_schema["properties"])[tab] = {"type": "string"}


def _require_create_tab(
    schemas: dict[str, dict[str, object]],
    tab: str,
    *,
    wire_type: str = "advanced-chart_node",
) -> None:
    create_schema = _create_node_schema(schemas, wire_type)
    data_schema = _object(_object(create_schema["properties"])["data"])
    required = data_schema.setdefault("required", [])
    assert isinstance(required, list)
    required.append(tab)


def _update_node_schema(
    schemas: dict[str, dict[str, object]],
    wire_type: str,
) -> dict[str, object]:
    mapping = _object(_entry_discriminator(schemas, "update")["mapping"])
    schema_ref = mapping[wire_type]
    assert isinstance(schema_ref, str)
    return _object(schemas[schema_ref.rsplit("/", 1)[-1]])


def _add_optional_update_tab(
    schemas: dict[str, dict[str, object]],
    tab: str,
    *,
    wire_type: str = "advanced-chart_node",
) -> None:
    update_schema = _update_node_schema(schemas, wire_type)
    data_schema = _object(_object(update_schema["properties"])["data"])
    _object(data_schema["properties"])[tab] = {"type": "string"}


def _require_update_tab(
    schemas: dict[str, dict[str, object]],
    tab: str,
    *,
    wire_type: str = "advanced-chart_node",
) -> None:
    update_schema = _update_node_schema(schemas, wire_type)
    data_schema = _object(_object(update_schema["properties"])["data"])
    required = data_schema.setdefault("required", [])
    assert isinstance(required, list)
    required.append(tab)


def _retain_update_wire_types(schemas: dict[str, dict[str, object]], *wire_types: str) -> None:
    mapping = _object(_entry_discriminator(schemas, "update")["mapping"])
    for wire_type in set(mapping) - set(wire_types):
        del mapping[wire_type]


def _metadata(first: codegen.ChartMeta, second: codegen.ChartMeta) -> codegen.Metadata:
    return cast(
        codegen.Metadata,
        {
            "installations": {
                "first": {"charts": first},
                "second": {"charts": second},
            }
        },
    )


def test_editor_metadata_allows_a_read_superset_without_opening_writes() -> None:
    schemas = _schemas()
    read_mapping = _object(_entry_discriminator(schemas, "read")["mapping"])
    read_mapping["legacy_read_only"] = "#/components/schemas/EditorTableNode"

    metadata = codegen._chart_meta(schemas)

    assert "legacy_read_only" in metadata["editor_read_nodes"]
    assert "legacy_read_only" not in metadata["editor_nodes"]
    assert "legacy_read_only" not in metadata["editor_update_nodes"]


def test_editor_update_tabs_are_bound_to_their_installation() -> None:
    first_schemas = _schemas()
    second_schemas = _schemas()
    _retain_update_wire_types(first_schemas, "advanced-chart_node")
    _retain_update_wire_types(second_schemas, "markdown_node")
    _add_optional_update_tab(first_schemas, "first_only")
    _add_optional_update_tab(second_schemas, "second_only", wire_type="markdown_node")
    first = codegen._chart_meta(first_schemas)
    second = codegen._chart_meta(second_schemas)

    emitted = codegen._emit_chart_dto(_metadata(first, second))

    first_tabs = sorted(first["editor_update_nodes"]["advanced-chart_node"]["data_fields"])
    second_tabs = sorted(second["editor_update_nodes"]["markdown_node"]["data_fields"])
    expected = f"""INSTALLATION_EDITOR_UPDATE_TABS_BY_WIRE_TYPE: dict[str, dict[str, frozenset[str]]] = {{
    'first': {{
        'advanced-chart_node': frozenset({first_tabs!r}),
    }},
    'second': {{
        'markdown_node': frozenset({second_tabs!r}),
    }},
}}"""
    assert expected in emitted


@pytest.mark.parametrize("emitter", [codegen._emit_chart_dto, codegen.emit_chart_builders], ids=["dto", "builders"])
@pytest.mark.parametrize("drift", ["fields", "requiredness"])
def test_editor_create_generation_rejects_installation_specific_shared_wire_type(
    emitter: Callable[[codegen.Metadata], str],
    drift: str,
) -> None:
    first_schemas = _schemas()
    second_schemas = _schemas()
    if drift == "fields":
        _add_optional_create_tab(second_schemas, "second_only")
    else:
        _add_optional_create_tab(first_schemas, "shared_tab")
        _add_optional_create_tab(second_schemas, "shared_tab")
        _require_create_tab(second_schemas, "shared_tab")
    first = codegen._chart_meta(first_schemas)
    second = codegen._chart_meta(second_schemas)

    with pytest.raises(ValueError, match="incompatible data fields or requiredness") as exc_info:
        emitter(_metadata(first, second))

    message = str(exc_info.value)
    assert "Editor create wire type 'advanced-chart_node'" in message
    assert "'first'" in message
    assert "'second'" in message
    assert "Per-installation Editor create DTOs and builders are not supported" in message


@pytest.mark.parametrize("drift", ["fields", "requiredness"])
def test_editor_update_dto_generation_rejects_installation_specific_shared_wire_type(drift: str) -> None:
    first_schemas = _schemas()
    second_schemas = _schemas()
    if drift == "fields":
        _add_optional_update_tab(second_schemas, "second_only")
    else:
        _add_optional_update_tab(first_schemas, "shared_tab")
        _add_optional_update_tab(second_schemas, "shared_tab")
        _require_update_tab(second_schemas, "shared_tab")
    first = codegen._chart_meta(first_schemas)
    second = codegen._chart_meta(second_schemas)

    with pytest.raises(ValueError, match="incompatible data fields or requiredness") as exc_info:
        codegen._emit_chart_dto(_metadata(first, second))

    message = str(exc_info.value)
    assert "'advanced-chart_node'" in message
    assert "'first'" in message
    assert "'second'" in message
    assert "Per-installation Editor update DTOs are not supported" in message


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
