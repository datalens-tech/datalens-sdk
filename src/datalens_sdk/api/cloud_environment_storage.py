from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.cloud_environment_storage import (
    CloudEnvironmentStorageConverter,
    CloudEnvironmentStorageDtoModule,
)
from datalens_sdk.domain.cloud_environment_storage import (
    CloudEnvironmentStorageObjectMetadata,
    CloudEnvironmentStorageSignedUrl,
)
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import CloudEnvironmentStorageOperations
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class CloudEnvironmentStorageAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def create_upload_url(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createBucketUploadUrl", payload)

    def create_download_url(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createBucketDownloadUrl", payload)

    def get_metadata(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getBucketObjectMetadata", payload, retry_policy=TRANSIENT_RETRY_POLICY
        )

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listBucketObjects", payload, retry_policy=TRANSIENT_RETRY_POLICY)


class CloudEnvironmentStorageService(CloudEnvironmentStorageOperations):
    def __init__(
        self, *, api: CloudEnvironmentStorageAPI, dto_module: CloudEnvironmentStorageDtoModule | None = None
    ) -> None:
        self._api = api
        self._dto_module = dto_module

    def create_bucket_upload_url(
        self, cloud_environment_id: str, path: str, size: str, content_md5: str
    ) -> CloudEnvironmentStorageSignedUrl:
        try:
            payload = CloudEnvironmentStorageConverter.upload_payload(
                cloud_environment_id, path, size, content_md5, dto_module=self._dto_module
            )
            raw = self._api.create_upload_url(payload.to_payload())
            return CloudEnvironmentStorageConverter.to_upload_url(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createBucketUploadUrl", reason=str(exc)) from exc

    def create_bucket_download_url(self, cloud_environment_id: str, path: str) -> CloudEnvironmentStorageSignedUrl:
        try:
            payload = CloudEnvironmentStorageConverter.download_payload(
                cloud_environment_id, path, dto_module=self._dto_module
            )
            raw = self._api.create_download_url(payload.to_payload())
            return CloudEnvironmentStorageConverter.to_download_url(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createBucketDownloadUrl", reason=str(exc)) from exc

    def get_bucket_object_metadata(self, cloud_environment_id: str, path: str) -> CloudEnvironmentStorageObjectMetadata:
        try:
            payload = CloudEnvironmentStorageConverter.metadata_payload(
                cloud_environment_id, path, dto_module=self._dto_module
            )
            raw = self._api.get_metadata(payload.to_payload())
            return CloudEnvironmentStorageConverter.to_metadata(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getBucketObjectMetadata", reason=str(exc)) from exc

    def list_bucket_objects(
        self,
        cloud_environment_id: str,
        prefix: str | None = None,
        page_size: int = 1000,
        page_token: str | None = None,
    ) -> Pager[str]:
        def load() -> Iterator[Page[str]]:
            token = page_token
            seen_tokens = {token} if token else set()
            while True:
                try:
                    payload = CloudEnvironmentStorageConverter.list_payload(
                        cloud_environment_id,
                        prefix=prefix,
                        page_size=page_size,
                        page_token=token,
                        dto_module=self._dto_module,
                    )
                    page = CloudEnvironmentStorageConverter.to_page(
                        self._api.list(payload.to_payload()), dto_module=self._dto_module
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listBucketObjects", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listBucketObjects", reason="pagination returned a repeated nextPageToken"
                    )
                seen_tokens.add(next_token)
                token = next_token

        return Pager(load)
