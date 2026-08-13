from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from typing import cast
import uuid

from datalens_sdk._runtime.chart_constants import gradient_types_for_palette
from datalens_sdk._runtime.viz_specs import geo_layer_supports_input, get_geo_layer_spec, get_layer_spec, get_viz_spec
from datalens_sdk.converter.wizard._common import FieldRef
from datalens_sdk.converter.wizard._decorations import _build_sort_item
from datalens_sdk.converter.wizard._normalizer import _Normalizer
from datalens_sdk.domain.chart_types import GeoLayerFilter
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
        if color is not None and geo_layer_supports_input(layer_spec, "color"):
            common["colors"] = normalizer.normalize([cast(FieldRef, color)])
        color_mode = layer_input.get("color_mode")
        color_palette = layer_input.get("color_palette")
        color_reversed = layer_input.get("color_reversed")
        if geo_layer_supports_input(layer_spec, "color") and any(
            value is not None for value in (color_mode, color_palette, color_reversed)
        ):
            gradient_mode = color_mode if isinstance(color_mode, str) else None
            colors_config = {
                "polygonBorders": "show",
                "reversed": color_reversed if isinstance(color_reversed, bool) else False,
                "thresholdsMode": "auto",
            }
            if layer_type != "polyline":
                colors_config["colorMode"] = "gradient"
            if isinstance(color_palette, str):
                colors_config["gradientPalette"] = color_palette
                if gradient_mode is None:
                    gradient_types = gradient_types_for_palette(color_palette)
                    gradient_mode = (
                        "2-point" if "2-point" in gradient_types else "3-point" if "3-point" in gradient_types else None
                    )
            if gradient_mode is not None:
                colors_config["gradientMode"] = gradient_mode
            common["colorsConfig"] = colors_config
        layer_filters = layer_input.get("filters")
        if geo_layer_supports_input(layer_spec, "filters") and isinstance(layer_filters, list) and layer_filters:
            normalized_filters: list[dict[str, object]] = []
            for layer_filter in layer_filters:
                if not isinstance(layer_filter, GeoLayerFilter):
                    raise DataLensConfigurationError("Geo layer filters must be GeoLayerFilter values.")
                normalized = normalizer.normalize([layer_filter.field])
                if not normalized:
                    raise DataLensConfigurationError(
                        f"Could not resolve geo layer filter field {layer_filter.field!r}."
                    )
                filter_field = dict(normalized[0])
                filter_field["filter"] = {
                    "operation": {"code": layer_filter.operation},
                    "value": list(layer_filter.values),
                }
                normalized_filters.append(filter_field)
            common["filters"] = normalized_filters
        tooltips = layer_input.get("tooltips")
        if geo_layer_supports_input(layer_spec, "tooltips") and isinstance(tooltips, list) and tooltips:
            common["tooltips"] = normalizer.normalize(cast(list[FieldRef], tooltips))
        labels = layer_input.get("labels")
        if geo_layer_supports_input(layer_spec, "labels") and isinstance(labels, list) and labels:
            normalized_labels = normalizer.normalize(cast(list[FieldRef], labels))
            available_label_modes = layer.get("availableLabelModes")
            if available_label_modes == ["absolute"]:
                for label in normalized_labels:
                    label["mode"] = "absolute"
            common["labels"] = normalized_labels
        sort_by = layer_input.get("sort_by")
        if sort_by is not None and geo_layer_supports_input(layer_spec, "sort_by"):
            normalized_sort = normalizer.normalize([cast(FieldRef, sort_by)])
            if not normalized_sort:
                raise DataLensConfigurationError(f"Could not resolve geo layer sort field {sort_by!r}.")
            sort_direction = layer_input.get("sort_direction", "asc")
            if sort_direction not in {"asc", "desc"}:
                raise DataLensConfigurationError(f"Unsupported geo layer sort direction: {sort_direction!r}.")
            dataset_id = (
                layer_dataset.id
                if isinstance(layer_dataset, Dataset)
                else spec.dataset.id
                if spec.dataset is not None
                else None
            )
            common["sort"] = [
                _build_sort_item(
                    normalized_sort[0],
                    direction=sort_direction,
                    dataset_id=dataset_id,
                    preserve_field_snapshot=True,
                )
            ]
        layer["commonPlaceholders"] = common
        layer_placeholders = cast(dict[str, object], layer_spec.get("placeholders", {}))
        placeholder_inputs = cast(dict[str, object], layer_spec.get("placeholder_inputs", {}))
        placeholders: list[dict[str, object]] = []
        for placeholder_id, placeholder_spec in layer_placeholders.items():
            placeholder = copy.deepcopy(cast(dict[str, object], placeholder_spec))
            placeholder["id"] = placeholder_id
            source_key = placeholder_inputs.get(placeholder_id, placeholder_id)
            if not isinstance(source_key, str):
                raise DataLensConfigurationError(
                    f"Geo layer placeholder {placeholder_id!r} has an invalid input mapping: {source_key!r}."
                )
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


def _sync_geolayer_selected_layer_fields(data: dict[str, object]) -> None:
    """Mirror the selected layer's field sections into the live top-level shape.

    Layer-local filters intentionally stay in ``commonPlaceholders.filters``;
    ``data.filters`` is the independent chart-level filter scope.
    """
    visualization = data.get("visualization")
    if not isinstance(visualization, Mapping):
        return
    layers = visualization.get("layers")
    selected_layer_id = visualization.get("selectedLayerId")
    if not isinstance(layers, list) or not isinstance(selected_layer_id, str):
        return
    selected_layer: Mapping[str, object] | None = None
    for layer in layers:
        if not isinstance(layer, Mapping):
            continue
        settings = layer.get("layerSettings")
        if isinstance(settings, Mapping) and settings.get("id") == selected_layer_id:
            selected_layer = layer
            break
    if selected_layer is None:
        return
    common = selected_layer.get("commonPlaceholders")
    if not isinstance(common, Mapping):
        return
    for key, value in common.items():
        if key != "filters":
            data[key] = copy.deepcopy(value)


def _finalize_geolayer_selected_layer_fields(data: dict[str, object]) -> None:
    """Remove defaults that the selected live geo-layer contract does not support."""
    visualization = data.get("visualization")
    if not isinstance(visualization, Mapping):
        return
    layers = visualization.get("layers")
    selected_layer_id = visualization.get("selectedLayerId")
    if not isinstance(layers, list) or not isinstance(selected_layer_id, str):
        return
    for layer in layers:
        if not isinstance(layer, Mapping):
            continue
        settings = layer.get("layerSettings")
        if isinstance(settings, Mapping) and settings.get("id") == selected_layer_id:
            if layer.get("id") == "polyline":
                data.pop("segments", None)
            return
