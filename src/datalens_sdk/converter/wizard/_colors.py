from __future__ import annotations

from collections.abc import Mapping
import re

from datalens_sdk._runtime.chart_constants import (
    DEFAULT_CATEGORICAL_PALETTE,
    VALID_DISCRETE_PALETTES,
    VALID_GRADIENT_PALETTES,
    gradient_types_for_palette,
)
from datalens_sdk._runtime.chart_wire import (
    build_pseudo_measure_names_for_data_colors,
    build_pseudo_measure_names_for_placeholder,
)
from datalens_sdk._runtime.viz_specs import WizardEncodingRule, get_wizard_encoding
from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
from datalens_sdk.converter.wizard._common import (
    FieldRef,
    _collect_measures,
    _item_matches_ref,
    _items_list,
    _placeholders_list,
)
from datalens_sdk.converter.wizard._normalizer import _Normalizer
from datalens_sdk.domain.chart_types import ShapeStyle
from datalens_sdk.errors import DataLensConfigurationError

# Wizard encoding config is stateful on read/update.  These keys are the
# complete ownership boundary for the semantic Color modes: a new encoding
# discards every prior owned key, then writes its own full state.  Unknown
# keys are neutral visualization state and deliberately survive.
_COLOR_ENCODING_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "palette",
        "fieldGuid",
        "gradientMode",
        "gradientPalette",
        "reversed",
        "thresholdsMode",
        "coloredByMeasure",
        "colorMode",
        "mountedColors",
        "polygonBorders",
    }
)

# Shapes has only field-bound and measure-name semantic state.  As with
# Color, carry neutral keys through an update but never retain another mode's
# field binding or mounted value map.
_SHAPE_ENCODING_CONFIG_KEYS: frozenset[str] = frozenset({"fieldGuid", "mountedShapes"})


def _has_color_split(data: dict[str, object], explicit_colors: bool) -> bool:
    if explicit_colors:
        return True
    if data.get("colors"):
        return True
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return False
    for ph in _placeholders_list(viz):
        if ph.get("id") == "colors" and _items_list(ph):
            return True
        for item in _items_list(ph):
            if item.get("type") == "PSEUDO":
                return True
    return False


def _color_items(data: dict[str, object]) -> list[dict[str, object]]:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return []
    return [
        item
        for placeholder in _placeholders_list(viz)
        if placeholder.get("id") == "colors"
        for item in _items_list(placeholder)
    ]


def _palette_color_items(data: dict[str, object]) -> list[dict[str, object]]:
    """Return the Color fields that determine a generic palette's semantics."""
    placeholder_items = _color_items(data)
    if placeholder_items:
        return placeholder_items
    raw_colors = data.get("colors")
    if not isinstance(raw_colors, list):
        return []
    return [item for item in raw_colors if isinstance(item, dict)]


def _validate_palette_color_items(palette_id: str, color_items: list[dict[str, object]]) -> None:
    """Reject a palette whose kind does not match the Color field type."""
    actual_types = frozenset(item_type for item in color_items if isinstance(item_type := item.get("type"), str))
    if not actual_types:
        raise DataLensConfigurationError(
            f"palette(id={palette_id!r}) requires a field in Color before build() or execute()."
        )
    if palette_id in VALID_DISCRETE_PALETTES:
        allowed_types = frozenset({"DIMENSION", "PSEUDO"})
        expected = "a DIMENSION (or PSEUDO Measure Names)"
    else:
        allowed_types = frozenset({"MEASURE"})
        expected = "a MEASURE"
    if not actual_types <= allowed_types:
        got = ", ".join(sorted(actual_types))
        raise DataLensConfigurationError(f"palette(id={palette_id!r}) requires {expected} in Color; got {got}.")


def _placeholder_by_id(data: dict[str, object], placeholder_id: str) -> dict[str, object] | None:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return None
    return next((ph for ph in _placeholders_list(viz) if ph.get("id") == placeholder_id), None)


