from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_state import EntryStateRecord


class EntryStateArgsDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class EntryStateArgsDTOClass(Protocol):
    def model_validate(self, obj: object) -> EntryStateArgsDTOProtocol: ...


class GetStateResultDTOProtocol(Protocol):
    entry_id: str
    hash: str
    data: Mapping[str, object] | None
    created_at: str


class GetStateResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> GetStateResultDTOProtocol: ...


class CreateStateResultDTOProtocol(Protocol):
    hash: str


class CreateStateResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> CreateStateResultDTOProtocol: ...


class EntryStateDtoModule(Protocol):
    GetStateArgsDTO: EntryStateArgsDTOClass
    GetStateResultDTO: GetStateResultDTOClass
    CreateStateArgsDTO: EntryStateArgsDTOClass
    CreateStateResultDTO: CreateStateResultDTOClass


def resolve_dto_module(dto_module: EntryStateDtoModule | None) -> EntryStateDtoModule:
    return cast(EntryStateDtoModule, generated_dto if dto_module is None else dto_module)


def parse_created_at(value: str) -> datetime | None:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


class EntryStateConverter:
    @staticmethod
    def get_payload(
        entry_id: str,
        hash: str,
        *,
        dto_module: EntryStateDtoModule | None = None,
    ) -> dict[str, object]:
        generated = resolve_dto_module(dto_module)
        return generated.GetStateArgsDTO.model_validate({"entryId": entry_id, "hash": hash}).to_payload()

    @staticmethod
    def create_payload(
        entry_id: str,
        data: Mapping[str, object],
        *,
        dto_module: EntryStateDtoModule | None = None,
    ) -> dict[str, object]:
        generated = resolve_dto_module(dto_module)
        return generated.CreateStateArgsDTO.model_validate({"entryId": entry_id, "data": dict(data)}).to_payload()

    @staticmethod
    def to_record(
        response: Mapping[str, object],
        *,
        dto_module: EntryStateDtoModule | None = None,
    ) -> EntryStateRecord:
        result = resolve_dto_module(dto_module).GetStateResultDTO.model_validate(response)
        return EntryStateRecord(
            entry_id=result.entry_id,
            hash=result.hash,
            data=result.data,
            created_at=parse_created_at(result.created_at),
        )

    @staticmethod
    def hash_from_create(
        response: Mapping[str, object],
        *,
        dto_module: EntryStateDtoModule | None = None,
    ) -> str:
        return resolve_dto_module(dto_module).CreateStateResultDTO.model_validate(response).hash
