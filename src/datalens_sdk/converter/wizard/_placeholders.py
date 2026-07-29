from __future__ import annotations

import copy
from typing import cast

from datalens_sdk._runtime.viz_specs import get_placeholder_id, get_viz_spec
from datalens_sdk.converter.wizard._common import _items_list, _placeholders_list
from datalens_sdk.converter.wizard._layers import _build_combined_visualization, _build_geolayer_visualization
from datalens_sdk.converter.wizard._normalizer import _Normalizer
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec


def _enrich_placeholder(spec_key: str, builder_ph_id: str, items: list[dict[str, object]]) -> dict[str, object]:
    actual_id = get_placeholder_id(spec_key, builder_ph_id)
    spec = get_viz_spec(spec_key)
    ph_specs = cast(dict[str, object], spec.get("placeholders", {}))
    ph_spec = ph_specs.get(actual_id, {})
    result = copy.deepcopy(cast(dict[str, object], ph_spec)) if ph_spec else {}
    result["id"] = actual_id
    result["items"] = items
    return result


def _build_visualization(
    spec: WizardChartCreateSpec,
    spec_key: str,
    normalizer: _Normalizer,
) -> dict[str, object]:
    placeholders_input = spec.placeholders
    if spec_key == "combined-chart":
        return _build_combined_visualization(spec, normalizer)
    if spec_key == "geolayer":
        return _build_geolayer_visualization(spec, normalizer)

    viz_spec = get_viz_spec(spec_key)
    viz: dict[str, object] = dict(cast(dict[str, object], viz_spec.get("viz", {})))
    viz["id"] = cast(dict[str, object], viz_spec.get("viz", {})).get("id", spec_key)

    normalized: dict[str, list[dict[str, object]]] = {
        builder_pid: normalizer.normalize(items) for builder_pid, items in placeholders_input.items()
    }

    enriched: list[dict[str, object]] = []
    spec_ph_order = list(cast(dict[str, object], viz_spec.get("placeholders", {})).keys())
    placed: set[str] = set()
    for spec_pid in spec_ph_order:
        matched: str | None = None
        for builder_pid in normalized:
            if get_placeholder_id(spec_key, builder_pid) == spec_pid:
                matched = builder_pid
                break
        if matched is not None:
            enriched.append(_enrich_placeholder(spec_key, matched, normalized[matched]))
            placed.add(matched)
    for builder_pid, items in normalized.items():
        if builder_pid not in placed:
            enriched.append(_enrich_placeholder(spec_key, builder_pid, items))
    viz["placeholders"] = enriched
    return viz


def _fill_missing_placeholders(data: dict[str, object], spec_key: str) -> None:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    if viz.get("layers"):
        return
    spec = get_viz_spec(spec_key)
    ph_specs = cast(dict[str, object], spec.get("placeholders", {}))
    if not ph_specs:
        return
    existing_by_id: dict[str, dict[str, object]] = {}
    for p in _placeholders_list(viz):
        pid = p.get("id")
        if isinstance(pid, str):
            existing_by_id[pid] = p
    spec_ids = list(ph_specs.keys())
    new_list: list[dict[str, object]] = []
    for ph_id, ph_spec in ph_specs.items():
        if ph_id in existing_by_id:
            new_list.append(existing_by_id[ph_id])
        else:
            new_ph = copy.deepcopy(cast(dict[str, object], ph_spec))
            new_ph["id"] = ph_id
            new_ph["items"] = []
            new_list.append(new_ph)
    for p in _placeholders_list(viz):
        if p.get("id") not in spec_ids:
            new_list.append(p)
    viz["placeholders"] = new_list


def _sync_axis_mode_map_in_placeholders(placeholders: list[dict[str, object]]) -> None:
    for ph in placeholders:
        settings = ph.get("settings")
        if not isinstance(settings, dict) or "axisModeMap" not in settings:
            continue
        current_map = settings.get("axisModeMap")
        if not isinstance(current_map, dict):
            current_map = {}
        for item in _items_list(ph):
            guid = item.get("guid")
            if not isinstance(guid, str) or not guid:
                continue
            if item.get("type") != "DIMENSION":
                continue
            data_type = str(item.get("data_type") or "").lower()
            if data_type.startswith("date") or "datetime" in data_type:
                current_map.setdefault(guid, "continuous")
        if current_map:
            settings["axisModeMap"] = current_map


def _sync_axis_mode_map(data: dict[str, object]) -> None:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    _sync_axis_mode_map_in_placeholders(_placeholders_list(viz))
    layers = viz.get("layers")
    if isinstance(layers, list):
        for layer in layers:
            if isinstance(layer, dict):
                _sync_axis_mode_map_in_placeholders(_placeholders_list(layer))
