from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk._runtime.viz_specs import build_ql_item
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter.raw.chart import (
    RawQLChartCreateEnvelope,
    RawQLChartReplaceEnvelope,
)
from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    key_from_location,
    resolve_entry_location_from_api_fields,
    workbook_id_from_location,
)
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.ql_chart import QLChart, QLChartUpdate, QLColumn
from datalens_sdk.domain.specs.ql_chart import QLChartCreateSpec
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import DatalensValidationError
from datalens_sdk.serialization.artifacts import ChartSnapshotView
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object


class QLChartCreateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class QLChartUpdateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class QLChartReadDTOProtocol(Protocol):
    entry_id: str | None
    type: str | None
    data: dict[str, object] | None
    raw: dict[str, object]


class QLChartReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> QLChartReadDTOProtocol: ...


class QLChartCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        template: str,
        data: Mapping[str, object],
        key: str | None = None,
        name: str | None = None,
        workbook_id: str | None = None,
        annotation: Mapping[str, object] | None = None,
    ) -> QLChartCreateDTOProtocol: ...


class QLChartUpdateDTOClass(Protocol):
    def __call__(
        self,
        *,
        entry_id: str,
        template: str,
        mode: str,
        data: Mapping[str, object],
        annotation: Mapping[str, object] | None = None,
    ) -> QLChartUpdateDTOProtocol: ...


class QLChartDtoModule(Protocol):
    QLChartCreateDTO: QLChartCreateDTOClass
    QLChartUpdateDTO: QLChartUpdateDTOClass
    QLChartReadDTO: QLChartReadDTOClass


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _connection_to_wire(connection: Connection) -> dict[str, object]:
    payload: dict[str, object] = {
        "entryId": connection.id,
        "type": connection.type,
    }
    raw_flag: object = None
    if "dataExportForbidden" in connection.raw:
        raw_flag = connection.raw["dataExportForbidden"]
    elif "data_export_forbidden" in connection.raw:
        raw_flag = connection.raw["data_export_forbidden"]
    if isinstance(raw_flag, bool):
        payload["dataExportForbidden"] = raw_flag
    elif isinstance(raw_flag, str) and raw_flag.lower() in {"on", "off", "true", "false"}:
        payload["dataExportForbidden"] = raw_flag.lower() in {"on", "true"}
    return payload


