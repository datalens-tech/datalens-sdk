from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from enum import Enum
import hashlib
import json
import keyword
from pathlib import Path
import re
from typing import TypedDict

from typing_extensions import NotRequired

from datalens_sdk._runtime.method_specs import (
    MethodSpec,
    method_specs_for_visualization,
    resolve_method_carriers,
)
from datalens_sdk._runtime.viz_specs import QL_VIZ_SPECS, factory_method_name, to_snake
from datalens_sdk._runtime.wizard_semantics import (
    WIZARD_VISUALIZATION_SEMANTICS,
)
from datalens_sdk._runtime.wizard_structure import (
    WizardFieldStructure,
    WizardLayerStructure,
    WizardSlotStructure,
    WizardValueStructure,
    WizardVisualizationRegistry,
    WizardVisualizationStructure,
)
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "spec"
PACKAGE_DIR = Path("src") / "datalens_sdk"

INSTALLATIONS = {
    "enterprise": SPEC_DIR / "enterprise.json",
    "yacloud": SPEC_DIR / "yacloud.json",
}

NAMESPACES = {
    "enterprise": ["collections", "connections", "dashboards", "datasets", "folders", "workbooks"],
    "yacloud": ["collections", "connections", "dashboards", "datasets", "folders", "licenses", "workbooks"],
}

READ_ONLY_FIELDS = {"id", "key", "created_at", "updated_at", "meta"}
LOCATION_FIELDS = {"name", "dir_path", "workbook_id", "collection_id"}
RESERVED_METHODS = {
    "build",
    "description",
    "workbook_id",
    "required_fields",
    "missing_required",
    "optional_fields",
    "allowed_values",
    "fields_help",
    "installation",
    "connector",
}
_WIZARD_VISUALIZATION_BASE_CREATE: dict[str, str] = {
    "combined-chart": "_CombinedWizardChartCreate",
    "geolayer": "_GeolayerWizardChartCreate",
    "metric": "_MetricWizardChartCreate",
    "flatTable": "_TableWizardChartCreate",
    "pivotTable": "_PivotWizardChartCreate",
    "scatter": "_ScatterWizardChartCreate",
}
_WIZARD_ROUTES = (
    "/rpc/createWizardChart",
    "/rpc/deleteWizardChart",
    "/rpc/getWizardChart",
    "/rpc/updateWizardChart",
)
_DASHBOARD_V2_ROOTS = (
    "CreateDashboardV2Args",
    "DeleteDashboardArgs",
    "GetDashboardV2Args",
    "GetDashboardV2Result",
    "UpdateDashboardV2Args",
)
_SCHEMA_REF_PREFIX = "#/components/schemas/"
_SCHEMA_DOCUMENTATION_KEYS = frozenset({"$comment", "description", "example", "examples", "title"})
_SCHEMA_NAMED_MAP_KEYS = frozenset({"properties"})
_SCHEMA_SET_LIKE_KEYS = frozenset({"allOf", "anyOf", "enum", "required", "type"})
_SCHEMA_MULTISET_KEYS = frozenset({"oneOf"})
_SCHEMA_SUPPORTED_KEYS = frozenset(
    {
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "enum",
        "items",
        "oneOf",
        "prefixItems",
        "properties",
        "required",
        "type",
    }
)
_DASHBOARD_SCHEMA_SUPPORTED_KEYS = frozenset({"discriminator", "minItems", "minLength", "minimum"})


class _WizardSchemaFeatureState(Enum):
    DOCUMENTATION_ONLY = "documentation-only"
    SUPPORTED = "supported"
    SEMANTIC_UNSUPPORTED = "semantic-unsupported"


_WIZARD_SCHEMA_FEATURE_POLICY: dict[str, _WizardSchemaFeatureState] = {
    **dict.fromkeys(_SCHEMA_DOCUMENTATION_KEYS, _WizardSchemaFeatureState.DOCUMENTATION_ONLY),
    **dict.fromkeys(_SCHEMA_SUPPORTED_KEYS, _WizardSchemaFeatureState.SUPPORTED),
}


class FieldMeta(TypedDict):
    type: str


class ConnectorMeta(TypedDict):
    schema: str
    required: list[str]
    available_fields: list[str]
    fields: dict[str, FieldMeta]
    defaults: dict[str, object]
    enum_restrictions: dict[str, list[object]]


class SourceMeta(TypedDict):
    schema: str
    method: str
    connection_type: str
    parameters: dict[str, str]


class NodeFieldMeta(TypedDict):
    required: bool


class EditorNodeMeta(TypedDict):
    wire_type: str
    create_schema: str
    data_fields: dict[str, NodeFieldMeta]


class EditorCreateNodeMeta(EditorNodeMeta):
    factory_method: str


class ChartMeta(TypedDict):
    editor_nodes: dict[str, EditorCreateNodeMeta]
    editor_update_nodes: dict[str, EditorNodeMeta]


class ChartFactoryMeta(TypedDict):
    wizard: list[str]
    ql: list[str]
    editor: list[str]


class WizardRouteMeta(TypedDict):
    method: str
    request_schema: str
    result_schema: str | None
    request_body_required: bool
    request_dto: str
    result_dto: str | None


class WizardInventory(TypedDict):
    routes: int
    roots: int
    schemas: int
    visualizations: int
    geo_layers: int
    combined_layers: int


class WizardSchemaMeta(TypedDict):
    api_version: str
    wizard_version: int
    routes: dict[str, WizardRouteMeta]
    roots: list[str]
    schemas: dict[str, JsonValue]
    visualizations: list[str]
    geo_layers: list[str]
    combined_layers: list[str]
    visualization_variants: dict[str, str]
    geo_layer_variants: dict[str, str]
    combined_layer_variants: dict[str, str]
    inventory: WizardInventory


class WizardContractMeta(TypedDict):
    fingerprint: str
    manifest: WizardSchemaMeta
    visualization_structure: WizardVisualizationRegistry
    field_structure: WizardFieldStructure


class DashboardContractMeta(TypedDict):
    roots: list[str]
    schemas: dict[str, JsonValue]


class InstallationMetadata(TypedDict):
    name: str
    namespaces: list[str]
    connectors: dict[str, ConnectorMeta]
    dataset_sources: dict[str, SourceMeta]
    charts: ChartMeta
    chart_factories: ChartFactoryMeta
    wizard: NotRequired[WizardContractMeta]


class Metadata(TypedDict):
    installations: dict[str, InstallationMetadata]
    dashboard: NotRequired[DashboardContractMeta]


