from dataclasses import dataclass, field
from typing import Generic, Literal, TypeAlias, TypeVar

from datalens_sdk.domain.runtime_params import RuntimeParams, normalize_params
from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.serialization.json_types import JsonValue

ColumnT_co = TypeVar("ColumnT_co", covariant=True)


@dataclass(frozen=True, slots=True)
class ChartDataTable(Generic[ColumnT_co]):
    """One ordered table; duplicate column names and varying row widths are preserved."""

    schema: tuple[ColumnT_co, ...]
    rows: tuple[tuple[JsonValue, ...], ...]


@dataclass(frozen=True, slots=True)
class WizardChartDataColumn:
    name: str
    type: str
    guid: str | None = None


@dataclass(frozen=True, slots=True)
class QLChartDataColumn:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class EditorChartDataColumn:
    name: str


@dataclass(frozen=True, slots=True)
class WizardChartData:
    results: tuple[ChartDataTable[WizardChartDataColumn], ...]
    chart_type: Literal["wizard"] = field(default="wizard", init=False)


@dataclass(frozen=True, slots=True)
class QLChartData:
    results: tuple[ChartDataTable[QLChartDataColumn], ...]
    chart_type: Literal["ql"] = field(default="ql", init=False)


@dataclass(frozen=True, slots=True)
class EditorChartData:
    results: tuple[ChartDataTable[EditorChartDataColumn], ...]
    chart_type: Literal["editor"] = field(default="editor", init=False)


ChartData: TypeAlias = WizardChartData | QLChartData | EditorChartData


@dataclass(frozen=True, slots=True, kw_only=True)
class ChartDataQuery:
    chart_id: str
    params: RuntimeParams | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.chart_id, str) or not self.chart_id:
            raise DataLensValidationError("chart_id must be a non-empty string")
        if self.params is not None:
            params = normalize_params(self.params, context="Chart data")
            for key in params:
                if key in {"branch", "revId"}:
                    raise DataLensValidationError(
                        f"Chart data parameter {key!r} is a revision selector; "
                        "get_chart_data does not support revision selection"
                    )
                if key in {"tab", "state"}:
                    raise DataLensValidationError(
                        f"Chart data parameter {key!r} is a dashboard control and cannot be passed in params"
                    )
            object.__setattr__(self, "params", params)
