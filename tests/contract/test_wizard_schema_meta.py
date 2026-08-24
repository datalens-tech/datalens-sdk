from __future__ import annotations

from collections.abc import Callable
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast, get_args

from pydantic import ValidationError
import pytest

from datalens_sdk._runtime.method_specs import (
    METHOD_SPECS,
    MethodSpec,
    method_requires_generated_structure,
    resolve_method_carriers,
)
from datalens_sdk._runtime.wizard_structure import WizardValueStructure, WizardVisualizationStructure
from datalens_sdk.codegen import (
    Metadata,
    WizardInventory,
    WizardRouteMeta,
    _method_is_supported_by_structure,
    build_metadata,
    build_wizard_field_structure,
    build_wizard_schema_meta,
    build_wizard_visualization_structure,
    diff_wizard_schema_meta,
    emit_chart_builders,
    emit_dto,
    wizard_schema_fingerprint,
)
from datalens_sdk.converter.wizard.converter import (
    WizardChartDtoModule,
    validate_wizard_generated_contract,
)
from datalens_sdk.domain.chart_types import CombinedLayerType, GeoLayerType
from datalens_sdk.errors import DataLensConfigurationError
from datalens_sdk.serialization.json_types import JsonValue

ROOT = Path(__file__).resolve().parents[2]
_PRE_DASHBOARD_EMITTER_WIZARD_BLOCK_SHA256 = "6cc64e2f4b2b4150e6548563d80b414929b8ab3c902e21e81a0c1ed5754c4561"


class _PayloadDTO(Protocol):
    def to_payload(self) -> dict[str, object]: ...


def _build_metadata(*, installation_spec: Path | None = None) -> Metadata:
    return build_metadata({"enterprise": installation_spec or ROOT / "spec" / "enterprise.json"})


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


def _tag_branch(tag: str, *, required: tuple[str, ...] = (), **properties: object) -> dict[str, object]:
    return {"properties": {"type": {"enum": [tag]}, **properties}, "required": ["type", *required]}


