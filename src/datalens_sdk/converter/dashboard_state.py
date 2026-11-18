from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_state import (
    DashboardStateData,
    StateQueueItem,
    StateWidget,
    StateWidgetState,
    StateWireValue,
)
from datalens_sdk.errors import DataLensValidationError

_META_KEY = "__meta__"
_STATE_VERSION: Literal[2] = 2
MAX_STATE_DATA_SYMBOLS = 50_000


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


class _MetaDTOClass(Protocol):
    def model_validate(self, obj: object) -> _MetaDTOProtocol: ...


class _WidgetDTOClass(Protocol):
    def model_validate(self, obj: object) -> _WidgetDTOProtocol: ...


class DashboardStateDtoModule(Protocol):
    DashboardStateMetaDTO: _MetaDTOClass
    DashboardStateWidgetDTO: _WidgetDTOClass


def _dto_module(dto_module: DashboardStateDtoModule | None) -> DashboardStateDtoModule:
    return cast(DashboardStateDtoModule, generated_dto if dto_module is None else dto_module)


def _wire_value(value: object) -> StateWireValue:
    return value if isinstance(value, str) else tuple(cast("Sequence[str]", value))


def _domain_params(params: Mapping[str, object]) -> Mapping[str, object]:
    return {
        key: {name: _wire_value(item) for name, item in value.items()}
        if isinstance(value, Mapping)
        else _wire_value(value)
        for key, value in params.items()
    }


def _payload_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _payload_value(item) for key, item in value.items()}
    return value if isinstance(value, str) else list(cast("Sequence[str]", value))


def _payload_params(params: Mapping[str, object]) -> dict[str, object]:
    return {key: _payload_value(value) for key, value in params.items()}


def _widget(dto: _WidgetDTOProtocol) -> StateWidget:
    state = dto.state
    return StateWidget(
        params=None if dto.params is None else cast("Mapping[str, StateWireValue]", _domain_params(dto.params)),
        state=None if state is None else StateWidgetState(tab_id=state.tab_id, extra=dict(state.model_extra or {})),
        extra=dict(dto.model_extra or {}),
    )


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
        widgets = {
            widget_id: _widget(generated.DashboardStateWidgetDTO.model_validate(value))
            for widget_id, value in raw.items()
            if widget_id != _META_KEY
        }
        meta = raw.get(_META_KEY)
        if meta is None:
            version: Literal[1, 2] = 1 if any(widget.params for widget in widgets.values()) else _STATE_VERSION
            return DashboardStateData(version=version, queue=(), widgets=widgets)
        meta_dto = generated.DashboardStateMetaDTO.model_validate(meta)
        queue = tuple(
            StateQueueItem(
                id=item.id,
                group_item_id=item.group_item_id,
                tab_id=item.tab_id,
                extra=dict(item.model_extra or {}),
            )
            for item in meta_dto.queue
        )
        return DashboardStateData(
            version=_STATE_VERSION,
            queue=queue,
            widgets=widgets,
            meta_extra=dict(meta_dto.model_extra or {}),
        )

    @staticmethod
    def to_payload(
        data: DashboardStateData,
        *,
        dto_module: DashboardStateDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        payload: dict[str, object] = {}
        for widget_id, widget in data.widgets.items():
            body: dict[str, object] = dict(widget.extra)
            if widget.params is not None:
                body["params"] = _payload_params(widget.params)
            if widget.state is not None:
                state = dict(widget.state.extra)
                if widget.state.tab_id is not None:
                    state["tabId"] = widget.state.tab_id
                body["state"] = state
            payload[widget_id] = generated.DashboardStateWidgetDTO.model_validate(body).to_payload()
        if data.version == _STATE_VERSION:
            queue = []
            for item in data.queue:
                record: dict[str, object] = {**item.extra, "id": item.id}
                if item.group_item_id is not None:
                    record["groupItemId"] = item.group_item_id
                if item.tab_id is not None:
                    record["tabId"] = item.tab_id
                queue.append(record)
            meta = {**data.meta_extra, "queue": queue, "version": _STATE_VERSION}
            payload[_META_KEY] = generated.DashboardStateMetaDTO.model_validate(meta).to_payload()
        return payload
