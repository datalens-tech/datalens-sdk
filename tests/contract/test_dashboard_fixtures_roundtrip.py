"""Golden round-trip contract tests for the dashboard read vertical (D1.5).

Each fixture in fixtures/dashboards/ is a live /rpc/getDashboard v2 response
(published branch, entry envelope removed, anonymized). These tests pin the
lossless contract of the read path at both layers:

* ``DashboardReadDTO.model_validate(entry).raw`` is the verbatim wire entry;
* ``client.get.dashboard(...).raw`` is the verbatim wire entry;
* feature-bearing fixtures keep their quirky payloads byte-for-byte
  (neuro_widget, enableActionParams, pinned layout parents, shared
  globalItems).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk._generated import dto as generated_dto

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"
_FIXTURE_PATHS = sorted(_FIXTURES_DIR.glob("*.json"))


def _load(path: Path) -> dict[str, object]:
    data: object = json.loads(path.read_text())
    assert isinstance(data, dict)
    return cast(dict[str, object], data)


def _load_fixture(stem: str) -> dict[str, object]:
    return _load(_FIXTURES_DIR / f"{stem}.json")


def _client_returning(entry: dict[str, object]) -> dl.DataLensClientYC:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rpc/getDashboard"
        return httpx.Response(200, json={"entry": entry})

    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(handler))


def _tabs(entry: dict[str, object]) -> list[dict[str, object]]:
    data = entry["data"]
    assert isinstance(data, dict)
    tabs = data["tabs"]
    assert isinstance(tabs, list)
    return cast(list[dict[str, object]], tabs)


def _tab_items(tab: dict[str, object], field: str) -> list[dict[str, object]]:
    items = tab.get(field, [])
    assert isinstance(items, list)
    return cast(list[dict[str, object]], items)


@pytest.mark.parametrize("path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_read_dto_round_trips_fixture_verbatim(path: Path) -> None:
    entry = _load(path)

    read_dto = generated_dto.DashboardReadDTO.model_validate(entry)

    assert read_dto.raw == entry


@pytest.mark.parametrize("path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_read_path_round_trips_fixture_verbatim(path: Path) -> None:
    entry = _load(path)
    client = _client_returning(entry)

    dashboard = client.get.dashboard(by_id=cast(str, entry["entryId"]))

    assert dashboard.raw == entry


@pytest.mark.parametrize("path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_read_dto_identity_uses_canonical_wire_key(path: Path) -> None:
    # DashboardReadDTO has populate_by_name=True and would happily accept a
    # pythonic "entry_id" key; the canonical contract is the camelCase wire
    # key, so identity is asserted against raw, not the DTO field.
    entry = _load(path)

    read_dto = generated_dto.DashboardReadDTO.model_validate(entry)

    assert "entry_id" not in read_dto.raw
    assert read_dto.raw["entryId"] == entry["entryId"]
    assert read_dto.entry_id == entry["entryId"]


def test_items_features_fixture_keeps_quirky_item_payloads() -> None:
    entry = _load_fixture("items_features")
    client = _client_returning(entry)

    dashboard = client.get.dashboard(by_id=cast(str, entry["entryId"]))

    fixture_tabs = _tabs(entry)
    read_tabs = _tabs(cast(dict[str, object], dashboard.raw))
    assert read_tabs == fixture_tabs

    fixture_items = [item for tab in fixture_tabs for item in _tab_items(tab, "items")]
    read_items = [item for tab in read_tabs for item in _tab_items(tab, "items")]

    neuro_fixture = [item for item in fixture_items if item.get("type") == "neuro_widget"]
    neuro_read = [item for item in read_items if item.get("type") == "neuro_widget"]
    assert neuro_fixture
    assert neuro_read == neuro_fixture

    action_params_fixture = [item for item in fixture_items if "enableActionParams" in json.dumps(item)]
    action_params_read = [item for item in read_items if "enableActionParams" in json.dumps(item)]
    assert action_params_fixture
    assert action_params_read == action_params_fixture

    fixture_parents = {
        cast(str, layout_item["parent"])
        for tab in fixture_tabs
        for layout_item in _tab_items(tab, "layout")
        if "parent" in layout_item
    }
    read_layout_by_parent = {
        cast(str, layout_item["parent"]): layout_item
        for tab in read_tabs
        for layout_item in _tab_items(tab, "layout")
        if "parent" in layout_item
    }
    assert fixture_parents == {"__fixHead", "__fixGCont"}
    assert set(read_layout_by_parent) == fixture_parents


def test_global_items_fixture_keeps_shared_selector_contract() -> None:
    entry = _load_fixture("global_items_shared_selectors")
    client = _client_returning(entry)

    dashboard = client.get.dashboard(by_id=cast(str, entry["entryId"]))

    fixture_tabs = _tabs(entry)
    read_tabs = _tabs(cast(dict[str, object], dashboard.raw))

    fixture_global = [_tab_items(tab, "globalItems") for tab in fixture_tabs]
    read_global = [_tab_items(tab, "globalItems") for tab in read_tabs]
    assert read_global == fixture_global

    # shared selectors are the same ids replicated across every tab — a
    # contract, not an id collision (d3e4)
    id_sets = [{cast(str, item["id"]) for item in items} for items in read_global]
    assert all(id_sets)
    assert len({frozenset(ids) for ids in id_sets}) == 1
    assert len(id_sets) == len(fixture_tabs) == 4
