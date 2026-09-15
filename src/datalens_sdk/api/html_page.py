from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from datalens_sdk.converter.html_page import HtmlPageConverter, HtmlPageDtoModule
from datalens_sdk.domain.entry_types import EntryBranch
from datalens_sdk.domain.html_page import HtmlPage, HtmlPageCreate, HtmlPageUpdate
from datalens_sdk.domain.ports import HtmlPageOperations
from datalens_sdk.errors import DataLensValidationError, translate_dto_validation_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class HtmlPageAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/createHtmlPage", payload)

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getHtmlPage", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/updateHtmlPage", payload)

    def delete(self, payload: dict[str, object]) -> None:
        self._client.post_json_object("/rpc/deleteHtmlPage", payload)


class HtmlPageService(HtmlPageOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: HtmlPageAPI,
        dto_module: HtmlPageDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._dto_module = dto_module

    def create_html_page(self, builder: HtmlPageCreate) -> HtmlPage:
        spec = builder.to_spec()
        try:
            dto = HtmlPageConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createHtmlPage", reason=str(exc)) from exc
        response = self._api.create(dto.to_payload())
        return self._to_domain(response, operation="createHtmlPage", name=spec.name)

    def get_html_page(
        self,
        entry_id: str,
        *,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
        include_favorite: bool | None = None,
        include_permissions: bool | None = None,
    ) -> HtmlPage:
        try:
            dto = HtmlPageConverter.from_domain_get(
                entry_id,
                branch=branch,
                rev_id=rev_id,
                include_favorite=include_favorite,
                include_permissions=include_permissions,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getHtmlPage", reason=str(exc)) from exc
        return self._to_domain(self._api.get(dto.to_payload()), operation="getHtmlPage")

    def update_html_page(self, builder: HtmlPageUpdate) -> HtmlPage:
        spec = builder.to_spec()
        try:
            dto = HtmlPageConverter.from_domain_update(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateHtmlPage", reason=str(exc)) from exc
        return self._to_domain(self._api.update(dto.to_payload()), operation="updateHtmlPage", name=builder.page.name)

    def delete_html_page(self, entry_id: str) -> None:
        try:
            dto = HtmlPageConverter.from_domain_delete(entry_id, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="deleteHtmlPage", reason=str(exc)) from exc
        self._api.delete(dto.to_payload())

    def _to_domain(
        self,
        response: dict[str, object],
        *,
        operation: Literal["createHtmlPage", "getHtmlPage", "updateHtmlPage"],
        name: str | None = None,
    ) -> HtmlPage:
        try:
            return HtmlPageConverter.to_domain(
                response,
                installation=self._installation,
                operations=self,
                operation=operation,
                name=name,
                dto_module=self._dto_module,
            )
        except (ValidationError, DataLensValidationError) as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
