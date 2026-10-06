from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datalens_sdk.domain.cloud_environment import CloudEnvironmentStorageSettings


@dataclass(frozen=True, slots=True)
class CloudEnvironmentCreateSpec:
    name: str
    cloud_id: str
    subnet_id: str
    description: str | None
    security_group_ids: tuple[str, ...] | None
    storage: CloudEnvironmentStorageSettings | None


@dataclass(frozen=True, slots=True)
class CloudEnvironmentUpdateSpec:
    cloud_environment_id: str
    name: str | None
    description: str | None
    security_group_ids: tuple[str, ...] | None
    storage: CloudEnvironmentStorageSettings | None
