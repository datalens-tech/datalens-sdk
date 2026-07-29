from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from datalens_sdk.api.entries import EntriesService
from datalens_sdk.converter.folder import FolderConverter, FolderDtoModule, FolderReadDTOProtocol
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.folder import Folder, FolderCreate, FolderUpdate
from datalens_sdk.domain.navigation import (
    DirectoryListOptions,
    DirectoryPager,
    EntrySummary,
    GetEntriesOptions,
)
from datalens_sdk.domain.ports import FolderOperations, NavigationOperations
from datalens_sdk.errors import (
    APIErrorContext,
    DatalensValidationError,
    NotFoundError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import HTTPClientProtocol


class FolderAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def _post_object(self, path: str, body: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(path, body)

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post_object("/rpc/createFolder", payload)

    def delete(self, folder_id: str) -> None:
        self._post_object("/rpc/deleteFolder", {"folderId": folder_id})


class FolderService(FolderOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: FolderAPI,
        entries_service: EntriesService,
        navigation_operations: NavigationOperations,
        dto_module: FolderDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._entries_service = entries_service
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    def _to_domain(
        self,
        raw: Mapping[str, object] | FolderReadDTOProtocol,
        *,
        operation: str,
    ) -> Folder:
        try:
            folder = FolderConverter.to_domain(
                raw,
                installation=self._installation,
                operations=self,
                dto_module=self._dto_module,
            )
        except (ValidationError, DatalensValidationError) as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
        if folder.scope != "folder":
            raise translate_invalid_response_error(operation=operation, reason="entry scope is not 'folder'")
        return folder

    def create_folder(self, builder: FolderCreate) -> Folder:
        spec = builder.to_spec()
        try:
            dto = FolderConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createFolder", reason=str(exc)) from exc
        return self._to_domain(self._api.create(dto.to_payload()), operation="createFolder")

    def _read_folders(
        self,
        entries: Sequence[Mapping[str, object]],
        *,
        operation: str,
    ) -> tuple[FolderReadDTOProtocol, ...]:
        try:
            return FolderConverter.read_result({"entries": entries}, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc

    def _get_folder_by_id(self, folder_id: str) -> Folder:
        summaries = self._navigation_operations.get_entries(
            GetEntriesOptions(ids=(folder_id,), scope="folder", page_size=1)
        )
        folders = self._read_folders(
            [summary.raw for summary in summaries],
            operation="getEntries",
        )
        if not folders:
            raise NotFoundError(
                APIErrorContext(
                    status_code=404,
                    code="ERR.DATALENS_SDK.NOT_FOUND",
                    message=f"Folder {folder_id!r} was not found",
                )
            )
        if len(folders) != 1:
            raise translate_invalid_response_error(operation="getEntries", reason="expected exactly one entry")
        return self._to_domain(folders[0], operation="getEntries")

    def get_folder(self, path: str) -> Folder:
        normalized_path = path.strip("/")
        if not normalized_path:
            raise DatalensValidationError("path must identify a folder")
        if "/" in normalized_path:
            parent_path, name = normalized_path.rsplit("/", 1)
        else:
            parent_path, name = "", normalized_path
        directory_path = f"{parent_path}/"
        summaries = self._navigation_operations.list_folder_entries(
            directory_path,
            DirectoryListOptions(name=name, page_size=200),
        )
        folders = self._read_folders(
            [summary.raw for summary in summaries],
            operation="listDirectory",
        )
        matches = [folder for folder in folders if folder.key.strip("/").casefold() == normalized_path.casefold()]
        if not matches:
            raise NotFoundError(
                APIErrorContext(
                    status_code=404,
                    code="ERR.DATALENS_SDK.NOT_FOUND",
                    message=f"Folder {path!r} was not found",
                )
            )
        if len(matches) != 1:
            raise translate_invalid_response_error(operation="listDirectory", reason="expected exactly one folder")
        return self._to_domain(matches[0], operation="listDirectory")

    def update_folder(self, builder: FolderUpdate) -> Folder:
        spec = builder.to_spec()
        self._entries_service.rename_entry(entry_id=spec.folder_id, name=spec.name)
        return self._get_folder_by_id(spec.folder_id)

    def delete_folder(self, folder_id: str) -> None:
        self._api.delete(folder_id)

    def move_folder(
        self,
        folder: Folder,
        location: EntryLocation,
        *,
        name: str | None = None,
    ) -> Folder:
        if not folder.id:
            raise DatalensValidationError("Cannot move a folder without an id")
        self._navigation_operations.move_folder_entry(entry_id=folder.id, location=location, name=name)
        return self._get_folder_by_id(folder.id)

    def list_folder_entries(
        self,
        path: str,
        options: DirectoryListOptions,
    ) -> DirectoryPager[EntrySummary]:
        return self._navigation_operations.list_folder_entries(path, options)
