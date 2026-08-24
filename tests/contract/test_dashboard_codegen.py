from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import cast

from pydantic import ValidationError
import pytest

from datalens_sdk.codegen import Metadata, build_metadata, emit_dto, write_outputs

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


def _dashboard_schemas() -> dict[str, object]:
    return {
        "CreateDashboardV2Args": {
            "properties": {
                "entry": {
                    "allOf": [
                        {
                            "properties": {
                                "annotation": _ref("EntryAnnotationArg"),
                                "data": _ref("DashDataV2"),
                                "meta": _ref("DashMetaV2"),
                            },
                            "required": ["data", "meta"],
                            "type": "object",
                        },
                        _ref("EntryLocationIdentifiers"),
                    ]
                }
            },
            "required": ["entry"],
            "type": "object",
        },
        "UpdateDashboardV2Args": {
            "additionalProperties": False,
            "properties": {
                "entry": {
                    "additionalProperties": False,
                    "properties": {
                        "annotation": _ref("EntryAnnotationArg"),
                        "data": _ref("DashDataV2"),
                        "entryId": {"type": "string"},
                        "meta": _ref("DashMetaV2"),
                        "revId": {"type": "string"},
                    },
                    "required": ["entryId", "data", "meta"],
                    "type": "object",
                },
                "lockToken": {"type": "string"},
                "mode": _ref("EntryUpdateMode"),
            },
            "required": ["entry", "mode"],
            "type": "object",
        },
        "GetDashboardV2Args": {
            "properties": {
                "branch": _ref("EntryBranch"),
                "dashboardId": {"type": "string"},
                "includeFavorite": {"type": "boolean"},
                "includeLinks": {"type": "boolean"},
                "includePermissions": {"type": "boolean"},
                "revId": {"type": "string"},
                "workbookId": {"type": "string"},
            },
            "required": ["dashboardId"],
            "type": "object",
        },
        "GetDashboardV2Result": {
            "properties": {
                "entry": _ref("DashboardV2"),
                "isFavorite": {"type": "boolean"},
                "permissions": _ref("EntryPermissions"),
            },
            "required": ["entry"],
            "type": "object",
        },
        "DeleteDashboardArgs": {
            "additionalProperties": False,
            "properties": {
                "dashboardId": {"type": "string"},
                "lockToken": {"type": "string"},
            },
            "required": ["dashboardId"],
            "type": "object",
        },
        "EntryAnnotationArg": {
            "properties": {"description": {"type": "string"}},
            "type": "object",
        },
        "EntryLocationIdentifiers": {
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "workbookId": {"type": "string"},
            },
            "type": "object",
        },
        "EntryUpdateMode": {"enum": ["save", "publish"], "type": "string"},
        "EntryBranch": {"enum": ["saved", "published"], "type": "string"},
        "EntryPermissions": {
            "additionalProperties": {"type": "boolean"},
            "type": "object",
        },
        "DashMetaV2": {
            "additionalProperties": {
                "anyOf": [{"type": "string"}, {"type": "boolean"}],
            },
            "type": ["object", "null"],
        },
        "DashConnectionV2": {
            "properties": {
                "from": {"minLength": 1, "type": "string"},
                "kind": {"enum": ["ignore"], "type": "string"},
                "to": {"minLength": 1, "type": "string"},
            },
            "required": ["from", "to", "kind"],
            "type": "object",
        },
        "DashControlElementV2": {
            "oneOf": [
                {
                    "properties": {"elementType": {"enum": ["select"], "type": "string"}},
                    "required": ["elementType"],
                    "type": "object",
                },
                {
                    "properties": {"elementType": {"enum": ["input"], "type": "string"}},
                    "required": ["elementType"],
                    "type": "object",
                },
            ]
        },
        "DashControlSourceManualV2": {
            "allOf": [
                _ref("DashControlElementV2"),
                {
                    "properties": {"fieldName": {"minLength": 1, "type": "string"}},
                    "required": ["fieldName"],
                    "type": "object",
                },
            ]
        },
        "DashControlV2": {
            "oneOf": [
                {
                    "properties": {
                        "source": _ref("DashControlSourceManualV2"),
                        "sourceType": {"enum": ["manual"], "type": "string"},
                        "title": {"minLength": 1, "type": "string"},
                    },
                    "required": ["title", "sourceType", "source"],
                    "type": "object",
                },
                {
                    "properties": {
                        "source": {
                            "properties": {
                                "datasetId": {"minLength": 1, "type": "string"},
                            },
                            "required": ["datasetId"],
                            "type": "object",
                        },
                        "sourceType": {"enum": ["dataset"], "type": "string"},
                        "title": {"minLength": 1, "type": "string"},
                    },
                    "required": ["title", "sourceType", "source"],
                    "type": "object",
                },
            ]
        },
        "DashTabControlItemV2": {
            "additionalProperties": False,
            "properties": {
                "data": _ref("DashControlV2"),
                "defaults": {"type": "object"},
                "id": {"minLength": 1, "type": "string"},
                "namespace": {"minLength": 1, "type": "string"},
                "type": {"enum": ["control"], "type": "string"},
            },
            "required": ["id", "namespace", "type", "data", "defaults"],
            "type": "object",
        },
        "DashTabGroupControlItemV2": {
            "additionalProperties": False,
            "properties": {
                "group": {"minLength": 1, "type": "string"},
                "id": {"minLength": 1, "type": "string"},
                "namespace": {"minLength": 1, "type": "string"},
                "type": {"enum": ["group_control"], "type": "string"},
            },
            "required": ["id", "namespace", "type", "group"],
            "type": "object",
        },
        "DashGlobalItemV2": {
            "discriminator": {
                "mapping": {
                    "control": "#/components/schemas/DashTabControlItemV2",
                    "group_control": "#/components/schemas/DashTabGroupControlItemV2",
                },
                "propertyName": "type",
            },
            "oneOf": [_ref("DashTabControlItemV2"), _ref("DashTabGroupControlItemV2")],
        },
        "DashTabItemV2": {
            "oneOf": [
                {
                    "properties": {
                        "data": {
                            "properties": {
                                "hideTitle": {"type": "boolean"},
                                "tabs": {
                                    "items": {
                                        "properties": {
                                            "chartId": {"minLength": 1, "type": "string"},
                                            "id": {"minLength": 1, "type": "string"},
                                            "params": {"type": "object"},
                                            "title": {"minLength": 1, "type": "string"},
                                        },
                                        "required": ["id", "title", "chartId", "params"],
                                        "type": "object",
                                    },
                                    "type": "array",
                                },
                            },
                            "required": ["hideTitle", "tabs"],
                            "type": "object",
                        },
                        "id": {"minLength": 1, "type": "string"},
                        "namespace": {"minLength": 1, "type": "string"},
                        "type": {"enum": ["widget"], "type": "string"},
                    },
                    "required": ["id", "namespace", "type", "data"],
                    "type": "object",
                },
                _ref("DashTabControlItemV2"),
                _ref("DashTabGroupControlItemV2"),
            ]
        },
        "DashLayoutItemV2": {
            "properties": {
                "h": {"type": "number"},
                "i": {"minLength": 1, "type": "string"},
                "w": {"type": "number"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["i", "h", "w", "x", "y"],
            "type": "object",
        },
        "DashTabV2": {
            "additionalProperties": False,
            "properties": {
                "aliases": {
                    "additionalProperties": False,
                    "properties": {
                        "default": {
                            "items": {
                                "items": {"minLength": 1, "type": "string"},
                                "minItems": 2,
                                "type": "array",
                            },
                            "type": "array",
                        }
                    },
                    "type": "object",
                },
                "connections": {"items": _ref("DashConnectionV2"), "type": "array"},
                "globalItems": {"items": _ref("DashGlobalItemV2"), "type": "array"},
                "id": {"minLength": 1, "type": "string"},
                "items": {"items": _ref("DashTabItemV2"), "type": "array"},
                "layout": {"items": _ref("DashLayoutItemV2"), "type": "array"},
                "title": {"minLength": 1, "type": "string"},
            },
            "required": ["id", "title", "items", "layout", "connections", "aliases"],
            "type": "object",
        },
        "DashDataV2": {
            "properties": {
                "counter": {"minimum": 1, "type": "integer"},
                "salt": {"minLength": 1, "type": "string"},
                "settings": {
                    "properties": {
                        "autoupdateInterval": {
                            "anyOf": [{"minimum": 30, "type": "number"}, {"type": "null"}],
                        },
                        "dependentSelectors": {"type": "boolean"},
                        "expandTOC": {"type": "boolean"},
                        "margins": {
                            "prefixItems": [{"type": "number"}, {"type": "number"}],
                            "type": "array",
                        },
                        "maxConcurrentRequests": {
                            "anyOf": [{"minimum": 1, "type": "number"}, {"type": "null"}],
                        },
                        "silentLoading": {"type": "boolean"},
                    },
                    "required": [
                        "autoupdateInterval",
                        "maxConcurrentRequests",
                        "silentLoading",
                        "dependentSelectors",
                        "expandTOC",
                    ],
                    "type": "object",
                },
                "tabs": {"items": _ref("DashTabV2"), "type": "array"},
            },
            "required": ["counter", "salt", "tabs", "settings"],
            "type": "object",
        },
        "DashboardV2": {
            "properties": {
                "data": _ref("DashDataV2"),
                "entryId": {"type": "string"},
                "key": {"type": "string"},
                "meta": _ref("DashMetaV2"),
                "name": {"type": "string"},
                "publishedId": {"type": "string"},
                "revId": {"type": "string"},
                "savedId": {"type": "string"},
                "workbookId": {"type": "string"},
            },
            "required": ["entryId", "data", "meta"],
            "type": "object",
        },
    }


def _build_dashboard_metadata(tmp_path: Path) -> Metadata:
    installation = cast(
        dict[str, object],
        json.loads((ROOT / "spec" / "enterprise.json").read_text(encoding="utf-8")),
    )
    paths = cast(dict[str, object], installation["paths"])
    paths.update(
        {
            "/rpc/createDashboard": _route("CreateDashboardV2Args", None),
            "/rpc/deleteDashboard": _route("DeleteDashboardArgs", None),
            "/rpc/getDashboard": _route("GetDashboardV2Args", "GetDashboardV2Result"),
            "/rpc/updateDashboard": _route("UpdateDashboardV2Args", None),
        }
    )
    components = cast(dict[str, object], installation["components"])
    schemas = cast(dict[str, object], components["schemas"])
    schemas.update(_dashboard_schemas())
    spec_path = tmp_path / "installation.json"
    spec_path.write_text(json.dumps(installation), encoding="utf-8")
    return build_metadata({"enterprise": spec_path})


@pytest.fixture
def dashboard_dto_module(tmp_path: Path) -> ModuleType:
    module_path = tmp_path / "synthetic_dashboard_dto.py"
    module_path.write_text(emit_dto(_build_dashboard_metadata(tmp_path)), encoding="utf-8")
    module_name = f"synthetic_dashboard_dto_{tmp_path.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _selector_item() -> dict[str, object]:
    return {
        "id": "control-1",
        "namespace": "default",
        "type": "control",
        "data": {
            "title": "Country",
            "sourceType": "manual",
            "source": {"elementType": "select", "fieldName": "country"},
        },
        "defaults": {},
    }


def _dashboard_data() -> dict[str, object]:
    selector = _selector_item()
    return {
        "counter": 1,
        "salt": "s",
        "settings": {
            "autoupdateInterval": None,
            "maxConcurrentRequests": None,
            "silentLoading": False,
            "dependentSelectors": False,
            "expandTOC": False,
            "margins": [8, 12],
        },
        "tabs": [
            {
                "id": "tab-1",
                "title": "Main",
                "items": [
                    {
                        "id": "widget-1",
                        "namespace": "default",
                        "type": "widget",
                        "data": {
                            "hideTitle": False,
                            "tabs": [
                                {
                                    "id": "member-1",
                                    "title": "Chart",
                                    "chartId": "chart-1",
                                    "params": {},
                                }
                            ],
                        },
                    },
                    selector,
                ],
                "globalItems": [copy.deepcopy(selector)],
                "layout": [
                    {"i": "widget-1", "h": 4, "w": 6, "x": 0, "y": 0},
                    {"i": "control-1", "h": 2, "w": 6, "x": 6, "y": 0},
                ],
                "connections": [],
                "aliases": {"default": [["country", "region"]]},
            }
        ],
    }


def _create_kwargs() -> dict[str, object]:
    return {"data": _dashboard_data(), "meta": None, "name": "Sales"}


def test_dashboard_v2_roots_carriers_and_stable_facades_are_emitted(
    dashboard_dto_module: ModuleType,
) -> None:
    expected = {
        "CreateDashboardV2ArgsDTO",
        "UpdateDashboardV2ArgsDTO",
        "GetDashboardV2ArgsDTO",
        "GetDashboardV2ResultReadDTO",
        "DeleteDashboardArgsDTO",
        "DashDataV2DTO",
        "DashConnectionV2DTO",
        "DashTabV2DTO",
        "DashTabItemV2DTO",
        "DashGlobalItemV2DTO",
        "DashControlV2DTO",
        "DashLayoutItemV2DTO",
        "DashboardCreateDTO",
        "DashboardUpdateDTO",
        "DashboardGetArgsDTO",
        "DashboardDeleteArgsDTO",
        "DashboardReadDTO",
    }

    assert expected <= set(vars(dashboard_dto_module))


def test_dashboard_v2_aliases_and_required_optional_fields_match_schema(
    dashboard_dto_module: ModuleType,
) -> None:
    get_args = dashboard_dto_module.GetDashboardV2ArgsDTO.model_validate({"dashboardId": "dash-1"})
    assert get_args.dashboard_id == "dash-1"
    assert get_args.model_dump(mode="json", by_alias=True, exclude_none=True) == {"dashboardId": "dash-1"}

    with pytest.raises(ValidationError):
        dashboard_dto_module.GetDashboardV2ArgsDTO.model_validate({})

    entry = {"name": "Sales", "data": _dashboard_data(), "meta": None}
    create = dashboard_dto_module.CreateDashboardV2ArgsDTO.model_validate({"entry": entry})
    assert create.entry.workbook_id is None
    assert create.model_dump(mode="json", by_alias=True, exclude_unset=True) == {"entry": entry}

    connection = dashboard_dto_module.DashConnectionV2DTO(from_="control-1", to="member-1", kind="ignore")
    assert connection.model_dump(mode="json", by_alias=True) == {
        "from": "control-1",
        "to": "member-1",
        "kind": "ignore",
    }

    missing_meta = copy.deepcopy(entry)
    del missing_meta["meta"]
    with pytest.raises(ValidationError):
        dashboard_dto_module.CreateDashboardV2ArgsDTO.model_validate({"entry": missing_meta})


def test_dashboard_create_facade_serializes_representative_v2_wire(
    dashboard_dto_module: ModuleType,
) -> None:
    kwargs = _create_kwargs()

    dto = dashboard_dto_module.DashboardCreateDTO(**kwargs)

    assert dto.to_payload() == {"entry": {"name": "Sales", "data": kwargs["data"], "meta": None}}


def test_dashboard_update_facade_keeps_owned_envelope_shallow(
    dashboard_dto_module: ModuleType,
) -> None:
    data = {"unknownExistingDocument": {"nested": [1, {"kept": True}]}}
    meta = {"futureMeta": {"kept": True}}
    annotation = {"futureAnnotation": ["kept"]}

    dto = dashboard_dto_module.DashboardUpdateDTO(
        entry_id="dash-1",
        data=data,
        meta=meta,
        annotation=annotation,
        mode="save",
    )

    assert dto.to_payload() == {
        "entry": {
            "entryId": "dash-1",
            "data": data,
            "meta": meta,
            "annotation": annotation,
        },
        "mode": "save",
    }


def test_dashboard_get_and_delete_facades_accept_explicit_none_optionals(
    dashboard_dto_module: ModuleType,
) -> None:
    get_args = dashboard_dto_module.DashboardGetArgsDTO(
        dashboard_id="dash-1",
        workbook_id=None,
        rev_id=None,
        branch=None,
        include_favorite=None,
        include_links=None,
        include_permissions=None,
    )
    delete_args = dashboard_dto_module.DashboardDeleteArgsDTO(
        dashboard_id="dash-1",
        lock_token=None,
    )

    assert get_args.to_payload() == {"dashboardId": "dash-1"}
    assert delete_args.to_payload() == {"dashboardId": "dash-1"}


@pytest.mark.parametrize(
    "case",
    [
        "missing-required",
        "invalid-enum",
        "wrong-discriminator-variant",
        "minimum",
        "min-length",
        "min-items",
    ],
)
def test_dashboard_create_facade_rejects_invalid_schema_features(
    dashboard_dto_module: ModuleType,
    case: str,
) -> None:
    kwargs = _create_kwargs()
    data = cast(dict[str, object], kwargs["data"])
    tab = cast(dict[str, object], cast(list[object], data["tabs"])[0])
    items = cast(list[object], tab["items"])

    if case == "missing-required":
        del tab["title"]
    elif case == "invalid-enum":
        cast(dict[str, object], items[0])["type"] = "future-widget"
    elif case == "wrong-discriminator-variant":
        global_control = cast(dict[str, object], cast(list[object], tab["globalItems"])[0])
        global_control["type"] = "group_control"
    elif case == "minimum":
        data["counter"] = 0
    elif case == "min-length":
        data["salt"] = ""
    elif case == "min-items":
        aliases = cast(dict[str, object], tab["aliases"])
        aliases["default"] = [["country"]]
    else:  # pragma: no cover - the parametrization is exhaustive
        raise AssertionError(case)

    with pytest.raises(ValidationError):
        dashboard_dto_module.DashboardCreateDTO(**kwargs).to_payload()


def test_dashboard_read_facade_is_shallow_tolerant_and_preserves_raw(
    dashboard_dto_module: ModuleType,
) -> None:
    wire = {
        "entryId": "dash-1",
        "workbookId": "wb-1",
        "data": {"tabs": [], "futureNested": {"kept": True}},
        "meta": None,
        "futureEntryField": ["kept", {"verbatim": True}],
    }

    dto = dashboard_dto_module.DashboardReadDTO.model_validate(wire)

    assert dto.entry_id == "dash-1"
    assert dto.workbook_id == "wb-1"
    assert dto.data == wire["data"]
    assert dto.raw == wire


def test_dashboard_contract_metadata_is_transient(tmp_path: Path) -> None:
    metadata = _build_dashboard_metadata(tmp_path)

    write_outputs(tmp_path / "generated", metadata)

    persisted = json.loads(
        (tmp_path / "generated" / "src" / "datalens_sdk" / "_generated" / "installations.json").read_text()
    )
    assert persisted == {"installations": metadata["installations"]}
    assert "dashboard" not in persisted
