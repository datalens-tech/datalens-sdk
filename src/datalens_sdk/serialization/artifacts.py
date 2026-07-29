from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Literal, TypeAlias

from datalens_sdk._runtime.chart_constants import is_ql_wire_type, is_wizard_wire_type
from datalens_sdk.errors import DatalensValidationError
from datalens_sdk.serialization.connection import ConnectionSnapshotView
from datalens_sdk.serialization.json_io import read_json_object, write_artifact_directory
from datalens_sdk.serialization.json_types import JsonObject, JsonValue, normalize_json_object

ArtifactPath = str | os.PathLike[str]
ChartArtifactCategory: TypeAlias = Literal["wizard", "editor", "ql"]
CHART_FILENAME = "chart.json"
CONNECTION_FILENAME = "connection.json"
DASHBOARD_FILENAME = "dashboard.json"
DATASET_FILENAME = "dataset.json"
_CHART_ID_KEYS = ("id", "entryId", "entry_id", "chartId", "chart_id")
_DASHBOARD_ID_KEYS = ("id", "entryId", "entry_id", "dashboardId", "dashboard_id")
_DATASET_ID_KEYS = ("id", "entryId", "entry_id", "datasetId", "dataset_id")
_PORTABLE_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{index}" for index in range(1, 10)), *(f"LPT{index}" for index in range(1, 10))}
)


@dataclass(frozen=True, slots=True)
class ChartSnapshotView(Mapping[str, JsonValue]):
    snapshot: dict[str, JsonValue]
    entry: dict[str, JsonValue]
    category: ChartArtifactCategory
    wire_type: str
    data: dict[str, JsonValue]

    @classmethod
    def from_raw(
        cls,
        raw: Mapping[str, JsonValue],
        *,
        expected_category: ChartArtifactCategory,
    ) -> ChartSnapshotView:
        if isinstance(raw, cls):
            if raw.category != expected_category:
                raise DatalensValidationError(
                    f"Chart category mismatch: expected {expected_category!r}, snapshot is {raw.category!r}"
                )
            return raw

        return cls.capture(raw, expected_category=expected_category)

    @classmethod
    def capture(
        cls,
        raw: Mapping[str, JsonValue],
        *,
        expected_category: ChartArtifactCategory,
    ) -> ChartSnapshotView:
        snapshot = normalize_json_object(raw, context="Chart response snapshot")
        entry = chart_entry_from_normalized_snapshot(snapshot)
        data = entry.get("data")
        if not isinstance(data, dict):
            getter = f"client.get.{expected_category}_chart(...)"
            raise DatalensValidationError(
                f"Chart response snapshot has no complete 'data' content; fetch it with {getter} first"
            )
        if not any(isinstance(entry.get(key), str) and entry[key] for key in _CHART_ID_KEYS):
            getter = f"client.get.{expected_category}_chart(...)"
            raise DatalensValidationError(f"Chart response snapshot has no source id; fetch it with {getter} first")
        wire_type = entry.get("type")
        if not isinstance(wire_type, str) or not wire_type:
            getter = f"client.get.{expected_category}_chart(...)"
            raise DatalensValidationError(f"Chart response snapshot has no wire type; fetch it with {getter} first")
        actual_category = chart_category_from_wire_type(wire_type)
        if actual_category != expected_category:
            raise DatalensValidationError(
                f"Chart category mismatch: expected {expected_category!r}, snapshot is {actual_category!r}"
            )
        return cls(
            snapshot=snapshot,
            entry=entry,
            category=actual_category,
            wire_type=wire_type,
            data=data,
        )

    def __getitem__(self, key: str) -> JsonValue:
        return self.snapshot[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.snapshot)

    def __len__(self) -> int:
        return len(self.snapshot)

    def optional_object(self, field: str) -> dict[str, JsonValue] | None:
        value = self.entry.get(field)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise DatalensValidationError(f"Chart response snapshot field {field!r} must be an object")
        return value


