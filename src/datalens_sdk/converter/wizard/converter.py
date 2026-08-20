from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass
import re
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk._runtime.wizard_structure import WizardFieldStructure, WizardVisualizationRegistry
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter._utils import _optional_str
from datalens_sdk.converter.raw.chart import (
    RawWizardChartCreateEnvelope,
    RawWizardChartReplaceEnvelope,
)
from datalens_sdk.converter.wizard._assemble import (
    _assemble_wizard_data,
    _assert_encoding_owned_setting_keys_are_generated,
)
from datalens_sdk.converter.wizard._types import WizardConfigV1, WizardJsonObject
from datalens_sdk.converter.wizard._update import _apply_update_operations, _refuse_orphaning_publish
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    key_from_location,
    resolve_entry_location_from_api_fields,
    workbook_id_from_location,
)
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec
from datalens_sdk.domain.wizard_chart import WizardChart, WizardChartUpdate
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.artifacts import ChartSnapshotView
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object


class WizardChartCreateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, JsonValue]: ...


class WizardChartUpdateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, JsonValue]: ...


class WizardChartCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        data: WizardConfigV1,
        key: str | None = None,
        name: str | None = None,
        workbook_id: str | None = None,
        annotation: Mapping[str, object] | None = None,
    ) -> WizardChartCreateDTOProtocol: ...


class WizardChartUpdateDTOClass(Protocol):
    def __call__(
        self,
        *,
        chart_id: str,
        mode: str,
        data: Mapping[str, JsonValue],
        annotation: Mapping[str, object] | None = None,
        rev_id: str | None = None,
    ) -> WizardChartUpdateDTOProtocol: ...


class WizardChartEntryReadDTOProtocol(Protocol):
    entry_id: str
    type: str | None
    data: dict[str, JsonValue]


class WizardChartReadDTOProtocol(Protocol):
    entry: WizardChartEntryReadDTOProtocol
    raw: dict[str, JsonValue]


class WizardChartReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> WizardChartReadDTOProtocol: ...


class WizardChartDtoModule(Protocol):
    WIZARD_SCHEMA_FINGERPRINT: str | None
    WIZARD_VISUALIZATION_STRUCTURE: WizardVisualizationRegistry
    WIZARD_FIELD_STRUCTURE: WizardFieldStructure
    WizardChartCreateDTO: WizardChartCreateDTOClass
    WizardChartUpdateDTO: WizardChartUpdateDTOClass
    WizardChartReadDTO: WizardChartReadDTOClass


@dataclass(frozen=True)
class WizardGeneratedContract:
    schema_fingerprint: str | None
    visualization_structure: WizardVisualizationRegistry
    field_structure: WizardFieldStructure
    create_dto: WizardChartCreateDTOClass
    update_dto: WizardChartUpdateDTOClass
    read_dto: WizardChartReadDTOClass

    def require_available(self) -> None:
        if not self.visualization_structure:
            raise DataLensConfigurationError(
                "Wizard API v3 is unavailable because this installation has no generated Wizard structure."
            )


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_value_structure(value: object) -> bool:
    if not isinstance(value, Mapping) or not set(value) <= {"enum"}:
        return False
    return "enum" not in value or _is_string_list(value["enum"])


def _is_settings_structure(value: object) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(name, str) and _is_value_structure(setting) for name, setting in value.items()
    )


