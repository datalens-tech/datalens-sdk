from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.codegen import build_html_page_contract_meta

ROOT = Path(__file__).resolve().parents[2]
HTML_PAGE_ROUTES = (
    "/rpc/createHtmlPage",
    "/rpc/deleteHtmlPage",
    "/rpc/getHtmlPage",
    "/rpc/updateHtmlPage",
)


def _spec(installation: str = "enterprise") -> dict[str, object]:
    return cast(dict[str, object], json.loads((ROOT / "spec" / f"{installation}.json").read_text()))


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
def test_html_page_contract_is_available_in_checked_in_specs(installation: str) -> None:
    spec = _spec(installation)
    contract = build_html_page_contract_meta(spec)

    assert contract is not None
    assert set(contract["roots"]) == {
        "CreateHtmlPageArgs",
        "CreateHtmlPageResult",
        "DeleteHtmlPageArgs",
        "GetHtmlPageArgs",
        "GetHtmlPageResult",
        "UpdateHtmlPageArgs",
        "UpdateHtmlPageResult",
    }
    paths = spec["paths"]
    assert isinstance(paths, dict)
    assert all(route in paths for route in HTML_PAGE_ROUTES)


def test_html_page_contract_rejects_partial_route_availability() -> None:
    spec = _spec()
    paths = spec["paths"]
    assert isinstance(paths, dict)
    del paths["/rpc/updateHtmlPage"]

    with pytest.raises(ValueError, match="HTML-page routes differ"):
        build_html_page_contract_meta(spec)


def test_html_page_contract_rejects_misbound_result_schema() -> None:
    spec = copy.deepcopy(_spec())
    paths = spec["paths"]
    assert isinstance(paths, dict)
    create_route = paths["/rpc/createHtmlPage"]
    assert isinstance(create_route, dict)
    post = create_route["post"]
    assert isinstance(post, dict)
    responses = post["responses"]
    assert isinstance(responses, dict)
    response = responses["200"]
    assert isinstance(response, dict)
    content = response["content"]
    assert isinstance(content, dict)
    media = content["application/json"]
    assert isinstance(media, dict)
    media["schema"] = {"$ref": "#/components/schemas/UpdateHtmlPageResult"}

    with pytest.raises(ValueError, match="schema references differ"):
        build_html_page_contract_meta(spec)
