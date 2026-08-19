from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from typing_extensions import TypedDict

from datalens_sdk.domain.fields import FieldLike

__all__ = [
    "ChartCategory",
    "CombinedLayerType",
    "DiscretePaletteId",
    "FilterOperation",
    "FunnelShape",
    "GeoLayerFilter",
    "GeoLayerType",
    "GradientPaletteId",
    "MeasureFormat",
    "PaletteId",
    "QLCast",
    "QLParamType",
    "ShapeStyle",
]

FilterOperation: TypeAlias = Literal[
    "IN",
    "EQ",
    "NE",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "BETWEEN",
    "ISNULL",
    "ISNOTNULL",
    "STARTSWITH",
    "CONTAINS",
]


@dataclass(frozen=True, slots=True)
class GeoLayerFilter:
    """A filter evaluated only within one geolayer visualization layer."""

    field: FieldLike | str
    operation: FilterOperation
    values: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))


FunnelShape: TypeAlias = Literal["auto", "rectangle", "trapezoid"]

DiscretePaletteId: TypeAlias = Literal[
    "datalens-classic-20",
    "classic20",
    "datalens-neo-20",
    "defaultScheme",
    "neutral20",
    "taxi-paired",
    "taxi-pastel",
    "taxi9",
    "yandex-cloud",
]

GradientPaletteId: TypeAlias = Literal[
    "blue",
    "orange-gray-blue",
    "orange-yellow",
    "pink-gray-green",
    "red-orange-green",
    "yellow",
]

PaletteId: TypeAlias = DiscretePaletteId | GradientPaletteId

ShapeStyle: TypeAlias = Literal[
    "Solid",
    "Dash",
    "Dot",
    "ShortDash",
    "ShortDot",
    "ShortDashDot",
    "ShortDashDotDot",
    "LongDash",
    "DashDot",
    "LongDashDot",
    "LongDashDotDot",
]

CombinedLayerType: TypeAlias = Literal["column", "line", "area"]

GeoLayerType: TypeAlias = Literal[
    "geopoint",
    "geopoint-with-cluster",
    "geopolygon",
    "heatmap",
    "polyline",
]

ChartCategory: TypeAlias = Literal["wizard", "editor", "ql"]

QLCast: TypeAlias = Literal["string", "integer", "genericdatetime"]

QLParamType: TypeAlias = Literal["number", "string", "date-interval"]


class MeasureFormat(TypedDict, total=False):
    format: Literal["number", "percent"]
    precision: int
    unit: Literal["auto", "k", "m", "b", "t"]
    prefix: str
    postfix: str
    show_rank_delimiter: bool
