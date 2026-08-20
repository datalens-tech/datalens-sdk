from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any, cast

from datalens_sdk._runtime.chart_constants import (
    DEFAULT_CATEGORICAL_PALETTE,
    VALID_DISCRETE_PALETTES,
    VALID_GRADIENT_PALETTES,
    gradient_types_for_palette,
)
from datalens_sdk._runtime.wizard_semantics import (
    get_wizard_encoding,
    get_wizard_visualization_semantics,
)
from datalens_sdk._runtime.wizard_structure import (
    WizardFieldStructure,
    WizardSlotStructure,
    WizardVisualizationRegistry,
)
from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
from datalens_sdk.converter.wizard._normalizer import (
    _dataset_of,
    _hierarchies_map,
    _local_fields_map,
    _Normalizer,
)
from datalens_sdk.converter.wizard._types import (
    CombinedLayerSettingsV1,
    GeoLayerSettingsV1,
    WizardConfigV1,
    WizardJsonObject,
    WizardSourcesV1,
)
from datalens_sdk.domain.chart_types import MeasureFormat
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object, normalize_json_value

# Encoding changes clear only the settings owned by the SDK operation. The
# generated registry remains authoritative for which settings the contract
# supports; _assert_encoding_owned_setting_keys_are_generated binds these
# policy subsets to that registry.
_COLOR_ENCODING_OWNED_SETTING_KEYS = frozenset(
    {
        "colorMode",
        "coloredByMeasure",
        "fieldGuid",
        "gradientMode",
        "gradientPalette",
        "leftThreshold",
        "middleThreshold",
        "mountedColors",
        "nullMode",
        "palette",
        "polygonBorders",
        "reversed",
        "rightThreshold",
        "thresholdsMode",
    }
)
# Shape ownership is intentionally narrower than the full generated shape
# settings carrier: unknown and server-owned shape settings must survive an
# encoding change.
_SHAPE_ENCODING_OWNED_SETTING_KEYS = frozenset({"fieldGuid", "mountedShapes"})
_MEASURE_NAMES_ITEM: WizardJsonObject = {
    "title": "Measure Names",
    "type": "PSEUDO",
    "data_type": "string",
}
_REFERENCE_ONLY_SLOT_NAMES = frozenset({"filters", "sort"})
_GEO_INPUT_SLOT_ALIASES: dict[str, str] = {
    "color": "colors",
    "filters": "filters",
    "geopoint": "points",
    "grouping": "grouping",
    "labels": "labels",
    "polygon": "polygons",
    "polyline": "polylines",
    "size": "size",
    "sort_by": "sort",
    "tooltips": "tooltip",
}
_X_SETTINGS: WizardJsonObject = {
    "axisFormatMode": "auto",
    "axisLabelDateFormat": "DD.MM.YYYY",
    "axisModeMap": {},
    "axisVisibility": "show",
    "grid": "on",
    "gridStep": "auto",
    "gridStepValue": 50,
    "hideLabels": "no",
    "holidays": "off",
    "labelsView": "auto",
    "title": "off",
    "titleValue": "",
    "type": "linear",
}
_Y_SETTINGS: WizardJsonObject = {
    "axisFormatMode": "auto",
    "axisLabelDateFormat": "DD.MM.YYYY",
    "axisVisibility": "show",
    "grid": "on",
    "gridStep": "auto",
    "gridStepValue": 50,
    "hideLabels": "no",
    "labelsView": "auto",
    "nulls": "connect",
    "scale": "auto",
    "scaleValue": "min-max",
    "title": "off",
    "titleValue": "",
    "type": "linear",
}
_SCATTER_AXIS_SETTINGS: WizardJsonObject = {
    "axisFormatMode": "auto",
    "axisLabelDateFormat": "DD.MM.YYYY",
    "axisModeMap": {},
    "axisVisibility": "show",
    "grid": "on",
    "gridStep": "auto",
    "gridStepValue": 50,
    "hideLabels": "no",
    "labelsView": "auto",
    "scale": "auto",
    "scaleValue": "min-max",
    "title": "off",
    "titleValue": "",
    "type": "linear",
}


def _visualization_type(visualization: Mapping[str, object]) -> str:
    value = visualization.get("type")
    if not isinstance(value, str):
        raise DataLensConfigurationError("Wizard V1 visualization requires a string type discriminator.")
    return value


def _visualization_slots(
    visualization_type: str,
    structure: WizardVisualizationRegistry,
) -> tuple[str, ...]:
    raw = structure.get(visualization_type)
    slots = raw.get("slots") if isinstance(raw, Mapping) else None
    if isinstance(slots, Mapping) and all(isinstance(name, str) for name in slots):
        return tuple(sorted(slots))
    raise DataLensConfigurationError(
        f"Wizard V1 generated structure has no slots registry for visualization {visualization_type!r}."
    )


def _chart_setting_names(
    visualization_type: str,
    structure: WizardVisualizationRegistry,
) -> frozenset[str] | None:
    raw = structure.get(visualization_type)
    settings = raw.get("chart_settings") if isinstance(raw, Mapping) else None
    if not isinstance(settings, Mapping) or not all(isinstance(name, str) for name in settings):
        return None
    return frozenset(settings)


def _slot_setting_names(
    visualization_type: str,
    slot_name: str,
    structure: WizardVisualizationRegistry,
) -> frozenset[str] | None:
    raw = structure.get(visualization_type)
    slots = raw.get("slots") if isinstance(raw, Mapping) else None
    slot = slots.get(slot_name) if isinstance(slots, Mapping) else None
    settings = slot.get("settings") if isinstance(slot, Mapping) else None
    if not isinstance(settings, Mapping) or not all(isinstance(name, str) for name in settings):
        return None
    return frozenset(settings)


def _assert_encoding_owned_setting_keys_are_generated(
    structure: WizardVisualizationRegistry,
) -> None:
    """Bind handwritten encoding ownership policy to generated carriers."""
    owned_setting_keys = {
        "colors": _COLOR_ENCODING_OWNED_SETTING_KEYS,
        "shapes": _SHAPE_ENCODING_OWNED_SETTING_KEYS,
    }
    for visualization_type, visualization in structure.items():
        carriers: list[tuple[str | None, dict[str, WizardSlotStructure]]] = [(None, visualization["slots"])]
        carriers.extend((layer_type, layer["slots"]) for layer_type, layer in visualization["layers"].items())
        for layer_type, slots in carriers:
            carrier = f"visualization {visualization_type!r}"
            if layer_type is not None:
                carrier += f" layer {layer_type!r}"
            for slot_name, owned_keys in owned_setting_keys.items():
                slot = slots.get(slot_name)
                if slot is None:
                    continue
                missing_keys = owned_keys - set(slot["settings"])
                if missing_keys:
                    raise DataLensConfigurationError(
                        f"Generated Wizard {carrier} slot {slot_name!r} settings are missing SDK-owned keys: "
                        f"{sorted(missing_keys)!r}."
                    )


