from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args

from typing_extensions import Self

from datalens_sdk._runtime.viz_specs import get_ql_viz_spec
from datalens_sdk.domain.chart import Chart
from datalens_sdk.domain.chart_types import ChartCategory, QLCast, QLParamType
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.fields import FieldsProxy
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.connection import Connection

_QL_CAST_VALUES = frozenset(get_args(QLCast))

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


_QL_PARAM_TYPES = frozenset(get_args(QLParamType))


@dataclass(frozen=True, slots=True)
class QLColumn:
    name: str
    cast: QLCast = "string"

    def __post_init__(self) -> None:
        if self.cast not in _QL_CAST_VALUES:
            raise DataLensValidationError(f"QLColumn cast must be one of {sorted(_QL_CAST_VALUES)}, got {self.cast!r}")


@dataclass(frozen=True, slots=True)
class QLParam:
    """A typed QL-chart parameter (``data.params`` item).

    Mirrors ``QLColumn``: a frozen, validated value object.  Three parameter
    types are supported — ``number``, ``string`` and ``date-interval`` — matching
    the QL reference fixtures.  Prefer the classmethod constructors
    (:meth:`number`, :meth:`string`, :meth:`date_interval`) for clarity.
    """

    name: str
    type: QLParamType
    default_value: str | Mapping[str, object]

    def __post_init__(self) -> None:
        if self.type not in _QL_PARAM_TYPES:
            raise DataLensValidationError(f"QLParam type must be one of {sorted(_QL_PARAM_TYPES)}, got {self.type!r}")
        if self.type == "date-interval" and not isinstance(self.default_value, Mapping):
            raise DataLensValidationError("QLParam(type='date-interval') requires default_value to be a Mapping")

    @classmethod
    def number(cls, name: str, *, default: str) -> Self:
        return cls(name=name, type="number", default_value=default)

    @classmethod
    def string(cls, name: str, *, default: str) -> Self:
        return cls(name=name, type="string", default_value=default)

    @classmethod
    def date_interval(cls, name: str, *, default: Mapping[str, object]) -> Self:
        return cls(name=name, type="date-interval", default_value=dict(default))

    def to_mapping(self) -> Mapping[str, object]:
        value: object = dict(self.default_value) if isinstance(self.default_value, Mapping) else self.default_value
        return {"type": self.type, "name": self.name, "defaultValue": value}


def _string_keyed_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if isinstance(key, str)}
    return {}


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return _string_keyed_mapping(value)
    return None


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[Mapping[str, object]] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(_string_keyed_mapping(item))
    return result


