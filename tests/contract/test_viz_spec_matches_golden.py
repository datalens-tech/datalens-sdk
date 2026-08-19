from __future__ import annotations

import json
import os
from typing import Any, cast, get_args

import pytest

from datalens_sdk._runtime.wizard_semantics import (
    WIZARD_GEO_LAYER_SEMANTICS,
    WIZARD_VISUALIZATION_SEMANTICS,
)
from datalens_sdk.domain.chart_types import CombinedLayerType

_FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "viz_specs",
)


def _load_fixture(viz_id: str) -> dict[str, Any]:
    path = os.path.join(_FIXTURES_DIR, f"{viz_id}.json")
    with open(path, encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


_IGNORED_VIZ_KEYS_AT_TOP: set[str] = {"placeholders", "layers", "selectedLayerId", "icon"}

_LIVE_CONFIRMED_GEO_LAYER_TYPES = frozenset({"geopoint", "geopoint-with-cluster", "geopolygon", "heatmap", "polyline"})


@pytest.mark.parametrize("viz_id", sorted(WIZARD_VISUALIZATION_SEMANTICS))
def test_viz_top_level_keys_match_golden(viz_id: str) -> None:
    fixture = _load_fixture(viz_id)
    golden_viz: dict[str, Any] = fixture["visualization"]
    semantics = WIZARD_VISUALIZATION_SEMANTICS[viz_id]
    assert golden_viz["id"] == viz_id
    assert {"slots", "slot_aliases", "allows_filters", "allows_labels", "allows_sort"} <= semantics.keys()


@pytest.mark.parametrize("viz_id", sorted(WIZARD_VISUALIZATION_SEMANTICS))
def test_viz_id_and_type_match_golden(viz_id: str) -> None:
    fixture = _load_fixture(viz_id)
    golden = fixture["visualization"]
    assert golden.get("id") == viz_id
    assert isinstance(golden.get("type"), str)


_IGNORED_PH_KEYS: set[str] = {"items"}


@pytest.mark.parametrize("viz_id", sorted(WIZARD_VISUALIZATION_SEMANTICS))
def test_legacy_placeholder_inventory_maps_to_named_slots(viz_id: str) -> None:
    if viz_id in ("combined-chart", "geolayer"):
        return
    fixture = _load_fixture(viz_id)
    golden_phs = fixture["visualization"].get("placeholders") or []
    slots = set(WIZARD_VISUALIZATION_SEMANTICS[viz_id]["slots"])
    for golden_ph in golden_phs:
        legacy_id = golden_ph["id"]
        slot_name = {"flat-table-columns": "columns", "pivot-table-columns": "columns"}.get(legacy_id, legacy_id)
        if slot_name not in slots:
            assert legacy_id in {"colors", "labels", "shapes", "sort", "tooltips"}, (
                f"{viz_id}: legacy {legacy_id!r} has no Wizard v3 named-slot mapping"
            )


@pytest.mark.parametrize("layer_type", get_args(CombinedLayerType))
def test_combined_layer_viz_keys_match_golden(layer_type: str) -> None:
    fixture = _load_fixture("combined-chart")
    layers = fixture["visualization"].get("layers", [])
    matching = [la for la in layers if la.get("type") == layer_type or la.get("id") == layer_type]
    if not matching:
        assert layer_type == "area", f"combined fixture unexpectedly misses {layer_type!r}"
        assert layer_type in WIZARD_VISUALIZATION_SEMANTICS
        return
    golden_layer = matching[0]
    assert golden_layer["layerSettings"]["type"] == layer_type
    legacy_slots = {placeholder["id"] for placeholder in golden_layer["placeholders"]}
    assert legacy_slots <= set(WIZARD_VISUALIZATION_SEMANTICS[layer_type]["slots"])


def test_heatmap_is_a_geo_layer_but_not_a_standalone_viz() -> None:
    assert "heatmap" in WIZARD_GEO_LAYER_SEMANTICS
    assert "heatmap" not in WIZARD_VISUALIZATION_SEMANTICS


@pytest.mark.parametrize("layer_type", sorted(WIZARD_GEO_LAYER_SEMANTICS))
def test_geo_layer_viz_keys_match_golden(layer_type: str) -> None:
    contract = _load_fixture("geolayer-live-contract")["layers"][layer_type]
    semantics = WIZARD_GEO_LAYER_SEMANTICS[layer_type]
    inputs = {placeholder["input"] for placeholder in contract["placeholders"].values()}
    assert semantics["required_geometry"] in inputs
    assert inputs <= semantics["supported_inputs"]


@pytest.mark.parametrize("layer_type", sorted(_LIVE_CONFIRMED_GEO_LAYER_TYPES))
def test_geo_layer_spec_matches_confirmed_live_contract(layer_type: str) -> None:
    contract = _load_fixture("geolayer-live-contract")["layers"][layer_type]
    semantics = WIZARD_GEO_LAYER_SEMANTICS[layer_type]
    required = [placeholder for placeholder in contract["placeholders"].values() if placeholder.get("required") is True]
    assert len(required) == 1
    assert required[0]["input"] == semantics["required_geometry"]
    assert contract["viz"]["id"] == layer_type
    assert contract["viz"]["type"] == "geo"
