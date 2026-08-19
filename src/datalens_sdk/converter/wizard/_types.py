from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

from typing_extensions import NotRequired

from datalens_sdk.serialization.json_types import JsonValue

WizardJsonObject = dict[str, JsonValue]
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


class WizardConfigV1(TypedDict):
    sources: WizardSourcesV1
    visualization: WizardJsonObject
