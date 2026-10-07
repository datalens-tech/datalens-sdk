from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk.domain.sql_query import SqlQueryParameter


@dataclass(frozen=True, slots=True)
class SqlQueryCreateSpec:
    name: str
    location: EntryLocation
    connection_id: str
    query: str
    description: str | None
    parameters: tuple[SqlQueryParameter, ...] | None


@dataclass(frozen=True, slots=True)
class SqlQueryUpdateSpec:
    sql_query_id: str
    name: str | None
    location: EntryLocation
    connection_id: str
    query: str
    description: str | None
    parameters: tuple[SqlQueryParameter, ...] | None
