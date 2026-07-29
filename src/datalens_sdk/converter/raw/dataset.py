from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from datalens_sdk.converter._dataset_policy import with_supported_rls2_state
from datalens_sdk.serialization.artifacts import DatasetSnapshotView
from datalens_sdk.serialization.json_types import JsonValue

_SERVER_OWNED_DATASET_FIELDS = frozenset({"name", "revId", "rev_id", "revisionId", "revision_id"})


class RawDatasetCreateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dataset: dict[str, JsonValue]
    dir_path: str | None = None
    workbook_id: str | None = None
    collection_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(exclude_none=True))


class RawDatasetReplaceData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: dict[str, JsonValue]


class RawDatasetReplaceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_id: str = Field(serialization_alias="datasetId")
    data: RawDatasetReplaceData

    def to_payload(self) -> dict[str, object]:
        return cast(dict[str, object], self.model_dump(by_alias=True))


def dataset_content_from_snapshot(source: DatasetSnapshotView) -> dict[str, JsonValue]:
    return with_supported_rls2_state(
        {key: value for key, value in source.dataset.items() if key not in _SERVER_OWNED_DATASET_FIELDS}
    )
