from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import TYPE_CHECKING

from datalens_sdk.errors import NotSupportedError

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import ChartCategory

DEFAULT_CATEGORICAL_PALETTE = "datalens-classic-20"

COLORS_IN_PLACEHOLDER_VIZ: frozenset[str] = frozenset({"pie", "donut"})

VALID_DISCRETE_PALETTES: frozenset[str] = frozenset(
    {
        "datalens-classic-20",
        "classic20",
        "datalens-neo-20",
        "defaultScheme",
        "neutral20",
        "taxi-paired",
        "taxi-pastel",
        "taxi9",
        "yandex-cloud",
    }
)

VALID_GRADIENT_PALETTES: frozenset[str] = frozenset(
    {
        "blue",
        "orange-yellow",
        "pink-gray-green",
        "red-orange-green",
        "yellow",
    }
)

VALID_PALETTES: frozenset[str] = VALID_DISCRETE_PALETTES | VALID_GRADIENT_PALETTES

SEQUENTIAL_GRADIENT_PALETTES: frozenset[str] = frozenset(
    {
        "blue",
        "orange-yellow",
        "yellow",
    }
)

DIVERGING_GRADIENT_PALETTES: frozenset[str] = frozenset(
    {
        "pink-gray-green",
        "red-orange-green",
    }
)


def is_ql_wire_type(wire_type: str | None) -> bool:
    return isinstance(wire_type, str) and wire_type.endswith("_ql_node")


def is_wizard_wire_type(wire_type: str | None) -> bool:
    return isinstance(wire_type, str) and wire_type.endswith("_wizard_node")


def classify_chart_wire_type(
    wire_type: str,
    *,
    editor_wire_types: AbstractSet[str],
) -> ChartCategory:
    if wire_type in editor_wire_types:
        return "editor"
    if is_ql_wire_type(wire_type):
        return "ql"
    if is_wizard_wire_type(wire_type):
        return "wizard"
    raise NotSupportedError(f"Unsupported chart wire type in dashboard dependency relation: {wire_type!r}")


INDICATOR_FONT_SIZE_UI_TO_PAYLOAD: dict[str, str] = {"xs": "s", "s": "m", "m": "l", "l": "xl"}


def gradient_types_for_palette(palette: str) -> frozenset[str]:
    """Return the gradient types a palette renders correctly in for column_bars.

    Sequential single-hue palettes render only as "2-point" and diverging
    palettes only as "3-point". A palette outside either group returns an
    empty set.
    """
    types: set[str] = set()
    if palette in SEQUENTIAL_GRADIENT_PALETTES:
        types.add("2-point")
    if palette in DIVERGING_GRADIENT_PALETTES:
        types.add("3-point")
    return frozenset(types)
