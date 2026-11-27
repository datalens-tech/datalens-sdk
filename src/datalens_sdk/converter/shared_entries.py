from __future__ import annotations

from typing import Protocol, cast

from pydantic import BaseModel

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.shared_entries import (
    SharedEntryBinding,
    SharedEntryBindingEntry,
    SharedEntryBindingEntryPermissions,
    SharedEntryBindingItem,
    SharedEntryBindingWorkbook,
    SharedEntryBindingWorkbookPermissions,
)


class SharedEntriesDtoModule(Protocol):
    SharedEntryBindingArgsDTO: type[BaseModel]
    SharedEntryBindingPairDTO: type[BaseModel]
    GetSharedEntryDelegationArgsDTO: type[BaseModel]
    GetSharedEntryBindingsArgsDTO: type[BaseModel]
    SharedEntryBindingReadDTO: type[BaseModel]
    GetSharedEntryBindingsResultReadDTO: type[BaseModel]


class SharedEntryConverter:
    def __init__(self, dto_module: SharedEntriesDtoModule | None = None) -> None:
        self._dto = cast(SharedEntriesDtoModule, generated_dto if dto_module is None else dto_module)

    def binding_args(self, *, source_id: str, target_id: str, delegation: bool) -> dict[str, object]:
        dto = self._dto.SharedEntryBindingArgsDTO(source_id=source_id, target_id=target_id, delegation=delegation)
        return dto.model_dump(by_alias=True)

    def pair_args(self, *, source_id: str, target_id: str) -> dict[str, object]:
        dto = self._dto.SharedEntryBindingPairDTO(source_id=source_id, target_id=target_id)
        return dto.model_dump(by_alias=True)

    def delegation_args(self, *, source_id: str, target_id: str, binded_workbook_id: str | None) -> dict[str, object]:
        fields: dict[str, object] = {"source_id": source_id, "target_id": target_id}
        if binded_workbook_id is not None:
            fields["binded_workbook_id"] = binded_workbook_id
        return self._dto.GetSharedEntryDelegationArgsDTO(**fields).model_dump(by_alias=True, exclude_none=True)

    def list_args(
        self,
        *,
        entry_id: str,
        entry_as: str,
        mode: str,
        filter_string: str | None,
        page: int,
        page_size: int,
        include_permissions_info: bool,
    ) -> dict[str, object]:
        fields: dict[str, object] = {
            "entry_id": entry_id,
            "entry_as": entry_as,
            "mode": mode,
            "page": page,
            "page_size": page_size,
            "include_permissions_info": include_permissions_info,
        }
        if filter_string is not None:
            fields["filter_string"] = filter_string
        return self._dto.GetSharedEntryBindingsArgsDTO(**fields).model_dump(by_alias=True, exclude_none=True)

    def binding(self, raw: dict[str, object]) -> SharedEntryBinding:
        value = cast(generated_dto.SharedEntryBindingReadDTO, self._dto.SharedEntryBindingReadDTO.model_validate(raw))
        return SharedEntryBinding(value.source_id, value.target_id, value.is_delegated)

    def list_result(self, raw: dict[str, object]) -> tuple[tuple[SharedEntryBindingItem, ...], str | None]:
        result = cast(
            generated_dto.GetSharedEntryBindingsResultReadDTO,
            self._dto.GetSharedEntryBindingsResultReadDTO.model_validate(raw),
        )
        items: list[SharedEntryBindingItem] = []
        for item in result.items:
            if item.entity == "entry":
                items.append(
                    SharedEntryBindingEntry(
                        item.entry_id,
                        item.scope,
                        item.type,
                        item.is_delegated,
                        item.collection_title,
                        item.collection_id,
                        item.workbook_id,
                        item.key,
                        item.display_key,
                        SharedEntryBindingEntryPermissions(**item.permissions.model_dump())
                        if item.permissions is not None
                        else None,
                    )
                )
            else:
                items.append(
                    SharedEntryBindingWorkbook(
                        item.workbook_id,
                        item.title,
                        item.is_delegated,
                        item.collection_title,
                        item.collection_id,
                        SharedEntryBindingWorkbookPermissions(**item.permissions.model_dump())
                        if item.permissions is not None
                        else None,
                    )
                )
        return tuple(items), result.next_page_token
