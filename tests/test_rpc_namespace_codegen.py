from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError
import pytest

from datalens_sdk import codegen
from datalens_sdk.api_version import API_VERSION
from datalens_sdk.serialization.json_types import JsonValue

ROOT = Path(__file__).resolve().parents[1]


def _operation(
    *,
    request: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    operation_id: str | None = None,
    required: bool = True,
    tag: str = "Widgets",
) -> dict[str, object]:
    operation: dict[str, object] = {
        "tags": [tag],
        "requestBody": {
            "required": required,
            "content": {
                "application/json": {
                    "schema": request if request is not None else {"$ref": "#/components/schemas/WidgetArgs"}
                }
            },
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": result if result is not None else {"$ref": "#/components/schemas/WidgetResult"}
                    }
                }
            },
        },
    }
    if operation_id is not None:
        operation["operationId"] = operation_id
    return operation


def _spec(
    paths: dict[str, object],
    *,
    schemas: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "paths": paths,
        "components": {
            "schemas": schemas
            if schemas is not None
            else {
                "WidgetArgs": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                "WidgetResult": {"type": "object", "properties": {"accepted": {"type": "boolean"}}},
            },
        },
    }


def _contract(spec: dict[str, object]) -> codegen.RpcNamespaceContractMeta:
    contract = codegen.build_rpc_namespace_contract_meta(spec, config={"tag": "Widgets", "namespace": "widgets"})
    assert contract is not None
    return contract


def _models(contract: codegen.RpcNamespaceContractMeta, *, real_json: bool = False) -> dict[str, object]:
    source = codegen._emit_rpc_namespace_dto(
        cast(codegen.Metadata, {"installations": {}, "rpc_namespaces": {"widgets": contract}})
    )
    return _load_models(source, real_json=real_json)


def _load_models(source: str, *, real_json: bool = False) -> dict[str, object]:
    def json_array_to_tuple(value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    scope: dict[str, object] = {
        "Annotated": Annotated,
        "BaseModel": BaseModel,
        "BeforeValidator": BeforeValidator,
        "ConfigDict": ConfigDict,
        "Field": Field,
        "Literal": Literal,
        "JsonValue": JsonValue if real_json else object,
        "_UNVALIDATED_NONE_DEFAULT": None,
        "_json_array_to_tuple": json_array_to_tuple,
    }
    exec("from __future__ import annotations\n" + source, scope)
    for value in scope.values():
        if isinstance(value, type) and value is not BaseModel and issubclass(value, BaseModel):
            value.model_rebuild(_types_namespace=scope)
    return scope


def _widget_models(
    *, request: dict[str, object], result: dict[str, object], real_json: bool = False
) -> dict[str, object]:
    return _models(
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}}, schemas={"WidgetArgs": request, "WidgetResult": result}
            )
        ),
        real_json=real_json,
    )


@pytest.fixture(scope="module")
def subscriptions_models() -> dict[str, object]:
    metadata = codegen.build_metadata(
        {
            "enterprise": ROOT / "spec" / "enterprise.json",
            "yacloud": ROOT / "spec" / "yacloud.json",
        },
        rpc_namespace_configs=({"tag": "Subscriptions", "namespace": "subscriptions"},),
    )
    scope: dict[str, object] = {}
    exec(codegen.emit_dto(metadata), scope)
    for value in scope.values():
        if not isinstance(value, type):
            continue
        try:
            is_model = issubclass(value, BaseModel)
        except TypeError:
            continue
        if is_model and value is not BaseModel:
            cast(type[BaseModel], value).model_rebuild(_types_namespace=scope)
    return scope


def test_generated_subscriptions_dto_imports_with_pydantic_lower_bound(
    subscriptions_models: dict[str, object],
) -> None:
    request = subscriptions_models["DeleteSubscriptionArgsDTO"]

    assert request(subscriptionId="subscription-1").to_payload() == {  # type: ignore[operator]
        "subscriptionId": "subscription-1"
    }


def test_subscriptions_dto_rejects_id_with_trailing_newline(subscriptions_models: dict[str, object]) -> None:
    request = subscriptions_models["DeleteSubscriptionArgsDTO"]

    with pytest.raises(ValidationError):
        request(subscriptionId="subscription-1\n")  # type: ignore[operator]


def _model(scope: dict[str, object], name: str) -> type[BaseModel]:
    return cast(type[BaseModel], scope[name])


def _installation_spec(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _write_installation_spec(tmp_path: Path, name: str, spec: dict[str, object]) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


def _add_installation_rpc(
    spec: dict[str, object],
    *,
    route: str,
    tag: str,
    request_name: str,
    result_name: str,
    result_schema: dict[str, object],
) -> None:
    paths = cast(dict[str, object], spec["paths"])
    schemas = cast(dict[str, object], cast(dict[str, object], spec["components"])["schemas"])
    paths[route] = {
        "post": _operation(
            tag=tag,
            request={"$ref": f"#/components/schemas/{request_name}"},
            result={"$ref": f"#/components/schemas/{result_name}"},
        )
    }
    schemas[request_name] = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "enabled": {"type": "boolean"}},
        "required": ["id"],
    }
    schemas[result_name] = result_schema


def test_tagged_rpc_uses_override_operation_id_and_route_fallback() -> None:
    spec = _spec(
        {
            "/rpc/wireOverride": {"post": _operation(operation_id="ignoredOperationId")},
            "/rpc/wireId": {"post": _operation(operation_id="readWidget", required=False)},
            "/rpc/deleteWidget": {"post": _operation()},
            "/rpc/ignored": {"get": _operation(tag="WidgetsOther")},
        }
    )
    original = deepcopy(spec)
    contract = codegen.build_rpc_namespace_contract_meta(
        spec,
        config={
            "tag": "Widgets",
            "namespace": "widgets",
            "operation_name_overrides": {"/rpc/wireOverride": "create_widget"},
        },
    )
    assert contract is not None
    assert contract["tag"] == "Widgets"
    assert contract["namespace"] == "widgets"
    assert contract["operations"] == {
        "create_widget": {
            "name": "create_widget",
            "method": "post",
            "route": "/rpc/wireOverride",
            "request_schema": "WidgetArgs",
            "result_schema": "WidgetResult",
            "request_body_required": True,
            "request_dto": "WidgetArgsDTO",
            "result_dto": "WidgetResultReadDTO",
        },
        "read_widget": {
            "name": "read_widget",
            "method": "post",
            "route": "/rpc/wireId",
            "request_schema": "WidgetArgs",
            "result_schema": "WidgetResult",
            "request_body_required": False,
            "request_dto": "WidgetArgsDTO",
            "result_dto": "WidgetResultReadDTO",
        },
        "delete_widget": {
            "name": "delete_widget",
            "method": "post",
            "route": "/rpc/deleteWidget",
            "request_schema": "WidgetArgs",
            "result_schema": "WidgetResult",
            "request_body_required": True,
            "request_dto": "WidgetArgsDTO",
            "result_dto": "WidgetResultReadDTO",
        },
    }
    assert contract["roots"] == ["WidgetArgs", "WidgetResult"]
    assert spec == original


@pytest.mark.parametrize("location", ["path", "operation"])
@pytest.mark.parametrize("required", [False, True])
def test_tagged_rpc_rejects_unmodeled_operation_parameters(location: str, required: bool) -> None:
    parameter = {"name": "tenant", "in": "header", "required": required, "schema": {"type": "string"}}
    path_item: dict[str, object] = {"post": _operation()}
    if location == "path":
        path_item["parameters"] = [parameter]
        pointer = "/paths/~1rpc~1createWidget/parameters/0"
    else:
        operation = cast(dict[str, object], path_item["post"])
        operation["parameters"] = [parameter]
        pointer = "/paths/~1rpc~1createWidget/post/parameters/0"

    with pytest.raises(ValueError, match="Unsupported tagged RPC parameter") as exc:
        _contract(_spec({"/rpc/createWidget": path_item}))

    assert pointer in str(exc.value)


@pytest.mark.parametrize("location", ["path", "operation"])
def test_tagged_rpc_accepts_transport_owned_api_version_header(location: str) -> None:
    path_item: dict[str, object] = {"post": _operation()}
    owner = path_item if location == "path" else cast(dict[str, object], path_item["post"])
    owner["parameters"] = [{"$ref": "#/components/parameters/ApiVersionHeader"}]
    spec = _spec({"/rpc/createWidget": path_item})
    components = cast(dict[str, object], spec["components"])
    components["parameters"] = {
        "ApiVersionHeader": {
            "description": "API version header.",
            "in": "header",
            "name": "x-dl-api-version",
            "required": True,
            "schema": {"const": API_VERSION, "example": API_VERSION, "type": "string"},
        }
    }

    assert _contract(spec)["operations"]["create_widget"]["route"] == "/rpc/createWidget"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("in", "query"),
        ("name", "x-other-version"),
        ("required", False),
        ("const", "2"),
        ("type", "integer"),
        ("extra", {"allowReserved": True}),
    ],
)
def test_tagged_rpc_rejects_changed_transport_version_header(field: str, value: object) -> None:
    path_item: dict[str, object] = {"post": _operation()}
    operation = cast(dict[str, object], path_item["post"])
    operation["parameters"] = [{"$ref": "#/components/parameters/ApiVersionHeader"}]
    spec = _spec({"/rpc/createWidget": path_item})
    components = cast(dict[str, object], spec["components"])
    header: dict[str, object] = {
        "in": "header",
        "name": "x-dl-api-version",
        "required": True,
        "schema": {"const": API_VERSION, "type": "string"},
    }
    if field in {"const", "type"}:
        schema = cast(dict[str, object], header["schema"])
        schema[field] = value
    elif field == "extra":
        header.update(cast(dict[str, object], value))
    else:
        header[field] = value
    components["parameters"] = {"ApiVersionHeader": header}

    with pytest.raises(ValueError, match="Unsupported tagged RPC parameter") as exc:
        _contract(spec)

    assert "/paths/~1rpc~1createWidget/post/parameters/0" in str(exc.value)


