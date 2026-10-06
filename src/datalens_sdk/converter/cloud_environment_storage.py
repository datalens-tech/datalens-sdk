from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter.lakehouse_operation import LakehouseTimestampReadDTOProtocol, lakehouse_timestamp_from_dto
from datalens_sdk.domain.cloud_environment_storage import (
    CloudEnvironmentStorageObjectMetadata,
    CloudEnvironmentStorageSignedUrl,
)
from datalens_sdk.domain.navigation import Page
from datalens_sdk.errors import translate_invalid_response_error


class CloudEnvironmentStorageWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class CloudEnvironmentStorageWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentStorageWriteDTOProtocol: ...


class CloudEnvironmentStorageSignedUrlReadDTOProtocol(Protocol):
    @property
    def url(self) -> str: ...


class CloudEnvironmentStorageSignedUrlReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentStorageSignedUrlReadDTOProtocol: ...


class CloudEnvironmentStorageObjectMetadataReadDTOProtocol(Protocol):
    @property
    def size(self) -> str: ...

    @property
    def last_modified(self) -> LakehouseTimestampReadDTOProtocol | None: ...


class CloudEnvironmentStorageObjectMetadataReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentStorageObjectMetadataReadDTOProtocol: ...


class CloudEnvironmentStorageListReadDTOProtocol(Protocol):
    @property
    def keys(self) -> Sequence[str]: ...

    @property
    def next_page_token(self) -> str: ...


class CloudEnvironmentStorageListReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentStorageListReadDTOProtocol: ...


class CloudEnvironmentStorageDtoModule(Protocol):
    CreateBucketUploadUrlArgsDTO: CloudEnvironmentStorageWriteDTOClass
    CreateBucketDownloadUrlArgsDTO: CloudEnvironmentStorageWriteDTOClass
    GetBucketObjectMetadataArgsDTO: CloudEnvironmentStorageWriteDTOClass
    ListBucketObjectsArgsDTO: CloudEnvironmentStorageWriteDTOClass
    CreateBucketUploadUrlResultReadDTO: CloudEnvironmentStorageSignedUrlReadDTOClass
    CreateBucketDownloadUrlResultReadDTO: CloudEnvironmentStorageSignedUrlReadDTOClass
    GetBucketObjectMetadataResultReadDTO: CloudEnvironmentStorageObjectMetadataReadDTOClass
    ListBucketObjectsResultReadDTO: CloudEnvironmentStorageListReadDTOClass


def _dto_module(dto_module: CloudEnvironmentStorageDtoModule | None) -> CloudEnvironmentStorageDtoModule:
    return cast(CloudEnvironmentStorageDtoModule, generated_dto if dto_module is None else dto_module)


class CloudEnvironmentStorageConverter:
    @staticmethod
    def upload_payload(
        cloud_environment_id: str,
        path: str,
        size: str,
        content_md5: str,
        *,
        dto_module: CloudEnvironmentStorageDtoModule | None = None,
    ) -> CloudEnvironmentStorageWriteDTOProtocol:
        return _dto_module(dto_module).CreateBucketUploadUrlArgsDTO.model_validate(
            {"cloudEnvironmentId": cloud_environment_id, "path": path, "size": size, "contentMd5": content_md5}
        )

    @staticmethod
    def download_payload(
        cloud_environment_id: str,
        path: str,
        *,
        dto_module: CloudEnvironmentStorageDtoModule | None = None,
    ) -> CloudEnvironmentStorageWriteDTOProtocol:
        return _dto_module(dto_module).CreateBucketDownloadUrlArgsDTO.model_validate(
            {"cloudEnvironmentId": cloud_environment_id, "path": path}
        )

    @staticmethod
    def metadata_payload(
        cloud_environment_id: str,
        path: str,
        *,
        dto_module: CloudEnvironmentStorageDtoModule | None = None,
    ) -> CloudEnvironmentStorageWriteDTOProtocol:
        return _dto_module(dto_module).GetBucketObjectMetadataArgsDTO.model_validate(
            {"cloudEnvironmentId": cloud_environment_id, "path": path}
        )

    @staticmethod
    def list_payload(
        cloud_environment_id: str,
        *,
        prefix: str | None,
        page_size: int,
        page_token: str | None,
        dto_module: CloudEnvironmentStorageDtoModule | None = None,
    ) -> CloudEnvironmentStorageWriteDTOProtocol:
        payload: dict[str, object] = {"cloudEnvironmentId": cloud_environment_id, "pageSize": page_size}
        if prefix is not None:
            payload["prefix"] = prefix
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListBucketObjectsArgsDTO.model_validate(payload)

    @staticmethod
    def to_upload_url(
        raw: Mapping[str, object], *, dto_module: CloudEnvironmentStorageDtoModule | None = None
    ) -> CloudEnvironmentStorageSignedUrl:
        validated = _dto_module(dto_module).CreateBucketUploadUrlResultReadDTO.model_validate(raw)
        return CloudEnvironmentStorageSignedUrl(url=validated.url)

    @staticmethod
    def to_download_url(
        raw: Mapping[str, object], *, dto_module: CloudEnvironmentStorageDtoModule | None = None
    ) -> CloudEnvironmentStorageSignedUrl:
        validated = _dto_module(dto_module).CreateBucketDownloadUrlResultReadDTO.model_validate(raw)
        return CloudEnvironmentStorageSignedUrl(url=validated.url)

    @staticmethod
    def to_metadata(
        raw: Mapping[str, object], *, dto_module: CloudEnvironmentStorageDtoModule | None = None
    ) -> CloudEnvironmentStorageObjectMetadata:
        validated = _dto_module(dto_module).GetBucketObjectMetadataResultReadDTO.model_validate(raw)
        try:
            timestamp = lakehouse_timestamp_from_dto(
                cast(Mapping[str, object] | None, raw.get("lastModified")), dto=validated.last_modified
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation="getBucketObjectMetadata", reason=str(exc)) from exc
        return CloudEnvironmentStorageObjectMetadata(size=validated.size, last_modified=timestamp)

    @staticmethod
    def to_page(raw: Mapping[str, object], *, dto_module: CloudEnvironmentStorageDtoModule | None = None) -> Page[str]:
        validated = _dto_module(dto_module).ListBucketObjectsResultReadDTO.model_validate(raw)
        return Page(items=tuple(validated.keys), next_page_token=validated.next_page_token)
