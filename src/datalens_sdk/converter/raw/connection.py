from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from datalens_sdk.serialization.connection import (
    CONNECTION_SERVER_OWNED_FIELDS,
    ConnectionOverridesView,
    ConnectionSnapshotView,
)
from datalens_sdk.serialization.json_types import JsonValue


class RawConnectionCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, JsonValue]

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.params)


class RawConnectionReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    connection_id: str = Field(serialization_alias="connectionId")
    data: dict[str, JsonValue]

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True))


def connection_params_from_snapshot(
    source: ConnectionSnapshotView,
    *,
    overrides: Mapping[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    params = {key: value for key, value in source.snapshot.items() if key not in CONNECTION_SERVER_OWNED_FIELDS}
    if overrides is None:
        return params
    params.update(ConnectionOverridesView.from_raw(overrides))
    return params
