from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from datalens_sdk.domain.dataset_types import RLSPatternType, RLSSubjectType
from datalens_sdk.domain.fields import DatasetField, FieldRef
from datalens_sdk.errors import DataLensValidationError


@dataclass(frozen=True, slots=True)
class RLSFieldRef:
    value: str
    by_guid: bool = False

    @classmethod
    def from_field(cls, field: FieldRef, *, dataset_id: str | None, fields: Sequence[DatasetField]) -> RLSFieldRef:
        if isinstance(field, DatasetField):
            if field.dataset_id is not None and field.dataset_id != dataset_id:
                raise DataLensValidationError("RLS field belongs to another dataset")
            return cls(field.guid, by_guid=True)
        return cls(field, by_guid=any(candidate.guid == field for candidate in fields))


@dataclass(frozen=True, slots=True)
class RLSRule:
    subject_id: str
    allowed_value: str | None = None
    subject_type: RLSSubjectType = "user"
    subject_name: str | None = None
    pattern_type: RLSPatternType = "value"


@dataclass(frozen=True, slots=True)
class RLSAdd:
    field: RLSFieldRef
    rule: RLSRule


@dataclass(frozen=True, slots=True)
class RLSUpdate:
    field: RLSFieldRef
    rule: RLSRule


@dataclass(frozen=True, slots=True)
class RLSDelete:
    field: RLSFieldRef


@dataclass(frozen=True, slots=True)
class RLSClear:
    """Explicitly clear the dataset's complete RLS rule set."""


RLSChange: TypeAlias = RLSAdd | RLSUpdate | RLSDelete | RLSClear
