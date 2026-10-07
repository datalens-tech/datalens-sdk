from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.lakehouse_operation import LakehouseOperationConverter
from datalens_sdk.converter.trino_cluster import TrinoClusterConverter, TrinoClusterDtoModule
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import LakehouseOperationOperations, TrinoClusterOperations
from datalens_sdk.domain.trino_cluster import (
    TrinoCluster,
    TrinoClusterCreate,
    TrinoClusterListOptions,
    TrinoResourcePreset,
    TrinoResourcePresetListOptions,
)
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class TrinoClusterAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createTrinoCluster", payload)

    def start(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/startTrinoCluster", payload)

    def stop(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/stopTrinoCluster", payload)

    def delete(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/deleteTrinoCluster", payload)

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getTrinoCluster", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listTrinoClusters", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def get_resource_preset(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getTrinoResourcePreset", payload, retry_policy=TRANSIENT_RETRY_POLICY
        )

    def list_resource_presets(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/listTrinoResourcePresets", payload, retry_policy=TRANSIENT_RETRY_POLICY
        )


class TrinoClusterService(TrinoClusterOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: TrinoClusterAPI,
        lakehouse_operations: LakehouseOperationOperations,
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._lakehouse_operations = lakehouse_operations
        self._dto_module = dto_module

    def _to_operation(self, raw: dict[str, object], *, operation: str) -> LakehouseOperation:
        return LakehouseOperationConverter.to_operation(
            raw,
            operations=self._lakehouse_operations,
            operation=operation,
            dto_module=self._dto_module,
        )

    def create_trino_cluster(self, builder: TrinoClusterCreate) -> LakehouseOperation:
        try:
            dto = TrinoClusterConverter.create_payload(builder.to_spec(), dto_module=self._dto_module)
            raw = self._api.create(dto.to_payload())
            return self._to_operation(raw, operation="createTrinoCluster")
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createTrinoCluster", reason=str(exc)) from exc

    def start_trino_cluster(self, cluster_id: str) -> LakehouseOperation:
        try:
            dto = TrinoClusterConverter.start_payload(cluster_id, dto_module=self._dto_module)
            return self._to_operation(self._api.start(dto.to_payload()), operation="startTrinoCluster")
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="startTrinoCluster", reason=str(exc)) from exc

    def stop_trino_cluster(self, cluster_id: str) -> LakehouseOperation:
        try:
            dto = TrinoClusterConverter.stop_payload(cluster_id, dto_module=self._dto_module)
            return self._to_operation(self._api.stop(dto.to_payload()), operation="stopTrinoCluster")
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="stopTrinoCluster", reason=str(exc)) from exc

    def delete_trino_cluster(self, trino_cluster_id: str) -> LakehouseOperation:
        try:
            dto = TrinoClusterConverter.delete_payload(trino_cluster_id, dto_module=self._dto_module)
            return self._to_operation(self._api.delete(dto.to_payload()), operation="deleteTrinoCluster")
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="deleteTrinoCluster", reason=str(exc)) from exc

    def get_trino_cluster(self, trino_cluster_id: str) -> TrinoCluster:
        try:
            dto = TrinoClusterConverter.get_payload(trino_cluster_id, dto_module=self._dto_module)
            return TrinoClusterConverter.to_cluster(
                self._api.get(dto.to_payload()),
                installation=self._installation,
                operations=self,
                operation="getTrinoCluster",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getTrinoCluster", reason=str(exc)) from exc

    def list_trino_clusters(self, options: TrinoClusterListOptions) -> Pager[TrinoCluster]:
        def load() -> Iterator[Page[TrinoCluster]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    dto = TrinoClusterConverter.list_payload(
                        options, page_token=page_token, dto_module=self._dto_module
                    )
                    if page_token:
                        seen_tokens.add(page_token)
                    page = TrinoClusterConverter.to_cluster_page(
                        self._api.list(dto.to_payload()),
                        installation=self._installation,
                        operations=self,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listTrinoClusters", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listTrinoClusters", reason="pagination returned a repeated nextPageToken"
                    )
                page_token = next_token

        return Pager(load)

    def get_trino_resource_preset(
        self,
        resource_preset_id: str,
        *,
        cloud_environment_id: str,
    ) -> TrinoResourcePreset:
        try:
            dto = TrinoClusterConverter.get_resource_preset_payload(
                resource_preset_id,
                cloud_environment_id=cloud_environment_id,
                dto_module=self._dto_module,
            )
            return TrinoClusterConverter.to_resource_preset(
                self._api.get_resource_preset(dto.to_payload()),
                installation=self._installation,
                cloud_environment_id=cloud_environment_id,
                operation="getTrinoResourcePreset",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getTrinoResourcePreset", reason=str(exc)) from exc

    def list_trino_resource_presets(self, options: TrinoResourcePresetListOptions) -> Pager[TrinoResourcePreset]:
        def load() -> Iterator[Page[TrinoResourcePreset]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    dto = TrinoClusterConverter.list_resource_presets_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    )
                    if page_token:
                        seen_tokens.add(page_token)
                    page = TrinoClusterConverter.to_resource_preset_page(
                        self._api.list_resource_presets(dto.to_payload()),
                        installation=self._installation,
                        cloud_environment_id=options.cloud_environment_id,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listTrinoResourcePresets", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listTrinoResourcePresets", reason="pagination returned a repeated nextPageToken"
                    )
                page_token = next_token

        return Pager(load)
