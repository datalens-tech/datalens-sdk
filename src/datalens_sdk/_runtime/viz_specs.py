from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, TypedDict, cast

from datalens_sdk.errors import DataLensConfigurationError

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import QLCast

WizardEncoding = Literal["color", "shape"]
WizardEncodingBinding = Literal["dimension", "measure", "measure_name"]
WizardEncodingTarget = Literal["data", "placeholder"]


class WizardEncodingRule(TypedDict, total=False):
    target: WizardEncodingTarget
    placeholder: str
    copy_to_data: bool
    requires_field_in: str
    implicit_from: str
    measure_placeholders: tuple[str, ...]
    category_placeholder: str


_X_AXIS_SETTINGS_LINEAR: dict[str, object] = {
    "axisFormatMode": "auto",
    "axisLabelDateFormat": "DD.MM.YYYY",
    "axisLabelFormating": {},
    "axisModeMap": {},
    "axisVisibility": "show",
    "grid": "off",
    "gridStep": "auto",
    "gridStepValue": 50,
    "hideLabels": "no",
    "holidays": "off",
    "labelsView": "auto",
    "title": "off",
    "titleValue": "",
    "type": "linear",
}

_Y_AXIS_SETTINGS_LINEAR: dict[str, object] = {
    "axisFormatMode": "auto",
    "axisLabelDateFormat": "DD.MM.YYYY",
    "axisLabelFormating": {},
    "axisVisibility": "show",
    "grid": "on",
    "gridStep": "auto",
    "gridStepValue": 50,
    "hideLabels": "no",
    "labelsView": "auto",
    "nulls": "ignore",
    "scale": "auto",
    "scaleValue": "min-max",
    "title": "off",
    "titleValue": "",
    "type": "linear",
}


def _x_placeholder_linear(
    capacity: int = 1,
    required: bool = True,
    title: str = "section_x",
) -> dict[str, object]:
    return {
        "allowedDataTypes": {},
        "allowedTypes": {},
        "capacity": capacity,
        "iconProps": {},
        "id": "x",
        "required": required,
        "settings": dict(_X_AXIS_SETTINGS_LINEAR),
        "title": title,
        "type": "x",
    }


def _y_placeholder_linear(
    pid: str = "y",
    title: str = "section_y",
    nulls: str = "ignore",
    capacity: int | None = None,
) -> dict[str, object]:
    settings = dict(_Y_AXIS_SETTINGS_LINEAR)
    settings["nulls"] = nulls
    ph: dict[str, object] = {
        "allowedDataTypes": {},
        "allowedFinalTypes": {},
        "allowedTypes": {},
        "iconProps": {},
        "id": pid,
        "settings": settings,
        "title": title,
        "type": pid,
    }
    if capacity is not None:
        ph["capacity"] = capacity
    return ph