def _validate_structural_settings(
    edits: Mapping[str, object],
    structure: object,
    *,
    context: str,
) -> None:
    if not edits:
        return
    if not isinstance(structure, Mapping):
        names = ", ".join(sorted(edits))
        raise DataLensConfigurationError(f"{context} does not support settings: {names}.")
    unsupported = set(edits) - set(structure)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise DataLensConfigurationError(f"{context} does not support settings: {names}.")
    for setting_name, value in edits.items():
        setting = structure.get(setting_name)
        enum = setting.get("enum") if isinstance(setting, Mapping) else None
        if isinstance(enum, list) and value not in enum:
            raise DataLensConfigurationError(f"{context}.{setting_name} must be one of {enum!r}; got {value!r}.")


def _chart_settings_structure(
    visualization_type: str,
    structure: WizardVisualizationRegistry,
) -> object:
    raw = structure.get(visualization_type)
    return raw.get("chart_settings") if isinstance(raw, Mapping) else None


def _slot_settings_structure(
    visualization_type: str,
    slot_name: str,
    structure: WizardVisualizationRegistry,
) -> object:
    raw = structure.get(visualization_type)
    slots = raw.get("slots") if isinstance(raw, Mapping) else None
    slot = slots.get(slot_name) if isinstance(slots, Mapping) else None
    return slot.get("settings") if isinstance(slot, Mapping) else None


def _default_slot_settings(visualization_type: str, slot_name: str) -> WizardJsonObject | None:
    if visualization_type in {"line", "column", "column100p", "area", "area100p"}:
        if slot_name == "x":
            return dict(_X_SETTINGS)
        if slot_name in {"y", "y2"}:
            return dict(_Y_SETTINGS)
    if visualization_type in {"bar", "bar100p"}:
        if slot_name == "y":
            settings = dict(_X_SETTINGS)
            settings.pop("holidays", None)
            return settings
        if slot_name == "x":
            return dict(_Y_SETTINGS)
    if visualization_type == "scatter" and slot_name in {"x", "y"}:
        settings = dict(_SCATTER_AXIS_SETTINGS)
        if slot_name == "x":
            settings["holidays"] = "off"
        return settings
    if slot_name in {"colors", "shapes", "size"}:
        return {}
    return None


def _json_object(value: Mapping[str, object], *, context: str) -> WizardJsonObject:
    return normalize_json_object(value, context=context)


def _json_array(value: object, *, context: str) -> list[JsonValue]:
    normalized = normalize_json_value(value, context=context)
    if not isinstance(normalized, list):
        raise AssertionError(f"{context} was narrowed to an array")
    return normalized


def _project_update_field(snapshot: Mapping[str, object], *, normalizer: _Normalizer) -> dict[str, object]:
    return {
        key: value
        for key, value in snapshot.items()
        if key in normalizer.update_field_properties
        and (value is not None or key in normalizer.nullable_update_field_properties)
    }


def _without_field_decorations(item: WizardJsonObject, *, normalizer: _Normalizer) -> WizardJsonObject:
    return {key: value for key, value in item.items() if key not in normalizer.direct_field_properties}


def _validate_create_semantic_guids(
    *,
    dataset: Dataset | None,
    local_fields: Sequence[Mapping[str, object]],
    hierarchies: Sequence[Mapping[str, object]],
) -> None:
    registrations: dict[str, str] = {}

    def register(guid: object, owner: str) -> None:
        if not isinstance(guid, str) or not guid:
            raise DataLensValidationError(f"{owner} requires a non-empty semantic GUID.")
        previous = registrations.get(guid)
        if previous is not None:
            raise DataLensValidationError(
                f"Wizard semantic GUID {guid!r} is registered by both {previous} and {owner}. "
                "Use a distinct stable GUID for every dataset parameter, chart-local field, and hierarchy."
            )
        registrations[guid] = owner

    if dataset is not None:
        for dataset_field in dataset.fields:
            kind = "dataset parameter" if dataset_field.calc_mode == "parameter" else "dataset field"
            register(dataset_field.guid, f"{kind} {dataset_field.title!r}")
    for local_field in local_fields:
        register(local_field.get("guid"), f"chart-local field {local_field.get('title')!r}")
    for hierarchy in hierarchies:
        register(hierarchy.get("guid"), f"hierarchy {hierarchy.get('title')!r}")


def _project_field(
    snapshot: Mapping[str, object],
    *,
    dataset_id: str | None,
    normalizer: _Normalizer,
) -> WizardJsonObject:
    decorations = {key: snapshot[key] for key in normalizer.direct_field_properties if key in snapshot}
    if snapshot.get("data_type") == "hierarchy":
        fields: list[WizardJsonObject] = []
        nested = snapshot.get("fields")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
            for item in nested:
                if not isinstance(item, Mapping):
                    continue
                guid = item.get("guid")
                item_dataset_id = item.get("datasetId") or dataset_id
                if isinstance(guid, str) and isinstance(item_dataset_id, str):
                    fields.append({"guid": guid, "datasetId": item_dataset_id})
        hierarchy = {
            **decorations,
            "guid": snapshot.get("guid"),
            "title": snapshot.get("title"),
            "data_type": "hierarchy",
            "fields": fields,
        }
        return _json_object(hierarchy, context="Wizard hierarchy field")

    if snapshot.get("type") == "PSEUDO":
        pseudo = {
            **decorations,
            "title": snapshot.get("title"),
            "type": "PSEUDO",
            "data_type": snapshot.get("data_type"),
        }
        return _json_object(pseudo, context="Wizard pseudo field")

    guid = snapshot.get("guid")
    field_dataset_id = snapshot.get("datasetId") or dataset_id
    if not isinstance(guid, str) or not isinstance(field_dataset_id, str):
        raise DataLensConfigurationError("Wizard field requires string guid and datasetId.")
    return _json_object(
        {**decorations, "guid": guid, "datasetId": field_dataset_id},
        context="Wizard field",
    )


def _normalize_fields(
    normalizer: _Normalizer,
    refs: Sequence[object],
    *,
    dataset_id: str | None,
) -> list[WizardJsonObject]:
    return [
        _project_field(item, dataset_id=dataset_id, normalizer=normalizer)
        for item in normalizer.normalize(refs)  # type: ignore[arg-type]
    ]


def _slot(items: list[WizardJsonObject], *, settings: WizardJsonObject | None = None) -> WizardJsonObject:
    result: dict[str, object] = {"items": items}
    if settings is not None:
        result["settings"] = settings
    return _json_object(result, context="Wizard slot")


def _layer_structures(
    visualization_type: str,
    structure: WizardVisualizationRegistry,
) -> Mapping[str, object] | None:
    raw = structure.get(visualization_type)
    layers = raw.get("layers") if isinstance(raw, Mapping) else None
    return layers if isinstance(layers, Mapping) else None


def _layer_structure(
    visualization_type: str,
    layer_type: str,
    structure: WizardVisualizationRegistry,
) -> Mapping[str, object]:
    layers = _layer_structures(visualization_type, structure)
    layer = layers.get(layer_type) if layers is not None else None
    if not isinstance(layer, Mapping):
        raise DataLensConfigurationError(
            f"Wizard V1 generated structure has no {visualization_type!r} layer {layer_type!r}."
        )
    return layer


