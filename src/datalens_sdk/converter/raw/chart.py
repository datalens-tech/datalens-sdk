from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from datalens_sdk.serialization.json_types import JsonValue


def _validate_wizard_v1_config(data: Mapping[str, JsonValue]) -> None:
    sources = data.get("sources")
    visualization = data.get("visualization")
    if not isinstance(sources, Mapping) or not isinstance(sources.get("datasetsIds"), list):
        raise ValueError("Wizard V1 config requires sources.datasetsIds")
    if not isinstance(visualization, Mapping) or not isinstance(visualization.get("type"), str):
        raise ValueError("Wizard V1 config requires visualization.type")


class RawWizardChartCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    data: dict[str, JsonValue]
    key: str | None = None
    name: str | None = None
    workbook_id: str | None = Field(default=None, serialization_alias="workbookId")
    annotation: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _validate_data(self) -> RawWizardChartCreateEnvelope:
        _validate_wizard_v1_config(self.data)
        return self

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True, exclude_none=True))


class RawWizardChartReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chart_id: str = Field(serialization_alias="chartId")
    mode: Literal["save", "publish"]
    data: dict[str, JsonValue]
    annotation: dict[str, JsonValue] | None = None
    rev_id: str | None = Field(default=None, serialization_alias="revId")

    @model_validator(mode="after")
    def _validate_data(self) -> RawWizardChartReplaceEnvelope:
        _validate_wizard_v1_config(self.data)
        return self

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
