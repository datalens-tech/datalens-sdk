from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, cast
import uuid

from typing_extensions import Self

from datalens_sdk._runtime.chart_constants import INDICATOR_FONT_SIZE_UI_TO_PAYLOAD
from datalens_sdk._runtime.chart_mutations import _ChartMutationsMixin
from datalens_sdk._runtime.chart_wire import build_date_interval, build_relative_date_interval
from datalens_sdk._runtime.validators import HEX_COLOR_RE
from datalens_sdk._runtime.viz_specs import build_ql_item, get_ql_viz_spec
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.ql_chart import QLColumn, QLParam
from datalens_sdk.domain.specs.editor_chart import EditorChartCreateSpec
from datalens_sdk.domain.specs.ql_chart import QLChartCreateSpec
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import (
        CombinedLayerType,
        DiscretePaletteId,
        FilterOperation,
        FunnelShape,
        GeoLayerType,
        GradientPaletteId,
        MapType,
        MeasureFormat,
        PaletteId,
        ShapeStyle,
    )
    from datalens_sdk.domain.connection import Connection
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.editor_chart import EditorChart
    from datalens_sdk.domain.fields import FieldLike
    from datalens_sdk.domain.ql_chart import QLChart
    from datalens_sdk.domain.wizard_chart import WizardChart
    from datalens_sdk.domain.wizard_chart_update import WizardChartUpdate


def build_local_field_entry(
    *,
    title: str,
    formula: str,
    guid: str | None = None,
    cast: str = "float",
    measure: bool = False,
    aggregation: str | None = None,
    formatting: MeasureFormat | None = None,
) -> dict[str, object]:
    """Build a wire field-entry for a formula-based local field.

    Shared by create-side ``_add_local_field`` and update-side
    ``WizardChartUpdate.add_local_field`` so both produce identical entries.
    """
    effective_guid = guid if guid is not None else str(uuid.uuid4())
    if measure:
        field_type = "MEASURE"
        if aggregation is None:
            effective_agg = "none"
            autoaggregated = True
        else:
            effective_agg = aggregation
            autoaggregated = False
    else:
        field_type = "DIMENSION"
        effective_agg = "none"
        autoaggregated = False
    field_entry: dict[str, object] = {
        "guid": effective_guid,
        "title": title,
        "calc_mode": "formula",
        "formula": formula,
        "cast": cast,
        "data_type": cast,
        "type": field_type,
        "aggregation": effective_agg,
        "autoaggregated": autoaggregated,
        "has_auto_aggregation": autoaggregated,
        "aggregation_locked": True,
        "local": True,
    }
    if formatting:
        field_entry["formatting"] = dict(formatting)
    return field_entry


def build_aggregated_measure_entry(
    field: DatasetField,
    *,
    aggregation: Literal["sum", "avg", "min", "max", "count", "countunique"],
    name: str | None = None,
    guid: str | None = None,
    allow_existing_measure: bool = False,
) -> dict[str, object]:
    """Build a local measure with an explicit aggregation from ``field``.

    Direct dimensions become direct measures. Formula dimensions preserve their
    formula because a direct field may reference only a physical source. The
    update-side aggregation change path may additionally clone an existing
    explicitly aggregated measure; automatic measures remain immutable.
    """
    if field.type == "MEASURE":
        autoaggregated = bool(field.raw.get("autoaggregated")) or bool(field.raw.get("has_auto_aggregation"))
        if autoaggregated:
            raise DataLensValidationError(
                f"Cannot set an explicit aggregation for {field.title!r}: it is already a measure with "
                "automatic aggregation. Place it directly instead."
            )
        if not allow_existing_measure:
            raise DataLensValidationError(
                f"Cannot create an aggregated measure from {field.title!r}: it is already a measure. "
                "Pass a dimension instead."
            )
    elif field.type != "DIMENSION":
        raise DataLensValidationError(
            f"Cannot create an aggregated measure from {field.title!r}: expected a dimension, got {field.type!r}."
        )

    effective_name = name if name is not None else f"{field.title} ({aggregation})"
    effective_guid = guid if guid is not None else str(uuid.uuid4())
    source_data_type = field.data_type or "float"
    entry: dict[str, object] = {
        "guid": effective_guid,
        "title": effective_name,
        "cast": field.cast or source_data_type,
        "data_type": "integer" if aggregation in {"count", "countunique"} else source_data_type,
        "type": "MEASURE",
        "aggregation": aggregation,
        "autoaggregated": False,
        "has_auto_aggregation": False,
        "local": True,
    }
    if field.calc_mode == "direct":
        source = field.source or field.guid
        if not source:
            raise DataLensValidationError(f"Cannot aggregate {field.title!r}: its direct source is missing.")
        entry.update(
            {
                "calc_mode": "direct",
                "source": source,
                "aggregation_locked": False,
            }
        )
        if field.avatar_id is not None:
            entry["avatar_id"] = field.avatar_id
        return entry

    if field.calc_mode == "formula":
        if not field.formula:
            raise DataLensValidationError(f"Cannot aggregate {field.title!r}: its formula is missing.")
        entry.update(
            {
                "calc_mode": "formula",
                "formula": field.formula,
                "source": "",
                "aggregation_locked": True,
            }
        )
        return entry

    raise DataLensValidationError(f"Cannot aggregate {field.title!r}: calc_mode {field.calc_mode!r} is not supported.")


