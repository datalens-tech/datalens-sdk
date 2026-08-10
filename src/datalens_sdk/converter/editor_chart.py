from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter._utils import _optional_str, _read_response_id
from datalens_sdk.converter.raw.chart import (
    RawEditorChartCreateEntry,
    RawEditorChartCreateEnvelope,
    RawEditorChartReplaceEntry,
    RawEditorChartReplaceEnvelope,
)
from datalens_sdk.domain.editor_chart import EditorChart, EditorChartUpdate
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    key_from_location,
    resolve_entry_location_from_api_fields,
    workbook_id_from_location,
)
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.specs.editor_chart import EditorChartCreateSpec
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import DataLensValidationError, NotSupportedError
from datalens_sdk.serialization.artifacts import ChartSnapshotView, chart_entry_from_normalized_snapshot
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object


class EditorChartCreateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class EditorChartUpdateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class _EditorChartUpdatePayload:
    """Preserve explicit secret clearing across generated DTO serialization."""

    def __init__(
        self,
        delegate: EditorChartUpdateDTOProtocol,
        *,
        include_secrets: bool,
        secrets: str | None,
    ) -> None:
        self._delegate = delegate
        self._include_secrets = include_secrets
        self._secrets = secrets

    def to_payload(self) -> dict[str, object]:
        payload = self._delegate.to_payload()
        if not self._include_secrets:
            return payload
        entry = payload.get("entry")
        if not isinstance(entry, dict):
            raise ValueError("Editor update DTO payload has no entry mapping")
        data = entry.get("data")
        if not isinstance(data, dict):
            raise ValueError("Editor update DTO payload has no entry.data mapping")
        data["secrets"] = self._secrets
        return payload


class EditorChartReadDTOProtocol(Protocol):
    entry_id: str | None
    type: str | None
    data: dict[str, object] | None
    raw: dict[str, object]


class EditorChartReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> EditorChartReadDTOProtocol: ...


class EditorChartDtoModule(Protocol):
    EditorChartReadDTO: EditorChartReadDTOClass
    INSTALLATION_EDITOR_NODE_TYPES: dict[str, frozenset[str]]


def editor_wire_types(installation: str, dto_module: EditorChartDtoModule | None) -> frozenset[str]:
    module = generated_dto if dto_module is None else dto_module
    mapping: dict[str, frozenset[str]] = getattr(module, "INSTALLATION_EDITOR_NODE_TYPES", {})
    return mapping.get(installation, frozenset())