@dataclass(frozen=True, slots=True)
class DashboardSnapshotView(Mapping[str, JsonValue]):
    snapshot: dict[str, JsonValue]
    entry: dict[str, JsonValue]
    data: dict[str, JsonValue]

    @classmethod
    def from_raw(cls, raw: Mapping[str, JsonValue]) -> DashboardSnapshotView:
        if isinstance(raw, cls):
            return raw

        return cls.capture(raw)

    @classmethod
    def capture(cls, raw: Mapping[str, JsonValue]) -> DashboardSnapshotView:
        snapshot = normalize_json_object(raw, context="Dashboard response snapshot")
        entry_value = snapshot.get("entry")
        if entry_value is None:
            entry = snapshot
        elif isinstance(entry_value, dict):
            entry = entry_value
        else:
            raise DatalensValidationError("Dashboard response snapshot field 'entry' must be an object")
        data = entry.get("data")
        if not isinstance(data, dict):
            raise DatalensValidationError(
                "Dashboard response snapshot has no complete 'data' content; "
                "fetch it with client.get.dashboard(...) first"
            )
        if not any(isinstance(entry.get(key), str) and entry[key] for key in _DASHBOARD_ID_KEYS):
            raise DatalensValidationError(
                "Dashboard response snapshot has no source id; fetch it with client.get.dashboard(...) first"
            )
        return cls(snapshot=snapshot, entry=entry, data=data)

    def __getitem__(self, key: str) -> JsonValue:
        return self.snapshot[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.snapshot)

    def __len__(self) -> int:
        return len(self.snapshot)

    def optional_object(self, field: str) -> dict[str, JsonValue] | None:
        value = self.entry.get(field)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise DatalensValidationError(f"Dashboard response snapshot field {field!r} must be an object or null")
        return value


@dataclass(frozen=True, slots=True)
class DatasetSnapshotView(Mapping[str, JsonValue]):
    snapshot: dict[str, JsonValue]
    dataset: dict[str, JsonValue]

    @classmethod
    def from_raw(cls, raw: Mapping[str, JsonValue]) -> DatasetSnapshotView:
        if isinstance(raw, cls):
            return raw

        return cls.capture(raw)

    @classmethod
    def capture(cls, raw: Mapping[str, JsonValue]) -> DatasetSnapshotView:
        snapshot = normalize_json_object(raw, context="Dataset response snapshot")
        return cls._from_normalized(snapshot)

    @classmethod
    def _from_normalized(cls, snapshot: dict[str, JsonValue]) -> DatasetSnapshotView:
        dataset = snapshot.get("dataset")
        if not isinstance(dataset, dict):
            raise DatalensValidationError(
                "Dataset response snapshot has no complete 'dataset' content; "
                "fetch it with client.get.dataset(...) first"
            )
        if not any(isinstance(snapshot.get(key), str) and snapshot[key] for key in _DATASET_ID_KEYS):
            raise DatalensValidationError(
                "Dataset response snapshot has no source id; fetch it with client.get.dataset(...) first"
            )
        return cls(snapshot=snapshot, dataset=dataset)

    def __getitem__(self, key: str) -> JsonValue:
        return self.snapshot[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.snapshot)

    def __len__(self) -> int:
        return len(self.snapshot)


def write_connection_artifact(
    path: ArtifactPath,
    response_snapshot: JsonObject,
    *,
    name: str | None,
    resource_id: str | None,
) -> Path:
    snapshot = require_complete_connection_snapshot(response_snapshot)
    target = artifact_directory_path(path, name=name, resource_id=resource_id, resource="Connection")
    return write_artifact_directory(target, filename=CONNECTION_FILENAME, value=snapshot)


def write_dataset_artifact(
    path: ArtifactPath,
    response_snapshot: JsonObject,
    *,
    name: str | None,
    resource_id: str | None,
) -> Path:
    snapshot = require_complete_dataset_snapshot(response_snapshot)
    target = artifact_directory_path(path, name=name, resource_id=resource_id, resource="Dataset")
    return write_artifact_directory(target, filename=DATASET_FILENAME, value=snapshot)


def write_dashboard_artifact(
    path: ArtifactPath,
    response_snapshot: JsonObject,
    *,
    name: str | None,
    resource_id: str | None,
) -> Path:
    snapshot = require_complete_dashboard_snapshot(response_snapshot)
    target = artifact_directory_path(path, name=name, resource_id=resource_id, resource="Dashboard")
    return write_artifact_directory(target, filename=DASHBOARD_FILENAME, value=snapshot)


def write_chart_artifact(
    path: ArtifactPath,
    response_snapshot: JsonObject,
    *,
    name: str | None,
    resource_id: str | None,
    category: ChartArtifactCategory,
    split_tabs: bool,
) -> Path:
    if split_tabs and category != "editor":
        raise DatalensValidationError("split_tabs=True is supported only for Editor charts")
    source = ChartSnapshotView.from_raw(response_snapshot, expected_category=category)
    target = artifact_directory_path(path, name=name, resource_id=resource_id, resource="Chart")
    if not split_tabs:
        return write_artifact_directory(target, filename=CHART_FILENAME, value=source.snapshot)

    from datalens_sdk.serialization.editor_tabs import materialize_editor_tabs  # noqa: PLC0415

    return write_artifact_directory(
        target,
        filename=CHART_FILENAME,
        value=source.snapshot,
        populate=lambda staging: materialize_editor_tabs(staging, source.data),
    )