VIZ_SPECS: dict[str, dict[str, object]] = {
    "metric": {
        "wire_type": "metric_wizard_node",
        "golden_id": "u6vchqqsj10ce",
        "viz": {
            "id": "metric",
            "type": "metric",
            "name": "label_visualization-metric",
            "iconProps": {"id": "visMetric", "width": "24"},
            "allowFilters": True,
            "allowLabels": False,
            "allowLayerFilters": False,
            "allowSort": False,
        },
        "placeholders": {
            "measures": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "measures",
                "required": True,
                "settings": {"axisModeMap": {}},
                "title": "section_measure",
                "type": "measures",
            },
            "colors": {
                "allowedTypes": {},
                "iconProps": {},
                "id": "colors",
                "settings": {},
                "title": "section_colors",
                "type": "colors",
            },
        },
        "placeholder_aliases": {"y": "measures"},
    },
    "line": {
        "wire_type": "d3_wizard_node",
        "golden_id": "xzije0qq2rteh",
        "measure_placeholder": "y",
        "encodings": {
            "color": {
                "dimension": {"target": "data"},
                "measure_name": {
                    "target": "data",
                    "measure_placeholders": ("y", "y2"),
                },
            },
            "shape": {
                "dimension": {"target": "data"},
                "measure_name": {
                    "target": "data",
                    "measure_placeholders": ("y", "y2"),
                },
            },
        },
        "viz": {
            "id": "line",
            "type": "line",
            "name": "label_visualization-line",
            "iconProps": {"id": "visLines", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSegments": True,
            "allowShapes": True,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
            "colorsCapacity": 1,
            "shapesCapacity": 1,
        },
        "placeholders": {
            "x": _x_placeholder_linear(capacity=1, required=True),
            "y": _y_placeholder_linear(pid="y", title="section_y", nulls="connect"),
            "y2": _y_placeholder_linear(pid="y2", title="section_y2", nulls="connect"),
            "shapes": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "shapes",
                "required": False,
                "settings": {},
                "title": "section_shapes",
                "type": "shapes",
            },
        },
        "placeholder_aliases": {},
    },
    "column": {
        "wire_type": "d3_wizard_node",
        "golden_id": "57qrvb08760yp",
        "measure_placeholder": "y",
        "encodings": {
            "color": {
                "dimension": {"target": "data"},
                "measure": {"target": "data"},
                "measure_name": {
                    "target": "data",
                    "measure_placeholders": ("y",),
                    "category_placeholder": "x",
                },
            },
        },
        "viz": {
            "id": "column",
            "type": "column",
            "name": "label_visualization-column",
            "iconProps": {"id": "visColumn", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowSegments": True,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
        },
        "placeholders": {
            "x": _x_placeholder_linear(capacity=2, required=False),
            "y": _y_placeholder_linear(pid="y", title="section_y", nulls="ignore"),
        },
        "placeholder_aliases": {},
    },
    "bar": {
        "wire_type": "graph_wizard_node",
        "golden_id": "yv9hywpbevyok",
        "requires_x_measure_autofix": True,
        "measure_placeholder": "x",
        "encodings": {
            "color": {
                "dimension": {"target": "data"},
                "measure": {"target": "data"},
                "measure_name": {
                    "target": "data",
                    "measure_placeholders": ("x",),
                    "category_placeholder": "y",
                },
            },
        },
        "viz": {
            "id": "bar",
            "type": "column",
            "name": "label_visualization-bar",
            "iconProps": {"id": "visBar", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
            "colorsCapacity": 2,
        },
        "placeholders": {
            "y": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 2,
                "iconProps": {},
                "id": "y",
                "required": False,
                "settings": {
                    "axisFormatMode": "auto",
                    "axisModeMap": {},
                    "axisVisibility": "show",
                    "grid": "off",
                    "gridStep": "auto",
                    "gridStepValue": 50,
                    "hideLabels": "no",
                    "labelsView": "auto",
                    "title": "off",
                    "titleValue": "",
                    "type": "linear",
                },
                "title": "section_y",
                "type": "y",
            },
            "x": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "iconProps": {},
                "id": "x",
                "settings": {
                    "axisFormatMode": "auto",
                    "axisVisibility": "show",
                    "grid": "off",
                    "gridStep": "auto",
                    "gridStepValue": 50,
                    "hideLabels": "yes",
                    "holidays": "off",
                    "labelsView": "auto",
                    "nulls": "ignore",
                    "scale": "auto",
                    "scaleValue": "min-max",
                    "title": "off",
                    "titleValue": "",
                    "type": "linear",
                },
                "title": "section_x",
                "type": "x",
            },
        },
        "placeholder_aliases": {},
    },
    "area": {
        "wire_type": "d3_wizard_node",
        "golden_id": "57qx9qyk8x4yp",
        "measure_placeholder": "y",
        "encodings": {
            "color": {
                "dimension": {"target": "data"},
            },
        },
        "viz": {
            "id": "area",
            "type": "line",
            "name": "label_visualization-area",
            "iconProps": {"id": "visArea", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSegments": True,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
        },
        "placeholders": {
            "x": _x_placeholder_linear(capacity=1, required=True),
            "y": _y_placeholder_linear(pid="y", title="section_y", nulls="as-0", capacity=1),
        },
        "placeholder_aliases": {},
    },
    "area100p": {
        "wire_type": "d3_wizard_node",
        "golden_id": "bndh47mfddnqv",
        "measure_placeholder": "y",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                },
            },
        },
        "viz": {
            "id": "area100p",
            "type": "line",
            "name": "label_visualization-area-100p",
            "iconProps": {"id": "visArea100p", "width": "24"},
            "highchartsId": "area",
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSegments": True,
            "allowSort": True,
            "availableLabelModes": ["absolute", "percent"],
        },
        "placeholders": {
            "x": _x_placeholder_linear(capacity=1, required=True),
            "y": _y_placeholder_linear(pid="y", title="section_y", nulls="as-0", capacity=1),
            "colors": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
        },
        "placeholder_aliases": {},
    },
    "column100p": {
        "wire_type": "graph_wizard_node",
        "golden_id": "eg56c4cumyzcy",
        "measure_placeholder": "y",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                },
            },
        },
        "viz": {
            "id": "column100p",
            "type": "column",
            "name": "label_visualization-column-100p",
            "iconProps": {"id": "visColumn100p", "width": "24"},
            "highchartsId": "column",
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSegments": True,
            "allowSort": True,
            "availableLabelModes": ["absolute", "percent"],
        },
        "placeholders": {
            "x": _x_placeholder_linear(capacity=2, required=False),
            "y": _y_placeholder_linear(pid="y", title="section_y", nulls="ignore", capacity=1),
            "colors": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
        },
        "placeholder_aliases": {},
    },
    "bar100p": {
        "wire_type": "graph_wizard_node",
        "golden_id": "94yprmepstny1",
        "requires_x_measure_autofix": True,
        "measure_placeholder": "x",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                },
            },
        },
        "viz": {
            "id": "bar100p",
            "type": "column",
            "name": "label_visualization-bar-100p",
            "iconProps": {"id": "visBar100p", "width": "24"},
            "highchartsId": "bar",
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSort": True,
            "availableLabelModes": ["absolute", "percent"],
        },
        "placeholders": {
            "y": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 2,
                "iconProps": {},
                "id": "y",
                "required": False,
                "settings": {
                    "axisFormatMode": "auto",
                    "axisModeMap": {},
                    "axisVisibility": "show",
                    "grid": "off",
                    "gridStep": "auto",
                    "gridStepValue": 50,
                    "hideLabels": "no",
                    "labelsView": "auto",
                    "title": "off",
                    "titleValue": "",
                    "type": "linear",
                },
                "title": "section_y",
                "type": "y",
            },
            "x": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "x",
                "settings": {
                    "axisFormatMode": "auto",
                    "axisVisibility": "show",
                    "grid": "off",
                    "gridStep": "auto",
                    "gridStepValue": 50,
                    "hideLabels": "yes",
                    "holidays": "off",
                    "labelsView": "auto",
                    "nulls": "ignore",
                    "scale": "auto",
                    "scaleValue": "min-max",
                    "title": "off",
                    "titleValue": "",
                    "type": "linear",
                },
                "title": "section_x",
                "type": "x",
            },
            "colors": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
        },
        "placeholder_aliases": {},
    },
    "donut": {
        "wire_type": "d3_wizard_node",
        "golden_id": "je8zp7ycsdx2b",
        "measure_placeholder": "measures",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "implicit_from": "dimensions",
                },
            },
        },
        "viz": {
            "id": "donut",
            "type": "pie",
            "name": "label_visualization-donut",
            "iconProps": {"id": "visDonut", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowSort": True,
            "availableLabelModes": ["absolute", "percent"],
            "allowLayerFilters": False,
            "highchartsId": "pie",
            "hidden": False,
        },
        "placeholders": {
            "dimensions": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "dimensions",
                "required": False,
                "settings": {},
                "title": "section_categories",
                "type": "dimensions",
            },
            "colors": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
            "measures": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "measures",
                "required": True,
                "settings": {},
                "title": "section_measures",
                "type": "measures",
            },
        },
        "placeholder_aliases": {"x": "dimensions", "y": "measures"},
    },
    "funnel": {
        "wire_type": "d3_wizard_node",
        "golden_id": "5v9tonl3zaogo",
        "measure_placeholder": "measures",
        "encodings": {
            "color": {
                "dimension": {"target": "data"},
            },
        },
        "viz": {
            "id": "funnel",
            "type": "funnel",
            "name": "label_visualization-funnel",
            "iconProps": {"id": "visFunnel", "width": "24"},
            "allowColors": True,
            "allowLabels": True,
            "availableLabelModes": ["absolute", "percent"],
            "allowFilters": True,
            "allowSort": True,
            "allowLayerFilters": False,
        },
        "placeholders": {
            "dimensions": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "dimensions",
                "required": True,
                "settings": {},
                "title": "section_categories",
                "type": "dimensions",
            },
            "measures": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "iconProps": {},
                "id": "measures",
                "required": True,
                "settings": {},
                "title": "section_measures",
                "type": "measures",
            },
        },
        "placeholder_aliases": {"x": "dimensions", "y": "measures"},
    },
    "treemap": {
        "wire_type": "graph_wizard_node",
        "golden_id": "vqkbipjv1jj6n",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                    "requires_field_in": "dimensions",
                },
                "measure": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                },
            },
        },
        "viz": {
            "id": "treemap",
            "type": "treemap",
            "name": "label_visualization-treemap",
            "iconProps": {"id": "visTreemap", "width": "24"},
            "allowFilters": True,
            "allowColors": True,
            "allowSort": False,
            "allowLayerFilters": False,
        },
        "placeholders": {
            "dimensions": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": -1,
                "iconProps": {},
                "id": "dimensions",
                "required": True,
                "settings": {},
                "title": "section_dimensions",
                "type": "dimensions",
            },
            "measures": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "measures",
                "required": True,
                "settings": {},
                "title": "section_size",
                "type": "measures",
            },
            "colors": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
        },
        "placeholder_aliases": {"x": "dimensions", "y": "measures", "color": "colors"},
    },
    "scatter": {
        "wire_type": "graph_wizard_node",
        "golden_id": "je8z32m90gr2b",
        "measure_placeholder": "y",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                },
                "measure": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "copy_to_data": True,
                },
            },
            "shape": {
                "dimension": {"target": "data"},
            },
        },
        "viz": {
            "id": "scatter",
            "type": "line",
            "name": "label_visualization-scatter",
            "iconProps": {"id": "visScatter", "width": "24"},
            "allowFilters": True,
            "allowColors": True,
            "allowSort": True,
            "allowLayerFilters": False,
            "colorsCapacity": 1,
            "shapesCapacity": 1,
            "allowShapes": True,
        },
        "placeholders": {
            "x": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "x",
                "required": True,
                "settings": {
                    "scale": "auto",
                    "scaleValue": "min-max",
                    "title": "off",
                    "titleValue": "",
                    "type": "linear",
                    "grid": "off",
                    "gridStep": "auto",
                    "gridStepValue": 50,
                    "hideLabels": "no",
                    "labelsView": "auto",
                    "axisModeMap": {},
                },
                "title": "section_x",
                "type": "x",
            },
            "y": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "y",
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
                },
                "title": "section_y",
                "type": "y",
            },
            "points": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "points",
                "required": False,
                "settings": {},
                "title": "section_points",
                "type": "points",
            },
            "size": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "size",
                "required": False,
                "settings": {},
                "title": "section_points_size",
                "type": "measures",
            },
            "colors": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
            "shapes": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "shapes",
                "required": False,
                "settings": {},
                "title": "section_shapes",
                "type": "shapes",
            },
        },
        "placeholder_aliases": {},
    },
    "pie": {
        "wire_type": "d3_wizard_node",
        "golden_id": "jp2baplb3kgq3",
        "measure_placeholder": "measures",
        "encodings": {
            "color": {
                "dimension": {
                    "target": "placeholder",
                    "placeholder": "colors",
                    "implicit_from": "dimensions",
                },
            },
        },
        "viz": {
            "id": "pie",
            "type": "pie",
            "name": "label_visualization-pie",
            "iconProps": {"id": "visPie", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": False,
            "allowSort": True,
            "availableLabelModes": ["absolute", "percent"],
        },
        "placeholders": {
            "dimensions": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "dimensions",
                "required": False,
                "settings": {},
                "title": "section_categories",
                "type": "dimensions",
            },
            "colors": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "colors",
                "required": False,
                "settings": {},
                "title": "section_color",
                "type": "colors",
            },
            "measures": {
                "allowedDataTypes": {},
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "capacity": 1,
                "iconProps": {},
                "id": "measures",
                "required": True,
                "settings": {},
                "title": "section_measures",
                "type": "measures",
            },
        },
        "placeholder_aliases": {
            "x": "dimensions",
            "y": "measures",
        },
    },
    "flatTable": {
        "wire_type": "table_wizard_node",
        "golden_id": "02mq3desnnh8k",
        "encodings": {
            "color": {
                "measure": {"target": "data"},
            },
        },
        "viz": {
            "id": "flatTable",
            "type": "table",
            "name": "label_visualization-flat-table",
            "iconProps": {"id": "visFlatTable", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLayerFilters": False,
            "allowSort": True,
        },
        "placeholders": {
            "flat-table-columns": {
                "allowedTypes": {},
                "iconProps": {},
                "id": "flat-table-columns",
                "required": True,
                "settings": {"groupping": "on"},
                "title": "section_columns",
                "type": "flat-table-columns",
            },
        },
        "placeholder_aliases": {
            "columns": "flat-table-columns",
        },
    },
    "pivotTable": {
        "wire_type": "table_wizard_node",
        "golden_id": "cecd684j8s64w",
        "encodings": {
            "color": {
                "measure": {"target": "data"},
            },
        },
        "viz": {
            "id": "pivotTable",
            "type": "table",
            "name": "label_visualization-pivot-table",
            "iconProps": {"id": "visPivot", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLayerFilters": False,
            "allowSort": True,
        },
        "placeholders": {
            "pivot-table-columns": {
                "allowedDataTypes": {},
                "allowedTypes": {},
                "iconProps": {},
                "id": "pivot-table-columns",
                "settings": {},
                "title": "section_columns",
                "type": "pivot-table-columns",
            },
            "rows": {
                "allowedDataTypes": {},
                "iconProps": {},
                "id": "rows",
                "settings": {},
                "title": "section_rows",
                "type": "rows",
            },
            "measures": {
                "allowedFinalTypes": {},
                "allowedTypes": {},
                "iconProps": {},
                "id": "measures",
                "settings": {"axisModeMap": {}},
                "title": "section_measures",
                "type": "measures",
            },
        },
        "placeholder_aliases": {
            "columns": "pivot-table-columns",
            "y": "measures",
        },
    },
    "combined-chart": {
        "wire_type": "d3_wizard_node",
        "golden_id": "r3u9vq251x0mb",
        "viz": {
            "id": "combined-chart",
            "type": "geo",
            "name": "label_visualization-combined-chart",
            "iconProps": {"id": "visCombined", "width": "24"},
            "highchartsId": "column",
            "allowFilters": True,
            "allowSort": True,
            "allowLayerFilters": False,
        },
        "placeholders": {},
        "placeholder_aliases": {},
    },
    "geolayer": {
        "wire_type": "ymap_wizard_node",
        "golden_id": "lga16nqs7eued",
        "viz": {
            "id": "geolayer",
            "type": "geo",
            "name": "label_visualization-geolayer",
            "iconProps": {"id": "visGeolayer", "width": "24"},
            "allowFilters": False,
            "allowSort": False,
            "allowLayerFilters": False,
            "hidden": False,
        },
        "placeholders": {},
        "placeholder_aliases": {},
    },
}

_COMMON_PLACEHOLDERS_EMPTY: dict[str, object] = {
    "colors": [],
    "colorsConfig": {},
    "filters": [],
    "geopointsConfig": {},
    "labels": [],
    "shapes": [],
    "shapesConfig": {},
    "sort": [],
    "tooltips": [],
}


def _y_placeholder_linear_with_axis_format(
    pid: str = "y",
    title: str = "section_y",
    nulls: str = "ignore",
    axis_format_mode: str = "auto",
) -> dict[str, object]:
    ph = _y_placeholder_linear(pid=pid, title=title, nulls=nulls)
    cast(dict[str, object], ph["settings"])["axisFormatMode"] = axis_format_mode
    return ph


_LAYER_VIZ_SPECS: dict[str, dict[str, object]] = {
    "column": {
        "viz": {
            "id": "column",
            "type": "column",
            "name": "label_visualization-column",
            "iconProps": {"id": "visColumn", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowSegments": True,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
        },
        "common_placeholders": dict(_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "x": _x_placeholder_linear(capacity=2, required=False),
            "y": _y_placeholder_linear(pid="y", nulls="ignore", title="section_y"),
            "y2": _y_placeholder_linear_with_axis_format(
                pid="y2",
                title="section_y2",
                nulls="connect",
                axis_format_mode="by-field",
            ),
        },
    },
    "line": {
        "viz": {
            "id": "line",
            "type": "line",
            "name": "label_visualization-line",
            "iconProps": {"id": "visLines", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowSegments": True,
            "allowShapes": True,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
            "colorsCapacity": 1,
            "shapesCapacity": 1,
        },
        "common_placeholders": dict(_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "x": _x_placeholder_linear(capacity=1, required=True),
            "y": _y_placeholder_linear(pid="y", nulls="ignore", title="section_y"),
            "y2": _y_placeholder_linear_with_axis_format(
                pid="y2",
                title="section_y2",
                nulls="connect",
                axis_format_mode="by-field",
            ),
        },
    },
    "area": {
        "viz": {
            "id": "area",
            "type": "line",
            "name": "label_visualization-area",
            "iconProps": {"id": "visArea", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowSegments": True,
            "allowSort": True,
            "availableLabelModes": ["absolute"],
        },
        "common_placeholders": dict(_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "x": _x_placeholder_linear(capacity=1, required=True),
            "y": _y_placeholder_linear(pid="y", nulls="as-0", title="section_y"),
            "y2": _y_placeholder_linear_with_axis_format(
                pid="y2",
                title="section_y2",
                nulls="connect",
                axis_format_mode="by-field",
            ),
        },
    },
}

_GEO_COMMON_PLACEHOLDERS_EMPTY: dict[str, object] = {
    "colors": [],
    "colorsConfig": {},
    "filters": [],
    "geopointsConfig": {},
    "labels": [],
    "segments": [],
    "shapes": [],
    "shapesConfig": {},
    "sort": [],
    "tooltips": [],
}


def _geo_placeholder(
    pid: str,
    ph_type: str,
    title: str,
    capacity: int | None = None,
    required: bool = False,
    settings: dict[str, object] | None = None,
) -> dict[str, object]:
    """Placeholder for a geo layer (geopoint/geopolygon/polyline/size/measures/grouping).

    capacity=None means unlimited (DataLens accepts it without the field).
    """
    ph: dict[str, object] = {
        "allowedDataTypes": {},
        "allowedTypes": {},
        "iconProps": {},
        "id": pid,
        "type": ph_type,
        "title": title,
        "settings": dict(settings) if settings else {},
    }
    if capacity is not None:
        ph["capacity"] = capacity
    if required:
        ph["required"] = True
    return ph


_GEO_LAYER_VIZ_SPECS: dict[str, dict[str, object]] = {
    "geopoint": {
        "viz": {
            "id": "geopoint",
            "type": "geo",
            "name": "label_visualization-geopoint",
            "iconProps": {"id": "visGeopoint", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": True,
            "allowLayerFilters": True,
            "allowTooltips": True,
            "availableLabelModes": ["absolute"],
        },
        "common_placeholders": dict(_GEO_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "geopoint": _geo_placeholder(
                "geopoint",
                "geopoint",
                "section_geopoint",
                required=True,
            ),
            "size": _geo_placeholder(
                "size",
                "measures",
                "section_points_size",
                capacity=1,
            ),
        },
    },
    "heatmap": {
        "viz": {
            "id": "heatmap",
            "type": "geo",
            "name": "label_visualization-heatmap",
            "iconProps": {"id": "visHeatmap", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLayerFilters": True,
            "hidden": True,
        },
        "common_placeholders": dict(_GEO_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "geopoint": _geo_placeholder(
                "geopoint",
                "geopoint",
                "section_geopoint",
                required=True,
            ),
        },
    },
    "geopolygon": {
        "viz": {
            "id": "geopolygon",
            "type": "geo",
            "name": "label_visualization-geopolygon",
            "iconProps": {"id": "visGeopolygon", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLayerFilters": True,
            "allowTooltips": True,
        },
        "common_placeholders": dict(_GEO_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "geopolygon": _geo_placeholder(
                "geopolygon",
                "geopolygon",
                "section_geopolygon",
                required=True,
            ),
        },
    },
    "polyline": {
        "viz": {
            "id": "polyline",
            "type": "geo",
            "name": "label_visualization-polyline",
            "iconProps": {"id": "visPolyline", "width": "24"},
            "allowColors": True,
            "allowFilters": True,
            "allowLabels": False,
            "allowLayerFilters": True,
            "allowSort": True,
            "allowTooltips": False,
            "availableLabelModes": ["absolute"],
        },
        "common_placeholders": dict(_GEO_COMMON_PLACEHOLDERS_EMPTY),
        "placeholders": {
            "polyline": _geo_placeholder(
                "polyline",
                "polyline",
                "section_polyline",
                required=True,
                settings={"polylinePoints": "off"},
            ),
            "measures": _geo_placeholder("measures", "measures", "section_measures"),
            "grouping": _geo_placeholder("grouping", "grouping", "section_grouping"),
        },
    },
}


def get_viz_spec(viz_id: str) -> dict[str, object]:
    """Return spec by viz_id; empty dict if spec is unknown."""
    return VIZ_SPECS.get(viz_id, {})


def get_wizard_encoding(
    viz_id: str,
    encoding: WizardEncoding,
    binding: WizardEncodingBinding,
) -> WizardEncodingRule | None:
    """Return one explicit Wizard encoding capability, if supported."""
    spec = VIZ_SPECS.get(viz_id, {})
    encodings = spec.get("encodings")
    if not isinstance(encodings, dict):
        return None
    encoding_spec = encodings.get(encoding)
    if not isinstance(encoding_spec, dict):
        return None
    rule = encoding_spec.get(binding)
    return cast(WizardEncodingRule, rule) if isinstance(rule, dict) else None


def viz_ids_for_wizard_encoding(
    encoding: WizardEncoding,
    binding: WizardEncodingBinding,
) -> frozenset[str]:
    """Return viz ids supporting an encoding/binding pair."""
    return frozenset(viz_id for viz_id in VIZ_SPECS if get_wizard_encoding(viz_id, encoding, binding) is not None)


def viz_ids_with_color_encoding() -> frozenset[str]:
    """Return viz ids supporting at least one semantic Color binding."""
    return frozenset(
        viz_id
        for viz_id in VIZ_SPECS
        if any(
            get_wizard_encoding(viz_id, "color", binding) is not None
            for binding in ("dimension", "measure", "measure_name")
        )
    )


def get_placeholder_id(viz_id: str, builder_id: str) -> str:
    """Map builder placeholder name to spec placeholder.id.

    Returns the aliased target name if defined (e.g. pie builder 'x' -> 'dimensions'),
    otherwise returns builder_id unchanged.
    """
    spec = VIZ_SPECS.get(viz_id, {})
    aliases = cast(dict[str, object], spec.get("placeholder_aliases", {}) or {})
    return cast(str, aliases.get(builder_id, builder_id))


def validate_placeholder_id(*, method: str, visualization_id: str, placeholder_id: str) -> str:
    """Return the canonical placeholder id or raise an actionable local error.

    The generated create surface and update validation share ``VIZ_SPECS`` and
    its ``placeholder_aliases`` mapping.  Keeping this lookup here prevents an
    update typo from becoming a best-effort wire mutation.
    """
    spec = VIZ_SPECS.get(visualization_id)
    if spec is None:
        raise DataLensConfigurationError(
            f"{method}: active visualization {visualization_id!r} is unknown. "
            f"Supported visualizations: {sorted(VIZ_SPECS)}."
        )
    placeholders = spec.get("placeholders")
    if not isinstance(placeholders, dict):
        placeholders = {}
    actual_id = get_placeholder_id(visualization_id, placeholder_id)
    if actual_id in placeholders:
        return actual_id
    aliases = spec.get("placeholder_aliases")
    alias_names = sorted(aliases) if isinstance(aliases, dict) else []
    allowed = sorted(set(placeholders) | set(alias_names))
    raise DataLensConfigurationError(
        f"{method}: placeholder {placeholder_id!r} is not applicable to active visualization "
        f"{visualization_id!r}. Allowed placeholders: {allowed}."
    )


def get_layer_spec(layer_type: str) -> dict[str, object]:
    """Return spec for a combined-chart layer.

    Returns dict with 'viz' and 'common_placeholders' keys,
    or empty dict if layer_type is unknown.
    """
    return _LAYER_VIZ_SPECS.get(layer_type, {})


def get_geo_layer_spec(layer_type: str) -> dict[str, object]:
    """Return spec for a geo-chart layer (viz.id='geolayer').

    Returns dict with 'viz', 'common_placeholders', 'placeholders' keys,
    or empty dict if layer_type is unknown.
    """
    return _GEO_LAYER_VIZ_SPECS.get(layer_type, {})


def requires_x_measure_autofix(visualization_id: str) -> bool:
    """Return whether viz requires auto-fix for x=MEASURE/y=DIMENSION pattern.

    Applies to horizontal bar charts (bar, bar100p).
    """
    spec = VIZ_SPECS.get(visualization_id) or {}
    return bool(spec.get("requires_x_measure_autofix", False))


# ---------------------------------------------------------------------------
# QL visualization specs
#
# A separate, QL-specific source of truth. QL charts source data from a SQL
# query (not a typed dataset) and carry a distinct placeholder/caps model:
# fewer placeholders (no ``shapes`` where wizard emits one), QL caps
# (``allowAvailable=True``, ``allowFilters/Sort/LayerFilters/Segments=False``).
# The wizard ``VIZ_SPECS`` above are correct for wizard charts and MUST NOT be
# reused for QL scaffolding. Each entry here mirrors a live QL reference chart
# verbatim (id/type/name/iconProps + QL caps + placeholders, excluding the
# user-supplied ``items`` which are filled from :class:`QLColumn`).
# ---------------------------------------------------------------------------


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
