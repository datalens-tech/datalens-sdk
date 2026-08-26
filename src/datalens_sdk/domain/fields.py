from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
import difflib
from types import MappingProxyType
from typing import Literal, TypeAlias, overload
import uuid

from datalens_sdk.domain.dataset_types import Aggregation, DataType
from datalens_sdk.domain.formatting import MeasureFormat
from datalens_sdk.errors import DataLensValidationError


def _empty_measure_format() -> MeasureFormat:
    return {}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _str_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _coerce_to_hashable(value: object) -> object:
    """Coerce container shapes the backend emits for ``default_value`` into
    hashable siblings so a ``DatasetField`` stays usable as a ``dict``/``set``
    member regardless of wire shape.

    - ``dict``/``Mapping`` → ``tuple`` of ``(key, coerc(value))`` pairs, sorted by
      key for deterministic ordering (so equal mappings hash equally).
    - ``list``/``tuple``/``set``/``frozenset`` → ``tuple`` of coerced items
      (iteration order preserved for sequences).

    Primitives pass through unchanged. The original raw shape remains available
    on ``DatasetField.raw['default_value']``.
    """
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _coerce_to_hashable(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_coerce_to_hashable(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DatasetField:
    guid: str
    title: str
    name: str
    calc_mode: str
    data_type: str | None = None
    type: str | None = None
    aggregation: str | None = None
    cast: str | None = None
    source: str | None = None
    avatar_id: str | None = None
    formula: str = ""
    description: str = ""
    hidden: bool = False
    default_value: object | None = None
    ui_settings: str | None = None
    initial_data_type: str | None = None
    dataset_id: str | None = None
    raw: Mapping[str, object] = dataclass_field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        # ``field_from_mapping`` coerces ``default_value`` to a hashable shape
        # before constructing DatasetField. Direct callers of the dataclass
        # constructor bypass that step. Apply the same coercion here so that
        # ``DatasetField(default_value=[1, 2, 3])`` stays hashable (E4-HASH).
        if self.default_value is not None and not isinstance(self.default_value, (str, int, float, bool, tuple)):
            object.__setattr__(self, "default_value", _coerce_to_hashable(self.default_value))


@dataclass(frozen=True, slots=True)
class WizardLocalField:
    """Stable identity handle for a formula field owned by one Wizard chart.

    Create a handle with :meth:`dimension` or :meth:`measure`, register it with
    ``add_local_field()``, and pass the same object anywhere a Wizard builder
    accepts a field reference.
    """

    guid: str
    title: str
    formula: str
    cast: DataType
    type: Literal["DIMENSION", "MEASURE"]
    aggregation: Aggregation
    autoaggregated: bool
    formatting: MeasureFormat = dataclass_field(
        default_factory=_empty_measure_format,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "formatting", MappingProxyType(dict(self.formatting)))

    @classmethod
    def dimension(
        cls,
        *,
        title: str,
        formula: str,
        guid: str | None = None,
        cast: DataType = "float",
        formatting: MeasureFormat | None = None,
    ) -> WizardLocalField:
        """Create a formula dimension handle with a stable GUID."""
        return cls(
            guid=guid if guid is not None else str(uuid.uuid4()),
            title=title,
            formula=formula,
            cast=cast,
            type="DIMENSION",
            aggregation="none",
            autoaggregated=False,
            formatting=formatting or {},
        )

    @classmethod
    def measure(
        cls,
        *,
        title: str,
        formula: str,
        guid: str | None = None,
        cast: DataType = "float",
        aggregation: Aggregation | None = None,
        formatting: MeasureFormat | None = None,
    ) -> WizardLocalField:
        """Create a formula measure handle with a stable GUID."""
        return cls(
            guid=guid if guid is not None else str(uuid.uuid4()),
            title=title,
            formula=formula,
            cast=cast,
            type="MEASURE",
            aggregation=aggregation or "none",
            autoaggregated=aggregation is None,
            formatting=formatting or {},
        )

    @property
    def name(self) -> str:
        return self.title

    @property
    def calc_mode(self) -> Literal["formula"]:
        return "formula"

    @property
    def data_type(self) -> DataType:
        return self.cast

    @property
    def dataset_id(self) -> None:
        return None

    def _to_field_definition(self) -> dict[str, object]:
        definition: dict[str, object] = {
            "guid": self.guid,
            "title": self.title,
            "calc_mode": self.calc_mode,
            "formula": self.formula,
            "cast": self.cast,
            "data_type": self.data_type,
            "type": self.type,
            "aggregation": self.aggregation,
            "autoaggregated": self.autoaggregated,
            "has_auto_aggregation": self.autoaggregated,
            "aggregation_locked": True,
            "local": True,
        }
        if self.formatting:
            definition["formatting"] = dict(self.formatting)
        return definition


_ExplicitAggregation: TypeAlias = Literal["sum", "avg", "min", "max", "count", "countunique"]


@dataclass(frozen=True, slots=True, kw_only=True)
class WizardAggregatedMeasure:
    """Stable handle for a chart-local aggregation of a Dataset field."""

    field: DatasetField
    aggregation: _ExplicitAggregation
    title: str
    guid: str = dataclass_field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def name(self) -> str:
        return self.title

    @property
    def type(self) -> Literal["MEASURE"]:
        return "MEASURE"

    @property
    def data_type(self) -> str:
        if self.aggregation in {"count", "countunique"}:
            return "integer"
        return self.field.data_type or "float"

    @property
    def dataset_id(self) -> str | None:
        return self.field.dataset_id


WizardHierarchyMember: TypeAlias = DatasetField | WizardLocalField | WizardAggregatedMeasure | str


@dataclass(frozen=True, slots=True, kw_only=True)
class WizardHierarchy:
    """Stable handle for a chart-local hierarchy and its ordered members."""

    title: str
    fields: Sequence[WizardHierarchyMember]
    guid: str = dataclass_field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))

    @property
    def name(self) -> str:
        return self.title

    @property
    def type(self) -> Literal["PSEUDO"]:
        return "PSEUDO"

    @property
    def data_type(self) -> Literal["hierarchy"]:
        return "hierarchy"

    @property
    def dataset_id(self) -> None:
        return None

    def _to_hierarchy_definition(self) -> dict[str, object]:
        return {"guid": self.guid, "title": self.title, "type": "PSEUDO", "fields": list(self.fields)}