def artifact_directory_path(
    parent: ArtifactPath,
    *,
    name: str | None,
    resource_id: str | None,
    resource: str,
) -> Path:
    parent_path = Path(parent)
    if not parent_path.is_dir():
        raise DatalensValidationError(f"Artifact parent directory does not exist: {parent_path}")
    if resource_id is None or not resource_id.strip():
        raise DatalensValidationError(f"{resource} artifact requires a resource id")
    if name is None or not name.strip():
        raise DatalensValidationError(f"{resource} artifact requires a resource name")
    sanitized_id = sanitize_artifact_component(resource_id)
    directory_name = f"{sanitize_artifact_component(name)} [{sanitized_id}]"
    return parent_path / directory_name


def sanitize_artifact_component(value: str) -> str:
    sanitized = _PORTABLE_UNSAFE_CHARS.sub("_", value).strip().rstrip(". ")
    if sanitized in {"", ".", ".."}:
        sanitized = "_"
    if sanitized.partition(".")[0].upper() in _WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    return sanitized


def read_dataset_artifact(path: ArtifactPath) -> DatasetSnapshotView:
    artifact_dir = Path(path)
    if not artifact_dir.is_dir():
        raise DatalensValidationError(f"Dataset artifact path must be a directory: {artifact_dir}")
    main_file = artifact_dir / DATASET_FILENAME
    if not main_file.is_file():
        raise DatalensValidationError(f"Dataset artifact does not contain {DATASET_FILENAME}: {artifact_dir}")
    return DatasetSnapshotView._from_normalized(read_json_object(main_file))


def read_connection_artifact(path: ArtifactPath) -> ConnectionSnapshotView:
    artifact_dir = Path(path)
    if not artifact_dir.is_dir():
        raise DatalensValidationError(f"Connection artifact path must be a directory: {artifact_dir}")
    main_file = artifact_dir / CONNECTION_FILENAME
    if not main_file.is_file():
        raise DatalensValidationError(f"Connection artifact does not contain {CONNECTION_FILENAME}: {artifact_dir}")
    return ConnectionSnapshotView._from_normalized(read_json_object(main_file))


def read_chart_artifact(
    path: ArtifactPath,
    *,
    expected_category: ChartArtifactCategory,
) -> ChartSnapshotView:
    artifact_dir = Path(path)
    if not artifact_dir.is_dir():
        raise DatalensValidationError(f"Chart artifact path must be a directory: {artifact_dir}")
    main_file = artifact_dir / CHART_FILENAME
    if not main_file.is_file():
        raise DatalensValidationError(f"Chart artifact does not contain {CHART_FILENAME}: {artifact_dir}")
    return ChartSnapshotView.from_raw(
        read_json_object(main_file),
        expected_category=expected_category,
    )


def read_dashboard_artifact(path: ArtifactPath) -> dict[str, JsonValue]:
    artifact_dir = Path(path)
    if not artifact_dir.is_dir():
        raise DatalensValidationError(f"Dashboard artifact path must be a directory: {artifact_dir}")
    main_file = artifact_dir / DASHBOARD_FILENAME
    if not main_file.is_file():
        raise DatalensValidationError(f"Dashboard artifact does not contain {DASHBOARD_FILENAME}: {artifact_dir}")
    return require_complete_dashboard_snapshot(read_json_object(main_file))


def chart_entry_from_normalized_snapshot(snapshot: dict[str, JsonValue]) -> dict[str, JsonValue]:
    entry = snapshot.get("entry")
    if entry is None:
        return snapshot
    if not isinstance(entry, dict):
        raise DatalensValidationError("Chart response snapshot field 'entry' must be an object")
    return entry


def chart_category_from_wire_type(wire_type: str) -> ChartArtifactCategory:
    if is_wizard_wire_type(wire_type):
        return "wizard"
    if is_ql_wire_type(wire_type):
        return "ql"
    return "editor"


def require_complete_chart_snapshot(
    raw: object,
    *,
    expected_category: ChartArtifactCategory,
) -> dict[str, JsonValue]:
    if not isinstance(raw, Mapping):
        raise DatalensValidationError("Chart response snapshot must be an object")
    return ChartSnapshotView.from_raw(raw, expected_category=expected_category).snapshot


def require_complete_dashboard_snapshot(raw: object) -> dict[str, JsonValue]:
    if not isinstance(raw, Mapping):
        raise DatalensValidationError("Dashboard response snapshot must be an object")
    return DashboardSnapshotView.from_raw(raw).snapshot


def require_complete_connection_snapshot(raw: object) -> dict[str, JsonValue]:
    if not isinstance(raw, Mapping):
        raise DatalensValidationError("Connection response snapshot must be an object")
    return ConnectionSnapshotView.from_raw(raw).snapshot


def require_complete_dataset_snapshot(raw: object) -> dict[str, JsonValue]:
    if not isinstance(raw, Mapping):
        raise DatalensValidationError("Dataset response snapshot must be an object")
    return DatasetSnapshotView.from_raw(raw).snapshot
