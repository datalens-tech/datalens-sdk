from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import difflib
from typing import overload

from datalens_sdk.errors import DataLensValidationError


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
    raw: Mapping[str, object] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        # ``field_from_mapping`` coerces ``default_value`` to a hashable shape
        # before constructing DatasetField. Direct callers of the dataclass
        # constructor bypass that step. Apply the same coercion here so that
        # ``DatasetField(default_value=[1, 2, 3])`` stays hashable (E4-HASH).
        if self.default_value is not None and not isinstance(self.default_value, (str, int, float, bool, tuple)):
            object.__setattr__(self, "default_value", _coerce_to_hashable(self.default_value))


FieldLike = DatasetField
FieldRef = FieldLike | str


def field_from_mapping(value: Mapping[str, object], *, dataset_id: str | None = None) -> DatasetField:
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
    title = _str_value(value.get("title"))
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


class FieldsProxy(Sequence[FieldLike]):
    def __init__(
        self,
        fields: Sequence[Mapping[str, object] | FieldLike],
        *,
        dataset_id: str | None = None,
    ) -> None:
        self._fields = tuple(
            field if isinstance(field, DatasetField) else field_from_mapping(field, dataset_id=dataset_id)
            for field in fields
        )

    def by_name(self, name: str) -> FieldLike:
        for item in self._fields:
            if item.title == name or item.name == name:
                return item
        hints = ", ".join(difflib.get_close_matches(name, [f.title for f in self._fields if f.title], n=3))
        suffix = f" Did you mean: {hints}?" if hints else ""
        raise DataLensValidationError(f"Field {name!r} not found.{suffix}")

    def by_guid(self, guid: str) -> FieldLike:
        for item in self._fields:
            if item.guid == guid:
                return item
        raise DataLensValidationError(f"Field with guid {guid!r} not found.")

    def __iter__(self) -> Iterator[FieldLike]:
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    @overload
    def __getitem__(self, index: int) -> FieldLike: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[FieldLike]: ...

    def __getitem__(self, index: int | slice) -> FieldLike | Sequence[FieldLike]:
        return self._fields[index]