def _is_slots_structure(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    for name, slot in value.items():
        if not isinstance(name, str) or not isinstance(slot, Mapping):
            return False
        if set(slot) != {"required", "items_required", "settings"}:
            return False
        if not isinstance(slot["required"], bool) or not isinstance(slot["items_required"], bool):
            return False
        if not _is_settings_structure(slot["settings"]):
            return False
    return True


def _is_layer_structure(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != {"properties", "required", "slots", "layer_settings"}:
        return False
    return (
        _is_string_list(value["properties"])
        and _is_string_list(value["required"])
        and _is_slots_structure(value["slots"])
        and _is_settings_structure(value["layer_settings"])
    )


def _is_visualization_structure(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != {"properties", "required", "slots", "chart_settings", "layers"}:
        return False
    layers = value["layers"]
    return (
        _is_string_list(value["properties"])
        and _is_string_list(value["required"])
        and _is_slots_structure(value["slots"])
        and _is_settings_structure(value["chart_settings"])
        and isinstance(layers, Mapping)
        and all(isinstance(name, str) and _is_layer_structure(layer) for name, layer in layers.items())
    )


def validate_wizard_generated_contract(dto_module: object | None = None) -> WizardGeneratedContract:
    module = generated_dto if dto_module is None else dto_module
    registry = getattr(module, "WIZARD_VISUALIZATION_STRUCTURE", None)
    if not isinstance(registry, Mapping):
        raise DataLensConfigurationError("Generated Wizard visualization registry is missing or invalid.")
    for visualization_type, raw in registry.items():
        if not isinstance(visualization_type, str) or not _is_visualization_structure(raw):
            raise DataLensConfigurationError(
                f"Generated Wizard structure for visualization {visualization_type!r} is invalid."
            )
    typed_registry = cast(WizardVisualizationRegistry, registry)
    if typed_registry:
        _assert_encoding_owned_setting_keys_are_generated(typed_registry)

    fingerprint = getattr(module, "WIZARD_SCHEMA_FINGERPRINT", None)
    if typed_registry:
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise DataLensConfigurationError("Generated Wizard schema fingerprint is missing or invalid.")
    elif fingerprint is not None:
        raise DataLensConfigurationError(
            "Generated Wizard schema fingerprint must be absent when the visualization registry is empty."
        )

    field_structure = getattr(module, "WIZARD_FIELD_STRUCTURE", None)
    expected_field_keys = {"direct_properties", "update_properties", "nullable_update_properties"}
    if not isinstance(field_structure, Mapping) or set(field_structure) != expected_field_keys:
        raise DataLensConfigurationError("Generated Wizard field structure is missing or invalid.")
    if any(
        not isinstance(values, tuple) or not all(isinstance(value, str) for value in values)
        for values in field_structure.values()
    ):
        raise DataLensConfigurationError("Generated Wizard field structure is missing or invalid.")
    if not set(field_structure["nullable_update_properties"]) <= set(field_structure["update_properties"]):
        raise DataLensConfigurationError(
            "Generated Wizard nullable update-field properties must be a subset of update-field properties."
        )
    if not typed_registry and any(field_structure.values()):
        raise DataLensConfigurationError(
            "Generated Wizard field structure must be empty when the visualization registry is empty."
        )

    create_dto = getattr(module, "WizardChartCreateDTO", None)
    update_dto = getattr(module, "WizardChartUpdateDTO", None)
    read_dto = getattr(module, "WizardChartReadDTO", None)
    if not callable(create_dto) or not callable(update_dto):
        raise DataLensConfigurationError("Generated Wizard DTO factories are missing or invalid.")
    if read_dto is None or not callable(getattr(read_dto, "model_validate", None)):
        raise DataLensConfigurationError("Generated Wizard read DTO factory is missing or invalid.")
    return WizardGeneratedContract(
        schema_fingerprint=fingerprint,
        visualization_structure=typed_registry,
        field_structure=cast(WizardFieldStructure, field_structure),
        create_dto=cast(WizardChartCreateDTOClass, create_dto),
        update_dto=cast(WizardChartUpdateDTOClass, update_dto),
        read_dto=cast(WizardChartReadDTOClass, read_dto),
    )


def _generated_contract(
    source: WizardChartDtoModule | WizardGeneratedContract | None,
) -> WizardGeneratedContract:
    return source if isinstance(source, WizardGeneratedContract) else validate_wizard_generated_contract(source)


class WizardChartConverter:
    @staticmethod
    def from_domain_create(
        spec: WizardChartCreateSpec,
        *,
        dto_module: WizardChartDtoModule | WizardGeneratedContract | None = None,
    ) -> WizardChartCreateDTOProtocol:
        generated = _generated_contract(dto_module)
        generated.require_available()
        data = _assemble_wizard_data(
            spec,
            visualization_structure=generated.visualization_structure,
            field_structure=generated.field_structure,
        )
        key = key_from_location(spec.location, name=spec.name)
        annotation: dict[str, object] | None = None
        if spec.description:
            annotation = {"description": spec.description}
        return generated.create_dto(
            data=data,
            key=key,
            name=None if key else spec.name,
            workbook_id=workbook_id_from_location(spec.location),
            annotation=annotation,
        )

    @staticmethod
    def from_domain_update(
        update: WizardChartUpdate,
        *,
        dto_module: WizardChartDtoModule | WizardGeneratedContract | None = None,
    ) -> WizardChartUpdateDTOProtocol:
        generated = _generated_contract(dto_module)
        generated.require_available()
        chart = update.chart
        data: WizardJsonObject = copy.deepcopy(normalize_json_object(chart.data, context="Wizard V1 update snapshot"))
        _refuse_orphaning_publish(update)
        _apply_update_operations(
            data,
            update,
            visualization_structure=generated.visualization_structure,
            field_structure=generated.field_structure,
        )
        annotation = {"description": update.description_value} if update.description_value is not None else None
        return generated.update_dto(
            chart_id=cast(str, chart.id),
            mode=update.mode_value,
            data=data,
            annotation=annotation,
        )

    @staticmethod
    def from_domain_publish_revision(
        chart: WizardChart,
        *,
        rev_id: str,
        dto_module: WizardChartDtoModule | WizardGeneratedContract | None = None,
    ) -> WizardChartUpdateDTOProtocol:
        """Publish an existing Wizard revision without creating a new one."""
        if not chart.id:
            raise DataLensValidationError("Cannot publish a Wizard chart without an id")
        if not rev_id:
            raise DataLensValidationError("rev_id must be a non-empty string")
        generated = _generated_contract(dto_module)
        generated.require_available()
        data = copy.deepcopy(normalize_json_object(chart.data, context="Wizard V1 publish snapshot"))
        raw_annotation = chart.raw.get("annotation")
        annotation = (
            normalize_json_object(raw_annotation, context="Wizard V1 publish annotation")
            if isinstance(raw_annotation, Mapping)
            else None
        )
        return generated.update_dto(
            chart_id=chart.id,
            mode="publish",
            data=data,
            annotation=annotation,
            rev_id=rev_id,
        )

    @staticmethod
    def from_raw_create(
        spec: RawCreateSpec,
        *,
        source: ChartSnapshotView,
    ) -> RawWizardChartCreateEnvelope:
        key = key_from_location(spec.location, name=spec.name)
        return RawWizardChartCreateEnvelope(
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
    ) -> RawWizardChartReplaceEnvelope:
        if source.wire_type != target_wire_type:
            raise DataLensValidationError(
                f"Wizard chart wire type mismatch: source is {source.wire_type!r}, target is {target_wire_type!r}"
            )
        return RawWizardChartReplaceEnvelope(
            chart_id=spec.target_id,
            mode=mode,
            data=source.data,
            annotation=source.optional_object("annotation"),
            rev_id=spec.target_revision_id,
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | WizardChartReadDTOProtocol,
        *,
        installation: str,
        operations: ChartOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        visualization_id_fallback: str | None = None,
        wire_type_fallback: str | None = None,
        dto_module: WizardChartDtoModule | WizardGeneratedContract | None = None,
    ) -> WizardChart:
        generated = _generated_contract(dto_module)
        generated.require_available()
        response_snapshot: dict[str, JsonValue] = {}
        response: Mapping[str, object]
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="Wizard chart API response")
            read_dto = generated.read_dto.model_validate(response_snapshot)
            response = normalize_json_object(
                response_snapshot,
                context="Wizard chart typed response state",
            )
        else:
            read_dto = raw
            response = read_dto.raw or {}
            response_snapshot = normalize_json_object(response, context="Wizard chart API response")
        entry_value = response.get("entry")
        if not isinstance(entry_value, Mapping):
            raise DataLensValidationError("Wizard API v3 response requires an entry object")
        entry = normalize_json_object(entry_value, context="Wizard chart entry")
        data = normalize_json_object(read_dto.entry.data, context="Wizard V1 config")
        visualization_value = data.get("visualization")
        visualization = visualization_value if isinstance(visualization_value, dict) else {}
        existing_viz_id = _optional_str(visualization.get("type"))
        if visualization_id_fallback and not existing_viz_id:
            enriched_visualization = dict(visualization)
            enriched_visualization["type"] = visualization_id_fallback
            data = dict(data)
            data["visualization"] = enriched_visualization
        wire_type = _optional_str(entry.get("type")) or read_dto.entry.type or wire_type_fallback
        key = _optional_str(entry.get("key"))
        domain_location = resolve_entry_location_from_api_fields(
            dir_path=_optional_str(entry.get("dir_path")),
            key=key,
            collection_id=_optional_str(entry.get("collection_id")) or _optional_str(entry.get("collectionId")),
            workbook_id=_optional_str(entry.get("workbook_id")) or _optional_str(entry.get("workbookId")),
            fallback=location,
        )
        return WizardChart(
            id=read_dto.entry.entry_id,
            installation=installation,
            name=_optional_str(entry.get("name")) or name_from_key(key) or name,
            location=domain_location,
            wire_type=wire_type,
            data=data,
            raw=entry,
            response_snapshot=response_snapshot,
            _operations=operations,
        )