def _layer_slot_names(
    visualization_type: str,
    layer_type: str,
    structure: WizardVisualizationRegistry,
) -> tuple[str, ...]:
    layer = _layer_structure(visualization_type, layer_type, structure)
    slots = layer.get("slots") if isinstance(layer, Mapping) else None
    if isinstance(slots, Mapping) and all(isinstance(name, str) for name in slots):
        return tuple(sorted(slots))
    raise DataLensConfigurationError(
        f"Wizard V1 generated structure has no slots registry for {visualization_type!r} layer {layer_type!r}."
    )


def _is_layered_visualization(
    visualization_type: str,
    structure: WizardVisualizationRegistry,
) -> bool:
    layers = _layer_structures(visualization_type, structure)
    return bool(layers)


def _layer_slot_settings_structure(
    visualization_type: str,
    layer_type: str,
    slot_name: str,
    structure: WizardVisualizationRegistry,
) -> object:
    layer = _layer_structure(visualization_type, layer_type, structure)
    slots = layer.get("slots") if isinstance(layer, Mapping) else None
    slot = slots.get(slot_name) if isinstance(slots, Mapping) else None
    return slot.get("settings") if isinstance(slot, Mapping) else None


def _new_layer(
    visualization_type: str,
    layer_type: str,
    layer_settings: Mapping[str, object],
    structure: WizardVisualizationRegistry,
) -> WizardJsonObject:
    layer: WizardJsonObject = {
        "type": layer_type,
        "layerSettings": _json_object(layer_settings, context=f"Wizard {visualization_type} layer settings"),
    }
    for slot_name in _layer_slot_names(visualization_type, layer_type, structure):
        settings = _default_slot_settings(layer_type, slot_name) if visualization_type == "combined-chart" else None
        if visualization_type == "geolayer" and layer_type == "polyline" and slot_name == "polylines":
            settings = {"polylinePoints": "off"}
        layer[slot_name] = _slot([], settings=settings)
    return layer


def _selected_layer(visualization: WizardJsonObject) -> WizardJsonObject:
    layers = visualization.get("layers")
    if not isinstance(layers, list) or not layers:
        raise DataLensConfigurationError("Wizard layered visualization requires at least one layer.")
    if "selectedLayerId" not in visualization:
        last = layers[-1]
        if not isinstance(last, dict):
            raise DataLensConfigurationError("Wizard visualization.layers must contain objects.")
        return last

    selected_id = visualization["selectedLayerId"]
    if not isinstance(selected_id, str) or not selected_id:
        raise DataLensConfigurationError("Wizard visualization.selectedLayerId must be a non-empty string.")
    matches: list[WizardJsonObject] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        settings = layer.get("layerSettings")
        if isinstance(settings, Mapping) and settings.get("id") == selected_id:
            matches.append(layer)
    if len(matches) != 1:
        raise DataLensConfigurationError(
            "Wizard visualization.selectedLayerId must match exactly one layerSettings.id; "
            f"got {selected_id!r} with {len(matches)} matches."
        )
    return matches[0]


def _layer_slot(layer: WizardJsonObject, slot_name: str) -> WizardJsonObject:
    value = layer.get(slot_name)
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        layer_type = layer.get("type")
        raise DataLensConfigurationError(
            f"Wizard V1 layer {layer_type!r} requires an object-valued {slot_name!r} slot."
        )
    return value


def _filter_item(
    normalizer: _Normalizer,
    ref: object,
    operation: str,
    values: Sequence[str],
    *,
    dataset_id: str | None,
) -> WizardJsonObject:
    item = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0]
    filter_value: WizardJsonObject = {"operation": {"code": operation}}
    if values:
        filter_value["value"] = list(values)
    result: WizardJsonObject = {
        "guid": item["guid"],
        "datasetId": item["datasetId"],
        "filter": filter_value,
    }
    if "fakeTitle" in item:
        result["fakeTitle"] = item["fakeTitle"]
    return result


def _field_guid(ref: object, normalizer: _Normalizer, *, dataset_id: str | None) -> str:
    fields = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)
    guid = fields[0].get("guid") if fields else None
    if not isinstance(guid, str):
        raise DataLensConfigurationError("Wizard field reference has no guid.")
    return guid


def _encoding_settings(
    slot: WizardJsonObject,
    *,
    owned_keys: frozenset[str],
) -> WizardJsonObject:
    current = slot.get("settings")
    settings = dict(current) if isinstance(current, dict) else {}
    for key in owned_keys:
        settings.pop(key, None)
    slot["settings"] = settings
    return settings


def _placed_measure_guids(visualization: WizardJsonObject) -> list[str]:
    guids: list[str] = []
    visualization_type = _visualization_type(visualization)
    rule = get_wizard_encoding(visualization_type, "color", "measure_name") or get_wizard_encoding(
        visualization_type,
        "shape",
        "measure_name",
    )
    for slot_name in rule.get("measure_slots", ()) if rule is not None else ():
        slot = visualization.get(slot_name)
        if not isinstance(slot, dict):
            continue
        items = slot.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            guid = item.get("guid") if isinstance(item, Mapping) else None
            if isinstance(guid, str) and guid and guid not in guids:
                guids.append(guid)
    return guids


def _measure_mapping(
    visualization: WizardJsonObject,
    values: Mapping[Any, str],
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
    method_name: str,
    defaults: bool,
) -> dict[str, str]:
    measure_guids = _placed_measure_guids(visualization)
    if len(measure_guids) < 2:
        raise DataLensConfigurationError(f"{method_name}() requires at least two measures across the y and y2 slots.")
    mounted: dict[str, str] = {guid: str(index) for index, guid in enumerate(measure_guids)} if defaults else {}
    for ref, value in values.items():
        guid = _field_guid(ref, normalizer, dataset_id=dataset_id)
        if guid not in measure_guids:
            raise DataLensConfigurationError(
                f"{method_name}(...): field {ref!r} is not placed as a measure in the y or y2 slot."
            )
        mounted[guid] = value
    return mounted


def _validate_measure_colors(colors: Mapping[Any, str]) -> None:
    for color in colors.values():
        if not isinstance(color, str) or (
            re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", color) is None and not color.isdigit()
        ):
            raise DataLensConfigurationError(
                "color_by_measure_name(colors_map=...): colors must be #RRGGBB or #RRGGBBAA values "
                "or non-negative palette indexes."
            )


def _apply_palette(
    settings: WizardJsonObject,
    palette: str,
    *,
    color_types: frozenset[str],
) -> None:
    if not color_types:
        raise DataLensConfigurationError(f"palette(id={palette!r}) requires a field in the colors slot.")
    if palette in VALID_DISCRETE_PALETTES:
        if not color_types <= {"DIMENSION", "PSEUDO"}:
            got = ", ".join(sorted(color_types))
            raise DataLensConfigurationError(
                f"palette(id={palette!r}) requires a DIMENSION (or PSEUDO Measure Names) in colors; got {got}."
            )
        settings.pop("gradientMode", None)
        settings.pop("gradientPalette", None)
        if settings.get("colorMode") == "gradient":
            settings["colorMode"] = "palette"
    elif palette in VALID_GRADIENT_PALETTES:
        if color_types != {"MEASURE"}:
            got = ", ".join(sorted(color_types))
            raise DataLensConfigurationError(f"palette(id={palette!r}) requires a MEASURE in colors; got {got}.")
        gradient_types = gradient_types_for_palette(palette)
        gradient_mode = "2-point" if "2-point" in gradient_types else "3-point"
        settings["colorMode"] = "gradient"
        settings["gradientMode"] = gradient_mode
        settings["gradientPalette"] = palette
        settings["thresholdsMode"] = "auto"
    else:
        raise DataLensConfigurationError(f"Unknown palette {palette!r}.")
    settings["palette"] = palette


