from __future__ import annotations

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import cast

from pydantic import TypeAdapter, ValidationError
import pytest
from typing_extensions import TypeForm

from datalens_sdk import codegen
from datalens_sdk._generated import dto

ROOT = Path(__file__).resolve().parents[1]
ROUTE = "/rpc/getChartData"
VARIANTS = {
    "wizard": "GetWizardChartDataResult",
    "ql": "GetQLChartDataResult",
    "editor": "GetEditorChartDataResult",
}


def _spec(name: str = "yacloud") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _schemas(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], cast(dict[str, object], spec["components"])["schemas"])


def _node(value: object, *keys: str) -> dict[str, object]:
    for key in keys:
        assert isinstance(value, dict)
        value = value[key]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _contract(spec: dict[str, object]) -> codegen.ChartDataContractMeta:
    contract = codegen.build_chart_data_contract_meta(spec)
    assert contract is not None
    return contract


def _write_spec(tmp_path: Path, spec: dict[str, object], name: str) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


def _models(spec: dict[str, object], tmp_path: Path) -> ModuleType:
    metadata: codegen.Metadata = {"installations": {}, "chart_data": _contract(spec)}
    path = tmp_path / "dto.py"
    path.write_text(codegen.emit_dto(metadata))
    name = f"_chart_data_codegen_{tmp_path.name.replace('-', '_')}"
    module_spec = importlib.util.spec_from_file_location(name, path)
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _response(tag: str) -> dict[str, object]:
    column = {"name": "value"} if tag == "editor" else {"name": "value", "type": "future_type"}
    return {"chartType": tag, "results": [{"schema": [column], "rows": [["01"], [], [None, True]]}]}


def test_chart_data_contract_matches_public_installations_and_retains_source_types() -> None:
    enterprise = _contract(_spec("enterprise"))
    yacloud = _contract(_spec())

    assert enterprise == yacloud
    assert enterprise["roots"] == ["GetChartDataArgs", "GetChartDataResult"]
    assert set(enterprise["schemas"]) == {*enterprise["roots"], *VARIANTS.values()}
    wizard_type = _node(
        enterprise["schemas"],
        "GetWizardChartDataResult",
        "properties",
        "results",
        "items",
        "properties",
        "schema",
        "items",
        "properties",
        "type",
    )
    assert "integer" in cast(list[str], wizard_type["enum"])
    assert set(_node(enterprise["schemas"], "GetChartDataArgs", "properties")) == {"chartId", "params"}


def test_chart_data_contract_does_not_depend_on_screenshots_or_other_data_routes() -> None:
    spec = _spec()
    expected = _contract(spec)
    paths = _node(spec, "paths")
    for path in ("/rpc/getChartScreenshot", "/rpc/getDashScreenshot"):
        del paths[path]
    paths["/rpc/getFutureData"] = {"post": {"tags": ["Data"]}}
    assert _contract(spec) == expected


def test_chart_data_missing_route_is_optional_but_partial_installation_availability_fails(tmp_path: Path) -> None:
    spec = _spec()
    del _node(spec, "paths")[ROUTE]
    assert codegen.build_chart_data_contract_meta(spec) is None
    with pytest.raises(ValueError, match="getChartData availability differs"):
        codegen.build_metadata(
            {
                "enterprise": _write_spec(tmp_path, _spec("enterprise"), "enterprise"),
                "yacloud": _write_spec(tmp_path, spec, "yacloud"),
            }
        )


@pytest.mark.parametrize("is_request", [True, False])
def test_chart_data_rejects_wrong_route_schema_reference(is_request: bool) -> None:
    spec = _spec()
    keys = (
        ("requestBody", "content", "application/json", "schema")
        if is_request
        else (
            "responses",
            "200",
            "content",
            "application/json",
            "schema",
        )
    )
    _node(spec, "paths", ROUTE, "post", *keys)["$ref"] = "#/components/schemas/GetRevisionsArgs"
    with pytest.raises(ValueError, match="getChartData schema references differ"):
        _contract(spec)


@pytest.mark.parametrize("name", ["GetChartDataArgs", "GetChartDataResult", *VARIANTS.values()])
def test_chart_data_rejects_missing_components(name: str) -> None:
    spec = _spec()
    del _schemas(spec)[name]
    with pytest.raises(ValueError, match="getChartData schema graph references missing component"):
        _contract(spec)


