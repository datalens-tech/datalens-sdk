from collections.abc import Mapping, Sequence
from typing import Generic, Literal, Protocol, TypeVar, cast

from pydantic import TypeAdapter
from typing_extensions import TypeForm

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._data_rows import normalize_data_rows
from datalens_sdk.converter.runtime_params import runtime_params_payload
from datalens_sdk.domain.chart_data import (
    ChartData,
    ChartDataAggregation,
    ChartDataQuery,
    ChartDataTable,
    EditorChartData,
    EditorChartDataColumn,
    QLChartData,
    QLChartDataColumn,
    WizardChartData,
    WizardChartDataColumn,
)


class ChartDataWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class ChartDataArgsDTOClass(Protocol):
    def model_validate(self, obj: object) -> ChartDataWriteDTOProtocol: ...


class ChartDataDtoModule(Protocol):
    GetChartDataArgsDTO: ChartDataArgsDTOClass
    GetChartDataResultDTO: TypeForm[object]


class EditorColumnReadDTOProtocol(Protocol):
    @property
    def name(self) -> str: ...


class QLColumnReadDTOProtocol(EditorColumnReadDTOProtocol, Protocol):
    @property
    def type(self) -> str: ...


class WizardColumnReadDTOProtocol(QLColumnReadDTOProtocol, Protocol):
    @property
    def guid(self) -> str | None: ...


ColumnT_co = TypeVar("ColumnT_co", covariant=True)


class TableReadDTOProtocol(Protocol, Generic[ColumnT_co]):
    @property
    def columns(self) -> Sequence[ColumnT_co]: ...

    @property
    def rows(self) -> Sequence[Sequence[object]]: ...


class ChartDataAggregationReadDTOProtocol(Protocol):
    @property
    def type(self) -> Literal["detail", "subtotal", "total"]: ...

    @property
    def group_by(self) -> Sequence[int]: ...


class WizardReadDTOProtocol(Protocol):
    chart_type: Literal["wizard"]
    results: Sequence[TableReadDTOProtocol[WizardColumnReadDTOProtocol]]


class QLReadDTOProtocol(Protocol):
    chart_type: Literal["ql"]
    results: Sequence[TableReadDTOProtocol[QLColumnReadDTOProtocol]]


class EditorReadDTOProtocol(Protocol):
    chart_type: Literal["editor"]
    results: Sequence[TableReadDTOProtocol[EditorColumnReadDTOProtocol]]


def _wizard_table_aggregation(table: TableReadDTOProtocol[WizardColumnReadDTOProtocol]) -> ChartDataAggregation | None:
    # Older generated DTO modules do not have the optional aggregation field.
    aggregation = cast(ChartDataAggregationReadDTOProtocol | None, getattr(table, "aggregation", None))
    if aggregation is None:
        return None
    return ChartDataAggregation(type=aggregation.type, group_by=tuple(aggregation.group_by))


class ChartDataConverter:
    @staticmethod
    def request_payload(
        query: ChartDataQuery,
        *,
        dto_module: ChartDataDtoModule | None = None,
    ) -> dict[str, object]:
        generated = cast(ChartDataDtoModule, generated_dto if dto_module is None else dto_module)
        payload: dict[str, object] = {"chartId": query.chart_id}
        params = query.params
        if params is not None:
            payload["params"] = runtime_params_payload(params)
        return generated.GetChartDataArgsDTO.model_validate(payload).to_payload()

    @staticmethod
    def result(
        raw: Mapping[str, object],
        *,
        dto_module: ChartDataDtoModule | None = None,
    ) -> ChartData:
        generated = cast(ChartDataDtoModule, generated_dto if dto_module is None else dto_module)
        result = cast(
            WizardReadDTOProtocol | QLReadDTOProtocol | EditorReadDTOProtocol,
            TypeAdapter[object](generated.GetChartDataResultDTO).validate_python(raw),
        )
        if result.chart_type == "wizard":
            return WizardChartData(
                results=tuple(
                    ChartDataTable(
                        schema=tuple(
                            WizardChartDataColumn(name=column.name, type=column.type, guid=column.guid)
                            for column in table.columns
                        ),
                        rows=normalize_data_rows(table.rows, context=f"Chart data table {table_index}"),
                        aggregation=_wizard_table_aggregation(table),
                    )
                    for table_index, table in enumerate(result.results)
                )
            )
        if result.chart_type == "ql":
            return QLChartData(
                results=tuple(
                    ChartDataTable(
                        schema=tuple(QLChartDataColumn(name=column.name, type=column.type) for column in table.columns),
                        rows=normalize_data_rows(table.rows, context=f"Chart data table {table_index}"),
                    )
                    for table_index, table in enumerate(result.results)
                )
            )
        return EditorChartData(
            results=tuple(
                ChartDataTable(
                    schema=tuple(EditorChartDataColumn(name=column.name) for column in table.columns),
                    rows=normalize_data_rows(table.rows, context=f"Chart data table {table_index}"),
                )
                for table_index, table in enumerate(result.results)
            )
        )
