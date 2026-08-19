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
from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
from datalens_sdk.converter.wizard._normalizer import (
    _dataset_of,
    _hierarchies_map,
    _local_fields_map,
    _Normalizer,
)
from datalens_sdk.converter.wizard._types import (
    WizardConfigV1,
    WizardJsonObject,
    WizardSourcesV1,
    WizardVisualizationStructure,
)
from datalens_sdk.domain.chart_types import MeasureFormat
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec
from datalens_sdk.errors import DataLensConfigurationError
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object, normalize_json_value

_LAYERED_VISUALIZATION_TYPES = frozenset({"combined-chart", "geolayer"})
_COLOR_ENCODING_SETTING_KEYS = frozenset(
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
_SHAPE_ENCODING_SETTING_KEYS = frozenset({"fieldGuid", "mountedShapes"})
_MEASURE_NAMES_ITEM: WizardJsonObject = {
    "title": "Measure Names",
    "type": "PSEUDO",
    "data_type": "string",
}
_FIELD_DECORATION_KEYS = frozenset(
    {
        "backgroundSettings",
        "barsSettings",
        "columnSettings",
        "fakeTitle",
        "format",
        "formatting",
        "hideLabelMode",
        "hintSettings",
        "markupType",
        "subTotalsSettings",
    }
)
_UPDATE_FIELD_KEYS = frozenset(
    {
        "aggregation",
        "aggregation_locked",
        "autoaggregated",
        "calc_mode",
        "cast",
        "data_type",
        "datasetId",
        "default_value",
        "fakeTitle",
        "format",
        "formula",
        "guid",
        "local",
        "originalDateCast",
        "originalFormula",
        "originalSource",
        "originalTitle",
        "quickFormula",
        "source",
        "title",
        "type",
        "avatar_id",
        "grouping",
    }
)
_NULLABLE_UPDATE_FIELD_KEYS = frozenset({"default_value", "originalDateCast"})
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
    structure: WizardVisualizationStructure | None,
) -> tuple[str, ...]:
    raw = structure.get(visualization_type) if structure is not None else None
    slots = raw.get("slots") if isinstance(raw, Mapping) else None
    if isinstance(slots, Mapping) and all(isinstance(name, str) for name in slots):
        return tuple(sorted(slots))
    semantics = get_wizard_visualization_semantics(visualization_type)
    return semantics["slots"] if semantics is not None else ()


def _chart_setting_names(
    visualization_type: str,
    structure: WizardVisualizationStructure | None,
) -> frozenset[str] | None:
    raw = structure.get(visualization_type) if structure is not None else None
    settings = raw.get("chart_settings") if isinstance(raw, Mapping) else None
    if not isinstance(settings, Mapping) or not all(isinstance(name, str) for name in settings):
        return None
    return frozenset(settings)


def _slot_setting_names(
    visualization_type: str,
    slot_name: str,
    structure: WizardVisualizationStructure | None,
) -> frozenset[str] | None:
    raw = structure.get(visualization_type) if structure is not None else None
    slots = raw.get("slots") if isinstance(raw, Mapping) else None
    slot = slots.get(slot_name) if isinstance(slots, Mapping) else None
    settings = slot.get("settings") if isinstance(slot, Mapping) else None
    if not isinstance(settings, Mapping) or not all(isinstance(name, str) for name in settings):
        return None
    return frozenset(settings)


def _validate_structural_settings(
    edits: Mapping[str, object],
    structure: object,
    *,
    context: str,
) -> None:
    if not isinstance(structure, Mapping):
        return
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
    structure: WizardVisualizationStructure | None,
) -> object:
    raw = structure.get(visualization_type) if structure is not None else None
    return raw.get("chart_settings") if isinstance(raw, Mapping) else None


def _slot_settings_structure(
    visualization_type: str,
    slot_name: str,
    structure: WizardVisualizationStructure | None,
) -> object:
    raw = structure.get(visualization_type) if structure is not None else None
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


def _project_update_field(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in snapshot.items()
        if key in _UPDATE_FIELD_KEYS and (value is not None or key in _NULLABLE_UPDATE_FIELD_KEYS)
    }


def _project_field(snapshot: Mapping[str, object], *, dataset_id: str | None) -> WizardJsonObject:
    decorations = {key: snapshot[key] for key in _FIELD_DECORATION_KEYS if key in snapshot}
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
    return [_project_field(item, dataset_id=dataset_id) for item in normalizer.normalize(refs)]  # type: ignore[arg-type]


