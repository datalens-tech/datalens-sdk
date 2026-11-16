from typing import Protocol

from pydantic import ValidationError

from datalens_sdk.converter.chart_data import ChartDataConverter, ChartDataDtoModule
from datalens_sdk.converter.data import DatasetDataConverter, DatasetDataDtoModule
from datalens_sdk.domain.chart_data import ChartData, ChartDataQuery
from datalens_sdk.domain.data import DatasetData, DatasetDataQuery
from datalens_sdk.domain.ports import DataOperations
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class DataDtoModule(DatasetDataDtoModule, ChartDataDtoModule, Protocol):
    pass


class DataAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get_dataset_data(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getDatasetData",
            payload,
            retry_policy=TRANSIENT_RETRY_POLICY,
        )

    def get_chart_data(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getChartData",
            payload,
            retry_policy=TRANSIENT_RETRY_POLICY,
        )


class DataService(DataOperations):
    def __init__(self, *, api: DataAPI, dto_module: DataDtoModule | None = None) -> None:
        self._api = api
        self._dto_module = dto_module

    def get_dataset_data(self, query: DatasetDataQuery) -> DatasetData:
        # Preserve the existing dataset request/response exception boundary.
        try:
            payload = DatasetDataConverter.request_payload(query, dto_module=self._dto_module)
            response = self._api.get_dataset_data(payload)
            return DatasetDataConverter.result(response, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getDatasetData", reason=str(exc)) from exc

    def get_chart_data(self, query: ChartDataQuery) -> ChartData:
        try:
            payload = ChartDataConverter.request_payload(query, dto_module=self._dto_module)
        except ValidationError as exc:
            raise DataLensValidationError(f"Invalid getChartData request: {exc}") from exc
        response = self._api.get_chart_data(payload)
        try:
            return ChartDataConverter.result(response, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getChartData", reason=str(exc)) from exc
        except DataLensValidationError as exc:
            raise translate_invalid_response_error(operation="getChartData", reason=str(exc)) from exc
