from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from datalens_sdk.domain.dataset_types import (
    DatasetCreateRelationPayload,
    DatasetUpdateAction,
    RLS2ConfigEntryPayload,
)
from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk.domain.dataset import Source

__all__ = ["DatasetCreateSpec", "DatasetUpdateSpec"]


@dataclass(frozen=True, slots=True)
class DatasetCreateSpec:
    """Immutable snapshot of a dataset-create builder's state.

    This is the read contract between the domain builder layer and the
    converter/api layers. Converters and services consume this spec instead of
    reaching into builder ``_protected`` attributes.
    """

    installation: str
    name: str
    location: EntryLocation
    description: str
    sources: tuple[Source, ...]
    relations: tuple[DatasetCreateRelationPayload, ...]
    actions: tuple[DatasetUpdateAction, ...]
    rls2_changes: Mapping[str, list[RLS2ConfigEntryPayload] | None]


@dataclass(frozen=True, slots=True)
class DatasetUpdateSpec:
    """Immutable snapshot of a dataset-update builder's state.

    The ``raw`` field carries the dataset's raw mapping (the full read
    response), not the entire ``Dataset`` domain object, so the converter never
    needs to touch ``builder._dataset``.
    """

    dataset_id: str
    name: str | None
    location: EntryLocation | None
    raw: Mapping[str, object]
    actions: tuple[DatasetUpdateAction, ...]
    name_change: str | None
    rls2_changes: Mapping[str, list[RLS2ConfigEntryPayload] | None]
