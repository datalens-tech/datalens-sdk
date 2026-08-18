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
from datalens_sdk._runtime.wizard_semantics import validate_slot_name, validate_visualization_transition
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
        self._target_visualization_type: str | None = None
        self._dataset_replacement: tuple[str, str] | None = None
        self._replace_formulas: dict[str, str] = {}
        self._new_hierarchies: list[dict[str, object]] = []
        self._local_field_additions: list[dict[str, object]] = []
        self._aggregation_field_replacements: dict[str, dict[str, object]] = {}
        self._init_chart_mutations()

    def _check_viz_applicability(self, method_name: str) -> None:
        validate_method_applicability(method_name, self.visualization_id or "")

    def _check_slot_applicability(self, *, method_name: str, slot_name: str) -> str:
        visualization_id = self.visualization_id or ""
        if visualization_id == "combined-chart" and slot_name == "x":
            return slot_name
        return validate_slot_name(
            method=method_name,
            visualization_type=visualization_id,
            slot_name=slot_name,
        )

    @property
    def chart(self) -> WizardChart:
        return self._chart

    @property
    def visualization_id(self) -> str | None:
        return self._target_visualization_type or self._chart.visualization_id

    @property
    def target_visualization_type(self) -> str | None:
        return self._target_visualization_type

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
    def slot_edits(self) -> Mapping[str, list[FieldRef]]:
        return self._slot_fields

    @property
    def chart_settings_edits(self) -> Mapping[str, object]:
        return self._chart_settings

    @property
    def slot_settings_edits(self) -> Mapping[str, Mapping[str, object]]:
        return self._slot_settings

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

    def _set_chart_setting(self, setting_key: str, value: object) -> Self:
        self._chart_settings[setting_key] = value
        return self

    def _set_slot_setting(self, method_name: str, slot_name: str, setting_key: str, value: object) -> Self:
        canonical_name = self._check_slot_applicability(method_name=method_name, slot_name=slot_name)
        self._slot_settings.setdefault(canonical_name, {})[setting_key] = value
        return self

    def legend(self, *, mode: Literal["show", "hide"]) -> Self:
        self._check_viz_applicability("legend")
        return self._set_chart_setting("legendMode", mode)

    def tooltip_sum(self, *, enabled: bool) -> Self:
        self._check_viz_applicability("tooltip_sum")
        return self._set_chart_setting("tooltipSum", "on" if enabled else "off")

    def totals(self, *, enabled: bool) -> Self:
        self._check_viz_applicability("totals")
        return self._set_chart_setting("totals", "on" if enabled else "off")

    def label_mode(self, *, mode: Literal["absolute", "percent"]) -> Self:
        self._check_viz_applicability("label_mode")
        return self._set_chart_setting("labelMode", mode)

    def labels_position(self, *, mode: Literal["inside", "outside", "auto"]) -> Self:
        self._check_viz_applicability("labels_position")
        return self._set_chart_setting("labelsPosition", mode)

    def tooltip_percentage_base(self, *, mode: Literal["auto", "first", "previous"]) -> Self:
        self._check_viz_applicability("tooltip_percentage_base")
        return self._set_chart_setting("tooltipPercentageBase", mode)

    def shape(self, *, value: FunnelShape) -> Self:
        self._check_viz_applicability("shape")
        return self._set_chart_setting("shape", value)

    def axis_visibility(self, slot_name: str, *, mode: Literal["show", "hide"]) -> Self:
        self._check_viz_applicability("axis_visibility")
        return self._set_slot_setting("axis_visibility", slot_name, "axisVisibility", mode)

    def hide_labels(self, slot_name: str, *, enabled: bool) -> Self:
        self._check_viz_applicability("hide_labels")
        return self._set_slot_setting("hide_labels", slot_name, "hideLabels", "yes" if enabled else "no")

    def nulls_mode(self, slot_name: str, *, mode: Literal["ignore", "connect", "as-0"]) -> Self:
        self._check_viz_applicability("nulls_mode")
        return self._set_slot_setting("nulls_mode", slot_name, "nulls", mode)

    def segments(self, fields: Sequence[FieldRef]) -> Self:
        self._check_viz_applicability("segments")
        return self._set_slot("segments", fields)

    def labels(self, fields: Sequence[FieldRef]) -> Self:
        self._check_viz_applicability("labels")
        return self._set_slot("labels", fields)

    def tooltips(self, fields: Sequence[FieldRef]) -> Self:
        self._check_viz_applicability("tooltips")
        return self._set_slot("tooltips", fields)

    def _mutate_item_by_guid(self, field: FieldRef, setting_key: str, value: object) -> Self:
        self._item_mutations.append((field, setting_key, value))
        return self

    def replace_formula(self, field: FieldRef, *, formula: str) -> Self:
        self._replace_formulas[_field_guid(field)] = formula
        return self

    def chart_title(self, *, text: str = "", mode: Literal["show", "hide"] = "show") -> Self:
        self._check_viz_applicability("chart_title")
        self._set_chart_setting("title", text)
        return self._set_chart_setting("titleMode", mode)

    def navigator(self, *, mode: Literal["show", "hide"]) -> Self:
        self._check_viz_applicability("navigator")
        current = self._chart_settings.get("navigatorSettings")
        settings = dict(current) if isinstance(current, Mapping) else {}
        settings["navigatorMode"] = mode
        return self._set_chart_setting("navigatorSettings", settings)

    def axis_title(self, slot_name: str, *, mode: Literal["off", "manual", "auto"], text: str = "") -> Self:
        self._check_viz_applicability("axis_title")
        self._set_slot_setting("axis_title", slot_name, "title", mode)
        if mode == "manual" and text:
            self._set_slot_setting("axis_title", slot_name, "titleValue", text)
        return self

    def axis_scale(
        self,
        slot_name: str,
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
        self._set_slot_setting("axis_scale", slot_name, "type", scale)
        self._set_slot_setting("axis_scale", slot_name, "scale", mode)
        if mode == "manual":
            self._set_slot_setting("axis_scale", slot_name, "scaleValue", [min, max])
        return self

    def grid(self, slot_name: str, *, enabled: bool, step: int | None = None) -> Self:
        self._check_viz_applicability("grid")
        self._set_slot_setting("grid", slot_name, "grid", "on" if enabled else "off")
        if step is not None:
            self._set_slot_setting("grid", slot_name, "gridStep", "manual")
            self._set_slot_setting("grid", slot_name, "gridStepValue", step)
        return self

    def pagination(self, *, enabled: bool, limit: int = 100) -> Self:
        self._check_viz_applicability("pagination")
        self._set_chart_setting("pagination", "on" if enabled else "off")
        if enabled:
            self._set_chart_setting("limit", limit)
        return self

    def table_size(self, *, size: Literal["s", "m", "l"]) -> Self:
        self._check_viz_applicability("table_size")
        return self._set_chart_setting("size", size)

    def freeze_columns(self, *, count: int = 1) -> Self:
        self._check_viz_applicability("freeze_columns")
        return self._set_chart_setting("pinnedColumns", count)

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
        return self._set_chart_setting("metricFontSize", INDICATOR_FONT_SIZE_UI_TO_PAYLOAD[size])

    def font_color(self, *, color: str) -> Self:
        self._check_viz_applicability("font_color")
        if not HEX_COLOR_RE.fullmatch(color):
            raise DataLensConfigurationError(f"font_color: color must be a hex string like #RRGGBB, got {color!r}")
        return self._set_chart_setting("metricFontColor", color)

    def measure_title_mode(self, *, mode: Literal["by-field", "manual", "hide"]) -> Self:
        self._check_viz_applicability("measure_title_mode")
        return self._set_chart_setting("indicatorTitleMode", mode)

    def mode(self, value: EntryUpdateMode) -> Self:
        if value not in get_args(EntryUpdateMode):
            raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
        self._mode = value
        return self

    def change_visualization_to(self, *, visualization_id: str) -> Self:
        validate_visualization_transition(
            method="change_visualization_to",
            source_visualization_type=self.visualization_id or "",
            target_visualization_type=visualization_id,
        )
        self._target_visualization_type = visualization_id
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

    def _set_slot(self, slot_name: str, fields: Sequence[FieldRef]) -> Self:
        canonical_name = self._check_slot_applicability(method_name=slot_name, slot_name=slot_name)
        self._slot_fields[canonical_name] = list(fields)
        return self

    def x(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("x", fields)

    def y(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("y", fields)

    def y2(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("y2", fields)

    def columns(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("columns", fields)

    def rows(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("rows", fields)

    def measures(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("measures", fields)

    def points(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("points", fields)

    def size(self, fields: Sequence[FieldRef]) -> Self:
        return self._set_slot("size", fields)

    def execute(self) -> WizardChart:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_wizard_chart(self)
