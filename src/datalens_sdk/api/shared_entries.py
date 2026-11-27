from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.shared_entries import SharedEntriesDtoModule, SharedEntryConverter
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.shared_entries import (
    SharedEntryBinding,
    SharedEntryBindingItem,
    SharedEntryMode,
    SharedEntryRole,
)
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class SharedBindingAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def execute(self, route: str, payload: dict[str, object], *, read: bool = False) -> dict[str, object]:
        if read:
            return self._client.post_json_object(route, payload, retry_policy=TRANSIENT_RETRY_POLICY)
        return self._client.post_json_object(route, payload)


class SharedEntriesService:
    def __init__(self, *, api: SharedBindingAPI, dto_module: SharedEntriesDtoModule | None = None) -> None:
        self._api = api
        self._converter = SharedEntryConverter(dto_module)

    def _binding(self, route: str, payload: dict[str, object], *, read: bool = False) -> SharedEntryBinding:
        raw = self._api.execute(route, payload, read=read)
        try:
            return self._converter.binding(raw)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=route, reason=str(exc)) from exc

    def bind(self, *, source_id: str, target_id: str, delegation: bool) -> SharedEntryBinding:
        try:
            payload = self._converter.binding_args(source_id=source_id, target_id=target_id, delegation=delegation)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createSharedEntryBinding", reason=str(exc)) from exc
        return self._binding("/rpc/createSharedEntryBinding", payload)

    def update(self, *, source_id: str, target_id: str, delegation: bool) -> SharedEntryBinding:
        try:
            payload = self._converter.binding_args(source_id=source_id, target_id=target_id, delegation=delegation)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateSharedEntryBinding", reason=str(exc)) from exc
        return self._binding("/rpc/updateSharedEntryBinding", payload)

    def unbind(self, *, source_id: str, target_id: str) -> SharedEntryBinding:
        try:
            payload = self._converter.pair_args(source_id=source_id, target_id=target_id)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="deleteSharedEntryBinding", reason=str(exc)) from exc
        return self._binding("/rpc/deleteSharedEntryBinding", payload)

    def get_delegation(
        self, *, source_id: str, target_id: str, binded_workbook_id: str | None = None
    ) -> SharedEntryBinding:
        try:
            payload = self._converter.delegation_args(
                source_id=source_id, target_id=target_id, binded_workbook_id=binded_workbook_id
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getSharedEntryDelegation", reason=str(exc)) from exc
        return self._binding("/rpc/getSharedEntryDelegation", payload, read=True)

    def list(
        self,
        *,
        entry_id: str,
        entry_as: SharedEntryRole,
        mode: SharedEntryMode = "all",
        filter_string: str | None = None,
        page_size: int = 20,
        include_permissions_info: bool = False,
    ) -> Pager[SharedEntryBindingItem]:
        if mode not in ("all", "workbooks", "entries"):
            raise DataLensValidationError("mode must be 'all', 'workbooks', or 'entries'")
        wire_mode = {"all": "all", "workbooks": "onlyWorkbooks", "entries": "onlyEntries"}[mode]

        def load() -> Iterator[Page[SharedEntryBindingItem]]:
            page = 0
            seen: set[int] = set()
            while True:
                try:
                    payload = self._converter.list_args(
                        entry_id=entry_id,
                        entry_as=entry_as,
                        mode=wire_mode,
                        filter_string=filter_string,
                        page=page,
                        page_size=page_size,
                        include_permissions_info=include_permissions_info,
                    )
                    raw = self._api.execute("/rpc/getSharedEntryBindings", payload, read=True)
                    items, token = self._converter.list_result(raw)
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="getSharedEntryBindings", reason=str(exc)) from exc
                yield Page(items=items, next_page_token=token)
                if not token:
                    return
                try:
                    next_page = int(token)
                except ValueError as exc:
                    raise translate_invalid_response_error(
                        operation="getSharedEntryBindings", reason="nextPageToken is not a page number"
                    ) from exc
                if next_page <= page or next_page in seen:
                    raise translate_invalid_response_error(
                        operation="getSharedEntryBindings", reason="pagination returned a repeated page"
                    )
                seen.add(next_page)
                page = next_page

        return Pager(load)
