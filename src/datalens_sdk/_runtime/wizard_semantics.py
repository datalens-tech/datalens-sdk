from __future__ import annotations

from typing import Literal, TypedDict

from typing_extensions import NotRequired

from datalens_sdk.errors import DataLensConfigurationError

WizardEncoding = Literal["color", "shape"]
WizardEncodingBinding = Literal["dimension", "measure", "measure_name"]


class WizardEncodingRule(TypedDict):
    slot: str
    implicit_from_slot: NotRequired[str]
    measure_slots: NotRequired[tuple[str, ...]]


class WizardAutofixRule(TypedDict):
    sort_from_slot: str
    sort_direction: str
    labels_from_slot: str


class WizardVisualizationSemantics(TypedDict):
    slot_aliases: dict[str, str]
    encodings: NotRequired[dict[WizardEncoding, dict[WizardEncodingBinding, WizardEncodingRule]]]
    label_modes: NotRequired[tuple[str, ...]]
    autofix: NotRequired[WizardAutofixRule]
    slot_capacities: NotRequired[dict[str, int]]


class WizardVisualizationTransition(TypedDict):
    slot_mapping: tuple[tuple[str, str], ...]


WIZARD_VISUALIZATION_SEMANTICS: dict[str, WizardVisualizationSemantics] = {
    "metric": {
        "slot_aliases": {"y": "measures"},
    },
    "line": {
        "slot_aliases": {},
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
        "label_modes": ("absolute",),
    },
    "column": {
        "slot_aliases": {},
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
                "measure_name": {"slot": "colors", "measure_slots": ("y",)},
            },
        },
        "label_modes": ("absolute",),
    },
    "bar": {
        "slot_aliases": {},
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
                "measure_name": {"slot": "colors", "measure_slots": ("x",)},
            },
        },
        "label_modes": ("absolute",),
        "autofix": {"sort_from_slot": "y", "sort_direction": "DESC", "labels_from_slot": "x"},
        "slot_capacities": {"y": 2},
    },
    "area": {
        "slot_aliases": {},
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "label_modes": ("absolute",),
    },
    "area100p": {
        "slot_aliases": {},
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "label_modes": ("absolute", "percent"),
    },
    "column100p": {
        "slot_aliases": {},
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "label_modes": ("absolute", "percent"),
    },
    "bar100p": {
        "slot_aliases": {},
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "label_modes": ("absolute", "percent"),
    },
    "donut": {
        "slot_aliases": {"x": "dimensions", "y": "measures"},
        "encodings": {
            "color": {"dimension": {"slot": "colors", "implicit_from_slot": "dimensions"}},
        },
        "label_modes": ("absolute", "percent"),
    },
    "funnel": {
        "slot_aliases": {"x": "dimensions", "y": "measures"},
        "encodings": {"color": {"dimension": {"slot": "colors"}}},
        "label_modes": ("absolute", "percent"),
    },
    "treemap": {
        "slot_aliases": {"x": "dimensions", "y": "measures", "color": "colors"},
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
            },
        },
    },
    "scatter": {
        "slot_aliases": {},
        "encodings": {
            "color": {
                "dimension": {"slot": "colors"},
                "measure": {"slot": "colors"},
            },
            "shape": {"dimension": {"slot": "shapes"}},
        },
    },
    "pie": {
        "slot_aliases": {"x": "dimensions", "y": "measures"},
        "encodings": {
            "color": {"dimension": {"slot": "colors", "implicit_from_slot": "dimensions"}},
        },
        "label_modes": ("absolute", "percent"),
    },
    "flatTable": {
        "slot_aliases": {},
        "encodings": {"color": {"measure": {"slot": "colors"}}},
    },
    "pivotTable": {
        "slot_aliases": {},
        "encodings": {"color": {"measure": {"slot": "colors"}}},
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


def resolve_slot_name(visualization_type: str, slot_name: str) -> str:
    semantics = WIZARD_VISUALIZATION_SEMANTICS.get(visualization_type)
    if semantics is None:
        return slot_name
    return semantics["slot_aliases"].get(slot_name, slot_name)


def validate_slot_name(*, method: str, visualization_type: str, slot_name: str) -> str:
    del method
    return resolve_slot_name(visualization_type, slot_name)