def _write_encoding_items(
    data: dict[str, object],
    *,
    data_key: str,
    rule: WizardEncodingRule,
    items: list[dict[str, object]],
) -> None:
    target = rule.get("target")
    if target == "data":
        data[data_key] = [dict(item) for item in items]
        return
    if target != "placeholder":
        raise DataLensConfigurationError(f"Unsupported Wizard encoding target {target!r}.")
    placeholder_id = rule.get("placeholder")
    if not isinstance(placeholder_id, str):
        raise DataLensConfigurationError("Wizard placeholder encoding is missing its placeholder id.")
    placeholder = _placeholder_by_id(data, placeholder_id)
    if placeholder is None:
        raise DataLensConfigurationError(
            f"Wizard visualization is missing the declared {placeholder_id!r} placeholder."
        )
    placeholder["items"] = [dict(item) for item in items]
    if rule.get("copy_to_data"):
        data[data_key] = [dict(item) for item in items]


def _validate_field_type(item: Mapping[str, object], *, method_name: str, expected_type: str) -> None:
    actual_type = item.get("type")
    if actual_type != expected_type:
        raise DataLensConfigurationError(
            f"{method_name}() requires a {expected_type} field; got {actual_type or 'UNKNOWN'}."
        )


def _validate_required_membership(
    data: dict[str, object],
    *,
    field: FieldRef,
    method_name: str,
    rule: WizardEncodingRule,
) -> None:
    placeholder_id = rule.get("requires_field_in")
    if not isinstance(placeholder_id, str):
        return
    placeholder = _placeholder_by_id(data, placeholder_id)
    if placeholder is not None and any(_item_matches_ref(item, field) for item in _items_list(placeholder)):
        return
    raise DataLensConfigurationError(
        f"{method_name}() requires the field to already be placed in the {placeholder_id!r} section."
    )


def _begin_color_encoding_config(data: dict[str, object]) -> dict[str, object]:
    """Return the neutral Color config after clearing prior semantic state.

    ``palette`` is reconstructed from the current builder intent below; it
    must not leak from an encoding selected in an earlier update.
    """
    existing = data.get("colorsConfig")
    cfg = dict(existing) if isinstance(existing, dict) else {}
    for key in _COLOR_ENCODING_CONFIG_KEYS:
        cfg.pop(key, None)
    data["colorsConfig"] = cfg
    return cfg


def _begin_shape_encoding_config(data: dict[str, object]) -> dict[str, object]:
    """Return the neutral Shapes config after clearing semantic state."""
    existing = data.get("shapesConfig")
    cfg = dict(existing) if isinstance(existing, dict) else {}
    for key in _SHAPE_ENCODING_CONFIG_KEYS:
        cfg.pop(key, None)
    data["shapesConfig"] = cfg
    return cfg


def _remove_measure_names_from_category(data: dict[str, object], visualization_id: str) -> None:
    """Remove the Color-owned Measure Names carrier before a field encoding."""
    rule = get_wizard_encoding(visualization_id, "color", "measure_name")
    if rule is None:
        return
    category_placeholder = rule.get("category_placeholder")
    if not isinstance(category_placeholder, str):
        return
    placeholder = _placeholder_by_id(data, category_placeholder)
    if placeholder is None:
        return
    items = _items_list(placeholder)
    placeholder["items"] = [item for item in items if item.get("type") != "PSEUDO"]


