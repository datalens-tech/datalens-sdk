from __future__ import annotations

from typing import Literal, TypedDict

from typing_extensions import NotRequired

from datalens_sdk.serialization.json_types import JsonValue

WizardJsonObject = dict[str, JsonValue]
WizardVisualizationTypeV1 = Literal["line"]
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


class WizardSlotV1(TypedDict):
    items: list[WizardJsonObject]
    settings: NotRequired[WizardJsonObject]


class WizardLineVisualizationV1(TypedDict):
    type: WizardVisualizationTypeV1
    x: WizardSlotV1
    chartSettings: NotRequired[WizardJsonObject]
    y: NotRequired[WizardSlotV1]
    y2: NotRequired[WizardSlotV1]
    colors: NotRequired[WizardSlotV1]
    shapes: NotRequired[WizardSlotV1]
    labels: NotRequired[WizardSlotV1]
    sort: NotRequired[WizardSlotV1]
    segments: NotRequired[WizardSlotV1]


class WizardConfigV1(TypedDict):
    sources: WizardSourcesV1
    visualization: WizardLineVisualizationV1
