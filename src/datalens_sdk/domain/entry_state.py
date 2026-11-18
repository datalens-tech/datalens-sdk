from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeAlias

StateWireValue: TypeAlias = "str | tuple[str, ...]"
StateWidgetParams: TypeAlias = "Mapping[str, StateWireValue] | Mapping[str, Mapping[str, StateWireValue]]"


@dataclass(frozen=True, slots=True)
class EntryStateRecord:
    """Raw entry state stored by ``createEntryState``; ``data`` is the opaque JSON object."""

    entry_id: str
    hash: str
    data: Mapping[str, object] | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class StateQueueItem:
    """One ``__meta__.queue`` item: a widget, a selector of a group (``group_item_id``) or a chart tab (``tab_id``)."""

    id: str
    group_item_id: str | None = None
    tab_id: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StateWidgetState:
    """The ``state`` of a widget entry: the active chart tab and any other widget settings."""

    tab_id: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StateWidget:
    """One widget entry of a dashboard state; ``params`` is ``None`` when the entry stores none."""

    params: StateWidgetParams | None = None
    state: StateWidgetState | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DashboardStateData:
    """A dashboard state as the ``DashboardState`` schema describes it, keyed by widget id."""

    version: Literal[1, 2]
    queue: tuple[StateQueueItem, ...]
    widgets: Mapping[str, StateWidget]
    meta_extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DashboardStateRecord:
    """A stored dashboard state: typed ``data`` and the JSON object it was read from or sent as."""

    hash: str
    data: DashboardStateData
    raw: Mapping[str, object]
    created_at: datetime | None = None
