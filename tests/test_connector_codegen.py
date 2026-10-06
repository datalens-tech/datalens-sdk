from __future__ import annotations

import ast
from typing import cast

from datalens_sdk.codegen import ConnectorMeta, InstallationMetadata, emit_builder_module


def test_builder_generator_emits_valid_annotation_for_null_only_enum() -> None:
    connector: ConnectorMeta = {
        "schema": "NullableConnector",
        "required": [],
        "available_fields": ["auth_type"],
        "fields": {"auth_type": {"type": "enum"}},
        "defaults": {},
        "enum_restrictions": {"auth_type": [None]},
    }
    metadata = cast(InstallationMetadata, {"connectors": {"nullable": connector}})

    generated = emit_builder_module("yacloud", metadata)
    module = ast.parse(generated)
    builder = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "NullableConnectionCreate"
    )
    method = next(node for node in builder.body if isinstance(node, ast.FunctionDef) and node.name == "auth_type")

    annotation = method.args.args[1].annotation
    assert isinstance(annotation, ast.Constant)
    assert annotation.value is None
