from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Literal, TypeVar

from pydantic import ValidationError

from datalens_sdk.converter.permissions import (
    AccessBindingsConverter,
    DirectorySubjectsConverter,
    EffectivePermissionsConverter,
    PermissionsDtoModule,
)
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.permissions import (
    BulkPermissionsResult,
    DataLensOperation,
    DirectorySubject,
    DirectorySubjectType,
    EffectivePermissionError,
    EntryEffectivePermissionResult,
    RoleBindingDelta,
    RootCollectionPermissions,
    SubjectRoleAssignments,
)
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import (
    DEFAULT_RETRY_POLICY,
    TRANSIENT_RETRY_POLICY,
    HTTPClientProtocol,
)

_T = TypeVar("_T")


class PermissionsAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def _read(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(path, payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def _write(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(path, payload, retry_policy=DEFAULT_RETRY_POLICY)

    def list_workbook(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/listWorkbookAccessBindings", payload)

    def list_collection(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/listCollectionAccessBindings", payload)

    def list_shared_entry(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/listSharedEntryAccessBindings", payload)

    def modify_workbook(self, payload: dict[str, object]) -> dict[str, object]:
        return self._write("/rpc/updateWorkbookAccessBindings", payload)

    def modify_collection(self, payload: dict[str, object]) -> dict[str, object]:
        return self._write("/rpc/updateCollectionAccessBindings", payload)

    def get_entries(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/getEntriesPermissions", payload)

    def get_bulk(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/getPermissionsBulk", payload)

    def get_root_collection(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/getRootCollectionPermissions", payload)

    def list_subjects(self, payload: dict[str, object]) -> dict[str, object]:
        return self._read("/rpc/batchListMembers", payload)


def _payload(operation: str, build: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return build()
    except (ValueError, TypeError) as exc:
        raise DataLensValidationError(f"{operation}: {exc}") from exc


def _pages(
    operation: str,
    payload: dict[str, object],
    fetch_page: Callable[[dict[str, object]], dict[str, object]],
    convert: Callable[[object], tuple[tuple[_T, ...], str]],
) -> Pager[_T]:
    def load() -> Iterator[Page[_T]]:
        body = dict(payload)
        seen_tokens: set[str] = set()
        while True:
            response = fetch_page(body)
            try:
                items, token = convert(response)
            except ValidationError as exc:
                raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
            if token and token in seen_tokens:
                raise translate_invalid_response_error(
                    operation=operation, reason="pagination returned a repeated nextPageToken"
                )
            yield Page(items=items, next_page_token=token)
            if not token:
                return
            seen_tokens.add(token)
            body = {**payload, "pageToken": token}

    return Pager(load)


class PermissionsService:
    def __init__(self, *, api: PermissionsAPI, dto_module: PermissionsDtoModule | None = None) -> None:
        self._api = api
        self._dto_module = dto_module

    def _binding_page(self, raw: object) -> tuple[tuple[SubjectRoleAssignments, ...], str]:
        page = AccessBindingsConverter.list_result(raw, dto_module=self._dto_module)
        return page.subjects, page.next_page_token

    def list_workbook(
        self, *, workbook_id: str, include_inherited: bool | None = None, page_size: int | None = None
    ) -> Pager[SubjectRoleAssignments]:
        payload = _payload(
            "listWorkbookAccessBindings",
            lambda: AccessBindingsConverter.list_workbook_payload(
                workbook_id, include_inherited=include_inherited, page_size=page_size, dto_module=self._dto_module
            ),
        )
        return _pages("listWorkbookAccessBindings", payload, self._api.list_workbook, self._binding_page)

    def list_collection(
        self, *, collection_id: str, include_inherited: bool | None = None, page_size: int | None = None
    ) -> Pager[SubjectRoleAssignments]:
        payload = _payload(
            "listCollectionAccessBindings",
            lambda: AccessBindingsConverter.list_collection_payload(
                collection_id, include_inherited=include_inherited, page_size=page_size, dto_module=self._dto_module
            ),
        )
        return _pages("listCollectionAccessBindings", payload, self._api.list_collection, self._binding_page)

    def list_shared_entry(
        self, *, entry_id: str, include_inherited: bool | None = None, page_size: int | None = None
    ) -> Pager[SubjectRoleAssignments]:
        payload = _payload(
            "listSharedEntryAccessBindings",
            lambda: AccessBindingsConverter.list_shared_entry_payload(
                entry_id, include_inherited=include_inherited, page_size=page_size, dto_module=self._dto_module
            ),
        )
        return _pages("listSharedEntryAccessBindings", payload, self._api.list_shared_entry, self._binding_page)

    def modify_workbook(self, *, workbook_id: str, deltas: Sequence[RoleBindingDelta]) -> DataLensOperation:
        payload = _payload(
            "updateWorkbookAccessBindings",
            lambda: AccessBindingsConverter.modify_workbook_payload(workbook_id, deltas, dto_module=self._dto_module),
        )
        raw = self._api.modify_workbook(payload)
        try:
            return AccessBindingsConverter.modify_result(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateWorkbookAccessBindings", reason=str(exc)) from exc

    def modify_collection(self, *, collection_id: str, deltas: Sequence[RoleBindingDelta]) -> DataLensOperation:
        payload = _payload(
            "updateCollectionAccessBindings",
            lambda: AccessBindingsConverter.modify_collection_payload(
                collection_id, deltas, dto_module=self._dto_module
            ),
        )
        raw = self._api.modify_collection(payload)
        try:
            return AccessBindingsConverter.modify_result(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateCollectionAccessBindings", reason=str(exc)) from exc

    def get_entries(
        self, *, entry_ids: Sequence[str]
    ) -> Mapping[str, EntryEffectivePermissionResult | EffectivePermissionError]:
        payload = _payload(
            "getEntriesPermissions",
            lambda: EffectivePermissionsConverter.entries_payload(entry_ids, dto_module=self._dto_module),
        )
        raw = self._api.get_entries(payload)
        try:
            return EffectivePermissionsConverter.entries_result(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getEntriesPermissions", reason=str(exc)) from exc

    def get_bulk(
        self,
        *,
        entry_ids: Sequence[str] | None = None,
        workbook_ids: Sequence[str] | None = None,
        collection_ids: Sequence[str] | None = None,
    ) -> BulkPermissionsResult:
        payload = _payload(
            "getPermissionsBulk",
            lambda: EffectivePermissionsConverter.bulk_payload(
                entry_ids=entry_ids,
                workbook_ids=workbook_ids,
                collection_ids=collection_ids,
                dto_module=self._dto_module,
            ),
        )
        raw = self._api.get_bulk(payload)
        try:
            return EffectivePermissionsConverter.bulk_result(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getPermissionsBulk", reason=str(exc)) from exc

    def get_root_collection(self) -> RootCollectionPermissions:
        raw = self._api.get_root_collection({})
        try:
            return EffectivePermissionsConverter.root_result(raw, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getRootCollectionPermissions", reason=str(exc)) from exc

    def _directory_page(self, raw: object) -> tuple[tuple[DirectorySubject, ...], str]:
        page = DirectorySubjectsConverter.list_result(raw, dto_module=self._dto_module)
        return page.subjects, page.next_page_token

    def list_subjects(
        self,
        *,
        search: str | None = None,
        filter: str | None = None,
        language: Literal["en", "ru"] | None = None,
        subject_type: DirectorySubjectType | None = None,
        page_size: int | None = None,
    ) -> Pager[DirectorySubject]:
        payload = _payload(
            "batchListMembers",
            lambda: DirectorySubjectsConverter.list_payload(
                search=search,
                filter=filter,
                language=language,
                subject_type=subject_type,
                page_size=page_size,
                dto_module=self._dto_module,
            ),
        )
        return _pages("batchListMembers", payload, self._api.list_subjects, self._directory_page)
