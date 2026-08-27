from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import TypeAlias, get_args

from typing_extensions import Self

from datalens_sdk.domain.common_types import SortDirection
from datalens_sdk.domain.dataset_types import WhereOperation
from datalens_sdk.domain.fields import DatasetField, FieldRef
from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.serialization.json_types import JsonValue

DatasetDataScalar: TypeAlias = str | int | float | bool
_FILTER_OPERATIONS = frozenset(get_args(WhereOperation))
_SORT_DIRECTIONS = frozenset(get_args(SortDirection))


def _field_guid(field: FieldRef, *, dataset_id: str) -> str:
    if isinstance(field, DatasetField):
        if field.dataset_id is not None and field.dataset_id != dataset_id:
            raise DataLensValidationError(
                f"Field {field.guid!r} belongs to dataset {field.dataset_id!r}, not {dataset_id!r}"
            )
        guid = field.guid
    else:
        guid = field
    if not guid:
        raise DataLensValidationError("Dataset data field GUID must not be empty")
    return guid


def _validate_scalar(value: DatasetDataScalar, *, context: str) -> None:
    if not isinstance(value, (str, int, float, bool)):
        raise DataLensValidationError(f"{context} must be a string, number, or boolean")
    if isinstance(value, float) and not math.isfinite(value):
        raise DataLensValidationError(f"{context} must be finite")


@dataclass(frozen=True, slots=True)
class DatasetDataFilter:
    field: FieldRef
    operation: WhereOperation
    values: tuple[DatasetDataScalar, ...] = ()

    def __post_init__(self) -> None:
        if self.operation not in _FILTER_OPERATIONS:
            raise DataLensValidationError(f"Unsupported dataset data filter operation: {self.operation!r}")
        for index, value in enumerate(self.values):
            _validate_scalar(value, context=f"Filter value at index {index}")


@dataclass(frozen=True, slots=True)
class DatasetDataParameter:
    field: FieldRef
    value: DatasetDataScalar

    def __post_init__(self) -> None:
        _validate_scalar(self.value, context="Parameter value")


@dataclass(frozen=True, slots=True)
class DatasetDataSort:
    field: FieldRef
    direction: SortDirection

    def __post_init__(self) -> None:
        if self.direction not in _SORT_DIRECTIONS:
            raise DataLensValidationError(f"Unsupported dataset data sort direction: {self.direction!r}")


@dataclass(frozen=True, slots=True)
class DatasetDataColumn:
    name: str
    guid: str
    type: str


@dataclass(frozen=True, slots=True)
class DatasetData:
    schema: tuple[DatasetDataColumn, ...]
    rows: tuple[tuple[JsonValue, ...], ...]


@dataclass(frozen=True, slots=True)
class DatasetDataQuery:
    dataset_id: str
    columns: tuple[FieldRef, ...]
    filters: tuple[DatasetDataFilter, ...] = ()
    params: tuple[DatasetDataParameter, ...] = ()
    sort: tuple[DatasetDataSort, ...] = ()
    limit: int = 500
    offset: int | None = None

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise DataLensValidationError("dataset_id must not be empty")
        if not self.columns:
            raise DataLensValidationError("columns must contain at least one field")
        if not 1 <= self.limit <= 100000:
            raise DataLensValidationError("limit must be between 1 and 100000")
        if self.offset is not None and self.offset < 0:
            raise DataLensValidationError("offset must be greater than or equal to 0")
        if self.offset is not None and self.offset > 0 and not self.sort:
            raise DataLensValidationError("offset greater than 0 requires sort")

        column_guids = set(self.column_guids())
        for filter_item in self.filters:
            _field_guid(filter_item.field, dataset_id=self.dataset_id)
        for parameter_item in self.params:
            _field_guid(parameter_item.field, dataset_id=self.dataset_id)
        for sort_item in self.sort:
            guid = _field_guid(sort_item.field, dataset_id=self.dataset_id)
            if guid not in column_guids:
                raise DataLensValidationError(f"Sort field {guid!r} must also be included in columns")

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        columns: Sequence[FieldRef],
        filters: Sequence[DatasetDataFilter] = (),
        params: Sequence[DatasetDataParameter] = (),
        sort: Sequence[DatasetDataSort] = (),
        limit: int = 500,
        offset: int | None = None,
    ) -> Self:
        if isinstance(columns, str):
            raise DataLensValidationError("columns must be a sequence of field references, not a string")
        return cls(
            dataset_id=dataset_id,
            columns=tuple(columns),
            filters=tuple(filters),
            params=tuple(params),
            sort=tuple(sort),
            limit=limit,
            offset=offset,
        )

    def column_guids(self) -> tuple[str, ...]:
        return tuple(_field_guid(field, dataset_id=self.dataset_id) for field in self.columns)

    def filter_guids(self) -> tuple[str, ...]:
        return tuple(_field_guid(item.field, dataset_id=self.dataset_id) for item in self.filters)

    def parameter_guids(self) -> tuple[str, ...]:
        return tuple(_field_guid(item.field, dataset_id=self.dataset_id) for item in self.params)

    def sort_guids(self) -> tuple[str, ...]:
        return tuple(_field_guid(item.field, dataset_id=self.dataset_id) for item in self.sort)
