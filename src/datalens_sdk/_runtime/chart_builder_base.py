from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, cast
import uuid

from typing_extensions import Self

from datalens_sdk._runtime.chart_constants import INDICATOR_FONT_SIZE_UI_TO_PAYLOAD, gradient_types_for_palette
from datalens_sdk._runtime.chart_mutations import _ChartMutationsMixin
from datalens_sdk._runtime.chart_wire import build_date_interval, build_navigator_settings, build_relative_date_interval
from datalens_sdk._runtime.validators import HEX_COLOR_RE
from datalens_sdk._runtime.viz_specs import build_ql_item, get_ql_viz_spec
from datalens_sdk._runtime.wizard_semantics import (
    geo_layer_supports_input,
    get_geo_layer_semantics,
    validate_label_mode,
)
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.ql_chart import QLColumn, QLParam
from datalens_sdk.domain.specs.editor_chart import EditorChartCreateSpec
from datalens_sdk.domain.specs.ql_chart import QLChartCreateSpec
from datalens_sdk.domain.specs.wizard_chart import CombinedLayerInput, GeoLayerInput, WizardChartCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import (
        CombinedLayerType,
        DiscretePaletteId,
        FilterOperation,
        FunnelShape,
        GeoLayerFilter,
        GeoLayerType,
        GradientPaletteId,
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
        visualization_type: str,
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None = None,
    ) -> None:
        installation = operations.installation if operations is not None else ""
        self._visualization_type = visualization_type
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="Wizard chart creation",
        )
        validate_entry_name(name=name, location=self._location)
        self._name = name
        self._operations = operations
        self._dataset: Dataset | None = None
        self._dataset_ids: list[str] = []
        self._local_fields: list[dict[str, object]] = []
        self._init_chart_mutations()
        self._combined_layers: list[CombinedLayerInput] = []
        self._geo_layers: list[GeoLayerInput] = []
        self._geo_datasets: list[Dataset] = []

    @property
    def visualization_type(self) -> str:
        return self._visualization_type

    def dataset(self, dataset: Dataset) -> Self:
        self._dataset = dataset
        if dataset.id and dataset.id not in self._dataset_ids:
            self._dataset_ids.append(dataset.id)
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
        format: Literal["number", "percent"] | None = None,
        precision: int | None = None,
        unit: Literal["auto", "k", "m", "b", "t"] | None = None,
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

    def _set_slot(self, slot_name: str, fields: Sequence[FieldLike | str]) -> Self:
        self._slot_fields[slot_name] = list(fields)
        return self

    def _set_chart_setting(self, setting_key: str, value: object) -> Self:
        self._chart_settings[setting_key] = value
        return self

    def _set_slot_setting(self, slot_name: str, setting_key: str, value: object) -> Self:
        self._slot_settings.setdefault(slot_name, {})[setting_key] = value
        return self

    def _funnel_shape(self, *, value: FunnelShape) -> Self:
        return self._set_chart_setting("shape", value)

    def _chart_title(self, *, text: str = "", mode: Literal["show", "hide"] = "show") -> Self:
        self._chart_settings["title"] = text
        self._chart_settings["titleMode"] = mode
        return self

    def _navigator(self, *, mode: Literal["show", "hide"]) -> Self:
        self._chart_settings["navigatorSettings"] = build_navigator_settings(
            mode=mode,
            current=self._chart_settings.get("navigatorSettings"),
        )
        return self

    def _label_mode(self, *, mode: Literal["absolute", "percent"]) -> Self:
        validate_label_mode(visualization_type=self._visualization_type, label_mode=mode)
        self._label_mode_value = mode
        return self

    def _labels_position(self, *, mode: Literal["inside", "outside", "auto"]) -> Self:
        self._labels_position_value = mode
        return self

    def _axis_title(
        self,
        slot_name: str,
        *,
        mode: Literal["off", "manual", "auto"],
        text: str = "",
    ) -> Self:
        self._set_slot_setting(slot_name, "title", mode)
        if mode == "manual" and text:
            self._set_slot_setting(slot_name, "titleValue", text)
        return self

    def _axis_scale(
        self,
        slot_name: str,
        *,
        scale: Literal["linear", "logarithmic"] = "linear",
        mode: Literal["auto", "manual"] = "auto",
        min: str | None = None,
        max: str | None = None,
    ) -> Self:
        if mode == "manual" and (min is None or max is None):
            raise DataLensConfigurationError("axis_scale(mode='manual') requires both min= and max= to be specified.")
        self._set_slot_setting(slot_name, "type", scale)
        self._set_slot_setting(slot_name, "scale", mode)
        if mode == "manual":
            self._set_slot_setting(slot_name, "scaleValue", [min, max])
        return self

    def _grid(self, slot_name: str, *, enabled: bool, step: int | None = None) -> Self:
        self._set_slot_setting(slot_name, "grid", "on" if enabled else "off")
        if step is not None:
            self._set_slot_setting(slot_name, "gridStep", "manual")
            self._set_slot_setting(slot_name, "gridStepValue", step)
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
            self._field_ref_matches(placed, field)
            for slot_fields in self._slot_fields.values()
            for placed in slot_fields
        )
        if not found:
            raise DataLensConfigurationError(
                f"Field {field!r} not found in any slot. Call .columns()/.measures()/.rows() before this method."
            )
        self._item_mutations.append((field, setting_key, value))
        return self

    def to_spec(self) -> WizardChartCreateSpec:
        return WizardChartCreateSpec(
            visualization_type=self._visualization_type,
            name=self._name,
            location=self._location,
            description=self._description,
            dataset=self._dataset,
            dataset_ids=tuple(self._dataset_ids),
            slots={key: tuple(value) for key, value in self._slot_fields.items()},
            local_fields=tuple(dict(lf) for lf in self._local_fields),
            chart_settings=dict(self._chart_settings),
            slot_settings={key: dict(value) for key, value in self._slot_settings.items()},
            item_mutations=tuple(self._item_mutations),
            pending_filters=tuple(self._pending_filters),
            sort_direction_items=tuple(self._sort_direction_items),
            colors_palette=self._colors_palette,
            color_encoding=self._color_encoding,
            hierarchies=tuple(dict(h) for h in self._hierarchies),
            pending_measure_formats=tuple(self._pending_measure_formats),
            shape_encoding=self._shape_encoding,
            geopoints_config=dict(self._geopoints_config),
            label_mode=self._label_mode_value,
            labels_position=self._labels_position_value,
            combined_layers=tuple(self._combined_layers),
            geo_layers=tuple(self._geo_layers),
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
        self._set_chart_setting("pagination", "on" if enabled else "off")
        if enabled:
            self._set_chart_setting("limit", limit)
        return self

    def _table_size(self, *, size: Literal["s", "m", "l"]) -> Self:
        self._set_chart_setting("size", size)
        return self

    def _freeze_columns(self, *, count: int = 1) -> Self:
        self._set_chart_setting("pinnedColumns", count)
        return self


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
        self._set_chart_setting("metricFontSize", payload_size)
        return self

    def _font_color(self, *, color: str) -> Self:
        if not HEX_COLOR_RE.match(color):
            raise DataLensConfigurationError(f"font_color: color must be a hex string like #RRGGBB, got {color!r}")
        self._set_chart_setting("metricFontColor", color)
        return self

    def _measure_title_mode(self, *, mode: Literal["by-field", "manual", "hide"]) -> Self:
        self._set_chart_setting("titleMode", mode)
        return self


class _PivotWizardChartCreate(_TableWizardChartCreate):
    def _subtotals(self, field: FieldLike | str, *, enabled: bool) -> Self:
        return self._mutate_item_by_guid(field, "subTotalsSettings", {"enabled": enabled})


class _CombinedWizardChartCreate(_BaseWizardChartCreate):
    def _combined_x(self, fields: Sequence[FieldLike | str]) -> Self:
        return self._set_slot("x", fields)

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
                "id": str(uuid.uuid4()),
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
        grouping: FieldLike | str | None = None,
        size: FieldLike | str | None = None,
        color: FieldLike | str | None = None,
        color_mode: Literal["2-point", "3-point"] | None = None,
        color_palette: GradientPaletteId | None = None,
        color_reversed: bool | None = None,
        filters: Sequence[GeoLayerFilter] = (),
        tooltips: Sequence[FieldLike | str] = (),
        labels: Sequence[FieldLike | str] = (),
        sort_by: FieldLike | str | None = None,
        sort_direction: Literal["asc", "desc"] = "asc",
        alpha: int = 80,
        name: str | None = None,
        dataset: Dataset | None = None,
    ) -> Self:
        layer_semantics = get_geo_layer_semantics(layer_type)
        if layer_semantics is None:
            raise DataLensConfigurationError(f"Unsupported geo layer type: {layer_type!r}.")
        geometry_argument = layer_semantics["required_geometry"]
        field_values = {"geopoint": geopoint, "polygon": polygon, "polyline": polyline}
        required_field = field_values[geometry_argument]
        if required_field is None:
            raise DataLensConfigurationError(f"add_layer({layer_type!r}) requires {geometry_argument}=.")
        field_inputs = {
            **field_values,
            "grouping": grouping,
            "size": size,
            "color": color,
            "sort_by": sort_by,
        }
        sequence_inputs = {"filters": filters, "tooltips": tooltips, "labels": labels}
        for input_name, value in field_inputs.items():
            if value is not None and not geo_layer_supports_input(layer_semantics, input_name):
                raise DataLensConfigurationError(f"Geo layer type {layer_type!r} does not support {input_name}=.")
        for input_name, sequence_value in sequence_inputs.items():
            if sequence_value and not geo_layer_supports_input(layer_semantics, input_name):
                raise DataLensConfigurationError(f"Geo layer type {layer_type!r} does not support {input_name}=.")
        if sort_direction != "asc" and sort_by is None:
            if not geo_layer_supports_input(layer_semantics, "sort_by"):
                raise DataLensConfigurationError(f"Geo layer type {layer_type!r} does not support sort_direction=.")
            raise DataLensConfigurationError("Geo layer sort_direction= requires sort_by=.")
        if color is None and any(value is not None for value in (color_mode, color_palette, color_reversed)):
            raise DataLensConfigurationError("Geo layer color settings require color=.")
        if color is not None and any(value is not None for value in (color_mode, color_palette, color_reversed)):
            effective_dataset = dataset or self._dataset
            color_field: DatasetField | None = color if isinstance(color, DatasetField) else None
            if color_field is None and isinstance(color, str) and effective_dataset is not None:
                try:
                    color_field = effective_dataset.fields.by_guid(color)
                except DataLensValidationError:
                    color_field = effective_dataset.fields.by_name(color)
            if color_field is not None and color_field.type != "MEASURE":
                raise DataLensConfigurationError(
                    f"A geo layer gradient color setting requires a MEASURE, got {color_field.type!r}."
                )
        if color_mode is not None and color_mode not in {"2-point", "3-point"}:
            raise DataLensConfigurationError(f"Unsupported geo layer color_mode: {color_mode!r}.")
        if color_palette is not None:
            valid_modes = gradient_types_for_palette(color_palette)
            if not valid_modes:
                raise DataLensConfigurationError(f"Unsupported geo layer color_palette: {color_palette!r}.")
            if color_mode is not None and color_mode not in valid_modes:
                raise DataLensConfigurationError(
                    f"Geo layer palette {color_palette!r} does not support color_mode={color_mode!r}. "
                    f"Supported: {sorted(valid_modes)}"
                )
        if dataset is not None:
            self._geo_add_dataset(dataset)
        self._geo_layers.append(
            {
                "id": str(uuid.uuid4()),
                "layer_type": layer_type,
                "geopoint": geopoint,
                "polygon": polygon,
                "polyline": polyline,
                "grouping": grouping,
                "size": size,
                "color": color,
                "color_mode": color_mode,
                "color_palette": color_palette,
                "color_reversed": color_reversed,
                "filters": tuple(filters),
                "tooltips": tuple(tooltips),
                "labels": tuple(labels),
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "alpha": alpha,
                "name": name,
                "dataset": dataset,
            }
        )
        return self

    def _map_center(self, *, lat: float, lon: float, zoom: int | None = None) -> Self:
        self._set_chart_setting("mapCenterMode", "manual")
        self._set_chart_setting("mapCenterValue", f"{lat},{lon}")
        if zoom is not None:
            self._set_chart_setting("zoomMode", "manual")
            self._set_chart_setting("zoomValue", zoom)
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
