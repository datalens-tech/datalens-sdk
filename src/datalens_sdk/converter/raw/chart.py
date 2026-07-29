from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from datalens_sdk.serialization.json_types import JsonValue


class RawWizardChartCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    template: Literal["datalens"] = "datalens"
    data: dict[str, JsonValue]
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: dict[str, JsonValue] | None = None

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))


class RawWizardChartReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    template: Literal["datalens"] = "datalens"
    mode: Literal["save", "publish"]
    data: dict[str, JsonValue]
    annotation: dict[str, JsonValue] | None = None

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))


class RawQLChartCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    template: Literal["ql"] = "ql"
    data: dict[str, JsonValue]
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: dict[str, JsonValue] | None = None

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))


class RawQLChartReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entry_id: str = Field(serialization_alias="entryId")
    template: Literal["ql"] = "ql"
    mode: Literal["save", "publish"]
    data: dict[str, JsonValue]
    annotation: dict[str, JsonValue] | None = None

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))


class RawEditorChartCreateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str
    data: dict[str, JsonValue]
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: dict[str, JsonValue] | None = None
    meta: dict[str, JsonValue] | None = None
    links: dict[str, JsonValue] | None = None


class RawEditorChartCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: RawEditorChartCreateEntry

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))


class RawEditorChartReplaceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: str
    entry_id: str = Field(serialization_alias="entryId")
    data: dict[str, JsonValue]
    annotation: dict[str, JsonValue] | None = None
    meta: dict[str, JsonValue] | None = None
    links: dict[str, JsonValue] | None = None


class RawEditorChartReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: RawEditorChartReplaceEntry
    mode: Literal["save", "publish"]

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))
