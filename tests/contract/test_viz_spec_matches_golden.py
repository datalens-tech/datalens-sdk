from __future__ import annotations

import json
import os
from typing import Any, cast

import pytest

from datalens_sdk._runtime.viz_specs import (
    _GEO_LAYER_VIZ_SPECS,
    _LAYER_VIZ_SPECS,
    VIZ_SPECS,
    get_geo_layer_spec,
    get_layer_spec,
    get_viz_spec,
)

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


@pytest.mark.parametrize("viz_id", sorted(VIZ_SPECS.keys()))
def test_viz_top_level_keys_match_golden(viz_id: str) -> None:
    fixture = _load_fixture(viz_id)
    golden_viz: dict[str, Any] = fixture["visualization"]
    spec_viz = cast(dict[str, Any], get_viz_spec(viz_id).get("viz", {}))
    golden_keys = set(golden_viz.keys()) - _IGNORED_VIZ_KEYS_AT_TOP
    spec_keys = set(spec_viz.keys())
    missing = golden_keys - spec_keys
    assert not missing, "VIZ_SPECS['{}'].viz missing keys: {}; update spec from golden_id={}".format(
        viz_id, sorted(missing), fixture.get("golden_id")
    )


@pytest.mark.parametrize("viz_id", sorted(VIZ_SPECS.keys()))
def test_viz_id_and_type_match_golden(viz_id: str) -> None:
    fixture = _load_fixture(viz_id)
    golden = fixture["visualization"]
    spec_viz = cast(dict[str, Any], get_viz_spec(viz_id).get("viz", {}))
    assert spec_viz.get("id") == golden.get("id")
    assert spec_viz.get("type") == golden.get("type")


_IGNORED_PH_KEYS: set[str] = {"items"}


@pytest.mark.parametrize("viz_id", sorted(VIZ_SPECS.keys()))
def test_placeholder_keys_match_golden(viz_id: str) -> None:
    if viz_id in ("combined-chart", "geolayer"):
        return
    fixture = _load_fixture(viz_id)
    golden_phs = fixture["visualization"].get("placeholders") or []
    spec_phs = cast(dict[str, Any], get_viz_spec(viz_id).get("placeholders", {}))
    for golden_ph in golden_phs:
        ph_id = golden_ph["id"]
        assert ph_id in spec_phs, (
            f"VIZ_SPECS['{viz_id}'].placeholders missing id='{ph_id}'; present: {sorted(spec_phs.keys())}"
        )
        spec_ph = spec_phs[ph_id]
        golden_keys = set(golden_ph.keys()) - _IGNORED_PH_KEYS
        spec_keys = set(spec_ph.keys())
        missing = golden_keys - spec_keys
        assert not missing, "VIZ_SPECS['{}'].placeholders['{}'] missing keys: {} (golden_id={}, has: {})".format(
            viz_id, ph_id, sorted(missing), fixture.get("golden_id"), sorted(spec_keys)
        )


@pytest.mark.parametrize("layer_type", sorted(_LAYER_VIZ_SPECS.keys()))
def test_combined_layer_viz_keys_match_golden(layer_type: str) -> None:
    if layer_type == "area":
        spec = get_layer_spec("area")
        viz = cast(dict[str, Any], spec.get("viz", {}))
        assert viz.get("id") == "area"
        assert viz.get("type") == "line"
        assert "iconProps" in viz
        return

    fixture = _load_fixture("combined-chart")
    layers = fixture["visualization"].get("layers", [])
    matching = [la for la in layers if la.get("type") == layer_type or la.get("id") == layer_type]
    if not matching:
        pytest.skip(f"combined.json has no layer of type '{layer_type}' for comparison")
    golden_layer = matching[0]
    spec_layer_viz = cast(dict[str, Any], get_layer_spec(layer_type).get("viz", {}))

    ignored = {"id", "layerSettings", "placeholders", "commonPlaceholders"}
    golden_keys = set(golden_layer.keys()) - ignored
    spec_keys = set(spec_layer_viz.keys())
    missing = golden_keys - spec_keys
    assert not missing, f"Layer-spec '{layer_type}' missing keys: {sorted(missing)}; has: {sorted(spec_keys)}"


def test_heatmap_is_a_geo_layer_but_not_a_standalone_viz() -> None:
    assert "heatmap" in _GEO_LAYER_VIZ_SPECS
    assert "heatmap" not in VIZ_SPECS


@pytest.mark.parametrize("layer_type", sorted(_GEO_LAYER_VIZ_SPECS.keys()))
def test_geo_layer_viz_keys_match_golden(layer_type: str) -> None:
    fixture = _load_fixture("geolayer")
    layers = fixture["visualization"].get("layers", [])
    matching = [
        la for la in layers if la.get("id") == layer_type or la.get("layerSettings", {}).get("type") == layer_type
    ]
    if not matching:
        spec = get_geo_layer_spec(layer_type)
        assert cast(dict[str, Any], spec.get("viz", {})).get("type") == "geo", (
            f"Geo-layer-spec '{layer_type}' must have viz.type='geo'"
        )
        return
    golden_layer = matching[0]
    spec_layer_viz = cast(dict[str, Any], get_geo_layer_spec(layer_type).get("viz", {}))
    ignored = {
        "id",
        "type",
        "layerSettings",
        "placeholders",
        "commonPlaceholders",
        "icon",
        "hidden",
        "name",
    }
    golden_keys = set(golden_layer.keys()) - ignored
    spec_keys = set(spec_layer_viz.keys())
    missing = golden_keys - spec_keys
    assert not missing, f"Geo-layer-spec '{layer_type}' missing keys: {sorted(missing)}"


@pytest.mark.parametrize("layer_type", sorted(_LIVE_CONFIRMED_GEO_LAYER_TYPES))
def test_geo_layer_spec_matches_confirmed_live_contract(layer_type: str) -> None:
    contract = _load_fixture("geolayer-live-contract")["layers"][layer_type]
    spec = get_geo_layer_spec(layer_type)

    assert spec["viz"] == contract["viz"]
    placeholders = cast(dict[str, dict[str, object]], spec["placeholders"])
    inputs = cast(dict[str, str], spec["placeholder_inputs"])
    assert set(placeholders) == set(contract["placeholders"])
    for placeholder_id, expected in contract["placeholders"].items():
        expected = dict(expected)
        assert inputs[placeholder_id] == expected.pop("input")
        for key, value in expected.items():
            assert placeholders[placeholder_id][key] == value