def _color_item_types(
    slot: WizardJsonObject,
    *,
    normalizer: _Normalizer,
) -> frozenset[str]:
    result: set[str] = set()
    items = slot.get("items")
    if not isinstance(items, list):
        return frozenset()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if not isinstance(item_type, str):
            guid = item.get("guid")
            if isinstance(guid, str):
                normalized = normalizer.normalize([guid])
                normalized_type = normalized[0].get("type") if normalized else None
                item_type = normalized_type if isinstance(normalized_type, str) else None
        if isinstance(item_type, str):
            result.add(item_type)
    if not result and items:
        settings = slot.get("settings")
        if isinstance(settings, Mapping):
            if settings.get("coloredByMeasure") is True:
                result.add("PSEUDO")
            elif isinstance(settings.get("fieldGuid"), str):
                result.add("MEASURE")
            else:
                result.add("DIMENSION")
    return frozenset(result)


def _apply_palette_to_visualization(
    visualization: WizardJsonObject,
    palette: str,
    *,
    normalizer: _Normalizer,
) -> None:
    colors = _ensure_visualization_slot(visualization, "colors", settings={})
    current = colors.get("settings")
    settings = dict(current) if isinstance(current, dict) else {}
    _apply_palette(settings, palette, color_types=_color_item_types(colors, normalizer=normalizer))
    colors["settings"] = settings


def _sync_axis_modes(slot: WizardJsonObject, normalized_items: Sequence[Mapping[str, object]]) -> None:
    current = slot.get("settings")
    settings = dict(current) if isinstance(current, dict) else {}
    current_modes = settings.get("axisModeMap")
    modes = dict(current_modes) if isinstance(current_modes, dict) else {}
    active_guids = {guid for item in normalized_items if isinstance((guid := item.get("guid")), str) and guid}
    modes = {key: value for key, value in modes.items() if key in active_guids}
    for item in normalized_items:
        if item.get("type") != "DIMENSION":
            continue
        guid = item.get("guid")
        data_type = str(item.get("data_type") or "").lower()
        if isinstance(guid, str) and (data_type.startswith("date") or "datetime" in data_type):
            modes.setdefault(guid, "continuous")
    settings["axisModeMap"] = modes
    slot["settings"] = settings


def _visualization_slot(visualization: WizardJsonObject, slot_name: str) -> WizardJsonObject:
    value = visualization.get(slot_name)
    if not isinstance(value, dict):
        visualization_type = _visualization_type(visualization)
        raise DataLensConfigurationError(
            f"Wizard V1 visualization {visualization_type!r} requires an object-valued {slot_name!r} slot."
        )
    items = value.get("items")
    if not isinstance(items, list):
        raise DataLensConfigurationError(f"Wizard V1 visualization.{slot_name}.items must be an array.")
    return value


def _ensure_visualization_slot(
    visualization: WizardJsonObject,
    slot_name: str,
    *,
    settings: WizardJsonObject | None = None,
) -> WizardJsonObject:
    if visualization.get(slot_name) is None:
        visualization[slot_name] = _slot([], settings=settings)
    return _visualization_slot(visualization, slot_name)


def _apply_implicit_measure_names(visualization: WizardJsonObject) -> None:
    visualization_type = _visualization_type(visualization)
    rule = get_wizard_encoding(visualization_type, "color", "measure_name")
    if rule is None:
        return
    target = _ensure_visualization_slot(visualization, rule["slot"], settings={})
    if target.get("items") or len(_placed_measure_guids(visualization)) < 2:
        return
    target["items"] = [dict(_MEASURE_NAMES_ITEM)]


def _apply_label_mode(visualization: WizardJsonObject, mode: str | None) -> None:
    if mode is None:
        return
    labels = _visualization_slot(visualization, "labels")
    items = labels.get("items")
    if not isinstance(items, list) or not items:
        raise DataLensConfigurationError("label_mode() requires at least one field in the labels slot.")
    for item in items:
        if not isinstance(item, dict):
            continue
        current = item.get("formatting")
        formatting = current if isinstance(current, dict) else {}
        formatting["labelMode"] = mode
        item["formatting"] = formatting


def _apply_labels_position(visualization: WizardJsonObject, mode: str | None) -> None:
    if mode is None:
        return
    visualization_type = _visualization_type(visualization)
    setting_name = {"bar": "labelsPosition", "column": "labelsPosition", "funnel": "position"}.get(visualization_type)
    if setting_name is None:
        raise DataLensConfigurationError(
            f"labels_position() is not supported for Wizard V1 visualization {visualization_type!r}."
        )
    labels = _visualization_slot(visualization, "labels")
    items = labels.get("items")
    if not isinstance(items, list) or not items:
        raise DataLensConfigurationError("labels_position() requires at least one field in the labels slot.")
    current = labels.get("settings")
    settings = current if isinstance(current, dict) else {}
    if mode == "auto":
        settings.pop(setting_name, None)
    else:
        settings[setting_name] = mode
    labels["settings"] = settings


def _apply_color_encoding(
    visualization: WizardJsonObject,
    encoding: WizardColorEncoding,
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
    palette: str | None,
) -> None:
    visualization_type = _visualization_type(visualization)
    rule = get_wizard_encoding(visualization_type, "color", encoding.kind)
    if rule is None:
        raise DataLensConfigurationError(
            f"color_by_{encoding.kind}() is not supported for Wizard V1 visualization {visualization_type!r}."
        )
    colors = _ensure_visualization_slot(visualization, rule["slot"], settings={})
    settings = _encoding_settings(colors, owned_keys=_COLOR_ENCODING_OWNED_SETTING_KEYS)
    items: list[WizardJsonObject]
    if encoding.kind == "measure_name":
        _validate_measure_colors(encoding.colors_map)
        mounted = _measure_mapping(
            visualization,
            encoding.colors_map,
            normalizer=normalizer,
            dataset_id=dataset_id,
            method_name="color_by_measure_name",
            defaults=True,
        )
        items = [dict(_MEASURE_NAMES_ITEM)]
        settings.update(
            {
                "coloredByMeasure": True,
                "colorMode": "palette",
                "mountedColors": _json_object(mounted, context="Wizard mounted colors"),
                "polygonBorders": "show",
            }
        )
        color_types = frozenset({"PSEUDO"})
    else:
        if encoding.field is None:
            raise DataLensConfigurationError(f"color_by_{encoding.kind}() requires a field.")
        normalized = normalizer.normalize([encoding.field])
        expected_type = "DIMENSION" if encoding.kind == "dimension" else "MEASURE"
        if not normalized or normalized[0].get("type") != expected_type:
            raise DataLensConfigurationError(f"color_by_{encoding.kind}() requires a {expected_type} field.")
        items = [_project_field(normalized[0], dataset_id=dataset_id, normalizer=normalizer)]
        color_types = frozenset({expected_type})
        if encoding.kind == "measure":
            settings["fieldGuid"] = items[0]["guid"]
            has_gradient_settings = any(
                value is not None for value in (encoding.gradient_mode, encoding.gradient_palette, encoding.reversed)
            )
            gradient_mode = encoding.gradient_mode
            if encoding.gradient_palette is not None:
                settings["gradientPalette"] = encoding.gradient_palette
                if gradient_mode is None:
                    gradient_types = gradient_types_for_palette(encoding.gradient_palette)
                    gradient_mode = "2-point" if "2-point" in gradient_types else "3-point"
            if has_gradient_settings:
                settings["colorMode"] = "gradient"
                settings["gradientMode"] = gradient_mode or "2-point"
                settings["reversed"] = encoding.reversed if encoding.reversed is not None else False
                settings["thresholdsMode"] = "auto"
        elif palette is None:
            settings["palette"] = DEFAULT_CATEGORICAL_PALETTE
    if palette is not None:
        _apply_palette(settings, palette, color_types=color_types)
    colors["items"] = _json_array(items, context="Wizard colors items")


