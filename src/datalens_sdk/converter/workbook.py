from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_location import EntryLocation, collection_id_from_location
from datalens_sdk.domain.ports import WorkbookOperations
from datalens_sdk.domain.specs.workbook import WorkbookCreateSpec, WorkbookUpdateSpec
from datalens_sdk.domain.workbook import Workbook, WorkbookStatus
from datalens_sdk.errors import DataLensValidationError


class WorkbookWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class WorkbookReadDTOProtocol(Protocol):
    id: str
    name: str
    description: str | None
    collection_id: str | None
    status: str | None
    tenant_id: str | None
    created_by: str | None
    created_at: str | None
    updated_by: str | None
    updated_at: str | None
    meta: Mapping[str, object] | None
    permissions: Mapping[str, object] | None
    raw: dict[str, object]


class WorkbookCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        name: str,
        collection_id: str | None,
        description: str | None,
    ) -> WorkbookWriteDTOProtocol: ...


class WorkbookReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> WorkbookReadDTOProtocol: ...


class WorkbookUpdateDTOClass(Protocol):
    def __call__(
        self,
        *,
        id: str,
        name: str | None,
        description: str | None,
    ) -> WorkbookWriteDTOProtocol: ...


class WorkbookMoveDTOClass(Protocol):
    def __call__(
        self,
        *,
        id: str,
        collection_id: str | None,
        name: str | None,
    ) -> WorkbookWriteDTOProtocol: ...


class WorkbookDtoModule(Protocol):
    WorkbookCreateDTO: WorkbookCreateDTOClass
    WorkbookMoveDTO: WorkbookMoveDTOClass
    WorkbookReadDTO: WorkbookReadDTOClass
    WorkbookUpdateDTO: WorkbookUpdateDTOClass


def _dto_module(dto_module: WorkbookDtoModule | None) -> WorkbookDtoModule:
    return cast(WorkbookDtoModule, generated_dto if dto_module is None else dto_module)


def _workbook_status(value: str | None) -> WorkbookStatus | None:
    if value in {"creating", "deleting", "active", "deleted"}:
        return cast(WorkbookStatus, value)
    return None


class WorkbookConverter:
    @staticmethod
    def from_domain_create(
        spec: WorkbookCreateSpec,
        *,
        dto_module: WorkbookDtoModule | None = None,
    ) -> WorkbookWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.WorkbookCreateDTO(
            name=spec.name,
            collection_id=collection_id_from_location(spec.collection),
            description=spec.description,
        )

    @staticmethod
    def from_domain_update(
        spec: WorkbookUpdateSpec,
        *,
        dto_module: WorkbookDtoModule | None = None,
    ) -> WorkbookWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.WorkbookUpdateDTO(
            id=spec.workbook_id,
            name=spec.changes.get("name"),
            description=spec.changes.get("description"),
        )

    @staticmethod
    def from_domain_move(
        workbook: Workbook,
        location: EntryLocation | None,
        *,
        name: str | None = None,
        dto_module: WorkbookDtoModule | None = None,
    ) -> WorkbookWriteDTOProtocol:
        if not workbook.id:
            raise DataLensValidationError("Cannot move a workbook without an id")
        generated = _dto_module(dto_module)
        return generated.WorkbookMoveDTO(
            id=workbook.id,
            collection_id=collection_id_from_location(location),
            name=name,
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | WorkbookReadDTOProtocol,
        *,
        installation: str,
        operations: WorkbookOperations | None = None,
        dto_module: WorkbookDtoModule | None = None,
    ) -> Workbook:
        generated = _dto_module(dto_module)
        read_dto = generated.WorkbookReadDTO.model_validate(raw) if isinstance(raw, Mapping) else raw
        return Workbook(
            id=read_dto.id,
            name=read_dto.name,
            installation=installation,
            description=read_dto.description,
            collection_id=read_dto.collection_id,
            status=_workbook_status(read_dto.status),
            tenant_id=read_dto.tenant_id,
            created_by=read_dto.created_by,
            created_at=read_dto.created_at,
            updated_by=read_dto.updated_by,
            updated_at=read_dto.updated_at,
            meta=dict(read_dto.meta or {}),
            permissions=dict(read_dto.permissions or {}),
            raw=read_dto.raw,
            _operations=operations,
        )