def test_tagged_rpc_rejects_additional_parameter_after_transport_version_header() -> None:
    operation = _operation()
    operation["parameters"] = [
        {"$ref": "#/components/parameters/ApiVersionHeader"},
        {"name": "tenant", "in": "header", "required": True, "schema": {"type": "string"}},
    ]
    spec = _spec({"/rpc/createWidget": {"post": operation}})
    components = cast(dict[str, object], spec["components"])
    components["parameters"] = {
        "ApiVersionHeader": {
            "in": "header",
            "name": "x-dl-api-version",
            "required": True,
            "schema": {"const": API_VERSION, "type": "string"},
        }
    }

    with pytest.raises(ValueError, match="Unsupported tagged RPC parameter") as exc:
        _contract(spec)

    assert "/paths/~1rpc~1createWidget/post/parameters/1" in str(exc.value)


@pytest.mark.parametrize("location", ["request", "response"])
def test_tagged_rpc_rejects_multiple_media_representations(location: str) -> None:
    operation = _operation()
    if location == "request":
        body = cast(dict[str, object], operation["requestBody"])
        content = cast(dict[str, object], body["content"])
        pointer = "/paths/~1rpc~1createWidget/post/requestBody/content/text~1plain"
    else:
        responses = cast(dict[str, object], operation["responses"])
        response = cast(dict[str, object], responses["200"])
        content = cast(dict[str, object], response["content"])
        pointer = "/paths/~1rpc~1createWidget/post/responses/200/content/text~1plain"
    content["text/plain"] = {"schema": {"type": "string"}}

    with pytest.raises(ValueError, match="Unsupported tagged RPC media representation") as exc:
        _contract(_spec({"/rpc/createWidget": {"post": operation}}))

    assert pointer in str(exc.value)


def test_tagged_rpc_inline_empty_response_gets_a_deterministic_result_root() -> None:
    contract = _contract(
        _spec({"/rpc/deleteWidget": {"post": _operation(result={"type": "object", "properties": {}})}})
    )
    operation = contract["operations"]["delete_widget"]
    assert operation["result_schema"] == "DeleteWidgetResult"
    assert operation["result_dto"] == "DeleteWidgetResultReadDTO"
    assert contract["roots"] == ["DeleteWidgetResult", "WidgetArgs"]
    assert contract["schemas"]["DeleteWidgetResult"] == {"type": "object", "properties": {}}


@pytest.mark.parametrize("components", [None, {}, {"schemas": {}}])
def test_tagged_rpc_inline_roots_do_not_require_existing_components(components: dict[str, object] | None) -> None:
    spec: dict[str, object] = {
        "paths": {
            "/rpc/createWidget": {
                "post": _operation(
                    request={"type": "object", "properties": {}, "additionalProperties": False},
                    result={"type": "object", "properties": {}},
                )
            }
        }
    }
    if components is not None:
        spec["components"] = components
    original = deepcopy(spec)
    contract = _contract(spec)
    assert contract["roots"] == ["CreateWidgetArgs", "CreateWidgetResult"]
    assert contract["schemas"] == {
        "CreateWidgetArgs": {"type": "object", "properties": {}, "additionalProperties": False},
        "CreateWidgetResult": {"type": "object", "properties": {}},
    }
    assert spec == original


@pytest.mark.parametrize("additional", [None, True, {"type": "string"}])
def test_tagged_rpc_rejects_map_request_root_without_dto_methods(additional: object | None) -> None:
    request_schema: dict[str, object] = {"type": "object"}
    if additional is not None:
        request_schema["additionalProperties"] = additional
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": request_schema,
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/additionalProperties"):
        _contract(spec)


def test_tagged_rpc_rejects_referenced_map_request_root_without_dto_methods() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {"$ref": "#/components/schemas/WidgetArgsMap"},
            "WidgetArgsMap": {"type": "object", "additionalProperties": {"type": "string"}},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match=r"/schemas/WidgetArgsMap/additionalProperties"):
        _contract(spec)


@pytest.mark.parametrize(
    "request_schema",
    [
        {},
        {"type": "string"},
        {"type": "array", "items": {"type": "string"}},
        {"anyOf": [{"type": "object", "properties": {}}, {"type": "string"}]},
        {"type": ["object", "string"], "properties": {}},
    ],
)
def test_tagged_rpc_rejects_request_roots_that_do_not_emit_dto_methods(request_schema: dict[str, object]) -> None:
    spec = _spec({"/rpc/createWidget": {"post": _operation(request=request_schema)}})

    with pytest.raises(ValueError, match=r"/schemas/CreateWidgetArgs"):
        _contract(spec)


def test_tagged_rpc_rejects_required_field_without_a_declared_property() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["id"],
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/required/0"):
        _models(_contract(spec))


def test_tagged_rpc_rejects_undeclared_required_field_in_nested_map() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "required": ["id"],
                    }
                },
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match=r"WidgetArgs.options.*required property 'id'"):
        _models(_contract(spec))


@pytest.mark.parametrize("required_in_branch", [False, True])
def test_tagged_rpc_all_of_required_property_can_be_declared_in_another_branch(required_in_branch: bool) -> None:
    required_branch: dict[str, object] = {"type": "object", "required": ["id"]}
    property_branch = {"type": "object", "properties": {"id": {"type": "string"}}}
    if required_in_branch:
        request: dict[str, object] = {"type": "object", "allOf": [required_branch, property_branch]}
    else:
        request = {"type": "object", "required": ["id"], "allOf": [property_branch]}

    widget_args = _model(_widget_models(request=request, result={"type": "object", "properties": {}}), "WidgetArgsDTO")
    assert widget_args(id="widget-1").to_payload() == {"id": "widget-1"}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        widget_args.model_validate({})


def test_tagged_rpc_all_of_required_property_can_be_declared_in_a_referenced_sibling() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "allOf": [
                    {"$ref": "#/components/schemas/RequiredId"},
                    {"type": "object", "properties": {"id": {"type": "string"}}},
                ],
            },
            "RequiredId": {"type": "object", "required": ["id"]},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    widget_args = _model(_models(_contract(spec)), "WidgetArgsDTO")
    assert widget_args(id="widget-1").to_payload() == {"id": "widget-1"}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        widget_args.model_validate({})


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    ("parent_constraint", "constraint_key", "member_declares_object"),
    [
        ({"type": "string"}, "type", True),
        ({"type": ["object", "null"]}, "type", False),
        ({"enum": ["only-string"]}, "enum", True),
    ],
)
def test_tagged_rpc_rejects_all_of_parent_constraint_lost_by_object_dto(
    nested: bool, parent_constraint: dict[str, object], constraint_key: str, member_declares_object: bool
) -> None:
    member: dict[str, object] = {"properties": {"id": {"type": "string"}}}
    if member_declares_object:
        member["type"] = "object"
    composed: dict[str, object] = {
        **parent_constraint,
        "allOf": [member],
    }
    request: dict[str, object] = {"type": "object", "properties": {"options": composed}} if nested else composed
    pointer = "/schemas/WidgetArgs/properties/options" if nested else "/schemas/WidgetArgs"
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={"WidgetArgs": request, "WidgetResult": {"type": "object", "properties": {}}},
    )

    with pytest.raises(ValueError, match="allOf parent constraint") as exc:
        _contract(spec)

    assert f"{pointer}/{constraint_key}" in str(exc.value)


@pytest.mark.parametrize("open_in_branch", [False, True])
def test_tagged_rpc_rejects_all_of_map_root_whose_valid_entries_dto_would_forbid(open_in_branch: bool) -> None:
    map_schema = {"type": "object", "additionalProperties": True}
    empty_object = {"type": "object"}
    request: dict[str, object] = (
        {"type": "object", "allOf": [map_schema, empty_object]}
        if open_in_branch
        else {
            **map_schema,
            "allOf": [empty_object],
        }
    )
    spec = _spec({"/rpc/createWidget": {"post": _operation(request=request)}})
    pointer = (
        r"/schemas/CreateWidgetArgs/allOf/0/additionalProperties"
        if open_in_branch
        else r"/schemas/CreateWidgetArgs/additionalProperties"
    )

    with pytest.raises(ValueError, match=pointer):
        _contract(spec)


def test_tagged_rpc_rejects_referenced_typed_map_all_of_branch_that_constrains_a_sibling_field() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "allOf": [
                    {"$ref": "#/components/schemas/TypedMap"},
                    {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                ],
            },
            "TypedMap": {"type": "object", "additionalProperties": {"type": "string", "minLength": 2}},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match=r"/schemas/TypedMap/additionalProperties"):
        _contract(spec)


