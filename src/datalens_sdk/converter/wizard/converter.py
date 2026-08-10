from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter._utils import _optional_str, _read_response_id
from datalens_sdk.converter.raw.chart import (
    RawWizardChartCreateEnvelope,
    RawWizardChartReplaceEnvelope,
)
from datalens_sdk.converter.wizard._assemble import _assemble_wizard_data
from datalens_sdk.converter.wizard._common import _dict_with_string_keys
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
from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.serialization.artifacts import ChartSnapshotView
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object

_WIZARD_ID_KEYS: tuple[str, ...] = ("entryId", "entry_id", "id", "chartId", "chart_id")


class WizardChartCreateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class WizardChartUpdateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class WizardChartCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        template: str,
        data: Mapping[str, object],
        key: str | None = None,
        name: str | None = None,
        workbook_id: str | None = None,
        annotation: Mapping[str, object] | None = None,
    ) -> WizardChartCreateDTOProtocol: ...


class WizardChartUpdateDTOClass(Protocol):
    def __call__(
        self,
        *,
        entry_id: str,
        template: str,
        mode: str,
        data: Mapping[str, object],
        annotation: Mapping[str, object] | None = None,
    ) -> WizardChartUpdateDTOProtocol: ...


class WizardChartReadDTOProtocol(Protocol):
    entry_id: str | None
    data: dict[str, object] | None
    raw: dict[str, object]


class WizardChartReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> WizardChartReadDTOProtocol: ...


class WizardChartDtoModule(Protocol):
    WizardChartCreateDTO: WizardChartCreateDTOClass
    WizardChartUpdateDTO: WizardChartUpdateDTOClass
    WizardChartReadDTO: WizardChartReadDTOClass


def _dto_module(dto_module: WizardChartDtoModule | None) -> WizardChartDtoModule:
    return cast(WizardChartDtoModule, generated_dto if dto_module is None else dto_module)


class WizardChartConverter:
    @staticmethod
    def from_domain_create(
        spec: WizardChartCreateSpec,
        *,
        dto_module: WizardChartDtoModule | None = None,
    ) -> WizardChartCreateDTOProtocol:
        generated = _dto_module(dto_module)
        data = _assemble_wizard_data(spec)
        key = key_from_location(spec.location, name=spec.name)
        annotation: dict[str, object] | None = None
        if spec.description:
            annotation = {"description": spec.description}
        return generated.WizardChartCreateDTO(
            template="datalens",
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
        dto_module: WizardChartDtoModule | None = None,
    ) -> WizardChartUpdateDTOProtocol:
        generated = _dto_module(dto_module)
        chart = update.chart
        data = copy.deepcopy(dict(chart.data))
        _refuse_orphaning_publish(update)
        _apply_update_operations(data, update)
        annotation = {"description": update.description_value} if update.description_value else None
        return generated.WizardChartUpdateDTO(
            entry_id=cast(str, chart.id),
            template="datalens",
            mode=update.mode_value,
            data=data,
            annotation=annotation,
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
            entry_id=spec.target_id,
            mode=mode,
            data=source.data,
            annotation=source.optional_object("annotation"),
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | WizardChartReadDTOProtocol,
        *,
        installation: str,
        operations: ChartOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        id_fallback: str | None = None,
        visualization_id_fallback: str | None = None,
        wire_type_fallback: str | None = None,
        dto_module: WizardChartDtoModule | None = None,
    ) -> WizardChart:
        generated = _dto_module(dto_module)
        response_snapshot: dict[str, JsonValue] = {}
        response: Mapping[str, object]
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="Wizard chart API response")
            dto_validation_input = dict(response_snapshot)
            dto_validation_input["raw"] = normalize_json_object(
                response_snapshot,
                context="Wizard chart typed response state",
            )
            read_dto = generated.WizardChartReadDTO.model_validate(dto_validation_input)
            response = normalize_json_object(
                response_snapshot,
                context="Wizard chart typed response state",
            )
        else:
            read_dto = raw
            response = read_dto.raw or {}
        data = read_dto.data if read_dto.data is not None else _dict_with_string_keys(response.get("data"))
        data = _dict_with_string_keys(data)
        visualization = _dict_with_string_keys(data.get("visualization"))
        existing_viz_id = _optional_str(visualization.get("id"))
        if visualization_id_fallback and not existing_viz_id:
            enriched_visualization = dict(visualization)
            enriched_visualization["id"] = visualization_id_fallback
            data = dict(data)
            data["visualization"] = enriched_visualization
        wire_type = _optional_str(response.get("type")) or wire_type_fallback
        key = _optional_str(response.get("key"))
        domain_location = resolve_entry_location_from_api_fields(
            dir_path=_optional_str(response.get("dir_path")),
            key=key,
            collection_id=_optional_str(response.get("collection_id")) or _optional_str(response.get("collectionId")),
            workbook_id=_optional_str(response.get("workbook_id")) or _optional_str(response.get("workbookId")),
            fallback=location,
        )
        return WizardChart(
            id=read_dto.entry_id or _read_response_id(response, keys=_WIZARD_ID_KEYS) or id_fallback,
            installation=installation,
            name=_optional_str(response.get("name")) or name_from_key(key) or name,
            location=domain_location,
            wire_type=wire_type,
            data=data,
            raw=response,
            response_snapshot=response_snapshot,
            _operations=operations,
        )
