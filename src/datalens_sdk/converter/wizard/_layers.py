from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from typing import cast
import uuid

from datalens_sdk._runtime.viz_specs import get_geo_layer_spec, get_layer_spec, get_viz_spec
from datalens_sdk.converter.wizard._common import FieldRef
from datalens_sdk.converter.wizard._normalizer import _Normalizer
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec
from datalens_sdk.errors import DataLensConfigurationError


def _local_fields_map(local_fields: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    # First pass: index by guid (takes priority)
    for lf in local_fields:
        guid = lf.get("guid")
        if isinstance(guid, str) and guid:
            out[guid] = dict(lf)
    # Second pass: index by title as an alias, unless the title string already
    # exists as a guid key (to avoid shadowing another field's guid).
    for lf in local_fields:
        title = lf.get("title")
        if isinstance(title, str) and title and title not in out:
            out[title] = dict(lf)
    return out


def _hierarchies_map(hierarchies: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Index hierarchies by guid (priority) and by title (alias) for placement.

    Mirrors ``_local_fields_map`` so a hierarchy can be placed into a
    placeholder via its title/guid string the same way local fields are.
    """
    out: dict[str, dict[str, object]] = {}
    for h in hierarchies:
        guid = h.get("guid")
        if isinstance(guid, str) and guid:
            out[guid] = dict(h)
    for h in hierarchies:
        title = h.get("title")
        if isinstance(title, str) and title and title not in out:
            out[title] = dict(h)
    return out


def _build_combined_visualization(
    spec: WizardChartCreateSpec,
    normalizer: _Normalizer,
) -> dict[str, object]:
    viz_spec = get_viz_spec("combined-chart")
    viz: dict[str, object] = dict(cast(dict[str, object], viz_spec.get("viz", {})))
    viz["id"] = cast(dict[str, object], viz_spec.get("viz", {})).get("id", "combined-chart")

    x_fields: tuple[FieldRef, ...] = spec.placeholders.get("x", ())
    if len(x_fields) > 1:
        raise DataLensConfigurationError("Combined chart .x() accepts at most one field.")
    normalized_x = normalizer.normalize(x_fields)

    layers: list[dict[str, object]] = []
    # Palette index is assigned across ALL layers (not per-layer), so each
    # layer's measure maps to a distinct palette slot -> different colors per
    # layer. A per-layer ``enumerate`` would reset to 0 and every single-measure
    # layer would collide on palette index 0 (one color for all layers).
    measure_color_index = 0
    for index, layer_input in enumerate(spec.combined_layers, start=1):
        layer_type = layer_input.get("layer_type")
        if not isinstance(layer_type, str):
            continue
        layer_spec = get_layer_spec(layer_type)
        if not layer_spec:
            raise DataLensConfigurationError(f"Unsupported combined layer type: {layer_type!r}.")
        layer: dict[str, object] = dict(cast(dict[str, object], layer_spec.get("viz", {})))
        layer_id = str(uuid.uuid4())
        configured_name = layer_input.get("name")
        layer["layerSettings"] = {
            "id": layer_id,
            "name": configured_name if isinstance(configured_name, str) else f"Layer {index}",
            "type": layer_type,
            "alpha": 80,
            "valid": True,
        }

        common = layer_spec.get("common_placeholders")
        common_placeholders = copy.deepcopy(dict(common)) if isinstance(common, Mapping) else {}
        measure_items: list[dict[str, object]] = []
        y_input = layer_input.get("y")
        y2_input = layer_input.get("y2")
        normalized_by_placeholder: dict[str, list[dict[str, object]]] = {"x": list(normalized_x)}
        if y_input is not None:
            normalized_by_placeholder["y"] = normalizer.normalize([cast(FieldRef, y_input)])
            measure_items.extend(normalized_by_placeholder["y"])
        if y2_input is not None:
            normalized_by_placeholder["y2"] = normalizer.normalize([cast(FieldRef, y2_input)])
            measure_items.extend(normalized_by_placeholder["y2"])
        mounted_colors: dict[str, str] = {}
        for measure in measure_items:
            title = measure.get("title")
            if isinstance(title, str) and title:
                mounted_colors[title] = str(measure_color_index)
            measure_color_index += 1
        if mounted_colors:
            common_placeholders["colorsConfig"] = {
                "colorMode": "palette",
                "coloredByMeasure": True,
                "fieldGuid": measure_items[0].get("guid"),
                "mountedColors": mounted_colors,
                "palette": "",
                "polygonBorders": "show",
            }
        layer["commonPlaceholders"] = common_placeholders

        layer_placeholders = cast(dict[str, object], layer_spec.get("placeholders", {}))
        placeholders: list[dict[str, object]] = []
        for placeholder_id, placeholder_spec in layer_placeholders.items():
            placeholder = copy.deepcopy(cast(dict[str, object], placeholder_spec))
            placeholder["id"] = placeholder_id
            placeholder["items"] = normalized_by_placeholder.get(placeholder_id, [])
            placeholders.append(placeholder)
        layer["placeholders"] = placeholders
        layers.append(layer)

    viz["layers"] = layers
    viz["placeholders"] = []
    if layers:
        layer_settings = cast(dict[str, object], layers[-1]["layerSettings"])
        viz["selectedLayerId"] = layer_settings["id"]
    return viz


def _build_geolayer_visualization(
    spec: WizardChartCreateSpec,
    default_normalizer: _Normalizer,
) -> dict[str, object]:
    viz_spec = get_viz_spec("geolayer")
    viz: dict[str, object] = dict(cast(dict[str, object], viz_spec.get("viz", {})))
    viz["id"] = cast(dict[str, object], viz_spec.get("viz", {})).get("id", "geolayer")
    local_fields = _local_fields_map(spec.local_fields)
    layers: list[dict[str, object]] = []
    for index, layer_input in enumerate(spec.geo_layers, start=1):
        layer_type = layer_input.get("layer_type")
        if not isinstance(layer_type, str):
            continue
        layer_spec = get_geo_layer_spec(layer_type)
        if not layer_spec:
            raise DataLensConfigurationError(f"Unsupported geo layer type: {layer_type!r}.")
        layer_dataset = layer_input.get("dataset")
        normalizer = (
            _Normalizer(dataset=layer_dataset, local_fields=local_fields)
            if isinstance(layer_dataset, Dataset)
            else default_normalizer
        )
        layer: dict[str, object] = dict(cast(dict[str, object], layer_spec.get("viz", {})))
        layer_id = str(uuid.uuid4())
        configured_name = layer_input.get("name")
        layer["layerSettings"] = {
            "id": layer_id,
            "name": configured_name if isinstance(configured_name, str) else f"Layer {index}",
            "type": layer_type,
            "alpha": layer_input.get("alpha", 80),
            "valid": True,
        }
        common_source = layer_spec.get("common_placeholders")
        common = copy.deepcopy(dict(common_source)) if isinstance(common_source, Mapping) else {}
        color = layer_input.get("color")
        if color is not None:
            common["colors"] = normalizer.normalize([cast(FieldRef, color)])
        tooltips = layer_input.get("tooltips")
        if isinstance(tooltips, list) and tooltips:
            common["tooltips"] = normalizer.normalize(cast(list[FieldRef], tooltips))
        labels = layer_input.get("labels")
        if isinstance(labels, list) and labels:
            common["labels"] = normalizer.normalize(cast(list[FieldRef], labels))
        layer["commonPlaceholders"] = common
        layer_placeholders = cast(dict[str, object], layer_spec.get("placeholders", {}))
        placeholders: list[dict[str, object]] = []
        for placeholder_id, placeholder_spec in layer_placeholders.items():
            placeholder = copy.deepcopy(cast(dict[str, object], placeholder_spec))
            placeholder["id"] = placeholder_id
            source_key = "polygon" if placeholder_id == "geopolygon" else placeholder_id
            value = layer_input.get(source_key)
            placeholder["items"] = normalizer.normalize([cast(FieldRef, value)]) if value is not None else []
            placeholders.append(placeholder)
        layer["placeholders"] = placeholders
        layers.append(layer)
    viz["layers"] = layers
    viz["placeholders"] = []
    if layers:
        layer_settings = cast(dict[str, object], layers[-1]["layerSettings"])
        viz["selectedLayerId"] = layer_settings["id"]
    return viz