def _apply_shape_encoding(
    visualization: WizardJsonObject,
    encoding: WizardShapeEncoding,
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
) -> None:
    visualization_type = _visualization_type(visualization)
    rule = get_wizard_encoding(visualization_type, "shape", encoding.kind)
    if rule is None:
        raise DataLensConfigurationError(
            f"shape_by_{encoding.kind}() is not supported for Wizard V1 visualization {visualization_type!r}."
        )
    shapes = _ensure_visualization_slot(visualization, rule["slot"], settings={})
    settings = _encoding_settings(shapes, owned_keys=_SHAPE_ENCODING_OWNED_SETTING_KEYS)
    items: list[WizardJsonObject]
    if encoding.kind == "measure_name":
        mounted = _measure_mapping(
            visualization,
            encoding.shapes_map or {},
            normalizer=normalizer,
            dataset_id=dataset_id,
            method_name="shape_by_measure_name",
            defaults=False,
        )
        items = [dict(_MEASURE_NAMES_ITEM)]
        if encoding.shapes_map is not None:
            settings["mountedShapes"] = _json_object(mounted, context="Wizard mounted shapes")
    else:
        if encoding.field is None:
            raise DataLensConfigurationError("shape_by_dimension() requires a field.")
        normalized = normalizer.normalize([encoding.field])
        if not normalized or normalized[0].get("type") != "DIMENSION":
            raise DataLensConfigurationError("shape_by_dimension() requires a DIMENSION field.")
        items = [_project_field(normalized[0], dataset_id=dataset_id, normalizer=normalizer)]
        settings["fieldGuid"] = items[0]["guid"]
        if encoding.shapes_map is not None:
            dimension_shapes: dict[str, str] = {}
            for value, shape in encoding.shapes_map.items():
                if not isinstance(value, str):
                    raise DataLensConfigurationError(
                        "shape_by_dimension(shapes_map=...) keys must be dimension values."
                    )
                dimension_shapes[value] = shape
            settings["mountedShapes"] = _json_object(
                dimension_shapes,
                context="Wizard mounted dimension shapes",
            )
    shapes["items"] = _json_array(items, context="Wizard shapes items")


def _apply_item_mutations(
    visualization: WizardJsonObject,
    mutations: Sequence[tuple[object, str, object]],
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
) -> None:
    for ref, key, value in mutations:
        guid = _field_guid(ref, normalizer, dataset_id=dataset_id)
        target_key = "fakeTitle" if key == "_title_override" else key
        normalized_value = normalize_json_object({"value": value}, context="Wizard item mutation")["value"]
        if target_key == "backgroundSettings":
            if not isinstance(normalized_value, dict):
                raise DataLensConfigurationError("column_background() requires an object-valued background setting.")
            normalized_value = {**normalized_value, "colorFieldGuid": guid}
        matched = False
        for slot in _iter_field_decoration_slots(visualization):
            items = slot.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("guid") == guid:
                    if target_key == "formatting" and isinstance(normalized_value, dict):
                        existing = item.get(target_key)
                        merged = dict(existing) if isinstance(existing, dict) else {}
                        merged.update(normalized_value)
                        item[target_key] = merged
                    else:
                        item[target_key] = normalized_value
                    matched = True
        if not matched:
            raise DataLensConfigurationError(f"Wizard field {guid!r} is not placed in any visualization slot.")


def _iter_field_decoration_slots(visualization: WizardJsonObject) -> Sequence[WizardJsonObject]:
    """Yield presentation slots whose field items own decorations."""
    return [
        slot
        for slot_name, slot in _iter_named_visualization_slots(visualization)
        if slot_name not in _REFERENCE_ONLY_SLOT_NAMES
    ]


def _iter_visualization_slots(visualization: WizardJsonObject) -> Sequence[WizardJsonObject]:
    """Yield every visualization slot, including reference-only carriers."""
    return [slot for _, slot in _iter_named_visualization_slots(visualization)]


def _iter_named_visualization_slots(visualization: WizardJsonObject) -> Sequence[tuple[str, WizardJsonObject]]:
    slots: list[tuple[str, WizardJsonObject]] = []
    for slot_name, value in visualization.items():
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            slots.append((slot_name, value))
    layers = visualization.get("layers")
    if isinstance(layers, list):
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            for slot_name, value in layer.items():
                if isinstance(value, dict) and isinstance(value.get("items"), list):
                    slots.append((slot_name, value))
    return slots


def _apply_measure_formats(
    visualization: WizardJsonObject,
    formats: Sequence[tuple[object, MeasureFormat]],
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
) -> None:
    mutations: list[tuple[object, str, object]] = []
    for ref, value in formats:
        formatting = {"showRankDelimiter" if key == "show_rank_delimiter" else key: item for key, item in value.items()}
        mutations.append((ref, "formatting", formatting))
    _apply_item_mutations(
        visualization,
        mutations,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )


def _apply_visualization_autofix(visualization: WizardJsonObject) -> None:
    visualization_type = _visualization_type(visualization)
    semantics = get_wizard_visualization_semantics(visualization_type)
    autofix = semantics.get("autofix") if semantics is not None else None
    if autofix is not None:
        sort = _visualization_slot(visualization, "sort")
        sort_items = sort.get("items")
        sort_source_items = _visualization_slot(visualization, autofix["sort_from_slot"]).get("items")
        if (
            isinstance(sort_items, list)
            and not sort_items
            and isinstance(sort_source_items, list)
            and sort_source_items
        ):
            item = _json_object(
                cast(Mapping[str, object], sort_source_items[0]),
                context=f"Wizard {visualization_type} sort autofix",
            )
            item["direction"] = autofix["sort_direction"]
            sort["items"] = [item]

        labels = _visualization_slot(visualization, "labels")
        label_items = labels.get("items")
        labels_source_items = _visualization_slot(visualization, autofix["labels_from_slot"]).get("items")
        if (
            isinstance(label_items, list)
            and not label_items
            and isinstance(labels_source_items, list)
            and labels_source_items
        ):
            labels["items"] = [
                _json_object(
                    cast(Mapping[str, object], labels_source_items[0]),
                    context=f"Wizard {visualization_type} labels autofix",
                )
            ]

    rule = get_wizard_encoding(visualization_type, "color", "dimension")
    implicit_from_slot = rule.get("implicit_from_slot") if rule is not None else None
    if rule is not None and implicit_from_slot is not None:
        target = _visualization_slot(visualization, rule["slot"])
        target_items = target.get("items")
        source_items = _visualization_slot(visualization, implicit_from_slot).get("items")
        if isinstance(target_items, list) and not target_items and isinstance(source_items, list) and source_items:
            target["items"] = [
                _json_object(
                    cast(Mapping[str, object], source_items[0]),
                    context=f"Wizard {visualization_type} color autofix",
                )
            ]


