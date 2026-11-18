"""Codec for dashboard parameter values as the DataLens UI stores them in states.

Wire forms: ``__<op>_<value>`` for an explicit operation (lower-case op), ``__interval_<start>_<end>`` for date
ranges and ``__relative_<offset>[_<cast><unit>]`` for relative dates. Decoding follows ``resolveOperation`` in
datalens-ui; encoding follows ``addOperationForValue``: a selector with an operation prefixes every value with it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import datetime
import re
from typing import Literal, TypeAlias, cast, get_args

from datalens_sdk._runtime.chart_wire import build_date_interval
from datalens_sdk.domain.chart_types import FilterOperation
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDate, RelativeDateInterval
from datalens_sdk.errors import DataLensValidationError

ParamOperation: TypeAlias = Literal[
    FilterOperation,
    "NIN",
    "ICONTAINS",
    "NOTCONTAINS",
    "NOTICONTAINS",
    "ISTARTSWITH",
    "ENDSWITH",
    "IENDSWITH",
    "LENEQ",
    "LENGT",
    "LENGTE",
    "LENLT",
    "LENLTE",
]
StateParamValue: TypeAlias = "str | DateInterval | RelativeDate"

_PARAM_OPERATIONS: frozenset[str] = frozenset(get_args(ParamOperation))
_VALUELESS_OPERATIONS: frozenset[str] = frozenset({"ISNULL", "ISNOTNULL"})
_ACTION_PARAM_PREFIX = "_ap_"
_INTERVAL_MARKER = "__interval"
_RELATIVE_PREFIX = "__relative_"
_OPERATION_RE = re.compile(r"^__([^_]+)_([\s\S]+)?$")
_RELATIVE_DATE_RE = re.compile(r"^__relative_([+-]\d+(?:ms|[yQMwdhms]))(?:_([se])([yQMwdhms]))?$")
_INTERVAL_EDGE = r"(__relative_[+-]\d+(?:ms|[yQMwdhms])(?:_[se][yQMwdhms])?|[^_]+)"
_INTERVAL_RE = re.compile(rf"^__interval_{_INTERVAL_EDGE}_{_INTERVAL_EDGE}$")


@dataclass(frozen=True, slots=True)
class StateValue:
    """One decoded parameter of a state source.

    ``values`` holds plain strings, :class:`DateInterval` ranges and :class:`RelativeDate` values; ``raw`` keeps the
    exact wire value. ``dataset_field`` marks keys that are dataset field guids (dataset selectors).
    """

    param: str
    operation: ParamOperation
    values: tuple[StateParamValue, ...]
    raw: str | tuple[str, ...]
    dataset_field: bool = False

    @property
    def is_action_param(self) -> bool:
        return self.param.startswith(_ACTION_PARAM_PREFIX)

    @property
    def field_guid(self) -> str | None:
        if self.is_action_param:
            return self.param[len(_ACTION_PARAM_PREFIX) :]
        return self.param if self.dataset_field else None


def decode_param_value(
    param: str,
    raw: str | Sequence[str],
    default_operation: ParamOperation | None = None,
    *,
    dataset_field: bool = False,
) -> StateValue:
    """Decode a stored parameter value as the DataLens UI resolves it.

    The first value's ``__<op>_`` prefix wins; without one, an interval is BETWEEN and anything else takes the
    selector's ``default_operation``, else IN. An unknown prefix is a plain IN value.
    """
    items = (raw,) if isinstance(raw, str) else tuple(raw)
    operation: ParamOperation | None = None
    values: list[StateParamValue] = []
    for item in items:
        item_operation, value = _resolve_operation(item, default_operation)
        if operation is None:
            operation = item_operation
        if value is not None:
            values.append(_decode_value(value))
    return StateValue(
        param=param,
        operation=operation or default_operation or "IN",
        values=tuple(values),
        raw=raw if isinstance(raw, str) else items,
        dataset_field=dataset_field,
    )


def encode_param_value(
    values: object,
    operation: ParamOperation | None = None,
    *,
    multiselect: bool,
    is_range: bool,
    default_operation: ParamOperation | None = None,
) -> str | list[str]:
    """Encode values for a state: a list for multiselect sources, one interval for range sources.

    ``default_operation`` is the selector's own operation: like the UI, every non-empty value is then prefixed
    with ``__<op>_``. Without it, the prefix is written only for an operation other than IN (BETWEEN for ranges).
    """
    for candidate in (operation, default_operation):
        if candidate is not None:
            _as_operation(candidate)
    items = _value_items(values)
    if is_range and (len(items) != 1 or not isinstance(items[0], (DateInterval, RelativeDateInterval))):
        raise DataLensValidationError("A range selector takes exactly one DateInterval or RelativeDateInterval")
    effective = operation or default_operation
    implicit = "BETWEEN" if is_range else "IN"
    prefixed = effective is not None and (default_operation is not None or effective != implicit)
    prefix = f"__{cast(str, effective).lower()}_" if prefixed else ""
    if effective in _VALUELESS_OPERATIONS:
        if items:
            raise DataLensValidationError(f"{effective} takes no values")
        encoded = [f"__{cast(str, effective).lower()}_"]
    else:
        if not multiselect and len(items) != 1:
            raise DataLensValidationError(f"A single-value source takes exactly one value, got {len(items)}")
        encoded = [f"{prefix}{wire}" if wire else wire for wire in (_encode_item(_) for _ in items)]
    return encoded if multiselect else encoded[0]


def _as_operation(value: str) -> ParamOperation:
    if value not in _PARAM_OPERATIONS:
        raise DataLensValidationError(
            f"Unknown parameter operation {value!r}; expected one of {sorted(_PARAM_OPERATIONS)}"
        )
    return cast(ParamOperation, value)


def _resolve_operation(
    raw: str,
    default_operation: ParamOperation | None,
) -> tuple[ParamOperation | None, str | None]:
    match = _OPERATION_RE.fullmatch(raw)
    if match is not None:
        operation, value = match.group(1).upper(), match.group(2)
        if operation in _PARAM_OPERATIONS and (value is not None or operation in _VALUELESS_OPERATIONS):
            return cast(ParamOperation, operation), value
        # An unknown prefix falls back without the selector's operation, as in the UI.
        default_operation = None
    if _INTERVAL_MARKER in raw:
        return "BETWEEN", raw
    return default_operation or "IN", raw


def _parse_relative_date(raw: str) -> RelativeDate | None:
    match = _RELATIVE_DATE_RE.fullmatch(raw)
    if match is None:
        return None
    offset, rounding, unit = match.groups()
    return RelativeDate(offset, cast=cast("Literal['s', 'e'] | None", rounding), unit=unit)


def _parse_date_interval(raw: str) -> DateInterval | None:
    match = _INTERVAL_RE.fullmatch(raw)
    if match is None:
        return None
    start, end = (_parse_relative_date(edge) or edge for edge in match.groups())
    try:
        return DateInterval(start, end)
    except DataLensValidationError:
        return None


def _decode_value(raw: str) -> StateParamValue:
    if raw.startswith(f"{_INTERVAL_MARKER}_"):
        return _parse_date_interval(raw) or raw
    if raw.startswith(_RELATIVE_PREFIX):
        return _parse_relative_date(raw) or raw
    return raw


def _value_items(values: object) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, DateInterval, RelativeDateInterval, RelativeDate)):
        return (values,)
    if isinstance(values, Sequence):
        return tuple(values)
    raise DataLensValidationError(f"State values must be a value or a sequence of values, got {values!r}")


def _encode_interval_edge(edge: str | datetime.date | RelativeDate) -> str:
    if isinstance(edge, RelativeDate):
        return edge.to_wire()
    if isinstance(edge, datetime.date):
        return edge.isoformat()
    if edge.startswith(("+", "-")):
        return RelativeDate(edge).to_wire()
    return edge


def _encode_item(value: object) -> str:
    if isinstance(value, (DateInterval, RelativeDateInterval)):
        inclusive_end = value.inclusive_end if isinstance(value, DateInterval) else True
        return build_date_interval(
            _encode_interval_edge(value.start),
            _encode_interval_edge(value.end),
            inclusive_end=inclusive_end,
        )
    if isinstance(value, RelativeDate):
        return value.to_wire()
    if isinstance(value, str):
        return value
    raise DataLensValidationError(
        f"State values must be strings, DateInterval, RelativeDateInterval or RelativeDate, got {value!r}"
    )