def _apply_color_field(
    data: dict[str, object],
    *,
    encoding: WizardColorEncoding,
    visualization_id: str,
    normalizer: _Normalizer,
) -> None:
    if encoding.field is None:
        raise DataLensConfigurationError(f"color_by_{encoding.kind}() requires a field.")
    rule = get_wizard_encoding(visualization_id, "color", encoding.kind)
    if rule is None:
        raise DataLensConfigurationError(f"color_by_{encoding.kind}() is not applicable to viz {visualization_id!r}.")
    normalized = normalizer.normalize([encoding.field])
    if not normalized:
        raise DataLensConfigurationError(f"color_by_{encoding.kind}() could not resolve its field.")
    item = normalized[0]
    expected_type = "DIMENSION" if encoding.kind == "dimension" else "MEASURE"
    method_name = f"color_by_{encoding.kind}"
    _validate_field_type(item, method_name=method_name, expected_type=expected_type)
    _validate_required_membership(
        data,
        field=encoding.field,
        method_name=method_name,
        rule=rule,
    )
    _write_encoding_items(data, data_key="colors", rule=rule, items=[item])

    cfg = _begin_color_encoding_config(data)
    if encoding.kind != "measure":
        return
    has_gradient_settings = any(
        value is not None for value in (encoding.gradient_mode, encoding.gradient_palette, encoding.reversed)
    )
    if not has_gradient_settings:
        return
    guid = item.get("guid")
    if isinstance(guid, str) and guid:
        cfg["fieldGuid"] = guid
    gradient_mode = encoding.gradient_mode
    if encoding.gradient_palette is not None:
        cfg["gradientPalette"] = encoding.gradient_palette
        if gradient_mode is None:
            gradient_types = gradient_types_for_palette(encoding.gradient_palette)
            gradient_mode = (
                "2-point" if "2-point" in gradient_types else "3-point" if "3-point" in gradient_types else None
            )
    if gradient_mode is not None:
        cfg["gradientMode"] = gradient_mode
    cfg["reversed"] = encoding.reversed if encoding.reversed is not None else False
    cfg["thresholdsMode"] = "auto"


def _measure_items(
    data: dict[str, object],
    *,
    rule: WizardEncodingRule,
    method_name: str,
) -> list[dict[str, object]]:
    measure_placeholders = rule.get("measure_placeholders")
    if not measure_placeholders:
        raise DataLensConfigurationError(f"{method_name}() has no measure placeholders configured.")
    measures = _collect_measures(data, list(measure_placeholders))
    if len(measures) < 2:
        joined = ", ".join(f".{placeholder}()" for placeholder in measure_placeholders)
        raise DataLensConfigurationError(f"{method_name}() requires at least two measures across {joined}.")
    return measures


def _append_measure_names_to_category(data: dict[str, object], rule: WizardEncodingRule) -> None:
    category_placeholder = rule.get("category_placeholder")
    if not isinstance(category_placeholder, str):
        return
    placeholder = _placeholder_by_id(data, category_placeholder)
    if placeholder is None:
        raise DataLensConfigurationError(
            f"Wizard visualization is missing the declared {category_placeholder!r} category placeholder."
        )
    items = placeholder.setdefault("items", [])
    if not isinstance(items, list):
        raise DataLensConfigurationError(f"Placeholder {category_placeholder!r} has invalid items.")
    if not any(isinstance(item, dict) and item.get("type") == "PSEUDO" for item in items):
        items.append(build_pseudo_measure_names_for_placeholder())


def _apply_color_by_measure_name(
    data: dict[str, object],
    *,
    encoding: WizardColorEncoding,
    visualization_id: str,
) -> None:
    rule = get_wizard_encoding(visualization_id, "color", "measure_name")
    if rule is None:
        raise DataLensConfigurationError(f"color_by_measure_name() is not applicable to viz {visualization_id!r}.")
    measures = _measure_items(data, rule=rule, method_name="color_by_measure_name")
    mounted_colors: dict[str, str] = {
        title: str(index)
        for index, measure in enumerate(measures)
        if isinstance((title := measure.get("title")), str) and title
    }
    for field_ref, color in encoding.colors_map.items():
        if re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", color) is None and not color.isdigit():
            raise DataLensConfigurationError(
                "color_by_measure_name(colors_map=...): colors must be #RRGGBB or #RRGGBBAA values "
                "or non-negative palette indexes."
            )
        matched_measure = next((item for item in measures if _item_matches_ref(item, field_ref)), None)
        if matched_measure is None:
            raise DataLensConfigurationError(
                f"color_by_measure_name(colors_map=...): field {field_ref!r} is not placed as a measure."
            )
        title = matched_measure.get("title")
        if isinstance(title, str) and title:
            mounted_colors[title] = color

    _write_encoding_items(
        data,
        data_key="colors",
        rule=rule,
        items=[build_pseudo_measure_names_for_data_colors()],
    )
    _append_measure_names_to_category(data, rule)
    cfg = _begin_color_encoding_config(data)
    cfg.update(
        {
            "coloredByMeasure": True,
            "colorMode": "palette",
            "polygonBorders": "show",
            "mountedColors": mounted_colors,
        }
    )
    data["colorsConfig"] = cfg