class QLChartUpdate:
    """Fluent update builder for a QL chart.

    A QL chart stores its configuration as a single structured ``data`` object.
    Updates merge targeted edits onto the chart's current ``data``. Placeholder
    and decoration methods accept the same typed QL columns as create builders;
    the converter applies those edits without rebuilding the visualization.
    """

    def __init__(self, *, chart: QLChart, operations: ChartOperations | None) -> None:
        self._chart = chart
        self._operations = operations
        self._mode: EntryUpdateMode = "save"
        self._query: str | None = None
        self._connection_obj: Connection | None = None
        self._params_objs: tuple[QLParam, ...] | None = None
        self._description: str | None = None
        self._placeholder_edits: dict[str, tuple[QLColumn, ...]] = {}
        self._data_section_edits: dict[str, tuple[QLColumn, ...]] = {}
        self._data_merge: dict[str, object] = {}
        self._has_data_merge = False

    @property
    def chart(self) -> QLChart:
        return self._chart

    @property
    def mode_value(self) -> EntryUpdateMode:
        return self._mode

    @property
    def query_value(self) -> str | None:
        return self._query

    @property
    def connection_obj(self) -> Connection | None:
        return self._connection_obj

    @property
    def params_objs(self) -> tuple[QLParam, ...] | None:
        return self._params_objs

    @property
    def description_value(self) -> str | None:
        return self._description

    @property
    def placeholder_edits(self) -> Mapping[str, tuple[QLColumn, ...]]:
        return self._placeholder_edits

    @property
    def data_section_edits(self) -> Mapping[str, tuple[QLColumn, ...]]:
        return self._data_section_edits

    @property
    def data_merge(self) -> Mapping[str, object]:
        return self._data_merge

    @property
    def has_data_merge(self) -> bool:
        return self._has_data_merge

    def mode(self, value: EntryUpdateMode) -> Self:
        if value not in get_args(EntryUpdateMode):
            raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
        self._mode = value
        return self

    def query(self, sql: str) -> Self:
        """Replace the chart's SQL query (``data.queryValue``)."""
        self._query = sql
        return self

    def connection(self, connection: Connection) -> Self:
        if not connection.id:
            raise DataLensValidationError("QL chart connection requires a Connection with an id")
        self._connection_obj = connection
        return self

    def params(self, params: Sequence[QLParam]) -> Self:
        """Replace the chart's parameters (``data.params``)."""
        self._params_objs = tuple(params)
        return self

    def description(self, text: str) -> Self:
        self._description = text
        return self

    def _active_viz_spec(self) -> tuple[str, Mapping[str, object]]:
        viz_id = self._chart.visualization_id
        if viz_id is None:
            raise DataLensConfigurationError("QL chart has no active visualization")
        spec = get_ql_viz_spec(viz_id)
        if not spec:
            raise DataLensConfigurationError(f"Unsupported active QL visualization {viz_id!r}")
        return viz_id, spec

    def _resolve_placeholder_id(self, placeholder_id: str) -> str:
        viz_id, spec = self._active_viz_spec()
        spec_placeholders = spec.get("placeholders")
        if not isinstance(spec_placeholders, Sequence):
            raise DataLensConfigurationError(f"QL visualization {viz_id!r} has no supported placeholders")

        canonical_id: str | None = None
        allowed: list[str] = []
        for placeholder in spec_placeholders:
            if not isinstance(placeholder, Mapping):
                continue
            value = placeholder.get("id")
            if not isinstance(value, str):
                continue
            allowed.append(value)
            if value == placeholder_id or value.replace("-", "_") == placeholder_id:
                canonical_id = value
        if canonical_id is None:
            raise DataLensConfigurationError(
                f"Placeholder {placeholder_id!r} is not applicable to QL visualization {viz_id!r}. "
                f"Allowed placeholders: {allowed}"
            )

        visualization = self._chart.data.get("visualization")
        placeholders = visualization.get("placeholders") if isinstance(visualization, Mapping) else None
        active_ids = (
            {
                value
                for placeholder in placeholders
                if isinstance(placeholder, Mapping) and isinstance((value := placeholder.get("id")), str)
            }
            if isinstance(placeholders, Sequence)
            else set()
        )
        if canonical_id not in active_ids:
            raise DataLensConfigurationError(
                f"Active QL visualization {viz_id!r} does not contain placeholder {canonical_id!r}"
            )
        return canonical_id

    @staticmethod
    def _columns(columns: Sequence[QLColumn | str]) -> tuple[QLColumn, ...]:
        return tuple(column if isinstance(column, QLColumn) else QLColumn(name=column) for column in columns)

    def _set_placeholder(self, placeholder_id: str, columns: Sequence[QLColumn | str]) -> Self:
        resolved = self._resolve_placeholder_id(placeholder_id)
        self._placeholder_edits[resolved] = self._columns(columns)
        return self

    def _set_data_section(self, section: str, columns: Sequence[QLColumn | str]) -> Self:
        viz_id, spec = self._active_viz_spec()
        if section == "colors" and viz_id in {"pie", "donut", "metric"}:
            return self._set_placeholder("colors", columns)

        viz = spec.get("viz")
        capability = {
            "colors": "allowColors",
            "labels": "allowLabels",
            "shapes": "allowShapes",
        }.get(section)
        if capability is not None and (not isinstance(viz, Mapping) or viz.get(capability) is not True):
            raise DataLensConfigurationError(f"Decoration {section!r} is not applicable to QL visualization {viz_id!r}")
        self._data_section_edits[section] = self._columns(columns)
        return self

    def x(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("x", columns)

    def y(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("y", columns)

    def y2(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("y2", columns)

    def dimensions(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("dimensions", columns)

    def measures(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("measures", columns)

    def points(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("points", columns)

    def size(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("size", columns)

    def flat_table_columns(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_placeholder("flat_table_columns", columns)

    def colors(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_data_section("colors", columns)

    def labels(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_data_section("labels", columns)

    def shapes(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_data_section("shapes", columns)

    def tooltips(self, columns: Sequence[QLColumn | str]) -> Self:
        return self._set_data_section("tooltips", columns)

    def data(self, blob: Mapping[str, object]) -> Self:
        """Opaque-merge additional fields into the chart ``data``.

        This is the escape hatch for any ``data`` keys without a dedicated
        accessor. Keys are merged shallowly at the top level of ``data``.
        """
        self._data_merge.update({key: value for key, value in blob.items() if isinstance(key, str)})
        self._has_data_merge = True
        return self

    def execute(self) -> QLChart:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_ql_chart(self)


@dataclass(slots=True)
class QLChart(Chart):
    @property
    def category(self) -> ChartCategory:
        return "ql"

    @property
    def query_value(self) -> str | None:
        """The chart's SQL query (``data.queryValue``)."""
        value = self.data.get("queryValue")
        return value if isinstance(value, str) else None

    @property
    def connection(self) -> Mapping[str, object] | None:
        """The chart's connection (``data.connection``)."""
        return _mapping_or_none(self.data.get("connection"))

    @property
    def params(self) -> list[Mapping[str, object]]:
        """The chart's parameters (``data.params``)."""
        return _mapping_list(self.data.get("params"))

    @property
    def visualization_id(self) -> str | None:
        """The chart's visualization id (``data.visualization.id``)."""
        visualization = self.data.get("visualization")
        if not isinstance(visualization, Mapping):
            return None
        value = visualization.get("id")
        return value if isinstance(value, str) else None

    @property
    def fields(self) -> FieldsProxy:
        """Field items placed across the chart's visualization placeholders.

        Mirrors ``WizardChart.fields``: reads ``data.visualization.placeholders``
        and flattens the ``items`` of each placeholder. For QL charts the items
        carry a synthetic ``datasetId="ql-mocked-dataset"`` because QL sources
        data from a SQL query rather than a dataset.
        """
        items: list[Mapping[str, object]] = []
        visualization = self.data.get("visualization")
        if isinstance(visualization, Mapping):
            placeholders = visualization.get("placeholders")
            if isinstance(placeholders, list):
                for placeholder in placeholders:
                    if not isinstance(placeholder, Mapping):
                        continue
                    placeholder_items = placeholder.get("items")
                    if isinstance(placeholder_items, list):
                        items.extend(item for item in placeholder_items if isinstance(item, Mapping))
        return FieldsProxy(items)

    @property
    def update(self) -> QLChartUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a QL chart without an id")
        return QLChartUpdate(chart=self, operations=self._operations)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a QL chart without an id")
        self._operations.delete_ql_chart(self.id)