def test_tagged_rpc_rejects_wire_fields_with_the_same_python_name() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"fooBar": {"type": "string"}, "foo_bar": {"type": "integer"}},
                "required": ["fooBar", "foo_bar"],
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="normalize to Python field") as exc:
        _contract(spec)

    message = str(exc.value)
    assert "/schemas/WidgetArgs/properties/foo_bar" in message
    assert "fooBar" in message
    assert "foo_bar" in message


def test_tagged_rpc_rejects_write_field_that_shadows_payload_method() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"toPayload": {"type": "string"}},
                "required": ["toPayload"],
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="shadows generated method") as exc:
        _models(_contract(spec))

    message = str(exc.value)
    assert "/schemas/WidgetArgs/properties/toPayload" in message
    assert "to_payload" in message


def test_tagged_rpc_rejects_write_field_that_shadows_pydantic_method() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"modelDump": {"type": "string"}},
                "required": ["modelDump"],
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="shadows Pydantic member") as exc:
        _models(_contract(spec))

    assert "/schemas/WidgetArgs/properties/modelDump" in str(exc.value)


def test_tagged_rpc_rejects_nested_all_of_parent_with_typed_map_semantics() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "allOf": [{"type": "object"}],
                    }
                },
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="allOf cannot merge a typed map branch") as exc:
        _models(_contract(spec))

    assert "/schemas/WidgetArgs/properties/options/additionalProperties" in str(exc.value)


def test_tagged_rpc_rejects_nested_all_of_referenced_open_map_branch() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"options": {"allOf": [{"$ref": "#/components/schemas/OpenMap"}]}},
            },
            "OpenMap": {"type": "object", "additionalProperties": True},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="allOf cannot merge an open map branch") as exc:
        _models(_contract(spec))

    assert "/schemas/OpenMap/additionalProperties" in str(exc.value)


@pytest.mark.parametrize("wire_name", ["", "_token"])
def test_tagged_rpc_rejects_unusable_python_field_name(wire_name: str) -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {"type": "object", "properties": {wire_name: {"type": "string"}}},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="unusable Python field name") as exc:
        _models(_contract(spec))

    assert "/schemas/WidgetArgs/properties/" in str(exc.value)


def test_tagged_rpc_rejects_python_field_collision_across_all_of_branches() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "allOf": [
                    {"type": "object", "properties": {"fooBar": {"type": "string"}}, "required": ["fooBar"]},
                    {"type": "object", "properties": {"foo_bar": {"type": "integer"}}, "required": ["foo_bar"]},
                ]
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="normalize to Python field") as exc:
        _contract(spec)

    message = str(exc.value)
    assert "/schemas/WidgetArgs/allOf/1/properties/foo_bar" in message
    assert "fooBar" in message
    assert "foo_bar" in message


def test_tagged_rpc_codegen_rejects_duplicate_operation_names() -> None:
    spec = _spec(
        {
            "/rpc/first": {"post": _operation(operation_id="createWidget")},
            "/rpc/second": {"post": _operation(operation_id="create_widget")},
        }
    )
    with pytest.raises(ValueError, match=r"duplicate.*create_widget.*first.*second"):
        _contract(spec)


@pytest.mark.parametrize(
    ("route", "method", "malformed"),
    [
        ("/rpc/createWidget", "get", None),
        ("/widgets/createWidget", "post", None),
        ("/rpc/createWidget", "post", "request"),
        ("/rpc/createWidget", "post", "result"),
        ("/rpc/createWidget/nested", "post", None),
        ("/rpc/", "post", None),
    ],
)
def test_tagged_rpc_codegen_rejects_incompatible_route_shapes(route: str, method: str, malformed: str | None) -> None:
    operation = _operation()
    if malformed == "request":
        operation["requestBody"] = {"content": {"text/plain": {"schema": {"type": "string"}}}}
    elif malformed == "result":
        operation["responses"] = {"200": {"content": {"text/plain": {"schema": {"type": "string"}}}}}
    with pytest.raises(ValueError, match=route):
        _contract(_spec({route: {method: operation}}))


@pytest.mark.parametrize("location", ["request", "result", "nested"])
@pytest.mark.parametrize("reference", ["#/components/schemas/MissingWidget", "https://example.test/widget.json"])
def test_tagged_rpc_codegen_rejects_missing_or_external_schema_refs(location: str, reference: str) -> None:
    operation = _operation()
    schemas: dict[str, object] = {
        "WidgetArgs": {"type": "object", "properties": {}},
        "WidgetResult": {"type": "object", "properties": {}},
    }
    if location == "request":
        operation = _operation(request={"$ref": reference})
    elif location == "result":
        operation = _operation(result={"$ref": reference})
    else:
        schemas["WidgetArgs"] = {"type": "object", "properties": {"nested": {"$ref": reference}}}
    with pytest.raises(ValueError, match="/rpc/createWidget") as exc:
        _contract(_spec({"/rpc/createWidget": {"post": operation}}, schemas=schemas))
    message = str(exc.value)
    assert "/rpc/createWidget" in message
    if reference.startswith("#"):
        assert "MissingWidget" in message
        assert "missing" in message
    else:
        assert "local" in message
    if location == "nested":
        assert "WidgetArgs" in message


