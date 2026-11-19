"""Dashboard state JSON <-> :class:`DashboardStateData` through the DTOs generated from the ``DashboardState`` schema.

Parameter values use the DataLens UI wire forms: ``__<op>_<value>`` for an explicit operation (lower-case op),
``__interval_<start>_<end>`` for date ranges and ``__relative_<offset>[_<cast><unit>]`` for relative dates.
Decoding follows ``resolveOperation`` in datalens-ui, encoding follows ``addOperationForValue``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import datetime
import json
import re
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk._runtime.chart_wire import build_date_interval
from datalens_sdk.domain.dashboard_state import (
    _PARAM_OPERATIONS,
    DashboardStateData,
    ParamOperation,
    StateOperand,
    StateParamValue,
    StateQueueItem,
    StateValue,
    StateWidget,
    StateWidgetState,
    _thaw,
)
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDate, RelativeDateInterval
from datalens_sdk.errors import DataLensValidationError

MAX_STATE_DATA_SYMBOLS = 50_000

_META_KEY = "__meta__"
_STATE_VERSION: Literal[2] = 2
_VALUELESS_OPERATIONS = frozenset({"ISNULL", "ISNOTNULL"})
_INTERVAL_MARKER = "__interval"
_RELATIVE_PREFIX = "__relative_"
_OPERATION_RE = re.compile(r"^__([^_]+)_([\s\S]+)?$")
_RELATIVE_DATE_RE = re.compile(r"^__relative_([+-]\d+(?:ms|[yQMwdhms]))(?:_([se])([yQMwdhms]))?$")
_INTERVAL_EDGE = r"(__relative_[+-]\d+(?:ms|[yQMwdhms])(?:_[se][yQMwdhms])?|[^_]+)"
_INTERVAL_RE = re.compile(rf"^__interval_{_INTERVAL_EDGE}_{_INTERVAL_EDGE}$")


class _PayloadDTOProtocol(Protocol):
    model_extra: dict[str, object] | None

    def to_payload(self) -> dict[str, object]: ...


class _QueueItemDTOProtocol(Protocol):
    id: str
    group_item_id: str | None
    tab_id: str | None
    model_extra: dict[str, object] | None


class _MetaDTOProtocol(_PayloadDTOProtocol, Protocol):
    queue: Sequence[_QueueItemDTOProtocol]


class _WidgetStateDTOProtocol(Protocol):
    tab_id: str | None
    model_extra: dict[str, object] | None


class _WidgetDTOProtocol(_PayloadDTOProtocol, Protocol):
    params: Mapping[str, object] | None
    state: _WidgetStateDTOProtocol | None


class _FieldInfo(Protocol):
    alias: str | None


class _DTOClass(Protocol):
    model_fields: Mapping[str, _FieldInfo]


class _MetaDTOClass(_DTOClass, Protocol):
    def model_validate(self, obj: object) -> _MetaDTOProtocol: ...


class _WidgetDTOClass(_DTOClass, Protocol):
    def model_validate(self, obj: object) -> _WidgetDTOProtocol: ...


class _WidgetStateDTOClass(_DTOClass, Protocol):
    def model_validate(self, obj: object) -> _WidgetStateDTOProtocol: ...


class DashboardStateDtoModule(Protocol):
    DashboardStateMetaDTO: _MetaDTOClass
    DashboardStateMetaQueueItemDTO: _DTOClass
    DashboardStateWidgetDTO: _WidgetDTOClass
    DashboardStateWidgetStateDTO: _WidgetStateDTOClass


def _split(dto_class: _DTOClass, value: object) -> tuple[object, dict[str, object]]:
    """Separate the schema fields (by wire name) from extension fields, which are kept verbatim.

    Only wire names reach the DTO, so an extension key that equals a Python field name (``tab_id``) stays an
    extension instead of populating the field.
    """
    if not isinstance(value, Mapping):
        return value, {}
    names = {field.alias or name for name, field in dto_class.model_fields.items()}
    known = {key: item for key, item in value.items() if key in names}
    return known, {key: item for key, item in value.items() if key not in names}


def _dto_module(dto_module: DashboardStateDtoModule | None) -> DashboardStateDtoModule:
    return cast(DashboardStateDtoModule, generated_dto if dto_module is None else dto_module)


def _relative_date_wire(value: RelativeDate) -> str:
    suffix = "" if value.cast is None else f"_{value.cast}{value.unit}"
    return f"{_RELATIVE_PREFIX}{value.offset}{suffix}"


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


def _decode_item(raw: str) -> StateParamValue:
    if raw.startswith(f"{_INTERVAL_MARKER}_"):
        return _parse_date_interval(raw) or raw
    if raw.startswith(_RELATIVE_PREFIX):
        return _parse_relative_date(raw) or raw
    return raw


def _decode_operand(raw: str) -> StateOperand:
    """``resolveOperation``: a known ``__<op>_`` prefix is kept, anything else is an unprefixed value."""
    match = _OPERATION_RE.fullmatch(raw)
    if match is not None:
        operation, value = match.group(1).upper(), match.group(2)
        if operation in _PARAM_OPERATIONS and (value is not None or operation in _VALUELESS_OPERATIONS):
            return StateOperand(cast(ParamOperation, operation), None if value is None else _decode_item(value))
    return StateOperand(None, _decode_item(raw))


def _decode_value(param: str, wire: object) -> StateValue:
    raw: str | tuple[str, ...] = wire if isinstance(wire, str) else tuple(cast("Sequence[str]", wire))
    items = (raw,) if isinstance(raw, str) else raw
    return StateValue(
        param=param,
        operands=tuple(_decode_operand(item) for item in items),
        multiple=not isinstance(raw, str),
        raw=raw,
    )


def _encode_interval_edge(edge: str | datetime.date | RelativeDate) -> str:
    if isinstance(edge, RelativeDate):
        return _relative_date_wire(edge)
    if isinstance(edge, datetime.date):
        return edge.isoformat()
    return _relative_date_wire(RelativeDate(edge)) if edge.startswith(("+", "-")) else edge


def _encode_item(value: StateParamValue | RelativeDateInterval) -> str:
    if isinstance(value, (DateInterval, RelativeDateInterval)):
        inclusive_end = value.inclusive_end if isinstance(value, DateInterval) else True
        start = _encode_interval_edge(value.start)
        end = _encode_interval_edge(value.end)
        return build_date_interval(start, end, inclusive_end=inclusive_end)
    if isinstance(value, RelativeDate):
        return _relative_date_wire(value)
    return value


def _encode_operand(operand: StateOperand) -> str:
    if operand.value is None:
        return f"__{(operand.operation or 'ISNULL').lower()}_"
    wire = _encode_item(operand.value)
    return f"__{operand.operation.lower()}_{wire}" if operand.operation is not None and wire else wire


def _encode_value(value: StateValue) -> str | list[str]:
    if value.raw is not None:
        return value.raw if isinstance(value.raw, str) else list(value.raw)
    encoded = [_encode_operand(operand) for operand in value.operands]
    return encoded if value.multiple else encoded[0]


def _decode_params(params: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: {name: _decode_value(name, item) for name, item in value.items()}
        if isinstance(value, Mapping)
        else _decode_value(key, value)
        for key, value in params.items()
    }


def _encode_params(params: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _encode_params(value) if isinstance(value, Mapping) else _encode_value(cast(StateValue, value))
        for key, value in params.items()
    }


def _widget(generated: DashboardStateDtoModule, value: object) -> StateWidget:
    known, extra = _split(generated.DashboardStateWidgetDTO, value)
    state_value = known.pop("state", None) if isinstance(known, dict) else None
    dto = generated.DashboardStateWidgetDTO.model_validate(known)
    state = None
    if state_value is not None:
        state_known, state_extra = _split(generated.DashboardStateWidgetStateDTO, state_value)
        state_dto = generated.DashboardStateWidgetStateDTO.model_validate(state_known)
        state = StateWidgetState(tab_id=state_dto.tab_id, extra=state_extra)
    return StateWidget(
        params=None if dto.params is None else cast("Mapping[str, StateValue]", _decode_params(dto.params)),
        state=state,
        extra=extra,
    )


def _queue(generated: DashboardStateDtoModule, meta: object) -> tuple[tuple[StateQueueItem, ...], dict[str, object]]:
    known, extra = _split(generated.DashboardStateMetaDTO, meta)
    queue_value = known.get("queue") if isinstance(known, dict) else None
    items = (
        [_split(generated.DashboardStateMetaQueueItemDTO, item) for item in queue_value]
        if isinstance(queue_value, list)
        else []
    )
    if isinstance(known, dict) and isinstance(queue_value, list):
        known = {**known, "queue": [item for item, _ in items]}
    meta_dto = generated.DashboardStateMetaDTO.model_validate(known)
    queue = tuple(
        StateQueueItem(item.id, item.group_item_id, item.tab_id, item_extra)
        for item, (_, item_extra) in zip(meta_dto.queue, items, strict=True)
    )
    return queue, extra


class DashboardStateConverter:
    """Map dashboard state JSON to :class:`DashboardStateData` and back through the generated DTOs."""

    @staticmethod
    def symbols(payload: Mapping[str, object]) -> int:
        """Length of the state JSON in UTF-16 code units, as ``JSON.stringify(data).length`` counts it in US."""
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return len(text.encode("utf-16-le")) // 2

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | None,
        *,
        dto_module: DashboardStateDtoModule | None = None,
    ) -> DashboardStateData:
        generated = _dto_module(dto_module)
        if not raw:
            return DashboardStateData(version=_STATE_VERSION, queue=(), widgets={})
        if "" in raw:
            raise DataLensValidationError("Dashboard state widget ids must be non-empty")
        widgets = {widget_id: _widget(generated, value) for widget_id, value in raw.items() if widget_id != _META_KEY}
        meta = raw.get(_META_KEY)
        if meta is None:
            # DashKit getCurrentVersion: any stored params map, even an empty one, marks version 1.
            has_params = any(widget.params is not None for widget in widgets.values())
            version: Literal[1, 2] = 1 if has_params else _STATE_VERSION
            return DashboardStateData(version=version, queue=(), widgets=widgets)
        queue, meta_extra = _queue(generated, meta)
        return DashboardStateData(_STATE_VERSION, queue, widgets, meta_extra)

    @staticmethod
    def to_payload(
        data: DashboardStateData,
        *,
        dto_module: DashboardStateDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        payload: dict[str, object] = {}
        for widget_id, widget in data.widgets.items():
            body: dict[str, object] = {}
            if widget.params is not None:
                body["params"] = _encode_params(widget.params)
            if widget.state is not None:
                body["state"] = {} if widget.state.tab_id is None else {"tabId": widget.state.tab_id}
            dumped = generated.DashboardStateWidgetDTO.model_validate(body).to_payload()
            if widget.state is not None:
                dumped["state"] = cast("dict[str, object]", _thaw(widget.state.extra)) | cast(
                    "dict[str, object]", dumped["state"]
                )
            payload[widget_id] = cast("dict[str, object]", _thaw(widget.extra)) | dumped
        if data.version == _STATE_VERSION:
            queue: list[dict[str, object]] = []
            for item in data.queue:
                record: dict[str, object] = {"id": item.id}
                if item.group_item_id is not None:
                    record["groupItemId"] = item.group_item_id
                if item.tab_id is not None:
                    record["tabId"] = item.tab_id
                queue.append(record)
            meta = generated.DashboardStateMetaDTO.model_validate({"queue": queue, "version": _STATE_VERSION})
            dumped_meta = meta.to_payload()
            dumped_meta["queue"] = [
                cast("dict[str, object]", _thaw(item.extra)) | record
                for item, record in zip(data.queue, cast("list[dict[str, object]]", dumped_meta["queue"]), strict=True)
            ]
            payload[_META_KEY] = cast("dict[str, object]", _thaw(data.meta_extra)) | dumped_meta
        return payload
