from __future__ import annotations

from typing import Literal, TypeAlias

from typing_extensions import TypedDict

__all__ = [
    "ChartCategory",
    "CombinedLayerType",
    "DiscretePaletteId",
    "FilterOperation",
    "FunnelShape",
    "GeoLayerType",
    "GradientPaletteId",
    "MapType",
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

MapType: TypeAlias = Literal["light", "dark", "satellite"]

CombinedLayerType: TypeAlias = Literal["column", "line", "area"]

GeoLayerType: TypeAlias = Literal["geopoint", "geopolygon", "heatmap", "polyline"]

ChartCategory: TypeAlias = Literal["wizard", "editor", "ql"]

QLCast: TypeAlias = Literal["string", "integer", "genericdatetime"]

QLParamType: TypeAlias = Literal["number", "string", "date-interval"]


class MeasureFormat(TypedDict, total=False):
    format: Literal["number", "percent", "currency"]
    precision: int
    unit: Literal["auto", "k", "m", "bln"]
    prefix: str
    postfix: str
    show_rank_delimiter: bool