def test_tagged_rpc_inline_request_rejects_recursive_refs_before_emission() -> None:
    request: dict[str, object] = {
        "type": "object",
        "properties": {"tree": {"$ref": "#/components/schemas/Tree"}},
    }
    schemas: dict[str, object] = {
        "Tree": {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/Tree"}}},
        "WidgetResult": {"type": "object", "properties": {}},
        "Unrelated": {"$ref": "https://example.test/ignored.json"},
    }
    with pytest.raises(ValueError, match=r"/schemas/Tree/properties/child/\$ref"):
        _contract(_spec({"/rpc/createWidget": {"post": _operation(request=request)}}, schemas=schemas))


@pytest.mark.parametrize("is_request", [True, False])
def test_tagged_rpc_inline_roots_reject_existing_component_collisions(is_request: bool) -> None:
    operation = _operation(request={} if is_request else None, result={} if not is_request else None)
    spec = _spec({"/rpc/createWidget": {"post": operation}})
    schemas = cast(dict[str, object], cast(dict[str, object], spec["components"])["schemas"])
    schemas["CreateWidgetArgs" if is_request else "CreateWidgetResult"] = {"type": "string"}
    with pytest.raises(ValueError, match=r"/rpc/createWidget.*collid"):
        _contract(spec)


def test_tagged_rpc_inline_root_reuses_an_equivalent_existing_component() -> None:
    result: dict[str, object] = {"type": "object", "properties": {}}
    spec = _spec({"/rpc/deleteWidget": {"post": _operation(result=result)}})
    schemas = cast(dict[str, object], cast(dict[str, object], spec["components"])["schemas"])
    schemas["DeleteWidgetResult"] = {**result, "description": "Same wire contract"}
    assert _contract(spec)["schemas"]["DeleteWidgetResult"] == result


def test_tagged_rpc_codegen_rejects_request_response_model_name_collision() -> None:
    spec = _spec(
        {
            "/rpc/readFoo": {
                "post": _operation(
                    request={"$ref": "#/components/schemas/FooRead"},
                    result={"$ref": "#/components/schemas/Foo"},
                )
            }
        },
        schemas={
            "FooRead": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            "Foo": {"type": "object", "properties": {"accepted": {"type": "boolean"}}},
        },
    )

    with pytest.raises(ValueError, match="FooReadDTO") as exc:
        codegen._emit_rpc_namespace_dto(
            cast(codegen.Metadata, {"installations": {}, "rpc_namespaces": {"widgets": _contract(spec)}})
        )

    message = str(exc.value)
    assert "FooReadDTO" in message
    assert "request #/components/schemas/FooRead" in message
    assert "response #/components/schemas/Foo" in message


def test_tagged_rpc_codegen_rejects_collision_with_existing_dto_class() -> None:
    spec = _spec(
        {
            "/rpc/createConnection": {
                "post": _operation(
                    request={"$ref": "#/components/schemas/ConnectionCreate"},
                    result={"$ref": "#/components/schemas/WidgetResult"},
                )
            }
        },
        schemas={
            "ConnectionCreate": {"type": "object", "properties": {"name": {"type": "string"}}},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )
    contract = _contract(spec)

    with pytest.raises(ValueError, match=r"ConnectionCreateDTO.*existing DTO class"):
        codegen.emit_dto(cast(codegen.Metadata, {"installations": {}, "rpc_namespaces": {"widgets": contract}}))


def test_tagged_rpc_codegen_rejects_collision_with_existing_dto_alias(tmp_path: Path) -> None:
    spec = _installation_spec("yacloud")
    _add_installation_rpc(
        spec,
        route="/rpc/createCollision",
        tag="Widgets",
        request_name="WizardChartEntryRead",
        result_name="CollisionResult",
        result_schema={"type": "object", "properties": {}},
    )
    installation = _write_installation_spec(tmp_path, "yacloud", spec)
    metadata = codegen.build_metadata(
        {"yacloud": installation},
        rpc_namespace_configs=({"tag": "Widgets", "namespace": "widgets"},),
    )

    with pytest.raises(ValueError, match=r"WizardChartEntryReadDTO.*existing DTO class"):
        codegen.emit_dto(metadata)


def test_tagged_rpc_codegen_rejects_inline_and_component_model_name_collision() -> None:
    spec = _spec(
        {
            "/rpc/createFoo": {
                "post": _operation(
                    request={"$ref": "#/components/schemas/Foo"},
                    result={"$ref": "#/components/schemas/WidgetResult"},
                )
            }
        },
        schemas={
            "Foo": {
                "type": "object",
                "properties": {
                    "bar": {"type": "object", "properties": {"inline": {"type": "string"}}},
                    "related": {"$ref": "#/components/schemas/FooBar"},
                },
            },
            "FooBar": {"type": "object", "properties": {"component": {"type": "integer"}}},
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="FooBarDTO") as exc:
        codegen._emit_rpc_namespace_dto(
            cast(codegen.Metadata, {"installations": {}, "rpc_namespaces": {"widgets": _contract(spec)}})
        )

    message = str(exc.value)
    assert "#/components/schemas/Foo (schema path ('bar',))" in message
    assert "#/components/schemas/FooBar" in message


def test_tagged_rpc_contracts_omit_absent_tags_and_preserve_shared_schemas() -> None:
    spec = _spec(
        {
            "/rpc/createWidget": {"post": _operation()},
            "/rpc/readGadget": {"post": _operation(tag="Gadgets")},
        }
    )
    assert codegen.build_rpc_namespace_contract_meta(spec, config={"tag": "Missing", "namespace": "missing"}) is None
    contracts = codegen.build_rpc_namespace_contracts(
        spec,
        configs=(
            {"tag": "Widgets", "namespace": "widgets"},
            {"tag": "Gadgets", "namespace": "gadgets"},
            {"tag": "Missing", "namespace": "missing"},
        ),
    )
    assert contracts["widgets"]["operations"]["create_widget"]["route"] == "/rpc/createWidget"
    assert contracts["gadgets"]["operations"]["read_gadget"]["route"] == "/rpc/readGadget"
    assert contracts["widgets"]["schemas"] == contracts["gadgets"]["schemas"]
    assert "missing" not in contracts


def test_tagged_rpc_contracts_reject_duplicate_namespace_configuration() -> None:
    with pytest.raises(ValueError, match=r"duplicate.*widgets"):
        codegen.build_rpc_namespace_contracts(
            _spec({"/rpc/createWidget": {"post": _operation()}}),
            configs=(
                {"tag": "Widgets", "namespace": "widgets"},
                {"tag": "Widgets", "namespace": "widgets"},
            ),
        )


def test_tagged_rpc_codegen_allows_an_installation_without_the_tag(tmp_path: Path) -> None:
    specs = {name: _installation_spec(name) for name in ("enterprise", "yacloud")}
    _add_installation_rpc(
        specs["yacloud"],
        route="/rpc/createTaggedWidget",
        tag="Widgets",
        request_name="TaggedWidgetArgs",
        result_name="TaggedWidgetResult",
        result_schema={"type": "object", "properties": {"accepted": {"type": "boolean"}}},
    )
    installations = {name: _write_installation_spec(tmp_path, name, spec) for name, spec in specs.items()}
    metadata = codegen.build_metadata(
        installations,
        rpc_namespace_configs=({"tag": "Widgets", "namespace": "widgets"},),
    )

    assert metadata["rpc_namespaces"]["widgets"]["tag"] == "Widgets"
    generated = codegen.emit_dto(metadata)
    scope = _load_models(generated[generated.index("\nclass TaggedWidgetArgsDTO(BaseModel):") :])
    assert _model(scope, "TaggedWidgetArgsDTO")(id="x", enabled=False).to_payload() == {  # type: ignore[attr-defined]
        "id": "x",
        "enabled": False,
    }


def test_tagged_rpc_shared_response_model_is_reused_across_namespaces(tmp_path: Path) -> None:
    spec = _installation_spec("yacloud")
    shared_ref = {"$ref": "#/components/schemas/TaggedSharedReceipt"}
    for route, tag, request_name, result_name in (
        ("/rpc/createTaggedWidget", "Widgets", "TaggedWidgetArgs", "TaggedWidgetResult"),
        ("/rpc/createTaggedGadget", "Gadgets", "TaggedGadgetArgs", "TaggedGadgetResult"),
    ):
        _add_installation_rpc(
            spec,
            route=route,
            tag=tag,
            request_name=request_name,
            result_name=result_name,
            result_schema={
                "type": "object",
                "properties": {"receipt": shared_ref},
                "required": ["receipt"],
            },
        )
    schemas = cast(dict[str, object], cast(dict[str, object], spec["components"])["schemas"])
    schemas["TaggedSharedReceipt"] = {
        "type": "object",
        "properties": {"accepted": {"type": "boolean"}},
        "required": ["accepted"],
    }
    metadata = codegen.build_metadata(
        {"yacloud": _write_installation_spec(tmp_path, "yacloud", spec)},
        rpc_namespace_configs=(
            {"tag": "Widgets", "namespace": "widgets"},
            {"tag": "Gadgets", "namespace": "gadgets"},
        ),
    )

    scope = _load_models(codegen._emit_rpc_namespace_dto(metadata))
    widget_receipt = _model(scope, "TaggedWidgetResultReadDTO").model_fields["receipt"].annotation
    gadget_receipt = _model(scope, "TaggedGadgetResultReadDTO").model_fields["receipt"].annotation
    assert widget_receipt is gadget_receipt is _model(scope, "TaggedSharedReceiptReadDTO")
    assert _model(scope, "TaggedWidgetResultReadDTO").model_validate({"receipt": {"accepted": True}}).receipt.accepted  # type: ignore[attr-defined]


def test_tagged_rpc_codegen_rejects_cross_installation_contract_drift(tmp_path: Path) -> None:
    specs = {name: _installation_spec(name) for name in ("enterprise", "yacloud")}
    for spec in specs.values():
        _add_installation_rpc(
            spec,
            route="/rpc/createTaggedWidget",
            tag="Widgets",
            request_name="TaggedWidgetArgs",
            result_name="TaggedWidgetResult",
            result_schema={"type": "object", "properties": {"accepted": {"type": "boolean"}}},
        )
    yacloud_schemas = cast(dict[str, object], cast(dict[str, object], specs["yacloud"]["components"])["schemas"])
    yacloud_schemas["TaggedWidgetResult"] = {"type": "object", "properties": {"accepted": {"type": "string"}}}
    installations = {name: _write_installation_spec(tmp_path, name, spec) for name, spec in specs.items()}

    with pytest.raises(ValueError, match=r"widgets.*enterprise.*yacloud"):
        codegen.build_metadata(
            installations,
            rpc_namespace_configs=({"tag": "Widgets", "namespace": "widgets"},),
        )


def test_tagged_rpc_yc_scoped_contract_uses_yc_wire_response_when_enterprise_differs(tmp_path: Path) -> None:
    specs = {name: _installation_spec(name) for name in ("enterprise", "yacloud")}
    for name, spec in specs.items():
        _add_installation_rpc(
            spec,
            route="/rpc/getTaggedWidget",
            tag="Widgets",
            request_name="TaggedWidgetArgs",
            result_name="TaggedWidgetResult",
            result_schema={
                "type": "object",
                "properties": {"accepted": {"type": "boolean" if name == "yacloud" else "string"}},
                "required": ["accepted"],
            },
        )
    installations = {name: _write_installation_spec(tmp_path, name, spec) for name, spec in specs.items()}

    metadata = codegen.build_metadata(
        installations,
        rpc_namespace_configs=({"tag": "Widgets", "namespace": "widgets", "installations": ("yacloud",)},),
    )
    scope = _load_models(codegen._emit_rpc_namespace_dto(metadata))
    result = _model(scope, "TaggedWidgetResultReadDTO")

    assert result.model_validate({"accepted": True}).model_dump() == {"accepted": True}
    with pytest.raises(ValidationError):
        result.model_validate({"accepted": "true"})


def test_tagged_rpc_empty_installations_keep_empty_metadata() -> None:
    assert codegen.build_metadata({}, rpc_namespace_configs=({"tag": "Widgets", "namespace": "widgets"},)) == {
        "installations": {}
    }


def test_tagged_rpc_request_payload_preserves_omitted_and_explicit_empty_values() -> None:
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "enabled": {"type": "boolean"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["id"],
        },
        result={"type": "object", "properties": {}},
    )
    request = _model(scope, "WidgetArgsDTO")
    assert request(id="x").to_payload() == {"id": "x"}  # type: ignore[attr-defined]
    assert request(id="x", enabled=False, labels=[], options={}).to_payload() == {  # type: ignore[attr-defined]
        "id": "x",
        "enabled": False,
        "labels": [],
        "options": {},
    }


def test_tagged_rpc_write_dto_rejects_unknown_fields_and_pattern_mismatches() -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {"id": {"type": "string", "pattern": "^[A-Z]+$"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )
    with pytest.raises(ValidationError):
        request(id="OK", surprise=True)
    with pytest.raises(ValidationError):
        request(id="lower")
    assert request(id="OK").to_payload() == {"id": "OK"}  # type: ignore[attr-defined]


def test_tagged_rpc_write_dto_supports_ecma_regex_lookaround() -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {"value": {"type": "string", "pattern": "(?=abc)abc"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )

    assert request(value="abc").to_payload() == {"value": "abc"}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request(value="abx")


def test_tagged_rpc_pattern_digit_matches_ecmascript_ascii_semantics() -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {"value": {"type": "string", "pattern": r"^\d+$"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )

    assert request(value="123").to_payload() == {"value": "123"}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request(value="٣")


def test_tagged_rpc_pattern_non_whitespace_matches_ecmascript_semantics() -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "pattern": r"^\S+$",
                    }
                },
                "required": ["value"],
                "additionalProperties": False,
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )

    assert request(value="spark-cluster").to_payload() == {"value": "spark-cluster"}  # type: ignore[attr-defined]
    assert request(value="spark\u0085cluster").to_payload() == {"value": "spark\u0085cluster"}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request(value="spark cluster")
    with pytest.raises(ValidationError):
        request(value="spark\ufeffcluster")


@pytest.mark.parametrize("pattern", [r"^\w+$", "("])
def test_tagged_rpc_rejects_unsupported_regex_dialect_at_generation(pattern: str) -> None:
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/properties/value/pattern"):
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}},
                schemas={
                    "WidgetArgs": {
                        "type": "object",
                        "properties": {"value": {"type": "string", "pattern": pattern}},
                    },
                    "WidgetResult": {"type": "object", "properties": {}},
                },
            )
        )


