from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_location import EntryLocation, dir_path_from_location
from datalens_sdk.domain.navigation import EntryMoveResult
from datalens_sdk.errors import DataLensValidationError, translate_invalid_response_error


class EntryMutationWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class EntryMoveDTOClass(Protocol):
    def __call__(
        self,
        *,
        entry_id: str,
        destination: str,
        name: str | None,
    ) -> EntryMutationWriteDTOProtocol: ...


class EntryRenameDTOClass(Protocol):
    def __call__(self, *, entry_id: str, name: str) -> EntryMutationWriteDTOProtocol: ...


class MoveEntryResultEntryReadDTOProtocol(Protocol):
    id: str
    key: str
    scope: str
    type: str


class MoveEntryResultEntryReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> MoveEntryResultEntryReadDTOProtocol: ...


class EntryMutationDtoModule(Protocol):
    EntryMoveDTO: EntryMoveDTOClass
    MoveEntryResultEntryReadDTO: MoveEntryResultEntryReadDTOClass
    EntryRenameDTO: EntryRenameDTOClass


def _dto_module(dto_module: EntryMutationDtoModule | None) -> EntryMutationDtoModule:
    return cast(EntryMutationDtoModule, generated_dto if dto_module is None else dto_module)


class EntryMutationConverter:
    @staticmethod
    def from_domain_move(
        *,
        entry_id: str,
        location: EntryLocation,
        name: str | None = None,
        dto_module: EntryMutationDtoModule | None = None,
    ) -> EntryMutationWriteDTOProtocol:
        destination = dir_path_from_location(location)
        if destination is None:
            raise DataLensValidationError("Folder move requires a path location")
        generated = _dto_module(dto_module)
        return generated.EntryMoveDTO(entry_id=entry_id, destination=destination, name=name)

    @staticmethod
    def to_domain_move_result(
        raw: Sequence[Mapping[str, object]],
        *,
        dto_module: EntryMutationDtoModule | None = None,
    ) -> tuple[EntryMoveResult, ...]:
        generated = _dto_module(dto_module)
        result: list[EntryMoveResult] = []
        for entry in raw:
            item = generated.MoveEntryResultEntryReadDTO.model_validate(entry)
            if not isinstance(entry.get("entryId"), str):
                raise translate_invalid_response_error(
                    operation="moveFolderEntry",
                    reason="entry is missing a moved entry id",
                )
            result.append(
                EntryMoveResult(
                    id=item.id,
                    key=item.key,
                    scope=item.scope,
                    type=item.type,
                    raw=dict(entry),
                )
            )
        return tuple(result)

    @staticmethod
    def from_domain_rename(
        *,
        entry_id: str,
        name: str,
        dto_module: EntryMutationDtoModule | None = None,
    ) -> EntryMutationWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.EntryRenameDTO(entry_id=entry_id, name=name)
