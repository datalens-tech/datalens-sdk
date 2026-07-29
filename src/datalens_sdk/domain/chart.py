from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from typing_extensions import Self

from datalens_sdk.domain.chart_types import ChartCategory
from datalens_sdk.domain.connection import _optional_str
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    dir_path_from_location,
    key_from_location,
    validate_entry_name,
    workbook_id_from_location,
)
from datalens_sdk.domain.navigation import EntryRelation, EntryScope, LinkDirection, Pager, RelationOptions
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.errors import DatalensConfigurationError, DatalensValidationError
from datalens_sdk.serialization.artifacts import ArtifactPath, write_chart_artifact
from datalens_sdk.serialization.json_types import JsonValue

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


class ChartUpdate(Protocol):
    def execute(self) -> Chart: ...


@dataclass(slots=True)
class Chart(ABC):
    id: str | None
    installation: str = ""
    name: str | None = None
    location: EntryLocation | None = None
    wire_type: str | None = None
    data: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    response_snapshot: Mapping[str, JsonValue] = field(default_factory=dict, repr=False, compare=False)
    _operations: ChartOperations | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.name is None:
            self.name = _optional_str(self.raw.get("name"))

    @property
    def key(self) -> str | None:
        return _optional_str(self.raw.get("key")) or key_from_location(self.location, name=self.name)

    @property
    def dir_path(self) -> str | None:
        return dir_path_from_location(self.location) or _optional_str(self.raw.get("dir_path"))

    @property
    def workbook_id(self) -> str | None:
        return workbook_id_from_location(self.location) or _optional_str(self.raw.get("workbook_id"))

    @property
    def collection_id(self) -> str | None:
        return collection_id_from_location(self.location) or _optional_str(self.raw.get("collection_id"))

    @property
    def description(self) -> str | None:
        annotation = self.raw.get("annotation")
        if not isinstance(annotation, Mapping):
            return None
        return _optional_str(annotation.get("description"))

    def get_relations(
        self,
        *,
        include_permissions_info: bool | None = None,
        link_direction: LinkDirection | None = None,
        page_size: int = 100,
        scope: EntryScope | None = None,
    ) -> Pager[EntryRelation]:
        if self._operations is None:
            raise DatalensConfigurationError(_UNBOUND)
        if not self.id:
            raise DatalensValidationError("Cannot get relations for a chart without an id")
        return self._operations.get_entry_relations(
            self.id,
            RelationOptions(
                include_permissions_info=include_permissions_info,
                link_direction=link_direction,
                page_size=page_size,
                scope=scope,
            ),
        )

    def rename(self, name: str) -> Self:
        if self._operations is None:
            raise DatalensConfigurationError(_UNBOUND)
        if not self.id:
            raise DatalensValidationError("Cannot rename a chart without an id")
        validate_entry_name(name=name, location=self.location)
        return cast(Self, self._operations.rename_chart(self, name))

    def _write_artifact(
        self,
        path: ArtifactPath,
        *,
        split_tabs: bool,
    ) -> Path:
        return write_chart_artifact(
            path,
            self.response_snapshot,
            name=self.name,
            resource_id=self.id,
            category=self.category,
            split_tabs=split_tabs,
        )

    def to_file(self, path: ArtifactPath) -> Path:
        return self._write_artifact(path, split_tabs=False)

    @property
    @abstractmethod
    def category(self) -> ChartCategory: ...

    @property
    @abstractmethod
    def update(self) -> ChartUpdate: ...

    @abstractmethod
    def delete(self) -> None: ...
