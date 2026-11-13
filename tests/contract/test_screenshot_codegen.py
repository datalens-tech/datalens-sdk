from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast

from pydantic import ValidationError
import pytest

from datalens_sdk._generated import dto
from datalens_sdk.codegen import build_screenshot_contract_meta

ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_ROUTES = ("/rpc/getChartScreenshot", "/rpc/getDashScreenshot")


def _spec(installation: str = "yacloud") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{installation}.json").read_text()))


def _paths(spec: dict[str, object]) -> dict[str, object]:
    paths = spec["paths"]
    assert isinstance(paths, dict)
    return cast(dict[str, object], paths)


def test_screenshot_contract_is_available_in_yandex_cloud_spec() -> None:
    contract = build_screenshot_contract_meta(_spec())

    assert contract is not None
    assert contract["roots"] == ["GetChartScreenshotArgs", "GetDashScreenshotArgs", "GetScreenshotResult"]
    assert set(contract["schemas"]) == set(contract["roots"])


def test_screenshot_contract_is_absent_from_enterprise_spec() -> None:
    assert build_screenshot_contract_meta(_spec("enterprise")) is None


def test_screenshot_contract_rejects_partial_route_availability() -> None:
    spec = _spec()
    del _paths(spec)["/rpc/getDashScreenshot"]

    with pytest.raises(ValueError, match="Screenshot routes differ"):
        build_screenshot_contract_meta(spec)


def test_screenshot_contract_rejects_misbound_result_schema() -> None:
    spec = copy.deepcopy(_spec())
    node: object = _paths(spec)
    for key in ("/rpc/getChartScreenshot", "post", "responses", "200", "content", "application/json", "schema"):
        assert isinstance(node, dict)
        node = node[key]
    assert isinstance(node, dict)
    node["$ref"] = "#/components/schemas/GetChartScreenshotArgs"

    with pytest.raises(ValueError, match="schema references differ"):
        build_screenshot_contract_meta(spec)


def test_screenshot_request_dtos_serialize_wire_aliases() -> None:
    chart = dto.GetChartScreenshotArgsDTO.model_validate(
        {
            "chart_id": "chart-1",
            "type": "png",
            "base64": True,
            "width": 1024,
            "height": 768,
            "query_params": {"revId": "rev-1", "City": ["Moscow", "Kazan"]},
        }
    )
    dashboard = dto.GetDashScreenshotArgsDTO.model_validate(
        {"dash_id": "dash-1", "type": "png", "s3": True, "full_page": True}
    )

    assert chart.to_payload() == {
        "chartId": "chart-1",
        "type": "png",
        "base64": True,
        "width": 1024,
        "height": 768,
        "queryParams": {"revId": "rev-1", "City": ["Moscow", "Kazan"]},
    }
    assert dashboard.to_payload() == {"dashId": "dash-1", "type": "png", "s3": True, "fullPage": True}


@pytest.mark.parametrize(
    "overrides",
    [{"width": 0}, {"width": 6001}, {"height": -1}, {"type": "gif"}, {"unknown": True}],
)
def test_screenshot_request_dto_rejects_out_of_contract_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        dto.GetChartScreenshotArgsDTO.model_validate({"chart_id": "chart-1", **overrides})


def test_screenshot_result_dto_requires_data_and_ignores_extras() -> None:
    result = dto.GetScreenshotResultReadDTO.model_validate({"data": "aGVsbG8=", "future": "ignored"})

    assert result.data == "aGVsbG8="
    with pytest.raises(ValidationError):
        dto.GetScreenshotResultReadDTO.model_validate({})
    with pytest.raises(ValidationError):
        dto.GetScreenshotResultReadDTO.model_validate({"data": 1})
