from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.domain.entry_location import key_from_location
from datalens_sdk.domain.folder import Folder
from datalens_sdk.domain.ports import FolderOperations
from datalens_sdk.domain.specs.folder import FolderCreateSpec, FolderUpdateSpec
from datalens_sdk.errors import DataLensValidationError


class FolderWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class FolderReadDTOProtocol(Protocol):
    id: str
    name: str | None
    key: str
    scope: str
    created_by: str | None
    created_at: str | None
    updated_by: str | None
    updated_at: str | None
    hidden: bool
    meta: Mapping[str, object] | None
    raw: dict[str, object]


class FolderGetResultDTOProtocol(Protocol):
    entries: tuple[FolderReadDTOProtocol, ...]


class FolderCreateDTOClass(Protocol):
    def __call__(self, *, key: str) -> FolderWriteDTOProtocol: ...


class FolderReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> FolderReadDTOProtocol: ...


class FolderGetResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> FolderGetResultDTOProtocol: ...


class FolderUpdateDTOClass(Protocol):
    def __call__(self, *, id: str, name: str) -> FolderWriteDTOProtocol: ...


class FolderDtoModule(Protocol):
    FolderCreateDTO: FolderCreateDTOClass
    FolderReadDTO: FolderReadDTOClass
    FolderGetResultDTO: FolderGetResultDTOClass
    FolderUpdateDTO: FolderUpdateDTOClass


def _dto_module(dto_module: FolderDtoModule | None) -> FolderDtoModule:
    return cast(FolderDtoModule, generated_dto if dto_module is None else dto_module)


class FolderConverter:
    @staticmethod
    def from_domain_create(
        spec: FolderCreateSpec,
        *,
        dto_module: FolderDtoModule | None = None,
    ) -> FolderWriteDTOProtocol:
        generated = _dto_module(dto_module)
        key = key_from_location(spec.location, name=spec.name)
        if key is None:
            raise DataLensValidationError("Folder creation requires a path location")
        return generated.FolderCreateDTO(key=key)

    @staticmethod
    def from_domain_update(
        spec: FolderUpdateSpec,
        *,
        dto_module: FolderDtoModule | None = None,
    ) -> FolderWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.FolderUpdateDTO(id=spec.folder_id, name=spec.name)

    @staticmethod
    def read_result(
        raw: Mapping[str, object],
        *,
        dto_module: FolderDtoModule | None = None,
    ) -> tuple[FolderReadDTOProtocol, ...]:
        generated = _dto_module(dto_module)
        return generated.FolderGetResultDTO.model_validate(raw).entries

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | FolderReadDTOProtocol,
        *,
        installation: str,
        operations: FolderOperations | None = None,
        dto_module: FolderDtoModule | None = None,
    ) -> Folder:
        generated = _dto_module(dto_module)
        read_dto = generated.FolderReadDTO.model_validate(raw) if isinstance(raw, Mapping) else raw
        name = read_dto.name or name_from_key(read_dto.key)
        if not name:
            raise DataLensValidationError("Folder response does not contain a name")
        return Folder(
            id=read_dto.id,
            name=name,
            key=read_dto.key,
            installation=installation,
            scope=read_dto.scope,
            created_by=read_dto.created_by,
            created_at=read_dto.created_at,
            updated_by=read_dto.updated_by,
            updated_at=read_dto.updated_at,
            hidden=read_dto.hidden,
            meta=dict(read_dto.meta or {}),
            raw=read_dto.raw,
            _operations=operations,
        )