def _apply_colors_config(
    data: dict[str, object],
    *,
    colors_palette: str | None,
    color_encoding: WizardColorEncoding | None,
    visualization_id: str | None,
    normalizer: _Normalizer,
) -> None:
    if color_encoding is not None:
        effective_viz_id = visualization_id or ""
        if color_encoding.kind == "measure_name":
            _apply_color_by_measure_name(
                data,
                encoding=color_encoding,
                visualization_id=effective_viz_id,
            )
        else:
            _remove_measure_names_from_category(data, effective_viz_id)
            _apply_color_field(
                data,
                encoding=color_encoding,
                visualization_id=effective_viz_id,
                normalizer=normalizer,
            )

    existing_cfg = data.get("colorsConfig")
    cfg = dict(existing_cfg) if isinstance(existing_cfg, dict) else {}
    palette_id = colors_palette
    palette_items = _palette_color_items(data)
    if palette_id is not None:
        _validate_palette_color_items(palette_id, palette_items)
        cfg["palette"] = palette_id
        if palette_id in VALID_GRADIENT_PALETTES:
            gradient_types = gradient_types_for_palette(palette_id)
            gradient_mode = (
                "2-point" if "2-point" in gradient_types else "3-point" if "3-point" in gradient_types else None
            )
            cfg["gradientPalette"] = palette_id
            if gradient_mode is not None:
                cfg["gradientMode"] = gradient_mode
    if any(item.get("type") == "DIMENSION" for item in palette_items) and palette_id is None:
        cfg.setdefault("palette", DEFAULT_CATEGORICAL_PALETTE)
    if cfg:
        data["colorsConfig"] = cfg


def _apply_shape_encoding(
    data: dict[str, object],
    *,
    shape_encoding: WizardShapeEncoding | None,
    visualization_id: str,
    normalizer: _Normalizer,
) -> None:
    if shape_encoding is None:
        return
    if shape_encoding.kind == "dimension":
        rule = get_wizard_encoding(visualization_id, "shape", "dimension")
        if rule is None:
            raise DataLensConfigurationError(f"shape_by_dimension() is not applicable to viz {visualization_id!r}.")
        if shape_encoding.field is None:
            raise DataLensConfigurationError("shape_by_dimension() requires a field.")
        normalized = normalizer.normalize([shape_encoding.field])
        if not normalized:
            raise DataLensConfigurationError("shape_by_dimension() could not resolve its field.")
        item = normalized[0]
        _validate_field_type(item, method_name="shape_by_dimension", expected_type="DIMENSION")
        _write_encoding_items(data, data_key="shapes", rule=rule, items=[item])
        guid = item.get("guid")
        cfg = _begin_shape_encoding_config(data)
        cfg["fieldGuid"] = guid if isinstance(guid, str) else ""
        if shape_encoding.shapes_map is not None:
            cfg["mountedShapes"] = dict(shape_encoding.shapes_map)
        data["shapesConfig"] = cfg
        return

    rule = get_wizard_encoding(visualization_id, "shape", "measure_name")
    if rule is None:
        raise DataLensConfigurationError(f"shape_by_measure_name() is not applicable to viz {visualization_id!r}.")
    measures = _measure_items(data, rule=rule, method_name="shape_by_measure_name")
    mounted_shapes: dict[str, ShapeStyle] = {}
    if shape_encoding.shapes_map is not None:
        for field_ref, shape in shape_encoding.shapes_map.items():
            matched_measure = next((item for item in measures if _item_matches_ref(item, field_ref)), None)
            if matched_measure is None:
                raise DataLensConfigurationError(
                    f"shape_by_measure_name(shapes_map=...): field {field_ref!r} is not placed as a measure."
                )
            title = matched_measure.get("title")
            if isinstance(title, str) and title:
                mounted_shapes[title] = shape
    _write_encoding_items(
        data,
        data_key="shapes",
        rule=rule,
        items=[build_pseudo_measure_names_for_data_colors()],
    )
    cfg = _begin_shape_encoding_config(data)
    if shape_encoding.shapes_map is not None:
        cfg["mountedShapes"] = mounted_shapes
    data["shapesConfig"] = cfg
