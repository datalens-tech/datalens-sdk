from __future__ import annotations

from typing import Literal, TypedDict

from typing_extensions import NotRequired

from datalens_sdk.errors import DataLensConfigurationError

WizardEncoding = Literal["color", "shape"]
WizardEncodingBinding = Literal["dimension", "measure", "measure_name"]


class WizardEncodingRule(TypedDict):
    slot: str
    requires_field_in_slot: NotRequired[str]
    implicit_from_slot: NotRequired[str]
    measure_slots: NotRequired[tuple[str, ...]]
    category_slot: NotRequired[str]


class WizardVisualizationSemantics(TypedDict):
    slots: tuple[str, ...]
    slot_aliases: dict[str, str]
    measure_slot: NotRequired[str]
    encodings: NotRequired[dict[WizardEncoding, dict[WizardEncodingBinding, WizardEncodingRule]]]
    allows_filters: bool
    allows_labels: bool
    allows_sort: bool
    label_modes: NotRequired[tuple[str, ...]]
    requires_x_measure_autofix: NotRequired[bool]
    slot_capacities: NotRequired[dict[str, int]]


class WizardGeoLayerSemantics(TypedDict):
    required_geometry: Literal["geopoint", "polygon", "polyline"]
    supported_inputs: frozenset[str]


class WizardVisualizationTransition(TypedDict):
    slot_mapping: tuple[tuple[str, str], ...]