def _string_object_dict(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{context} contains a non-string key")
        result[key] = item
    return result


def _schema_dict(value: object, *, context: str) -> dict[str, dict[str, object]]:
    raw = _string_object_dict(value, context=context)
    result: dict[str, dict[str, object]] = {}
    for key, item in raw.items():
        if not isinstance(item, dict):
            raise TypeError(f"{context}.{key} must be an object")
        result[key] = _string_object_dict(item, context=f"{context}.{key}")
    return result


def _string_list(value: object, *, context: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{context} must be a list of strings")
    return list(value)


def _string_mapping(value: object, *, context: str) -> dict[str, str]:
    raw = _string_object_dict(value, context=context)
    result: dict[str, str] = {}
    for key, item in raw.items():
        if not isinstance(item, str):
            raise TypeError(f"{context}.{key} must be a string")
        result[key] = item
    return result


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise TypeError(f"{path} did not contain a JSON object")
    return _string_object_dict(data, context=str(path))


def _schemas(spec: Mapping[str, object]) -> dict[str, dict[str, object]]:
    components = _string_object_dict(spec.get("components"), context="components")
    return _schema_dict(components.get("schemas"), context="components.schemas")


def _ref_name(ref: str) -> str:
    return ref.removeprefix("#/components/schemas/")


def _schema_ref_name(value: object, *, context: str) -> str:
    schema = _string_object_dict(value, context=context)
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith(_SCHEMA_REF_PREFIX):
        raise ValueError(f"{context} must contain a local schema $ref")
    name = ref.removeprefix(_SCHEMA_REF_PREFIX)
    if not name or "/" in name:
        raise ValueError(f"{context} contains unsupported schema $ref {ref!r}")
    return name


def _schema_refs(value: object) -> set[str]:
    if isinstance(value, list):
        return set().union(*(_schema_refs(item) for item in value)) if value else set()
    if not isinstance(value, dict):
        return set()

    refs: set[str] = set()
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith(_SCHEMA_REF_PREFIX):
        refs.add(_schema_ref_name(value, context="schema node"))
    for child in value.values():
        refs.update(_schema_refs(child))
    return refs


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _deduplicate_sorted_json(values: list[JsonValue]) -> list[JsonValue]:
    by_json = {_canonical_json(value): value for value in values}
    return [by_json[key] for key in sorted(by_json)]


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _schema_pointer(pointer: str, key: str | int) -> str:
    return f"{pointer}/{_json_pointer_token(str(key))}"


def _wizard_schema_feature_state(key: str) -> _WizardSchemaFeatureState:
    if key.startswith("x-datalens-"):
        return _WizardSchemaFeatureState.SEMANTIC_UNSUPPORTED
    if key.startswith("x-"):
        return _WizardSchemaFeatureState.DOCUMENTATION_ONLY
    return _WIZARD_SCHEMA_FEATURE_POLICY.get(key, _WizardSchemaFeatureState.SEMANTIC_UNSUPPORTED)


def _singleton_schema_values(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    properties = value.get("properties")
    required = value.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        return {}
    result: dict[str, str] = {}
    for property_name in required:
        property_schema = properties.get(property_name) if isinstance(property_name, str) else None
        if not isinstance(property_schema, Mapping):
            continue
        enum = property_schema.get("enum")
        if isinstance(enum, list) and len(enum) == 1:
            result[property_name] = _canonical_json(enum[0])
    return result


def _one_of_is_provably_disjoint(branches: list[object]) -> bool:
    singleton_values = [_singleton_schema_values(branch) for branch in branches]
    common_keys = set.intersection(*(set(values) for values in singleton_values)) if singleton_values else set()
    if any(len({values[key] for values in singleton_values}) == len(branches) for key in common_keys):
        return True
    primitive_types: list[frozenset[str]] = []
    for branch in branches:
        if not isinstance(branch, Mapping):
            return False
        raw_type = branch.get("type")
        values = frozenset(raw_type if isinstance(raw_type, list) else [raw_type])
        if not values or not all(isinstance(item, str) for item in values):
            return False
        primitive_types.append(values)
    return all(
        left.isdisjoint(right) for index, left in enumerate(primitive_types) for right in primitive_types[index + 1 :]
    )


def _audit_pydantic_schema_features(
    value: object,
    *,
    pointer: str,
    contract: str,
    require_provably_disjoint_one_of: bool,
) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{contract} schema node at {pointer} must be an object")

    for key in value:
        if not isinstance(key, str):
            raise TypeError(f"{contract} schema node at {pointer} contains a non-string key")
        state = _wizard_schema_feature_state(key)
        dashboard_extension = contract == "Dashboard" and key in _DASHBOARD_SCHEMA_SUPPORTED_KEYS
        if state is _WizardSchemaFeatureState.SEMANTIC_UNSUPPORTED and not dashboard_extension:
            raise ValueError(
                f"Unsupported behavior-bearing {contract} schema feature at {_schema_pointer(pointer, key)}: {key}"
            )

    ref = value.get("$ref")
    if "$ref" in value and not isinstance(ref, str):
        raise ValueError(f"{contract} schema feature at {_schema_pointer(pointer, '$ref')} must be a string")
    raw_type = value.get("type")
    schema_types = raw_type if isinstance(raw_type, list) else [raw_type]
    if "type" in value and (
        not schema_types
        or any(
            not isinstance(schema_type, str)
            or schema_type not in {"array", "boolean", "integer", "null", "number", "object", "string"}
            for schema_type in schema_types
        )
    ):
        raise ValueError(
            f"{contract} schema feature at {_schema_pointer(pointer, 'type')} must contain supported JSON Schema types"
        )
    required = value.get("required")
    if "required" in value and (not isinstance(required, list) or any(not isinstance(name, str) for name in required)):
        raise ValueError(f"{contract} schema feature at {_schema_pointer(pointer, 'required')} must be a string list")

    enum = value.get("enum")
    if "enum" in value and (
        not isinstance(enum, list)
        or not enum
        or any(item is not None and not isinstance(item, (str, bool, int, float)) for item in enum)
    ):
        raise ValueError(f"{contract} schema enum at {_schema_pointer(pointer, 'enum')} must contain JSON scalars")

    for constraint in ("minItems", "minLength"):
        constraint_value = value.get(constraint)
        if constraint in value and (
            not isinstance(constraint_value, int) or isinstance(constraint_value, bool) or constraint_value < 0
        ):
            raise ValueError(
                f"{contract} schema feature at {_schema_pointer(pointer, constraint)} must be a non-negative integer"
            )
    minimum = value.get("minimum")
    if "minimum" in value and (not isinstance(minimum, (int, float)) or isinstance(minimum, bool)):
        raise ValueError(f"{contract} schema feature at {_schema_pointer(pointer, 'minimum')} must be a number")

    discriminator = value.get("discriminator")
    if "discriminator" in value:
        if not isinstance(discriminator, Mapping) or not isinstance(discriminator.get("propertyName"), str):
            raise ValueError(
                f"{contract} schema feature at {_schema_pointer(pointer, 'discriminator')} "
                "must contain a string propertyName"
            )
        mapping = discriminator.get("mapping")
        if mapping is not None and (
            not isinstance(mapping, Mapping)
            or any(not isinstance(tag, str) or not isinstance(ref_value, str) for tag, ref_value in mapping.items())
        ):
            raise ValueError(
                f"{contract} schema feature at {_schema_pointer(pointer, 'discriminator')}/mapping "
                "must map strings to schema references"
            )

    additional = value.get("additionalProperties")
    if "additionalProperties" in value and not isinstance(additional, (bool, Mapping)):
        raise ValueError(
            f"{contract} schema feature at {_schema_pointer(pointer, 'additionalProperties')} "
            "must be a boolean or schema"
        )
    properties = value.get("properties")
    if isinstance(additional, Mapping) and isinstance(properties, Mapping) and properties:
        raise ValueError(
            f"Unsupported behavior-bearing {contract} schema feature at "
            f"{_schema_pointer(pointer, 'additionalProperties')}: typed extras on an object with named properties"
        )

    for map_key in ("properties",):
        children = value.get(map_key)
        if map_key not in value:
            continue
        if not isinstance(children, Mapping):
            raise ValueError(f"{contract} schema feature at {_schema_pointer(pointer, map_key)} must be an object")
        for name, child in children.items():
            if not isinstance(name, str):
                raise TypeError(
                    f"{contract} schema map at {_schema_pointer(pointer, map_key)} contains a non-string key"
                )
            _audit_pydantic_schema_features(
                child,
                pointer=_schema_pointer(_schema_pointer(pointer, map_key), name),
                contract=contract,
                require_provably_disjoint_one_of=require_provably_disjoint_one_of,
            )

    items = value.get("items")
    if "items" not in value:
        pass
    elif isinstance(items, Mapping):
        _audit_pydantic_schema_features(
            items,
            pointer=_schema_pointer(pointer, "items"),
            contract=contract,
            require_provably_disjoint_one_of=require_provably_disjoint_one_of,
        )
    else:
        raise ValueError(f"{contract} schema feature at {_schema_pointer(pointer, 'items')} must be a schema")

    additional_schema = value.get("additionalProperties")
    if isinstance(additional_schema, Mapping):
        _audit_pydantic_schema_features(
            additional_schema,
            pointer=_schema_pointer(pointer, "additionalProperties"),
            contract=contract,
            require_provably_disjoint_one_of=require_provably_disjoint_one_of,
        )

    for list_key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        children = value.get(list_key)
        if list_key not in value:
            continue
        if not isinstance(children, list) or not children:
            raise ValueError(
                f"{contract} schema feature at {_schema_pointer(pointer, list_key)} must be a non-empty list"
            )
        if list_key == "oneOf" and require_provably_disjoint_one_of and not _one_of_is_provably_disjoint(children):
            raise ValueError(
                f"Unsupported behavior-bearing {contract} schema feature at "
                f"{_schema_pointer(pointer, list_key)}: oneOf branches are not provably disjoint"
            )
        for index, child in enumerate(children):
            child_pointer = _schema_pointer(_schema_pointer(pointer, list_key), index)
            if list_key == "allOf" and isinstance(child, Mapping):
                unsupported_merge_keys = {
                    key
                    for key in child
                    if (
                        _wizard_schema_feature_state(str(key)) is _WizardSchemaFeatureState.SUPPORTED
                        or (contract == "Dashboard" and key in _DASHBOARD_SCHEMA_SUPPORTED_KEYS)
                    )
                    and key not in {"$ref", "properties", "required", "type"}
                }
                if unsupported_merge_keys:
                    key = min(str(item) for item in unsupported_merge_keys)
                    raise ValueError(
                        f"Unsupported behavior-bearing {contract} schema feature at "
                        f"{_schema_pointer(child_pointer, key)}: allOf constraint merging"
                    )
            _audit_pydantic_schema_features(
                child,
                pointer=child_pointer,
                contract=contract,
                require_provably_disjoint_one_of=require_provably_disjoint_one_of,
            )


def _audit_wizard_schema_features(value: object, *, pointer: str) -> None:
    _audit_pydantic_schema_features(
        value,
        pointer=pointer,
        contract="Wizard",
        require_provably_disjoint_one_of=True,
    )


def _audit_dashboard_schema_features(value: object, *, pointer: str) -> None:
    _audit_pydantic_schema_features(
        value,
        pointer=pointer,
        contract="Dashboard",
        require_provably_disjoint_one_of=False,
    )


def _normalize_wizard_schema(value: object, *, parent_key: str | None = None) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        normalized = [_normalize_wizard_schema(item) for item in value]
        if parent_key in _SCHEMA_SET_LIKE_KEYS:
            return _deduplicate_sorted_json(normalized)
        if parent_key in _SCHEMA_MULTISET_KEYS:
            return sorted(normalized, key=_canonical_json)
        return normalized
    if not isinstance(value, Mapping):
        raise TypeError(f"Wizard schema contains unsupported value {type(value).__name__}")

    normalized_object: dict[str, JsonValue] = {}
    for key, child in sorted(value.items()):
        if not isinstance(key, str):
            raise TypeError("Wizard schema contains a non-string object key")
        if parent_key not in _SCHEMA_NAMED_MAP_KEYS and (
            _wizard_schema_feature_state(key) is _WizardSchemaFeatureState.DOCUMENTATION_ONLY
        ):
            continue
        normalized_object[key] = _normalize_wizard_schema(child, parent_key=key)
    return normalized_object


def _route_schema(
    operation: dict[str, object],
    *,
    route: str,
    request: bool,
) -> tuple[str | None, bool]:
    if request:
        body = _string_object_dict(operation.get("requestBody"), context=f"{route}.post.requestBody")
        content = _string_object_dict(body.get("content"), context=f"{route}.post.requestBody.content")
        media = _string_object_dict(
            content.get("application/json"),
            context=f"{route}.post.requestBody.content.application/json",
        )
        schema = _string_object_dict(
            media.get("schema"),
            context=f"{route}.post.requestBody.content.application/json.schema",
        )
        return _schema_ref_name(schema, context=f"{route} request schema"), body.get("required") is True

    responses = _string_object_dict(operation.get("responses"), context=f"{route}.post.responses")
    response = _string_object_dict(responses.get("200"), context=f"{route}.post.responses.200")
    content = _string_object_dict(response.get("content"), context=f"{route}.post.responses.200.content")
    media = _string_object_dict(
        content.get("application/json"),
        context=f"{route}.post.responses.200.content.application/json",
    )
    schema = _string_object_dict(
        media.get("schema"),
        context=f"{route}.post.responses.200.content.application/json.schema",
    )
    ref = schema.get("$ref")
    if ref is None:
        return None, False
    return _schema_ref_name(schema, context=f"{route} result schema"), False


def _wizard_schema_dto_name(schema_name: str, *, read: bool = False) -> str:
    suffix = "ReadDTO" if read else "DTO"
    return f"{schema_name}{suffix}"


def _singleton_union_variant_paths(
    schema: object,
    *,
    context: str,
    pointer: str,
) -> dict[str, str]:
    schema_object = _string_object_dict(_normalize_wizard_schema(schema), context=context)
    branches = schema_object.get("oneOf")
    if not isinstance(branches, list):
        raise ValueError(f"{context}.oneOf must be a list")

    variants: dict[str, str] = {}
    for index, branch in enumerate(branches):
        branch_object = _string_object_dict(branch, context=f"{context}.oneOf[{index}]")
        properties = _string_object_dict(
            branch_object.get("properties"),
            context=f"{context}.oneOf[{index}].properties",
        )
        type_schema = _string_object_dict(
            properties.get("type"),
            context=f"{context}.oneOf[{index}].properties.type",
        )
        enum = type_schema.get("enum")
        if not isinstance(enum, list) or len(enum) != 1 or not isinstance(enum[0], str):
            raise ValueError(f"{context}.oneOf[{index}].properties.type.enum must contain one string")
        tag = enum[0]
        if tag in variants:
            raise ValueError(f"{context} contains duplicate type tag {tag!r}")
        variants[tag] = f"{pointer}/oneOf/{index}"
    return dict(sorted(variants.items()))


def build_wizard_schema_meta(spec: Mapping[str, object]) -> WizardSchemaMeta:
    """Extract the API-v3 envelope and embedded Wizard V1 contract from OpenAPI."""

    paths = _string_object_dict(spec.get("paths"), context="paths")
    discovered_routes = {path for path in paths if "WizardChart" in path}
    if discovered_routes != set(_WIZARD_ROUTES):
        raise ValueError(
            f"Wizard routes differ from the expected contract: "
            f"expected {sorted(_WIZARD_ROUTES)}, got {sorted(discovered_routes)}"
        )
    route_meta: dict[str, WizardRouteMeta] = {}
    roots: set[str] = set()
    for route in _WIZARD_ROUTES:
        path_item = _string_object_dict(paths.get(route), context=route)
        operation = _string_object_dict(path_item.get("post"), context=f"{route}.post")
        request_schema, request_body_required = _route_schema(operation, route=route, request=True)
        assert request_schema is not None
        result_schema, _ = _route_schema(operation, route=route, request=False)
        roots.add(request_schema)
        if result_schema is not None:
            roots.add(result_schema)
        route_meta[route] = {
            "method": "post",
            "request_schema": request_schema,
            "result_schema": result_schema,
            "request_body_required": request_body_required,
            "request_dto": _wizard_schema_dto_name(request_schema),
            "result_dto": _wizard_schema_dto_name(result_schema, read=True) if result_schema is not None else None,
        }

    schemas = _schemas(spec)
    reached: set[str] = set()
    queue = sorted(roots)
    normalized_schemas: dict[str, JsonValue] = {}
    while queue:
        name = queue.pop(0)
        if name in reached:
            continue
        schema = schemas.get(name)
        if schema is None:
            raise ValueError(f"Wizard schema graph references missing component {name!r}")
        reached.add(name)
        _audit_wizard_schema_features(schema, pointer=f"/schemas/{_json_pointer_token(name)}")
        normalized_schemas[name] = _normalize_wizard_schema(schema)
        queue.extend(sorted(_schema_refs(schema) - reached - set(queue)))

    config = schemas.get("WizardV1ConfigSchema")
    if config is None:
        raise ValueError("Wizard schema graph does not contain WizardV1ConfigSchema")
    config_properties = _string_object_dict(
        config.get("properties"),
        context="WizardV1ConfigSchema.properties",
    )
    visualization_variants = _singleton_union_variant_paths(
        config_properties.get("visualization"),
        context="WizardV1ConfigSchema.properties.visualization",
        pointer="/schemas/WizardV1ConfigSchema/properties/visualization",
    )
    geo_layer_variants = _singleton_union_variant_paths(
        schemas.get("WizardV1GeolayerLayerSchema"),
        context="WizardV1GeolayerLayerSchema",
        pointer="/schemas/WizardV1GeolayerLayerSchema",
    )
    combined_layer_variants = _singleton_union_variant_paths(
        schemas.get("WizardV1CombinedChartLayerSchema"),
        context="WizardV1CombinedChartLayerSchema",
        pointer="/schemas/WizardV1CombinedChartLayerSchema",
    )

    wizard = schemas.get("WizardV1")
    if wizard is None:
        raise ValueError("Wizard schema graph does not contain WizardV1")
    wizard_properties = _string_object_dict(wizard.get("properties"), context="WizardV1.properties")
    version_schema = _string_object_dict(wizard_properties.get("version"), context="WizardV1.properties.version")
    version_enum = version_schema.get("enum")
    if (
        not isinstance(version_enum, list)
        or len(version_enum) != 1
        or not isinstance(version_enum[0], int)
        or isinstance(version_enum[0], bool)
    ):
        raise ValueError("WizardV1.properties.version.enum must contain one integer")

    info = _string_object_dict(spec.get("info"), context="info")
    api_version = info.get("version")
    if not isinstance(api_version, str):
        raise ValueError("info.version must be a string")

    inventory: WizardInventory = {
        "routes": len(route_meta),
        "roots": len(roots),
        "schemas": len(reached),
        "visualizations": len(visualization_variants),
        "geo_layers": len(geo_layer_variants),
        "combined_layers": len(combined_layer_variants),
    }
    return {
        "api_version": api_version,
        "wizard_version": version_enum[0],
        "routes": route_meta,
        "roots": sorted(roots),
        "schemas": dict(sorted(normalized_schemas.items())),
        "visualizations": sorted(visualization_variants),
        "geo_layers": sorted(geo_layer_variants),
        "combined_layers": sorted(combined_layer_variants),
        "visualization_variants": visualization_variants,
        "geo_layer_variants": geo_layer_variants,
        "combined_layer_variants": combined_layer_variants,
        "inventory": inventory,
    }


def build_dashboard_contract_meta(spec: Mapping[str, object]) -> DashboardContractMeta:
    """Extract the focused Dashboard V2 roots and their transitive schema closure."""

    schemas = _schemas(spec)
    missing_roots = sorted(set(_DASHBOARD_V2_ROOTS) - schemas.keys())
    if missing_roots:
        raise ValueError(f"Dashboard V2 contract is missing roots: {missing_roots}")

    reached: set[str] = set()
    queue = list(_DASHBOARD_V2_ROOTS)
    normalized_schemas: dict[str, JsonValue] = {}
    while queue:
        name = queue.pop(0)
        if name in reached:
            continue
        schema = schemas.get(name)
        if schema is None:
            raise ValueError(f"Dashboard V2 schema graph references missing component {name!r}")
        reached.add(name)
        _audit_dashboard_schema_features(schema, pointer=f"/schemas/{_json_pointer_token(name)}")
        normalized_schemas[name] = _normalize_wizard_schema(schema)
        queue.extend(sorted(_schema_refs(schema) - reached - set(queue)))

    return {
        "roots": list(_DASHBOARD_V2_ROOTS),
        "schemas": dict(sorted(normalized_schemas.items())),
    }


def wizard_schema_fingerprint(meta: WizardSchemaMeta) -> str:
    canonical = normalize_json_object(meta, context="Wizard schema metadata")
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def _wizard_value_structure(value: object, *, context: str) -> WizardValueStructure:
    schema = _string_object_dict(value, context=context)
    enum = schema.get("enum")
    if enum is None:
        return {}
    if not isinstance(enum, list) or not all(isinstance(item, str) for item in enum):
        raise ValueError(f"{context}.enum must contain only strings")
    return {"enum": list(enum)}


def _wizard_resolved_schema(
    meta: WizardSchemaMeta,
    value: object,
    *,
    context: str,
) -> dict[str, object]:
    schema = _string_object_dict(value, context=context)
    ref = schema.get("$ref")
    if ref is None:
        return schema
    if not isinstance(ref, str):
        raise ValueError(f"{context}.$ref must be a string")
    schema_name = _schema_ref_name(schema, context=context)
    return _string_object_dict(meta["schemas"].get(schema_name), context=schema_name)


def _wizard_schema_allows_null(
    meta: WizardSchemaMeta,
    value: object,
    *,
    context: str,
) -> bool:
    schema = _wizard_resolved_schema(meta, value, context=context)
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for union_key in ("anyOf", "oneOf"):
        branches = schema.get(union_key)
        if branches is None:
            continue
        if not isinstance(branches, list):
            raise ValueError(f"{context}.{union_key} must be a list")
        return any(
            _wizard_schema_allows_null(
                meta,
                branch,
                context=f"{context}.{union_key}[{index}]",
            )
            for index, branch in enumerate(branches)
        )
    return False


def build_wizard_field_structure(meta: WizardSchemaMeta) -> WizardFieldStructure:
    """Build focused property metadata used to project Wizard field snapshots."""

    field_schema = _wizard_resolved_schema(
        meta,
        meta["schemas"].get("WizardFieldSchema"),
        context="WizardFieldSchema",
    )
    branches = field_schema.get("anyOf")
    if not isinstance(branches, list):
        raise ValueError("WizardFieldSchema.anyOf must be a list")

    direct_candidates: list[dict[str, object]] = []
    for index, raw_branch in enumerate(branches):
        branch = _wizard_resolved_schema(
            meta,
            raw_branch,
            context=f"WizardFieldSchema.anyOf[{index}]",
        )
        properties = _string_object_dict(
            branch.get("properties"),
            context=f"WizardFieldSchema.anyOf[{index}].properties",
        )
        required_value = branch.get("required", [])
        if not isinstance(required_value, list) or not all(isinstance(item, str) for item in required_value):
            raise ValueError(f"WizardFieldSchema.anyOf[{index}].required must contain strings")
        if {"guid", "datasetId"} <= properties.keys() and {"guid", "datasetId"} <= set(required_value):
            direct_candidates.append(properties)
    if len(direct_candidates) != 1:
        raise ValueError(
            "WizardFieldSchema.anyOf must contain exactly one direct-field branch requiring guid and datasetId"
        )
    direct_properties = sorted(direct_candidates[0].keys() - {"guid", "datasetId"})

    config = _wizard_resolved_schema(
        meta,
        meta["schemas"].get("WizardV1ConfigSchema"),
        context="WizardV1ConfigSchema",
    )
    config_properties = _string_object_dict(config.get("properties"), context="WizardV1ConfigSchema.properties")
    sources = _wizard_resolved_schema(
        meta,
        config_properties.get("sources"),
        context="WizardV1ConfigSchema.properties.sources",
    )
    source_properties = _string_object_dict(
        sources.get("properties"),
        context="WizardV1ConfigSchema.properties.sources.properties",
    )
    updates = _wizard_resolved_schema(
        meta,
        source_properties.get("updates"),
        context="WizardV1ConfigSchema.properties.sources.properties.updates",
    )
    update_item = _wizard_resolved_schema(
        meta,
        updates.get("items"),
        context="WizardV1ConfigSchema.properties.sources.properties.updates.items",
    )
    update_properties = _string_object_dict(
        update_item.get("properties"),
        context="WizardV1ConfigSchema.properties.sources.properties.updates.items.properties",
    )
    update_field = _wizard_resolved_schema(
        meta,
        update_properties.get("field"),
        context="WizardV1ConfigSchema.properties.sources.properties.updates.items.properties.field",
    )
    field_properties = _string_object_dict(
        update_field.get("properties"),
        context="WizardV1ConfigSchema.properties.sources.properties.updates.items.properties.field.properties",
    )
    nullable_properties = [
        name
        for name, value in sorted(field_properties.items())
        if _wizard_schema_allows_null(
            meta,
            value,
            context=(
                f"WizardV1ConfigSchema.properties.sources.properties.updates.items.properties.field.properties.{name}"
            ),
        )
    ]
    return {
        "direct_properties": tuple(direct_properties),
        "update_properties": tuple(sorted(field_properties)),
        "nullable_update_properties": tuple(nullable_properties),
    }


def _wizard_slot_structures(
    properties: Mapping[str, object],
    required: set[str],
    *,
    context: str,
) -> dict[str, WizardSlotStructure]:
    slots: dict[str, WizardSlotStructure] = {}
    for property_name, raw_property in sorted(properties.items()):
        if not isinstance(raw_property, dict):
            continue
        nested_properties = raw_property.get("properties")
        if not isinstance(nested_properties, dict) or "items" not in nested_properties:
            continue
        nested_required_value = raw_property.get("required", [])
        if not isinstance(nested_required_value, list) or not all(
            isinstance(item, str) for item in nested_required_value
        ):
            raise ValueError(f"{context}.{property_name}.required must contain strings")
        settings: dict[str, WizardValueStructure] = {}
        raw_settings = nested_properties.get("settings")
        if isinstance(raw_settings, dict):
            setting_properties = raw_settings.get("properties")
            if isinstance(setting_properties, dict):
                settings = {
                    name: _wizard_value_structure(
                        value,
                        context=f"{context}.{property_name}.settings.{name}",
                    )
                    for name, value in sorted(setting_properties.items())
                }
        slots[property_name] = {
            "required": property_name in required,
            "items_required": "items" in nested_required_value,
            "settings": settings,
        }
    return slots


def _wizard_layer_structures(
    meta: WizardSchemaMeta,
    schema_name: str,
    *,
    context: str,
) -> dict[str, WizardLayerStructure]:
    schema = _string_object_dict(meta["schemas"].get(schema_name), context=schema_name)
    branches = schema.get("oneOf")
    if not isinstance(branches, list):
        raise ValueError(f"{schema_name}.oneOf must be a list")
    result: dict[str, WizardLayerStructure] = {}
    for index, raw_branch in enumerate(branches):
        branch = _string_object_dict(raw_branch, context=f"{context} branch {index}")
        properties = _string_object_dict(
            branch.get("properties"),
            context=f"{context} branch {index}.properties",
        )
        type_schema = _string_object_dict(
            properties.get("type"),
            context=f"{context} branch {index}.properties.type",
        )
        type_enum = type_schema.get("enum")
        if not isinstance(type_enum, list) or len(type_enum) != 1 or not isinstance(type_enum[0], str):
            raise ValueError(f"{context} branch {index} requires one string type discriminator")
        layer_type = type_enum[0]
        required_value = branch.get("required", [])
        if not isinstance(required_value, list) or not all(isinstance(item, str) for item in required_value):
            raise ValueError(f"{context} branch {layer_type!r}.required must contain strings")
        required = set(required_value)
        raw_layer_settings = properties.get("layerSettings")
        layer_settings: dict[str, WizardValueStructure] = {}
        if isinstance(raw_layer_settings, dict):
            setting_properties = raw_layer_settings.get("properties")
            if isinstance(setting_properties, dict):
                layer_settings = {
                    name: _wizard_value_structure(
                        value,
                        context=f"{context} {layer_type}.layerSettings.{name}",
                    )
                    for name, value in sorted(setting_properties.items())
                }
        result[layer_type] = {
            "properties": sorted(properties),
            "required": sorted(required),
            "slots": _wizard_slot_structures(
                properties,
                required,
                context=f"{context} {layer_type}",
            ),
            "layer_settings": layer_settings,
        }
    return dict(sorted(result.items()))


def build_wizard_visualization_structure(meta: WizardSchemaMeta) -> dict[str, WizardVisualizationStructure]:
    """Build the compact runtime registry for Wizard V1 visualization structure."""

    config = _string_object_dict(meta["schemas"]["WizardV1ConfigSchema"], context="WizardV1ConfigSchema")
    config_properties = _string_object_dict(config.get("properties"), context="WizardV1ConfigSchema.properties")
    visualization = _string_object_dict(
        config_properties.get("visualization"),
        context="WizardV1ConfigSchema.properties.visualization",
    )
    branches = visualization.get("oneOf")
    if not isinstance(branches, list):
        raise ValueError("WizardV1ConfigSchema.properties.visualization.oneOf must be a list")

    result: dict[str, WizardVisualizationStructure] = {}
    for index, raw_branch in enumerate(branches):
        branch = _string_object_dict(raw_branch, context=f"Wizard visualization branch {index}")
        properties = _string_object_dict(
            branch.get("properties"),
            context=f"Wizard visualization branch {index}.properties",
        )
        type_schema = _string_object_dict(
            properties.get("type"),
            context=f"Wizard visualization branch {index}.properties.type",
        )
        type_enum = type_schema.get("enum")
        if not isinstance(type_enum, list) or len(type_enum) != 1 or not isinstance(type_enum[0], str):
            raise ValueError(f"Wizard visualization branch {index} requires one string type discriminator")
        visualization_type = type_enum[0]
        required_value = branch.get("required", [])
        if not isinstance(required_value, list) or not all(isinstance(item, str) for item in required_value):
            raise ValueError(f"Wizard visualization branch {visualization_type!r}.required must contain strings")
        required = set(required_value)

        chart_settings: dict[str, WizardValueStructure] = {}
        raw_chart_settings = properties.get("chartSettings")
        if isinstance(raw_chart_settings, dict):
            chart_setting_properties = raw_chart_settings.get("properties")
            if isinstance(chart_setting_properties, dict):
                chart_settings = {
                    name: _wizard_value_structure(
                        value,
                        context=f"Wizard visualization {visualization_type}.chartSettings.{name}",
                    )
                    for name, value in sorted(chart_setting_properties.items())
                }

        slots = _wizard_slot_structures(
            properties,
            required,
            context=f"Wizard visualization {visualization_type}",
        )
        layers: dict[str, WizardLayerStructure] = {}
        raw_layers = properties.get("layers")
        if isinstance(raw_layers, dict):
            raw_items = raw_layers.get("items")
            if isinstance(raw_items, dict) and isinstance(raw_items.get("$ref"), str):
                schema_name = _schema_ref_name(
                    raw_items,
                    context=f"Wizard visualization {visualization_type}.layers.items",
                )
                layers = _wizard_layer_structures(
                    meta,
                    schema_name,
                    context=f"Wizard visualization {visualization_type} layer",
                )

        result[visualization_type] = {
            "properties": sorted(properties),
            "required": sorted(required),
            "slots": slots,
            "chart_settings": chart_settings,
            "layers": layers,
        }
    return dict(sorted(result.items()))


def _display_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _diff_json(before: object, after: object, *, pointer: str, lines: list[str]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        before_keys = {key for key in before if isinstance(key, str)}
        after_keys = {key for key in after if isinstance(key, str)}
        if len(before_keys) != len(before) or len(after_keys) != len(after):
            raise TypeError("Wizard manifest diff requires string object keys")
        for key in sorted(before_keys | after_keys):
            child_pointer = f"{pointer}/{_json_pointer_token(key)}"
            if key not in before:
                lines.append(f"+ {child_pointer}: {_display_json(after[key])}")
            elif key not in after:
                lines.append(f"- {child_pointer}: {_display_json(before[key])}")
            else:
                _diff_json(before[key], after[key], pointer=child_pointer, lines=lines)
        return
    if type(before) is type(after) and before == after:
        return
    lines.append(f"~ {pointer or '/'}: {_display_json(before)} -> {_display_json(after)}")


def diff_wizard_schema_meta(before: WizardSchemaMeta, after: WizardSchemaMeta) -> str:
    """Render a stable JSON-pointer diff for two normalized Wizard manifests."""

    lines: list[str] = []
    _diff_json(before, after, pointer="", lines=lines)
    return "\n".join(lines) if lines else "No structural changes."


def _safe_name(name: str) -> str:
    return f"{name}_" if keyword.iskeyword(name) or name in RESERVED_METHODS else name


_CAMEL_SPLIT_RE = re.compile(r"[-_]|(?<=[a-z0-9])(?=[A-Z])")
_EDITOR_CREATE_SCHEMA_RE = re.compile(r"^CreateEditor(?P<ui_name>[A-Z][A-Za-z0-9]*?)(?:Node)?Entry$")
_EDITOR_FACTORY_METHOD_OVERRIDES = {
    "metric_node": "indicator",
}
_CONNECTOR_DEFAULT_OVERRIDES: dict[tuple[str, str], dict[str, object]] = {
    ("yateam", "ch_over_yt"): {"additional_cluster": ""},
}
_CONNECTOR_FIELD_ENUM_OVERRIDES: dict[tuple[str, str], dict[str, list[object]]] = {
    ("enterprise", "clickhouse"): {"secure": ["on", "off"]},
    ("yacloud", "clickhouse"): {"secure": ["on", "off"]},
    ("yateam", "clickhouse"): {"secure": ["on", "off"]},
}


def _class_name(value: str, suffix: str) -> str:
    return "".join(part.capitalize() for part in _CAMEL_SPLIT_RE.split(value) if part) + suffix


def _editor_factory_method_name(wire_type: str, schema_name: str) -> str:
    match = _EDITOR_CREATE_SCHEMA_RE.fullmatch(schema_name)
    if match is None or match.group("ui_name") == "Node":
        raise ValueError(
            f"Editor factory method cannot be derived from schema {schema_name!r}; "
            "expected CreateEditor<UiName>[Node]Entry"
        )
    method = _EDITOR_FACTORY_METHOD_OVERRIDES.get(wire_type, to_snake(match.group("ui_name")))
    if not method.isidentifier() or keyword.iskeyword(method) or method in RESERVED_METHODS:
        raise ValueError(
            f"Editor factory method {method!r} derived from schema {schema_name!r} "
            f"for wire type {wire_type!r} is not a safe public method name"
        )
    return method


def _visualization_factory_methods(visualization_types: list[str], *, family: str) -> dict[str, str]:
    methods: dict[str, str] = {}
    owners: dict[str, str] = {}
    for visualization_type in visualization_types:
        method = factory_method_name(visualization_type)
        if not method.isidentifier() or keyword.iskeyword(method) or method in RESERVED_METHODS:
            raise ValueError(
                f"{family} factory method {method!r} derived from visualization type "
                f"{visualization_type!r} is not a safe public method name"
            )
        previous_visualization_type = owners.get(method)
        if previous_visualization_type is not None:
            raise ValueError(
                f"{family} factory method collision: visualization types {previous_visualization_type!r} "
                f"and {visualization_type!r} both map to {method!r}"
            )
        owners[method] = visualization_type
        methods[visualization_type] = method
    return methods


def _node_class_name(wire_type: str) -> str:
    return "".join(part.capitalize() for part in wire_type.replace("-", "_").split("_"))


def _ql_class_name(viz_id: str) -> str:
    return "Ql" + viz_id[0].upper() + viz_id[1:] + "ChartCreate"


def _field_type(schema: dict[str, object]) -> str:
    enum = schema.get("enum")
    if isinstance(enum, list):
        return "enum"
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        raw_type = next((item for item in raw_type if item != "null"), "object")
    if raw_type is None and "default" in schema and schema["default"] is not None:
        default = schema["default"]
        if isinstance(default, bool):
            return "boolean"
        if isinstance(default, int):
            return "integer"
        if isinstance(default, float):
            return "number"
        if isinstance(default, str):
            return "string"
        if isinstance(default, list):
            return "array"
        if isinstance(default, dict):
            return "object"
    return str(raw_type or "object")


def _annotation_for_schema_type(field_type: str) -> str:
    if field_type == "string":
        return "str"
    if field_type == "integer":
        return "int"
    if field_type == "number":
        return "float"
    if field_type == "boolean":
        return "bool"
    if field_type == "array":
        return "Sequence[object]"
    if field_type == "object":
        return "Mapping[str, object]"
    return "object"


def _annotation_for_field(field: str, meta: ConnectorMeta) -> str:
    enum_values = meta["enum_restrictions"].get(field)
    if enum_values and all(isinstance(value, str) for value in enum_values):
        return f"Literal[{', '.join(repr(value) for value in enum_values)}]"
    field_meta = meta["fields"].get(field)
    field_type = field_meta["type"] if field_meta is not None else "object"
    return _annotation_for_schema_type(field_type)


def _connector_meta(
    schemas: dict[str, dict[str, object]],
    connector: str,
    ref: str,
    installation: str,
) -> ConnectorMeta:
    schema = schemas[_ref_name(ref)]
    properties = _schema_dict(schema.get("properties", {}), context=f"{connector}.properties")
    required = set(_string_list(schema.get("required", []), context=f"{connector}.required"))
    fields: dict[str, FieldMeta] = {}
    defaults: dict[str, object] = {}
    enums: dict[str, list[object]] = {}
    for field, field_schema in sorted(properties.items()):
        if field in READ_ONLY_FIELDS or field_schema.get("readOnly"):
            continue
        fields[field] = {"type": _field_type(field_schema)}
        if "default" in field_schema and field_schema["default"] is not None:
            defaults[field] = field_schema["default"]
        enum_values = field_schema.get("enum")
        if isinstance(enum_values, list):
            enums[field] = [item for item in enum_values if item is not None]
    for field, default in _CONNECTOR_DEFAULT_OVERRIDES.get((installation, connector), {}).items():
        if field not in fields:
            raise ValueError(f"Default override targets unknown field {installation}.{connector}.{field}")
        defaults[field] = default
    for field, enum_values in _CONNECTOR_FIELD_ENUM_OVERRIDES.get((installation, connector), {}).items():
        if field not in fields:
            raise ValueError(f"Enum override targets unknown field {installation}.{connector}.{field}")
        fields[field]["type"] = "enum"
        enums[field] = list(enum_values)
    return {
        "schema": _ref_name(ref),
        "required": sorted(field for field in required if field in fields and field not in LOCATION_FIELDS),
        "available_fields": sorted(fields),
        "fields": fields,
        "defaults": defaults,
        "enum_restrictions": enums,
    }


def _infer_connection_type(source_type: str, installation: str) -> str:
    lowered = source_type.lower()
    if source_type.startswith("CHYT_USER_AUTH_"):
        return "ch_over_yt_user_auth"
    if source_type.startswith("CHYT_"):
        return "ch_over_yt" if installation == "yateam" else "chyt"
    if source_type.startswith("CHYT_YTSAURUS_"):
        return "chyt"
    prefix_map = {
        "APPMETRICA_API": "appmetrica_api",
        "BIGQUERY": "bigquery",
        "CH_BILLING_ANALYTICS": "ch_billing_analytics",
        "CH_SMB_HEATMAPS": "smb_heatmaps",
        "CH_USAGE_TRACKING_YA_TEAM": "usage_tracking_ya_team",
        "CH_YA_MUSIC_PODCAST_STATS": "ch_ya_music_podcast_stats",
        "CH": "clickhouse",
        "EQUEO": "equeo",
        "EXTRACTOR_1C": "extractor1c",
        "GP": "greenplum",
        "GSHEETS": "gsheets",
        "JSON_API": "json_api",
        "KONTUR_MARKET": "kontur_market",
        "METRIKA_API": "metrika_api",
        "MONITORING": "monitoring",
        "MOYSKLAD": "moysklad",
        "MSSQL": "mssql",
        "MYSQL": "mysql",
        "ORACLE": "oracle",
        "PG": "postgres",
        "PROMQL": "promql",
        "SNOWFLAKE": "snowflake",
        "SOLOMON": "solomon",
        "SPEECHSENSE": "speechsense",
        "TRINO": "trino",
        "YDB": "ydb",
        "YQ": "yq",
    }
    for prefix, connection_type in prefix_map.items():
        if source_type == prefix or source_type.startswith(prefix + "_"):
            return connection_type
    return lowered.split("_", 1)[0]


def _source_params(schemas: dict[str, dict[str, object]], ref: str) -> dict[str, str]:
    source_schema = schemas[_ref_name(ref)]
    source_properties = _schema_dict(source_schema.get("properties", {}), context=f"{ref}.properties")
    parameters = source_properties.get("parameters", {})
    parameter_ref = parameters.get("$ref")
    if not isinstance(parameter_ref, str):
        return {}
    parameter_schema = schemas.get(_ref_name(parameter_ref), {})
    props = _schema_dict(parameter_schema.get("properties", {}), context=f"{parameter_ref}.properties")
    return {name: _annotation_for_schema_type(_field_type(prop_schema)) for name, prop_schema in sorted(props.items())}


def _source_meta(
    schemas: dict[str, dict[str, object]],
    source_type: str,
    ref: str,
    installation: str,
) -> SourceMeta:
    return {
        "schema": _ref_name(ref),
        "method": source_type.lower(),
        "connection_type": _infer_connection_type(source_type, installation),
        "parameters": _source_params(schemas, ref),
    }


def _chart_meta(schemas: dict[str, dict[str, object]]) -> ChartMeta:
    if "CreateEditorChartArgs" not in schemas:
        return {"editor_nodes": {}, "editor_update_nodes": {}}

    create_args = schemas["CreateEditorChartArgs"]
    props = _string_object_dict(create_args.get("properties", {}), context="CreateEditorChartArgs.properties")
    entry = _string_object_dict(props.get("entry", {}), context="CreateEditorChartArgs.entry")
    all_of_raw = entry.get("allOf", [])
    if not isinstance(all_of_raw, list) or not all_of_raw:
        return {"editor_nodes": {}, "editor_update_nodes": {}}

    discriminator_part = _string_object_dict(all_of_raw[0], context="CreateEditorChartArgs.entry.allOf[0]")
    discriminator = _string_object_dict(
        discriminator_part.get("discriminator", {}),
        context="CreateEditorChartArgs.entry.allOf[0].discriminator",
    )
    mapping = _string_mapping(
        discriminator.get("mapping", {}),
        context="CreateEditorChartArgs.entry.allOf[0].discriminator.mapping",
    )

    editor_nodes: dict[str, EditorCreateNodeMeta] = {}
    editor_method_owners: dict[str, str] = {}
    for wire_type, ref in sorted(mapping.items()):
        schema_name = _ref_name(ref)
        if schema_name not in schemas:
            continue
        schema = schemas[schema_name]
        schema_props = _string_object_dict(schema.get("properties", {}), context=f"{schema_name}.properties")
        data_raw = schema_props.get("data", {})
        data_schema = _string_object_dict(data_raw, context=f"{schema_name}.properties.data")
        data_props_raw = data_schema.get("properties", {})
        data_props = _schema_dict(data_props_raw, context=f"{schema_name}.properties.data.properties")
        data_required_raw = data_schema.get("required", [])
        data_required = set(_string_list(data_required_raw, context=f"{schema_name}.properties.data.required"))
        data_fields: dict[str, NodeFieldMeta] = {
            field: {"required": field in data_required} for field in sorted(data_props)
        }
        factory_method = _editor_factory_method_name(wire_type, schema_name)
        previous_wire_type = editor_method_owners.get(factory_method)
        if previous_wire_type is not None:
            raise ValueError(
                f"Editor factory method collision: wire types {previous_wire_type!r} and "
                f"{wire_type!r} both map to {factory_method!r}"
            )
        editor_method_owners[factory_method] = wire_type
        editor_nodes[wire_type] = {
            "wire_type": wire_type,
            "create_schema": schema_name,
            "data_fields": data_fields,
            "factory_method": factory_method,
        }

    update_editor_nodes: dict[str, EditorNodeMeta] = {}
    if "UpdateEditorChartArgs" in schemas:
        update_args = schemas["UpdateEditorChartArgs"]
        update_props = _string_object_dict(
            update_args.get("properties", {}), context="UpdateEditorChartArgs.properties"
        )
        update_entry = _string_object_dict(update_props.get("entry", {}), context="UpdateEditorChartArgs.entry")
        update_discriminator_raw = _string_object_dict(
            update_entry.get("discriminator", {}), context="UpdateEditorChartArgs.entry.discriminator"
        )
        update_mapping = _string_mapping(
            update_discriminator_raw.get("mapping", {}),
            context="UpdateEditorChartArgs.entry.discriminator.mapping",
        )
        for wire_type, ref in sorted(update_mapping.items()):
            schema_name = _ref_name(ref)
            if schema_name not in schemas:
                continue
            schema = schemas[schema_name]
            schema_props = _string_object_dict(schema.get("properties", {}), context=f"{schema_name}.properties")
            data_raw = schema_props.get("data", {})
            data_schema = _string_object_dict(data_raw, context=f"{schema_name}.properties.data")
            data_props_raw = data_schema.get("properties", {})
            data_props = _schema_dict(data_props_raw, context=f"{schema_name}.properties.data.properties")
            data_required_raw = data_schema.get("required", [])
            data_required = set(_string_list(data_required_raw, context=f"{schema_name}.properties.data.required"))
            upd_data_fields: dict[str, NodeFieldMeta] = {
                field: {"required": field in data_required} for field in sorted(data_props)
            }
            update_editor_nodes[wire_type] = {
                "wire_type": wire_type,
                "create_schema": schema_name,
                "data_fields": upd_data_fields,
            }

    return {"editor_nodes": editor_nodes, "editor_update_nodes": update_editor_nodes}


def build_metadata(installations: dict[str, Path]) -> Metadata:
    out: Metadata = {"installations": {}}
    dashboard_contracts: list[tuple[str, DashboardContractMeta]] = []
    ql_factory_methods = sorted(_visualization_factory_methods(sorted(QL_VIZ_SPECS), family="QL").values())
    for installation, spec_path in sorted(installations.items()):
        spec = _load_json(spec_path)
        schemas = _schemas(spec)
        dashboard_contract = build_dashboard_contract_meta(spec)
        dashboard_contracts.append((installation, dashboard_contract))
        connection_discriminator = _string_object_dict(
            schemas["ConnectionCreate"].get("discriminator"),
            context="ConnectionCreate.discriminator",
        )
        source_discriminator = _string_object_dict(
            schemas["DataSourceStrict"].get("discriminator"),
            context="DataSourceStrict.discriminator",
        )
        connection_mapping = _string_mapping(
            connection_discriminator.get("mapping"),
            context="ConnectionCreate.discriminator.mapping",
        )
        source_mapping = _string_mapping(
            source_discriminator.get("mapping"),
            context="DataSourceStrict.discriminator.mapping",
        )
        chart_meta = _chart_meta(schemas)
        installation_metadata: InstallationMetadata = {
            "name": installation,
            "namespaces": NAMESPACES[installation],
            "connectors": {
                connector: _connector_meta(schemas, connector, ref, installation)
                for connector, ref in sorted(connection_mapping.items())
            },
            "dataset_sources": {
                source_type: _source_meta(schemas, source_type, ref, installation)
                for source_type, ref in sorted(source_mapping.items())
            },
            "charts": chart_meta,
            "chart_factories": {
                "wizard": [],
                "ql": ql_factory_methods,
                "editor": sorted(node["factory_method"] for node in chart_meta["editor_nodes"].values()),
            },
        }
        wizard_manifest = build_wizard_schema_meta(spec)
        wizard_structure = build_wizard_visualization_structure(wizard_manifest)
        installation_metadata["wizard"] = {
            "fingerprint": wizard_schema_fingerprint(wizard_manifest),
            "manifest": wizard_manifest,
            "visualization_structure": wizard_structure,
            "field_structure": build_wizard_field_structure(wizard_manifest),
        }
        installation_metadata["chart_factories"]["wizard"] = sorted(
            _visualization_factory_methods(sorted(wizard_structure), family="Wizard").values()
        )
        out["installations"][installation] = installation_metadata
    if dashboard_contracts:
        canonical_installation, canonical_dashboard = dashboard_contracts[0]
        for installation, candidate in dashboard_contracts[1:]:
            if candidate != canonical_dashboard:
                raise ValueError(
                    f"Dashboard V2 schema closure differs between {canonical_installation!r} and {installation!r}"
                )
        out["dashboard"] = canonical_dashboard
    editor_methods_by_wire_type: dict[str, tuple[str, str]] = {}
    for installation, info in sorted(out["installations"].items()):
        for wire_type, node_meta in sorted(info["charts"]["editor_nodes"].items()):
            method = node_meta["factory_method"]
            previous = editor_methods_by_wire_type.get(wire_type)
            if previous is not None and previous[1] != method:
                raise ValueError(
                    f"Editor wire type {wire_type!r} maps to factory methods "
                    f"{previous[1]!r} in {previous[0]!r} and {method!r} in {installation!r}"
                )
            editor_methods_by_wire_type[wire_type] = (installation, method)
    return out


def _emit_literal(value: object) -> str:
    return repr(value)


def _wizard_python_field_name(wire_name: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", wire_name).replace("-", "_").lower()
    if not value.isidentifier():
        value = re.sub(r"\W", "_", value)
    if value[:1].isdigit():
        value = f"field_{value}"
    return f"{value}_" if keyword.iskeyword(value) else value


def _wizard_inline_model_name(path: tuple[str, ...], *, read: bool) -> str:
    stem = "".join(part[:1].upper() + part[1:] for value in path for part in _CAMEL_SPLIT_RE.split(value) if part)
    return f"{stem}{'ReadDTO' if read else 'DTO'}"


def _wizard_contract(metadata: Metadata) -> WizardContractMeta | None:
    contracts = [
        (installation, info["wizard"])
        for installation, info in sorted(metadata["installations"].items())
        if "wizard" in info
    ]
    if not contracts:
        return None
    canonical_installation, canonical = contracts[0]
    for installation, candidate in contracts[1:]:
        if candidate["fingerprint"] != canonical["fingerprint"]:
            diff = diff_wizard_schema_meta(canonical["manifest"], candidate["manifest"])
            raise ValueError(
                f"Wizard schema fingerprint differs between {canonical_installation!r} and {installation!r}:\n{diff}"
            )
    return canonical


class _PydanticSchemaEmitter:
    """Emit the focused Pydantic subset shared by Wizard and Dashboard schemas."""

    def __init__(
        self,
        schemas: Mapping[str, JsonValue],
        *,
        read: bool,
        contract: str,
        open_schema_refs: Mapping[str, str] | frozenset[str] = frozenset(),
    ) -> None:
        self._schemas = schemas
        self._read = read
        self._contract = contract
        self._open_schema_refs = (
            dict(open_schema_refs)
            if isinstance(open_schema_refs, Mapping)
            else dict.fromkeys(open_schema_refs, "dict[str, JsonValue]")
        )
        self._lines: list[str] = []
        self._emitted: set[str] = set()
        self._emitting: set[str] = set()
        self._definitions: dict[str, str] = {}
        self._definitions_by_schema: dict[str, str] = {}

    def emit(self, schema_names: Iterable[str]) -> str:
        for schema_name in sorted(schema_names):
            self._emit_named(schema_name)
        return "\n".join(self._lines)

    def _model_name(self, path: tuple[str, ...]) -> str:
        return _wizard_inline_model_name(path, read=self._read)

    def _schema_object(self, value: JsonValue, *, context: str) -> dict[str, JsonValue]:
        if not isinstance(value, dict):
            raise TypeError(f"{context} must be an object")
        return value

    def _emit_named(self, schema_name: str) -> str:
        name = _wizard_schema_dto_name(schema_name, read=self._read)
        if name in self._emitted:
            return name
        if name in self._emitting:
            raise ValueError(f"Recursive {self._contract} schema {schema_name!r} is not supported")
        raw = self._schemas.get(schema_name)
        if raw is None:
            raise ValueError(f"{self._contract} contract references missing schema {schema_name!r}")
        schema = self._schema_object(raw, context=f"{self._contract} schema {schema_name}")
        self._emitting.add(name)
        annotation = self._annotation(schema, path=(schema_name,), preferred_name=name)
        if annotation != name:
            self._lines.append(f"{name} = {annotation}")
            self._lines.append("")
            self._emitted.add(name)
        self._emitting.remove(name)
        return name

    def _annotation(
        self,
        schema: dict[str, JsonValue],
        *,
        path: tuple[str, ...],
        preferred_name: str | None = None,
    ) -> str:
        ref = schema.get("$ref")
        if isinstance(ref, str):
            schema_name = _ref_name(ref)
            if schema_name in self._open_schema_refs:
                return self._open_schema_refs[schema_name]
            return self._emit_named(schema_name)

        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            return f"Literal[{', '.join(_emit_literal(value) for value in enum)}]"

        for union_key in ("oneOf", "anyOf"):
            branches = schema.get(union_key)
            if isinstance(branches, list):
                branch_schemas = [
                    self._schema_object(branch, context=f"{'.'.join(path)}.{union_key}[{index}]")
                    for index, branch in enumerate(branches)
                ]
                constrained_nullable_index: int | None = None
                if union_key == "anyOf":
                    non_null_indices = [
                        index
                        for index, branch_schema in enumerate(branch_schemas)
                        if branch_schema.get("type") != "null"
                    ]
                    if (
                        len(non_null_indices) == 1
                        and all(
                            index == non_null_indices[0] or branch_schema.get("type") == "null"
                            for index, branch_schema in enumerate(branch_schemas)
                        )
                        and any(
                            key in branch_schemas[non_null_indices[0]] for key in ("minItems", "minLength", "minimum")
                        )
                    ):
                        constrained_nullable_index = non_null_indices[0]

                annotations: list[str] = []
                constrained_nullable_schema: dict[str, JsonValue] | None = None
                for index, branch_schema in enumerate(branch_schemas):
                    emitted_schema = branch_schema
                    if index == constrained_nullable_index:
                        constrained_nullable_schema = branch_schema
                        emitted_schema = {
                            key: value
                            for key, value in branch_schema.items()
                            if key not in {"minItems", "minLength", "minimum"}
                        }
                    annotations.append(
                        self._annotation(
                            emitted_schema,
                            path=(*path, f"{union_key}{index}"),
                        )
                    )
                annotation = " | ".join(dict.fromkeys(annotations))
                if constrained_nullable_schema is not None:
                    constrained_type = constrained_nullable_schema.get("type")
                    if constrained_type == "string":
                        annotation = self._with_constraints(
                            annotation,
                            constrained_nullable_schema,
                            length_key="minLength",
                        )
                    elif constrained_type == "array":
                        annotation = self._with_constraints(
                            annotation,
                            constrained_nullable_schema,
                            length_key="minItems",
                        )
                    elif constrained_type in {"integer", "number"}:
                        annotation = self._with_constraints(annotation, constrained_nullable_schema, minimum=True)
                discriminator = schema.get("discriminator")
                discriminator_property = discriminator.get("propertyName") if isinstance(discriminator, dict) else None
                # Pydantic 2.0 cannot reuse a discriminated type alias inside nested models.
                # Dashboard variants already carry disjoint Literal tags, so their plain union
                # preserves validation semantics across the supported Pydantic range.
                if isinstance(discriminator_property, str) and self._contract != "Dashboard":
                    property_name = _wizard_python_field_name(discriminator_property)
                    return f"Annotated[{annotation}, Field(discriminator={property_name!r})]"
                return annotation

        if isinstance(schema.get("allOf"), list):
            variants = self._all_of_variants(schema, context=".".join(path), seen=frozenset())
            annotations = [
                self._emit_object(
                    variant,
                    path=(*path, f"allOf{index}") if len(variants) > 1 else path,
                    preferred_name=preferred_name if len(variants) == 1 else None,
                )
                for index, variant in enumerate(variants)
            ]
            return " | ".join(dict.fromkeys(annotations))

        raw_type = schema.get("type")
        if isinstance(raw_type, list):
            annotations = [
                self._annotation(
                    {**schema, "type": item},
                    path=(*path, str(item)),
                    preferred_name=preferred_name,
                )
                for item in raw_type
                if isinstance(item, str)
            ]
            return " | ".join(dict.fromkeys(annotations)) or "JsonValue"

        if raw_type == "string":
            return self._with_constraints("str", schema, length_key="minLength")
        if raw_type == "integer":
            return self._with_constraints("int", schema, minimum=True)
        if raw_type == "number":
            return self._with_constraints("float", schema, minimum=True)
        if raw_type == "boolean":
            return "bool"
        if raw_type == "null":
            return "None"
        if raw_type == "array" or "items" in schema or "prefixItems" in schema:
            prefix_items = schema.get("prefixItems")
            if isinstance(prefix_items, list) and prefix_items:
                annotations = [
                    self._annotation(
                        self._schema_object(item, context=f"{'.'.join(path)}.prefixItems[{index}]"),
                        path=(*path, f"item{index}"),
                    )
                    for index, item in enumerate(prefix_items)
                ]
                annotation = f"Annotated[tuple[{', '.join(annotations)}], BeforeValidator(_json_array_to_tuple)]"
                return self._with_constraints(annotation, schema, length_key="minItems")
            items = schema.get("items")
            item_annotation = self._annotation(items, path=(*path, "item")) if isinstance(items, dict) else "JsonValue"
            return self._with_constraints(f"list[{item_annotation}]", schema, length_key="minItems")

        properties = schema.get("properties")
        if raw_type == "object" or isinstance(properties, dict):
            if isinstance(properties, dict) and properties:
                return self._emit_object(schema, path=path, preferred_name=preferred_name)
            additional = schema.get("additionalProperties")
            if additional is False:
                return self._emit_object(schema, path=path, preferred_name=preferred_name)
            if isinstance(additional, dict) and additional:
                value_annotation = self._annotation(additional, path=(*path, "value"))
            else:
                value_annotation = "JsonValue"
            return f"dict[str, {value_annotation}]"

        return "JsonValue"

    @staticmethod
    def _with_constraints(
        annotation: str,
        schema: Mapping[str, JsonValue],
        *,
        length_key: str | None = None,
        minimum: bool = False,
    ) -> str:
        constraints: list[str] = []
        if length_key is not None and isinstance(schema.get(length_key), int):
            constraints.append(f"min_length={schema[length_key]!r}")
        if minimum and isinstance(schema.get("minimum"), (int, float)):
            constraints.append(f"ge={schema['minimum']!r}")
        if not constraints:
            return annotation
        return f"Annotated[{annotation}, Field({', '.join(constraints)})]"

    def _object_extra(self, schema: Mapping[str, JsonValue]) -> str:
        if self._read:
            return "ignore"
        additional = schema.get("additionalProperties")
        return "allow" if additional is True or isinstance(additional, dict) else "forbid"

    @staticmethod
    def _embed_field_alias(annotation: str, alias: str) -> tuple[str, bool]:
        if not annotation.startswith("Annotated["):
            return annotation, False
        head, marker, tail = annotation.rpartition(", Field(")
        if not marker or not tail.endswith(")]"):
            return annotation, False
        field_args = tail[:-2]
        separator = ", " if field_args else ""
        return f"{head}{marker}{field_args}{separator}alias={alias!r})]", True

    def _emit_object(
        self,
        schema: dict[str, JsonValue],
        *,
        path: tuple[str, ...],
        preferred_name: str | None,
    ) -> str:
        canonical = _canonical_json(schema)
        if preferred_name is None:
            existing_name = self._definitions_by_schema.get(canonical)
            if existing_name is not None:
                return existing_name

        name = preferred_name or self._model_name(path)
        previous = self._definitions.get(name)
        if previous is not None:
            if previous != canonical:
                raise ValueError(f"{self._contract} inline model name collision for {name}")
            return name
        self._definitions[name] = canonical

        properties_value = schema.get("properties")
        properties = properties_value if isinstance(properties_value, dict) else {}
        required_value = schema.get("required")
        required = (
            {value for value in required_value if isinstance(value, str)} if isinstance(required_value, list) else set()
        )

        fields: list[tuple[str, str, str, bool, bool]] = []
        for wire_name, raw_field_schema in sorted(properties.items()):
            if not isinstance(raw_field_schema, dict):
                raise TypeError(f"{self._contract} schema {'.'.join(path)}.{wire_name} must be an object")
            python_name = _wizard_python_field_name(wire_name)
            annotation = self._annotation(raw_field_schema, path=(*path, wire_name))
            alias_in_annotation = False
            if python_name != wire_name:
                annotation, alias_in_annotation = self._embed_field_alias(annotation, wire_name)
            fields.append((python_name, wire_name, annotation, wire_name in required, alias_in_annotation))

        extra = self._object_extra(schema)
        self._lines.append(f"class {name}(BaseModel):")
        self._lines.append(f"    model_config = ConfigDict(extra={extra!r}, populate_by_name=True, strict=True)")
        self._lines.append("")
        if not fields:
            self._lines.append("    pass")
        for python_name, wire_name, annotation, is_required, alias_in_annotation in fields:
            alias = (
                f" = Field(alias={wire_name!r})"
                if python_name != wire_name and is_required and not alias_in_annotation
                else ""
            )
            if is_required:
                self._lines.append(f"    {python_name}: {annotation}{alias}")
                continue
            # Pydantic keeps the shared omitted default unvalidated, while an explicitly supplied
            # None is validated against the annotation. Its Any annotation preserves that runtime
            # distinction without making the generated field annotation nullable.
            if python_name != wire_name:
                if alias_in_annotation:
                    self._lines.append(f"    {python_name}: {annotation} = _UNVALIDATED_NONE_DEFAULT")
                else:
                    self._lines.append(
                        f"    {python_name}: {annotation} = "
                        f"Field(default=_UNVALIDATED_NONE_DEFAULT, alias={wire_name!r})"
                    )
            else:
                self._lines.append(f"    {python_name}: {annotation} = _UNVALIDATED_NONE_DEFAULT")
        self._lines.append("")
        self._emitted.add(name)
        self._definitions_by_schema.setdefault(canonical, name)
        return name

    def _object_variants(
        self,
        schema: dict[str, JsonValue],
        *,
        context: str,
        seen: frozenset[str],
    ) -> list[dict[str, JsonValue]]:
        ref = schema.get("$ref")
        if isinstance(ref, str):
            schema_name = _ref_name(ref)
            if schema_name in seen:
                raise ValueError(f"Recursive {self._contract} allOf schema {schema_name!r} is not supported")
            raw = self._schemas.get(schema_name)
            if raw is None:
                raise ValueError(f"{self._contract} contract references missing schema {schema_name!r}")
            return self._object_variants(
                self._schema_object(raw, context=f"{self._contract} schema {schema_name}"),
                context=schema_name,
                seen=seen | {schema_name},
            )
        for union_key in ("oneOf", "anyOf"):
            branches = schema.get(union_key)
            if isinstance(branches, list):
                variants: list[dict[str, JsonValue]] = []
                for index, branch in enumerate(branches):
                    variants.extend(
                        self._object_variants(
                            self._schema_object(branch, context=f"{context}.{union_key}[{index}]"),
                            context=f"{context}.{union_key}[{index}]",
                            seen=seen,
                        )
                    )
                return variants
        if isinstance(schema.get("allOf"), list):
            return self._all_of_variants(schema, context=context, seen=seen)
        if schema.get("type") == "object" or isinstance(schema.get("properties"), dict):
            return [schema]
        raise ValueError(f"{self._contract} allOf member {context} is not an object schema")

    def _all_of_variants(
        self,
        schema: dict[str, JsonValue],
        *,
        context: str,
        seen: frozenset[str],
    ) -> list[dict[str, JsonValue]]:
        all_of = schema.get("allOf")
        if not isinstance(all_of, list):
            return [schema]
        own = {key: value for key, value in schema.items() if key != "allOf"}
        combinations: list[dict[str, JsonValue]] = [own]
        for index, member in enumerate(all_of):
            member_object = self._schema_object(member, context=f"{context}.allOf[{index}]")
            variants = self._object_variants(
                member_object,
                context=f"{context}.allOf[{index}]",
                seen=seen,
            )
            combinations = [self._merge_object_schemas(base, variant) for base in combinations for variant in variants]
        return combinations

    @staticmethod
    def _merge_object_schemas(
        left: dict[str, JsonValue],
        right: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        merged: dict[str, JsonValue] = {"type": "object"}
        properties: dict[str, JsonValue] = {}
        required: set[str] = set()
        for source in (left, right):
            source_properties = source.get("properties")
            if isinstance(source_properties, dict):
                properties.update(source_properties)
            source_required = source.get("required")
            if isinstance(source_required, list):
                required.update(value for value in source_required if isinstance(value, str))
        if properties:
            merged["properties"] = dict(sorted(properties.items()))
        if required:
            required_values: list[JsonValue] = []
            for value in sorted(required):
                required_values.append(value)
            merged["required"] = required_values
        additional_values = [
            source["additionalProperties"] for source in (left, right) if "additionalProperties" in source
        ]
        if False in additional_values:
            merged["additionalProperties"] = False
        elif additional_values:
            merged["additionalProperties"] = additional_values[-1]
        return merged


def _emit_wizard_dto(metadata: Metadata) -> str:
    contract = _wizard_contract(metadata)
    fingerprint = contract["fingerprint"] if contract is not None else None
    visualization_structure = contract["visualization_structure"] if contract is not None else {}
    field_structure: WizardFieldStructure = (
        contract["field_structure"]
        if contract is not None
        else {
            "direct_properties": (),
            "update_properties": (),
            "nullable_update_properties": (),
        }
    )
    strict_models = ""
    read_models = ""
    create_validation = "_validate_wizard_v1_config(self.data)"
    update_validation = "_validate_wizard_v1_config(self.data)"
    entry_model = """class WizardChartEntryReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    version: Literal[1]
    entry_id: str = Field(alias="entryId")
    type: str | None = None
    data: dict[str, JsonValue]
"""
    if contract is not None:
        manifest = contract["manifest"]
        request_schemas = {route_meta["request_schema"] for route_meta in manifest["routes"].values()}
        result_schemas: set[str] = set()
        for route_meta in manifest["routes"].values():
            result_schema = route_meta["result_schema"]
            if result_schema is not None:
                result_schemas.add(result_schema)
        update_request_schema = manifest["routes"]["/rpc/updateWizardChart"]["request_schema"]
        strict_models = _PydanticSchemaEmitter(
            manifest["schemas"],
            read=False,
            contract="Wizard",
        ).emit(request_schemas)
        read_models = _PydanticSchemaEmitter(
            manifest["schemas"],
            read=True,
            contract="Wizard",
            open_schema_refs=frozenset({"WizardV1ConfigSchema"}),
        ).emit((*result_schemas, update_request_schema, "WizardV1ConfigSchema"))
        create_request_dto = manifest["routes"]["/rpc/createWizardChart"]["request_dto"]
        update_request_read_dto = _wizard_schema_dto_name(update_request_schema, read=True)
        create_validation = f"{create_request_dto}.model_validate(self.to_payload())"
        update_validation = (
            f"{update_request_read_dto}.model_validate(self.to_payload())\n"
            "        WizardV1ConfigSchemaReadDTO.model_validate(self.data)"
        )
        entry_model = f"WizardChartEntryReadDTO = {_wizard_schema_dto_name('WizardV1', read=True)}"
    field_structure_lines = "\n".join(
        f"    {name!r}: {values!r},"
        for name, values in (
            ("direct_properties", field_structure["direct_properties"]),
            ("nullable_update_properties", field_structure["nullable_update_properties"]),
            ("update_properties", field_structure["update_properties"]),
        )
    )

    return f"""
WIZARD_SCHEMA_FINGERPRINT: str | None = {fingerprint!r}
WIZARD_VISUALIZATION_STRUCTURE: WizardVisualizationRegistry = {visualization_structure!r}
WIZARD_FIELD_STRUCTURE: WizardFieldStructure = {{
{field_structure_lines}
}}

{strict_models}
{read_models}

def _validate_wizard_v1_config(data: Mapping[str, JsonValue]) -> None:
    sources = data.get("sources")
    visualization = data.get("visualization")
    if not isinstance(sources, Mapping) or not isinstance(sources.get("datasetsIds"), list):
        raise ValueError("Wizard V1 config sources.datasetsIds must be an array")
    supported = sorted(WIZARD_VISUALIZATION_STRUCTURE)
    if not supported:
        raise NotSupportedError("Wizard API v3 is unavailable for this installation")
    if not isinstance(visualization, Mapping) or visualization.get("type") not in supported:
        raise ValueError(f"Wizard V1 config visualization.type must be one of {{sorted(supported)}}")


class WizardChartCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    data: dict[str, JsonValue]
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _validate_data(self) -> WizardChartCreateDTO:
        {create_validation}
        return self

    def to_payload(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {{"data": dict(self.data)}}
        if self.key is not None:
            payload["key"] = self.key
        if self.name is not None:
            payload["name"] = self.name
        if self.workbook_id is not None:
            payload["workbookId"] = self.workbook_id
        if self.annotation is not None:
            payload["annotation"] = dict(self.annotation)
        return payload


class WizardChartUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    chart_id: str = Field(serialization_alias="chartId")
    mode: Literal["save", "publish"]
    data: dict[str, JsonValue]
    annotation: dict[str, JsonValue] | None = None
    rev_id: str | None = Field(default=None, serialization_alias="revId")

    @model_validator(mode="after")
    def _validate_data(self) -> WizardChartUpdateDTO:
        {update_validation}
        return self

    def to_payload(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {{
            "chartId": self.chart_id,
            "mode": self.mode,
            "data": dict(self.data),
        }}
        if self.annotation is not None:
            payload["annotation"] = dict(self.annotation)
        if self.rev_id is not None:
            payload["revId"] = self.rev_id
        return payload


{entry_model}

class WizardChartReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entry: WizardChartEntryReadDTO
    raw: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class WizardChartGetArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chart_id: str = Field(serialization_alias="chartId")
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"chartId": self.chart_id}}
        if self.workbook_id is not None:
            payload["workbookId"] = self.workbook_id
        return payload


class WizardChartDeleteArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chart_id: str = Field(serialization_alias="chartId")

    def to_payload(self) -> dict[str, object]:
        return {{"chartId": self.chart_id}}
"""


def _emit_chart_dto(metadata: Metadata) -> str:
    all_editor_nodes: dict[str, EditorCreateNodeMeta] = {}
    installation_editor_types: dict[str, list[str]] = {}
    for installation, info in sorted(metadata["installations"].items()):
        node_types = sorted(info["charts"]["editor_nodes"])
        installation_editor_types[installation] = node_types
        for wire_type, node_meta in info["charts"]["editor_nodes"].items():
            if wire_type not in all_editor_nodes:
                all_editor_nodes[wire_type] = node_meta

    lines: list[str] = []

    lines.append("")
    lines.append("INSTALLATION_EDITOR_NODE_TYPES: dict[str, frozenset[str]] = {")
    for installation, node_types in sorted(installation_editor_types.items()):
        lines.append(f"    {installation!r}: frozenset({node_types!r}),")
    lines.append("}")
    lines.append("")

    lines.append(_emit_wizard_dto(metadata))

    lines.append("""
class QLChartCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    template: Literal["ql"]
    data: Mapping[str, object]
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: Mapping[str, object] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "template": self.template,
            "data": dict(self.data),
        }
        if self.key is not None:
            payload["key"] = self.key
        if self.name is not None:
            payload["name"] = self.name
        if self.workbook_id is not None:
            payload["workbookId"] = self.workbook_id
        if self.annotation is not None:
            payload["annotation"] = dict(self.annotation)
        return payload


class QLChartUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    template: Literal["ql"]
    mode: Literal["save", "publish"]
    data: Mapping[str, object]
    annotation: Mapping[str, object] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "entryId": self.entry_id,
            "template": self.template,
            "mode": self.mode,
            "data": dict(self.data),
        }
        if self.annotation is not None:
            payload["annotation"] = dict(self.annotation)
        return payload


class QLChartReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entry_id: str | None = Field(default=None, alias="entryId")
    type: str | None = None
    data: dict[str, object] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {**value, "raw": dict(value)}
        return value


class QLChartGetArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chart_id: str = Field(serialization_alias="chartId")
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"chartId": self.chart_id}
        if self.workbook_id is not None:
            payload["workbookId"] = self.workbook_id
        return payload


class QLChartDeleteArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chart_id: str = Field(serialization_alias="chartId")

    def to_payload(self) -> dict[str, object]:
        return {"chartId": self.chart_id}
""")

    for wire_type, node_meta in sorted(all_editor_nodes.items()):
        cls_prefix = _node_class_name(wire_type)
        data_fields = node_meta["data_fields"]

        data_cls = f"{cls_prefix}NodeDataDTO"
        lines.append(f"class {data_cls}(BaseModel):")
        lines.append('    model_config = ConfigDict(extra="forbid", populate_by_name=True)')
        lines.append("")
        required_fields = sorted(f for f, m in data_fields.items() if m["required"])
        optional_fields = sorted(f for f, m in data_fields.items() if not m["required"])
        for field in required_fields:
            lines.append(f"    {field}: str")
        for field in optional_fields:
            lines.append(f"    {field}: str | None = None")
        lines.append("")

        create_cls = f"{cls_prefix}NodeEntryCreateDTO"
        lines.append(f"class {create_cls}(BaseModel):")
        lines.append('    model_config = ConfigDict(extra="forbid", populate_by_name=True)')
        lines.append("")
        lines.append(f"    type: Literal[{wire_type!r}]")
        lines.append(f"    data: {data_cls}")
        lines.append("    key: str | None = None")
        lines.append("    name: str | None = None")
        lines.append("    workbook_id: str | None = Field(default=None, serialization_alias='workbookId')")
        lines.append("    annotation: Mapping[str, object] | None = None")
        lines.append("    links: Mapping[str, str] | None = None")
        lines.append("")
        lines.append("    def to_payload(self) -> dict[str, object]:")
        lines.append("        entry: dict[str, object] = {")
        lines.append(f"            'type': {wire_type!r},")
        lines.append("            'data': self.data.model_dump(exclude_none=True),")
        lines.append("        }")
        lines.append("        if self.annotation is not None:")
        lines.append("            entry['annotation'] = dict(self.annotation)")
        lines.append("        if self.links is not None:")
        lines.append("            entry['links'] = dict(self.links)")
        lines.append("        if self.key is not None:")
        lines.append("            entry['key'] = self.key")
        lines.append("        if self.name is not None:")
        lines.append("            entry['name'] = self.name")
        lines.append("        if self.workbook_id is not None:")
        lines.append("            entry['workbookId'] = self.workbook_id")
        lines.append("        return {'entry': entry}")
        lines.append("")

    all_editor_update_nodes: dict[str, EditorNodeMeta] = {}
    for _installation, info in sorted(metadata["installations"].items()):
        for wire_type, update_node_meta in info["charts"]["editor_update_nodes"].items():
            if wire_type not in all_editor_update_nodes:
                all_editor_update_nodes[wire_type] = update_node_meta

    for wire_type, update_node_meta in sorted(all_editor_update_nodes.items()):
        cls_prefix = _node_class_name(wire_type)
        data_fields = update_node_meta["data_fields"]

        upd_data_cls = f"{cls_prefix}NodeUpdateDataDTO"
        lines.append(f"class {upd_data_cls}(BaseModel):")
        lines.append('    model_config = ConfigDict(extra="forbid", populate_by_name=True)')
        lines.append("")
        required_fields = sorted(f for f, m in data_fields.items() if m["required"])
        optional_fields = sorted(f for f, m in data_fields.items() if not m["required"])
        for field in required_fields:
            lines.append(f"    {field}: str")
        for field in optional_fields:
            lines.append(f"    {field}: str | None = None")
        lines.append("")

        update_cls = f"{cls_prefix}NodeEntryUpdateDTO"
        lines.append(f"class {update_cls}(BaseModel):")
        lines.append('    model_config = ConfigDict(extra="forbid", populate_by_name=True)')
        lines.append("")
        lines.append(f"    type: Literal[{wire_type!r}]")
        lines.append("    entry_id: str = Field(serialization_alias='entryId')")
        lines.append(f"    data: {upd_data_cls}")
        lines.append("    mode: Literal['save', 'publish']")
        lines.append("    annotation: Mapping[str, object] | None = None")
        lines.append("    links: Mapping[str, str] | None = None")
        lines.append("    rev_id: str | None = Field(default=None, serialization_alias='revId')")
        lines.append("")
        lines.append("    def to_payload(self) -> dict[str, object]:")
        lines.append("        entry: dict[str, object] = {")
        lines.append(f"            'type': {wire_type!r},")
        lines.append("            'entryId': self.entry_id,")
        lines.append("            'data': self.data.model_dump(exclude_none=True),")
        lines.append("        }")
        lines.append("        if self.annotation is not None:")
        lines.append("            entry['annotation'] = dict(self.annotation)")
        lines.append("        if self.links is not None:")
        lines.append("            entry['links'] = dict(self.links)")
        lines.append("        if self.rev_id is not None:")
        lines.append("            entry['revId'] = self.rev_id")
        lines.append("        return {'entry': entry, 'mode': self.mode}")
        lines.append("")

    lines.append("""
class EditorChartReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entry_id: str | None = Field(default=None, alias="entryId")
    type: str | None = None
    data: dict[str, object] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {**value, "raw": value}
        return value


class EditorChartGetArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"entryId": self.entry_id}
        if self.workbook_id is not None:
            payload["workbookId"] = self.workbook_id
        return payload


class EditorChartDeleteArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")

    def to_payload(self) -> dict[str, object]:
        return {"entryId": self.entry_id}
""")

    return "\n".join(lines)


def _emit_navigation_dto() -> str:
    return r"""
class GetEntriesArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ids: tuple[str, ...] = ()
    created_by: tuple[str, ...] = ()
    name: str | None = None
    exclude_locked: bool | None = None
    ignore_shared_entries: bool | None = None
    ignore_workbook_entries: bool | None = None
    include_data: bool | None = None
    include_links: bool | None = None
    include_permissions_info: bool | None = None
    order_field: Literal["createdAt", "name"] | None = None
    order_direction: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=100, ge=1, le=200)
    page_token: str | None = None
    scope: str | None = None
    type: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"pageSize": self.page_size}
        if self.ids:
            payload["ids"] = list(self.ids)
        if self.created_by:
            payload["createdBy"] = list(self.created_by)
        if self.name is not None:
            payload["filters"] = {"name": self.name}
        for key, value in (
            ("excludeLocked", self.exclude_locked),
            ("ignoreSharedEntries", self.ignore_shared_entries),
            ("ignoreWorkbookEntries", self.ignore_workbook_entries),
            ("includeData", self.include_data),
            ("includeLinks", self.include_links),
            ("includePermissionsInfo", self.include_permissions_info),
        ):
            if value is not None:
                payload[key] = value
        if self.order_field is not None:
            payload["orderBy"] = {"field": self.order_field, "direction": self.order_direction}
        if self.page_token is not None:
            payload["pageToken"] = self.page_token
        if self.scope is not None:
            payload["scope"] = self.scope
        if self.type is not None:
            payload["type"] = self.type
        return payload


class ListDirectoryArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str
    created_by: str | tuple[str, ...] | None = None
    name: str | None = None
    include_permissions_info: bool | None = None
    order_field: Literal["createdAt", "name"] | None = None
    order_direction: Literal["asc", "desc"] = "asc"
    page: int = Field(default=0, ge=0)
    page_size: int = Field(default=100, ge=1)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"path": self.path, "page": self.page, "pageSize": self.page_size}
        if self.created_by is not None:
            payload["createdBy"] = list(self.created_by) if isinstance(self.created_by, tuple) else self.created_by
        if self.name is not None:
            payload["filters"] = {"name": self.name}
        if self.include_permissions_info is not None:
            payload["includePermissionsInfo"] = self.include_permissions_info
        if self.order_field is not None:
            payload["orderBy"] = {"field": self.order_field, "direction": self.order_direction}
        return payload


class CollectionContentArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    collection_id: str
    filter_string: str | None = None
    include_permissions_info: bool | None = None
    mode: Literal["all", "onlyCollections", "onlyWorkbooks", "onlyEntries"] = "all"
    only_my: bool | None = None
    order_field: Literal["title", "createdAt", "updatedAt"] | None = None
    order_direction: Literal["asc", "desc"] = "asc"
    page: str | None = None
    page_size: int = Field(default=100, ge=1)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "collectionId": self.collection_id,
            "mode": self.mode,
            "pageSize": self.page_size,
        }
        for key, value in (
            ("filterString", self.filter_string),
            ("includePermissionsInfo", self.include_permissions_info),
            ("onlyMy", self.only_my),
            ("page", self.page),
        ):
            if value is not None:
                payload[key] = value
        if self.order_field is not None:
            payload["orderField"] = self.order_field
            payload["orderDirection"] = self.order_direction
        return payload


class WorkbookEntriesArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workbook_id: str
    created_by: str | None = None
    name: str | None = None
    include_permissions_info: bool | None = None
    order_field: Literal["name", "createdAt"] | None = None
    order_direction: Literal["asc", "desc"] = "asc"
    page: int = Field(default=0, ge=0)
    page_size: int = Field(default=100, ge=1)
    scope: str | tuple[str, ...] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "workbookId": self.workbook_id,
            "page": self.page,
            "pageSize": self.page_size,
        }
        if self.created_by is not None:
            payload["createdBy"] = self.created_by
        if self.name is not None:
            payload["filters"] = {"name": self.name}
        if self.include_permissions_info is not None:
            payload["includePermissionsInfo"] = self.include_permissions_info
        if self.order_field is not None:
            payload["orderBy"] = {"field": self.order_field, "direction": self.order_direction}
        if self.scope is not None:
            payload["scope"] = list(self.scope) if isinstance(self.scope, tuple) else self.scope
        return payload


class EntryRelationsArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_ids: tuple[str, ...]
    include_permissions_info: bool | None = None
    link_direction: Literal["from", "to"] | None = None
    limit: int = Field(default=100, ge=1)
    page_token: str | None = None
    scope: Literal["dash", "report", "widget", "dataset", "folder", "connection"] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"entryIds": list(self.entry_ids), "limit": self.limit}
        for key, value in (
            ("includePermissionsInfo", self.include_permissions_info),
            ("linkDirection", self.link_direction),
            ("pageToken", self.page_token),
            ("scope", self.scope),
        ):
            if value is not None:
                payload[key] = value
        return payload


class EntrySummaryReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(validation_alias=AliasChoices("entryId", "id"))
    scope: str
    type: str
    name: str | None = Field(default=None, validation_alias=AliasChoices("name", "title", "displayKey"))
    key: str | None = None
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    created_at: str | None = Field(default=None, validation_alias="createdAt")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    updated_at: str | None = Field(default=None, validation_alias="updatedAt")
    saved_id: str | None = Field(default=None, validation_alias="savedId")
    published_id: str | None = Field(default=None, validation_alias="publishedId")
    workbook_id: str | None = Field(default=None, validation_alias="workbookId")
    collection_id: str | None = Field(default=None, validation_alias="collectionId")
    hidden: bool | None = None
    is_favorite: bool | None = Field(default=None, validation_alias="isFavorite")
    is_locked: bool = Field(default=False, validation_alias="isLocked")
    meta: Mapping[str, object] | None = None
    permissions: Mapping[str, object] | None = None
    data: Mapping[str, object] | None = None
    links: Mapping[str, str] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {**value, "raw": value}
        return value


class GetEntriesResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entries: tuple[EntrySummaryReadDTO, ...]
    next_page_token: str | None = Field(default=None, validation_alias="nextPageToken")


class DirectoryBreadcrumbReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(validation_alias="entryId")
    name: str = Field(validation_alias="title")
    path: str
    is_locked: bool = Field(validation_alias="isLocked")
    permissions: Mapping[str, object]
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {**value, "raw": value}
        return value


class ListDirectoryResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entries: tuple[EntrySummaryReadDTO, ...]
    breadcrumbs: tuple[DirectoryBreadcrumbReadDTO, ...] = Field(validation_alias="breadCrumbs")
    has_next_page: bool = Field(validation_alias="hasNextPage")


class CollectionSummaryReadDTO(CollectionReadDTO):
    entity: Literal["collection"]


class WorkbookSummaryReadDTO(WorkbookReadDTO):
    entity: Literal["workbook"]


class StructureEntrySummaryReadDTO(EntrySummaryReadDTO):
    entity: Literal["entry"]


class CollectionContentResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    items: tuple[CollectionSummaryReadDTO | WorkbookSummaryReadDTO | StructureEntrySummaryReadDTO, ...]
    next_page_token: str | None = Field(default=None, validation_alias="nextPageToken")


class WorkbookEntriesResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entries: tuple[EntrySummaryReadDTO, ...]
    next_page_token: str | None = Field(default=None, validation_alias="nextPageToken")


class EntryRelationReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(validation_alias="entryId")
    scope: Literal["dash", "report", "widget", "dataset", "folder", "connection"]
    type: str
    key: str | None = None
    created_at: str | None = Field(default=None, validation_alias="createdAt")
    public: bool = False
    tenant_id: str | None = Field(default=None, validation_alias="tenantId")
    workbook_id: str | None = Field(default=None, validation_alias="workbookId")
    collection_id: str | None = Field(default=None, validation_alias="collectionId")
    is_locked: bool = Field(default=False, validation_alias="isLocked")
    permissions: Mapping[str, object] | None = None
    full_permissions: Mapping[str, object] | None = Field(default=None, validation_alias="fullPermissions")
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {**value, "raw": value}
        return value


class EntryRelationsResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    relations: tuple[EntryRelationReadDTO, ...]
    next_page_token: str | None = Field(default=None, validation_alias="nextPageToken")
"""


def _emit_dashboard_dto(metadata: Metadata) -> str:
    contract = metadata.get("dashboard")
    if contract is None:
        return ""

    schemas = contract["schemas"]
    create_models = _PydanticSchemaEmitter(
        schemas,
        read=False,
        contract="Dashboard",
        open_schema_refs={"EntryAnnotationArg": "EntryAnnotationArgDTO"},
    ).emit(("CreateDashboardV2Args",))
    update_models = _PydanticSchemaEmitter(
        schemas,
        read=False,
        contract="Dashboard",
        open_schema_refs={
            "DashDataV2": "dict[str, JsonValue]",
            "DashMetaV2": "dict[str, JsonValue] | None",
            "EntryAnnotationArg": "dict[str, JsonValue]",
            "EntryUpdateMode": "EntryUpdateModeDTO",
        },
    ).emit(("UpdateDashboardV2Args",))
    args_models = _PydanticSchemaEmitter(
        schemas,
        read=False,
        contract="Dashboard",
        open_schema_refs={"EntryBranch": "EntryBranchDTO"},
    ).emit(("DeleteDashboardArgs", "GetDashboardV2Args"))
    read_models = _PydanticSchemaEmitter(
        schemas,
        read=True,
        contract="Dashboard",
        open_schema_refs={
            "DashboardV2": "dict[str, JsonValue]",
            "EntryPermissions": "dict[str, JsonValue]",
        },
    ).emit(("GetDashboardV2Result",))

    return f"""

{create_models}
{update_models}
{args_models}
{read_models}

class DashboardCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    data: Mapping[str, object]
    # Required but nullable by the DashMetaV2 schema: "meta": null must serialize.
    meta: Mapping[str, object] | None
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: Mapping[str, object] | None = None

    def to_payload(self) -> dict[str, object]:
        entry: dict[str, object] = {{
            "data": dict(self.data),
            "meta": None if self.meta is None else dict(self.meta),
        }}
        if self.annotation is not None:
            entry["annotation"] = dict(self.annotation)
        if self.key is not None:
            entry["key"] = self.key
        if self.name is not None:
            entry["name"] = self.name
        if self.workbook_id is not None:
            entry["workbookId"] = self.workbook_id
        model = CreateDashboardV2ArgsDTO.model_validate({{"entry": entry}})
        return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


class DashboardUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    entry_id: str = Field(serialization_alias="entryId")
    data: Mapping[str, object]
    # Required but nullable by the DashMetaV2 schema: "meta": null must serialize.
    meta: Mapping[str, object] | None
    mode: Literal["save", "publish"]
    rev_id: str | None = Field(default=None, serialization_alias="revId")
    lock_token: str | None = Field(default=None, serialization_alias="lockToken")
    annotation: Mapping[str, object] | None = None

    def to_payload(self) -> dict[str, object]:
        entry: dict[str, object] = {{
            "entryId": self.entry_id,
            "data": dict(self.data),
            "meta": None if self.meta is None else dict(self.meta),
        }}
        if self.annotation is not None:
            entry["annotation"] = dict(self.annotation)
        if self.rev_id is not None:
            entry["revId"] = self.rev_id
        payload: dict[str, object] = {{"entry": entry, "mode": self.mode}}
        if self.lock_token is not None:
            payload["lockToken"] = self.lock_token
        UpdateDashboardV2ArgsDTO.model_validate(payload)
        return payload


class DashboardReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entry_id: str | None = Field(default=None, alias="entryId")
    key: str | None = None
    name: str | None = None
    data: dict[str, object] | None = None
    rev_id: str | None = Field(default=None, alias="revId")
    saved_id: str | None = Field(default=None, alias="savedId")
    published_id: str | None = Field(default=None, alias="publishedId")
    workbook_id: str | None = Field(default=None, alias="workbookId")
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class DashboardGetArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    dashboard_id: str = Field(serialization_alias="dashboardId")
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    rev_id: str | None = Field(default=None, serialization_alias="revId")
    branch: Literal["saved", "published"] | None = None
    include_favorite: bool | None = Field(default=None, serialization_alias="includeFavorite")
    include_links: bool | None = Field(default=None, serialization_alias="includeLinks")
    include_permissions: bool | None = Field(default=None, serialization_alias="includePermissions")

    def to_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        model = GetDashboardV2ArgsDTO.model_validate(payload)
        return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


class DashboardDeleteArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)

    dashboard_id: str = Field(serialization_alias="dashboardId")
    lock_token: str | None = Field(default=None, serialization_alias="lockToken")

    def to_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        model = DeleteDashboardArgsDTO.model_validate(payload)
        return model.model_dump(mode="json", by_alias=True, exclude_unset=True)
"""


def emit_dto(metadata: Metadata) -> str:
    installations = metadata["installations"]
    connectors = {name: sorted(info["connectors"]) for name, info in sorted(installations.items())}
    connector_fields = {
        (name, connector): info["connectors"][connector]["available_fields"]
        for name, info in sorted(installations.items())
        for connector in sorted(info["connectors"])
    }
    sources = {name: sorted(info["dataset_sources"]) for name, info in sorted(installations.items())}
    chart_dto_block = _emit_chart_dto(metadata)
    dashboard_dto_block = _emit_dashboard_dto(metadata)
    navigation_dto_block = _emit_navigation_dto()
    return f"""# AUTOGENERATED by scripts/generate_sdk.py. Do not edit by hand.
# ruff: noqa
from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal
from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from datalens_sdk._runtime.wizard_structure import WizardFieldStructure, WizardVisualizationRegistry
from datalens_sdk.domain.dataset_types import RawSchemaColumnPayload
from datalens_sdk.errors import NotSupportedError
from datalens_sdk.serialization.json_types import JsonValue


_UNVALIDATED_NONE_DEFAULT: Any = None


def _json_array_to_tuple(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value

INSTALLATION_CONNECTORS: dict[str, frozenset[str]] = {{
{chr(10).join(f"    {name!r}: frozenset({items!r})," for name, items in connectors.items())}
}}

CONNECTOR_FIELDS: dict[tuple[str, str], frozenset[str]] = {{
{chr(10).join(f"    {key!r}: frozenset({value!r})," for key, value in sorted(connector_fields.items()))}
}}

INSTALLATION_SOURCES: dict[str, frozenset[str]] = {{
{chr(10).join(f"    {name!r}: frozenset({items!r})," for name, items in sources.items())}
}}


class ConnectionCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    installation: str
    connection_type: str = Field(serialization_alias="connectionType")
    params: Mapping[str, object] = Field(repr=False)

    @model_validator(mode="after")
    def _validate_support(self) -> ConnectionCreateDTO:
        connectors = INSTALLATION_CONNECTORS.get(self.installation)
        if connectors is None or self.connection_type not in connectors:
            raise NotSupportedError(
                f"Connection type {{self.connection_type!r}} is not available on installation {{self.installation!r}}"
            )
        fields = CONNECTOR_FIELDS[(self.installation, self.connection_type)]
        unknown = sorted(set(self.params) - fields)
        if unknown:
            raise NotSupportedError(
                f"Fields {{unknown}} are not available for {{self.connection_type!r}} on {{self.installation!r}}"
            )
        return self

    def to_payload(self) -> dict[str, object]:
        payload = dict(self.params)
        payload["type"] = self.connection_type
        return payload


class ConnectionReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    type: str | None = None
    db_type: str | None = None
    name: str | None = None
    description: str | None = None
    key: str | None = None
    dir_path: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class DatasetSourceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    title: str
    source_type: str
    connection_id: str | None = None
    connection_type: str
    managed_by: str = "user"
    parameters: Mapping[str, object] = Field(default_factory=dict)
    raw_schema: tuple[RawSchemaColumnPayload, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {{
            "id": self.id,
            "title": self.title,
            "source_type": self.source_type,
            "connection_id": self.connection_id,
            "connection_type": self.connection_type,
            "managed_by": self.managed_by,
            "parameters": dict(self.parameters),
            "raw_schema": [dict(field) for field in self.raw_schema],
        }}


class DatasetContentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    description: str = ""
    sources: tuple[DatasetSourceDTO, ...] = ()
    source_avatars: tuple[object, ...] = ()
    avatar_relations: tuple[object, ...] = ()
    result_schema: tuple[Mapping[str, object], ...] = ()
    obligatory_filters: tuple[Mapping[str, object], ...] = ()
    rls2: Mapping[str, object] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{
            "description": self.description,
            "sources": [source.to_payload() for source in self.sources],
            "source_avatars": list(self.source_avatars),
            "avatar_relations": list(self.avatar_relations),
        }}
        if self.result_schema:
            payload["result_schema"] = [dict(field) for field in self.result_schema]
        if self.obligatory_filters:
            payload["obligatory_filters"] = [dict(item) for item in self.obligatory_filters]
        if self.rls2 is not None:
            payload["rls2"] = dict(self.rls2)
        return payload


class DatasetCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    installation: str
    name: str
    dir_path: str | None = None
    workbook_id: str | None = None
    collection_id: str | None = None
    dataset: DatasetContentDTO

    @model_validator(mode="after")
    def _validate_sources(self) -> DatasetCreateDTO:
        available = INSTALLATION_SOURCES.get(self.installation, frozenset())
        for source in self.dataset.sources:
            if source.source_type not in available:
                raise NotSupportedError(
                    f"Dataset source {{source.source_type!r}} is not available on installation {{self.installation!r}}"
                )
        return self

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"name": self.name, "dataset": self.dataset.to_payload()}}
        if self.dir_path is not None:
            payload["dir_path"] = self.dir_path
        if self.workbook_id is not None:
            payload["workbook_id"] = self.workbook_id
        if self.collection_id is not None:
            payload["collection_id"] = self.collection_id
        return payload


class DatasetReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    name: str | None = None
    dir_path: str | None = None
    workbook_id: str | None = None
    collection_id: str | None = None
    key: str | None = None
    is_favorite: bool | None = None
    permissions: Mapping[str, object] | None = None
    full_permissions: Mapping[str, object] | None = None
    options: Mapping[str, object] | None = None
    published_id: str | None = Field(default=None, validation_alias="publishedId")
    rev_id: str | None = Field(default=None, validation_alias="revId")
    saved_id: str | None = Field(default=None, validation_alias="savedId")
    dataset: dict[str, object] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class DatasetValidateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_id: str = Field(serialization_alias="datasetId")
    data: Mapping[str, object]

    def to_payload(self) -> dict[str, object]:
        return {{"datasetId": self.dataset_id, "data": dict(self.data)}}


class DatasetUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_id: str = Field(serialization_alias="datasetId")
    data: Mapping[str, object]

    def to_payload(self) -> dict[str, object]:
        return {{"datasetId": self.dataset_id, "data": dict(self.data)}}


class EntryMoveDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    destination: str
    name: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"entryId": self.entry_id, "destination": self.destination}}
        if self.name is not None:
            payload["name"] = self.name
        return payload


class EntryRenameDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    name: str

    def to_payload(self) -> dict[str, object]:
        return {{"entryId": self.entry_id, "name": self.name}}


class CollectionCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(serialization_alias="title")
    parent_id: str | None = Field(serialization_alias="parentId")
    description: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"title": self.name, "parentId": self.parent_id}}
        if self.description is not None:
            payload["description"] = self.description
        return payload


class CollectionReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(validation_alias="collectionId")
    name: str = Field(validation_alias="title")
    description: str | None = None
    parent_id: str | None = Field(default=None, validation_alias="parentId")
    tenant_id: str | None = Field(default=None, validation_alias="tenantId")
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    created_at: str | None = Field(default=None, validation_alias="createdAt")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    updated_at: str | None = Field(default=None, validation_alias="updatedAt")
    meta: Mapping[str, object] | None = None
    permissions: Mapping[str, object] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class CollectionUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(serialization_alias="collectionId")
    name: str | None = Field(default=None, serialization_alias="title")
    description: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"collectionId": self.id}}
        if self.name is not None:
            payload["title"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        return payload


class CollectionMoveDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(serialization_alias="collectionId")
    parent_id: str | None = Field(serialization_alias="parentId")
    name: str | None = Field(default=None, serialization_alias="title")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"collectionId": self.id, "parentId": self.parent_id}}
        if self.name is not None:
            payload["title"] = self.name
        return payload


class WorkbookCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(serialization_alias="title")
    collection_id: str | None = Field(default=None, serialization_alias="collectionId")
    description: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"title": self.name}}
        if self.collection_id is not None:
            payload["collectionId"] = self.collection_id
        if self.description is not None:
            payload["description"] = self.description
        return payload


class WorkbookReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(validation_alias="workbookId")
    name: str = Field(validation_alias="title")
    description: str | None = None
    collection_id: str | None = Field(default=None, validation_alias="collectionId")
    status: str | None = None
    tenant_id: str | None = Field(default=None, validation_alias="tenantId")
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    created_at: str | None = Field(default=None, validation_alias="createdAt")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    updated_at: str | None = Field(default=None, validation_alias="updatedAt")
    meta: Mapping[str, object] | None = None
    permissions: Mapping[str, object] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class WorkbookUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(serialization_alias="workbookId")
    name: str | None = Field(default=None, serialization_alias="title")
    description: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"workbookId": self.id}}
        if self.name is not None:
            payload["title"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        return payload


class WorkbookMoveDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(serialization_alias="workbookId")
    collection_id: str | None = Field(serialization_alias="collectionId")
    name: str | None = Field(default=None, serialization_alias="title")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"workbookId": self.id, "collectionId": self.collection_id}}
        if self.name is not None:
            payload["title"] = self.name
        return payload


class FolderCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str

    def to_payload(self) -> dict[str, object]:
        return {{"key": self.key}}


class FolderReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(validation_alias="entryId")
    name: str | None = None
    key: str
    scope: str
    created_by: str | None = Field(default=None, validation_alias="createdBy")
    created_at: str | None = Field(default=None, validation_alias="createdAt")
    updated_by: str | None = Field(default=None, validation_alias="updatedBy")
    updated_at: str | None = Field(default=None, validation_alias="updatedAt")
    hidden: bool = False
    meta: Mapping[str, object] | None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class FolderGetResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    entries: tuple[FolderReadDTO, ...]


class FolderUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(serialization_alias="entryId")
    name: str

    def to_payload(self) -> dict[str, object]:
        return {{"entryId": self.id, "name": self.name}}


{navigation_dto_block}


class LicenseAssignArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_ids: tuple[str, ...] = Field(serialization_alias="userIds", min_length=1, max_length=1000)

    def to_payload(self) -> dict[str, object]:
        return {{"userIds": list(self.user_ids)}}


class LicenseListArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    user_ids: tuple[str, ...] = Field(default=(), serialization_alias="userIds", max_length=1000)
    status: Literal["active", "expired", "expiring"] | None = None
    sort_by: Literal["createdAt", "updatedAt"] | None = Field(default=None, serialization_alias="sortBy")
    order: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=100, ge=1, le=200)
    page_token: str | None = Field(default=None, serialization_alias="pageToken")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {{"limit": self.limit, "order": self.order}}
        if self.user_ids:
            payload["userIds"] = list(self.user_ids)
        if self.status is not None:
            payload["status"] = self.status
        if self.sort_by is not None:
            payload["sortBy"] = self.sort_by
        if self.page_token is not None:
            payload["pageToken"] = self.page_token
        return payload


class LicenseReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    license_id: str = Field(validation_alias="licenseId")
    user_id: str = Field(validation_alias="userId")
    tenant_id: str = Field(validation_alias="tenantId")
    license_type: Literal["creator"] = Field(validation_alias="licenseType")
    is_active: bool = Field(validation_alias="isActive")
    expires_at: str | None = Field(validation_alias="expiresAt")
    created_by: str = Field(validation_alias="createdBy")
    created_at: str = Field(validation_alias="createdAt")
    updated_by: str = Field(validation_alias="updatedBy")
    updated_at: str = Field(validation_alias="updatedAt")
    last_login_at: str | None = Field(default=None, validation_alias="lastLoginAt")
    meta: Mapping[str, object]
    raw: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _capture_raw(cls, value: object) -> object:
        if isinstance(value, dict) and "raw" not in value:
            return {{**value, "raw": value}}
        return value


class LicenseWithLastLoginReadDTO(LicenseReadDTO):
    last_login_at: str | None = Field(validation_alias="lastLoginAt")


class LicenseListResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    licenses: tuple[LicenseWithLastLoginReadDTO, ...]
    next_page_token: str | None = Field(default=None, validation_alias="nextPageToken")


class LicenseLimitReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: Literal["regular", "forced"]
    value: int
    started_at: str = Field(validation_alias="startedAt")
    active_licenses_count: int | None = Field(validation_alias="activeLicensesCount")


class LicenseLimitsReadDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    current: LicenseLimitReadDTO | None
    next: LicenseLimitReadDTO | None


class LicenseSetLimitArgsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    value: int = Field(ge=1, le=10000)

    def to_payload(self) -> dict[str, object]:
        return {{"value": self.value}}
{chart_dto_block}{dashboard_dto_block}"""


def emit_builder_module(installation: str, info: InstallationMetadata) -> str:
    connectors = info["connectors"]
    metadata_lines: list[str] = []
    for connector, meta in sorted(connectors.items()):
        metadata_lines.append(
            f"    {connector!r}: ConnectorMetadata(\n"
            f"        connector={connector!r},\n"
            f"        required=frozenset({meta['required']!r}),\n"
            f"        available_fields=frozenset({meta['available_fields']!r}),\n"
            f"        defaults={_emit_literal(meta['defaults'])},\n"
            f"        enum_restrictions={_emit_literal(meta['enum_restrictions'])},\n"
            f"    ),"
        )
    lines = [
        "# AUTOGENERATED by scripts/generate_sdk.py. Do not edit by hand.",
        "# ruff: noqa",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping, Sequence",
        "from typing import Literal",
        "",
        "from typing_extensions import Self",
        "",
        "from datalens_sdk.domain.entry_location import EntryLocation",
        "from datalens_sdk.domain.ports import ConnectionOperations",
        "from datalens_sdk.runtime import BaseConnectionCreate, ConnectorMetadata",
        "",
        f"INSTALLATION = {installation!r}",
        "METADATA: dict[str, ConnectorMetadata] = {",
        *metadata_lines,
        "}",
        "",
    ]
    for connector, meta in sorted(connectors.items()):
        cls = _class_name(connector, "ConnectionCreate")
        lines.extend(
            [
                f"class {cls}(BaseConnectionCreate):",
                "    def __init__(self, *, name: str, location: EntryLocation, operations: ConnectionOperations | None = None) -> None:",
                "        super().__init__(",
                "            installation=INSTALLATION,",
                "            location=location,",
                "            name=name,",
                f"            connector={connector!r},",
                f"            metadata=METADATA[{connector!r}],",
                "            operations=operations,",
                "        )",
                "",
            ]
        )
        for field in meta["available_fields"]:
            if field in {"name", "dir_path", "type", "description", "workbook_id", "collection_id"}:
                continue
            method = _safe_name(field)
            annotation = _annotation_for_field(field, meta)
            lines.extend(
                [
                    f"    def {method}(self, value: {annotation}) -> Self:",
                    f"        return self._set({field!r}, value)",
                    "",
                ]
            )
    lines.extend(
        [
            "class ConnectionCreateFactory:",
            "    def __init__(self, operations: ConnectionOperations) -> None:",
            "        self._operations = operations",
            "",
        ]
    )
    for connector in sorted(connectors):
        cls = _class_name(connector, "ConnectionCreate")
        lines.extend(
            [
                f"    def {connector}(self, *, name: str, location: EntryLocation) -> {cls}:",
                f"        return {cls}(name=name, location=location, operations=self._operations)",
                "",
            ]
        )
    return "\n".join(lines)


def emit_dataset_sources(metadata: Metadata) -> str:
    lines = [
        "# AUTOGENERATED by scripts/generate_sdk.py. Do not edit by hand.",
        "# ruff: noqa",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping, Sequence",
        "",
        "from datalens_sdk.domain.connection import Connection",
        "from datalens_sdk.domain.dataset import Source, SourceBuilder, SourceCreate",
        "from datalens_sdk.domain.ports import DatasetOperations",
        "",
    ]
    for installation, info in sorted(metadata["installations"].items()):
        cls = _class_name(installation, "SourceCreateFactory")
        lines.extend(
            [
                f"{installation.upper()}_SOURCE_TYPES = {info['dataset_sources']!r}",
                "",
                f"class {cls}(SourceBuilder):",
                "    def __init__(self, *, connection: Connection, operations: DatasetOperations | None = None) -> None:",
                "        super().__init__(",
                f"            installation={installation!r},",
                "            connection=connection,",
                f"            source_types={installation.upper()}_SOURCE_TYPES,",
                "            operations=operations,",
                "        )",
                "",
            ]
        )
        for source_type, meta in sorted(info["dataset_sources"].items()):
            params = {param: annotation for param, annotation in meta["parameters"].items() if param.isidentifier()}
            signature = ", ".join(
                f"{_safe_name(param)}: {annotation} | None = None" for param, annotation in params.items()
            )
            if signature:
                signature = ", " + signature
            param_dict_items = ", ".join(f"{param!r}: {_safe_name(param)}" for param in params)
            lines.extend(
                [
                    f"    def {meta['method']}(self, *, alias: str{signature}) -> SourceCreate:",
                    f"        raw_params: dict[str, object | None] = {{{param_dict_items}}}",
                    "        source = self.raw(",
                    "            alias=alias,",
                    f"            source_type={source_type!r},",
                    "            parameters={key: value for key, value in raw_params.items() if value is not None},",
                    "        )",
                    "        return SourceCreate(source=source, operations=self._operations)",
                    "",
                ]
            )
    return "\n".join(lines)


_SLOT_NAME_HELPERS: frozenset[str] = frozenset({"axis_title", "axis_scale", "grid"})


def _wizard_builder_structure(metadata: Metadata) -> dict[str, WizardVisualizationStructure] | None:
    structures = [
        info["wizard"]["visualization_structure"] for info in metadata["installations"].values() if "wizard" in info
    ]
    if not structures:
        return None
    first = structures[0]
    if any(structure != first for structure in structures[1:]):
        raise ValueError("Wizard builder generation requires identical installation structures")
    return first


def _method_is_supported_by_structure(
    method_name: str,
    spec: MethodSpec,
    visualization_structure: WizardVisualizationStructure | None,
) -> bool:
    if visualization_structure is None:
        return True
    return resolve_method_carriers(
        method_name,
        spec,
        visualization_structure,
        scope="builder_surface",
    ).supported


def _setting_enum(
    visualization_structure: WizardVisualizationStructure | None,
    *,
    setting_key: str,
    slot_names: Iterable[str] = (),
) -> tuple[str, ...]:
    if visualization_structure is None:
        return ()
    if slot_names:
        values: list[str] = []
        for slot_name in slot_names:
            setting = visualization_structure["slots"][slot_name]["settings"].get(setting_key)
            if setting is not None:
                values.extend(setting.get("enum", ()))
        return tuple(dict.fromkeys(values))
    setting = visualization_structure["chart_settings"].get(setting_key)
    return tuple(setting.get("enum", ())) if setting is not None else ()


def _axis_slot_names(
    method_name: str,
    spec: MethodSpec,
    visualization_structure: WizardVisualizationStructure | None,
) -> list[str]:
    if visualization_structure is None:
        return []
    resolution = resolve_method_carriers(
        method_name,
        spec,
        visualization_structure,
        scope="builder_surface",
    )
    return [name for name in resolution.matched_slot_names if name in {"x", "y", "y2"}]


_HELPER_WRAPPERS: dict[str, tuple[str, str]] = {
    "chart_title": (
        "*, text: str = '', mode: Literal['show', 'hide'] = 'show'",
        "self._chart_title(text=text, mode=mode)",
    ),
    "description": ("text: str", "self._set_description(text)"),
    "add_local_field": (
        "field: WizardLocalField",
        "self._add_local_field(field)",
    ),
    "add_aggregated_measure": (
        "field: WizardAggregatedMeasure",
        "self._add_aggregated_measure(field)",
    ),
    "add_filter": (
        "field: WizardFieldRef, *, operation: FilterOperation, values: Sequence[str] = ()",
        "self._add_filter(field, operation=operation, values=values)",
    ),
    "add_date_filter": (
        "field: WizardFieldRef, *, start: str, end: str, inclusive_end: bool = True",
        "self._add_date_filter(field, start=start, end=end, inclusive_end=inclusive_end)",
    ),
    "add_relative_date_filter": (
        "field: WizardFieldRef, *, start_offset: str, end_offset: str",
        "self._add_relative_date_filter(field, start_offset=start_offset, end_offset=end_offset)",
    ),
    "add_sort": (
        "field: WizardFieldRef, *, direction: Literal['asc', 'desc'] = 'asc'",
        "self._add_sort(field, direction=direction)",
    ),
    "navigator": ("*, mode: Literal['show', 'hide']", "self._navigator(mode=mode)"),
    "pagination": ("*, enabled: bool, limit: int = 100", "self._pagination(enabled=enabled, limit=limit)"),
    "table_size": ("*, size: Literal['s', 'm', 'l']", "self._table_size(size=size)"),
    "freeze_columns": ("*, count: int = 1", "self._freeze_columns(count=count)"),
    "labels_position": (
        "*, mode: Literal['inside', 'outside', 'auto']",
        "self._labels_position(mode=mode)",
    ),
    "column_background": (
        "field: WizardFieldRef, *, mode: Literal['2-point', '3-point'] = '3-point', palette: GradientPaletteId = 'red-orange-green', thresholds: tuple[float, ...] | None = None, reversed: bool = False",
        "self._column_background(field, mode=mode, palette=palette, thresholds=thresholds, reversed=reversed)",
    ),
    "column_bars": (
        "field: WizardFieldRef, *, enabled: bool = True, color_type: Literal['one-color', 'two-color', 'gradient'] = 'one-color', color: str | None = None, palette: DiscretePaletteId | None = None, color_index: int | None = None, color_positive: str | None = None, color_negative: str | None = None, positive_color_index: int | None = None, negative_color_index: int | None = None, gradient_palette: GradientPaletteId | None = None, gradient_type: Literal['2-point', '3-point'] = '2-point', reversed: bool = False, show_labels: bool = True, show_in_totals: bool = False, align: Literal['default', 'left', 'right'] = 'default'",
        "self._column_bars(field, enabled=enabled, color_type=color_type, color=color, palette=palette, color_index=color_index, color_positive=color_positive, color_negative=color_negative, positive_color_index=positive_color_index, negative_color_index=negative_color_index, gradient_palette=gradient_palette, gradient_type=gradient_type, reversed=reversed, show_labels=show_labels, show_in_totals=show_in_totals, align=align)",
    ),
    "column_title": ("field: WizardFieldRef, *, title: str", "self._column_title(field, title=title)"),
    "subtotals": ("field: WizardFieldRef, *, enabled: bool", "self._subtotals(field, enabled=enabled)"),
    "measure_format": (
        "field: WizardFieldRef, *, format: Literal['number', 'percent'] | None = None, precision: int | None = None, unit: Literal['auto', 'k', 'm', 'b', 't'] | None = None, prefix: str | None = None, postfix: str | None = None, show_rank_delimiter: bool | None = None",
        "self._measure_format(field, format=format, precision=precision, unit=unit, prefix=prefix, postfix=postfix, show_rank_delimiter=show_rank_delimiter)",
    ),
    "shape": ("*, value: FunnelShape", "self._funnel_shape(value=value)"),
    "palette": ("*, id: PaletteId", "self._palette(id=id)"),
    "color_by_dimension": (
        "field: WizardFieldRef",
        "self._color_by_dimension(field)",
    ),
    "color_by_measure": (
        "field: WizardFieldRef, *, mode: Literal['2-point', '3-point'] | None = None, palette: GradientPaletteId | None = None, reversed: bool | None = None",
        "self._color_by_measure(field, mode=mode, palette=palette, reversed=reversed)",
    ),
    "color_by_measure_name": (
        "*, colors_map: Mapping[WizardFieldRef, str] | None = None",
        "self._color_by_measure_name(colors_map=colors_map)",
    ),
    "shape_by_dimension": (
        "field: WizardFieldRef, *, shapes_map: Mapping[str, ShapeStyle] | None = None",
        "self._shape_by_dimension(field, shapes_map=shapes_map)",
    ),
    "shape_by_measure_name": (
        "*, shapes_map: Mapping[WizardFieldRef, ShapeStyle] | None = None",
        "self._shape_by_measure_name(shapes_map=shapes_map)",
    ),
    "point_size_range": (
        "*, min_radius: float = 4.5, max_radius: float = 9.0",
        "self._point_size_range(min_radius=min_radius, max_radius=max_radius)",
    ),
    "font_size": ("*, size: Literal['xs', 's', 'm', 'l']", "self._font_size(size=size)"),
    "font_color": ("*, color: str", "self._font_color(color=color)"),
    "measure_title_mode": ("*, mode: Literal['by-field', 'manual', 'hide']", "self._measure_title_mode(mode=mode)"),
    "add_hierarchy": (
        "hierarchy: WizardHierarchy",
        "self._add_hierarchy(hierarchy)",
    ),
}


def _emit_wizard_methods(
    visualization_type: str,
    visualization_structure: WizardVisualizationStructure | None = None,
) -> list[str]:
    specs = {
        name: spec
        for name, spec in method_specs_for_visualization(visualization_type).items()
        if _method_is_supported_by_structure(name, spec, visualization_structure)
    }
    lines: list[str] = []
    for method_name, spec in sorted(specs.items()):
        kind = spec.get("kind", "")
        value_type = spec.get("value_type", "str")
        literal_values = spec.get("literal_values", ())
        value_map = spec.get("value_map", {})
        slot_name = spec.get("slot_name", "")
        setting_key = spec.get("setting_key", "")

        if kind == "chart_setting":
            literal_values = _setting_enum(visualization_structure, setting_key=setting_key) or literal_values
            if value_type == "literal":
                lit = ", ".join(repr(v) for v in literal_values)
                lines.extend(
                    [
                        f"    def {method_name}(self, *, mode: Literal[{lit}]) -> Self:",
                        f"        return self._set_chart_setting({setting_key!r}, mode)",
                        "",
                    ]
                )
            elif value_type == "bool":
                true_val = value_map.get("true", "on")
                false_val = value_map.get("false", "off")
                lines.extend(
                    [
                        f"    def {method_name}(self, *, enabled: bool) -> Self:",
                        f"        return self._set_chart_setting({setting_key!r}, {true_val!r} if enabled else {false_val!r})",
                        "",
                    ]
                )
            elif value_type == "str":
                lines.extend(
                    [
                        f"    def {method_name}(self, *, value: str) -> Self:",
                        f"        return self._set_chart_setting({setting_key!r}, value)",
                        "",
                    ]
                )

        elif kind == "slot_setting":
            axis_slot_names = _axis_slot_names(
                method_name,
                spec,
                visualization_structure,
            )
            axis_slot_literal = ", ".join(repr(slot_name) for slot_name in axis_slot_names)
            if not axis_slot_literal:
                continue
            literal_values = (
                _setting_enum(
                    visualization_structure,
                    setting_key=setting_key,
                    slot_names=axis_slot_names,
                )
                or literal_values
            )
            if value_type == "literal":
                lit = ", ".join(repr(v) for v in literal_values)
                lines.extend(
                    [
                        f"    def {method_name}(self, slot_name: Literal[{axis_slot_literal}], *, mode: Literal[{lit}]) -> Self:",
                        f"        return self._set_slot_setting(slot_name, {setting_key!r}, mode)",
                        "",
                    ]
                )
            elif value_type == "bool":
                true_val = value_map.get("true", "yes")
                false_val = value_map.get("false", "no")
                lines.extend(
                    [
                        f"    def {method_name}(self, slot_name: Literal[{axis_slot_literal}], *, enabled: bool) -> Self:",
                        f"        return self._set_slot_setting(slot_name, {setting_key!r}, {true_val!r} if enabled else {false_val!r})",
                        "",
                    ]
                )

        elif kind == "slot":
            lines.extend(
                [
                    f"    def {method_name}(self, fields: Sequence[WizardFieldRef]) -> Self:",
                    f"        return self._set_slot({slot_name!r}, fields)",
                    "",
                ]
            )

        elif kind == "helper" and method_name in _SLOT_NAME_HELPERS:
            axis_slot_names = _axis_slot_names(
                method_name,
                spec,
                visualization_structure,
            )
            axis_slot_literal = ", ".join(repr(slot_name) for slot_name in axis_slot_names)
            if not axis_slot_literal:
                continue
            if method_name == "axis_title":
                lines.extend(
                    [
                        f"    def axis_title(self, slot_name: Literal[{axis_slot_literal}], *, mode: Literal['off', 'manual', 'auto'], text: str = '') -> Self:",
                        "        return self._axis_title(slot_name, mode=mode, text=text)",
                        "",
                    ]
                )
            elif method_name == "axis_scale":
                lines.extend(
                    [
                        f"    def axis_scale(self, slot_name: Literal[{axis_slot_literal}], *, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str | None = None, max: str | None = None) -> Self:",
                        "        return self._axis_scale(slot_name, scale=scale, mode=mode, min=min, max=max)",
                        "",
                    ]
                )
            elif method_name == "grid":
                lines.extend(
                    [
                        "    def grid(self, slot_name: Literal["
                        + axis_slot_literal
                        + "], *, enabled: bool, step: int | None = None) -> Self:",
                        "        return self._grid(slot_name, enabled=enabled, step=step)",
                        "",
                    ]
                )
        elif kind == "helper" and method_name == "label_mode":
            semantics = WIZARD_VISUALIZATION_SEMANTICS[visualization_type]
            modes = ", ".join(repr(mode) for mode in semantics["label_modes"])
            lines.extend(
                [
                    f"    def label_mode(self, *, mode: Literal[{modes}]) -> Self:",
                    "        return self._label_mode(mode=mode)",
                    "",
                ]
            )
        elif kind == "helper" and method_name in _HELPER_WRAPPERS:
            signature, call = _HELPER_WRAPPERS[method_name]
            lines.extend(
                [
                    f"    def {method_name}(self, {signature}) -> Self:",
                    f"        return {call}",
                    "",
                ]
            )

    return lines


def _wizard_slot_methods(
    visualization_type: str,
    visualization_structure: WizardVisualizationStructure,
) -> dict[str, str]:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    if semantics is None:
        return {}
    slots = frozenset(visualization_structure["slots"])
    aliases = semantics["slot_aliases"]
    method_slots = {
        spec["slot_name"]
        for spec in method_specs_for_visualization(visualization_type).values()
        if spec.get("kind") == "slot" and "slot_name" in spec
    }
    hidden_slots = {"colors", "shapes"} | method_slots
    alias_targets = set(aliases.values())
    exposed: dict[str, str] = {}
    for alias_name, target_slot in sorted(aliases.items()):
        if target_slot not in hidden_slots:
            exposed[alias_name.replace("-", "_")] = target_slot
    for slot_name in sorted(slots):
        if slot_name not in hidden_slots and slot_name not in alias_targets:
            exposed[slot_name.replace("-", "_")] = slot_name
    return exposed


def _ql_viz_methods(viz_id: str) -> list[str]:
    spec = QL_VIZ_SPECS.get(viz_id, {})
    placeholders = spec.get("placeholders", [])
    if not isinstance(placeholders, list):
        return []
    exposed: list[str] = []
    for placeholder in placeholders:
        if not isinstance(placeholder, dict):
            continue
        ph_id = placeholder.get("id")
        if not isinstance(ph_id, str):
            continue
        sanitized = ph_id.replace("-", "_")
        if sanitized not in exposed:
            exposed.append(sanitized)
    return exposed


def _ql_data_section_methods(viz_id: str) -> list[str]:
    spec = QL_VIZ_SPECS.get(viz_id, {})
    viz = spec.get("viz", {})
    if not isinstance(viz, dict):
        return []
    placeholder_methods = set(_ql_viz_methods(viz_id))
    sections: list[str] = []
    if viz.get("allowColors") and "colors" not in placeholder_methods:
        sections.append("colors")
    if viz.get("allowLabels") and "labels" not in placeholder_methods:
        sections.append("labels")
    if viz.get("allowShapes") and "shapes" not in placeholder_methods:
        sections.append("shapes")
    if "tooltips" not in placeholder_methods:
        sections.append("tooltips")
    return sections


def emit_chart_builders(metadata: Metadata) -> str:
    wizard_structure = _wizard_builder_structure(metadata)
    wizard_visualization_types = sorted(wizard_structure) if wizard_structure is not None else []
    wizard_factory_methods = _visualization_factory_methods(
        wizard_visualization_types,
        family="Wizard",
    )
    ql_factory_methods = _visualization_factory_methods(sorted(QL_VIZ_SPECS), family="QL")
    all_editor_nodes: dict[str, EditorCreateNodeMeta] = {}
    installation_editor_types: dict[str, list[str]] = {}
    for installation, info in sorted(metadata["installations"].items()):
        node_types = sorted(info["charts"]["editor_nodes"])
        installation_editor_types[installation] = node_types
        for wire_type, node_meta in info["charts"]["editor_nodes"].items():
            if wire_type not in all_editor_nodes:
                all_editor_nodes[wire_type] = node_meta

    lines = [
        "# AUTOGENERATED by scripts/generate_sdk.py. Do not edit by hand.",
        "# ruff: noqa",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping, Sequence",
        f"from typing import {'Literal' if wizard_visualization_types else 'Any, Literal'}",
        "",
        "from typing_extensions import Self",
        "",
        "from datalens_sdk.runtime import (",
        "    _BaseEditorNodeCreate,",
        "    _BaseQLChartCreate,",
        "    _BaseWizardChartCreate,",
        "    _CombinedWizardChartCreate,",
        "    _GeolayerWizardChartCreate,",
        "    _MetricWizardChartCreate,",
        "    _PivotWizardChartCreate,",
        "    _ScatterWizardChartCreate,",
        "    _TableWizardChartCreate,",
        ")",
        "from datalens_sdk.domain.entry_location import EntryLocation",
        "from datalens_sdk.domain.chart_types import CombinedLayerType, DiscretePaletteId, FilterOperation, FunnelShape, GeoLayerFilter, GeoLayerType, GradientPaletteId, MeasureFormat, PaletteId, ShapeStyle",
        "from datalens_sdk.domain.fields import (",
        "    DatasetField,",
        "    WizardFieldRef,",
        "    WizardAggregatedMeasure,",
        "    WizardHierarchy,",
        "    WizardLocalField,",
        ")",
        "from datalens_sdk.domain.dataset import Dataset",
        "from datalens_sdk.domain.ports import ChartOperations",
        "from datalens_sdk.domain.ql_chart import QLColumn",
        *([] if wizard_visualization_types else ["from datalens_sdk.errors import NotSupportedError"]),
        "",
    ]

    lines.append("INSTALLATION_EDITOR_NODE_TYPES: dict[str, frozenset[str]] = {")
    for installation, node_types in sorted(installation_editor_types.items()):
        lines.append(f"    {installation!r}: frozenset({node_types!r}),")
    lines.append("}")
    lines.append("")

    for visualization_type in wizard_visualization_types:
        assert wizard_structure is not None
        visualization_structure = wizard_structure[visualization_type]
        base_create = _WIZARD_VISUALIZATION_BASE_CREATE.get(visualization_type, "_BaseWizardChartCreate")
        create_cls = _class_name(visualization_type, "WizardChartCreate")

        lines.extend(
            [
                f"class {create_cls}({base_create}):",
                "    def __init__(self, *, name: str, location: EntryLocation, operations: ChartOperations | None = None) -> None:",
                "        super().__init__(",
                f"            visualization_type={visualization_type!r},",
                "            name=name,",
                "            location=location,",
                "            operations=operations,",
                "        )",
                "",
            ]
        )

        if visualization_type not in {"combined-chart", "geolayer"}:
            methods = _wizard_slot_methods(visualization_type, visualization_structure)
            for method_name, slot_name in methods.items():
                lines.extend(
                    [
                        f"    def {method_name}(self, fields: Sequence[WizardFieldRef]) -> Self:",
                        f"        return self._set_slot({slot_name!r}, fields)",
                        "",
                    ]
                )
        if visualization_type == "combined-chart":
            lines.extend(
                [
                    "    def x(self, fields: Sequence[WizardFieldRef]) -> Self:",
                    "        return self._combined_x(fields)",
                    "",
                    "    def add_layer(self, layer_type: CombinedLayerType, *, y: WizardFieldRef | None = None, y2: WizardFieldRef | None = None, name: str | None = None) -> Self:",
                    "        return self._combined_add_layer(layer_type, y=y, y2=y2, name=name)",
                    "",
                ]
            )
        if visualization_type == "geolayer":
            lines.extend(
                [
                    "    def add_dataset(self, dataset: Dataset) -> Self:",
                    "        return self._geo_add_dataset(dataset)",
                    "",
                    "    def add_layer(self, layer_type: GeoLayerType, *, geopoint: WizardFieldRef | None = None, polygon: WizardFieldRef | None = None, polyline: WizardFieldRef | None = None, grouping: WizardFieldRef | None = None, size: WizardFieldRef | None = None, color: WizardFieldRef | None = None, color_mode: Literal['2-point', '3-point'] | None = None, color_palette: GradientPaletteId | None = None, color_reversed: bool | None = None, filters: Sequence[GeoLayerFilter] = (), tooltips: Sequence[WizardFieldRef] = (), labels: Sequence[WizardFieldRef] = (), sort_by: WizardFieldRef | None = None, sort_direction: Literal['asc', 'desc'] = 'asc', alpha: int = 80, name: str | None = None, dataset: Dataset | None = None) -> Self:",
                    "        return self._geo_add_layer(layer_type, geopoint=geopoint, polygon=polygon, polyline=polyline, grouping=grouping, size=size, color=color, color_mode=color_mode, color_palette=color_palette, color_reversed=color_reversed, filters=filters, tooltips=tooltips, labels=labels, sort_by=sort_by, sort_direction=sort_direction, alpha=alpha, name=name, dataset=dataset)",
                    "",
                    "    def map_center(self, *, lat: float, lon: float, zoom: int | None = None) -> Self:",
                    "        return self._map_center(lat=lat, lon=lon, zoom=zoom)",
                    "",
                ]
            )
        lines.extend(_emit_wizard_methods(visualization_type, visualization_structure))

    lines.extend(
        [
            "class WizardChartCreateFactory:",
            "    def __init__(self, operations: ChartOperations) -> None:",
            "        self._operations = operations",
            "",
        ]
    )
    for visualization_type in wizard_visualization_types:
        create_cls = _class_name(visualization_type, "WizardChartCreate")
        method_name = wizard_factory_methods[visualization_type]
        lines.extend(
            [
                f"    def {method_name}(self, *, name: str, location: EntryLocation) -> {create_cls}:",
                f"        return {create_cls}(name=name, location=location, operations=self._operations)",
                "",
            ]
        )
    if not wizard_visualization_types:
        lines.extend(
            [
                "    def __getattr__(self, name: str) -> Any:",
                "        raise NotSupportedError(",
                "            'Wizard API v3 is unavailable because this installation has no generated Wizard structure'",
                "        )",
                "",
            ]
        )

    for wire_type, node_meta in sorted(all_editor_nodes.items()):
        cls_prefix = _node_class_name(wire_type)
        editor_cls = f"{cls_prefix}NodeCreate"
        data_fields = node_meta["data_fields"]

        lines.extend(
            [
                f"class {editor_cls}(_BaseEditorNodeCreate):",
                "    def __init__(self, *, name: str, location: EntryLocation, operations: ChartOperations | None = None) -> None:",
                "        super().__init__(",
                f"            wire_type={wire_type!r},",
                "            name=name,",
                "            location=location,",
                "            operations=operations,",
                "        )",
                "",
            ]
        )
        for field in sorted(data_fields):
            meta = data_fields[field]
            annotation = "str" if meta["required"] else "str | None"
            lines.extend(
                [
                    f"    def {field}(self, value: {annotation}) -> Self:",
                    f"        return self._set_tab({field!r}, value)",
                    "",
                ]
            )

    for installation, node_types in sorted(installation_editor_types.items()):
        factory_cls = _class_name(installation, "EditorChartCreateFactory")
        lines.extend(
            [
                f"class {factory_cls}:",
                "    def __init__(self, operations: ChartOperations) -> None:",
                "        self._operations = operations",
                "",
            ]
        )
        for wire_type in sorted(node_types):
            node_meta = metadata["installations"][installation]["charts"]["editor_nodes"][wire_type]
            cls_prefix = _node_class_name(wire_type)
            editor_cls = f"{cls_prefix}NodeCreate"
            method = node_meta["factory_method"]
            lines.extend(
                [
                    f"    def {method}(self, *, name: str, location: EntryLocation) -> {editor_cls}:",
                    f"        return {editor_cls}(name=name, location=location, operations=self._operations)",
                    "",
                ]
            )

    for viz_id in sorted(QL_VIZ_SPECS):
        create_cls = _ql_class_name(viz_id)
        lines.extend(
            [
                f"class {create_cls}(_BaseQLChartCreate):",
                "    def __init__(self, *, name: str, location: EntryLocation, operations: ChartOperations | None = None) -> None:",
                "        super().__init__(",
                f"            viz_id={viz_id!r},",
                "            name=name,",
                "            location=location,",
                "            operations=operations,",
                "        )",
                "",
            ]
        )
        for method in _ql_viz_methods(viz_id):
            lines.extend(
                [
                    f"    def {method}(self, columns: Sequence[QLColumn | str]) -> Self:",
                    f"        return self._set_placeholder({method!r}, columns)",
                    "",
                ]
            )
        for section in _ql_data_section_methods(viz_id):
            lines.extend(
                [
                    f"    def {section}(self, columns: Sequence[QLColumn | str]) -> Self:",
                    f"        return self._set_data_section({section!r}, columns)",
                    "",
                ]
            )

    lines.extend(
        [
            "class QLChartCreateFactory:",
            "    def __init__(self, operations: ChartOperations) -> None:",
            "        self._operations = operations",
            "",
        ]
    )
    for viz_id in sorted(QL_VIZ_SPECS):
        create_cls = _ql_class_name(viz_id)
        method_name = ql_factory_methods[viz_id]
        lines.extend(
            [
                f"    def {method_name}(self, *, name: str, location: EntryLocation) -> {create_cls}:",
                f"        return {create_cls}(name=name, location=location, operations=self._operations)",
                "",
            ]
        )

    return "\n".join(lines)


def write_outputs(output_root: Path, metadata: Metadata) -> None:
    package_root = output_root / PACKAGE_DIR
    generated = package_root / "_generated"
    builders = generated / "builders"
    builders.mkdir(parents=True, exist_ok=True)
    (generated / "__init__.py").write_text("")
    (builders / "__init__.py").write_text("")
    persisted_metadata = {"installations": metadata["installations"]}
    (generated / "installations.json").write_text(json.dumps(persisted_metadata, indent=2, sort_keys=True) + "\n")
    (generated / "dto.py").write_text(emit_dto(metadata))
    for installation, info in metadata["installations"].items():
        (builders / f"{installation}.py").write_text(emit_builder_module(installation, info))
    (builders / "dataset_sources.py").write_text(emit_dataset_sources(metadata))
    (builders / "charts.py").write_text(emit_chart_builders(metadata))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    write_outputs(args.output_root, build_metadata(INSTALLATIONS))


if __name__ == "__main__":
    main()
