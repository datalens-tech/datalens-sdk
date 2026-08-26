from __future__ import annotations

from typing import TypeAlias, TypedDict

from typing_extensions import NotRequired


class WizardValueStructure(TypedDict):
    enum: NotRequired[list[str]]


class WizardSlotStructure(TypedDict):
    required: bool
    items_required: bool
    settings: dict[str, WizardValueStructure]


class WizardLayerStructure(TypedDict):
    properties: list[str]
    required: list[str]
    slots: dict[str, WizardSlotStructure]
    layer_settings: dict[str, WizardValueStructure]


class WizardVisualizationStructure(TypedDict):
    properties: list[str]
    required: list[str]
    slots: dict[str, WizardSlotStructure]
    chart_settings: dict[str, WizardValueStructure]
    layers: dict[str, WizardLayerStructure]


WizardVisualizationRegistry: TypeAlias = dict[str, WizardVisualizationStructure]


class WizardFieldStructure(TypedDict):
    direct_properties: tuple[str, ...]
    update_properties: tuple[str, ...]
    nullable_update_properties: tuple[str, ...]