WIZARD_VISUALIZATION_SEMANTICS: dict[str, WizardVisualizationSemantics] = {
    "metric": {
        "slots": ("measures",),
        "slot_aliases": {"y": "measures"},
        "measure_slot": "measures",
        "allows_filters": True,
        "allows_labels": False,
        "allows_sort": False,
    },
    "line": {
        "slots": ("colors", "labels", "segments", "shapes", "sort", "x", "y", "y2"),
        "slot_aliases": {},
        "measure_slot": "y",
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure_name": {"slot": "colors", "measure_slots": ("y", "y2")},
            },
            "shape": {
                "dimension": {"slot": "shapes"},
                "measure_name": {"slot": "shapes", "measure_slots": ("y", "y2")},
            },
        },
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute",),
    },
    "column": {
        "slots": ("colors", "labels", "segments", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "y",
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
                "measure_name": {"slot": "colors", "measure_slots": ("y",), "category_slot": "x"},
            },
        },
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute",),
    },
    "bar": {
        "slots": ("colors", "labels", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "x",
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
                "measure_name": {"slot": "colors", "measure_slots": ("x",), "category_slot": "y"},
            },
        },
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute",),
        "requires_x_measure_autofix": True,
        "slot_capacities": {"y": 2},
    },
    "area": {
        "slots": ("colors", "labels", "segments", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "y",
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute",),
    },
    "area100p": {
        "slots": ("colors", "labels", "segments", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "y",
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute", "percent"),
    },
    "column100p": {
        "slots": ("colors", "labels", "segments", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "y",
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute", "percent"),
    },
    "bar100p": {
        "slots": ("colors", "labels", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "x",
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute", "percent"),
        "requires_x_measure_autofix": True,
    },
    "donut": {
        "slots": ("colors", "dimensions", "labels", "measures", "sort"),
        "slot_aliases": {"x": "dimensions", "y": "measures"},
        "measure_slot": "measures",
        "encodings": {
            "color": {"dimension": {"slot": "colors", "implicit_from_slot": "dimensions"}},
        },
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute", "percent"),
    },
    "funnel": {
        "slots": ("colors", "dimensions", "labels", "measures", "sort"),
        "slot_aliases": {"x": "dimensions", "y": "measures"},
        "measure_slot": "measures",
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute", "percent"),
    },
    "treemap": {
        "slots": ("colors", "dimensions", "measures"),
        "slot_aliases": {"x": "dimensions", "y": "measures", "color": "colors"},
        "measure_slot": "measures",
        "encodings": {
            "color": {
                "dimension": {"slot": "colors", "requires_field_in_slot": "dimensions"},
                "measure": {"slot": "colors"},
            },
        },
        "allows_filters": True,
        "allows_labels": False,
        "allows_sort": False,
    },
    "scatter": {
        "slots": ("colors", "points", "shapes", "size", "sort", "x", "y"),
        "slot_aliases": {},
        "measure_slot": "y",
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
            },
            "shape": {"dimension": {"slot": "shapes"}},
        },
        "allows_filters": True,
        "allows_labels": False,
        "allows_sort": True,
    },
    "pie": {
        "slots": ("colors", "dimensions", "labels", "measures", "sort"),
        "slot_aliases": {"x": "dimensions", "y": "measures"},
        "measure_slot": "measures",
        "encodings": {
            "color": {"dimension": {"slot": "colors", "implicit_from_slot": "dimensions"}},
        },
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
        "label_modes": ("absolute", "percent"),
    },
    "flatTable": {
        "slots": ("colors", "columns", "sort"),
        "slot_aliases": {},
        "encodings": {"color": {"measure": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": False,
        "allows_sort": True,
    },
    "pivotTable": {
        "slots": ("colors", "columns", "measures", "rows", "sort"),
        "slot_aliases": {"y": "measures"},
        "measure_slot": "measures",
        "encodings": {"color": {"measure": {"slot": "colors"}}},
        "allows_filters": True,
        "allows_labels": False,
        "allows_sort": True,
    },
    "combined-chart": {
        "slots": (),
        "slot_aliases": {},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": True,
    },
    "geolayer": {
        "slots": (),
        "slot_aliases": {},
        "allows_filters": True,
        "allows_labels": True,
        "allows_sort": False,
    },
}


WIZARD_VISUALIZATION_TRANSITIONS: dict[tuple[str, str], WizardVisualizationTransition] = {
    ("line", "column"): {"slot_mapping": (("x", "x"), ("y", "y"))},
    ("column", "line"): {"slot_mapping": (("x", "x"), ("y", "y"))},
    ("line", "bar"): {"slot_mapping": (("x", "y"), ("y", "x"))},
    ("bar", "line"): {"slot_mapping": (("y", "x"), ("x", "y"))},
}


def validate_visualization_transition(
    *,
    method: str,
    source_visualization_type: str,
    target_visualization_type: str,
) -> WizardVisualizationTransition:
    known_types = frozenset(WIZARD_VISUALIZATION_SEMANTICS)
    if source_visualization_type not in known_types:
        raise DataLensConfigurationError(
            f"{method}: active visualization {source_visualization_type!r} is unknown. "
            f"Supported visualizations: {sorted(known_types)}."
        )
    if target_visualization_type not in known_types:
        raise DataLensConfigurationError(
            f"{method}: target visualization {target_visualization_type!r} is unknown for active visualization "
            f"{source_visualization_type!r}. Supported visualizations: {sorted(known_types)}."
        )
    if target_visualization_type == source_visualization_type:
        raise DataLensConfigurationError(
            f"{method}: target visualization {target_visualization_type!r} is already active; "
            "choose a different supported transition."
        )
    transition = WIZARD_VISUALIZATION_TRANSITIONS.get((source_visualization_type, target_visualization_type))
    if transition is not None:
        return transition
    targets = sorted(
        target_type
        for source_type, target_type in WIZARD_VISUALIZATION_TRANSITIONS
        if source_type == source_visualization_type
    )
    raise DataLensConfigurationError(
        f"{method}: transition from active visualization {source_visualization_type!r} to "
        f"{target_visualization_type!r} is not supported. Verified targets: {targets}."
    )


WIZARD_GEO_LAYER_SEMANTICS: dict[str, WizardGeoLayerSemantics] = {
    "geopoint": {
        "required_geometry": "geopoint",
        "supported_inputs": frozenset({"geopoint", "size", "color", "filters", "tooltips", "labels"}),
    },
    "geopoint-with-cluster": {
        "required_geometry": "geopoint",
        "supported_inputs": frozenset({"geopoint", "size", "color", "filters", "tooltips", "labels"}),
    },
    "heatmap": {
        "required_geometry": "geopoint",
        "supported_inputs": frozenset({"geopoint", "color", "filters"}),
    },
    "geopolygon": {
        "required_geometry": "polygon",
        "supported_inputs": frozenset({"polygon", "color", "filters", "tooltips"}),
    },
    "polyline": {
        "required_geometry": "polyline",
        "supported_inputs": frozenset({"polyline", "grouping", "measures", "color", "filters", "sort_by"}),
    },
}


def get_wizard_visualization_semantics(visualization_type: str) -> WizardVisualizationSemantics | None:
    return WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)


def get_wizard_encoding(
    visualization_type: str,
    encoding: WizardEncoding,
    binding: WizardEncodingBinding,
) -> WizardEncodingRule | None:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    if semantics is None:
        return None
    return semantics.get("encodings", {}).get(encoding, {}).get(binding)


def visualization_types_for_wizard_encoding(
    encoding: WizardEncoding,
    binding: WizardEncodingBinding,
) -> frozenset[str]:
    return frozenset(
        visualization_type
        for visualization_type in WIZARD_VISUALIZATION_SEMANTICS
        if get_wizard_encoding(visualization_type, encoding, binding) is not None
    )


def visualization_types_with_color_encoding() -> frozenset[str]:
    return frozenset(
        visualization_type
        for visualization_type in WIZARD_VISUALIZATION_SEMANTICS
        if any(
            get_wizard_encoding(visualization_type, "color", binding) is not None
            for binding in ("dimension", "measure", "measure_name")
        )
    )


def visualization_types_with_slot(slot_name: str) -> frozenset[str]:
    return frozenset(
        visualization_type
        for visualization_type, semantics in WIZARD_VISUALIZATION_SEMANTICS.items()
        if slot_name in semantics["slots"]
    )


def visualization_types_with_label_mode(label_mode: str) -> frozenset[str]:
    return frozenset(
        visualization_type
        for visualization_type, semantics in WIZARD_VISUALIZATION_SEMANTICS.items()
        if label_mode in semantics.get("label_modes", ())
    )


def validate_label_mode(*, visualization_type: str, label_mode: str) -> None:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    allowed = semantics.get("label_modes", ()) if semantics is not None else ()
    if label_mode not in allowed:
        raise DataLensConfigurationError(
            f"label_mode: mode {label_mode!r} is not applicable to visualization {visualization_type!r}. "
            f"Allowed modes: {list(allowed)}."
        )


def visualization_types_where(flag: Literal["allows_filters", "allows_labels", "allows_sort"]) -> frozenset[str]:
    return frozenset(
        visualization_type
        for visualization_type, semantics in WIZARD_VISUALIZATION_SEMANTICS.items()
        if semantics.get(flag) is True
    )


def resolve_slot_name(visualization_type: str, slot_name: str) -> str:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    if semantics is None:
        return slot_name
    return semantics["slot_aliases"].get(slot_name, slot_name)


def validate_slot_name(*, method: str, visualization_type: str, slot_name: str) -> str:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    if semantics is None:
        raise DataLensConfigurationError(
            f"{method}: active visualization {visualization_type!r} is unknown. "
            f"Supported visualizations: {sorted(WIZARD_VISUALIZATION_SEMANTICS)}."
        )
    canonical_name = resolve_slot_name(visualization_type, slot_name)
    if canonical_name in semantics["slots"]:
        return canonical_name
    if canonical_name == "labels" and semantics.get("allows_labels") is True:
        return canonical_name
    if canonical_name == "sort" and semantics.get("allows_sort") is True:
        return canonical_name
    allowed = sorted(set(semantics["slots"]) | set(semantics["slot_aliases"]))
    raise DataLensConfigurationError(
        f"{method}: slot {slot_name!r} is not applicable to active visualization "
        f"{visualization_type!r}. Allowed slots: {allowed}."
    )


def get_geo_layer_semantics(layer_type: str) -> WizardGeoLayerSemantics | None:
    return WIZARD_GEO_LAYER_SEMANTICS.get(layer_type)


def geo_layer_supports_input(layer_semantics: WizardGeoLayerSemantics, input_name: str) -> bool:
    return input_name in layer_semantics["supported_inputs"]


def requires_x_measure_autofix(visualization_type: str) -> bool:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    return bool(semantics and semantics.get("requires_x_measure_autofix"))
