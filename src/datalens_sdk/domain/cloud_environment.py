from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeAlias

from typing_extensions import Self

from datalens_sdk.domain.lakehouse_operation import LakehouseOperation, LakehouseTimestamp
from datalens_sdk.domain.specs.cloud_environment import CloudEnvironmentCreateSpec, CloudEnvironmentUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.ports import CloudEnvironmentOperations

CloudEnvironmentStatus: TypeAlias = Literal["STATUS_UNSPECIFIED", "CREATING", "READY", "ERROR", "DELETING", "BROKEN"]
_UNBOUND_OPERATIONS = "Cloud environment is not bound to client operations"


@dataclass(frozen=True, slots=True)
class CloudEnvironmentStorageSettings:
    max_size: str


@dataclass(slots=True)
class CloudEnvironment:
    id: str
    name: str
    created_at: LakehouseTimestamp
    created_by_id: str
    updated_at: LakehouseTimestamp
    updated_by_id: str
    status: CloudEnvironmentStatus
    status_details: str
    cloud_id: str
    tenant_id: str
    subnet_id: str
    security_group_ids: tuple[str, ...]
    installation: str
    description: str | None
    permissions: Mapping[str, bool] | None
    storage: CloudEnvironmentStorageSettings | None
    raw: Mapping[str, object]
    _operations: CloudEnvironmentOperations | None = field(default=None, repr=False, compare=False)

    def refresh(self, *, include_permissions: bool | None = None) -> CloudEnvironment:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND_OPERATIONS)
        return self._operations.get_cloud_environment(self.id, include_permissions=include_permissions)

    def update(self) -> CloudEnvironmentUpdate:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND_OPERATIONS)
        return CloudEnvironmentUpdate(cloud_environment_id=self.id, operations=self._operations)

    def delete(self) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND_OPERATIONS)
        return self._operations.delete_cloud_environment(self.id)


class CloudEnvironmentCreate:
    def __init__(
        self,
        *,
        name: str,
        cloud_id: str,
        subnet_id: str,
        operations: CloudEnvironmentOperations | None,
    ) -> None:
        self._name = name
        self._cloud_id = cloud_id
        self._subnet_id = subnet_id
        self._operations = operations
        self._description: str | None = None
        self._security_group_ids: tuple[str, ...] | None = None
        self._storage: CloudEnvironmentStorageSettings | None = None

    def description(self, value: str) -> Self:
        if not isinstance(value, str):
            raise DataLensValidationError("description must be a string")
        self._description = value
        return self

    def security_group_ids(self, values: Sequence[str]) -> Self:
        self._security_group_ids = _string_tuple(values, field_name="security_group_ids")
        return self

    def storage(self, *, max_size: str) -> Self:
        if not isinstance(max_size, str):
            raise DataLensValidationError("storage max_size must be a string")
        self._storage = CloudEnvironmentStorageSettings(max_size=max_size)
        return self

    def to_spec(self) -> CloudEnvironmentCreateSpec:
        return CloudEnvironmentCreateSpec(
            name=self._name,
            cloud_id=self._cloud_id,
            subnet_id=self._subnet_id,
            description=self._description,
            security_group_ids=self._security_group_ids,
            storage=self._storage,
        )

    def build(self) -> LakehouseOperation:
        if self._operations is None:
            raise DataLensConfigurationError("Cloud environment create builder is not bound to client operations")
        return self._operations.create_cloud_environment(self)


class CloudEnvironmentUpdate:
    def __init__(self, *, cloud_environment_id: str, operations: CloudEnvironmentOperations) -> None:
        if not isinstance(cloud_environment_id, str) or not cloud_environment_id:
            raise DataLensValidationError("cloud_environment_id must be a non-empty string")
        self._cloud_environment_id = cloud_environment_id
        self._operations = operations
        self._name: str | None = None
        self._description: str | None = None
        self._security_group_ids: tuple[str, ...] | None = None
        self._storage: CloudEnvironmentStorageSettings | None = None
        self._configured = False

    def name(self, value: str) -> Self:
        self._name = value
        self._configured = True
        return self

    def description(self, value: str) -> Self:
        self._description = value
        self._configured = True
        return self

    def security_group_ids(self, values: Sequence[str]) -> Self:
        self._security_group_ids = _string_tuple(values, field_name="security_group_ids")
        self._configured = True
        return self

    def storage(self, *, max_size: str) -> Self:
        if not isinstance(max_size, str):
            raise DataLensValidationError("storage max_size must be a string")
        self._storage = CloudEnvironmentStorageSettings(max_size=max_size)
        self._configured = True
        return self

    def to_spec(self) -> CloudEnvironmentUpdateSpec:
        if not self._configured:
            raise DataLensValidationError("cloud environment update requires at least one field")
        return CloudEnvironmentUpdateSpec(
            cloud_environment_id=self._cloud_environment_id,
            name=self._name,
            description=self._description,
            security_group_ids=self._security_group_ids,
            storage=self._storage,
        )

    def execute(self) -> LakehouseOperation:
        self.to_spec()
        return self._operations.update_cloud_environment(self)


@dataclass(frozen=True, slots=True)
class CloudEnvironmentListOptions:
    filters: tuple[str, ...] = ()
    include_permissions: bool | None = None
    page_size: int = 100
    page_token: str | None = None

    @classmethod
    def create(
        cls,
        *,
        filters: Sequence[str] = (),
        include_permissions: bool | None = None,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> CloudEnvironmentListOptions:
        normalized_filters = _string_tuple(filters, field_name="filters")
        return cls(
            filters=normalized_filters,
            include_permissions=include_permissions,
            page_size=page_size,
            page_token=page_token,
        )


def _string_tuple(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise DataLensValidationError(f"{field_name} must be a sequence of strings")
    if any(not isinstance(value, str) for value in values):
        raise DataLensValidationError(f"{field_name} must contain only strings")
    return tuple(values)