def _wizard_spec() -> dict[str, object]:
    schemas: dict[str, object] = {
        "CreateWizardChartV1Args": {
            "properties": {"data": _ref("WizardV1ConfigSchema")},
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
            "properties": {"chartId": {"type": "string"}, "data": _ref("WizardV1ConfigSchema")},
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
                "scalars": {
                    "properties": {
                        "count": {"type": "integer"},
                        "bounds": {
                            "prefixItems": [{"type": "string"}, {"type": "string"}],
                            "type": "array",
                        },
                        "enabled": {"type": "boolean"},
                        "label": {"type": "string"},
                        "nested": {
                            "properties": {"flag": {"type": "boolean"}},
                            "required": ["flag"],
                            "type": "object",
                        },
                        "nullable": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "optionalLabel": {"type": "string"},
                        "optionalNullable": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "optionalScaleValue": {
                            "anyOf": [
                                {"enum": ["auto"], "type": "string"},
                                {
                                    "prefixItems": [{"type": "number"}, {"type": "number"}],
                                    "type": "array",
                                },
                            ],
                        },
                    },
                    "required": ["bounds", "count", "enabled", "label", "nested", "nullable"],
                    "type": "object",
                },
                "sources": {
                    "properties": {
                        "updates": {
                            "items": {
                                "properties": {
                                    "field": {
                                        "properties": {
                                            "cast": {"type": "string"},
                                            "datasetId": {"type": "string"},
                                            "default_value": {
                                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                            },
                                            "guid": {"type": "string"},
                                            "originalDateCast": {"type": ["string", "null"]},
                                            "title": {"type": "string"},
                                        },
                                        "type": "object",
                                    },
                                },
                                "type": "object",
                            },
                            "type": "array",
                        },
                    },
                    "type": "object",
                },
                "visualization": {
                    "oneOf": [
                        _tag_branch(
                            "line",
                            required=("x",),
                            optionalTitle={"type": "string"},
                            chartSettings={
                                "properties": {
                                    "legendMode": {"enum": ["show", "hide"], "type": "string"},
                                    "titleMode": {"enum": ["show", "hide"], "type": "string"},
                                },
                                "type": "object",
                            },
                            sort={
                                "properties": {
                                    "items": {"items": _ref("WizardSortItemSchema"), "type": "array"},
                                },
                                "type": "object",
                            },
                            x={
                                "properties": {
                                    "items": {"items": _ref("WizardFieldSchema"), "type": "array"},
                                    "settings": {
                                        "properties": {
                                            "axisVisibility": {"enum": ["show", "hide"], "type": "string"},
                                        },
                                        "type": "object",
                                    },
                                },
                                "required": ["items"],
                                "type": "object",
                            },
                        ),
                        _tag_branch(
                            "geolayer",
                            layers={"items": _ref("WizardV1GeolayerLayerSchema"), "type": "array"},
                        ),
                        _tag_branch(
                            "combined-chart",
                            layers={"items": _ref("WizardV1CombinedChartLayerSchema"), "type": "array"},
                        ),
                    ],
                },
            },
            "required": ["scalars", "visualization"],
            "type": "object",
        },
        "WizardFieldSchema": {
            "anyOf": [
                {
                    "properties": {
                        "backgroundSettings": {"type": "object"},
                        "datasetId": {"type": "string"},
                        "format": {"type": "object"},
                        "guid": {"type": "string"},
                    },
                    "required": ["datasetId", "guid"],
                    "type": "object",
                },
                {
                    "properties": {
                        "data_type": {"type": "string"},
                        "fields": {"items": {"type": "object"}, "type": "array"},
                        "guid": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["data_type", "fields", "guid", "title"],
                    "type": "object",
                },
                {
                    "properties": {
                        "data_type": {"type": "string"},
                        "title": {"type": "string"},
                        "type": {"enum": ["PSEUDO"], "type": "string"},
                    },
                    "required": ["data_type", "title", "type"],
                    "type": "object",
                },
            ],
        },
        "WizardV1GeolayerLayerSchema": {
            "oneOf": [
                _tag_branch(
                    "geopoint",
                    required=("points",),
                    layerSettings={
                        "properties": {"alpha": {"type": "integer"}, "id": {"type": "string"}},
                        "type": "object",
                    },
                    points={
                        "properties": {"items": {"items": _ref("WizardFieldSchema"), "type": "array"}},
                        "required": ["items"],
                        "type": "object",
                    },
                    sort={
                        "properties": {
                            "items": {"items": _ref("WizardSortItemSchema"), "type": "array"},
                        },
                        "type": "object",
                    },
                    size={
                        "properties": {
                            "items": {"items": _ref("WizardFieldSchema"), "type": "array"},
                            "settings": {
                                "properties": {"minRadius": {"type": "number"}},
                                "type": "object",
                            },
                        },
                        "type": "object",
                    },
                ),
                _tag_branch("geopoint-with-cluster"),
                _tag_branch("geopolygon"),
                _tag_branch(
                    "heatmap",
                    required=("points",),
                    points={
                        "properties": {"items": {"items": _ref("WizardFieldSchema"), "type": "array"}},
                        "required": ["items"],
                        "type": "object",
                    },
                ),
                _tag_branch("polyline"),
            ],
        },
        "WizardV1CombinedChartLayerSchema": {
            "oneOf": [
                _tag_branch(
                    "column",
                    required=("x", "y"),
                    x={
                        "properties": {"items": {"items": _ref("WizardFieldSchema"), "type": "array"}},
                        "required": ["items"],
                        "type": "object",
                    },
                    sort={
                        "properties": {
                            "items": {"items": _ref("WizardSortItemSchema"), "type": "array"},
                        },
                        "type": "object",
                    },
                    y={
                        "properties": {
                            "items": {"items": _ref("WizardFieldSchema"), "type": "array"},
                            "settings": {
                                "properties": {
                                    "axisVisibility": {"enum": ["show", "hide"], "type": "string"},
                                },
                                "type": "object",
                            },
                        },
                        "required": ["items"],
                        "type": "object",
                    },
                ),
                _tag_branch(
                    "line",
                    required=("x", "y"),
                    optionalOpacity={"type": "number"},
                    x={
                        "properties": {"items": {"items": _ref("WizardFieldSchema"), "type": "array"}},
                        "required": ["items"],
                        "type": "object",
                    },
                    sort={
                        "properties": {
                            "items": {"items": _ref("WizardSortItemSchema"), "type": "array"},
                        },
                        "type": "object",
                    },
                    y={
                        "properties": {"items": {"items": _ref("WizardFieldSchema"), "type": "array"}},
                        "required": ["items"],
                        "type": "object",
                    },
                ),
                _tag_branch(
                    "area",
                    sort={
                        "properties": {
                            "items": {"items": _ref("WizardSortItemSchema"), "type": "array"},
                        },
                        "type": "object",
                    },
                ),
            ],
        },
        "WizardSortItemSchema": {
            "properties": {
                "datasetId": {"type": "string"},
                "direction": {"enum": ["ASC", "DESC"], "type": "string"},
                "guid": {"type": "string"},
            },
            "required": ["datasetId", "direction", "guid"],
            "type": "object",
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


def _write_wizard_installation_spec(
    path: Path,
    *,
    wizard_spec_value: dict[str, object] | None = None,
) -> Path:
    installation = _raw_object(
        json.loads((ROOT / "spec" / "enterprise.json").read_text()),
        path="installation",
    )
    wizard = wizard_spec_value or _wizard_spec()
    installation["openapi"] = wizard["openapi"]
    installation["info"] = wizard["info"]
    installation_paths = _raw_object(installation["paths"], path="installation.paths")
    wizard_paths = _raw_object(wizard["paths"], path="wizard.paths")
    installation_paths.update(wizard_paths)
    installation_components = _raw_object(installation["components"], path="installation.components")
    installation_schemas = _raw_object(installation_components["schemas"], path="installation.components.schemas")
    wizard_components = _raw_object(wizard["components"], path="wizard.components")
    wizard_schemas = _raw_object(wizard_components["schemas"], path="wizard.components.schemas")
    installation_schemas.update(wizard_schemas)
    path.write_text(json.dumps(installation), encoding="utf-8")
    return path


def _generated_wizard_dto_module(
    tmp_path: Path,
    *,
    wizard_spec_value: dict[str, object] | None = None,
) -> ModuleType:
    wizard_spec = _write_wizard_installation_spec(
        tmp_path / "wizard.json",
        wizard_spec_value=wizard_spec_value,
    )
    metadata = _build_metadata(installation_spec=wizard_spec)
    module_path = tmp_path / "synthetic_wizard_dto.py"
    module_path.write_text(emit_dto(metadata), encoding="utf-8")
    module_name = "synthetic_wizard_dto"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_wizard_block_matches_pre_dashboard_emitter(tmp_path: Path) -> None:
    generated = emit_dto(_build_metadata_from_api_v3_spec(tmp_path))
    start = generated.index("WIZARD_SCHEMA_FINGERPRINT:")
    end = generated.index("\nclass QLChartCreateDTO", start)

    assert hashlib.sha256(generated[start:end].encode()).hexdigest() == (_PRE_DASHBOARD_EMITTER_WIZARD_BLOCK_SHA256)


def _strict_config() -> dict[str, object]:
    return {
        "scalars": {
            "bounds": ["0", "100"],
            "count": 1,
            "enabled": True,
            "label": "valid",
            "nested": {"flag": False},
            "nullable": None,
        },
        "visualization": {"type": "line", "x": {"items": []}},
    }


def test_wizard_schema_meta_extracts_routes_and_structural_inventory() -> None:
    manifest = build_wizard_schema_meta(_wizard_spec())
    expected_inventory: WizardInventory = {
        "routes": 4,
        "roots": 7,
        "schemas": 14,
        "visualizations": 3,
        "geo_layers": 5,
        "combined_layers": 3,
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
    assert manifest["geo_layers"] == ["geopoint", "geopoint-with-cluster", "geopolygon", "heatmap", "polyline"]
    assert manifest["combined_layers"] == ["area", "column", "line"]
    assert manifest["visualization_variants"] == {
        "combined-chart": "/schemas/WizardV1ConfigSchema/properties/visualization/oneOf/1",
        "geolayer": "/schemas/WizardV1ConfigSchema/properties/visualization/oneOf/2",
        "line": "/schemas/WizardV1ConfigSchema/properties/visualization/oneOf/0",
    }
    assert manifest["geo_layer_variants"] == {
        "geopoint": "/schemas/WizardV1GeolayerLayerSchema/oneOf/0",
        "geopoint-with-cluster": "/schemas/WizardV1GeolayerLayerSchema/oneOf/2",
        "geopolygon": "/schemas/WizardV1GeolayerLayerSchema/oneOf/3",
        "heatmap": "/schemas/WizardV1GeolayerLayerSchema/oneOf/1",
        "polyline": "/schemas/WizardV1GeolayerLayerSchema/oneOf/4",
    }
    assert manifest["combined_layer_variants"] == {
        "area": "/schemas/WizardV1CombinedChartLayerSchema/oneOf/1",
        "column": "/schemas/WizardV1CombinedChartLayerSchema/oneOf/2",
        "line": "/schemas/WizardV1CombinedChartLayerSchema/oneOf/0",
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


def test_build_metadata_uses_the_installation_wizard_spec(tmp_path: Path) -> None:
    wizard_spec = _write_wizard_installation_spec(tmp_path / "wizard.json")

    metadata = _build_metadata(installation_spec=wizard_spec)

    wizard = metadata["installations"]["enterprise"]["wizard"]
    assert wizard["manifest"] == build_wizard_schema_meta(_wizard_spec())
    assert wizard["fingerprint"] == wizard_schema_fingerprint(wizard["manifest"])
    assert wizard["visualization_structure"] == build_wizard_visualization_structure(wizard["manifest"])
    assert wizard["field_structure"] == build_wizard_field_structure(wizard["manifest"])
    assert wizard["field_structure"] == {
        "direct_properties": ("backgroundSettings", "format"),
        "nullable_update_properties": ("default_value", "originalDateCast"),
        "update_properties": ("cast", "datasetId", "default_value", "guid", "originalDateCast", "title"),
    }
    assert wizard["visualization_structure"]["line"] == {
        "properties": ["chartSettings", "optionalTitle", "sort", "type", "x"],
        "required": ["type", "x"],
        "slots": {
            "sort": {
                "required": False,
                "items_required": False,
                "settings": {},
            },
            "x": {
                "required": True,
                "items_required": True,
                "settings": {"axisVisibility": {"enum": ["hide", "show"]}},
            },
        },
        "chart_settings": {
            "legendMode": {"enum": ["hide", "show"]},
            "titleMode": {"enum": ["hide", "show"]},
        },
        "layers": {},
    }
    assert wizard["visualization_structure"]["geolayer"]["layers"]["geopoint"]["slots"]["points"] == {
        "required": True,
        "items_required": True,
        "settings": {},
    }
    assert wizard["visualization_structure"]["combined-chart"]["layers"]["column"]["slots"]["y"] == {
        "required": True,
        "items_required": True,
        "settings": {"axisVisibility": {"enum": ["hide", "show"]}},
    }


def test_public_layer_type_aliases_match_generated_wizard_layer_tags() -> None:
    registry = build_wizard_visualization_structure(build_wizard_schema_meta(_wizard_spec()))

    assert set(get_args(CombinedLayerType)) == set(registry["combined-chart"]["layers"])
    assert set(get_args(GeoLayerType)) == set(registry["geolayer"]["layers"])


def test_chart_builder_generation_uses_only_generated_wizard_tags(tmp_path: Path) -> None:
    wizard_spec = _write_wizard_installation_spec(tmp_path / "wizard.json")
    metadata = _build_metadata(installation_spec=wizard_spec)

    generated = emit_chart_builders(metadata)

    assert "class LineWizardChartCreate" in generated
    assert "class CombinedChartWizardChartCreate" in generated
    assert "class GeolayerWizardChartCreate" in generated
    assert "class AreaWizardChartCreate" not in generated
    assert "def line(self, *, name: str, location: EntryLocation) -> LineWizardChartCreate:" in generated
    assert "from typing import Literal" in generated
    assert "from typing import Any, Literal" not in generated
    assert "from datalens_sdk.errors import NotSupportedError" not in generated

    line_body = generated.split("class LineWizardChartCreate", 1)[1].split("\nclass ", 1)[0]
    combined_body = generated.split("class CombinedChartWizardChartCreate", 1)[1].split("\nclass ", 1)[0]
    geolayer_body = generated.split("class GeolayerWizardChartCreate", 1)[1].split("\nclass ", 1)[0]
    assert "def measure_title_mode(" not in line_body
    assert "def add_sort(" in line_body
    assert "def sort(" in line_body
    assert "def add_sort(" in combined_body
    assert "def sort(" in combined_body
    assert "def add_sort(" not in geolayer_body
    assert "def sort(" not in geolayer_body


def _minimal_method_structure(spec: MethodSpec) -> WizardVisualizationStructure:
    chart_settings: dict[str, WizardValueStructure] = {key: {} for key in spec.get("required_chart_settings", ())}
    required_enum = spec.get("required_chart_setting_enum")
    if required_enum is not None:
        setting_key, required_values = required_enum
        chart_settings[setting_key] = {"enum": sorted(required_values)}
    slot_settings: dict[str, WizardValueStructure] = {key: {} for key in spec.get("required_slot_settings", ())}
    required_slot_settings_any = spec.get("required_slot_settings_any")
    if required_slot_settings_any:
        slot_settings[min(required_slot_settings_any)] = {}
    slot_name = spec.get("required_slot_carrier", "x")
    return {
        "properties": [],
        "required": [],
        "slots": {
            slot_name: {
                "required": False,
                "items_required": False,
                "settings": slot_settings,
            }
        },
        "chart_settings": chart_settings,
        "layers": {},
    }


def test_helper_generation_requires_every_descriptor_carrier() -> None:
    for method_name, spec in METHOD_SPECS.items():
        if not method_requires_generated_structure(method_name):
            continue
        complete = _minimal_method_structure(spec)
        assert _method_is_supported_by_structure(method_name, spec, complete), method_name

        for setting_key in spec.get("required_chart_settings", ()):
            incomplete = copy.deepcopy(complete)
            del incomplete["chart_settings"][setting_key]
            assert not _method_is_supported_by_structure(method_name, spec, incomplete), (method_name, setting_key)

        required_enum = spec.get("required_chart_setting_enum")
        if required_enum is not None:
            setting_key, required_values = required_enum
            for missing_value in required_values:
                incomplete = copy.deepcopy(complete)
                incomplete["chart_settings"][setting_key]["enum"].remove(missing_value)
                assert not _method_is_supported_by_structure(method_name, spec, incomplete), (
                    method_name,
                    missing_value,
                )

        slot_name = spec.get("required_slot_carrier", "x")
        if "required_slot_carrier" in spec:
            incomplete = copy.deepcopy(complete)
            del incomplete["slots"][slot_name]
            assert not _method_is_supported_by_structure(method_name, spec, incomplete), method_name

        for setting_key in spec.get("required_slot_settings", ()):
            incomplete = copy.deepcopy(complete)
            del incomplete["slots"][slot_name]["settings"][setting_key]
            assert not _method_is_supported_by_structure(method_name, spec, incomplete), (method_name, setting_key)

        required_slot_settings_any = spec.get("required_slot_settings_any")
        if required_slot_settings_any:
            incomplete = copy.deepcopy(complete)
            incomplete["slots"][slot_name]["settings"].clear()
            assert not _method_is_supported_by_structure(method_name, spec, incomplete), method_name
            for setting_key in required_slot_settings_any:
                alternative = copy.deepcopy(incomplete)
                alternative["slots"][slot_name]["settings"][setting_key] = {}
                assert _method_is_supported_by_structure(method_name, spec, alternative), (method_name, setting_key)


def test_carrier_resolver_distinguishes_builder_surface_from_active_layer() -> None:
    structure: WizardVisualizationStructure = {
        "properties": ["layers", "type"],
        "required": ["layers", "type"],
        "slots": {},
        "chart_settings": {},
        "layers": {
            "line": {
                "properties": ["type", "x"],
                "required": ["type", "x"],
                "slots": {
                    "x": {
                        "required": True,
                        "items_required": True,
                        "settings": {"title": {}, "titleValue": {}},
                    },
                    "sort": {"required": False, "items_required": False, "settings": {}},
                },
                "layer_settings": {},
            },
            "area": {
                "properties": ["type", "x"],
                "required": ["type", "x"],
                "slots": {
                    "x": {"required": True, "items_required": True, "settings": {}},
                    "sort": {"required": False, "items_required": False, "settings": {}},
                },
                "layer_settings": {},
            },
        },
    }
    axis_spec = METHOD_SPECS["axis_title"]
    builder = resolve_method_carriers("axis_title", axis_spec, structure, scope="builder_surface")
    active_line = resolve_method_carriers(
        "axis_title",
        axis_spec,
        structure,
        scope="active_layer",
        active_layer_type="line",
    )
    active_area = resolve_method_carriers(
        "axis_title",
        axis_spec,
        structure,
        scope="active_layer",
        active_layer_type="area",
    )

    assert builder.failure is not None
    assert builder.failure.code == "missing_slot_setting"
    assert active_line.supported
    assert active_line.matched_slot_names == ("x",)
    assert active_area.failure is not None
    assert active_area.failure.code == "missing_slot_setting"

    sort_spec = METHOD_SPECS["add_sort"]
    assert resolve_method_carriers("add_sort", sort_spec, structure, scope="builder_surface").supported
    del structure["layers"]["area"]["slots"]["sort"]
    sort_failure = resolve_method_carriers("add_sort", sort_spec, structure, scope="builder_surface")
    assert sort_failure.failure is not None
    assert sort_failure.failure.code == "missing_slot"


def test_carrier_resolver_reports_unknown_active_layer_structurally() -> None:
    structure = _minimal_method_structure(METHOD_SPECS["labels_position"])
    structure["layers"] = {
        "line": {
            "properties": [],
            "required": [],
            "slots": structure["slots"],
            "layer_settings": {},
        }
    }
    structure["slots"] = {}

    resolution = resolve_method_carriers(
        "labels_position",
        METHOD_SPECS["labels_position"],
        structure,
        scope="active_layer",
        active_layer_type="missing",
    )

    assert resolution.failure is not None
    assert resolution.failure.code == "unknown_active_layer"
    assert resolution.failure.layer_type == "missing"


def test_converter_rejects_invalid_nested_generated_wizard_structure() -> None:
    valid_registry: dict[str, object] = {
        "combined-chart": {
            "properties": ["layers", "type"],
            "required": ["layers", "type"],
            "slots": {},
            "chart_settings": {"titleMode": {"enum": ["hide", "show"]}},
            "layers": {
                "line": {
                    "properties": ["layerSettings", "type", "x"],
                    "required": ["layerSettings", "type", "x"],
                    "slots": {
                        "x": {
                            "required": True,
                            "items_required": True,
                            "settings": {"axisVisibility": {"enum": ["hide", "show"]}},
                        }
                    },
                    "layer_settings": {"id": {}},
                }
            },
        }
    }
    invalid_values = (
        (("combined-chart", "properties"), ["type", 1]),
        (("combined-chart", "required"), "type"),
        (("combined-chart", "chart_settings", "titleMode", "enum"), ["hide", 1]),
        (("combined-chart", "slots"), {"x": None}),
        (("combined-chart", "layers", "line", "properties"), ["type", 1]),
        (("combined-chart", "layers", "line", "slots", "x", "required"), 1),
        (("combined-chart", "layers", "line", "slots", "x", "settings"), {"axisVisibility": None}),
        (("combined-chart", "layers", "line", "layer_settings", "id", "enum"), [1]),
    )

    for path, invalid in invalid_values:
        registry = copy.deepcopy(valid_registry)
        target = registry
        for key in path[:-1]:
            target = cast(dict[str, object], target[key])
        target[path[-1]] = invalid
        module = SimpleNamespace(
            WIZARD_VISUALIZATION_STRUCTURE=registry,
            WIZARD_FIELD_STRUCTURE={
                "direct_properties": (),
                "update_properties": (),
                "nullable_update_properties": (),
            },
        )

        with pytest.raises(DataLensConfigurationError, match=r"Generated Wizard structure.*invalid"):
            validate_wizard_generated_contract(cast(WizardChartDtoModule, module))


def test_generated_contract_boundary_validates_fingerprint_factories_and_unavailable_shape(tmp_path: Path) -> None:
    module = _generated_wizard_dto_module(tmp_path)
    contract = validate_wizard_generated_contract(module)
    assert contract.schema_fingerprint == module.WIZARD_SCHEMA_FINGERPRINT
    assert contract.visualization_structure is module.WIZARD_VISUALIZATION_STRUCTURE
    assert contract.field_structure is module.WIZARD_FIELD_STRUCTURE

    malformed_fingerprint = SimpleNamespace(
        WIZARD_SCHEMA_FINGERPRINT=None,
        WIZARD_VISUALIZATION_STRUCTURE=module.WIZARD_VISUALIZATION_STRUCTURE,
        WIZARD_FIELD_STRUCTURE=module.WIZARD_FIELD_STRUCTURE,
        WizardChartCreateDTO=module.WizardChartCreateDTO,
        WizardChartUpdateDTO=module.WizardChartUpdateDTO,
        WizardChartReadDTO=module.WizardChartReadDTO,
    )
    with pytest.raises(DataLensConfigurationError, match="fingerprint"):
        validate_wizard_generated_contract(malformed_fingerprint)

    unavailable = SimpleNamespace(
        WIZARD_SCHEMA_FINGERPRINT=None,
        WIZARD_VISUALIZATION_STRUCTURE={},
        WIZARD_FIELD_STRUCTURE={
            "direct_properties": (),
            "update_properties": (),
            "nullable_update_properties": (),
        },
        WizardChartCreateDTO=module.WizardChartCreateDTO,
        WizardChartUpdateDTO=module.WizardChartUpdateDTO,
        WizardChartReadDTO=module.WizardChartReadDTO,
    )
    unavailable_contract = validate_wizard_generated_contract(unavailable)
    with pytest.raises(DataLensConfigurationError, match="unavailable"):
        unavailable_contract.require_available()


def test_generated_wizard_create_and_update_validation_is_strict_and_preserves_open_data(tmp_path: Path) -> None:
    module = _generated_wizard_dto_module(tmp_path)
    assert module.WIZARD_FIELD_STRUCTURE == {
        "direct_properties": ("backgroundSettings", "format"),
        "nullable_update_properties": ("default_value", "originalDateCast"),
        "update_properties": ("cast", "datasetId", "default_value", "guid", "originalDateCast", "title"),
    }
    create_dto = module.WizardChartCreateDTO
    update_dto = module.WizardChartUpdateDTO
    invalid_values = (
        (("scalars", "bounds"), ["0"]),
        (("scalars", "bounds"), ["0", "100", "200"]),
        (("scalars", "bounds"), [0, "100"]),
        (("scalars", "enabled"), "true"),
        (("scalars", "count"), "1"),
        (("scalars", "label"), 1),
        (("scalars", "nullable"), 1),
        (("scalars", "nested", "flag"), 0),
    )

    for path, invalid in invalid_values:
        data = _strict_config()
        target = data
        for key in path[:-1]:
            value = target[key]
            assert isinstance(value, dict)
            target = value
        target[path[-1]] = invalid

        with pytest.raises(ValidationError):
            create_dto(data=data)
        with pytest.raises(ValidationError):
            update_dto(chart_id="chart-1", mode="save", data=data)

    create_payload = create_dto(data=_strict_config()).to_payload()
    assert _raw_object(create_payload["data"], path="create.data")["scalars"] == _strict_config()["scalars"]

    open_data = _strict_config()
    open_data["futureRoot"] = {"enabled": True}
    scalars = open_data["scalars"]
    assert isinstance(scalars, dict)
    scalars["futureNested"] = {"value": 1}

    with pytest.raises(ValidationError):
        create_dto(data=open_data)
    update_payload = update_dto(chart_id="chart-1", mode="save", data=open_data).to_payload()
    assert update_payload["data"] == open_data


def test_generated_optional_properties_keep_omission_distinct_from_null(tmp_path: Path) -> None:
    module = _generated_wizard_dto_module(tmp_path)
    module_path = module.__file__
    assert module_path is not None
    generated = Path(module_path).read_text(encoding="utf-8")
    assert "from typing import Annotated, Any, Literal" in generated
    assert "cast as _typing_cast" not in generated
    assert "_UNVALIDATED_NONE_DEFAULT: Any = None" in generated
    assert "optional_label: str = Field(default=_UNVALIDATED_NONE_DEFAULT, alias='optionalLabel')" in generated
    assert "optional_title: str = Field(default=_UNVALIDATED_NONE_DEFAULT, alias='optionalTitle')" in generated
    assert "sources: WizardV1ConfigSchemaSourcesDTO = _UNVALIDATED_NONE_DEFAULT" in generated
    assert "cast: str = _UNVALIDATED_NONE_DEFAULT" in generated
    assert "dataset_id: str = Field(default=_UNVALIDATED_NONE_DEFAULT, alias='datasetId')" in generated
    assert (
        "optional_scale_value: Literal['auto'] | Annotated[tuple[float, float], "
        "BeforeValidator(_json_array_to_tuple)] = Field(default=_UNVALIDATED_NONE_DEFAULT, "
        "alias='optionalScaleValue')" in generated
    )

    create_dto = cast(Callable[..., _PayloadDTO], module.WizardChartCreateDTO)
    update_dto = cast(Callable[..., _PayloadDTO], module.WizardChartUpdateDTO)
    factories: tuple[Callable[[dict[str, object]], _PayloadDTO], ...] = (
        lambda data: create_dto(data=data),
        lambda data: update_dto(chart_id="chart-1", mode="save", data=data),
    )

    for factory in factories:
        omitted = _strict_config()
        assert factory(omitted).to_payload()["data"] == omitted

        non_nullable_null = _strict_config()
        cast(dict[str, object], non_nullable_null["scalars"])["optionalLabel"] = None
        with pytest.raises(ValidationError):
            factory(non_nullable_null)

        nullable_null = _strict_config()
        cast(dict[str, object], nullable_null["scalars"])["optionalNullable"] = None
        assert factory(nullable_null).to_payload()["data"] == nullable_null

        annotated_null = _strict_config()
        cast(dict[str, object], annotated_null["scalars"])["optionalScaleValue"] = None
        with pytest.raises(ValidationError):
            factory(annotated_null)

        visualization_null = _strict_config()
        cast(dict[str, object], visualization_null["visualization"])["optionalTitle"] = None
        with pytest.raises(ValidationError):
            factory(visualization_null)

        layered = _strict_config()
        layered["visualization"] = {
            "type": "combined-chart",
            "layers": [
                {
                    "type": "line",
                    "x": {"items": []},
                    "y": {"items": []},
                    "optionalOpacity": None,
                }
            ],
        }
        with pytest.raises(ValidationError):
            factory(layered)


def test_generated_wizard_models_reuse_equivalent_anonymous_object_schemas(tmp_path: Path) -> None:
    spec = _wizard_spec()
    schemas = _raw_object(_raw_object(spec["components"], path="components")["schemas"], path="schemas")
    config = _raw_object(schemas["WizardV1ConfigSchema"], path="WizardV1ConfigSchema")
    config_properties = _raw_object(config["properties"], path="config.properties")
    scalars = _raw_object(config_properties["scalars"], path="scalars")
    scalar_properties = _raw_object(scalars["properties"], path="scalars.properties")
    repeated = {
        "properties": {"marker": {"enum": ["shared"], "type": "string"}},
        "required": ["marker"],
        "type": "object",
    }
    scalar_properties["duplicateAlpha"] = repeated
    scalar_properties["duplicateBeta"] = copy.deepcopy(repeated)

    installation_spec = _write_wizard_installation_spec(tmp_path / "wizard.json", wizard_spec_value=spec)
    generated = emit_dto(_build_metadata(installation_spec=installation_spec))

    assert generated.count("class WizardV1ConfigSchemaScalarsDuplicateAlphaDTO(BaseModel):") == 1
    assert "class WizardV1ConfigSchemaScalarsDuplicateBetaDTO(BaseModel):" not in generated
    assert "duplicate_alpha: WizardV1ConfigSchemaScalarsDuplicateAlphaDTO" in generated
    assert "duplicate_beta: WizardV1ConfigSchemaScalarsDuplicateAlphaDTO" in generated
    assert generated.count("class WizardV1ConfigSchemaScalarsDuplicateAlphaReadDTO(BaseModel):") == 1
    assert "class WizardV1ConfigSchemaScalarsDuplicateBetaReadDTO(BaseModel):" not in generated
    assert "duplicate_alpha: WizardV1ConfigSchemaScalarsDuplicateAlphaReadDTO" in generated
    assert "duplicate_beta: WizardV1ConfigSchemaScalarsDuplicateAlphaReadDTO" in generated


def test_generated_wizard_models_consume_current_object_openness(tmp_path: Path) -> None:
    spec = _wizard_spec()
    schemas = _raw_object(_raw_object(spec["components"], path="components")["schemas"], path="schemas")
    config = _raw_object(schemas["WizardV1ConfigSchema"], path="WizardV1ConfigSchema")
    config_properties = _raw_object(config["properties"], path="config.properties")
    scalars = _raw_object(config_properties["scalars"], path="scalars")
    scalar_properties = _raw_object(scalars["properties"], path="scalars.properties")
    scalar_properties.update(
        {
            "labelsById": {"type": "object", "additionalProperties": {"type": "string"}},
            "openNode": {
                "type": "object",
                "properties": {"known": {"type": "boolean"}},
                "required": ["known"],
                "additionalProperties": True,
            },
        }
    )
    cast(list[str], scalars["required"]).extend(["labelsById", "openNode"])
    module = _generated_wizard_dto_module(tmp_path, wizard_spec_value=spec)
    valid = _strict_config()
    cast(dict[str, object], valid["scalars"]).update(
        {
            "labelsById": {"one": "label"},
            "openNode": {"known": True, "future": {"value": 1}},
        }
    )
    assert module.WizardChartCreateDTO(data=valid).to_payload()["data"] == valid
    assert module.WizardChartUpdateDTO(chart_id="chart-1", mode="save", data=valid).to_payload()["data"] == valid

    invalid = copy.deepcopy(valid)
    cast(dict[str, object], invalid["scalars"])["labelsById"] = {"one": 1}
    with pytest.raises(ValidationError):
        module.WizardChartCreateDTO(data=invalid)
    with pytest.raises(ValidationError):
        module.WizardChartUpdateDTO(chart_id="chart-1", mode="save", data=invalid)


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("const", 1),
        ("default", 1),
        ("deprecated", True),
        ("format", "uuid"),
        ("minimum", 0),
        ("minItems", 1),
        ("minLength", 1),
        ("multipleOf", 2),
        ("pattern", "^[0-9]+$"),
        ("x-datalens-rule", True),
    ],
)
def test_wizard_schema_rejects_unsupported_semantic_features_with_exact_pointer(
    keyword: str,
    value: object,
) -> None:
    spec = _wizard_spec()
    schemas = _raw_object(_raw_object(spec["components"], path="components")["schemas"], path="schemas")
    config = _raw_object(schemas["WizardV1ConfigSchema"], path="WizardV1ConfigSchema")
    scalars = _raw_object(_raw_object(config["properties"], path="properties")["scalars"], path="scalars")
    count = _raw_object(_raw_object(scalars["properties"], path="scalar properties")["count"], path="count")
    count[keyword] = value

    pointer = f"/schemas/WizardV1ConfigSchema/properties/scalars/properties/count/{keyword}"
    with pytest.raises(ValueError, match=re.escape(pointer)):
        build_wizard_schema_meta(spec)


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("$ref", None),
        ("additionalProperties", None),
        ("enum", None),
        ("items", None),
        ("oneOf", None),
        ("properties", None),
        ("required", None),
        ("type", None),
    ],
)
def test_wizard_schema_rejects_malformed_supported_features_with_exact_pointer(
    keyword: str,
    value: object,
) -> None:
    spec = _wizard_spec()
    schemas = _raw_object(_raw_object(spec["components"], path="components")["schemas"], path="schemas")
    config = _raw_object(schemas["WizardV1ConfigSchema"], path="WizardV1ConfigSchema")
    scalars = _raw_object(_raw_object(config["properties"], path="properties")["scalars"], path="scalars")
    count = _raw_object(_raw_object(scalars["properties"], path="scalar properties")["count"], path="count")
    count[keyword] = value

    pointer = f"/schemas/WizardV1ConfigSchema/properties/scalars/properties/count/{keyword}"
    with pytest.raises(ValueError, match=re.escape(pointer)):
        build_wizard_schema_meta(spec)


def test_wizard_schema_rejects_ambiguous_one_of_instead_of_deduplicating_it() -> None:
    spec = _wizard_spec()
    schemas = _raw_object(_raw_object(spec["components"], path="components")["schemas"], path="schemas")
    config = _raw_object(schemas["WizardV1ConfigSchema"], path="WizardV1ConfigSchema")
    visualization = _raw_object(
        _raw_object(config["properties"], path="properties")["visualization"],
        path="visualization",
    )
    branches = cast(list[object], visualization["oneOf"])
    branches.append(copy.deepcopy(branches[0]))

    with pytest.raises(ValueError, match=r"/schemas/WizardV1ConfigSchema/properties/visualization/oneOf"):
        build_wizard_schema_meta(spec)
