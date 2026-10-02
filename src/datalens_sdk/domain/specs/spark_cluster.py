from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk.domain.spark_cluster import SparkResourcePoolConfig


@dataclass(frozen=True, slots=True)
class SparkClusterCreateSpec:
    name: str
    location: EntryLocation
    cloud_environment_id: str
    driver: SparkResourcePoolConfig
    executor: SparkResourcePoolConfig
    dependencies_configured: bool
    pip_packages: tuple[str, ...] | None
    deb_packages: tuple[str, ...] | None
    logging_enabled: bool | None
    spark_version: str | None
    description: str | None
    labels: Mapping[str, str] | None
