from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.spark_cluster import SparkClusterConverter, SparkClusterDtoModule
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import SparkClusterOperations
from datalens_sdk.domain.spark_cluster import (
    SparkCluster,
    SparkClusterListOptions,
    SparkResourcePreset,
    SparkResourcePresetListOptions,
)
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class SparkClusterAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getSparkCluster", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listSparkClusters", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def get_resource_preset(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getSparkResourcePreset", payload, retry_policy=TRANSIENT_RETRY_POLICY
        )

    def list_resource_presets(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/listSparkResourcePresets", payload, retry_policy=TRANSIENT_RETRY_POLICY
        )


class SparkClusterService(SparkClusterOperations):
    def __init__(
        self, *, installation: str, api: SparkClusterAPI, dto_module: SparkClusterDtoModule | None = None
    ) -> None:
        self._installation = installation
        self._api = api
        self._dto_module = dto_module

    def get_spark_cluster(self, spark_cluster_id: str) -> SparkCluster:
        if not isinstance(spark_cluster_id, str) or not spark_cluster_id:
            raise DataLensValidationError("getSparkCluster id must be a non-empty string")
        try:
            payload = SparkClusterConverter.get_payload(spark_cluster_id, dto_module=self._dto_module).to_payload()
            raw = self._api.get(payload)
            return SparkClusterConverter.to_cluster(
                raw,
                installation=self._installation,
                operations=self,
                operation="getSparkCluster",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getSparkCluster", reason=str(exc)) from exc

    def get_spark_resource_preset(self, resource_preset_id: str, *, cloud_environment_id: str) -> SparkResourcePreset:
        if not isinstance(resource_preset_id, str) or not resource_preset_id:
            raise DataLensValidationError("getSparkResourcePreset resource_preset_id must be a non-empty string")
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("getSparkResourcePreset cloud_environment_id must be a non-empty string")
        try:
            payload = SparkClusterConverter.get_resource_preset_payload(
                resource_preset_id,
                cloud_environment_id=cloud_environment_id,
                dto_module=self._dto_module,
            ).to_payload()
            raw = self._api.get_resource_preset(payload)
            return SparkClusterConverter.to_resource_preset(
                raw,
                installation=self._installation,
                cloud_environment_id=cloud_environment_id,
                operation="getSparkResourcePreset",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getSparkResourcePreset", reason=str(exc)) from exc

    def list_spark_clusters(self, options: SparkClusterListOptions) -> Pager[SparkCluster]:
        def load() -> Iterator[Page[SparkCluster]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = SparkClusterConverter.list_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    ).to_payload()
                    if page_token:
                        seen_tokens.add(page_token)
                    page = SparkClusterConverter.to_cluster_page(
                        self._api.list(payload),
                        installation=self._installation,
                        operations=self,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listSparkClusters", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listSparkClusters", reason="pagination returned a repeated nextPageToken"
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)

    def list_spark_resource_presets(self, options: SparkResourcePresetListOptions) -> Pager[SparkResourcePreset]:
        def load() -> Iterator[Page[SparkResourcePreset]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = SparkClusterConverter.list_resource_presets_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    ).to_payload()
                    if page_token:
                        seen_tokens.add(page_token)
                    page = SparkClusterConverter.to_resource_preset_page(
                        self._api.list_resource_presets(payload),
                        installation=self._installation,
                        cloud_environment_id=options.cloud_environment_id,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listSparkResourcePresets", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listSparkResourcePresets", reason="pagination returned a repeated nextPageToken"
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)
