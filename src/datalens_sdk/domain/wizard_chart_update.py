from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, get_args
import uuid

from typing_extensions import Self

from datalens_sdk._runtime.chart_constants import INDICATOR_FONT_SIZE_UI_TO_PAYLOAD
from datalens_sdk._runtime.chart_mutations import _ChartMutationsMixin
from datalens_sdk._runtime.chart_wire import build_date_interval, build_relative_date_interval
from datalens_sdk._runtime.method_specs import validate_method_applicability
from datalens_sdk._runtime.validators import HEX_COLOR_RE
from datalens_sdk._runtime.viz_specs import validate_placeholder_id
from datalens_sdk._runtime.wizard_visualization_transitions import validate_visualization_transition
from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
from datalens_sdk.domain.chart_types import (
    DiscretePaletteId,
    FilterOperation,
    FunnelShape,
    GradientPaletteId,
    MeasureFormat,
    PaletteId,
    ShapeStyle,
)
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.fields import DatasetField, FieldRef
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.wizard_chart import WizardChart

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


def _field_guid(field: FieldRef) -> str:
    return field.guid if isinstance(field, DatasetField) else field


class WizardChartUpdate(_ChartMutationsMixin):
    def __init__(self, *, chart: WizardChart, operations: ChartOperations | None) -> None:
        self._chart = chart
        self._operations = operations
        self._mode: EntryUpdateMode = "save"
        self._field_replacements: dict[str, FieldRef] = {}
        self._deleted_field_guids: set[str] = set()
        self._deleted_filter_guids: set[str] = set()
        self._new_viz_id: str | None = None
        self._dataset_replacement: tuple[str, str] | None = None
        self._placeholder_edits: dict[str, list[FieldRef]] = {}
        self._replace_formulas: dict[str, str] = {}
        self._new_hierarchies: list[dict[str, object]] = []
        self._local_field_additions: list[dict[str, object]] = []
        self._aggregation_field_replacements: dict[str, dict[str, object]] = {}
        self._init_chart_mutations()

    def _check_viz_applicability(self, method_name: str) -> None:
        validate_method_applicability(method_name, self.visualization_id or "")

    def _check_placeholder_applicability(self, *, method_name: str, placeholder_id: str) -> str:
        visualization_id = self.visualization_id or ""
        if visualization_id == "combined-chart" and placeholder_id == "x":
            return placeholder_id
        return validate_placeholder_id(
            method=method_name,
            visualization_id=visualization_id,
            placeholder_id=placeholder_id,
        )

    @property
    def chart(self) -> WizardChart:
        return self._chart

    @property
    def visualization_id(self) -> str | None:
        return self._new_viz_id or self._chart.visualization_id

    @property
    def mode_value(self) -> EntryUpdateMode:
        return self._mode

    @property
    def field_replacements(self) -> Mapping[str, FieldRef]:
        return self._field_replacements

    @property
    def deleted_field_guids(self) -> frozenset[str]:
        return frozenset(self._deleted_field_guids)

    @property
    def deleted_filter_guids(self) -> frozenset[str]:
        return frozenset(self._deleted_filter_guids)

    @property
    def dataset_replacement(self) -> tuple[str, str] | None:
        return self._dataset_replacement

    @property
    def placeholder_edits(self) -> Mapping[str, list[FieldRef]]:
        return self._placeholder_edits

    @property
    def extra_settings_edits(self) -> Mapping[str, object]:
        return self._extra_settings

    @property
    def ph_settings_edits(self) -> Mapping[str, Mapping[str, object]]:
        return self._ph_settings

    @property
    def data_fields_edits(self) -> Mapping[str, list[FieldRef]]:
        return self._data_fields

    @property
    def item_mutations(self) -> Sequence[tuple[FieldRef, str, object]]:
        return self._item_mutations

    @property
    def pending_filters(self) -> Sequence[tuple[FieldRef, str, list[str]]]:
        return self._pending_filters

    @property
    def sort_direction_items(self) -> Sequence[tuple[FieldRef, str]]:
        return self._sort_direction_items

    @property
    def colors_palette(self) -> str | None:
        return self._colors_palette

    @property
    def color_encoding(self) -> WizardColorEncoding | None:
        return self._color_encoding

    @property
    def pending_measure_formats(self) -> Sequence[tuple[FieldRef, MeasureFormat]]:
        return self._pending_measure_formats

    @property
    def shape_encoding(self) -> WizardShapeEncoding | None:
        return self._shape_encoding

    @property
    def geopoints_config(self) -> Mapping[str, object]:
        return self._geopoints_config

    @property
    def description_value(self) -> str | None:
        return self._description

    @property
    def formula_replacements(self) -> Mapping[str, str]:
        return self._replace_formulas

    @property
    def new_hierarchies(self) -> Sequence[Mapping[str, object]]:
        return self._new_hierarchies

    @property
    def local_field_additions(self) -> Sequence[Mapping[str, object]]:
        return self._local_field_additions

    @property
    def aggregation_field_replacements(self) -> Mapping[str, Mapping[str, object]]:
        return self._aggregation_field_replacements

    @property
    def explicit_colors(self) -> bool:
        return self._color_encoding is not None

    def _set_extra(self, setting_key: str, value: object) -> Self:
        self._extra_settings[setting_key] = value
        return self

    def _set_ph_setting(self, method_name: str, placeholder_id: str, setting_key: str, value: object) -> Self:
        self._check_placeholder_applicability(method_name=method_name, placeholder_id=placeholder_id)
        self._ph_settings.setdefault(placeholder_id, {})[setting_key] = value
        return self

    def _set_data_field(self, wire_key: str, fields: Sequence[FieldRef]) -> Self:
        self._data_fields[wire_key] = list(fields)
        return self

    def legend(self, *, mode: Literal["show", "hide"]) -> Self:
        self._check_viz_applicability("legend")
        return self._set_extra("legendMode", mode)

    def tooltip_sum(self, *, enabled: bool) -> Self:
        self._check_viz_applicability("tooltip_sum")
        return self._set_extra("tooltipSum", "on" if enabled else "off")

    def totals(self, *, enabled: bool) -> Self:
        self._check_viz_applicability("totals")
        return self._set_extra("totals", "on" if enabled else "off")

    def label_mode(self, *, mode: Literal["absolute", "percent"]) -> Self:
        self._check_viz_applicability("label_mode")
        return self._set_extra("labelMode", mode)

    def labels_position(self, *, mode: Literal["inside", "outside", "auto"]) -> Self:
        self._check_viz_applicability("labels_position")
        return self._set_extra("labelsPosition", mode)

    def tooltip_percentage_base(self, *, mode: Literal["auto", "first", "previous"]) -> Self:
        self._check_viz_applicability("tooltip_percentage_base")
        return self._set_extra("tooltipPercentageBase", mode)

    def shape(self, *, value: FunnelShape) -> Self:
        self._check_viz_applicability("shape")
        return self._set_extra("shape", value)

    def axis_visibility(self, ph_id: str, *, mode: Literal["show", "hide"]) -> Self:
        self._check_viz_applicability("axis_visibility")
        return self._set_ph_setting("axis_visibility", ph_id, "axisVisibility", mode)

    def hide_labels(self, ph_id: str, *, enabled: bool) -> Self:
        self._check_viz_applicability("hide_labels")
        return self._set_ph_setting("hide_labels", ph_id, "hideLabels", "yes" if enabled else "no")

    def nulls_mode(self, ph_id: str, *, mode: Literal["ignore", "connect", "as-0"]) -> Self:
        self._check_viz_applicability("nulls_mode")
        return self._set_ph_setting("nulls_mode", ph_id, "nulls", mode)

    def segments(self, fields: Sequence[FieldRef]) -> Self:
        self._check_viz_applicability("segments")
        return self._set_data_field("segments", fields)

    def labels(self, fields: Sequence[FieldRef]) -> Self:
        self._check_viz_applicability("labels")
        return self._set_data_field("labels", fields)

    def tooltips(self, fields: Sequence[FieldRef]) -> Self:
        self._check_viz_applicability("tooltips")
        return self._set_data_field("tooltips", fields)

    def _mutate_item_by_guid(self, field: FieldRef, setting_key: str, value: object) -> Self:
        self._item_mutations.append((field, setting_key, value))
        return self

    def replace_formula(self, field: FieldRef, *, formula: str) -> Self:
        self._replace_formulas[_field_guid(field)] = formula
        return self

    def chart_title(self, *, text: str = "", mode: Literal["show", "hide"] = "show") -> Self:
        self._check_viz_applicability("chart_title")
        self._set_extra("title", text)
        return self._set_extra("titleMode", mode)

    def navigator(self, *, mode: Literal["show", "hide"]) -> Self:
        self._check_viz_applicability("navigator")
        current = self._extra_settings.get("navigatorSettings")
        settings = dict(current) if isinstance(current, Mapping) else {}
        settings["navigatorMode"] = mode
        return self._set_extra("navigatorSettings", settings)

    def axis_title(self, ph_id: str, *, mode: Literal["off", "manual", "auto"], text: str = "") -> Self:
        self._check_viz_applicability("axis_title")
        self._set_ph_setting("axis_title", ph_id, "title", mode)
        if mode == "manual" and text:
            self._set_ph_setting("axis_title", ph_id, "titleValue", text)
        return self

    def axis_scale(
        self,
        ph_id: str,
        *,
        scale: Literal["linear", "logarithmic"] = "linear",
        mode: Literal["auto", "manual"] = "auto",
        min: str | None = None,
        max: str | None = None,
    ) -> Self:
        self._check_viz_applicability("axis_scale")
        if mode == "manual" and min is None and max is None:
            raise DataLensConfigurationError(
                "axis_scale(mode='manual') requires at least one of min= or max= to be specified."
            )
        self._set_ph_setting("axis_scale", ph_id, "type", scale)
        self._set_ph_setting("axis_scale", ph_id, "scale", mode)
        if mode == "manual":
            self._set_ph_setting("axis_scale", ph_id, "scaleValue", [min, max])
        return self

    def grid(self, ph_id: str, *, enabled: bool, step: int | None = None) -> Self:
        self._check_viz_applicability("grid")
        self._set_ph_setting("grid", ph_id, "grid", "on" if enabled else "off")
        if step is not None:
            self._set_ph_setting("grid", ph_id, "gridStep", "manual")
            self._set_ph_setting("grid", ph_id, "gridStepValue", step)
        return self

    def pagination(self, *, enabled: bool, limit: int = 100) -> Self:
        self._check_viz_applicability("pagination")
        self._set_extra("pagination", "on" if enabled else "off")
        if enabled:
            self._set_extra("limit", limit)
        return self

    def table_size(self, *, size: Literal["s", "m", "l"]) -> Self:
        self._check_viz_applicability("table_size")
        return self._set_extra("size", size)

    def freeze_columns(self, *, count: int = 1) -> Self:
        self._check_viz_applicability("freeze_columns")
        return self._set_extra("pinnedColumns", count)

    def description(self, text: str) -> Self:
        self._description = text
        return self

    def palette(self, *, id: PaletteId) -> Self:
        self._check_viz_applicability("palette")
        self._set_palette(id=id)
        return self

    def color_by_dimension(self, field: FieldRef) -> Self:
        self._check_viz_applicability("color_by_dimension")
        self._set_color_by_dimension(field)
        return self

    def color_by_measure(
        self,
        field: FieldRef,
        *,
        mode: Literal["2-point", "3-point"] | None = None,
        palette: GradientPaletteId | None = None,
        reversed: bool | None = None,
    ) -> Self:
        self._check_viz_applicability("color_by_measure")
        self._set_color_by_measure(field, mode=mode, palette=palette, reversed=reversed)
        return self

    def color_by_measure_name(self, *, colors_map: Mapping[FieldRef, str] | None = None) -> Self:
        self._check_viz_applicability("color_by_measure_name")
        self._set_color_by_measure_name(colors_map)
        return self

    def add_filter(self, field: FieldRef, *, operation: FilterOperation, values: Sequence[str] = ()) -> Self:
        self._check_viz_applicability("add_filter")
        self._pending_filters.append((field, operation, list(values)))
        return self

    def add_date_filter(self, field: FieldRef, *, start: str, end: str, inclusive_end: bool = True) -> Self:
        self._check_viz_applicability("add_date_filter")
        self._pending_filters.append((field, "BETWEEN", [build_date_interval(start, end, inclusive_end=inclusive_end)]))
        return self

    def add_relative_date_filter(self, field: FieldRef, *, start_offset: str, end_offset: str) -> Self:
        self._check_viz_applicability("add_relative_date_filter")
        self._pending_filters.append((field, "BETWEEN", [build_relative_date_interval(start_offset, end_offset)]))
        return self

    def add_sort(self, field: FieldRef, *, direction: Literal["asc", "desc"] = "asc") -> Self:
        self._check_viz_applicability("add_sort")
        self._sort_direction_items.append((field, direction))
        return self

    def add_hierarchy(
        self,
        title: str,
        fields: Sequence[FieldRef],
        *,
        guid: str | None = None,
    ) -> Self:
        self._check_viz_applicability("add_hierarchy")
        effective_guid = guid if guid is not None else str(uuid.uuid4())
        self._new_hierarchies.append({"guid": effective_guid, "title": title, "type": "PSEUDO", "fields": list(fields)})
        return self

    def add_local_field(
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
        from datalens_sdk._runtime.chart_builder_base import build_local_field_entry  # noqa: PLC0415

        entry = build_local_field_entry(
            title=title,
            formula=formula,
            guid=guid,
            cast=cast,
            measure=measure,
            aggregation=aggregation,
            formatting=formatting,
        )
        self._local_field_additions.append(entry)
        return self

    def add_aggregated_measure(
        self,
        field: DatasetField,
        *,
        aggregation: Literal["sum", "avg", "min", "max", "count", "countunique"],
        name: str | None = None,
        guid: str | None = None,
    ) -> Self:
        from datalens_sdk._runtime.chart_builder_base import build_aggregated_measure_entry  # noqa: PLC0415

        self._local_field_additions.append(
            build_aggregated_measure_entry(field, aggregation=aggregation, name=name, guid=guid)
        )
        return self

    def change_aggregation(
        self,
        field: DatasetField,
        *,
        aggregation: Literal["sum", "avg", "min", "max", "count", "countunique"],
        name: str,
        guid: str | None = None,
    ) -> Self:
        from datalens_sdk._runtime.chart_builder_base import stage_aggregation_change  # noqa: PLC0415

        stage_aggregation_change(
            self,
            field=field,
            aggregation=aggregation,
            name=name,
            guid=guid,
        )
        return self

    def measure_format(
        self,
        field: FieldRef,
        *,
        format: Literal["number", "percent", "currency"] | None = None,
        precision: int | None = None,
        unit: Literal["auto", "k", "m", "bln"] | None = None,
        prefix: str | None = None,
        postfix: str | None = None,
        show_rank_delimiter: bool | None = None,
    ) -> Self:
        self._check_viz_applicability("measure_format")
        formatting: MeasureFormat = {}
        if format is not None:
            formatting["format"] = format
        if precision is not None:
            formatting["precision"] = precision
        if unit is not None:
            formatting["unit"] = unit
        if prefix is not None:
            formatting["prefix"] = prefix
        if postfix is not None:
            formatting["postfix"] = postfix
        if show_rank_delimiter is not None:
            formatting["show_rank_delimiter"] = show_rank_delimiter
        self._pending_measure_formats.append((field, formatting))
        return self

    def column_background(
        self,
        field: FieldRef,
        *,
        mode: Literal["2-point", "3-point"] = "3-point",
        palette: GradientPaletteId = "red-orange-green",
        thresholds: tuple[float, ...] | None = None,
        reversed: bool = False,
    ) -> Self:
        self._check_viz_applicability("column_background")
        settings = self._build_column_background_settings(
            mode=mode,
            palette=palette,
            reversed=reversed,
            thresholds=thresholds,
        )
        return self._mutate_item_by_guid(field, "backgroundSettings", settings)

    def column_bars(
        self,
        field: FieldRef,
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
        self._check_viz_applicability("column_bars")
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

    def column_title(self, field: FieldRef, *, title: str) -> Self:
        self._check_viz_applicability("column_title")
        return self._mutate_item_by_guid(field, "_title_override", title)

    def subtotals(self, field: FieldRef, *, enabled: bool) -> Self:
        self._check_viz_applicability("subtotals")
        return self._mutate_item_by_guid(field, "subTotalsSettings", {"enabled": enabled})

    def shape_by_dimension(self, field: FieldRef, *, shapes_map: Mapping[str, ShapeStyle] | None = None) -> Self:
        self._check_viz_applicability("shape_by_dimension")
        self._set_shape_by_dimension(field, shapes_map)
        return self

    def shape_by_measure_name(self, *, shapes_map: Mapping[FieldRef, ShapeStyle] | None = None) -> Self:
        self._check_viz_applicability("shape_by_measure_name")
        self._set_shape_by_measure_name(shapes_map)
        return self

    def point_size_range(self, *, min_radius: float = 4.5, max_radius: float = 9.0) -> Self:
        self._check_viz_applicability("point_size_range")
        self._geopoints_config = {
            "radius": (min_radius + max_radius) / 2,
            "minRadius": min_radius,
            "maxRadius": max_radius,
        }
        return self

    def font_size(self, *, size: Literal["xs", "s", "m", "l"]) -> Self:
        self._check_viz_applicability("font_size")
        return self._set_extra("metricFontSize", INDICATOR_FONT_SIZE_UI_TO_PAYLOAD[size])

    def font_color(self, *, color: str) -> Self:
        self._check_viz_applicability("font_color")
        if not HEX_COLOR_RE.fullmatch(color):
            raise DataLensConfigurationError(f"font_color: color must be a hex string like #RRGGBB, got {color!r}")
        return self._set_extra("metricFontColor", color)

    def measure_title_mode(self, *, mode: Literal["by-field", "manual", "hide"]) -> Self:
        self._check_viz_applicability("measure_title_mode")
        return self._set_extra("indicatorTitleMode", mode)

    def mode(self, value: EntryUpdateMode) -> Self:
        if value not in get_args(EntryUpdateMode):
            raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
        self._mode = value
        return self

    def change_visualization_to(self, *, visualization_id: str) -> Self:
        source_visualization_id = self.visualization_id or ""
        validate_visualization_transition(
            method="change_visualization_to",
            source_visualization_id=source_visualization_id,
            target_visualization_id=visualization_id,
        )
        self._new_viz_id = visualization_id
        return self

    def replace_field(self, old: FieldRef, new: FieldRef) -> Self:
        self._field_replacements[_field_guid(old)] = new
        return self

    def delete_field(self, field: FieldRef) -> Self:
        self._deleted_field_guids.add(_field_guid(field))
        return self

    def replace_dataset(self, *, old: str, new: str) -> Self:
        self._dataset_replacement = (old, new)
        return self

    def delete_filter(self, field: FieldRef) -> Self:
        self._deleted_filter_guids.add(_field_guid(field))
        return self

    def _set_placeholder(self, placeholder_id: str, fields: Sequence[FieldRef]) -> Self:
        self._check_placeholder_applicability(method_name=placeholder_id, placeholder_id=placeholder_id)
        self._placeholder_edits[placeholder_id] = list(fields)
        return self

    def x(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("x", fields)

    def y(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("y", fields)

    def y2(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("y2", fields)

    def columns(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("columns", fields)

    def rows(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("rows", fields)

    def measures(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("measures", fields)

    def points(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("points", fields)

    def size(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_placeholder("size", fields)

    def execute(self) -> WizardChart:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_wizard_chart(self)
