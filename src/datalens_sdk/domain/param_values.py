"""Codec for dashboard parameter values as the DataLens UI stores them in states and selector defaults.

Wire forms: ``__<op>_<value>`` for an explicit operation (lower-case op), ``__interval_<start>_<end>`` for date
ranges and ``__relative_<offset>[_<cast>_<unit>]`` for relative dates. A value without a prefix uses the
operation of its selector, else IN (BETWEEN for intervals), mirroring ``resolveOperation`` in datalens-ui.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import datetime
import re
from typing import Literal, TypeAlias, cast, get_args

from datalens_sdk._runtime.chart_wire import build_date_interval
from datalens_sdk.domain.chart_types import FilterOperation
from datalens_sdk.domain.dashboard_types import (
    RELATIVE_DATE_PREFIX,
    DateInterval,
    RelativeDate,
    RelativeDateInterval,
)
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
PARAM_OPERATIONS: frozenset[str] = frozenset(get_args(ParamOperation))
VALUELESS_OPERATIONS: frozenset[str] = frozenset({"ISNULL", "ISNOTNULL"})
ACTION_PARAM_PREFIX = "_ap_"
INTERVAL_PREFIX = "__interval_"

StateParamValue: TypeAlias = "str | DateInterval | RelativeDate"

OPERATION_RE = re.compile(r"^__([A-Za-z]+)_(.*)$", re.DOTALL)
VALUELESS_RE = re.compile(r"^__(isnull|isnotnull)_?$", re.IGNORECASE)
RELATIVE_DATE_RE = re.compile(r"^__relative_([+-]?\d+(?:ms|[yQMwdhms]))(?:_([se])_([A-Za-z]+))?$")
INTERVAL_EDGE = r"(__relative_[+-]?\d+(?:ms|[yQMwdhms])(?:_[se]_[A-Za-z]+)?|[^_]+)"
INTERVAL_RE = re.compile(rf"^__interval_{INTERVAL_EDGE}_{INTERVAL_EDGE}$")


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
        return self.param.startswith(ACTION_PARAM_PREFIX)

    @property
    def field_guid(self) -> str | None:
        if self.is_action_param:
            return self.param[len(ACTION_PARAM_PREFIX) :]
        return self.param if self.dataset_field else None


def parse_relative_date(raw: str) -> RelativeDate | None:
    match = RELATIVE_DATE_RE.fullmatch(raw)
    if match is None:
        return None
    offset, rounding, unit = match.groups()
    return RelativeDate(offset, cast=cast("Literal['s', 'e'] | None", rounding), unit=unit)


def parse_interval_edge(raw: str) -> str | RelativeDate:
    return parse_relative_date(raw) or raw


def parse_date_interval(raw: str) -> DateInterval | None:
    match = INTERVAL_RE.fullmatch(raw)
    if match is None:
        return None
    start, end = match.groups()
    try:
        return DateInterval(parse_interval_edge(start), parse_interval_edge(end))
    except DataLensValidationError:
        return None


def decode_value(raw: str) -> StateParamValue:
    if raw.startswith(INTERVAL_PREFIX):
        return parse_date_interval(raw) or raw
    if raw.startswith(RELATIVE_DATE_PREFIX):
        return parse_relative_date(raw) or raw
    return raw


def decode_item(raw: str) -> tuple[ParamOperation | None, StateParamValue | None]:
    valueless = VALUELESS_RE.fullmatch(raw)
    if valueless is not None:
        return as_operation(valueless.group(1).upper()), None
    match = OPERATION_RE.fullmatch(raw)
    if match is not None and match.group(1).upper() in PARAM_OPERATIONS:
        return as_operation(match.group(1).upper()), decode_value(match.group(2))
    return None, decode_value(raw)


def as_operation(value: str) -> ParamOperation:
    if value not in PARAM_OPERATIONS:
        raise DataLensValidationError(
            f"Unknown parameter operation {value!r}; expected one of {sorted(PARAM_OPERATIONS)}"
        )
    return cast(ParamOperation, value)


def decode_param_value(
    param: str,
    raw: str | Sequence[str],
    default_operation: ParamOperation | None = None,
    *,
    dataset_field: bool = False,
) -> StateValue:
    """Decode a stored parameter value the way the DataLens UI resolves it.

    The first explicit ``__<op>_`` prefix wins; without one the selector's ``default_operation`` applies, else IN
    (BETWEEN when the value is a date interval).
    """
    items = (raw,) if isinstance(raw, str) else tuple(raw)
    operation: ParamOperation | None = None
    values: list[StateParamValue] = []
    for item in items:
        item_operation, value = decode_item(item)
        if operation is None and item_operation is not None:
            operation = item_operation
        if value is not None:
            values.append(value)
    if operation is None:
        operation = default_operation
    if operation is None:
        operation = "BETWEEN" if any(isinstance(value, DateInterval) for value in values) else "IN"
    return StateValue(
        param=param,
        operation=operation,
        values=tuple(values),
        raw=raw if isinstance(raw, str) else items,
        dataset_field=dataset_field,
    )


def encode_interval_edge(edge: str | datetime.date | RelativeDate) -> str:
    if isinstance(edge, RelativeDate):
        return edge.to_wire()
    if isinstance(edge, datetime.date):
        return edge.isoformat()
    if edge.startswith(("+", "-")):
        return f"{RELATIVE_DATE_PREFIX}{edge}"
    return edge


def encode_interval(value: DateInterval | RelativeDateInterval) -> str:
    inclusive_end = value.inclusive_end if isinstance(value, DateInterval) else True
    return build_date_interval(
        encode_interval_edge(value.start),
        encode_interval_edge(value.end),
        inclusive_end=inclusive_end,
    )


def encode_item(value: object) -> str:
    if isinstance(value, (DateInterval, RelativeDateInterval)):
        return encode_interval(value)
    if isinstance(value, RelativeDate):
        return value.to_wire()
    if isinstance(value, str):
        return value
    raise DataLensValidationError(
        f"State values must be strings, DateInterval, RelativeDateInterval or RelativeDate, got {value!r}"
    )


def encode_param_value(
    values: object,
    operation: ParamOperation | None = None,
    *,
    multiselect: bool,
    is_range: bool,
) -> str | list[str]:
    """Encode values for a state; multiselect sources always get a list, range sources require one interval.

    The ``__<op>_`` prefix is written only when ``operation`` differs from the implicit IN (BETWEEN for ranges).
    """
    if operation is not None:
        as_operation(operation)
    items: tuple[object, ...]
    if values is None:
        items = ()
    elif isinstance(values, (str, DateInterval, RelativeDateInterval, RelativeDate)):
        items = (values,)
    elif isinstance(values, Sequence):
        items = tuple(values)
    else:
        raise DataLensValidationError(f"State values must be a value or a sequence of values, got {values!r}")
    if is_range and (len(items) != 1 or not isinstance(items[0], (DateInterval, RelativeDateInterval))):
        raise DataLensValidationError("A range selector takes exactly one DateInterval or RelativeDateInterval")
    implicit = "BETWEEN" if is_range else "IN"
    prefix = "" if operation is None or operation == implicit else f"__{operation.lower()}_"
    if operation in VALUELESS_OPERATIONS:
        if items:
            raise DataLensValidationError(f"{operation} takes no values")
        encoded = [prefix]
    else:
        if not multiselect and len(items) != 1:
            raise DataLensValidationError(f"A single-value source takes exactly one value, got {len(items)}")
        encoded = [f"{prefix}{encode_item(item)}" for item in items]
    return encoded if multiselect else encoded[0]