def stage_aggregation_change(
    update: WizardChartUpdate,
    *,
    field: DatasetField,
    aggregation: Literal["sum", "avg", "min", "max", "count", "countunique"],
    name: str,
    guid: str | None,
) -> None:
    """Create and stage a replacement local measure for a placed chart field."""
    if not isinstance(field, DatasetField):
        raise DataLensValidationError("change_aggregation expects a DatasetField from chart.fields.by_guid(...).")
    try:
        placed_field = update._chart.fields.by_guid(field.guid)
    except DataLensValidationError as error:
        raise DataLensValidationError(
            f"Cannot change aggregation for {field.title!r}: the field is not placed in this chart."
        ) from error
    entry = build_aggregated_measure_entry(
        placed_field,
        aggregation=aggregation,
        name=name,
        guid=guid,
        allow_existing_measure=True,
    )
    update._local_field_additions.append(entry)
    update._aggregation_field_replacements[placed_field.guid] = entry


class _BaseWizardChartCreate(_ChartMutationsMixin):
    def __init__(
        self,
        *,
        viz_id: str,
        wire_type: str,
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None = None,
    ) -> None:
        installation = operations.installation if operations is not None else ""
        self._viz_id = viz_id
        self._wire_type = wire_type
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="Wizard chart creation",
        )
        validate_entry_name(name=name, location=self._location)
        self._name = name
        self._operations = operations
        self._placeholders: dict[str, list[FieldLike | str]] = {}
        self._dataset: Dataset | None = None
        self._dataset_ids: list[str] = []
        self._local_fields: list[dict[str, object]] = []
        self._sort: list[FieldLike | str] | None = None
        self._labels: list[FieldLike | str] | None = None
        self._init_chart_mutations()
        self._combined_layers: list[dict[str, object]] = []
        self._geo_layers: list[dict[str, object]] = []
        self._geo_datasets: list[Dataset] = []

    @property
    def viz_id(self) -> str:
        return self._viz_id

    @property
    def wire_type(self) -> str:
        return self._wire_type

    def dataset(self, dataset: Dataset) -> Self:
        self._dataset = dataset
        if dataset.id and dataset.id not in self._dataset_ids:
            self._dataset_ids.append(dataset.id)
        return self

    def _sort_fields(self, fields: Sequence[FieldLike | str]) -> Self:
        self._sort = list(fields)
        return self

    def _labels_fields(self, fields: Sequence[FieldLike | str]) -> Self:
        self._labels = list(fields)
        return self

    def _add_local_field(
        self,
        *,
        title: str,
        formula: str,
        guid: str | None = None,
        cast: str = "float",
        measure: bool = False,
        aggregation: str | None = None,
        formatting: MeasureFormat | None = None,
    ) -> Self:
        self._local_fields.append(
            build_local_field_entry(
                title=title,
                formula=formula,
                guid=guid,
                cast=cast,
                measure=measure,
                aggregation=aggregation,
                formatting=formatting,
            )
        )
        return self

    def _add_aggregated_measure(
        self,
        field: DatasetField,
        *,
        aggregation: Literal["sum", "avg", "min", "max", "count", "countunique"],
        name: str | None = None,
        guid: str | None = None,
    ) -> Self:
        self._local_fields.append(build_aggregated_measure_entry(field, aggregation=aggregation, name=name, guid=guid))
        return self

    def _set_description(self, text: str) -> Self:
        self._description = text
        return self

    def _add_hierarchy(
        self,
        title: str,
        fields: Sequence[FieldLike | str],
        *,
        guid: str | None = None,
    ) -> Self:
        effective_guid = guid if guid is not None else str(uuid.uuid4())
        self._hierarchies.append(
            {
                "guid": effective_guid,
                "title": title,
                "type": "PSEUDO",
                "fields": list(fields),
            }
        )
        return self

    def _measure_format(
        self,
        field: FieldLike | str,
        *,
        format: Literal["number", "percent", "currency"] | None = None,
        precision: int | None = None,
        unit: Literal["auto", "k", "m", "bln"] | None = None,
        prefix: str | None = None,
        postfix: str | None = None,
        show_rank_delimiter: bool | None = None,
    ) -> Self:
        fmt: MeasureFormat = {}
        if format is not None:
            fmt["format"] = format
        if precision is not None:
            fmt["precision"] = precision
        if unit is not None:
            fmt["unit"] = unit
        if prefix is not None:
            fmt["prefix"] = prefix
        if postfix is not None:
            fmt["postfix"] = postfix
        if show_rank_delimiter is not None:
            fmt["show_rank_delimiter"] = show_rank_delimiter
        self._pending_measure_formats.append((field, fmt))
        return self

    def _set_placeholder(self, placeholder_id: str, fields: Sequence[FieldLike | str]) -> Self:
        self._placeholders[placeholder_id] = list(fields)
        return self

    def _set_data_field(self, wire_key: str, fields: Sequence[FieldLike | str]) -> Self:
        self._data_fields[wire_key] = list(fields)
        return self

    def _set_extra(self, setting_key: str, value: object) -> Self:
        self._extra_settings[setting_key] = value
        return self

    def _set_ph_setting(self, placeholder_id: str, setting_key: str, value: object) -> Self:
        if placeholder_id not in self._ph_settings:
            self._ph_settings[placeholder_id] = {}
        self._ph_settings[placeholder_id][setting_key] = value
        return self

    def _funnel_shape(self, *, value: FunnelShape) -> Self:
        return self._set_extra("shape", value)

    def _chart_title(self, *, text: str = "", mode: Literal["show", "hide"] = "show") -> Self:
        self._extra_settings["title"] = text
        self._extra_settings["titleMode"] = mode
        return self

    def _navigator(self, *, mode: Literal["show", "hide"]) -> Self:
        existing = self._extra_settings.get("navigatorSettings", {})
        settings = dict(existing) if isinstance(existing, dict) else {}
        settings["navigatorMode"] = mode
        self._extra_settings["navigatorSettings"] = settings
        return self

    def _axis_title(
        self,
        ph_id: str,
        *,
        mode: Literal["off", "manual", "auto"],
        text: str = "",
    ) -> Self:
        self._set_ph_setting(ph_id, "title", mode)
        if mode == "manual" and text:
            self._set_ph_setting(ph_id, "titleValue", text)
        return self

    def _axis_scale(
        self,
        ph_id: str,
        *,
        scale: Literal["linear", "logarithmic"] = "linear",
        mode: Literal["auto", "manual"] = "auto",
        min: str | None = None,
        max: str | None = None,
    ) -> Self:
        if mode == "manual" and min is None and max is None:
            raise DataLensConfigurationError(
                "axis_scale(mode='manual') requires at least one of min= or max= to be specified."
            )
        self._set_ph_setting(ph_id, "type", scale)
        self._set_ph_setting(ph_id, "scale", mode)
        if mode == "manual":
            self._set_ph_setting(ph_id, "scaleValue", [min, max])
        return self

    def _grid(self, ph_id: str, *, enabled: bool, step: int | None = None) -> Self:
        self._set_ph_setting(ph_id, "grid", "on" if enabled else "off")
        if step is not None:
            self._set_ph_setting(ph_id, "gridStep", "manual")
            self._set_ph_setting(ph_id, "gridStepValue", step)
        return self

    def _palette(self, *, id: PaletteId) -> Self:
        self._set_palette(id=id)
        return self

    def _color_by_dimension(self, field: FieldLike | str) -> Self:
        self._set_color_by_dimension(field)
        return self

    def _color_by_measure(
        self,
        field: FieldLike | str,
        *,
        mode: Literal["2-point", "3-point"] | None = None,
        palette: GradientPaletteId | None = None,
        reversed: bool | None = None,
    ) -> Self:
        self._set_color_by_measure(field, mode=mode, palette=palette, reversed=reversed)
        return self

    def _color_by_measure_name(
        self,
        *,
        colors_map: Mapping[FieldLike | str, str] | None = None,
    ) -> Self:
        self._set_color_by_measure_name(colors_map)
        return self

    def _add_filter(
        self,
        field: FieldLike | str,
        *,
        operation: FilterOperation,
        values: Sequence[str] = (),
    ) -> Self:
        self._pending_filters.append((field, operation, list(values)))
        return self

    def _add_date_filter(
        self,
        field: FieldLike | str,
        *,
        start: str,
        end: str,
        inclusive_end: bool = True,
    ) -> Self:
        interval = build_date_interval(start, end, inclusive_end=inclusive_end)
        self._pending_filters.append((field, "BETWEEN", [interval]))
        return self

    def _add_relative_date_filter(
        self,
        field: FieldLike | str,
        *,
        start_offset: str,
        end_offset: str,
    ) -> Self:

        interval = build_relative_date_interval(start_offset, end_offset)
        self._pending_filters.append((field, "BETWEEN", [interval]))
        return self

    def _add_sort(
        self,
        field: FieldLike | str,
        *,
        direction: Literal["asc", "desc"] = "asc",
    ) -> Self:
        self._sort_direction_items.append((field, direction))
        return self

    def _shape_by_dimension(
        self,
        field: FieldLike | str,
        *,
        shapes_map: Mapping[str, ShapeStyle] | None = None,
    ) -> Self:
        self._set_shape_by_dimension(field, shapes_map)
        return self

    def _shape_by_measure_name(
        self,
        *,
        shapes_map: Mapping[FieldLike | str, ShapeStyle] | None = None,
    ) -> Self:
        self._set_shape_by_measure_name(shapes_map)
        return self

    @staticmethod
    def _field_ref_matches(placed: FieldLike | str, ref: FieldLike | str) -> bool:
        if isinstance(ref, DatasetField):
            if isinstance(placed, DatasetField):
                return placed.guid == ref.guid
            return placed == ref.guid or placed == ref.title
        if isinstance(placed, DatasetField):
            return placed.guid == ref or placed.title == ref or placed.name == ref
        return placed == ref

    def _mutate_item_by_guid(
        self,
        field: FieldLike | str,
        setting_key: str,
        value: object,
    ) -> Self:
        found = any(
            self._field_ref_matches(placed, field) for ph_fields in self._placeholders.values() for placed in ph_fields
        )
        if not found:
            raise DataLensConfigurationError(
                f"Field {field!r} not found in any placeholder. Call .columns()/.measures()/.rows() before this method."
            )
        self._item_mutations.append((field, setting_key, value))
        return self

    def to_spec(self) -> WizardChartCreateSpec:
        return WizardChartCreateSpec(
            viz_id=self._viz_id,
            name=self._name,
            location=self._location,
            description=self._description,
            dataset=self._dataset,
            dataset_ids=tuple(self._dataset_ids),
            placeholders={key: tuple(value) for key, value in self._placeholders.items()},
            explicit_colors=self._color_encoding is not None,
            local_fields=tuple(dict(lf) for lf in self._local_fields),
            sort=tuple(self._sort) if self._sort is not None else None,
            labels=tuple(self._labels) if self._labels is not None else None,
            data_fields={key: tuple(value) for key, value in self._data_fields.items()},
            extra_settings=dict(self._extra_settings),
            ph_settings={key: dict(value) for key, value in self._ph_settings.items()},
            item_mutations=tuple(self._item_mutations),
            pending_filters=tuple(self._pending_filters),
            sort_direction_items=tuple(self._sort_direction_items),
            colors_palette=self._colors_palette,
            color_encoding=self._color_encoding,
            hierarchies=tuple(dict(h) for h in self._hierarchies),
            pending_measure_formats=tuple(self._pending_measure_formats),
            shape_encoding=self._shape_encoding,
            geopoints_config=dict(self._geopoints_config),
            combined_layers=tuple(dict(layer) for layer in self._combined_layers),
            geo_layers=tuple(dict(layer) for layer in self._geo_layers),
            geo_datasets=tuple(self._geo_datasets),
        )

    def build(self) -> WizardChart:
        if self._operations is None:
            raise DataLensConfigurationError("Builder is not bound to client operations")
        return self._operations.create_wizard_chart(self)


