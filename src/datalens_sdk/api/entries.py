from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Protocol

from pydantic import ValidationError

from datalens_sdk.converter.entry import EntryMutationConverter, EntryMutationDtoModule
from datalens_sdk.converter.navigation import NavigationConverter, NavigationDtoModule
from datalens_sdk.domain.navigation import (
    EntryRelation,
    Page,
    Pager,
    RelationOptions,
)
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy


class EntriesAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def _response(
        self,
        path: str,
        body: dict[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> object:
        response = self._client.post_json(path, body, retry_policy=retry_policy)
        return {} if response is None else response

    def _post_object(
        self,
        path: str,
        body: dict[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> dict[str, object]:
        return self._client.post_json_object(path, body, retry_policy=retry_policy)

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post_object("/rpc/getEntries", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list_directory(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post_object("/rpc/listDirectory", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def get_relations(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post_object("/rpc/getEntriesRelations", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def move(self, payload: dict[str, object]) -> None:
        response = self._response("/rpc/moveFolderEntry", payload)
        if not isinstance(response, list) or not all(isinstance(item, Mapping) for item in response):
            raise translate_invalid_response_error(
                operation="/rpc/moveFolderEntry", reason="response root is not an array"
            )

    def rename(self, payload: dict[str, object]) -> None:
        response = self._response("/rpc/renameEntry", payload)
        if not isinstance(response, list) or not all(isinstance(item, Mapping) for item in response):
            raise translate_invalid_response_error(operation="/rpc/renameEntry", reason="response root is not an array")


class EntriesDtoModule(EntryMutationDtoModule, NavigationDtoModule, Protocol): ...


class EntriesService:
    def __init__(
        self,
        *,
        api: EntriesAPI,
        dto_module: EntriesDtoModule | None = None,
    ) -> None:
        self._api = api
        self._dto_module = dto_module

    def get_entry_relations(
        self,
        entry_id: str,
        options: RelationOptions,
    ) -> Pager[EntryRelation]:
        def load() -> Iterator[Page[EntryRelation]]:
            page_token: str | None = None
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = NavigationConverter.relations_payload(
                        entry_id,
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    )
                    items, next_token = NavigationConverter.relations_result(
                        self._api.get_relations(payload),
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="getEntriesRelations", reason=str(exc)) from exc
                yield Page(items=items, next_page_token=next_token)
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="getEntriesRelations",
                        reason="pagination returned a repeated nextPageToken",
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)

    def rename_entry(self, *, entry_id: str, name: str) -> None:
        try:
            dto = EntryMutationConverter.from_domain_rename(
                entry_id=entry_id,
                name=name,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="renameEntry", reason=str(exc)) from exc
        self._api.rename(dto.to_payload())
