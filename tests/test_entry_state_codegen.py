from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import cast

from pydantic import ValidationError
import pytest

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[1]
GET_ROUTE = "/rpc/getEntryState"
CREATE_ROUTE = "/rpc/createEntryState"


def _load_spec(name: str = "yacloud") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{name}.json").read_text()))


def _paths(spec: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], spec["paths"])


def _schemas(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], cast(dict[str, object], spec["components"])["schemas"])


def _properties(schema: dict[str, object]) -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], schema["properties"])


def _write_spec(tmp_path: Path, spec: dict[str, object], name: str = "yacloud") -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec))
    return path


@pytest.fixture(scope="module")
def state_dto_module(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    path = tmp_path_factory.mktemp("entry-state-dto") / "dto.py"
    path.write_text(
        codegen.emit_dto(
            codegen.build_metadata({name: ROOT / "spec" / f"{name}.json" for name in ("enterprise", "yacloud")})
        )
    )
    module_name = "_entry_state_codegen_test_dto"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["enterprise", "yacloud"])
def test_entry_state_contract_is_built_for_public_installations(name: str) -> None:
    contract = codegen.build_entry_state_contract_meta(_load_spec(name))

    assert contract is not None
    assert contract["roots"] == [
        "GetStateArgs",
        "GetStateResult",
        "CreateStateArgs",
        "CreateStateResult",
        "DashboardStateMeta",
        "DashboardStateWidget",
    ]
    assert sorted(contract["schemas"]) == sorted(
        [*contract["roots"], "DashStringDefaultValueV2", "DashStringDefaultsV2"]
    )
    result = cast(dict[str, object], contract["schemas"]["GetStateResult"])
    assert _properties(result)["data"] == {"additionalProperties": True, "type": ["null", "object"]}
    create = cast(dict[str, object], contract["schemas"]["CreateStateArgs"])
    assert _properties(create)["data"] == {"additionalProperties": True, "type": "object"}
    widget = cast(dict[str, object], contract["schemas"]["DashboardStateWidget"])
    assert set(_properties(widget)) == {"params", "state"}
    assert "tabId" in _properties(_properties(widget)["state"])


@pytest.mark.parametrize("drift", ["no-widget-schema", "meta-optional", "extra-property"])
def test_entry_state_contract_rejects_dashboard_state_drift(drift: str) -> None:
    spec = _load_spec()
    schema = _schemas(spec)["DashboardState"]
    if drift == "no-widget-schema":
        del schema["additionalProperties"]
    elif drift == "meta-optional":
        schema["required"] = []
    else:
        _properties(schema)["extra"] = {"type": "string"}

    with pytest.raises(ValueError, match="DashboardState must be an object"):
        codegen.build_entry_state_contract_meta(spec)


def test_entry_state_contract_matches_between_installations() -> None:
    metadata = codegen.build_metadata({name: ROOT / "spec" / f"{name}.json" for name in ("enterprise", "yacloud")})

    assert metadata["entry_state"] == codegen.build_entry_state_contract_meta(_load_spec("enterprise"))


def test_entry_state_contract_is_absent_without_routes() -> None:
    spec = _load_spec()
    del _paths(spec)[GET_ROUTE]
    del _paths(spec)[CREATE_ROUTE]

    assert codegen.build_entry_state_contract_meta(spec) is None


@pytest.mark.parametrize("route", [GET_ROUTE, CREATE_ROUTE])
def test_entry_state_contract_requires_both_routes(route: str) -> None:
    spec = _load_spec()
    del _paths(spec)[route]

    with pytest.raises(ValueError, match="entry state routes must be published together"):
        codegen.build_entry_state_contract_meta(spec)


@pytest.mark.parametrize("route", [GET_ROUTE, CREATE_ROUTE])
def test_entry_state_contract_rejects_other_roots(route: str) -> None:
    spec = _load_spec()
    post = cast(dict[str, object], cast(dict[str, object], _paths(spec)[route])["post"])
    content = cast(dict[str, dict[str, object]], cast(dict[str, object], post["requestBody"])["content"])
    content["application/json"]["schema"] = {"$ref": "#/components/schemas/GetRevisionsArgs"}

    with pytest.raises(ValueError, match=f"{route} must use"):
        codegen.build_entry_state_contract_meta(spec)


def test_entry_state_contract_requires_data_property() -> None:
    spec = _load_spec()
    del _properties(_schemas(spec)["GetStateResult"])["data"]

    with pytest.raises(ValueError, match="must define a 'data' property"):
        codegen.build_entry_state_contract_meta(spec)


def test_entry_state_codegen_rejects_installation_availability_drift(tmp_path: Path) -> None:
    enterprise = _load_spec("enterprise")
    del _paths(enterprise)[GET_ROUTE]
    del _paths(enterprise)[CREATE_ROUTE]
    installations = {
        "enterprise": _write_spec(tmp_path, enterprise, "enterprise"),
        "yacloud": _write_spec(tmp_path, _load_spec(), "yacloud"),
    }

    with pytest.raises(ValueError, match="entry state availability differs"):
        codegen.build_metadata(installations)


def test_entry_state_codegen_rejects_unsupported_constraints() -> None:
    spec = _load_spec()
    _properties(_schemas(spec)["GetStateArgs"])["hash"]["pattern"] = "^[a-z0-9]+$"

    with pytest.raises(ValueError, match=r"Unsupported behavior-bearing entryState schema feature.*pattern"):
        codegen.build_entry_state_contract_meta(spec)