@pytest.mark.parametrize(
    ("reference", "component", "message"),
    [
        ("#/components/schemas/MissingChartColumn", None, "missing component"),
        ("https://example.test/schemas.json#ChartColumn", None, "local schema"),
        ("#/components/schemas/ChartColumn", {"$ref": "#/components/schemas/ChartColumn"}, "Recursive"),
    ],
)
def test_chart_data_rejects_invalid_schema_closures(
    reference: str,
    component: dict[str, object] | None,
    message: str,
) -> None:
    spec = _spec()
    column_array = _node(
        _schemas(spec), "GetWizardChartDataResult", "properties", "results", "items", "properties", "schema"
    )
    column_array["items"] = {"$ref": reference}
    if component is not None:
        _schemas(spec)["ChartColumn"] = component
    with pytest.raises(ValueError, match=message):
        _contract(spec)


@pytest.mark.parametrize("mutation", ["property", "mapping", "branch", "tag", "optional_tag"])
def test_chart_data_rejects_discriminator_drift(mutation: str) -> None:
    spec = _spec()
    result = _schemas(spec)["GetChartDataResult"]
    if mutation == "property":
        _node(result, "discriminator")["propertyName"] = "kind"
    elif mutation == "mapping":
        _node(result, "discriminator", "mapping")["wizard"] = "#/components/schemas/GetQLChartDataResult"
    elif mutation == "branch":
        cast(list[object], result["oneOf"]).pop()
    elif mutation == "tag":
        _node(_schemas(spec), "GetWizardChartDataResult", "properties", "chartType")["enum"] = ["other"]
    else:
        cast(list[str], _schemas(spec)["GetWizardChartDataResult"]["required"]).remove("chartType")
    with pytest.raises(ValueError, match="getChartData"):
        _contract(spec)


@pytest.mark.parametrize("drift", ["request", "wizard_type", "annotation"])
def test_chart_data_compares_original_contract_before_read_normalization(tmp_path: Path, drift: str) -> None:
    changed = _spec("enterprise")
    if drift == "request":
        _node(_schemas(changed), "GetChartDataArgs", "properties")["future"] = {"type": "string"}
    elif drift == "wizard_type":
        wizard_type = _node(
            _schemas(changed),
            "GetWizardChartDataResult",
            "properties",
            "results",
            "items",
            "properties",
            "schema",
            "items",
            "properties",
            "type",
        )
        cast(list[str], wizard_type["enum"]).append("new_type")
    else:
        _schemas(changed)["GetChartDataArgs"]["description"] = "Changed source contract"
    with pytest.raises(ValueError, match="getChartData schemas differ"):
        codegen.build_metadata(
            {
                "enterprise": _write_spec(tmp_path, changed, "enterprise"),
                "yacloud": _write_spec(tmp_path, _spec(), "yacloud"),
            }
        )


def test_chart_data_emission_does_not_mutate_source_contract() -> None:
    contract = _contract(_spec())
    before = deepcopy(contract)
    codegen.emit_dto({"installations": {}, "chart_data": contract})
    assert contract == before


def test_chart_data_resolves_local_wizard_column_ref_and_widens_only_read_type(tmp_path: Path) -> None:
    spec = _spec()
    columns = _node(
        _schemas(spec), "GetWizardChartDataResult", "properties", "results", "items", "properties", "schema"
    )
    _schemas(spec)["ChartColumn"] = _node(columns, "items")
    columns["items"] = {"$ref": "#/components/schemas/ChartColumn"}
    models = _models(spec, tmp_path)
    adapter: TypeAdapter[object] = TypeAdapter(cast(TypeForm[object], models.GetChartDataResultDTO))
    result = adapter.validate_python(_response("wizard"))
    assert result.chart_type == "wizard"  # type: ignore[attr-defined]
    assert result.results[0].columns[0].type == "future_type"  # type: ignore[attr-defined]


@pytest.mark.parametrize("feature", ["pattern", "maxLength", "uniqueItems", "x-datalens-validation"])
def test_chart_data_does_not_silently_ignore_unknown_behavior_features(feature: str) -> None:
    spec = _spec()
    _node(_schemas(spec), "GetChartDataArgs", "properties", "chartId")[feature] = "unsupported"
    with pytest.raises(ValueError, match="Unsupported behavior-bearing getChartData schema feature"):
        _contract(spec)