class _TableWizardChartCreate(_BaseWizardChartCreate):
    def _column_background(
        self,
        field: FieldLike | str,
        *,
        mode: Literal["2-point", "3-point"] = "3-point",
        palette: GradientPaletteId = "red-orange-green",
        thresholds: tuple[float, ...] | None = None,
        reversed: bool = False,
    ) -> Self:
        settings = self._build_column_background_settings(
            mode=mode,
            palette=palette,
            reversed=reversed,
            thresholds=thresholds,
        )
        return self._mutate_item_by_guid(field, "backgroundSettings", settings)

    def _column_bars(
        self,
        field: FieldLike | str,
        *,
        enabled: bool = True,
        color_type: Literal["one-color", "two-color", "gradient"] = "one-color",
        color: str | None = None,
        palette: DiscretePaletteId | None = None,
        color_index: int | None = None,
        color_positive: str | None = None,
        color_negative: str | None = None,
        positive_color_index: int | None = None,
        negative_color_index: int | None = None,
        gradient_palette: GradientPaletteId | None = None,
        gradient_type: Literal["2-point", "3-point"] = "2-point",
        reversed: bool = False,
        show_labels: bool = True,
        show_in_totals: bool = False,
        align: Literal["default", "left", "right"] = "default",
    ) -> Self:
        settings = self._build_column_bars_settings(
            enabled=enabled,
            color_type=color_type,
            color=color,
            palette=palette,
            color_index=color_index,
            color_positive=color_positive,
            color_negative=color_negative,
            positive_color_index=positive_color_index,
            negative_color_index=negative_color_index,
            gradient_palette=gradient_palette,
            gradient_type=gradient_type,
            reversed=reversed,
            show_labels=show_labels,
            show_in_totals=show_in_totals,
            align=align,
        )
        return self._mutate_item_by_guid(field, "barsSettings", settings)

    def _column_title(self, field: FieldLike | str, *, title: str) -> Self:
        return self._mutate_item_by_guid(field, "_title_override", title)

    def _pagination(self, *, enabled: bool, limit: int = 100) -> Self:
        self._set_extra("pagination", "on" if enabled else "off")
        if enabled:
            self._set_extra("limit", limit)
        return self

    def _table_size(self, *, size: Literal["s", "m", "l"]) -> Self:
        self._set_extra("size", size)
        return self

    def _freeze_columns(self, *, count: int = 1) -> Self:
        return self._set_extra("pinnedColumns", count)


