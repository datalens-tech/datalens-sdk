from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from datalens_sdk.serialization.json_types import JsonValue


class RawDashboardCreateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: dict[str, JsonValue]
    meta: dict[str, JsonValue] | None
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: dict[str, JsonValue] | None = None


class RawDashboardCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: RawDashboardCreateEntry

    def to_payload(self) -> dict[str, object]:
        entry = cast(dict[str, object], self.entry.model_dump(by_alias=True, exclude_none=True))
        entry["meta"] = self.entry.meta
        return {"entry": entry}


class RawDashboardReplaceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    data: dict[str, JsonValue]
    meta: dict[str, JsonValue] | None
    annotation: dict[str, JsonValue] | None = None


class RawDashboardReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry: RawDashboardReplaceEntry
    mode: Literal["save", "publish"]
    lock_token: str | None = Field(default=None, serialization_alias="lockToken")

    def to_payload(self) -> dict[str, object]:
        entry = cast(dict[str, object], self.entry.model_dump(by_alias=True, exclude_none=True))
        entry["meta"] = self.entry.meta
        payload: dict[str, object] = {"entry": entry, "mode": self.mode}
        if self.lock_token is not None:
            payload["lockToken"] = self.lock_token
        return payload
