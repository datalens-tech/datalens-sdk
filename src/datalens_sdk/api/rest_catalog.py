from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.lakehouse_operation import LakehouseOperationConverter
from datalens_sdk.converter.rest_catalog import RestCatalogConverter, RestCatalogDtoModule
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import LakehouseOperationOperations, RestCatalogOperations
from datalens_sdk.domain.rest_catalog import RestCatalog, RestCatalogCreate, RestCatalogListOptions
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class RestCatalogAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createRestCatalog", payload)

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listCatalogs", payload, retry_policy=TRANSIENT_RETRY_POLICY)


class RestCatalogService(RestCatalogOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: RestCatalogAPI,
        lakehouse_operations: LakehouseOperationOperations,
        dto_module: RestCatalogDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._lakehouse_operations = lakehouse_operations
        self._dto_module = dto_module

    def create_rest_catalog(self, builder: RestCatalogCreate) -> LakehouseOperation:
        try:
            dto = RestCatalogConverter.create_payload(builder.to_spec(), dto_module=self._dto_module)
            raw = self._api.create(dto.to_payload())
            return LakehouseOperationConverter.to_operation(
                raw,
                operations=self._lakehouse_operations,
                operation="createRestCatalog",
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createRestCatalog", reason=str(exc)) from exc

    def list_rest_catalogs(self, options: RestCatalogListOptions) -> Pager[RestCatalog]:
        def load() -> Iterator[Page[RestCatalog]]:
            page_token = options.page_token
            seen_tokens = {page_token} if page_token else set()
            while True:
                try:
                    payload = RestCatalogConverter.list_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    )
                    page = RestCatalogConverter.to_page(
                        self._api.list(payload.to_payload()),
                        installation=self._installation,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listCatalogs", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listCatalogs",
                        reason="pagination returned a repeated nextPageToken",
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)
