from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class _SparkApplicationCommonCreateSpec:
    archive_uris: tuple[str, ...] | None = None
    file_uris: tuple[str, ...] | None = None
    jar_file_uris: tuple[str, ...] | None = None
    packages: tuple[str, ...] | None = None
    repositories: tuple[str, ...] | None = None
    exclude_packages: tuple[str, ...] | None = None
    properties: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SparkApplicationSparkCreateSpec(_SparkApplicationCommonCreateSpec):
    main_jar_file_uri: str
    main_class: str | None = None
    args: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SparkApplicationPySparkCreateSpec(_SparkApplicationCommonCreateSpec):
    main_python_file_uri: str
    args: tuple[str, ...] | None = None
    python_file_uris: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SparkApplicationConnectCreateSpec(_SparkApplicationCommonCreateSpec):
    pass


@dataclass(frozen=True, slots=True)
class SparkApplicationCreateSpec:
    cluster_id: str
    name: str | None
    catalog_ids: tuple[str, ...] | None
    variant: SparkApplicationSparkCreateSpec | SparkApplicationPySparkCreateSpec | SparkApplicationConnectCreateSpec
