"""Smoke checks for the anonymized dashboard golden fixtures (D0.2).

Each fixture is a live /rpc/getDashboard v2 response (published branch,
entry envelope removed, anonymized). The smoke gate asserts every fixture
flows through the public read path without loss; full golden round-trip
contract tests are a separate work item (D1.5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"
_FIXTURE_PATHS = sorted(_FIXTURES_DIR.glob("*.json"))


def _load(path: Path) -> dict[str, object]:
    data: object = json.loads(path.read_text())
    assert isinstance(data, dict)
    return cast(dict[str, object], data)


def _client_returning(entry: dict[str, object]) -> dl.DataLensClientYC:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rpc/getDashboard"
        return httpx.Response(200, json={"entry": entry})

    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_fixture_parses_through_read_path(path: Path) -> None:
    entry = _load(path)
    client = _client_returning(entry)

    dashboard = client.get.dashboard(by_id=cast(str, entry["entryId"]))

    assert dashboard.id == entry["entryId"]
    assert dashboard.name == path.stem
    assert dashboard.rev_id == entry["revId"]
    assert dashboard.saved_id == entry["savedId"]
    assert dashboard.published_id == entry["publishedId"]
    assert dashboard.location is not None
    tabs = dashboard.data.get("tabs")
    assert isinstance(tabs, list)
    assert tabs
    # lenient read must not drop anything the wire sent
    assert dashboard.raw == entry


def test_fixture_inventory_is_complete() -> None:
    assert {path.stem for path in _FIXTURE_PATHS} == {
        "simple",
        "selectors_dataset",
        "selectors_manual_two_tabs",
        "group_control_manual",
        "group_control_dataset",
        "global_items_shared_selectors",
        "items_features",
    }