@pytest.mark.parametrize(
    "params", [None, {}, {"": "", "_page": [], "revId": ["r1", "r2"], "город": "Москва & область"}]
)
def test_chart_data_request_wire_payload(params: dict[str, object] | None) -> None:
    args: dict[str, object] = {"chart_id": "chart-1"}
    expected: dict[str, object] = {"chartId": "chart-1"}
    if params is not None:
        args["params"] = params
        expected["params"] = params
    request = dto.GetChartDataArgsDTO.model_validate(args)
    assert request.to_payload() == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"chartId": ""},
        {"chartId": 1},
        {"revId": "r"},
        {"limit": 500},
        {"params": None},
        {"params": {"x": 1}},
        {"params": {"x": True}},
        {"params": {"x": [1]}},
        {"params": {1: "x"}},
    ],
)
def test_chart_data_request_rejects_invalid_values_and_extras(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        dto.GetChartDataArgsDTO.model_validate({"chartId": "chart-1", **overrides})


@pytest.mark.parametrize("tag", list(VARIANTS))
def test_chart_data_read_union_is_typed_tolerant_and_preserves_rows(tag: str) -> None:
    payload = _response(tag)
    payload["future"] = "ignored"
    table = cast(list[dict[str, object]], payload["results"])[0]
    table["future"] = True
    cast(list[dict[str, object]], table["schema"])[0]["future"] = 1
    adapter: TypeAdapter[object] = TypeAdapter(dto.GetChartDataResultDTO)
    result = adapter.validate_python(payload)
    assert result.chart_type == tag  # type: ignore[attr-defined]
    assert result.results[0].columns[0].name == "value"  # type: ignore[attr-defined]
    assert result.results[0].rows == [["01"], [], [None, True]]  # type: ignore[attr-defined]
    assert "future" not in result.model_dump()  # type: ignore[attr-defined]
    assert "future" not in result.results[0].model_dump()  # type: ignore[attr-defined]
    assert "future" not in result.results[0].columns[0].model_dump()  # type: ignore[attr-defined]
    assert adapter.validate_python({"chartType": tag, "results": []}).results == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "payload",
    [
        {"results": []},
        {"chartType": "future", "results": []},
        {"chartType": "wizard", "results": [{"schema": [{"name": "a", "type": 1}], "rows": []}]},
        {"chartType": "editor", "results": [{"schema": [], "rows": ["not a row"]}]},
    ],
)
def test_chart_data_read_union_rejects_missing_tags_and_invalid_shapes(payload: dict[str, object]) -> None:
    adapter: TypeAdapter[object] = TypeAdapter(dto.GetChartDataResultDTO)
    with pytest.raises(ValidationError):
        adapter.validate_python(payload)


def test_chart_data_uses_shared_schema_emitter_and_exact_nested_aliases() -> None:
    source = ast.parse((ROOT / "src" / "datalens_sdk" / "codegen.py").read_text())
    assert not [
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and "ChartData" in node.name and "Emitter" in node.name
    ]
    for tag, variant in VARIANTS.items():
        model = getattr(dto, f"{variant}DTO")
        table = model.model_validate(_response(tag)).results[0]
        assert table.model_fields["columns"].alias == "schema"
        assert "schema" in table.model_dump(by_alias=True)


@pytest.mark.parametrize("location", ["request", "response", "column", "params"])
def test_chart_data_rejects_composition_sibling_constraints(location: str) -> None:
    spec = _spec()
    if location in {"request", "response"}:
        keys = (
            ("requestBody", "content", "application/json", "schema")
            if location == "request"
            else (
                "responses",
                "200",
                "content",
                "application/json",
                "schema",
            )
        )
        node = _node(spec, "paths", ROUTE, "post", *keys)
        node["type"] = "object"
    elif location == "column":
        columns = _node(
            _schemas(spec), "GetWizardChartDataResult", "properties", "results", "items", "properties", "schema"
        )
        _schemas(spec)["ChartColumn"] = _node(columns, "items")
        columns["items"] = {"$ref": "#/components/schemas/ChartColumn", "type": "object"}
    else:
        _node(_schemas(spec), "GetChartDataArgs", "properties", "params", "additionalProperties")["minLength"] = 1
    with pytest.raises(ValueError, match="sibling constraint"):
        _contract(spec)
