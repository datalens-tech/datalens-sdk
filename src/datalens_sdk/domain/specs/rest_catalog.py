from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datalens_sdk.domain.rest_catalog import RestCatalogBucketSettings


@dataclass(frozen=True, slots=True)
class RestCatalogCreateSpec:
    name: str
    cloud_environment_id: str
    bucket_settings: RestCatalogBucketSettings
    description: str | None
    labels: Mapping[str, str] | None