class _ScatterWizardChartCreate(_BaseWizardChartCreate):
    def _point_size_range(
        self,
        *,
        min_radius: float = 4.5,
        max_radius: float = 9.0,
    ) -> Self:
        radius = (min_radius + max_radius) / 2
        self._geopoints_config = {
            "radius": radius,
            "minRadius": min_radius,
            "maxRadius": max_radius,
        }
        return self


class _MetricWizardChartCreate(_BaseWizardChartCreate):
    def _font_size(self, *, size: Literal["xs", "s", "m", "l"]) -> Self:
        payload_size = INDICATOR_FONT_SIZE_UI_TO_PAYLOAD.get(size, size)
        return self._set_extra("metricFontSize", payload_size)

    def _font_color(self, *, color: str) -> Self:
        if not HEX_COLOR_RE.match(color):
            raise DataLensConfigurationError(f"font_color: color must be a hex string like #RRGGBB, got {color!r}")
        return self._set_extra("metricFontColor", color)

    def _measure_title_mode(self, *, mode: Literal["by-field", "manual", "hide"]) -> Self:
        return self._set_extra("indicatorTitleMode", mode)


class _PivotWizardChartCreate(_TableWizardChartCreate):
    def _subtotals(self, field: FieldLike | str, *, enabled: bool) -> Self:
        return self._mutate_item_by_guid(field, "subTotalsSettings", {"enabled": enabled})


