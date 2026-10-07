from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter.lakehouse_operation import (
    LakehouseOperationReadDtoModule,
    LakehouseTimestampReadDTOProtocol,
    lakehouse_timestamp_from_dto,
)
from datalens_sdk.domain.cloud_environment import (
    CloudEnvironment,
    CloudEnvironmentListOptions,
    CloudEnvironmentStatus,
    CloudEnvironmentStorageSettings,
)
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.ports import CloudEnvironmentOperations
from datalens_sdk.domain.specs.cloud_environment import CloudEnvironmentCreateSpec, CloudEnvironmentUpdateSpec
from datalens_sdk.errors import translate_invalid_response_error


class CloudEnvironmentWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class CloudEnvironmentWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentWriteDTOProtocol: ...


class CloudEnvironmentStorageReadDTOProtocol(Protocol):
    @property
    def max_size(self) -> str: ...


class CloudEnvironmentReadDTOProtocol(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def created_at(self) -> LakehouseTimestampReadDTOProtocol: ...

    @property
    def created_by_id(self) -> str: ...

    @property
    def updated_at(self) -> LakehouseTimestampReadDTOProtocol: ...

    @property
    def updated_by_id(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def status_details(self) -> str: ...

    @property
    def cloud_id(self) -> str: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def subnet_id(self) -> str: ...

    @property
    def security_group_ids(self) -> Sequence[str]: ...

    @property
    def description(self) -> str | None: ...

    @property
    def permissions(self) -> Mapping[str, bool] | None: ...

    @property
    def storage(self) -> CloudEnvironmentStorageReadDTOProtocol | None: ...


class CloudEnvironmentReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentReadDTOProtocol: ...


class CloudEnvironmentListReadDTOProtocol(Protocol):
    @property
    def cloud_environments(self) -> Sequence[CloudEnvironmentReadDTOProtocol]: ...

    @property
    def next_page_token(self) -> str: ...


class CloudEnvironmentListReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> CloudEnvironmentListReadDTOProtocol: ...


class CloudEnvironmentDtoModule(LakehouseOperationReadDtoModule, Protocol):
    CreateCloudEnvironmentArgsDTO: CloudEnvironmentWriteDTOClass
    DeleteCloudEnvironmentArgsDTO: CloudEnvironmentWriteDTOClass
    GetCloudEnvironmentArgsDTO: CloudEnvironmentWriteDTOClass
    ListCloudEnvironmentsArgsDTO: CloudEnvironmentWriteDTOClass
    UpdateCloudEnvironmentArgsDTO: CloudEnvironmentWriteDTOClass
    CloudEnvironmentReadDTO: CloudEnvironmentReadDTOClass
    ListCloudEnvironmentsResultReadDTO: CloudEnvironmentListReadDTOClass


def _dto_module(dto_module: CloudEnvironmentDtoModule | None) -> CloudEnvironmentDtoModule:
    return cast(CloudEnvironmentDtoModule, generated_dto if dto_module is None else dto_module)


def _storage_payload(storage: CloudEnvironmentStorageSettings | None) -> dict[str, object] | None:
    if storage is None:
        return None
    return {"maxSize": storage.max_size}


class CloudEnvironmentConverter:
    @staticmethod
    def create_payload(
        spec: CloudEnvironmentCreateSpec,
        *,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> CloudEnvironmentWriteDTOProtocol:
        payload: dict[str, object] = {
            "name": spec.name,
            "cloudId": spec.cloud_id,
            "subnetId": spec.subnet_id,
        }
        if spec.description is not None:
            payload["description"] = spec.description
        if spec.security_group_ids is not None:
            payload["securityGroupIds"] = list(spec.security_group_ids)
        if spec.storage is not None:
            payload["storage"] = _storage_payload(spec.storage)
        return _dto_module(dto_module).CreateCloudEnvironmentArgsDTO.model_validate(payload)

    @staticmethod
    def update_payload(
        spec: CloudEnvironmentUpdateSpec,
        *,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> CloudEnvironmentWriteDTOProtocol:
        payload: dict[str, object] = {"id": spec.cloud_environment_id}
        if spec.name is not None:
            payload["name"] = spec.name
        if spec.description is not None:
            payload["description"] = spec.description
        if spec.security_group_ids is not None:
            payload["securityGroupIds"] = list(spec.security_group_ids)
        if spec.storage is not None:
            payload["storage"] = _storage_payload(spec.storage)
        return _dto_module(dto_module).UpdateCloudEnvironmentArgsDTO.model_validate(payload)

    @staticmethod
    def delete_payload(
        cloud_environment_id: str,
        *,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> CloudEnvironmentWriteDTOProtocol:
        return _dto_module(dto_module).DeleteCloudEnvironmentArgsDTO.model_validate({"id": cloud_environment_id})

    @staticmethod
    def get_payload(
        cloud_environment_id: str,
        *,
        include_permissions: bool | None,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> CloudEnvironmentWriteDTOProtocol:
        payload: dict[str, object] = {"id": cloud_environment_id}
        if include_permissions is not None:
            payload["includePermissions"] = include_permissions
        return _dto_module(dto_module).GetCloudEnvironmentArgsDTO.model_validate(payload)

    @staticmethod
    def list_payload(
        options: CloudEnvironmentListOptions,
        *,
        page_token: str | None,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> CloudEnvironmentWriteDTOProtocol:
        payload: dict[str, object] = {"pageSize": options.page_size}
        if options.filters:
            payload["filter"] = list(options.filters)
        if options.include_permissions is not None:
            payload["includePermissions"] = options.include_permissions
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListCloudEnvironmentsArgsDTO.model_validate(payload)

    @staticmethod
    def to_environment(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: CloudEnvironmentOperations | None,
        operation: str,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> CloudEnvironment:
        validated = _dto_module(dto_module).CloudEnvironmentReadDTO.model_validate(raw)
        try:
            created_at_raw = _mapping(raw["createdAt"], field="createdAt")
            updated_at_raw = _mapping(raw["updatedAt"], field="updatedAt")
            storage = None
            if validated.storage is not None:
                storage = CloudEnvironmentStorageSettings(max_size=validated.storage.max_size)
            return CloudEnvironment(
                id=validated.id,
                name=validated.name,
                created_at=_required_timestamp(created_at_raw, validated.created_at),
                created_by_id=validated.created_by_id,
                updated_at=_required_timestamp(updated_at_raw, validated.updated_at),
                updated_by_id=validated.updated_by_id,
                status=cast(CloudEnvironmentStatus, validated.status),
                status_details=validated.status_details,
                cloud_id=validated.cloud_id,
                tenant_id=validated.tenant_id,
                subnet_id=validated.subnet_id,
                security_group_ids=tuple(validated.security_group_ids),
                installation=installation,
                description=validated.description,
                permissions=validated.permissions,
                storage=storage,
                raw=dict(raw),
                _operations=operations,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation=operation, reason=str(exc)) from exc

    @staticmethod
    def to_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: CloudEnvironmentOperations | None,
        dto_module: CloudEnvironmentDtoModule | None = None,
    ) -> Page[CloudEnvironment]:
        validated = _dto_module(dto_module).ListCloudEnvironmentsResultReadDTO.model_validate(raw)
        environments = []
        raw_environments = raw["cloudEnvironments"]
        if not isinstance(raw_environments, Sequence) or isinstance(raw_environments, (str, bytes)):
            raise translate_invalid_response_error(
                operation="listCloudEnvironments", reason="cloudEnvironments is not an array"
            )
        for raw_environment in raw_environments:
            if not isinstance(raw_environment, Mapping):
                raise translate_invalid_response_error(
                    operation="listCloudEnvironments", reason="cloud environment is not an object"
                )
            environments.append(
                CloudEnvironmentConverter.to_environment(
                    cast(Mapping[str, object], raw_environment),
                    installation=installation,
                    operations=operations,
                    operation="listCloudEnvironments",
                    dto_module=dto_module,
                )
            )
        return Page(items=tuple(environments), next_page_token=validated.next_page_token)


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} is not an object")
    return cast(Mapping[str, object], value)


def _required_timestamp(raw: Mapping[str, object], dto: LakehouseTimestampReadDTOProtocol) -> LakehouseTimestamp:
    timestamp = lakehouse_timestamp_from_dto(raw, dto=dto)
    if timestamp is None:
        raise ValueError("required timestamp is missing")
    return timestamp