def _assemble_combined_visualization(
    spec: WizardChartCreateSpec,
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
    visualization_structure: WizardVisualizationRegistry,
) -> WizardJsonObject:
    if not spec.combined_layers:
        raise DataLensConfigurationError("combined_chart() requires at least one add_layer().")
    x_snapshots = normalizer.normalize(list(spec.slots.get("x", ())))
    x_items = [_project_field(item, dataset_id=dataset_id, normalizer=normalizer) for item in x_snapshots]
    layers: list[WizardJsonObject] = []
    measure_color_index = 0
    for index, layer_input in enumerate(spec.combined_layers, start=1):
        layer_type = layer_input["layer_type"]
        layer_settings: CombinedLayerSettingsV1 = {
            "id": layer_input["id"],
            "name": layer_input["name"] or f"Layer {index}",
        }
        layer = _new_layer(
            "combined-chart",
            layer_type,
            layer_settings,
            visualization_structure,
        )
        x_slot = _layer_slot(layer, "x")
        x_slot["items"] = _json_array(x_items, context="Wizard combined x items")
        x_settings = x_slot.get("settings")
        if isinstance(x_settings, Mapping) and "axisModeMap" in x_settings:
            _sync_axis_modes(x_slot, x_snapshots)

        measure_guids: list[str] = []
        for slot_name in ("y", "y2"):
            ref = layer_input[slot_name]
            if ref is None:
                continue
            if slot_name not in _layer_slot_names("combined-chart", layer_type, visualization_structure):
                raise DataLensConfigurationError(f"Combined layer type {layer_type!r} does not support {slot_name}=.")
            snapshots = normalizer.normalize([ref])
            target = _layer_slot(layer, slot_name)
            target["items"] = _json_array(
                [_project_field(item, dataset_id=dataset_id, normalizer=normalizer) for item in snapshots],
                context=f"Wizard combined {slot_name} items",
            )
            for snapshot in snapshots:
                guid = snapshot.get("guid")
                if isinstance(guid, str):
                    measure_guids.append(guid)
        if measure_guids and "colors" in layer:
            mounted = {guid: str(measure_color_index + offset) for offset, guid in enumerate(measure_guids)}
            measure_color_index += len(measure_guids)
            colors = _layer_slot(layer, "colors")
            colors["items"] = [dict(_MEASURE_NAMES_ITEM)]
            colors["settings"] = _json_object(
                {
                    "colorMode": "palette",
                    "coloredByMeasure": True,
                    "mountedColors": mounted,
                    "palette": DEFAULT_CATEGORICAL_PALETTE,
                    "polygonBorders": "show",
                },
                context="Wizard combined colors settings",
            )
        layers.append(layer)

    visualization: WizardJsonObject = {
        "type": "combined-chart",
        "layers": _json_array(layers, context="Wizard combined layers"),
        "selectedLayerId": spec.combined_layers[-1]["id"],
    }
    selected = _selected_layer(visualization)
    if "labels" in spec.slots:
        labels = _layer_slot(selected, "labels")
        labels["items"] = _json_array(
            _normalize_fields(normalizer, list(spec.slots["labels"]), dataset_id=dataset_id),
            context="Wizard combined labels items",
        )
    if spec.sort_direction_items or spec.slots.get("sort"):
        sort = _layer_slot(selected, "sort")
        sort_items: list[WizardJsonObject] = []
        if spec.sort_direction_items:
            for ref, direction in spec.sort_direction_items:
                item = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0]
                item["direction"] = direction.upper()
                sort_items.append(item)
        else:
            for item in _normalize_fields(normalizer, list(spec.slots["sort"]), dataset_id=dataset_id):
                item["direction"] = "ASC"
                sort_items.append(item)
        sort["items"] = _json_array(sort_items, context="Wizard combined sort items")
    if spec.label_mode is not None:
        _apply_label_mode(selected, spec.label_mode)
    _apply_labels_position(selected, spec.labels_position)
    _apply_item_mutations(
        visualization,
        spec.item_mutations,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )
    _apply_measure_formats(
        visualization,
        spec.pending_measure_formats,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )
    return visualization


def _geo_normalizer(
    spec: WizardChartCreateSpec, dataset: object, *, field_structure: WizardFieldStructure
) -> _Normalizer:
    return _Normalizer(
        dataset=dataset,  # type: ignore[arg-type]
        local_fields=_local_fields_map(spec.local_fields),
        hierarchies=_hierarchies_map(spec.hierarchies),
        field_structure=field_structure,
    )


