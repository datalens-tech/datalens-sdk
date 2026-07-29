from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import cast

from pydantic import ValidationError

from datalens_sdk.converter.license import LicenseConverter, LicenseDtoModule
from datalens_sdk.domain.license import License, LicenseLimits, LicenseListOptions
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import LicenseOperations
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class LicenseAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def assign(self, payload: dict[str, object]) -> list[dict[str, object]]:
        response = self._client.post_json("/rpc/assignLicenses", payload)
        if not isinstance(response, list) or not all(isinstance(item, Mapping) for item in response):
            raise translate_invalid_response_error(
                operation="assignLicenses",
                reason="response root is not an array",
            )
        return [cast(dict[str, object], dict(item)) for item in response]

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getLicenses",
            payload,
            retry_policy=TRANSIENT_RETRY_POLICY,
        )

    def get_limits(self) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getLicensesLimit",
            {},
            retry_policy=TRANSIENT_RETRY_POLICY,
        )

    def set_limit(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/setLicenseLimit", payload)


class LicenseService(LicenseOperations):
    def __init__(
        self,
        *,
        api: LicenseAPI,
        dto_module: LicenseDtoModule | None = None,
    ) -> None:
        self._api = api
        self._dto_module = dto_module

    def assign_licenses(self, user_ids: Sequence[str]) -> tuple[License, ...]:
        try:
            payload = LicenseConverter.assign_payload(user_ids, dto_module=self._dto_module)
            return LicenseConverter.assign_result(self._api.assign(payload), dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="assignLicenses", reason=str(exc)) from exc

    def list_licenses(self, options: LicenseListOptions) -> Pager[License]:
        def load() -> Iterator[Page[License]]:
            page_token: str | None = None
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = LicenseConverter.list_payload(
                        options,
                        page_token=page_token,
                        dto_module=self._dto_module,
                    )
                    items, next_token = LicenseConverter.list_result(
                        self._api.list(payload),
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="getLicenses", reason=str(exc)) from exc
                yield Page(items=items, next_page_token=next_token)
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="getLicenses",
                        reason="pagination returned a repeated nextPageToken",
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return Pager(load)

    def get_license_limits(self) -> LicenseLimits:
        try:
            return LicenseConverter.limits_result(self._api.get_limits(), dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getLicensesLimit", reason=str(exc)) from exc

    def set_license_limit(self, value: int) -> LicenseLimits:
        try:
            payload = LicenseConverter.set_limit_payload(value, dto_module=self._dto_module)
            return LicenseConverter.limits_result(self._api.set_limit(payload), dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="setLicenseLimit", reason=str(exc)) from exc
