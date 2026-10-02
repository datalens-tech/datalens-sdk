from __future__ import annotations

from pydantic import ValidationError

from datalens_sdk.converter.lakehouse_operation import LakehouseOperationConverter, LakehouseOperationDtoModule
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.ports import LakehouseOperationOperations
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class LakehouseOperationAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getLakehouseOperation", payload, retry_policy=TRANSIENT_RETRY_POLICY)


class LakehouseOperationService(LakehouseOperationOperations):
    def __init__(self, *, api: LakehouseOperationAPI, dto_module: LakehouseOperationDtoModule | None = None) -> None:
        self._api = api
        self._dto_module = dto_module

    def get_lakehouse_operation(self, operation_id: str) -> LakehouseOperation:
        try:
            dto = LakehouseOperationConverter.from_domain_get(operation_id, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getLakehouseOperation", reason=str(exc)) from exc
        response = self._api.get(dto.to_payload())
        try:
            operation = LakehouseOperationConverter.to_operation(
                response,
                operations=self,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getLakehouseOperation", reason=str(exc)) from exc
        if operation.id != operation_id:
            raise translate_invalid_response_error(
                operation="getLakehouseOperation",
                reason=f"response ID {operation.id!r} does not match requested ID {operation_id!r}",
            )
        return operation
