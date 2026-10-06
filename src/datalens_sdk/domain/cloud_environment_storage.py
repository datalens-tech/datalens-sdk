from __future__ import annotations

from dataclasses import dataclass, field

from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp


@dataclass(frozen=True, slots=True)
class CloudEnvironmentStorageSignedUrl:
    url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CloudEnvironmentStorageObjectMetadata:
    size: str
    last_modified: LakehouseTimestamp | None = None