def _assemble_geo_visualization(
    spec: WizardChartCreateSpec,
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
    visualization_structure: WizardVisualizationRegistry,
) -> WizardJsonObject:
    if not spec.geo_layers:
        raise DataLensConfigurationError("geolayer() requires at least one add_layer().")
    layers: list[WizardJsonObject] = []
    for index, layer_input in enumerate(spec.geo_layers, start=1):
        layer_type = layer_input["layer_type"]
        layer_dataset = layer_input.get("dataset") or spec.dataset
        layer_dataset_id = layer_dataset.id if layer_dataset is not None and layer_dataset.id else dataset_id
        layer_normalizer = (
            _geo_normalizer(spec, layer_dataset, field_structure=normalizer.field_structure)
            if layer_dataset is not None
            else normalizer
        )
        layer_settings: GeoLayerSettingsV1 = {
            "id": layer_input["id"],
            "name": layer_input["name"] or f"Layer {index}",
            "alpha": layer_input["alpha"],
        }
        layer = _new_layer("geolayer", layer_type, layer_settings, visualization_structure)
        layer_structure = _layer_structure("geolayer", layer_type, visualization_structure)
        raw_slots = layer_structure.get("slots")
        if not isinstance(raw_slots, Mapping):
            raise DataLensConfigurationError(
                f"Wizard V1 generated structure has no slots registry for geolayer layer {layer_type!r}."
            )
        supported_slots = frozenset(raw_slots)
        required_slots = frozenset(
            slot_name
            for slot_name, slot_structure in raw_slots.items()
            if isinstance(slot_structure, Mapping) and slot_structure.get("required") is True
        )
        geometry_inputs = [
            input_name
            for input_name in ("geopoint", "polygon", "polyline")
            if _GEO_INPUT_SLOT_ALIASES[input_name] in required_slots
        ]
        if len(geometry_inputs) != 1:
            raise DataLensConfigurationError(
                f"Wizard V1 generated structure for geolayer layer {layer_type!r} must require one geometry slot."
            )
        geometry_input = geometry_inputs[0]
        geometry_slot = _GEO_INPUT_SLOT_ALIASES[geometry_input]
        geometry_ref = cast(Mapping[str, Any], layer_input)[geometry_input]
        if geometry_ref is None:
            raise DataLensConfigurationError(f"Geo layer type {layer_type!r} requires {geometry_input}=.")
        geometry = _layer_slot(layer, geometry_slot)
        geometry["items"] = _json_array(
            _normalize_fields(layer_normalizer, [geometry_ref], dataset_id=layer_dataset_id),
            context=f"Wizard geo {geometry_slot} items",
        )

        for input_name in ("grouping", "size", "color", "tooltips", "labels"):
            slot_name = _GEO_INPUT_SLOT_ALIASES[input_name]
            raw_value = cast(Mapping[str, Any], layer_input)[input_name]
            refs = (
                list(cast(Sequence[Any], raw_value))
                if input_name in {"tooltips", "labels"}
                else ([] if raw_value is None else [raw_value])
            )
            if not refs:
                continue
            if slot_name not in supported_slots:
                raise DataLensConfigurationError(f"Geo layer type {layer_type!r} does not support {input_name}=.")
            snapshots = layer_normalizer.normalize(refs)
            target = _layer_slot(layer, slot_name)
            target["items"] = _json_array(
                [_project_field(item, dataset_id=layer_dataset_id, normalizer=layer_normalizer) for item in snapshots],
                context=f"Wizard geo {slot_name} items",
            )
            if input_name == "labels":
                _apply_label_mode(layer, "absolute")
            if input_name == "color":
                color_type = snapshots[0].get("type") if snapshots else None
                settings: WizardJsonObject = {}
                if color_type == "MEASURE":
                    palette = layer_input["color_palette"]
                    mode = layer_input["color_mode"]
                    if palette is not None and mode is None:
                        gradient_types = gradient_types_for_palette(palette)
                        mode = "2-point" if "2-point" in gradient_types else "3-point"
                    target_items = target.get("items")
                    if not isinstance(target_items, list) or not target_items or not isinstance(target_items[0], dict):
                        raise DataLensConfigurationError("Wizard geo colors require a projected field item.")
                    settings.update(
                        {
                            "colorMode": "gradient",
                            "fieldGuid": target_items[0]["guid"],
                            "gradientMode": mode or "2-point",
                            "gradientPalette": palette or "orange-gray-blue",
                            "polygonBorders": "show",
                            "reversed": layer_input["color_reversed"] or False,
                            "thresholdsMode": "auto",
                        }
                    )
                target["settings"] = settings

        if layer_input["filters"]:
            if "filters" not in supported_slots:
                raise DataLensConfigurationError(f"Geo layer type {layer_type!r} does not support filters=.")
            filters = _layer_slot(layer, "filters")
            filters["items"] = [
                _filter_item(
                    layer_normalizer,
                    item.field,
                    item.operation,
                    item.values,
                    dataset_id=layer_dataset_id,
                )
                for item in layer_input["filters"]
            ]
        if layer_input["sort_by"] is not None:
            if "sort" not in supported_slots:
                raise DataLensConfigurationError(f"Geo layer type {layer_type!r} does not support sort_by=.")
            sort = _layer_slot(layer, "sort")
            item = _normalize_fields(layer_normalizer, [layer_input["sort_by"]], dataset_id=layer_dataset_id)[0]
            item["direction"] = layer_input["sort_direction"].upper()
            sort["items"] = [item]
        layers.append(layer)

    visualization: WizardJsonObject = {
        "type": "geolayer",
        "layers": _json_array(layers, context="Wizard geo layers"),
        "selectedLayerId": spec.geo_layers[-1]["id"],
    }
    selected = _selected_layer(visualization)
    selected_input = spec.geo_layers[-1]
    selected_dataset = selected_input.get("dataset") or spec.dataset
    selected_dataset_id = selected_dataset.id if selected_dataset is not None and selected_dataset.id else dataset_id
    selected_normalizer = (
        _geo_normalizer(spec, selected_dataset, field_structure=normalizer.field_structure)
        if selected_dataset is not None
        else normalizer
    )
    if "labels" in spec.slots:
        if "labels" not in selected:
            raise DataLensConfigurationError(f"Geo layer type {selected.get('type')!r} does not support labels().")
        labels = _layer_slot(selected, "labels")
        labels["items"] = _json_array(
            _normalize_fields(selected_normalizer, list(spec.slots["labels"]), dataset_id=selected_dataset_id),
            context="Wizard geo labels items",
        )
        if labels["items"]:
            _apply_label_mode(selected, "absolute")
    _apply_item_mutations(
        visualization,
        spec.item_mutations,
        normalizer=selected_normalizer,
        dataset_id=selected_dataset_id,
    )
    _apply_measure_formats(
        visualization,
        spec.pending_measure_formats,
        normalizer=selected_normalizer,
        dataset_id=selected_dataset_id,
    )
    return visualization


def _assemble_root_filters(
    spec: WizardChartCreateSpec,
    *,
    normalizer: _Normalizer,
    dataset_id: str | None,
) -> list[WizardJsonObject]:
    return [
        _filter_item(normalizer, ref, operation, values, dataset_id=dataset_id)
        for ref, operation, values in spec.pending_filters
    ]