WizardFieldHandle: TypeAlias = WizardLocalField | WizardAggregatedMeasure | WizardHierarchy
FieldLike: TypeAlias = DatasetField
WizardFieldLike: TypeAlias = DatasetField | WizardFieldHandle
WizardFieldRef: TypeAlias = WizardFieldLike | str


def field_from_mapping(value: Mapping[str, object], *, dataset_id: str | None = None) -> DatasetField:
    if dataset_id is None:
        dataset_id = _str_or_none(value.get("datasetId")) or _str_or_none(value.get("dataset_id"))
    default_value = value.get("default_value")
    if default_value is None:
        default_value = value.get("defaultValue")
    # ``DatasetField`` is frozen with an auto-``__hash__`` that includes
    # ``default_value``. Backend parameter payloads may carry a ``list`` or
    # ``dict`` here (e.g. date-interval ``{"from": ..., "to": ...}``), which
    # would make the field unhashable and break ``color_by_measure_name(colors_map=
    # {field: ...})``. Coerce to a hashable sibling; the raw shape stays
    # accessible via ``DatasetField.raw['default_value']``.
    coerced_default = _coerce_to_hashable(default_value) if default_value is not None else None
    raw_name = _str_value(value.get("name"))
    title = _str_value(value.get("title")) or _str_value(value.get("fakeTitle"))
    return DatasetField(
        guid=_str_value(value.get("guid")),
        title=title,
        name=raw_name or title,
        calc_mode=_str_value(value.get("calc_mode"), "direct"),
        data_type=_str_or_none(value.get("data_type")),
        type=_str_or_none(value.get("type")),
        aggregation=_str_or_none(value.get("aggregation")),
        cast=_str_or_none(value.get("cast")),
        source=_str_or_none(value.get("source")),
        avatar_id=_str_or_none(value.get("avatar_id")),
        formula=_str_value(value.get("formula")),
        description=_str_value(value.get("description")),
        hidden=bool(value.get("hidden", False)),
        default_value=coerced_default,
        ui_settings=_str_or_none(value.get("ui_settings")),
        initial_data_type=_str_or_none(value.get("initial_data_type")),
        dataset_id=dataset_id,
        raw=dict(value),
    )


class FieldsProxy(Sequence[DatasetField]):
    def __init__(
        self,
        fields: Sequence[Mapping[str, object] | DatasetField],
        *,
        dataset_id: str | None = None,
    ) -> None:
        self._fields = tuple(
            field if isinstance(field, DatasetField) else field_from_mapping(field, dataset_id=dataset_id)
            for field in fields
        )

    def by_name(self, name: str) -> DatasetField:
        for item in self._fields:
            if item.title == name or item.name == name:
                return item
        hints = ", ".join(difflib.get_close_matches(name, [f.title for f in self._fields if f.title], n=3))
        suffix = f" Did you mean: {hints}?" if hints else ""
        raise DataLensValidationError(f"Field {name!r} not found.{suffix}")

    def by_guid(self, guid: str) -> DatasetField:
        for item in self._fields:
            if item.guid == guid:
                return item
        raise DataLensValidationError(f"Field with guid {guid!r} not found.")

    def __iter__(self) -> Iterator[DatasetField]:
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    @overload
    def __getitem__(self, index: int) -> DatasetField: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[DatasetField]: ...

    def __getitem__(self, index: int | slice) -> DatasetField | Sequence[DatasetField]:
        return self._fields[index]