def test_tagged_rpc_rejects_named_properties_with_open_extras() -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "additionalProperties": True,
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="open extras on an object with named properties") as exc:
        _contract(spec)

    assert "/schemas/WidgetArgs/additionalProperties" in str(exc.value)


@pytest.mark.parametrize("additional", [{"type": "string"}, False])
def test_tagged_rpc_rejects_constrained_map_without_an_object_type(additional: object) -> None:
    spec = _spec(
        {"/rpc/createWidget": {"post": _operation()}},
        schemas={
            "WidgetArgs": {
                "type": "object",
                "properties": {"options": {"additionalProperties": additional}},
            },
            "WidgetResult": {"type": "object", "properties": {}},
        },
    )

    with pytest.raises(ValueError, match="constrained map requires an object type") as exc:
        _models(_contract(spec))

    assert "/schemas/WidgetArgs/properties/options/additionalProperties" in str(exc.value)


def test_tagged_rpc_nested_nullable_typed_map_validates_values() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "options": {
                "type": ["object", "null"],
                "additionalProperties": {"type": "string", "minLength": 2},
            }
        },
        "required": ["options"],
    }
    scope = _widget_models(request=schema, result=schema)
    request = _model(scope, "WidgetArgsDTO")
    response = _model(scope, "WidgetResultReadDTO")

    for value in ({"label": "ok"}, None):
        assert request(options=value).to_payload() == {"options": value}  # type: ignore[attr-defined]
        assert response(options=value).model_dump() == {"options": value}
    for model in (request, response):
        with pytest.raises(ValidationError):
            model(options={"label": "x"})


def test_tagged_rpc_closed_object_with_named_properties_does_not_require_an_explicit_type() -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {
                    "options": {
                        "properties": {"label": {"type": "string"}},
                        "required": ["label"],
                        "additionalProperties": False,
                    }
                },
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )
    assert request(options={"label": "ok"}).to_payload() == {"options": {"label": "ok"}}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request(options={"label": "ok", "other": 1})


def test_tagged_rpc_constraints_apply_through_nested_unions_and_maps() -> None:
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 2, "maxLength": 4, "pattern": "^[A-Z]+$"},
                "count": {"type": "integer", "minimum": 1, "maximum": 3},
                "nested": {
                    "type": "object",
                    "properties": {"ratio": {"type": "number", "minimum": 0.5, "maximum": 1.5}},
                },
                "values": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "minLength": 2, "maxLength": 3},
                },
                "items": {"type": "array", "items": {"type": "integer", "minimum": 2, "maximum": 4}},
                "choice": {
                    "anyOf": [
                        {"type": "null"},
                        {"type": "string", "minLength": 2, "maxLength": 3, "pattern": "^[a-z]+$"},
                    ]
                },
            },
            "required": ["name", "count"],
        },
        result={"type": "object", "properties": {}},
    )
    request = _model(scope, "WidgetArgsDTO")
    assert request(name="AB", count=2, nested={"ratio": 1.0}, values={"a": "ok"}, items=[2], choice="abc").to_payload()  # type: ignore[attr-defined]
    for invalid in (
        {"name": "a", "count": 2},
        {"name": "ABCDE", "count": 2},
        {"name": "Ab", "count": 2},
        {"name": "AB", "count": 0},
        {"name": "AB", "count": 4},
        {"name": "AB", "count": 2, "nested": {"ratio": 0.1}},
        {"name": "AB", "count": 2, "nested": {"ratio": 2.0}},
        {"name": "AB", "count": 2, "values": {"a": "x"}},
        {"name": "AB", "count": 2, "items": [5]},
        {"name": "AB", "count": 2, "choice": "A"},
    ):
        with pytest.raises(ValidationError):
            request.model_validate(invalid)


@pytest.mark.parametrize("read", [False, True])
@pytest.mark.parametrize("value", [9007199254740993, 1.25, 1.0])
def test_tagged_rpc_number_round_trips_integer_precision_and_floats(read: bool, value: int | float) -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "numberValue": {"type": "number"},
            "boundedNumber": {"type": "number", "minimum": 0, "maximum": 9007199254740994},
            "values": {"type": "array", "items": {"type": "number"}},
            "mapping": {"type": "object", "additionalProperties": {"type": "number"}},
            "choice": {"anyOf": [{"type": "string"}, {"type": "number"}]},
        },
        "required": ["numberValue", "boundedNumber", "values", "mapping", "choice"],
    }
    model = _model(_widget_models(request=schema, result=schema), "WidgetResultReadDTO" if read else "WidgetArgsDTO")
    payload = {
        "numberValue": value,
        "boundedNumber": value,
        "values": [value],
        "mapping": {"a": value},
        "choice": value,
    }
    for instance in (model.model_validate(payload), model.model_validate_json(json.dumps(payload))):
        serialized = (
            instance.model_dump(mode="json", by_alias=True) if read else instance.to_payload()  # type: ignore[attr-defined]
        )
        assert serialized == payload
        assert type(serialized["numberValue"]) is type(value)
        assert type(serialized["boundedNumber"]) is type(value)
    for invalid in (-1, 9007199254740996, True, "1"):
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "boundedNumber": invalid})


def test_tagged_rpc_nested_array_bounds_validate_and_serialize() -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 2,
                        "items": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
                    }
                },
                "required": ["rows"],
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )
    assert request(rows=[[""]]).to_payload() == {"rows": [[""]]}  # type: ignore[attr-defined]
    assert request(rows=[["a", "b"], ["c"]]).to_payload() == {"rows": [["a", "b"], ["c"]]}  # type: ignore[attr-defined]
    for invalid in ([], [[], ["a"]], [["a", "b", "c"]], [["a"], ["b"], ["c"]]):
        with pytest.raises(ValidationError):
            request(rows=invalid)


@pytest.mark.parametrize("required", [True, False])
def test_tagged_rpc_aliased_tuple_with_constrained_prefix_item_round_trips(required: bool) -> None:
    tuple_schema: dict[str, object] = {
        "type": "array",
        "prefixItems": [{"type": "string", "minLength": 2}, {"type": "integer"}],
    }
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {"wireTuple": tuple_schema},
            "required": ["wireTuple"] if required else [],
        },
        result={
            "type": "object",
            "properties": {"wireTuple": tuple_schema},
            "required": ["wireTuple"],
        },
    )
    request = _model(scope, "WidgetArgsDTO")
    response = _model(scope, "WidgetResultReadDTO")

    assert request.model_validate({"wireTuple": ["ok", 3]}).to_payload() == {"wireTuple": ["ok", 3]}  # type: ignore[attr-defined]
    assert request(wire_tuple=("ok", 3)).to_payload() == {"wireTuple": ["ok", 3]}  # type: ignore[attr-defined]
    assert response.model_validate({"wireTuple": ["ok", 3]}).model_dump(mode="json", by_alias=True) == {
        "wireTuple": ["ok", 3]
    }
    with pytest.raises(ValidationError):
        request.model_validate({"wireTuple": ["x", 3]})
    if not required:
        assert request().to_payload() == {}  # type: ignore[attr-defined]


def test_tagged_rpc_prefix_items_without_tail_constraint_accepts_short_and_long_arrays() -> None:
    tuple_schema: dict[str, object] = {
        "type": "array",
        "prefixItems": [{"type": "string", "minLength": 2}, {"type": "integer"}],
    }
    shape: dict[str, object] = {"type": "object", "properties": {"wireTuple": tuple_schema}, "required": ["wireTuple"]}
    scope = _widget_models(request=shape, result=shape, real_json=True)
    request = _model(scope, "WidgetArgsDTO")
    response = _model(scope, "WidgetResultReadDTO")

    for values in ([], ["ok"], ["ok", 3], ["ok", 3, {"extra": True}]):
        assert request.model_validate({"wireTuple": values}).to_payload() == {"wireTuple": values}  # type: ignore[attr-defined]
        assert response.model_validate({"wireTuple": values}).model_dump(mode="json", by_alias=True) == {
            "wireTuple": values
        }
    for values in (["x"], ["ok", True], ["ok", 3, object()]):
        with pytest.raises(ValidationError):
            request.model_validate({"wireTuple": values})
        with pytest.raises(ValidationError):
            response.model_validate({"wireTuple": values})


