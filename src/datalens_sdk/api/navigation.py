from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.api.collection import CollectionAPI
from datalens_sdk.api.entries import EntriesAPI, EntriesDtoModule, EntriesService
from datalens_sdk.api.workbook import WorkbookAPI
from datalens_sdk.converter.entry import EntryMutationConverter
from datalens_sdk.converter.navigation import NavigationConverter
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import (
    CollectionListOptions,
    DirectoryListOptions,
    DirectoryPage,
    DirectoryPager,
    EntryRelation,
    EntrySummary,
    GetEntriesOptions,
    Page,
    Pager,
    RelationOptions,
    StructureSummary,
    WorkbookListOptions,
)
from datalens_sdk.domain.ports import NavigationOperations
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error


class NavigationService(NavigationOperations):
    def __init__(
        self,
        *,
        entries_api: EntriesAPI,
        entries_service: EntriesService,
        collection_api: CollectionAPI,
        workbook_api: WorkbookAPI,
        dto_module: EntriesDtoModule | None = None,
    ) -> None:
        self._entries_api = entries_api
        self._entries_service = entries_service
        self._collection_api = collection_api
        self._workbook_api = workbook_api
        self._dto_module = dto_module

    def get_entries(self, options: GetEntriesOptions) -> Pager[EntrySummary]:
        def load() -> Iterator[Page[EntrySummary]]:
            page_token: str | None = None
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = NavigationConverter.get_entries_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    )
                    items, next_token = NavigationConverter.get_entries_result(
                        self._entries_api.get(payload),
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="getEntries", reason=str(exc)) from exc
                yield Page(items=items, next_page_token=next_token)
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="getEntries",
                        reason="pagination returned a repeated nextPageToken",
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)

    def list_folder_entries(
        self,
        path: str,
        options: DirectoryListOptions,
    ) -> DirectoryPager[EntrySummary]:
        def load() -> Iterator[DirectoryPage[EntrySummary]]:
            page = 0
            while True:
                try:
                    payload = NavigationConverter.directory_payload(
                        path,
                        options,
                        page=page,
                        dto_module=self._dto_module,
                    )
                    items, breadcrumbs, has_next_page = NavigationConverter.directory_result(
                        self._entries_api.list_directory(payload),
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listDirectory", reason=str(exc)) from exc
                next_token = str(page + 1) if has_next_page else None
                yield DirectoryPage(
                    items=items,
                    next_page_token=next_token,
                    breadcrumbs=breadcrumbs,
                )
                if not has_next_page:
                    return
                page += 1

        return DirectoryPager(load)

    def move_folder_entry(
        self,
        *,
        entry_id: str,
        location: EntryLocation,
        name: str | None = None,
    ) -> None:
        try:
            dto = EntryMutationConverter.from_domain_move(
                entry_id=entry_id,
                location=location,
                name=name,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="moveFolderEntry", reason=str(exc)) from exc
        self._entries_api.move(dto.to_payload())

    def list_collection_entries(
        self,
        collection_id: str,
        options: CollectionListOptions,
    ) -> Pager[StructureSummary]:
        def load() -> Iterator[Page[StructureSummary]]:
            page_token: str | None = None
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = NavigationConverter.collection_payload(
                        collection_id,
                        options,
                        page=page_token,
                        dto_module=self._dto_module,
                    )
                    items, next_token = NavigationConverter.collection_result(
                        self._collection_api.get_content(payload),
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="getCollectionContent", reason=str(exc)) from exc
                yield Page(items=items, next_page_token=next_token)
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="getCollectionContent",
                        reason="pagination returned a repeated nextPageToken",
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)

    def list_workbook_entries(
        self,
        workbook_id: str,
        options: WorkbookListOptions,
    ) -> Pager[EntrySummary]:
        def load() -> Iterator[Page[EntrySummary]]:
            page = 0
            while True:
                try:
                    payload = NavigationConverter.workbook_payload(
                        workbook_id,
                        options,
                        page=page,
                        dto_module=self._dto_module,
                    )
                    items, next_token = NavigationConverter.workbook_result(
                        self._workbook_api.get_entries(payload),
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="getWorkbookEntries", reason=str(exc)) from exc
                yield Page(items=items, next_page_token=next_token)
                if not next_token:
                    return
                page += 1

        return Pager(load)

    def get_entry_relations(
        self,
        entry_id: str,
        options: RelationOptions,
    ) -> Pager[EntryRelation]:
        return self._entries_service.get_entry_relations(entry_id, options)
