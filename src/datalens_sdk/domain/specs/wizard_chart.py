from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
    from datalens_sdk.domain.chart_types import MeasureFormat
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.fields import FieldLike

    FieldRef = FieldLike | str

__all__ = ["WizardChartCreateSpec"]


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
    slots: Mapping[str, tuple[FieldRef, ...]]
    local_fields: tuple[Mapping[str, object], ...]
    chart_settings: Mapping[str, object]
    slot_settings: Mapping[str, Mapping[str, object]]
    item_mutations: tuple[tuple[FieldRef, str, object], ...]
    pending_filters: tuple[tuple[FieldRef, str, list[str]], ...]
    sort_direction_items: tuple[tuple[FieldRef, str], ...]
    colors_palette: str | None
    color_encoding: WizardColorEncoding | None
    hierarchies: tuple[Mapping[str, object], ...]
    pending_measure_formats: tuple[tuple[FieldRef, MeasureFormat], ...]
    shape_encoding: WizardShapeEncoding | None
    geopoints_config: Mapping[str, object]
    label_mode: str | None
    labels_position: str | None
    combined_layers: tuple[Mapping[str, object], ...]
    geo_layers: tuple[Mapping[str, object], ...]
    geo_datasets: tuple[Dataset, ...]
