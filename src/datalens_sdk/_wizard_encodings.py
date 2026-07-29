from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datalens_sdk.domain.chart_types import ShapeStyle
    from datalens_sdk.domain.fields import FieldRef


@dataclass(frozen=True, slots=True)
class WizardColorEncoding:
    """One explicit semantic binding of the Wizard Color section."""

    kind: Literal["dimension", "measure", "measure_name"]
    field: FieldRef | None = None
    colors_map: Mapping[FieldRef, str] = dataclass_field(default_factory=dict)
    gradient_mode: Literal["2-point", "3-point"] | None = None
    gradient_palette: str | None = None
    reversed: bool | None = None


@dataclass(frozen=True, slots=True)
class WizardShapeEncoding:
    """One explicit semantic binding of the Wizard Shapes section."""

    kind: Literal["dimension", "measure_name"]
    field: FieldRef | None = None
    shapes_map: Mapping[FieldRef, ShapeStyle] | None = None
