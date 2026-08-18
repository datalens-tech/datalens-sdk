from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

from datalens_sdk._runtime.chart_constants import (
    VALID_GRADIENT_PALETTES,
    VALID_PALETTES,
    gradient_types_for_palette,
)
from datalens_sdk._runtime.chart_wire import build_background_settings, build_bars_settings
from datalens_sdk._wizard_encodings import WizardColorEncoding, WizardShapeEncoding
from datalens_sdk.errors import DataLensConfigurationError

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import (
        DiscretePaletteId,
        GradientPaletteId,
        MeasureFormat,
        PaletteId,
        ShapeStyle,
    )
    from datalens_sdk.domain.fields import FieldLike


class _ChartMutationsMixin:
    def _init_chart_mutations(self) -> None:
        self._chart_settings: dict[str, object] = {}
        self._slot_settings: dict[str, dict[str, object]] = {}
        self._slot_fields: dict[str, list[FieldLike | str]] = {}
        self._item_mutations: list[tuple[FieldLike | str, str, object]] = []
        self._pending_filters: list[tuple[FieldLike | str, str, list[str]]] = []
        self._sort_direction_items: list[tuple[FieldLike | str, str]] = []
        self._colors_palette: str | None = None
        self._colors_config_patch: dict[str, object] = {}
        self._color_encoding: WizardColorEncoding | None = None
        self._description: str | None = None
        self._hierarchies: list[dict[str, object]] = []
        self._pending_measure_formats: list[tuple[FieldLike | str, MeasureFormat]] = []
        self._shape_encoding: WizardShapeEncoding | None = None
        self._geopoints_config: dict[str, object] = {}

    def _set_palette(self, *, id: PaletteId) -> None:
        if id not in VALID_PALETTES:
            raise DataLensConfigurationError(f"Unknown palette {id!r}. Valid palettes: {sorted(VALID_PALETTES)}")
        self._colors_palette = id

    def _set_color_by_dimension(self, field: FieldLike | str) -> None:
        self._color_encoding = WizardColorEncoding(kind="dimension", field=field)

    def _set_color_by_measure(
        self,
        field: FieldLike | str,
        *,
        mode: Literal["2-point", "3-point"] | None,
        palette: GradientPaletteId | None,
        reversed: bool | None,
    ) -> None:
        if palette is not None and palette not in VALID_GRADIENT_PALETTES:
            raise DataLensConfigurationError(
                f"color_by_measure: palette must be a gradient palette, got {palette!r}. "
                f"Valid: {sorted(VALID_GRADIENT_PALETTES)}"
            )
        if palette is not None and mode is not None:
            valid_types = gradient_types_for_palette(palette)
            if mode not in valid_types:
                raise DataLensConfigurationError(
                    f"color_by_measure: palette {palette!r} does not support mode={mode!r}. "
                    f"Supported: {sorted(valid_types)}"
                )
        self._color_encoding = WizardColorEncoding(
            kind="measure",
            field=field,
            gradient_mode=mode,
            gradient_palette=palette,
            reversed=reversed,
        )

    def _set_color_by_measure_name(
        self,
        colors_map: Mapping[FieldLike | str, str] | None,
    ) -> None:
        self._color_encoding = WizardColorEncoding(
            kind="measure_name",
            colors_map=dict(colors_map) if colors_map is not None else {},
        )

    def _set_shape_by_dimension(
        self,
        field: FieldLike | str,
        shapes_map: Mapping[str, ShapeStyle] | None,
    ) -> None:
        self._shape_encoding = WizardShapeEncoding(
            kind="dimension",
            field=field,
            shapes_map=cast("Mapping[FieldLike | str, ShapeStyle] | None", shapes_map),
        )

    def _set_shape_by_measure_name(
        self,
        shapes_map: Mapping[FieldLike | str, ShapeStyle] | None,
    ) -> None:
        self._shape_encoding = WizardShapeEncoding(kind="measure_name", shapes_map=shapes_map)

    def _build_column_background_settings(
        self,
        *,
        mode: str,
        palette: GradientPaletteId,
        reversed: bool,
        thresholds: tuple[float, ...] | None,
    ) -> dict[str, object]:
        if palette not in VALID_GRADIENT_PALETTES:
            raise DataLensConfigurationError(
                f"column_background: palette must be a gradient palette, got {palette!r}. "
                f"Valid: {sorted(VALID_GRADIENT_PALETTES)}"
            )
        if thresholds is not None:
            expected = 2 if mode == "2-point" else 3
            if len(thresholds) != expected:
                raise DataLensConfigurationError(
                    f"column_background(mode={mode!r}) requires exactly {expected} thresholds, got {len(thresholds)}."
                )
        return build_background_settings(mode=mode, palette=palette, reversed=reversed, thresholds=thresholds)

    def _build_column_bars_settings(
        self,
        *,
        enabled: bool,
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
        show_labels: bool,
        show_in_totals: bool,
        align: str,
    ) -> dict[str, object]:
        if color_type == "gradient":
            if gradient_palette is None:
                raise DataLensConfigurationError(
                    "column_bars(color_type='gradient') requires gradient_palette= to be specified."
                )
            palette_str = str(gradient_palette)
            valid_types = gradient_types_for_palette(palette_str)
            if not valid_types:
                raise DataLensConfigurationError(
                    f"column_bars: palette {palette_str!r} is not supported for gradient bars. "
                    "Use a sequential or diverging gradient palette."
                )
            if gradient_type not in valid_types:
                raise DataLensConfigurationError(
                    f"column_bars: palette {palette_str!r} does not support gradient_type={gradient_type!r}. "
                    f"Supported: {sorted(valid_types)}"
                )
        if color_type == "one-color":
            _incompatible = {
                "color_positive": color_positive,
                "color_negative": color_negative,
                "positive_color_index": positive_color_index,
                "negative_color_index": negative_color_index,
                "gradient_palette": gradient_palette,
            }
            bad = [k for k, v in _incompatible.items() if v is not None]
            if bad:
                raise DataLensConfigurationError(
                    f"column_bars(color_type='one-color') does not accept: {', '.join(bad)}."
                )
        elif color_type == "two-color":
            _incompatible2 = {
                "color": color,
                "palette": palette,
                "color_index": color_index,
                "gradient_palette": gradient_palette,
            }
            bad2 = [k for k, v in _incompatible2.items() if v is not None]
            if bad2:
                raise DataLensConfigurationError(
                    f"column_bars(color_type='two-color') does not accept: {', '.join(bad2)}."
                )
        elif color_type == "gradient":
            _incompatible3 = {
                "color": color,
                "palette": palette,
                "color_index": color_index,
                "color_positive": color_positive,
                "color_negative": color_negative,
                "positive_color_index": positive_color_index,
                "negative_color_index": negative_color_index,
            }
            bad3 = [k for k, v in _incompatible3.items() if v is not None]
            if bad3:
                raise DataLensConfigurationError(
                    f"column_bars(color_type='gradient') does not accept: {', '.join(bad3)}."
                )
        return build_bars_settings(
            enabled=enabled,
            color_type=color_type,
            color=color,
            palette=str(palette) if palette is not None else None,
            color_index=color_index,
            color_positive=color_positive,
            color_negative=color_negative,
            positive_color_index=positive_color_index,
            negative_color_index=negative_color_index,
            gradient_palette=str(gradient_palette) if gradient_palette is not None else None,
            gradient_type=gradient_type,
            reversed=reversed,
            show_labels=show_labels,
            show_in_totals=show_in_totals,
            align=align,
        )