@pytest.mark.parametrize(
    "data", [None, {}, {"__meta__": {"version": 2, "queue": []}, "item": {"params": {"a": ["1"]}}}]
)
def test_get_state_result_dto_accepts_null_and_arbitrary_objects(state_dto_module: ModuleType, data: object) -> None:
    result = state_dto_module.GetStateResultDTO.model_validate(
        {"entryId": "abc", "hash": "h1", "data": data, "createdAt": "2026-01-01T00:00:00.000Z", "unknown": 1}
    )

    assert result.data == data
    assert result.created_at == "2026-01-01T00:00:00.000Z"


@pytest.mark.parametrize("data", [{}, {"any": {"nested": [1, "two", None]}}])
def test_create_state_args_dto_accepts_arbitrary_objects(state_dto_module: ModuleType, data: object) -> None:
    args = state_dto_module.CreateStateArgsDTO.model_validate({"entryId": "abc", "data": data})

    assert args.to_payload() == {"entryId": "abc", "data": data}


@pytest.mark.parametrize(
    "payload",
    [
        {"entryId": "abc", "data": None},
        {"entryId": "abc", "data": []},
        {"entryId": "abc"},
        {"entryId": "abc", "data": {}, "unknown": True},
    ],
)
def test_create_state_args_dto_rejects_invalid_payloads(
    state_dto_module: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        state_dto_module.CreateStateArgsDTO.model_validate(payload)


@pytest.mark.parametrize("payload", [{"entryId": "abc", "hash": ""}, {"entryId": "abc"}])
def test_get_state_args_dto_rejects_invalid_payloads(state_dto_module: ModuleType, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        state_dto_module.GetStateArgsDTO.model_validate(payload)


@pytest.mark.parametrize("payload", [{}, {"hash": ""}, {"hash": None}])
def test_create_state_result_dto_requires_hash(state_dto_module: ModuleType, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        state_dto_module.CreateStateResultDTO.model_validate(payload)


def test_dashboard_state_dtos_round_trip_the_spec_example(state_dto_module: ModuleType) -> None:
    example = cast(
        dict[str, dict[str, object]],
        cast(list[object], _schemas(_load_spec())["DashboardState"]["examples"])[0],
    )

    meta = state_dto_module.DashboardStateMetaDTO.model_validate(example["__meta__"])
    widgets = {
        key: state_dto_module.DashboardStateWidgetDTO.model_validate(value)
        for key, value in example.items()
        if key != "__meta__"
    }

    assert meta.queue[2].tab_id == "chart-tab-id"
    assert widgets["chart-widget-id"].state.tab_id == "chart-tab-id"
    assert {"__meta__": meta.to_payload(), **{key: _.to_payload() for key, _ in widgets.items()}} == example


def test_dashboard_state_widget_dto_keeps_unknown_state_fields(state_dto_module: ModuleType) -> None:
    widget = {"params": {}, "state": {"tabId": "t1", "scroll": 10}, "future": True}

    assert state_dto_module.DashboardStateWidgetDTO.model_validate(widget).to_payload() == widget


@pytest.mark.parametrize(
    "meta",
    [{"queue": []}, {"version": 1, "queue": []}, {"version": 2}, {"version": 2, "queue": [{"tabId": "t"}]}],
)
def test_dashboard_state_meta_dto_rejects_invalid_meta(state_dto_module: ModuleType, meta: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        state_dto_module.DashboardStateMetaDTO.model_validate(meta)


@pytest.mark.parametrize(
    ("schema_name", "data_schema"),
    [
        ("GetStateResult", {"type": ["null", "string"], "anyOf": [{"type": "string"}, {"type": "null"}]}),
        ("CreateStateArgs", {"type": "array", "items": {"type": "string"}}),
        (
            "CreateStateArgs",
            {
                "type": ["null", "object"],
                "anyOf": [
                    {"$ref": "#/components/schemas/DashboardState"},
                    {"type": "object", "additionalProperties": True},
                    {"type": "null"},
                ],
            },
        ),
    ],
    ids=["nullable-string-result", "array-request", "nullable-request"],
)
def test_entry_state_contract_rejects_data_envelope_drift(schema_name: str, data_schema: dict[str, object]) -> None:
    spec = _load_spec()
    _properties(_schemas(spec)[schema_name])["data"] = data_schema

    with pytest.raises(ValueError, match=f"entryState schema '{schema_name}' 'data' must be"):
        codegen.build_entry_state_contract_meta(spec)


@pytest.mark.parametrize(
    ("schema_name", "drop"),
    [
        ("CreateStateArgs", "object"),
        ("GetStateResult", "object"),
        ("GetStateResult", "null"),
    ],
    ids=["create-without-any-object", "get-without-any-object", "get-without-null"],
)
def test_entry_state_contract_rejects_removed_data_alternatives(schema_name: str, drop: str) -> None:
    spec = _load_spec()
    data = _properties(_schemas(spec)[schema_name])["data"]
    branches = cast(list[dict[str, object]], data["anyOf"])
    data["anyOf"] = [_ for _ in branches if _.get("type") != drop]

    with pytest.raises(ValueError, match=f"entryState schema '{schema_name}' 'data' must be"):
        codegen.build_entry_state_contract_meta(spec)
