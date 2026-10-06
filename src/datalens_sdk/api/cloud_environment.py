from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.cloud_environment import CloudEnvironmentConverter, CloudEnvironmentDtoModule
from datalens_sdk.converter.lakehouse_operation import LakehouseOperationConverter
from datalens_sdk.domain.cloud_environment import (
    CloudEnvironment,
    CloudEnvironmentCreate,
    CloudEnvironmentListOptions,
    CloudEnvironmentUpdate,
)
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import CloudEnvironmentOperations, LakehouseOperationOperations
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class CloudEnvironmentAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createCloudEnvironment", payload)

    def delete(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/deleteCloudEnvironment", payload)

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getCloudEnvironment", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listCloudEnvironments", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/updateCloudEnvironment", payload)


class CloudEnvironmentService(CloudEnvironmentOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: CloudEnvironmentAPI,
        lakehouse_operations: LakehouseOperationOperations,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._lakehouse_operations = lakehouse_operations
        self._dto_module = dto_module

    def create_cloud_environment(self, builder: CloudEnvironmentCreate) -> LakehouseOperation:
        try:
            payload = CloudEnvironmentConverter.create_payload(builder.to_spec(), dto_module=self._dto_module)
            raw = self._api.create(payload.to_payload())
            return LakehouseOperationConverter.to_operation(
                raw,
                operations=self._lakehouse_operations,
                operation="createCloudEnvironment",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createCloudEnvironment", reason=str(exc)) from exc

    def update_cloud_environment(self, builder: CloudEnvironmentUpdate) -> LakehouseOperation:
        try:
            payload = CloudEnvironmentConverter.update_payload(builder.to_spec(), dto_module=self._dto_module)
            raw = self._api.update(payload.to_payload())
            return LakehouseOperationConverter.to_operation(
                raw,
                operations=self._lakehouse_operations,
                operation="updateCloudEnvironment",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateCloudEnvironment", reason=str(exc)) from exc

    def delete_cloud_environment(self, cloud_environment_id: str) -> LakehouseOperation:
        try:
            payload = CloudEnvironmentConverter.delete_payload(cloud_environment_id, dto_module=self._dto_module)
            raw = self._api.delete(payload.to_payload())
            return LakehouseOperationConverter.to_operation(
                raw,
                operations=self._lakehouse_operations,
                operation="deleteCloudEnvironment",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="deleteCloudEnvironment", reason=str(exc)) from exc

    def get_cloud_environment(
        self, cloud_environment_id: str, *, include_permissions: bool | None = None
    ) -> CloudEnvironment:
        try:
            payload = CloudEnvironmentConverter.get_payload(
                cloud_environment_id,
                include_permissions=include_permissions,
                dto_module=self._dto_module,
            )
            raw = self._api.get(payload.to_payload())
            return CloudEnvironmentConverter.to_environment(
                raw,
                installation=self._installation,
                operations=self,
                operation="getCloudEnvironment",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getCloudEnvironment", reason=str(exc)) from exc

    def list_cloud_environments(self, options: CloudEnvironmentListOptions) -> Pager[CloudEnvironment]:
        def load() -> Iterator[Page[CloudEnvironment]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    dto = CloudEnvironmentConverter.list_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    )
                    payload = dto.to_payload()
                    if page_token:
                        seen_tokens.add(page_token)
                    page = CloudEnvironmentConverter.to_page(
                        self._api.list(payload),
                        installation=self._installation,
                        operations=self,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listCloudEnvironments", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listCloudEnvironments", reason="pagination returned a repeated nextPageToken"
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)
