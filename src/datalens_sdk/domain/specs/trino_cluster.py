from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk.domain.trino_cluster import TrinoWorkerConfig


@dataclass(frozen=True, slots=True)
class TrinoClusterCreateSpec:
    name: str
    location: EntryLocation
    cloud_environment_id: str
    worker: TrinoWorkerConfig
    description: str | None
    labels: Mapping[str, str] | None
    trino_version: str | None
    catalog_ids: tuple[str, ...] | None = None
