from __future__ import annotations

import pytest

from datalens_sdk._runtime.chart_constants import (
    COLORS_IN_PLACEHOLDER_VIZ,
    DEFAULT_CATEGORICAL_PALETTE,
    DIVERGING_GRADIENT_PALETTES,
    INDICATOR_FONT_SIZE_UI_TO_PAYLOAD,
    SEQUENTIAL_GRADIENT_PALETTES,
    VALID_DISCRETE_PALETTES,
    VALID_GRADIENT_PALETTES,
    classify_chart_wire_type,
    gradient_types_for_palette,
    is_wizard_wire_type,
)
from datalens_sdk._runtime.viz_specs import VIZ_SPECS
from datalens_sdk.errors import NotSupportedError


def test_default_categorical_palette_is_a_public_discrete_palette() -> None:
    assert DEFAULT_CATEGORICAL_PALETTE in VALID_DISCRETE_PALETTES


def test_colors_in_placeholder_viz_reference_existing_viz() -> None:
    assert set(VIZ_SPECS) >= COLORS_IN_PLACEHOLDER_VIZ


def test_gradient_subsets_are_within_valid_gradient() -> None:
    assert SEQUENTIAL_GRADIENT_PALETTES <= VALID_GRADIENT_PALETTES
    assert DIVERGING_GRADIENT_PALETTES <= VALID_GRADIENT_PALETTES


def test_gradient_types_for_sequential_palette() -> None:
    assert gradient_types_for_palette("blue") == frozenset({"2-point"})


def test_gradient_types_for_diverging_palette() -> None:
    assert gradient_types_for_palette("pink-gray-green") == frozenset({"3-point"})
    assert gradient_types_for_palette("orange-gray-blue") == frozenset({"3-point"})


def test_gradient_types_for_unknown_palette_is_empty() -> None:
    assert gradient_types_for_palette("not-a-real-palette") == frozenset()


def test_indicator_font_size_ui_to_payload_keys_and_values() -> None:
    assert set(INDICATOR_FONT_SIZE_UI_TO_PAYLOAD) == {"xs", "s", "m", "l"}
    assert set(INDICATOR_FONT_SIZE_UI_TO_PAYLOAD.values()) == {"s", "m", "l", "xl"}


@pytest.mark.parametrize(
    ("wire_type", "expected"),
    [
        ("advanced-chart_node", "editor"),
        ("d3_ql_node", "ql"),
        ("metric_wizard_node", "wizard"),
    ],
)
def test_chart_relation_classifier_uses_installation_editor_types_and_namespace_suffixes(
    wire_type: str,
    expected: str,
) -> None:
    assert (
        classify_chart_wire_type(
            wire_type,
            editor_wire_types=frozenset({"advanced-chart_node"}),
        )
        == expected
    )


def test_chart_relation_classifier_rejects_unknown_wire_type() -> None:
    with pytest.raises(NotSupportedError, match="mystery_node"):
        classify_chart_wire_type("mystery_node", editor_wire_types=frozenset())


def test_wizard_wire_type_predicate_is_symmetric_with_ql_predicate() -> None:
    assert is_wizard_wire_type("metric_wizard_node")
    assert not is_wizard_wire_type("metric_node")
