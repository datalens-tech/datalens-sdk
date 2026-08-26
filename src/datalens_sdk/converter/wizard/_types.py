from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired

from datalens_sdk.serialization.json_types import JsonValue

WizardJsonObject = dict[str, JsonValue]


class WizardSourcesV1(TypedDict):
    datasetsIds: list[str]
    updates: NotRequired[list[WizardJsonObject]]
    links: NotRequired[list[WizardJsonObject]]
    hierarchies: NotRequired[list[WizardJsonObject]]
    filters: NotRequired[list[WizardJsonObject]]


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