class _CombinedWizardChartCreate(_BaseWizardChartCreate):
    def _combined_x(self, fields: Sequence[FieldLike | str]) -> Self:
        self._placeholders["x"] = list(fields)
        return self

    def _combined_add_layer(
        self,
        layer_type: CombinedLayerType,
        *,
        y: FieldLike | str | None = None,
        y2: FieldLike | str | None = None,
        name: str | None = None,
    ) -> Self:
        if y is None and y2 is None:
            raise DataLensConfigurationError("add_layer() requires at least one of y= or y2=.")
        self._combined_layers.append(
            {
                "layer_type": layer_type,
                "y": y,
                "y2": y2,
                "name": name,
            }
        )
        return self


class _GeolayerWizardChartCreate(_BaseWizardChartCreate):
    def _geo_add_dataset(self, dataset: Dataset) -> Self:
        if dataset.id and dataset.id not in self._dataset_ids:
            self._dataset_ids.append(dataset.id)
        if dataset not in self._geo_datasets:
            self._geo_datasets.append(dataset)
        return self

    def _geo_add_layer(
        self,
        layer_type: GeoLayerType,
        *,
        geopoint: FieldLike | str | None = None,
        polygon: FieldLike | str | None = None,
        polyline: FieldLike | str | None = None,
        size: FieldLike | str | None = None,
        color: FieldLike | str | None = None,
        tooltips: Sequence[FieldLike | str] = (),
        labels: Sequence[FieldLike | str] = (),
        alpha: int = 80,
        name: str | None = None,
        dataset: Dataset | None = None,
    ) -> Self:
        if layer_type not in ("geopoint", "geopolygon", "heatmap", "polyline"):
            raise DataLensConfigurationError(f"Unsupported geo layer type: {layer_type!r}.")
        required_field = {
            "geopoint": geopoint,
            "heatmap": geopoint,
            "geopolygon": polygon,
            "polyline": polyline,
        }[layer_type]
        if required_field is None:
            parameter = (
                "polygon" if layer_type == "geopolygon" else "polyline" if layer_type == "polyline" else "geopoint"
            )
            raise DataLensConfigurationError(f"add_layer({layer_type!r}) requires {parameter}=.")
        if dataset is not None:
            self._geo_add_dataset(dataset)
        self._geo_layers.append(
            {
                "layer_type": layer_type,
                "geopoint": geopoint,
                "polygon": polygon,
                "polyline": polyline,
                "size": size,
                "color": color,
                "tooltips": list(tooltips),
                "labels": list(labels),
                "alpha": alpha,
                "name": name,
                "dataset": dataset,
            }
        )
        return self

    def _map_type(self, *, mode: MapType) -> Self:
        self._set_extra("mapType", mode)
        return self

    def _map_center(self, *, lat: float, lon: float, zoom: int | None = None) -> Self:
        self._set_extra("mapCenterMode", "manual")
        self._set_extra("mapCenter", {"lat": lat, "lon": lon})
        if zoom is not None:
            self._set_extra("mapZoom", zoom)
        return self