def test_tagged_rpc_prefix_items_validate_typed_tail_and_array_bounds() -> None:
    tuple_schema: dict[str, object] = {
        "type": "array",
        "prefixItems": [{"type": "string"}],
        "items": {"type": "integer", "minimum": 0},
        "minItems": 1,
        "maxItems": 3,
    }
    shape: dict[str, object] = {"type": "object", "properties": {"wireTuple": tuple_schema}, "required": ["wireTuple"]}
    scope = _widget_models(request=shape, result=shape)
    for model in (_model(scope, "WidgetArgsDTO"), _model(scope, "WidgetResultReadDTO")):
        for values in (["ok"], ["ok", 0], ["ok", 1, 2]):
            assert model.model_validate({"wireTuple": values}).model_dump(mode="json", by_alias=True) == {
                "wireTuple": values
            }
        for values in ([], ["ok", -1], ["ok", "1"], ["ok", 1, 2, 3]):
            with pytest.raises(ValidationError):
                model.model_validate({"wireTuple": values})


@pytest.mark.parametrize("tail", [False, True])
def test_tagged_rpc_prefix_items_respect_boolean_tail_policy(tail: bool) -> None:
    tuple_schema: dict[str, object] = {
        "type": "array",
        "prefixItems": [{"type": "string"}],
        "items": tail,
    }
    shape: dict[str, object] = {"type": "object", "properties": {"wireTuple": tuple_schema}, "required": ["wireTuple"]}
    scope = _widget_models(request=shape, result=shape, real_json=True)
    for model in (_model(scope, "WidgetArgsDTO"), _model(scope, "WidgetResultReadDTO")):
        assert model.model_validate({"wireTuple": []}).model_dump(mode="json", by_alias=True) == {"wireTuple": []}
        assert model.model_validate({"wireTuple": ["ok"]}).model_dump(mode="json", by_alias=True) == {
            "wireTuple": ["ok"]
        }
        if tail:
            assert model.model_validate({"wireTuple": ["ok", {"extra": 1}]}).model_dump(mode="json", by_alias=True) == {
                "wireTuple": ["ok", {"extra": 1}]
            }
        else:
            with pytest.raises(ValidationError):
                model.model_validate({"wireTuple": ["ok", 2]})


def test_tagged_rpc_prefix_items_keep_nested_dto_validation_and_wire_aliases() -> None:
    tuple_schema: dict[str, object] = {"type": "array", "prefixItems": [{"$ref": "#/components/schemas/TupleChild"}]}
    shape = {"type": "object", "properties": {"wireTuple": tuple_schema}, "required": ["wireTuple"]}
    scope = _models(
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}},
                schemas={
                    "WidgetArgs": shape,
                    "WidgetResult": shape,
                    "TupleChild": {
                        "type": "object",
                        "properties": {"wireValue": {"type": "string", "minLength": 2}},
                        "required": ["wireValue"],
                    },
                },
            )
        ),
        real_json=True,
    )
    request = _model(scope, "WidgetArgsDTO").model_validate({"wireTuple": [{"wireValue": "ok"}]})
    response = _model(scope, "WidgetResultReadDTO").model_validate({"wireTuple": [{"wireValue": "ok"}]})
    assert isinstance(request.wire_tuple[0], _model(scope, "TupleChildDTO"))  # type: ignore[attr-defined]
    assert isinstance(response.wire_tuple[0], _model(scope, "TupleChildReadDTO"))  # type: ignore[attr-defined]
    assert request.to_payload() == {"wireTuple": [{"wireValue": "ok"}]}  # type: ignore[attr-defined]
    assert response.model_dump(mode="json", by_alias=True) == {"wireTuple": [{"wireValue": "ok"}]}
    with pytest.raises(ValidationError):
        _model(scope, "WidgetArgsDTO").model_validate({"wireTuple": [{"wireValue": "x"}]})


@pytest.mark.parametrize("constraint", ["minItems", "maxItems"])
@pytest.mark.parametrize("schema_type", ["string", "object", "null", ["array", "string"]])
def test_tagged_rpc_array_bounds_reject_incompatible_types(constraint: str, schema_type: object) -> None:
    with pytest.raises(
        ValueError, match=rf"/schemas/WidgetArgs/properties/value/{constraint}: incompatible schema type"
    ):
        _widget_models(
            request={"type": "object", "properties": {"value": {"type": schema_type, constraint: 1}}},
            result={"type": "object", "properties": {}},
        )


@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize(
    ("alternative", "wire_value"),
    [
        ({"type": "integer", "minimum": 0}, 0),
        ({"type": "array", "maxItems": 2, "items": {"type": "string"}}, []),
        ({"type": "boolean"}, False),
    ],
)
def test_tagged_rpc_constrained_union_alias_preserves_wire_payload(
    required: bool, alternative: dict[str, object], wire_value: object
) -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {"wireValue": {"anyOf": [{"type": "string", "minLength": 2}, alternative]}},
                "required": ["wireValue"] if required else [],
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )
    for value in ("ok", wire_value):
        assert request.model_validate({"wireValue": value}).to_payload() == {"wireValue": value}  # type: ignore[attr-defined]
        assert request(wire_value=value).to_payload() == {"wireValue": value}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request.model_validate({"wireValue": "x"})
    if required:
        with pytest.raises(ValidationError):
            request.model_validate({})
    else:
        assert request().to_payload() == {}  # type: ignore[attr-defined]


def test_tagged_rpc_read_dto_ignores_unknown_fields_but_requires_declared_fields() -> None:
    response = _model(
        _widget_models(
            request={"type": "object", "properties": {}, "additionalProperties": False},
            result={"type": "object", "properties": {"accepted": {"type": "boolean"}}, "required": ["accepted"]},
        ),
        "WidgetResultReadDTO",
    )
    assert response.model_validate({"accepted": True, "future": "new"}).model_dump() == {"accepted": True}
    with pytest.raises(ValidationError):
        response.model_validate({"future": "new"})


def test_tagged_rpc_union_request_variants_serialize_their_payloads() -> None:
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {
                "choice": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {"kind": {"enum": ["left"]}, "left": {"type": "string"}},
                            "required": ["kind", "left"],
                        },
                        {
                            "type": "object",
                            "properties": {"kind": {"enum": ["right"]}, "right": {"type": "integer"}},
                            "required": ["kind", "right"],
                        },
                    ]
                }
            },
        },
        result={"type": "object", "properties": {}},
    )
    assert _model(scope, "WidgetArgsChoiceAnyOf0DTO")(kind="left", left="x").to_payload() == {  # type: ignore[attr-defined]
        "kind": "left",
        "left": "x",
    }
    assert _model(scope, "WidgetArgsChoiceAnyOf1DTO")(kind="right", right=2).to_payload() == {  # type: ignore[attr-defined]
        "kind": "right",
        "right": 2,
    }


def test_tagged_rpc_nested_write_objects_serialize_their_payloads() -> None:
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {
                "direct": {"type": "object", "properties": {"value": {"type": "string"}}},
                "array": {"type": "array", "items": {"type": "object", "properties": {"value": {"type": "string"}}}},
                "map": {
                    "type": "object",
                    "additionalProperties": {"type": "object", "properties": {"other": {"type": "integer"}}},
                },
                "union": {
                    "anyOf": [
                        {"type": "object", "properties": {"kind": {"enum": ["one"]}}},
                        {"type": "object", "properties": {"kind": {"enum": ["two"]}}},
                    ]
                },
            },
        },
        result={"type": "object", "properties": {}},
    )
    for name, kwargs, expected in (
        ("WidgetArgsArrayItemDTO", {"value": "x"}, {"value": "x"}),
        ("WidgetArgsMapValueDTO", {"other": 2}, {"other": 2}),
        ("WidgetArgsUnionAnyOf0DTO", {"kind": "one"}, {"kind": "one"}),
        ("WidgetArgsUnionAnyOf1DTO", {"kind": "two"}, {"kind": "two"}),
    ):
        assert _model(scope, name)(**kwargs).to_payload() == expected  # type: ignore[attr-defined]
    payload = {
        "direct": {"value": "x"},
        "array": [{"value": "y"}],
        "map": {"first": {"other": 2}},
        "union": {"kind": "one"},
    }
    root = _model(scope, "WidgetArgsDTO")
    assert root.model_validate(payload).to_payload() == payload  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        root.model_validate({"direct": {"value": 2}})


