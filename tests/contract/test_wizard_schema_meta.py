from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.codegen import (
    WizardInventory,
    WizardRouteMeta,
    build_metadata,
    build_wizard_schema_meta,
    diff_wizard_schema_meta,
    wizard_schema_fingerprint,
)
from datalens_sdk.serialization.json_types import JsonValue

ROOT = Path(__file__).resolve().parents[2]


def _ref(name: str) -> dict[str, object]:
    return {"$ref": f"#/components/schemas/{name}"}


def _route(request_schema: str, result_schema: str | None) -> dict[str, object]:
    response_schema: dict[str, object] = _ref(result_schema) if result_schema is not None else {}
    return {
        "post": {
            "requestBody": {
                "content": {"application/json": {"schema": _ref(request_schema)}},
            },
            "responses": {
                "200": {
                    "content": {"application/json": {"schema": response_schema}},
                }
            },
        }
    }


def _tag_branch(tag: str, **properties: object) -> dict[str, object]:
    return {"properties": {"type": {"enum": [tag]}, **properties}, "required": ["type"]}


def _wizard_spec() -> dict[str, object]:
    schemas: dict[str, object] = {
        "CreateWizardChartV1Args": {
            "properties": {"data": _ref("WizardV1")},
            "required": ["data"],
            "type": "object",
        },
        "CreateWizardChartV1Result": {
            "properties": {"entry": _ref("WizardV1")},
            "required": ["entry"],
            "type": "object",
        },
        "DeleteWizardChartArgs": {
            "properties": {"chartId": {"type": "string"}},
            "required": ["chartId"],
            "type": "object",
        },
        "GetWizardChartV1Args": {
            "properties": {"chartId": {"type": "string"}},
            "required": ["chartId"],
            "type": "object",
        },
        "GetWizardChartV1Result": {
            "properties": {"entry": _ref("WizardV1")},
            "required": ["entry"],
            "type": "object",
        },
        "UpdateWizardV1Args": {
            "properties": {"chartId": {"type": "string"}, "data": _ref("WizardV1")},
            "required": ["data", "chartId"],
            "type": "object",
        },
        "UpdateWizardV1Result": {
            "properties": {"entry": _ref("WizardV1")},
            "required": ["entry"],
            "type": "object",
        },
        "WizardV1": {
            "description": "Ignored documentation.",
            "properties": {
                "annotation": _ref("EntryAnnotationArg"),
                "config": _ref("WizardV1ConfigSchema"),
                "key": {"anyOf": [{"type": "string"}, {"type": "null"}, {"type": "null"}]},
                "version": {"enum": [1], "type": "integer"},
            },
            "required": ["config", "version"],
            "type": "object",
        },
        "EntryAnnotationArg": {
            "properties": {"description": {"type": "string"}},
            "type": "object",
        },
        "WizardV1ConfigSchema": {
            "properties": {
                "visualization": {
                    "oneOf": [
                        _tag_branch("line"),
                        _tag_branch(
                            "geolayer",
                            layers={"items": _ref("WizardV1GeolayerLayerSchema"), "type": "array"},
                        ),
                        _tag_branch(
                            "combined-chart",
                            layers={"items": _ref("WizardV1CombinedChartLayerSchema"), "type": "array"},
                        ),
                    ]
                }
            },
            "required": ["visualization"],
            "type": "object",
        },
        "WizardV1GeolayerLayerSchema": {
            "oneOf": [_tag_branch("geopoint"), _tag_branch("heatmap")],
        },
        "WizardV1CombinedChartLayerSchema": {
            "oneOf": [_tag_branch("column"), _tag_branch("line")],
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Synthetic Wizard contract", "version": "3"},
        "paths": {
            "/rpc/createWizardChart": _route("CreateWizardChartV1Args", "CreateWizardChartV1Result"),
            "/rpc/deleteWizardChart": _route("DeleteWizardChartArgs", None),
            "/rpc/getWizardChart": _route("GetWizardChartV1Args", "GetWizardChartV1Result"),
            "/rpc/updateWizardChart": _route("UpdateWizardV1Args", "UpdateWizardV1Result"),
        },
        "components": {"schemas": schemas},
    }


def _object(value: JsonValue | None, *, path: str) -> dict[str, JsonValue]:
    assert isinstance(value, dict), f"{path} must be an object"
    return value


def _raw_object(value: object, *, path: str) -> dict[str, object]:
    assert isinstance(value, dict), f"{path} must be an object"
    assert all(isinstance(key, str) for key in value)
    return cast(dict[str, object], value)


def test_wizard_schema_meta_extracts_routes_and_structural_inventory() -> None:
    manifest = build_wizard_schema_meta(_wizard_spec())
    expected_inventory: WizardInventory = {
        "routes": 4,
        "roots": 7,
        "schemas": 12,
        "visualizations": 3,
        "geo_layers": 2,
        "combined_layers": 2,
    }
    expected_routes: dict[str, WizardRouteMeta] = {
        "/rpc/createWizardChart": {
            "method": "post",
            "request_schema": "CreateWizardChartV1Args",
            "result_schema": "CreateWizardChartV1Result",
            "request_body_required": False,
            "request_dto": "CreateWizardChartV1ArgsDTO",
            "result_dto": "CreateWizardChartV1ResultReadDTO",
        },
        "/rpc/deleteWizardChart": {
            "method": "post",
            "request_schema": "DeleteWizardChartArgs",
            "result_schema": None,
            "request_body_required": False,
            "request_dto": "DeleteWizardChartArgsDTO",
            "result_dto": None,
        },
        "/rpc/getWizardChart": {
            "method": "post",
            "request_schema": "GetWizardChartV1Args",
            "result_schema": "GetWizardChartV1Result",
            "request_body_required": False,
            "request_dto": "GetWizardChartV1ArgsDTO",
            "result_dto": "GetWizardChartV1ResultReadDTO",
        },
        "/rpc/updateWizardChart": {
            "method": "post",
            "request_schema": "UpdateWizardV1Args",
            "result_schema": "UpdateWizardV1Result",
            "request_body_required": False,
            "request_dto": "UpdateWizardV1ArgsDTO",
            "result_dto": "UpdateWizardV1ResultReadDTO",
        },
    }
    assert manifest["api_version"] == "3"
    assert manifest["wizard_version"] == 1
    assert manifest["inventory"] == expected_inventory
    assert manifest["routes"] == expected_routes
    assert manifest["visualizations"] == ["combined-chart", "geolayer", "line"]
    assert manifest["geo_layers"] == ["geopoint", "heatmap"]
    assert manifest["combined_layers"] == ["column", "line"]
    assert manifest["visualization_variants"] == {
        "combined-chart": "/schemas/WizardV1ConfigSchema/properties/visualization/oneOf/0",
        "geolayer": "/schemas/WizardV1ConfigSchema/properties/visualization/oneOf/1",
        "line": "/schemas/WizardV1ConfigSchema/properties/visualization/oneOf/2",
    }
    assert manifest["geo_layer_variants"] == {
        "geopoint": "/schemas/WizardV1GeolayerLayerSchema/oneOf/0",
        "heatmap": "/schemas/WizardV1GeolayerLayerSchema/oneOf/1",
    }
    assert manifest["combined_layer_variants"] == {
        "column": "/schemas/WizardV1CombinedChartLayerSchema/oneOf/0",
        "line": "/schemas/WizardV1CombinedChartLayerSchema/oneOf/1",
    }


def test_manifest_normalizes_non_structural_noise() -> None:
    spec = _wizard_spec()
    expected = build_wizard_schema_meta(spec)
    schemas = _raw_object(
        _raw_object(spec["components"], path="components")["schemas"],
        path="components.schemas",
    )
    wizard = _raw_object(schemas["WizardV1"], path="components.schemas.WizardV1")
    wizard["description"] = "Changed documentation."
    properties = _raw_object(wizard["properties"], path="components.schemas.WizardV1.properties")
    wizard["properties"] = dict(reversed(properties.items()))

    actual = build_wizard_schema_meta(spec)
    key_schema = _object(
        _object(actual["schemas"]["WizardV1"], path="schemas.WizardV1")["properties"],
        path="schemas.WizardV1.properties",
    )["key"]
    assert isinstance(key_schema, dict)
    key_branches = key_schema["anyOf"]
    assert isinstance(key_branches, list)
    assert key_branches.count({"type": "null"}) == 1
    assert actual == expected
    assert wizard_schema_fingerprint(actual) == wizard_schema_fingerprint(expected)


def test_manifest_diff_reports_nested_structural_changes() -> None:
    before = build_wizard_schema_meta(_wizard_spec())
    after = copy.deepcopy(before)
    wizard = _object(after["schemas"]["WizardV1"], path="schemas.WizardV1")
    properties = _object(wizard["properties"], path="schemas.WizardV1.properties")
    version = _object(properties["version"], path="schemas.WizardV1.properties.version")
    version["enum"] = [2]

    assert diff_wizard_schema_meta(before, after) == "~ /schemas/WizardV1/properties/version/enum: [1] -> [2]"


def test_build_metadata_accepts_an_explicit_wizard_spec(tmp_path: Path) -> None:
    wizard_spec = tmp_path / "wizard.json"
    wizard_spec.write_text(json.dumps(_wizard_spec()), encoding="utf-8")

    metadata = build_metadata(
        {"enterprise": ROOT / "spec" / "enterprise.json"},
        wizard_specs={"enterprise": wizard_spec},
    )

    wizard = metadata["installations"]["enterprise"]["wizard"]
    assert wizard["manifest"] == build_wizard_schema_meta(_wizard_spec())
    assert wizard["fingerprint"] == wizard_schema_fingerprint(wizard["manifest"])


def test_build_metadata_rejects_wizard_specs_for_unknown_installations(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown installations: yateam"):
        build_metadata(
            {"enterprise": ROOT / "spec" / "enterprise.json"},
            wizard_specs={"yateam": tmp_path / "wizard.json"},
        )