def _read_response_id(raw: Mapping[str, object]) -> str | None:
    for key in ("entryId", "entry_id", "id"):
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _dict_with_string_keys(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _dto_module(dto_module: QLChartDtoModule | None) -> QLChartDtoModule:
    return cast(QLChartDtoModule, generated_dto if dto_module is None else dto_module)


def _apply_placeholder_edits(
    data: dict[str, object],
    edits: Mapping[str, tuple[QLColumn, ...]],
) -> None:
    if not edits:
        return
    visualization = data.get("visualization")
    if not isinstance(visualization, Mapping):
        raise ValueError("QL placeholder edits require data.visualization")
    placeholders = visualization.get("placeholders")
    if not isinstance(placeholders, list):
        raise ValueError("QL placeholder edits require data.visualization.placeholders")

    edited_placeholders: list[object] = []
    applied: set[str] = set()
    for placeholder in placeholders:
        if not isinstance(placeholder, Mapping):
            edited_placeholders.append(placeholder)
            continue
        placeholder_id = placeholder.get("id")
        if not isinstance(placeholder_id, str):
            edited_placeholders.append(placeholder)
            continue
        columns = edits.get(placeholder_id)
        if columns is None:
            edited_placeholders.append(placeholder)
            continue
        edited = dict(placeholder)
        edited["items"] = [build_ql_item(column.name, column.cast) for column in columns]
        edited_placeholders.append(edited)
        applied.add(placeholder_id)

    missing = set(edits) - applied
    if missing:
        raise ValueError(f"QL visualization is missing edited placeholders: {sorted(missing)}")
    edited_visualization = dict(visualization)
    edited_visualization["placeholders"] = edited_placeholders
    data["visualization"] = edited_visualization


class QLChartConverter:
    @staticmethod
    def from_domain_create(
        spec: QLChartCreateSpec,
        *,
        dto_module: QLChartDtoModule | None = None,
    ) -> QLChartCreateDTOProtocol:
        """Build a create payload DTO from a structured QL create spec.

        The QL ``data`` object is assembled from the spec's structured fields
        (connection, queryValue, params, visualization) plus the stable scaffold
        keys shared by every QL chart (``chartType``, ``type``, ``version``,
        empty ``queries``/``colors``/... arrays). Unknown additional fields from
        ``spec.extra_data`` are merged on top as an escape hatch.
        """
        generated = _dto_module(dto_module)
        data = _build_create_data(spec)
        key = key_from_location(spec.location, name=spec.name)
        annotation: dict[str, object] | None = None
        if spec.description:
            annotation = {"description": spec.description}
        return generated.QLChartCreateDTO(
            template="ql",
            data=data,
            key=key,
            name=None if key else spec.name,
            workbook_id=workbook_id_from_location(spec.location),
            annotation=annotation,
        )

    @staticmethod
    def from_domain_update(
        update: QLChartUpdate,
        *,
        dto_module: QLChartDtoModule | None = None,
    ) -> QLChartUpdateDTOProtocol:
        """Build an update payload DTO by merging targeted edits onto current data.

        Starts from the chart's existing structured ``data``, then overlays the
        explicit update fields (``queryValue``/``connection``/``params``) and the
        opaque ``data()`` merge, preserving round-trip fidelity of untouched
        fields.
        """
        generated = _dto_module(dto_module)
        chart = update.chart
        current_data: dict[str, object] = {k: v for k, v in chart.data.items() if isinstance(k, str)}
        if update.query_value is not None:
            current_data["queryValue"] = update.query_value
        if update.connection_obj is not None:
            current_data["connection"] = _connection_to_wire(update.connection_obj)
        if update.params_objs is not None:
            current_data["params"] = [dict(p.to_mapping()) for p in update.params_objs]
        _apply_placeholder_edits(current_data, update.placeholder_edits)
        for section, columns in update.data_section_edits.items():
            current_data[section] = [build_ql_item(column.name, column.cast) for column in columns]
        if update.has_data_merge:
            current_data.update(update.data_merge)
        annotation_data = _dict_with_string_keys(chart.raw.get("annotation"))
        if update.description_value is not None:
            annotation_data["description"] = update.description_value
        annotation: dict[str, object] | None = annotation_data or None
        return generated.QLChartUpdateDTO(
            entry_id=cast(str, chart.id),
            template="ql",
            mode=update.mode_value,
            data=current_data,
            annotation=annotation,
        )

    @staticmethod
    def from_raw_create(
        spec: RawCreateSpec,
        *,
        source: ChartSnapshotView,
    ) -> RawQLChartCreateEnvelope:
        key = key_from_location(spec.location, name=spec.name)
        return RawQLChartCreateEnvelope(
            data=source.data,
            key=key,
            name=None if key else spec.name,
            workbook_id=workbook_id_from_location(spec.location),
            annotation=source.optional_object("annotation"),
        )

    @staticmethod
    def from_raw_replace(
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
        source: ChartSnapshotView,
    ) -> RawQLChartReplaceEnvelope:
        if source.wire_type != target_wire_type:
            raise DatalensValidationError(
                f"QL chart wire type mismatch: source is {source.wire_type!r}, target is {target_wire_type!r}"
            )
        return RawQLChartReplaceEnvelope(
            entry_id=spec.target_id,
            mode=mode,
            data=source.data,
            annotation=source.optional_object("annotation"),
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | QLChartReadDTOProtocol,
        *,
        installation: str,
        operations: ChartOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        id_fallback: str | None = None,
        wire_type_fallback: str | None = None,
        dto_module: QLChartDtoModule | None = None,
    ) -> QLChart:
        generated = _dto_module(dto_module)
        response_snapshot: dict[str, JsonValue] = {}
        response: Mapping[str, object]
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="QL chart API response")
            dto_validation_input = dict(response_snapshot)
            dto_validation_input["raw"] = normalize_json_object(
                response_snapshot,
                context="QL chart typed response state",
            )
            read_dto = generated.QLChartReadDTO.model_validate(dto_validation_input)
            response = normalize_json_object(
                response_snapshot,
                context="QL chart typed response state",
            )
        else:
            read_dto = raw
            response = read_dto.raw or {}
        wire_type = read_dto.type or _optional_str(response.get("type")) or wire_type_fallback or "d3_ql_node"
        raw_data = read_dto.data
        if raw_data is None:
            raw_data = _dict_with_string_keys(response.get("data"))
        data = _dict_with_string_keys(raw_data) if raw_data is not None else {}
        key = _optional_str(response.get("key"))
        domain_location = resolve_entry_location_from_api_fields(
            dir_path=_optional_str(response.get("dir_path")),
            key=key,
            collection_id=_optional_str(response.get("collection_id")) or _optional_str(response.get("collectionId")),
            workbook_id=_optional_str(response.get("workbook_id")) or _optional_str(response.get("workbookId")),
            fallback=location,
        )
        return QLChart(
            id=read_dto.entry_id or _read_response_id(response) or id_fallback,
            installation=installation,
            name=_optional_str(response.get("name")) or name_from_key(key) or name,
            location=domain_location,
            wire_type=wire_type,
            data=data,
            raw=response,
            response_snapshot=response_snapshot,
            _operations=operations,
        )


def _build_create_data(spec: QLChartCreateSpec) -> dict[str, object]:
    connection = spec.connection
    data: dict[str, object] = {
        "chartType": "sql",
        "type": "ql",
        "version": "7",
        "connection": _connection_to_wire(connection) if connection is not None else {},
        "queryValue": spec.query,
        "params": [dict(p.to_mapping()) for p in spec.params],
        "queries": [],
        "order": None,
        "colors": [],
        "labels": [],
        "shapes": [],
        "tooltips": [],
        "colorsConfig": {},
        "shapesConfig": {},
        "extraSettings": {},
        "geopointsConfig": {},
    }
    if spec.visualization is not None:
        data["visualization"] = dict(spec.visualization)
    for key, value in spec.extra_data.items():
        if isinstance(key, str):
            data[key] = value
    return data
