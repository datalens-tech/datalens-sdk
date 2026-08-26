from __future__ import annotations

from collections.abc import Iterable

import pytest

from datalens_sdk._runtime.wizard_field_references import (
    _FIELD_SNAPSHOT_OWNED_KEYS_BY_CARRIER,
    FieldCarrier,
    _replacement_snapshot,
)
from datalens_sdk._runtime.wizard_semantics import WIZARD_VISUALIZATION_SEMANTICS
from datalens_sdk._runtime.wizard_structure import (
    WizardLayerStructure,
    WizardSlotStructure,
    WizardVisualizationRegistry,
    WizardVisualizationStructure,
)
from datalens_sdk.converter.wizard._assemble import (
    _COLOR_ENCODING_OWNED_SETTING_KEYS,
    _SHAPE_ENCODING_OWNED_SETTING_KEYS,
    _assert_encoding_owned_setting_keys_are_generated,
)
from datalens_sdk.errors import DataLensConfigurationError


def _slot(setting_keys: Iterable[str]) -> WizardSlotStructure:
    return {
        "required": False,
        "items_required": False,
        "settings": {key: {} for key in setting_keys},
    }


def _visualization(
    *,
    colors: Iterable[str] | None = None,
    shapes: Iterable[str] | None = None,
) -> WizardVisualizationStructure:
    slots: dict[str, WizardSlotStructure] = {}
    if colors is not None:
        slots["colors"] = _slot(colors)
    if shapes is not None:
        slots["shapes"] = _slot(shapes)
    return {
        "properties": ["type", *slots],
        "required": ["type"],
        "slots": slots,
        "chart_settings": {},
        "layers": {},
    }


def _registry(
    *,
    colors: Iterable[str] | None = None,
    shapes: Iterable[str] | None = None,
) -> WizardVisualizationRegistry:
    return {"line": _visualization(colors=colors, shapes=shapes)}


def test_encoding_owned_setting_keys_are_generated_policy_subsets() -> None:
    generated_color_keys = {*_COLOR_ENCODING_OWNED_SETTING_KEYS, "futureColorSetting"}
    generated_shape_keys = {*_SHAPE_ENCODING_OWNED_SETTING_KEYS, "futureShapeSetting"}
    registry = _registry(colors=generated_color_keys, shapes=generated_shape_keys)

    _assert_encoding_owned_setting_keys_are_generated(registry)

    assert generated_color_keys >= _COLOR_ENCODING_OWNED_SETTING_KEYS
    # Shape ownership deliberately leaves schema-supported settings untouched.
    assert generated_shape_keys > _SHAPE_ENCODING_OWNED_SETTING_KEYS


@pytest.mark.parametrize(
    ("slot_name", "owned_keys"),
    [
        ("colors", _COLOR_ENCODING_OWNED_SETTING_KEYS),
        ("shapes", _SHAPE_ENCODING_OWNED_SETTING_KEYS),
    ],
)
def test_encoding_owned_setting_keys_reject_generated_drift(
    slot_name: str,
    owned_keys: frozenset[str],
) -> None:
    missing_key = sorted(owned_keys)[0]
    generated_keys = owned_keys - {missing_key}
    registry = _registry(
        colors=generated_keys if slot_name == "colors" else None,
        shapes=generated_keys if slot_name == "shapes" else None,
    )

    with pytest.raises(DataLensConfigurationError, match=missing_key):
        _assert_encoding_owned_setting_keys_are_generated(registry)


@pytest.mark.parametrize(
    ("slot_name", "owned_keys"),
    [
        ("colors", _COLOR_ENCODING_OWNED_SETTING_KEYS),
        ("shapes", _SHAPE_ENCODING_OWNED_SETTING_KEYS),
    ],
)
def test_complete_encoding_carrier_cannot_mask_incomplete_carrier(
    slot_name: str,
    owned_keys: frozenset[str],
) -> None:
    missing_key = sorted(owned_keys)[0]
    registry = _registry(
        colors=owned_keys if slot_name == "colors" else None,
        shapes=owned_keys if slot_name == "shapes" else None,
    )
    registry["scatter"] = _visualization(
        colors=owned_keys - {missing_key} if slot_name == "colors" else None,
        shapes=owned_keys - {missing_key} if slot_name == "shapes" else None,
    )

    with pytest.raises(DataLensConfigurationError, match=rf"scatter.*{slot_name}.*{missing_key}"):
        _assert_encoding_owned_setting_keys_are_generated(registry)


def test_layer_encoding_carrier_rejects_generated_drift() -> None:
    missing_key = sorted(_SHAPE_ENCODING_OWNED_SETTING_KEYS)[0]
    layer: WizardLayerStructure = {
        "properties": ["type", "shapes"],
        "required": ["type"],
        "slots": {"shapes": _slot(_SHAPE_ENCODING_OWNED_SETTING_KEYS - {missing_key})},
        "layer_settings": {},
    }
    combined = _visualization()
    combined["layers"] = {"line": layer}
    registry: WizardVisualizationRegistry = {"combined-chart": combined}

    with pytest.raises(DataLensConfigurationError, match=rf"combined-chart.*layer 'line'.*shapes.*{missing_key}"):
        _assert_encoding_owned_setting_keys_are_generated(registry)


def test_absent_encoding_carrier_has_no_ownership_contract() -> None:
    _assert_encoding_owned_setting_keys_are_generated(_registry())


def test_semantic_descriptors_contain_only_executable_policy_fields() -> None:
    assert all(
        set(semantics) <= {"slot_aliases", "encodings", "label_modes", "autofix", "slot_capacities"}
        for semantics in WIZARD_VISUALIZATION_SEMANTICS.values()
    )
    assert {
        visualization_type
        for visualization_type, semantics in WIZARD_VISUALIZATION_SEMANTICS.items()
        if "autofix" in semantics
    } == {"bar"}
    assert WIZARD_VISUALIZATION_SEMANTICS["bar"]["autofix"] == {
        "sort_from_slot": "y",
        "sort_direction": "DESC",
        "labels_from_slot": "x",
    }
    for semantics in WIZARD_VISUALIZATION_SEMANTICS.values():
        for encoding_rules in semantics.get("encodings", {}).values():
            for rule in encoding_rules.values():
                assert set(rule) <= {"slot", "implicit_from_slot", "measure_slots"}
                assert rule["slot"]


@pytest.mark.parametrize("carrier", _FIELD_SNAPSHOT_OWNED_KEYS_BY_CARRIER)
def test_field_replacement_ownership_preserves_open_snapshot_properties(carrier: FieldCarrier) -> None:
    owned_keys = _FIELD_SNAPSHOT_OWNED_KEYS_BY_CARRIER[carrier]
    current: dict[str, object] = {key: f"old:{key}" for key in owned_keys}
    current["futureSchemaProperty"] = {"owner": "server"}
    replacement: dict[str, object] = {key: f"new:{key}" for key in owned_keys}
    replacement["futureReplacementProperty"] = {"owner": "replacement"}

    result = _replacement_snapshot(current, replacement, carrier=carrier)

    assert all(result[key] == f"new:{key}" for key in owned_keys)
    assert result["futureSchemaProperty"] == {"owner": "server"}
    assert "futureReplacementProperty" not in result