def test_html_payload_policy_preserves_root_variants_and_nested_models() -> None:
    schemas: dict[str, JsonValue] = {
        "CreateHtmlPageArgs": {
            "type": "object",
            "properties": {"nested": {"type": "object", "properties": {"value": {"type": "string"}}}},
        },
        "DeleteHtmlPageArgs": {"type": "object", "properties": {"id": {"type": "string"}}},
        "GetHtmlPageArgs": {"type": "object", "properties": {"id": {"type": "string"}}},
        "GetHtmlPagePreviewUrlArgs": {"type": "object", "properties": {"id": {"type": "string"}}},
        "UpdateHtmlPageArgs": {
            "anyOf": [
                {"type": "object", "properties": {"kind": {"enum": ["one"]}}},
                {"type": "object", "properties": {"kind": {"enum": ["two"]}}},
            ]
        },
        "CreateHtmlPageResult": {"type": "object", "properties": {"id": {"type": "string"}}},
        "GetHtmlPageResult": {"type": "object", "properties": {"id": {"type": "string"}}},
        "GetHtmlPagePreviewUrlResult": {"type": "object", "properties": {"url": {"type": "string"}}},
        "UpdateHtmlPageResult": {"type": "object", "properties": {"id": {"type": "string"}}},
    }
    source = codegen._emit_html_page_dto(
        cast(codegen.Metadata, {"installations": {}, "html_page": {"roots": sorted(schemas), "schemas": schemas}})
    )
    scope = _load_models(source)
    for name in (
        "CreateHtmlPageArgsDTO",
        "DeleteHtmlPageArgsDTO",
        "GetHtmlPageArgsDTO",
        "GetHtmlPagePreviewUrlArgsDTO",
    ):
        assert _model(scope, name)().to_payload() == {}  # type: ignore[attr-defined]
    assert _model(scope, "UpdateHtmlPageArgsAnyOf0DTO")(kind="one").to_payload() == {"kind": "one"}  # type: ignore[attr-defined]
    assert _model(scope, "UpdateHtmlPageArgsAnyOf1DTO")(kind="two").to_payload() == {"kind": "two"}  # type: ignore[attr-defined]
    assert _model(scope, "CreateHtmlPageArgsDTO").model_validate({"nested": {"value": "x"}}).to_payload() == {  # type: ignore[attr-defined]
        "nested": {"value": "x"}
    }
    assert _model(scope, "GetHtmlPagePreviewUrlArgsDTO")(id="page-1").to_payload() == {  # type: ignore[attr-defined]
        "id": "page-1"
    }
    assert _model(scope, "GetHtmlPagePreviewUrlResultReadDTO").model_validate(
        {"url": "https://example.test/preview", "future": True}
    ).model_dump() == {"url": "https://example.test/preview"}
    assert not hasattr(_model(scope, "CreateHtmlPageArgsNestedDTO"), "to_payload")


def test_html_payload_policy_does_not_promote_identical_nested_objects() -> None:
    helper: JsonValue = {"type": "object", "properties": {"value": {"type": "string"}}}
    schemas: dict[str, JsonValue] = {
        "AWrapper": {"type": "object", "properties": {"helper": helper}},
        "BUnion": {"anyOf": [helper, {"type": "object", "properties": {"other": {"type": "string"}}}]},
    }
    source = codegen._PydanticSchemaEmitter(schemas, read=False, contract="HtmlPages", payload_methods="roots").emit(
        schemas
    )
    scope = _load_models(source)
    assert not hasattr(_model(scope, "AWrapperHelperDTO"), "to_payload")
    assert _model(scope, "BUnionAnyOf0DTO")(value="x").to_payload() == {"value": "x"}  # type: ignore[attr-defined]


def test_tagged_rpc_inline_empty_response_accepts_an_empty_object() -> None:
    contract = _contract(
        _spec({"/rpc/deleteWidget": {"post": _operation(result={"type": "object", "properties": {}})}})
    )
    response = _model(_models(contract), "DeleteWidgetResultReadDTO")
    assert response.model_validate({}).model_dump() == {}
    assert response.model_validate({"future": True}).model_dump() == {}


def test_tagged_rpc_codegen_rejects_unsupported_behavioral_constraints() -> None:
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/properties/items/uniqueItems"):
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}},
                schemas={
                    "WidgetArgs": {
                        "type": "object",
                        "properties": {"items": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}},
                    },
                    "WidgetResult": {"type": "object", "properties": {}},
                },
            )
        )


@pytest.mark.parametrize("union_key", ["anyOf", "oneOf"])
def test_tagged_rpc_all_of_object_union_preserves_base_and_variant_fields(union_key: str) -> None:
    request = _model(
        _widget_models(
            request={
                "type": "object",
                "properties": {
                    "params": {
                        "type": "array",
                        "items": {
                            "allOf": [
                                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                                {
                                    union_key: [
                                        {
                                            "type": "object",
                                            "properties": {"kind": {"enum": ["text"]}, "value": {"type": "string"}},
                                            "required": ["kind", "value"],
                                        },
                                        {
                                            "type": "object",
                                            "properties": {"kind": {"enum": ["flag"]}, "value": {"type": "boolean"}},
                                            "required": ["kind", "value"],
                                        },
                                    ]
                                },
                            ]
                        },
                    }
                },
                "required": ["params"],
            },
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )
    payload = {"params": [{"name": "a", "kind": "text", "value": ""}, {"name": "b", "kind": "flag", "value": False}]}
    assert request.model_validate(payload).to_payload() == payload  # type: ignore[attr-defined]
    for invalid in (
        {"kind": "text", "value": "x"},
        {"name": "a", "kind": "text"},
        {"name": "a", "kind": "flag", "value": "x"},
        {"name": "a", "kind": "other", "value": False},
        {"name": "a", "kind": "text", "value": "x", "extra": True},
    ):
        with pytest.raises(ValidationError):
            request.model_validate({"params": [invalid]})


@pytest.mark.parametrize(("union_key", "referenced"), [("anyOf", False), ("anyOf", True), ("oneOf", False)])
@pytest.mark.parametrize("closed", [False, True])
def test_tagged_rpc_all_of_union_does_not_widen_closed_object_branches(
    union_key: str, referenced: bool, closed: bool
) -> None:
    branch: dict[str, object] = {
        "type": "object",
        "properties": {"kind": {"enum": ["text"]}},
        "required": ["kind"],
    }
    if closed:
        branch["additionalProperties"] = False
    schemas: dict[str, object] = {
        "WidgetArgs": {
            "type": "object",
            "properties": {
                "param": {
                    "allOf": [
                        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                        {union_key: [{"$ref": "#/components/schemas/TextBranch"} if referenced else branch]},
                    ]
                }
            },
            "required": ["param"],
        },
        "WidgetResult": {"type": "object", "properties": {}},
        "TextBranch": branch,
    }
    spec = _spec({"/rpc/createWidget": {"post": _operation()}}, schemas=schemas)
    payload = {"param": {"name": "n", "kind": "text"}}

    def validate_payload() -> None:
        request = _model(_models(_contract(spec)), "WidgetArgsDTO")
        assert request.model_validate(payload).to_payload() == payload  # type: ignore[attr-defined]

    if closed:
        pointer = (
            "/schemas/TextBranch/additionalProperties"
            if referenced
            else f"/schemas/WidgetArgs/properties/param/allOf/1/{union_key}/0/additionalProperties"
        )
        # The name required by the base is forbidden by the closed branch. The
        # generator must reject this intersection instead of emitting an accepting DTO.
        with pytest.raises(ValueError, match=pointer):
            validate_payload()
    else:
        validate_payload()


@pytest.mark.parametrize("additional", [False, {"type": "string"}])
def test_tagged_rpc_all_of_rejects_child_property_for_constrained_parent(additional: object) -> None:
    request: dict[str, object] = {
        "type": "object",
        "additionalProperties": additional,
        "allOf": [
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ],
    }
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/additionalProperties"):
        _widget_models(request=request, result={"type": "object", "properties": {}})


def test_tagged_rpc_all_of_union_property_conflict_fails_with_pointer() -> None:
    request: dict[str, object] = {
        "allOf": [
            {"type": "object", "properties": {"name": {"type": "string", "minLength": 2}}},
            {"anyOf": [{"type": "object", "properties": {"name": {"type": "string", "maxLength": 4}}}]},
        ]
    }
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/allOf/1: allOf overlaps property 'name'"):
        _widget_models(request=request, result={"type": "object", "properties": {}})


def test_tagged_rpc_all_of_overlapping_property_constraints_fail_with_pointer() -> None:
    request: dict[str, object] = {
        "allOf": [
            {"type": "object", "properties": {"name": {"type": "string", "minLength": 2}}},
            {"type": "object", "properties": {"name": {"type": "string", "maxLength": 4}}},
        ]
    }
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/allOf/1/properties/name"):
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}},
                schemas={"WidgetArgs": request, "WidgetResult": {"type": "object", "properties": {}}},
            )
        )


def test_tagged_rpc_all_of_parent_property_conflict_fails_with_pointer() -> None:
    request: dict[str, object] = {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 2}},
        "allOf": [
            {"type": "object", "properties": {"name": {"type": "string", "maxLength": 4}}},
        ],
    }
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/allOf/0/properties/name"):
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}},
                schemas={"WidgetArgs": request, "WidgetResult": {"type": "object", "properties": {}}},
            )
        )


def test_tagged_rpc_all_of_preserves_identical_property_constraints() -> None:
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 2}},
            "allOf": [
                {"type": "object", "properties": {"name": {"type": "string", "minLength": 2}}, "required": ["name"]},
                {
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 2}, "enabled": {"type": "boolean"}},
                },
            ],
        },
        result={"type": "object", "properties": {}},
    )
    request = _model(scope, "WidgetArgsDTO")
    assert request(name="AB", enabled=False).to_payload() == {"name": "AB", "enabled": False}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request(name="A")


