from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.collection import Collection
from datalens_sdk.domain.entry_location import EntryLocation, collection_id_from_location
from datalens_sdk.domain.ports import CollectionOperations
from datalens_sdk.domain.specs.collection import CollectionCreateSpec, CollectionUpdateSpec
from datalens_sdk.errors import DataLensValidationError


class CollectionWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class CollectionReadDTOProtocol(Protocol):
    id: str
    name: str
    description: str | None
    parent_id: str | None
    tenant_id: str | None
    created_by: str | None
    created_at: str | None
    updated_by: str | None
    updated_at: str | None
    meta: Mapping[str, object] | None
    permissions: Mapping[str, object] | None
    raw: dict[str, object]


class CollectionCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        name: str,
        parent_id: str | None,
        description: str | None,
    ) -> CollectionWriteDTOProtocol: ...


class CollectionReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> CollectionReadDTOProtocol: ...


class CollectionUpdateDTOClass(Protocol):
    def __call__(
        self,
        *,
        id: str,
        name: str | None,
        description: str | None,
    ) -> CollectionWriteDTOProtocol: ...


class CollectionMoveDTOClass(Protocol):
    def __call__(
        self,
        *,
        id: str,
        parent_id: str | None,
        name: str | None,
    ) -> CollectionWriteDTOProtocol: ...


class CollectionDtoModule(Protocol):
    CollectionCreateDTO: CollectionCreateDTOClass
    CollectionMoveDTO: CollectionMoveDTOClass
    CollectionReadDTO: CollectionReadDTOClass
    CollectionUpdateDTO: CollectionUpdateDTOClass


def _dto_module(dto_module: CollectionDtoModule | None) -> CollectionDtoModule:
    return cast(CollectionDtoModule, generated_dto if dto_module is None else dto_module)


class CollectionConverter:
    @staticmethod
    def from_domain_create(
        spec: CollectionCreateSpec,
        *,
        dto_module: CollectionDtoModule | None = None,
    ) -> CollectionWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.CollectionCreateDTO(
            name=spec.name,
            parent_id=collection_id_from_location(spec.parent),
            description=spec.description,
        )

    @staticmethod
    def from_domain_update(
        spec: CollectionUpdateSpec,
        *,
        dto_module: CollectionDtoModule | None = None,
    ) -> CollectionWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.CollectionUpdateDTO(
            id=spec.collection_id,
            name=spec.changes.get("name"),
            description=spec.changes.get("description"),
        )

    @staticmethod
    def from_domain_move(
        collection: Collection,
        location: EntryLocation | None,
        *,
        name: str | None = None,
        dto_module: CollectionDtoModule | None = None,
    ) -> CollectionWriteDTOProtocol:
        if not collection.id:
            raise DataLensValidationError("Cannot move a collection without an id")
        generated = _dto_module(dto_module)
        return generated.CollectionMoveDTO(
            id=collection.id,
            parent_id=collection_id_from_location(location),
            name=name,
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | CollectionReadDTOProtocol,
        *,
        installation: str,
        operations: CollectionOperations | None = None,
        dto_module: CollectionDtoModule | None = None,
    ) -> Collection:
        generated = _dto_module(dto_module)
        read_dto = generated.CollectionReadDTO.model_validate(raw) if isinstance(raw, Mapping) else raw
        return Collection(
            id=read_dto.id,
            name=read_dto.name,
            installation=installation,
            description=read_dto.description,
            parent_id=read_dto.parent_id,
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
