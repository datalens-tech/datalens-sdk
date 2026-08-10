from __future__ import annotations

from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.entry_location import EntryLocation, dir_path_from_location
from datalens_sdk.errors import DataLensValidationError


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


class EntryMutationDtoModule(Protocol):
    EntryMoveDTO: EntryMoveDTOClass
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
    def from_domain_rename(
        *,
        entry_id: str,
        name: str,
        dto_module: EntryMutationDtoModule | None = None,
    ) -> EntryMutationWriteDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.EntryRenameDTO(entry_id=entry_id, name=name)
