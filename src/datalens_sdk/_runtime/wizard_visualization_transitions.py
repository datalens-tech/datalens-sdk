"""Explicit, loss-aware Wizard visualization transition contract.

Each entry retains only the listed placeholder items.  All target metadata and
placeholder settings are rebuilt from ``VIZ_SPECS`` by the converter, so this
matrix is deliberately small rather than a best-effort generic migration.
"""

from __future__ import annotations

from typing import TypedDict

from datalens_sdk._runtime.viz_specs import VIZ_SPECS
from datalens_sdk.errors import DataLensConfigurationError


class WizardVisualizationTransition(TypedDict):
    placeholder_mapping: tuple[tuple[str, str], ...]


WIZARD_VISUALIZATION_TRANSITIONS: dict[tuple[str, str], WizardVisualizationTransition] = {
    # Cartesian vertical charts retain their axes directly.
    ("line", "column"): {"placeholder_mapping": (("x", "x"), ("y", "y"))},
    ("column", "line"): {"placeholder_mapping": (("x", "x"), ("y", "y"))},
    # A horizontal bar chart reverses the category and measure axes.
    ("line", "bar"): {"placeholder_mapping": (("x", "y"), ("y", "x"))},
    ("bar", "line"): {"placeholder_mapping": (("y", "x"), ("x", "y"))},
}


def validate_visualization_transition(
    *,
    method: str,
    source_visualization_id: str,
    target_visualization_id: str,
) -> WizardVisualizationTransition:
    """Return one verified transition or fail before an RPC is built."""
    if source_visualization_id not in VIZ_SPECS:
        raise DataLensConfigurationError(
            f"{method}: active visualization {source_visualization_id!r} is unknown. "
            f"Supported visualizations: {sorted(VIZ_SPECS)}."
        )
    if target_visualization_id not in VIZ_SPECS:
        raise DataLensConfigurationError(
            f"{method}: target visualization {target_visualization_id!r} is unknown for active visualization "
            f"{source_visualization_id!r}. Supported visualizations: {sorted(VIZ_SPECS)}."
        )
    if target_visualization_id == source_visualization_id:
        raise DataLensConfigurationError(
            f"{method}: target visualization {target_visualization_id!r} is already active; "
            "choose a different supported transition."
        )
    transition = WIZARD_VISUALIZATION_TRANSITIONS.get((source_visualization_id, target_visualization_id))
    if transition is not None:
        return transition
    targets = sorted(target for source, target in WIZARD_VISUALIZATION_TRANSITIONS if source == source_visualization_id)
    raise DataLensConfigurationError(
        f"{method}: transition from active visualization {source_visualization_id!r} to "
        f"{target_visualization_id!r} is not supported. Verified targets: {targets}."
    )