def test_tagged_rpc_nullable_object_variant_has_payload_method() -> None:
    scope = _widget_models(
        request={
            "type": "object",
            "properties": {
                "value": {"type": ["object", "null"], "properties": {"id": {"type": "string"}}, "required": ["id"]}
            },
        },
        result={"type": "object", "properties": {}},
    )
    assert _model(scope, "WidgetArgsValueObjectDTO")(id="x").to_payload() == {"id": "x"}  # type: ignore[attr-defined]


@pytest.mark.parametrize("root", ["WidgetArgs", "WidgetResult"])
@pytest.mark.parametrize(
    ("field_schema", "constraint"),
    [
        ({"$ref": "#/components/schemas/Text", "type": "string", "minLength": 3}, "minLength"),
        ({"$ref": "#/components/schemas/Text", "type": "string", "pattern": "^[A-Z]+$"}, "pattern"),
        ({"anyOf": [{"type": "string"}], "type": "string", "minLength": 3}, "minLength"),
        ({"anyOf": [{"type": "string"}], "type": "string", "pattern": "^[A-Z]+$"}, "pattern"),
        ({"oneOf": [{"type": "string"}, {"type": "null"}], "type": ["string", "null"], "minLength": 3}, "minLength"),
        ({"$ref": "#/components/schemas/Text", "enum": ["allowed"]}, "enum"),
        ({"anyOf": [{"type": "string"}, {"type": "integer"}], "type": "string"}, "type"),
    ],
)
def test_tagged_rpc_rejects_ignored_composition_siblings_with_pointer(
    root: str, field_schema: dict[str, object], constraint: str
) -> None:
    schemas: dict[str, object] = {
        "WidgetArgs": {"type": "object", "properties": {}},
        "WidgetResult": {"type": "object", "properties": {}},
        "Text": {"type": "string"},
    }
    schemas[root] = {"type": "object", "properties": {"value": field_schema}, "required": ["value"]}
    with pytest.raises(ValueError, match=rf"/schemas/{root}/properties/value/{constraint}"):
        _models(_contract(_spec({"/rpc/createWidget": {"post": _operation()}}, schemas=schemas)))


@pytest.mark.parametrize("root", ["WidgetArgs", "WidgetResult"])
@pytest.mark.parametrize(
    "branches",
    [
        [{"type": "string"}, {"type": "string"}],
        [{"type": "integer"}, {"type": "number"}],
        [{"type": ["integer", "null"]}, {"type": "number"}],
    ],
)
def test_tagged_rpc_overlapping_one_of_fails_with_pointer(root: str, branches: list[dict[str, object]]) -> None:
    schemas: dict[str, object] = {
        "WidgetArgs": {"type": "object", "properties": {}},
        "WidgetResult": {"type": "object", "properties": {}},
    }
    schemas[root] = {"type": "object", "properties": {"value": {"oneOf": branches}}}
    with pytest.raises(ValueError, match=rf"/schemas/{root}/properties/value/oneOf"):
        _models(_contract(_spec({"/rpc/createWidget": {"post": _operation()}}, schemas=schemas)))


def test_tagged_rpc_disjoint_one_of_validates_each_branch() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"value": {"oneOf": [{"type": "string", "minLength": 2}, {"type": "integer"}, {"type": "null"}]}},
        "required": ["value"],
    }
    scope = _widget_models(request=schema, result=schema)
    request = _model(scope, "WidgetArgsDTO")
    response = _model(scope, "WidgetResultReadDTO")
    for value in ("ok", 1, None):
        assert request(value=value).to_payload() == {"value": value}  # type: ignore[attr-defined]
        assert response(value=value).model_dump() == {"value": value}
    invalid_values: tuple[object, ...] = ("x", 1.5, False, [], {})
    for model in (request, response):
        for invalid in invalid_values:
            with pytest.raises(ValidationError):
                model(value=invalid)


@pytest.mark.parametrize("root", ["WidgetArgs", "WidgetResult"])
@pytest.mark.parametrize(
    "field_schema",
    [
        {"type": "string", "enum": [1]},
        {"type": "integer", "enum": [True]},
        {"type": ["string", "null"], "enum": [1, None]},
    ],
)
def test_tagged_rpc_rejects_enum_values_outside_declared_type_for_write_and_read(
    root: str, field_schema: dict[str, object]
) -> None:
    schemas: dict[str, object] = {
        "WidgetArgs": {"type": "object", "properties": {}},
        "WidgetResult": {"type": "object", "properties": {}},
    }
    schemas[root] = {"type": "object", "properties": {"value": field_schema}, "required": ["value"]}
    with pytest.raises(ValueError, match=rf"/schemas/{root}/properties/value/enum"):
        _models(_contract(_spec({"/rpc/createWidget": {"post": _operation()}}, schemas=schemas)))


@pytest.mark.parametrize(
    ("field_schema", "value"),
    [
        ({"type": "integer", "enum": [1.0]}, 1.0),
        ({"type": "number", "enum": [1, 1.5]}, 1),
    ],
)
def test_tagged_rpc_compatible_numeric_enums_round_trip_in_write_and_read(
    field_schema: dict[str, object], value: int | float
) -> None:
    schema: dict[str, object] = {"type": "object", "properties": {"value": field_schema}, "required": ["value"]}
    scope = _widget_models(request=schema, result=schema)
    assert _model(scope, "WidgetArgsDTO")(value=value).to_payload() == {"value": value}  # type: ignore[attr-defined]
    assert _model(scope, "WidgetResultReadDTO")(value=value).model_dump() == {"value": value}


def test_tagged_rpc_nullable_enum_constraints_fail_with_pointer() -> None:
    request: dict[str, object] = {
        "type": "object",
        "properties": {"value": {"type": ["string", "null"], "enum": ["AB", None], "minLength": 3}},
    }
    with pytest.raises(ValueError, match=r"/schemas/WidgetArgs/properties/value/minLength"):
        _contract(
            _spec(
                {"/rpc/createWidget": {"post": _operation()}},
                schemas={"WidgetArgs": request, "WidgetResult": {"type": "object", "properties": {}}},
            )
        )


def test_tagged_rpc_unconstrained_nullable_enum_remains_supported() -> None:
    request = _model(
        _widget_models(
            request={"type": "object", "properties": {"choice": {"type": ["string", "null"], "enum": ["a", None]}}},
            result={"type": "object", "properties": {}},
        ),
        "WidgetArgsDTO",
    )
    assert request(choice=None).to_payload() == {"choice": None}  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        request(choice="b")


def test_html_payload_policy_keeps_nested_references_to_roots_method_free() -> None:
    schemas: dict[str, JsonValue] = {
        "AWrapper": {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/BRoot"}}},
        "BRoot": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        "CRoot": {"$ref": "#/components/schemas/BRoot"},
    }
    source = codegen._PydanticSchemaEmitter(schemas, read=False, contract="HtmlPages", payload_methods="roots").emit(
        ("AWrapper", "CRoot")
    )
    scope = _load_models(source)
    assert _model(scope, "CRootDTO")(id="x").to_payload() == {"id": "x"}  # type: ignore[attr-defined]
    child_type = _model(scope, "AWrapperDTO").model_fields["child"].annotation
    assert isinstance(child_type, type)
    assert issubclass(child_type, BaseModel)
    assert not hasattr(child_type, "to_payload")
    assert _model(scope, "AWrapperDTO").model_validate({"child": {"id": "x"}}).model_dump() == {"child": {"id": "x"}}


def test_tagged_rpc_shared_result_uses_strict_wire_alias_for_read_and_mutation() -> None:
    request = {"$ref": "#/components/schemas/Request"}
    result = {"$ref": "#/components/schemas/SharedResult"}

    def operation(tag: str) -> dict[str, object]:
        return {
            "tags": [tag],
            "requestBody": {"required": True, "content": {"application/json": {"schema": request}}},
            "responses": {"200": {"content": {"application/json": {"schema": result}}}},
        }

    spec: dict[str, object] = {
        "paths": {
            "/rpc/getStrictWidget": {"post": operation("Strict")},
            "/rpc/createRelaxedWidget": {"post": operation("Relaxed")},
        },
        "components": {
            "schemas": {
                "Request": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                "SharedResult": {
                    "type": "object",
                    "properties": {"clusterId": {"type": "string"}},
                    "required": ["clusterId"],
                },
            }
        },
    }
    strict = codegen.build_rpc_namespace_contract_meta(
        spec, config={"tag": "Strict", "namespace": "strict", "alias_only_read": True}
    )
    relaxed = codegen.build_rpc_namespace_contract_meta(spec, config={"tag": "Relaxed", "namespace": "relaxed"})
    assert strict is not None
    assert relaxed is not None

    metadata: codegen.Metadata = {
        "installations": {},
        "rpc_namespaces": {"strict": strict, "relaxed": relaxed},
    }
    scope = _load_models(codegen._emit_rpc_namespace_dto(metadata))
    shared_result = _model(scope, "SharedResultReadDTO")
    assert shared_result.model_validate({"clusterId": "managed-1"}).model_dump()["cluster_id"] == "managed-1"
    with pytest.raises(ValidationError, match="clusterId"):
        shared_result.model_validate({"cluster_id": "managed-1"})
