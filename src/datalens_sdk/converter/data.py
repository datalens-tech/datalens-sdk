from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.data import (
    DatasetData,
    DatasetDataColumn,
    DatasetDataQuery,
)
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_value


class DatasetDataWriteDTOProtocol(Protocol):
    def model_dump(
        self,
        *,
        mode: Literal["json"],
        by_alias: bool,
        exclude_unset: bool,
    ) -> dict[str, object]: ...


class DatasetDataArgsDTOClass(Protocol):
    def model_validate(self, obj: object) -> DatasetDataWriteDTOProtocol: ...


class DatasetDataColumnReadDTOProtocol(Protocol):
    name: str
    guid: str
    type: str


class DatasetDataReadDTOProtocol(Protocol):
    columns: Sequence[DatasetDataColumnReadDTOProtocol]
    rows: Sequence[Sequence[object]]


class DatasetDataReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> DatasetDataReadDTOProtocol: ...


class DatasetDataDtoModule(Protocol):
    DatasetDataArgsDTO: DatasetDataArgsDTOClass
    DatasetDataReadDTO: DatasetDataReadDTOClass


def _dto_module(dto_module: DatasetDataDtoModule | None) -> DatasetDataDtoModule:
    return cast(DatasetDataDtoModule, generated_dto if dto_module is None else dto_module)


class DatasetDataConverter:
    @staticmethod
    def request_payload(
        query: DatasetDataQuery,
        *,
        dto_module: DatasetDataDtoModule | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "datasetId": query.dataset_id,
            "columns": list(query.column_guids()),
            "limit": query.limit,
        }
        if query.filters:
            payload["filters"] = [
                {
                    "guid": guid,
                    "operation": item.operation.lower(),
                    "values": list(item.values),
                }
                for guid, item in zip(query.filter_guids(), query.filters, strict=True)
            ]
        if query.params:
            payload["params"] = [
                {"guid": guid, "value": item.value}
                for guid, item in zip(query.parameter_guids(), query.params, strict=True)
            ]
        if query.sort:
            payload["sort"] = [
                {"guid": guid, "direction": item.direction}
                for guid, item in zip(query.sort_guids(), query.sort, strict=True)
            ]
        if query.offset is not None:
            payload["offset"] = query.offset
        return (
            _dto_module(dto_module)
            .DatasetDataArgsDTO.model_validate(payload)
            .model_dump(
                mode="json",
                by_alias=True,
                exclude_unset=True,
            )
        )

    @staticmethod
    def result(
        raw: Mapping[str, object],
        *,
        dto_module: DatasetDataDtoModule | None = None,
    ) -> DatasetData:
        result = _dto_module(dto_module).DatasetDataReadDTO.model_validate(raw)
        columns = tuple(DatasetDataColumn(name=item.name, guid=item.guid, type=item.type) for item in result.columns)
        rows: list[tuple[JsonValue, ...]] = []
        for row_index, row in enumerate(result.rows):
            rows.append(
                tuple(
                    normalize_json_value(cell, context=f"Dataset data row {row_index} column {column_index}")
                    for column_index, cell in enumerate(row)
                )
            )
        return DatasetData(schema=columns, rows=tuple(rows))