class _BaseEditorNodeCreate:
    def __init__(
        self,
        *,
        wire_type: str,
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None = None,
    ) -> None:
        installation = operations.installation if operations is not None else ""
        self._wire_type = wire_type
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="Editor chart creation",
        )
        validate_entry_name(name=name, location=self._location)
        self._name = name
        self._operations = operations
        self._tabs: dict[str, str | None] = {}
        self._description: str | None = None

    @property
    def wire_type(self) -> str:
        return self._wire_type

    def _set_tab(self, tab: str, content: str | None) -> Self:
        self._tabs[tab] = content
        return self

    def description(self, text: str) -> Self:
        self._description = text
        return self

    def to_spec(self) -> EditorChartCreateSpec:
        return EditorChartCreateSpec(
            wire_type=self._wire_type,
            name=self._name,
            tabs=dict(self._tabs),
            location=self._location,
            description=self._description,
        )

    def build(self) -> EditorChart:
        if self._operations is None:
            raise DataLensConfigurationError("Builder is not bound to client operations")
        return self._operations.create_editor_chart(self)


class _BaseQLChartCreate:
    def __init__(
        self,
        *,
        viz_id: str,
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None = None,
    ) -> None:
        installation = operations.installation if operations is not None else ""
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="QL chart creation",
        )
        validate_entry_name(name=name, location=self._location)
        self._viz_id = viz_id
        self._name = name
        self._operations = operations
        self._connection_obj: Connection | None = None
        self._query: str = ""
        self._columns: dict[str, list[QLColumn]] = {}
        self._visualization: Mapping[str, object] | None = None
        self._params_objs: tuple[QLParam, ...] = ()
        self._extra_data: dict[str, object] = {}
        self._data_sections: dict[str, list[dict[str, object]]] = {}
        self._description: str | None = None

    def connection(self, connection: Connection) -> Self:
        if not connection.id:
            raise DataLensValidationError("QL chart connection requires a Connection with an id")
        self._connection_obj = connection
        return self

    def query(self, sql: str) -> Self:
        self._query = sql
        return self

    def _set_placeholder(self, placeholder_id: str, columns: Sequence[QLColumn | str]) -> Self:
        resolved = self._resolve_placeholder_id(placeholder_id)
        self._columns[resolved] = [
            column if isinstance(column, QLColumn) else QLColumn(name=column) for column in columns
        ]
        return self

    def _resolve_placeholder_id(self, placeholder_id: str) -> str:
        spec = get_ql_viz_spec(self._viz_id)
        spec_placeholders = cast(Sequence[Mapping[str, object]], spec.get("placeholders", []))
        for placeholder in spec_placeholders:
            ph_id = cast(str, placeholder.get("id", ""))
            if ph_id == placeholder_id or ph_id.replace("-", "_") == placeholder_id:
                return ph_id
        return placeholder_id

    def _set_data_section(self, section: str, columns: Sequence[QLColumn | str]) -> Self:
        resolved = [column if isinstance(column, QLColumn) else QLColumn(name=column) for column in columns]
        self._data_sections[section] = [build_ql_item(col.name, col.cast) for col in resolved]
        return self

    def visualization(self, blob: Mapping[str, object]) -> Self:
        self._visualization = dict(blob)
        return self

    def params(self, params: Sequence[QLParam]) -> Self:
        self._params_objs = tuple(params)
        return self

    def data(self, blob: Mapping[str, object]) -> Self:
        self._extra_data.update({key: value for key, value in blob.items() if isinstance(key, str)})
        return self

    def description(self, text: str) -> Self:
        self._description = text
        return self

    def to_spec(self) -> QLChartCreateSpec:
        visualization = self._visualization
        if visualization is None:
            visualization = _build_ql_visualization(self._viz_id, self._columns)
        extra_data = dict(self._extra_data)
        for section, items in self._data_sections.items():
            extra_data[section] = [dict(item) for item in items]
        return QLChartCreateSpec(
            name=self._name,
            location=self._location,
            connection=self._connection_obj,
            query=self._query,
            visualization=visualization,
            params=self._params_objs,
            extra_data=extra_data,
            description=self._description,
        )

    def build(self) -> QLChart:
        if self._operations is None:
            raise DataLensConfigurationError("Builder is not bound to client operations")
        self._validate_required_placeholders()
        return self._operations.create_ql_chart(self)

    def _validate_required_placeholders(self) -> None:
        if self._visualization is not None:
            return
        spec = get_ql_viz_spec(self._viz_id)
        placeholders = cast(Mapping[str, object], spec.get("placeholders", {}))
        missing: list[str] = []
        for placeholder in placeholders:
            placeholder_map = cast(Mapping[str, object], placeholder)
            if bool(placeholder_map.get("required")):
                ph_id = cast(str, placeholder_map.get("id"))
                if not self._columns.get(ph_id):
                    missing.append(ph_id)
        if missing:
            raise DataLensValidationError(
                f"QL chart {self._viz_id!r} requires placeholder(s) {missing} to be filled "
                "before build(); pass columns to the corresponding builder method."
            )


def _build_ql_visualization(viz_id: str, columns: Mapping[str, list[QLColumn]]) -> Mapping[str, object]:
    """Build a QL ``visualization`` from ``QL_VIZ_SPECS`` with filled items.

    The ``viz`` object and each placeholder structure are taken verbatim from
    the QL reference specs; placeholder ``items`` are filled from the builder's
    columns via :func:`build_ql_item` (constant ``DIMENSION``/``ql-mocked-dataset``
    structure). Placeholders without columns get ``items: []``.
    """
    spec = get_ql_viz_spec(viz_id)
    viz = dict(cast(Mapping[str, object], spec["viz"]))
    spec_placeholders = cast(Sequence[Mapping[str, object]], spec.get("placeholders", []))
    placeholders: list[dict[str, object]] = []
    for placeholder in spec_placeholders:
        placeholder_copy = dict(placeholder)
        ph_id = cast(str, placeholder_copy.get("id"))
        ph_columns = columns.get(ph_id, [])
        placeholder_copy["items"] = [build_ql_item(col.name, col.cast) for col in ph_columns]
        placeholders.append(placeholder_copy)
    viz["placeholders"] = placeholders
    return viz
