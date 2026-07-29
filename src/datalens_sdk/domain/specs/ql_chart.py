from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from datalens_sdk.domain.entry_location import EntryLocation

if TYPE_CHECKING:
    from datalens_sdk.domain.connection import Connection
    from datalens_sdk.domain.ql_chart import QLParam

__all__ = ["QLChartCreateSpec"]


@dataclass(frozen=True, slots=True)
class QLChartCreateSpec:
    """Immutable snapshot of a QL-chart-create builder's state.

    A QL (SQL) chart stores its configuration as a single structured ``data``
    object on the wire (``chartType=sql``, ``type=ql``, ``version=7``), not as
    free-form string tabs. This spec is the read contract between the domain
    builder layer and the converter/api layers: it carries the QL-specific
    structured fields (connection, query, visualization, params) plus an opaque
    ``extra_data`` escape hatch for any additional ``data`` keys.

    Converters and services consume this spec instead of reaching into builder
    ``_protected`` attributes. Wire serialization (``entryId``/``type``,
    ``QLParam.to_mapping()``) happens only in
    :class:`datalens_sdk.converter.ql_chart.QLChartConverter`; the spec holds
    domain objects (``Connection``, ``QLParam``).
    """

    name: str
    location: EntryLocation
    connection: Connection | None = None
    query: str = ""
    visualization: Mapping[str, object] | None = None
    params: tuple[QLParam, ...] = ()
    extra_data: Mapping[str, object] = field(default_factory=dict)
    description: str | None = None
