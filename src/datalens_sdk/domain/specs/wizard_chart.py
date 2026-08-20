from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

from typing_extensions import NotRequired

from datalens_sdk.domain.chart_types import CombinedLayerType, GeoLayerFilter, GeoLayerType, GradientPaletteId
from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
    from datalens_sdk.domain.chart_types import MeasureFormat
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.fields import WizardFieldRef

__all__ = ["CombinedLayerInput", "GeoLayerInput", "WizardChartCreateSpec"]


class CombinedLayerInput(TypedDict):
    id: str
    layer_type: CombinedLayerType
    y: WizardFieldRef | None
    y2: WizardFieldRef | None
    name: str | None


class GeoLayerInput(TypedDict):
    id: str
    layer_type: GeoLayerType
    geopoint: WizardFieldRef | None
    polygon: WizardFieldRef | None
    polyline: WizardFieldRef | None
    grouping: WizardFieldRef | None
    size: WizardFieldRef | None
    color: WizardFieldRef | None
    color_mode: Literal["2-point", "3-point"] | None
    color_palette: GradientPaletteId | None
    color_reversed: bool | None
    filters: tuple[GeoLayerFilter, ...]
    tooltips: tuple[WizardFieldRef, ...]
    labels: tuple[WizardFieldRef, ...]
    sort_by: WizardFieldRef | None
    sort_direction: Literal["asc", "desc"]
    alpha: int
    name: str | None
    dataset: NotRequired[Dataset | None]


@dataclass(frozen=True, slots=True)
class WizardChartCreateSpec:
    """Immutable snapshot of a wizard-chart-create builder's state.

    This is the read contract between the domain builder layer and the
    converter/api layers. Converters and services consume this spec instead of
    reaching into builder ``_protected`` attributes.
    """

    visualization_type: str
    name: str
    location: EntryLocation
    description: str | None
    dataset: Dataset | None
    dataset_ids: tuple[str, ...]
    slots: Mapping[str, tuple[WizardFieldRef, ...]]
    local_fields: tuple[Mapping[str, object], ...]
    chart_settings: Mapping[str, object]
    slot_settings: Mapping[str, Mapping[str, object]]
    item_mutations: tuple[tuple[WizardFieldRef, str, object], ...]
    pending_filters: tuple[tuple[WizardFieldRef, str, list[str]], ...]
    sort_direction_items: tuple[tuple[WizardFieldRef, str], ...]
    colors_palette: str | None
    color_encoding: WizardColorEncoding | None
    hierarchies: tuple[Mapping[str, object], ...]
    pending_measure_formats: tuple[tuple[WizardFieldRef, MeasureFormat], ...]
    shape_encoding: WizardShapeEncoding | None
    geopoints_config: Mapping[str, object]
    label_mode: str | None
    labels_position: str | None
    combined_layers: tuple[CombinedLayerInput, ...]
    geo_layers: tuple[GeoLayerInput, ...]
    geo_datasets: tuple[Dataset, ...]