def _dict_with_string_keys(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


_WIRE_TYPE_TO_CREATE_DTO: dict[str, str] = {
    "advanced-chart_node": "AdvancedChartNodeNodeEntryCreateDTO",
    "control_node": "ControlNodeNodeEntryCreateDTO",
    "d3_node": "D3NodeNodeEntryCreateDTO",
    "graph_node": "GraphNodeNodeEntryCreateDTO",
    "markdown_node": "MarkdownNodeNodeEntryCreateDTO",
    "markup_node": "MarkupNodeNodeEntryCreateDTO",
    "metric_node": "MetricNodeNodeEntryCreateDTO",
    "module": "ModuleNodeEntryCreateDTO",
    "table_node": "TableNodeNodeEntryCreateDTO",
    "timeseries_node": "TimeseriesNodeNodeEntryCreateDTO",
    "ymap_node": "YmapNodeNodeEntryCreateDTO",
}

_WIRE_TYPE_TO_UPDATE_DTO: dict[str, str] = {
    "advanced-chart_node": "AdvancedChartNodeNodeEntryUpdateDTO",
    "control_node": "ControlNodeNodeEntryUpdateDTO",
    "d3_node": "D3NodeNodeEntryUpdateDTO",
    "graph_node": "GraphNodeNodeEntryUpdateDTO",
    "markdown_node": "MarkdownNodeNodeEntryUpdateDTO",
    "markup_node": "MarkupNodeNodeEntryUpdateDTO",
    "metric_node": "MetricNodeNodeEntryUpdateDTO",
    "module": "ModuleNodeEntryUpdateDTO",
    "table_node": "TableNodeNodeEntryUpdateDTO",
    "timeseries_node": "TimeseriesNodeNodeEntryUpdateDTO",
    "ymap_node": "YmapNodeNodeEntryUpdateDTO",
}

_WIRE_TYPE_TO_DATA_DTO: dict[str, str] = {
    "advanced-chart_node": "AdvancedChartNodeNodeDataDTO",
    "control_node": "ControlNodeNodeDataDTO",
    "d3_node": "D3NodeNodeDataDTO",
    "graph_node": "GraphNodeNodeDataDTO",
    "markdown_node": "MarkdownNodeNodeDataDTO",
    "markup_node": "MarkupNodeNodeDataDTO",
    "metric_node": "MetricNodeNodeDataDTO",
    "module": "ModuleNodeDataDTO",
    "table_node": "TableNodeNodeDataDTO",
    "timeseries_node": "TimeseriesNodeNodeDataDTO",
    "ymap_node": "YmapNodeNodeDataDTO",
}

_WIRE_TYPE_TO_UPDATE_DATA_DTO: dict[str, str] = {
    "advanced-chart_node": "AdvancedChartNodeNodeUpdateDataDTO",
    "control_node": "ControlNodeNodeUpdateDataDTO",
    "d3_node": "D3NodeNodeUpdateDataDTO",
    "graph_node": "GraphNodeNodeUpdateDataDTO",
    "markdown_node": "MarkdownNodeNodeUpdateDataDTO",
    "markup_node": "MarkupNodeNodeUpdateDataDTO",
    "metric_node": "MetricNodeNodeUpdateDataDTO",
    "module": "ModuleNodeUpdateDataDTO",
    "table_node": "TableNodeNodeUpdateDataDTO",
    "timeseries_node": "TimeseriesNodeNodeUpdateDataDTO",
    "ymap_node": "YmapNodeNodeUpdateDataDTO",
}


def _get_required_fields(data_dto_name: str, dto_module: object) -> frozenset[str]:
    data_dto_cls = getattr(dto_module, data_dto_name, None)
    if data_dto_cls is None:
        return frozenset()
    model_fields = getattr(data_dto_cls, "model_fields", {})
    required: set[str] = set()
    for field_name, field_info in model_fields.items():
        is_required = getattr(field_info, "is_required", lambda: True)
        if callable(is_required):
            if is_required():
                required.add(field_name)
        else:
            if is_required:
                required.add(field_name)
    return frozenset(required)


def _fill_required_tabs(
    tabs: Mapping[str, str | None],
    *,
    data_dto_name: str,
    dto_module: object,
) -> dict[str, str | None]:
    required = _get_required_fields(data_dto_name, dto_module)
    result = dict(tabs)
    for field_name in required:
        if field_name not in result:
            result[field_name] = ""
    return result


class EditorChartConverter:
    @staticmethod
    def from_domain_create(
        spec: EditorChartCreateSpec,
        *,
        dto_module: object = None,
    ) -> EditorChartCreateDTOProtocol:
        effective_module = generated_dto if dto_module is None else dto_module
        wire_type = spec.wire_type

        create_dto_name = _WIRE_TYPE_TO_CREATE_DTO.get(wire_type)
        data_dto_name = _WIRE_TYPE_TO_DATA_DTO.get(wire_type)
        if create_dto_name is None or data_dto_name is None:
            raise ValueError(f"Unknown editor wire_type: {wire_type!r}")

        create_dto_cls = getattr(effective_module, create_dto_name, None)
        data_dto_cls = getattr(effective_module, data_dto_name, None)
        if create_dto_cls is None:
            raise ValueError(f"DTO class {create_dto_name!r} not found in dto module")
        if data_dto_cls is None:
            raise ValueError(f"DTO class {data_dto_name!r} not found in dto module")

        filled_tabs = _fill_required_tabs(
            spec.tabs,
            data_dto_name=data_dto_name,
            dto_module=effective_module,
        )
        data_obj = data_dto_cls(**filled_tabs)

        key = key_from_location(spec.location, name=spec.name)
        annotation = {"description": spec.description} if spec.description else None
        result = create_dto_cls(
            type=wire_type,
            data=data_obj,
            key=key,
            name=None if key else spec.name,
            workbook_id=workbook_id_from_location(spec.location),
            annotation=annotation,
        )
        return cast(EditorChartCreateDTOProtocol, result)

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | EditorChartReadDTOProtocol,
        *,
        installation: str,
        operations: ChartOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        id_fallback: str | None = None,
        wire_type_fallback: str | None = None,
        dto_module: object = None,
    ) -> EditorChart:
        effective_module = generated_dto if dto_module is None else dto_module
        read_dto_cls = getattr(effective_module, "EditorChartReadDTO", None)
        if read_dto_cls is None:
            raise ValueError("EditorChartReadDTO not found in dto module")
        response_snapshot: dict[str, JsonValue] = {}
        response: Mapping[str, object]
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="Editor chart API response")
            response = chart_entry_from_normalized_snapshot(response_snapshot)
            dto_validation_input = dict(response)
            dto_validation_input["raw"] = normalize_json_object(
                response,
                context="Editor chart typed response state",
            )
            read_dto = read_dto_cls.model_validate(dto_validation_input)
            response = normalize_json_object(
                response,
                context="Editor chart typed response state",
            )
        else:
            read_dto = raw
            response = read_dto.raw or {}
        wire_type = _optional_str(response.get("type")) or wire_type_fallback
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
        return EditorChart(
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

    @staticmethod
    def from_raw_create(
        spec: RawCreateSpec,
        *,
        installation: str,
        dto_module: EditorChartDtoModule | None,
        source: ChartSnapshotView,
    ) -> RawEditorChartCreateEnvelope:
        supported = editor_wire_types(installation, dto_module)
        if source.wire_type not in supported:
            raise NotSupportedError(
                f"Editor chart type {source.wire_type!r} is not available on installation {installation!r}"
            )
        key = key_from_location(spec.location, name=spec.name)
        return RawEditorChartCreateEnvelope(
            entry=RawEditorChartCreateEntry(
                type=source.wire_type,
                data=source.data,
                key=key,
                name=None if key else spec.name,
                workbook_id=workbook_id_from_location(spec.location),
                annotation=source.optional_object("annotation"),
                meta=source.optional_object("meta"),
                links=source.optional_object("links"),
            )
        )

    @staticmethod
    def from_raw_replace(
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
        installation: str,
        dto_module: EditorChartDtoModule | None,
        source: ChartSnapshotView,
    ) -> RawEditorChartReplaceEnvelope:
        supported = editor_wire_types(installation, dto_module)
        if source.wire_type not in supported:
            raise NotSupportedError(
                f"Editor chart type {source.wire_type!r} is not available on installation {installation!r}"
            )
        if source.wire_type != target_wire_type:
            raise DataLensValidationError(
                f"Editor chart wire type mismatch: source is {source.wire_type!r}, target is {target_wire_type!r}"
            )
        return RawEditorChartReplaceEnvelope(
            entry=RawEditorChartReplaceEntry(
                type=target_wire_type,
                entry_id=spec.target_id,
                data=source.data,
                annotation=source.optional_object("annotation"),
                meta=source.optional_object("meta"),
                links=source.optional_object("links"),
            ),
            mode=mode,
        )

    @staticmethod
    def from_domain_update(
        update: EditorChartUpdate,
        *,
        dto_module: object = None,
    ) -> EditorChartUpdateDTOProtocol:
        effective_module = generated_dto if dto_module is None else dto_module
        chart = update.chart
        wire_type = chart.wire_type
        if wire_type is None:
            raise ValueError("Cannot update editor chart without wire_type")

        update_dto_name = _WIRE_TYPE_TO_UPDATE_DTO.get(wire_type)
        update_data_dto_name = _WIRE_TYPE_TO_UPDATE_DATA_DTO.get(wire_type)
        if update_dto_name is None or update_data_dto_name is None:
            raise ValueError(f"Unknown editor wire_type for update: {wire_type!r}")

        update_dto_cls = getattr(effective_module, update_dto_name, None)
        update_data_dto_cls = getattr(effective_module, update_data_dto_name, None)
        if update_dto_cls is None:
            raise ValueError(f"DTO class {update_dto_name!r} not found in dto module")
        if update_data_dto_cls is None:
            raise ValueError(f"DTO class {update_data_dto_name!r} not found in dto module")

        current_data: dict[str, str | None] = {k: v for k, v in chart.data.items() if isinstance(v, str) or v is None}
        for tab, content in update.tab_edits.items():
            current_data[tab] = content

        filled_data = _fill_required_tabs(
            current_data,
            data_dto_name=update_data_dto_name,
            dto_module=effective_module,
        )
        data_obj = update_data_dto_cls(**filled_data)

        annotation_data = _dict_with_string_keys(chart.raw.get("annotation"))
        if update.description_value is not None:
            annotation_data["description"] = update.description_value
        annotation: dict[str, object] | None = annotation_data or None
        result = update_dto_cls(
            type=wire_type,
            entry_id=cast(str, chart.id),
            data=data_obj,
            mode=update.mode_value,
            annotation=annotation,
        )
        delegate = cast(EditorChartUpdateDTOProtocol, result)
        return _EditorChartUpdatePayload(
            delegate,
            include_secrets="secrets" in update.tab_edits,
            secrets=update.tab_edits.get("secrets"),
        )
