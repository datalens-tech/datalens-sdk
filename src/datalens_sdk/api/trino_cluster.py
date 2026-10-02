from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.trino_cluster import TrinoClusterConverter, TrinoClusterDtoModule
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import TrinoClusterOperations
from datalens_sdk.domain.trino_cluster import (
    TrinoCluster,
    TrinoClusterListOptions,
    TrinoResourcePreset,
    TrinoResourcePresetListOptions,
)
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class TrinoClusterAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

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
        dto_module: TrinoClusterDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._dto_module = dto_module

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
