"""QL visualization wire specifications.

QL charts use their own placeholder-based transport contract. Wizard document
semantics live in :mod:`datalens_sdk._runtime.wizard_semantics`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import QLCast


def build_ql_item(name: str, cast: QLCast) -> dict[str, object]:
    """Build a QL placeholder ``item`` with the constant structure observed
    across all live QL reference charts.

    Only ``guid``/``title`` (the SQL column name) and ``cast``/``data_type``
    vary; everything else is constant (``type="DIMENSION"``, synthetic
    ``datasetId="ql-mocked-dataset"``).
    """
    return {
        "guid": name,
        "title": name,
        "datasetId": "ql-mocked-dataset",
        "data_type": cast,
        "cast": cast,
        "type": "DIMENSION",
        "calc_mode": "direct",
        "inspectHidden": True,
        "formulaHidden": True,
        "noEdit": True,
    }


def _ql_x_placeholder(*, required: bool = True, capacity: int = 1) -> dict[str, object]:
    return {
        "allowedTypes": {},
        "allowedDataTypes": {},
        "id": "x",
        "type": "x",
        "title": "section_x",
        "iconProps": {},
        "required": required,
        "capacity": capacity,
        "settings": {
            "title": "off",
            "titleValue": "",
            "type": "linear",
            "grid": "on",
            "gridStep": "auto",
            "gridStepValue": 50,
            "hideLabels": "no",
            "labelsView": "auto",
            "holidays": "off",
            "axisLabelDateFormat": "DD.MM.YYYY",
            "axisLabelFormating": {},
            "axisFormatMode": "auto",
            "axisModeMap": {"dttm": "discrete"},
            "axisVisibility": "show",
            "disableAxisMode": True,
        },
    }


def _ql_x_placeholder_no_settings() -> dict[str, object]:
    """Horizontal-bar-style X placeholder (measure axis, no date settings)."""
    return {
        "allowedTypes": {},
        "allowedFinalTypes": {},
        "allowedDataTypes": {},
        "id": "x",
        "type": "x",
        "title": "section_x",
        "iconProps": {},
        "settings": {
            "scale": "auto",
            "scaleValue": "min-max",
            "title": "off",
            "titleValue": "",
            "type": "linear",
            "grid": "on",
            "gridStep": "auto",
            "gridStepValue": 50,
            "hideLabels": "no",
            "labelsView": "auto",
            "nulls": "ignore",
            "holidays": "off",
            "axisLabelDateFormat": "DD.MM.YYYY",
            "axisLabelFormating": {},
            "axisFormatMode": "auto",
            "axisVisibility": "show",
        },
    }


def _ql_y_placeholder(*, required: bool = False, capacity: int = 2) -> dict[str, object]:
    return {
        "allowedTypes": {},
        "allowedDataTypes": {},
        "id": "y",
        "type": "y",
        "title": "section_y",
        "iconProps": {},
        "required": required,
        "capacity": capacity,
        "settings": {
            "title": "off",
            "titleValue": "",
            "type": "linear",
            "grid": "on",
            "gridStep": "auto",
            "gridStepValue": 50,
            "hideLabels": "no",
            "labelsView": "auto",
            "axisLabelDateFormat": "DD.MM.YYYY",
            "axisLabelFormating": {},
            "axisFormatMode": "auto",
            "axisModeMap": {"dttm": "discrete"},
            "axisVisibility": "show",
            "disableAxisMode": True,
        },
    }


def _ql_y_measure_placeholder(*, pid: str = "y", title: str = "section_y", nulls: str = "ignore") -> dict[str, object]:
    """Measure-axis Y placeholder (scale/nulls, no date settings)."""
    return {
        "allowedTypes": {},
        "allowedFinalTypes": {},
        "allowedDataTypes": {},
        "id": pid,
        "type": pid,
        "title": title,
        "iconProps": {},
        "settings": {
            "scale": "auto",
            "scaleValue": "min-max",
            "title": "off",
            "titleValue": "",
            "type": "linear",
            "grid": "on",
            "gridStep": "auto",
            "gridStepValue": 50,
            "hideLabels": "no",
            "labelsView": "auto",
            "nulls": nulls,
            "axisLabelDateFormat": "DD.MM.YYYY",
            "axisLabelFormating": {},
            "axisFormatMode": "auto",
            "axisVisibility": "show",
        },
    }


def _ql_scatter_axis(pid: str, title: str) -> dict[str, object]:
    placeholder: dict[str, object] = {
        "allowedTypes": {},
        "allowedDataTypes": {},
        "capacity": 1,
        "iconProps": {},
        "id": pid,
        "required": True,
        "settings": {
            "scale": "auto",
            "scaleValue": "min-max",
            "title": "off",
            "titleValue": "",
            "type": "linear",
            "grid": "on",
            "gridStep": "auto",
            "gridStepValue": 50,
            "hideLabels": "no",
            "labelsView": "auto",
            "axisLabelDateFormat": "DD.MM.YYYY",
            "axisLabelFormating": {},
            "axisFormatMode": "auto",
            "axisVisibility": "show",
        },
        "title": title,
        "type": pid,
    }
    settings = cast(dict[str, object], placeholder["settings"])
    if pid == "x":
        settings["holidays"] = "off"
        settings["axisModeMap"] = {"dttm": "discrete"}
    else:
        placeholder["allowedFinalTypes"] = {}
    return placeholder


def _ql_dimension_placeholder(
    *,
    required: bool,
    capacity: int | None,
    title: str,
    allowed_final_types: bool = True,
    settings: bool = True,
) -> dict[str, object]:
    ph: dict[str, object] = {
        "allowedTypes": {},
        "allowedDataTypes": {},
        "id": "dimensions",
        "type": "dimensions",
        "title": title,
        "iconProps": {},
        "required": required,
    }
    if allowed_final_types:
        ph["allowedFinalTypes"] = {}
    if capacity is not None:
        ph["capacity"] = capacity
    if settings:
        ph["settings"] = {}
    return ph


def _ql_measure_placeholder(
    *,
    required: bool,
    capacity: int,
    title: str,
    settings: bool = True,
) -> dict[str, object]:
    ph: dict[str, object] = {
        "allowedTypes": {},
        "allowedFinalTypes": {},
        "allowedDataTypes": {},
        "id": "measures",
        "type": "measures",
        "title": title,
        "iconProps": {},
        "required": required,
        "capacity": capacity,
    }
    if settings:
        ph["settings"] = {}
    return ph


def _ql_color_placeholder(*, capacity: int = 1) -> dict[str, object]:
    return {
        "allowedTypes": {},
        "allowedDataTypes": {},
        "id": "colors",
        "type": "colors",
        "title": "section_color",
        "iconProps": {},
        "required": False,
        "capacity": capacity,
        "settings": {},
    }


def _ql_flat_table_columns_placeholder() -> dict[str, object]:
    return {
        "allowedTypes": {},
        "id": "flat-table-columns",
        "type": "flat-table-columns",
        "title": "section_columns",
        "iconProps": {},
        "required": True,
        "settings": {"groupping": "on"},
    }


def _ql_metric_colors_placeholder() -> dict[str, object]:
    return {
        "allowedTypes": {},
        "id": "colors",
        "type": "colors",
        "title": "section_colors",
        "iconProps": {},
    }


QL_VIZ_SPECS: dict[str, dict[str, object]] = {
    "line": {
        "viz": {
            "id": "line",
            "type": "line",
            "name": "label_visualization-line",
            "iconProps": {"id": "visLines", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowLabels": True,
            "allowSegments": False,
            "allowShapes": True,
            "colorsCapacity": 2,
            "shapesCapacity": 2,
            "availableLabelModes": ["absolute"],
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_x_placeholder(required=True, capacity=1),
            _ql_y_measure_placeholder(nulls="connect"),
            _ql_y_measure_placeholder(pid="y2", title="section_y2", nulls="connect"),
        ],
    },
    "area": {
        "viz": {
            "id": "area",
            "type": "line",
            "name": "label_visualization-area",
            "iconProps": {"id": "visArea", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowSegments": False,
            "allowLabels": True,
            "availableLabelModes": ["absolute"],
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_x_placeholder(required=True, capacity=1),
            _ql_y_measure_placeholder(nulls="as-0"),
        ],
    },
    "column": {
        "viz": {
            "id": "column",
            "type": "column",
            "name": "label_visualization-column",
            "iconProps": {"id": "visColumn", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowSegments": False,
            "allowLabels": True,
            "availableLabelModes": ["absolute"],
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_x_placeholder(required=False, capacity=2),
            _ql_y_measure_placeholder(nulls="ignore"),
        ],
    },
    "bar": {
        "viz": {
            "id": "bar",
            "type": "column",
            "name": "label_visualization-bar",
            "iconProps": {"id": "visBar", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowLabels": True,
            "availableLabelModes": ["absolute"],
            "allowSegments": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_y_placeholder(required=False, capacity=2),
            _ql_x_placeholder_no_settings(),
        ],
    },
    "column100p": {
        "viz": {
            "id": "column100p",
            "type": "column",
            "name": "label_visualization-column-100p",
            "iconProps": {"id": "visColumn100p", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowSegments": False,
            "allowLabels": True,
            "availableLabelModes": ["absolute", "percent"],
            "highchartsId": "column",
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_x_placeholder(required=False, capacity=2),
            _ql_y_measure_placeholder(nulls="ignore"),
        ],
    },
    "area100p": {
        "viz": {
            "id": "area100p",
            "type": "line",
            "name": "label_visualization-area-100p",
            "iconProps": {"id": "visArea100p", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowSegments": False,
            "allowLabels": True,
            "availableLabelModes": ["absolute", "percent"],
            "highchartsId": "area",
            "allowAvailable": True,
            "allowLayerFilters": False,
            "colorsCapacity": 2,
        },
        "placeholders": [
            _ql_x_placeholder(required=True, capacity=1),
            _ql_y_measure_placeholder(nulls="as-0"),
        ],
    },
    "bar100p": {
        "viz": {
            "id": "bar100p",
            "type": "column",
            "name": "label_visualization-bar-100p",
            "iconProps": {"id": "visBar100p", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowLabels": True,
            "availableLabelModes": ["absolute", "percent"],
            "highchartsId": "bar",
            "allowSegments": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_y_placeholder(required=False, capacity=2),
            _ql_x_placeholder_no_settings(),
        ],
    },
    "flatTable": {
        "viz": {
            "id": "flatTable",
            "type": "table",
            "name": "label_visualization-flat-table",
            "iconProps": {"id": "visFlatTable", "width": "24"},
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowSegments": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [_ql_flat_table_columns_placeholder()],
    },
    "metric": {
        "viz": {
            "id": "metric",
            "type": "metric",
            "name": "label_visualization-metric",
            "iconProps": {"id": "visMetric", "width": "24"},
            "allowFilters": False,
            "allowLabels": False,
            "allowSort": False,
            "allowSegments": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_measure_placeholder(required=True, capacity=1, title="section_measure", settings=False),
            _ql_metric_colors_placeholder(),
        ],
    },
    "scatter": {
        "viz": {
            "id": "scatter",
            "type": "line",
            "name": "label_visualization-scatter",
            "allowFilters": False,
            "allowColors": True,
            "allowSort": False,
            "allowSegments": False,
            "allowShapes": True,
            "iconProps": {"id": "visScatter", "width": "24"},
            "shapesCapacity": 1,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_scatter_axis("x", "section_x"),
            _ql_scatter_axis("y", "section_y"),
            {
                "allowedTypes": {},
                "allowedDataTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "points",
                "title": "section_points",
                "type": "points",
            },
            {
                "allowedTypes": {},
                "allowedFinalTypes": {},
                "allowedDataTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "size",
                "title": "section_points_size",
                "type": "measures",
            },
        ],
    },
    "treemap": {
        "viz": {
            "id": "treemap",
            "type": "treemap",
            "name": "label_visualization-treemap",
            "allowFilters": False,
            "iconProps": {"id": "visTreemap", "width": "24"},
            "allowColors": True,
            "allowSegments": False,
            "allowSort": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_dimension_placeholder(
                required=True,
                capacity=None,
                title="section_dimensions",
                allowed_final_types=False,
                settings=False,
            ),
            _ql_measure_placeholder(required=True, capacity=1, title="section_size", settings=False),
        ],
    },
    "pie": {
        "viz": {
            "id": "pie",
            "type": "pie",
            "name": "label_visualization-pie",
            "iconProps": {"id": "visPie", "width": "24"},
            "allowFilters": False,
            "allowLabels": True,
            "allowSort": False,
            "availableLabelModes": ["absolute", "percent"],
            "allowSegments": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_dimension_placeholder(required=False, capacity=1, title="section_categories"),
            _ql_color_placeholder(capacity=1),
            _ql_measure_placeholder(required=True, capacity=1, title="section_measures"),
        ],
    },
    "donut": {
        "viz": {
            "id": "donut",
            "type": "pie",
            "name": "label_visualization-donut",
            "iconProps": {"id": "visDonut", "width": "24"},
            "allowFilters": False,
            "allowLabels": True,
            "allowSort": False,
            "availableLabelModes": ["absolute", "percent"],
            "highchartsId": "pie",
            "hidden": False,
            "allowSegments": False,
            "allowAvailable": True,
            "allowLayerFilters": False,
        },
        "placeholders": [
            _ql_dimension_placeholder(required=False, capacity=1, title="section_categories"),
            _ql_color_placeholder(capacity=1),
            _ql_measure_placeholder(required=True, capacity=1, title="section_measures"),
        ],
    },
}


def get_ql_viz_spec(viz_id: str) -> dict[str, object]:
    """Return the QL viz spec by viz_id; empty dict if unknown."""
    return QL_VIZ_SPECS.get(viz_id, {})


def to_snake(wire_id: str) -> str:
    """Project a wire identifier onto a snake_case identifier.

    The viz-id (the canonical key in ``QL_VIZ_SPECS`` and the value of
    ``chart.visualization_id``) stays wire-shaped end-to-end. A separator is
    inserted before each capital letter (camelCase boundary) and before a run of
    digits that follows a letter, then the result is lowercased.

    ``flatTable`` -> ``flat_table``, ``area100p`` -> ``area_100p``,
    ``combined-chart`` -> ``combined_chart``, ``metric`` -> ``metric``.
    """
    s = wire_id.replace("-", "_")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Za-z])([0-9])", r"\1_\2", s)
    return s.lower()


_FACTORY_METHOD_OVERRIDES = {
    "metric": "indicator",
}


def factory_method_name(viz_id: str) -> str:
    """Return the DataLens UI-aligned factory method for a wire viz-id."""
    return _FACTORY_METHOD_OVERRIDES.get(viz_id, to_snake(viz_id))