def _assemble_wizard_data(
    spec: WizardChartCreateSpec,
    *,
    visualization_structure: WizardVisualizationRegistry,
    field_structure: WizardFieldStructure,
) -> WizardConfigV1:
    if spec.visualization_type not in visualization_structure:
        raise DataLensConfigurationError(
            f"Wizard V1 generated structure has no visualization {spec.visualization_type!r}."
        )
    visualization_type = spec.visualization_type
    allowed_slots = _visualization_slots(visualization_type, visualization_structure)

    dataset = _dataset_of(spec.dataset)
    dataset_ids = list(dict.fromkeys(spec.dataset_ids))
    if dataset is not None and dataset.id and dataset.id not in dataset_ids:
        dataset_ids.insert(0, dataset.id)
    dataset_id = dataset_ids[0] if dataset_ids else None
    _validate_create_semantic_guids(
        dataset=dataset,
        local_fields=spec.local_fields,
        hierarchies=spec.hierarchies,
    )
    normalizer = _Normalizer(
        dataset=dataset,
        local_fields=_local_fields_map(spec.local_fields),
        hierarchies=_hierarchies_map(spec.hierarchies),
        field_structure=field_structure,
    )

    sources: WizardSourcesV1 = {"datasetsIds": dataset_ids}
    updates: list[WizardJsonObject] = []
    update_guids: set[str] = set()
    if dataset is not None:
        for parameter in dataset.parameters:
            field = _project_update_field(parameter.raw, normalizer=normalizer)
            field.setdefault("guid", parameter.guid)
            field.setdefault("title", parameter.title)
            field.setdefault("calc_mode", "parameter")
            if dataset_id is not None and "datasetId" not in field:
                field["datasetId"] = dataset_id
            guid = field.get("guid")
            if not isinstance(guid, str) or not guid:
                raise DataLensConfigurationError("Wizard dataset parameter requires a non-empty guid.")
            if guid in update_guids:
                continue
            default_value = field.get("default_value")
            if default_value is not None and not isinstance(default_value, (str, int, float, bool)):
                raise DataLensConfigurationError(
                    f"Wizard V1 dataset parameter {guid!r} requires a scalar default_value."
                )
            updates.append(
                _json_object(
                    {"action": "update_field", "field": field},
                    context="Wizard parameter update",
                )
            )
            update_guids.add(guid)
    for local_field in spec.local_fields:
        field = _project_update_field(local_field, normalizer=normalizer)
        if dataset_id is not None and "datasetId" not in field:
            field["datasetId"] = dataset_id
        guid = field.get("guid")
        if isinstance(guid, str) and guid in update_guids:
            continue
        updates.append(_json_object({"action": "add_field", "field": field}, context="Wizard field update"))
        if isinstance(guid, str):
            update_guids.add(guid)
    if updates:
        sources["updates"] = updates

    hierarchies: list[WizardJsonObject] = []
    for hierarchy in spec.hierarchies:
        fields = hierarchy.get("fields")
        hierarchy_refs = list(fields) if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)) else []
        normalized = _normalize_fields(normalizer.for_hierarchy_fields(), hierarchy_refs, dataset_id=dataset_id)
        hierarchies.append(
            _json_object(
                {
                    "guid": hierarchy.get("guid"),
                    "title": hierarchy.get("title"),
                    "fields": [{"guid": item.get("guid"), "datasetId": item.get("datasetId")} for item in normalized],
                },
                context="Wizard hierarchy",
            )
        )
    if hierarchies:
        sources["hierarchies"] = hierarchies

    if _is_layered_visualization(visualization_type, visualization_structure):
        _validate_structural_settings(
            spec.chart_settings,
            _chart_settings_structure(visualization_type, visualization_structure),
            context=f"Wizard V1 visualization {visualization_type!r}",
        )
        if spec.slot_settings:
            names = ", ".join(sorted(spec.slot_settings))
            raise DataLensConfigurationError(
                f"Wizard V1 layered visualization {visualization_type!r} has no top-level slot settings: {names}."
            )
        layered_visualization = (
            _assemble_combined_visualization(
                spec,
                normalizer=normalizer,
                dataset_id=dataset_id,
                visualization_structure=visualization_structure,
            )
            if visualization_type == "combined-chart"
            else _assemble_geo_visualization(
                spec,
                normalizer=normalizer,
                dataset_id=dataset_id,
                visualization_structure=visualization_structure,
            )
        )
        if spec.chart_settings:
            layered_visualization["chartSettings"] = _json_object(spec.chart_settings, context="Wizard chart settings")
        filters = _assemble_root_filters(spec, normalizer=normalizer, dataset_id=dataset_id)
        if filters:
            sources["filters"] = filters
        return {"sources": sources, "visualization": layered_visualization}

    visualization: WizardJsonObject = {"type": visualization_type}
    for slot_name in allowed_slots:
        visualization[slot_name] = _slot(
            [],
            settings=_default_slot_settings(visualization_type, slot_name),
        )

    for slot_name, slot_refs in spec.slots.items():
        if slot_name not in allowed_slots:
            raise DataLensConfigurationError(
                f"Wizard V1 visualization {visualization_type!r} has no {slot_name!r} slot."
            )
        slot_snapshots = normalizer.normalize(list(slot_refs))
        slot = _visualization_slot(visualization, slot_name)
        slot["items"] = _json_array(
            [_project_field(item, dataset_id=dataset_id, normalizer=normalizer) for item in slot_snapshots],
            context=f"Wizard {slot_name} items",
        )
        settings = slot.get("settings")
        if isinstance(settings, Mapping) and "axisModeMap" in settings:
            _sync_axis_modes(slot, slot_snapshots)
    if spec.sort_direction_items:
        if "sort" not in allowed_slots:
            raise DataLensConfigurationError(
                f"Wizard V1 visualization {visualization_type!r} does not support sorting."
            )
        sort_items: list[WizardJsonObject] = []
        for ref, direction in spec.sort_direction_items:
            item = _without_field_decorations(
                _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0],
                normalizer=normalizer,
            )
            item["direction"] = direction.upper()
            sort_items.append(item)
        _visualization_slot(visualization, "sort")["items"] = _json_array(
            sort_items,
            context="Wizard sort items",
        )
    elif spec.slots.get("sort"):
        sort_items = [
            _without_field_decorations(item, normalizer=normalizer)
            for item in _normalize_fields(normalizer, list(spec.slots["sort"]), dataset_id=dataset_id)
        ]
        for item in sort_items:
            item["direction"] = "ASC"
        _visualization_slot(visualization, "sort")["items"] = _json_array(
            sort_items,
            context="Wizard sort items",
        )

    for slot_name, slot_settings in spec.slot_settings.items():
        if slot_name not in allowed_slots:
            raise DataLensConfigurationError(
                f"Wizard V1 visualization {visualization_type!r} has no {slot_name!r} slot."
            )
        _validate_structural_settings(
            slot_settings,
            _slot_settings_structure(visualization_type, slot_name, visualization_structure),
            context=f"Wizard V1 visualization {visualization_type!r} slot {slot_name!r}",
        )
        slot = _visualization_slot(visualization, slot_name)
        current_value = slot.get("settings")
        current = current_value if isinstance(current_value, dict) else {}
        current.update(_json_object(slot_settings, context=f"Wizard {slot_name} settings"))
        slot["settings"] = current

    _validate_structural_settings(
        spec.chart_settings,
        _chart_settings_structure(visualization_type, visualization_structure),
        context=f"Wizard V1 visualization {visualization_type!r}",
    )
    if spec.chart_settings:
        visualization["chartSettings"] = _json_object(spec.chart_settings, context="Wizard chart settings")

    _apply_label_mode(visualization, spec.label_mode)
    _apply_labels_position(visualization, spec.labels_position)

    if spec.color_encoding is None:
        _apply_implicit_measure_names(visualization)
    if spec.color_encoding is not None:
        _apply_color_encoding(
            visualization,
            spec.color_encoding,
            normalizer=normalizer,
            dataset_id=dataset_id,
            palette=spec.colors_palette,
        )
    elif spec.colors_palette is not None:
        _apply_palette_to_visualization(
            visualization,
            spec.colors_palette,
            normalizer=normalizer,
        )
    if spec.shape_encoding is not None:
        _apply_shape_encoding(
            visualization,
            spec.shape_encoding,
            normalizer=normalizer,
            dataset_id=dataset_id,
        )
    if spec.geopoints_config:
        if visualization_type != "scatter":
            raise DataLensConfigurationError(
                f"Wizard V1 visualization {visualization_type!r} has no point-size settings."
            )
        size = _visualization_slot(visualization, "size")
        current_value = size.get("settings")
        size_settings = current_value if isinstance(current_value, dict) else {}
        size_settings.update(_json_object(spec.geopoints_config, context="Wizard scatter size settings"))
        size["settings"] = size_settings

    _apply_visualization_autofix(visualization)

    _apply_item_mutations(
        visualization,
        spec.item_mutations,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )
    _apply_measure_formats(
        visualization,
        spec.pending_measure_formats,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )

    filters = _assemble_root_filters(spec, normalizer=normalizer, dataset_id=dataset_id)
    if filters:
        sources["filters"] = filters

    return {"sources": sources, "visualization": visualization}