def _slot(items: list[WizardJsonObject], *, settings: WizardJsonObject | None = None) -> WizardJsonObject:
    result: dict[str, object] = {"items": items}
    if settings is not None:
        result["settings"] = settings
    return _json_object(result, context="Wizard slot")


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
    if get_wizard_encoding(visualization_type, "color", "measure_name") is None:
        return
    colors = _ensure_visualization_slot(visualization, "colors", settings={})
    if colors.get("items") or len(_placed_measure_guids(visualization)) < 2:
        return
    colors["items"] = [dict(_MEASURE_NAMES_ITEM)]


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
    colors = _ensure_visualization_slot(visualization, "colors", settings={})
    settings = _encoding_settings(colors, owned_keys=_COLOR_ENCODING_SETTING_KEYS)
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
        items = [_project_field(normalized[0], dataset_id=dataset_id)]
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
    if get_wizard_encoding(visualization_type, "shape", encoding.kind) is None:
        raise DataLensConfigurationError(
            f"shape_by_{encoding.kind}() is not supported for Wizard V1 visualization {visualization_type!r}."
        )
    shapes = _ensure_visualization_slot(visualization, "shapes", settings={})
    settings = _encoding_settings(shapes, owned_keys=_SHAPE_ENCODING_SETTING_KEYS)
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
        items = [_project_field(normalized[0], dataset_id=dataset_id)]
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
        for slot in visualization.values():
            if not isinstance(slot, dict):
                continue
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
    visualization_type = visualization.get("type")
    if visualization_type == "bar":
        sort = _visualization_slot(visualization, "sort")
        sort_items = sort.get("items")
        y_items = _visualization_slot(visualization, "y").get("items")
        if isinstance(sort_items, list) and not sort_items and isinstance(y_items, list) and y_items:
            item = _json_object(
                cast(Mapping[str, object], y_items[0]),
                context="Wizard bar sort autofix",
            )
            item["direction"] = "DESC"
            sort["items"] = [item]

        labels = _visualization_slot(visualization, "labels")
        label_items = labels.get("items")
        x_items = _visualization_slot(visualization, "x").get("items")
        if isinstance(label_items, list) and not label_items and isinstance(x_items, list) and x_items:
            labels["items"] = [
                _json_object(
                    cast(Mapping[str, object], x_items[0]),
                    context="Wizard bar labels autofix",
                )
            ]

    if visualization_type in {"pie", "donut"}:
        colors = _visualization_slot(visualization, "colors")
        color_items = colors.get("items")
        dimensions = _visualization_slot(visualization, "dimensions").get("items")
        if isinstance(color_items, list) and not color_items and isinstance(dimensions, list) and dimensions:
            colors["items"] = [
                _json_object(
                    cast(Mapping[str, object], dimensions[0]),
                    context="Wizard pie colors autofix",
                )
            ]


def _assemble_wizard_data(
    spec: WizardChartCreateSpec,
    *,
    visualization_structure: WizardVisualizationStructure | None = None,
) -> WizardConfigV1:
    semantics = get_wizard_visualization_semantics(spec.visualization_type)
    if semantics is None or spec.visualization_type in _LAYERED_VISUALIZATION_TYPES:
        raise DataLensConfigurationError(
            f"Wizard API v3 phase 3A supports only non-layered visualization creation, got {spec.visualization_type!r}."
        )
    if visualization_structure and spec.visualization_type not in visualization_structure:
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
    normalizer = _Normalizer(
        dataset=dataset,
        local_fields=_local_fields_map(spec.local_fields),
        hierarchies=_hierarchies_map(spec.hierarchies),
    )

    sources: WizardSourcesV1 = {"datasetsIds": dataset_ids}
    updates: list[WizardJsonObject] = []
    update_guids: set[str] = set()
    if dataset is not None:
        for parameter in dataset.parameters:
            field = _project_update_field(parameter.raw)
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
        field = _project_update_field(local_field)
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
            [_project_field(item, dataset_id=dataset_id) for item in slot_snapshots],
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
            item = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0]
            item["direction"] = direction.upper()
            sort_items.append(item)
        _visualization_slot(visualization, "sort")["items"] = _json_array(
            sort_items,
            context="Wizard sort items",
        )
    elif spec.slots.get("sort"):
        sort_items = _normalize_fields(normalizer, list(spec.slots["sort"]), dataset_id=dataset_id)
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

    filters: list[WizardJsonObject] = []
    for ref, operation, values in spec.pending_filters:
        item = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0]
        filter_value: WizardJsonObject = {"operation": {"code": operation}}
        if values:
            filter_value["value"] = list(values)
        filter_item: WizardJsonObject = {
            "guid": item["guid"],
            "datasetId": item["datasetId"],
            "filter": filter_value,
        }
        if "fakeTitle" in item:
            filter_item["fakeTitle"] = item["fakeTitle"]
        filters.append(filter_item)
    if filters:
        sources["filters"] = filters

    return {"sources": sources, "visualization": visualization}
