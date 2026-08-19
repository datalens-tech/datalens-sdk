from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

from typing_extensions import NotRequired

from datalens_sdk.serialization.json_types import JsonValue

WizardJsonObject = dict[str, JsonValue]
WizardVisualizationTypeV1 = Literal[
    "area",
    "area100p",
    "bar",
    "bar100p",
    "column",
    "column100p",
    "combined-chart",
    "donut",
    "flatTable",
    "funnel",
    "geolayer",
    "line",
    "metric",
    "pie",
    "pivotTable",
    "scatter",
    "treemap",
]
WizardNonLayeredVisualizationTypeV1 = Literal[
    "area",
    "area100p",
    "bar",
    "bar100p",
    "column",
    "column100p",
    "donut",
    "flatTable",
    "funnel",
    "line",
    "metric",
    "pie",
    "pivotTable",
    "scatter",
    "treemap",
]
WizardCombinedLayerTypeV1 = Literal["area", "column", "line"]
WizardGeoLayerTypeV1 = Literal["geopoint", "geopoint-with-cluster", "geopolygon", "heatmap", "polyline"]
WizardFieldUpdateActionV1 = Literal[
    "add_field",
    "add",
    "update_field",
    "update",
    "delete",
    "delete_field",
]


class WizardSourcesV1(TypedDict):
    datasetsIds: list[str]
    updates: NotRequired[list[WizardJsonObject]]
    links: NotRequired[list[WizardJsonObject]]
    hierarchies: NotRequired[list[WizardJsonObject]]
    filters: NotRequired[list[WizardJsonObject]]


WizardVisualizationStructure = Mapping[str, Mapping[str, JsonValue]]


class CombinedLayerSettingsV1(TypedDict):
    id: str
    name: str


class GeoLayerSettingsV1(TypedDict):
    id: str
    name: str
    alpha: NotRequired[int]


class WizardConfigV1(TypedDict):
    sources: WizardSourcesV1
    visualization: WizardJsonObject
