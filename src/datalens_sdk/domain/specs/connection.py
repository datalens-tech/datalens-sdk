from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from datalens_sdk.domain.entry_location import EntryLocation

__all__ = ["ConnectionCreateSpec", "ConnectionUpdateSpec"]


@dataclass(frozen=True, slots=True)
class ConnectionCreateSpec:
    """Immutable snapshot of a connection-create builder's state.

    This is the read contract between the domain builder layer and the
    converter/api layers. Converters and services consume this spec instead of
    reaching into builder ``_protected`` attributes.
    """

    installation: str
    connector: str
    name: str
    params: Mapping[str, object] = field(repr=False)
    location: EntryLocation


@dataclass(frozen=True, slots=True)
class ConnectionUpdateSpec:
    """Immutable snapshot of a connection-update builder's state."""

    connection_id: str
    changes: Mapping[str, object] = field(repr=False)
    connection_name: str | None = None
    connection_location: EntryLocation | None = None
