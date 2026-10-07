from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.spark_application import SparkApplicationConverter, SparkApplicationDtoModule
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import SparkApplicationOperations
from datalens_sdk.domain.spark_application import (
    SparkApplication,
    SparkApplicationListOptions,
    SparkApplicationLogOptions,
    SparkApplicationLogPage,
    SparkApplicationLogPager,
)
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class SparkApplicationAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getSparkApplication", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listSparkApplications", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list_log(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/listSparkApplicationLog", payload, retry_policy=TRANSIENT_RETRY_POLICY
        )


class SparkApplicationService(SparkApplicationOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: SparkApplicationAPI,
        dto_module: SparkApplicationDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._dto_module = dto_module

    def get_spark_application(self, cluster_id: str, application_id: str) -> SparkApplication:
        if not isinstance(cluster_id, str) or not cluster_id:
            raise DataLensValidationError("getSparkApplication cluster_id must be a non-empty string")
        if not isinstance(application_id, str) or not application_id:
            raise DataLensValidationError("getSparkApplication application_id must be a non-empty string")
        try:
            payload = SparkApplicationConverter.get_payload(
                cluster_id, application_id, dto_module=self._dto_module
            ).to_payload()
            return SparkApplicationConverter.to_application(
                self._api.get(payload),
                installation=self._installation,
                operations=self,
                operation="getSparkApplication",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getSparkApplication", reason=str(exc)) from exc

    def list_spark_applications(self, options: SparkApplicationListOptions) -> Pager[SparkApplication]:
        def load() -> Iterator[Page[SparkApplication]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = SparkApplicationConverter.list_payload(
                        options, page_token=page_token, dto_module=self._dto_module
                    ).to_payload()
                    if page_token:
                        seen_tokens.add(page_token)
                    page = SparkApplicationConverter.to_page(
                        self._api.list(payload),
                        installation=self._installation,
                        operations=self,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listSparkApplications", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listSparkApplications", reason="pagination returned a repeated nextPageToken"
                    )
                page_token = next_token

        return Pager(load)

    def list_spark_application_log(self, options: SparkApplicationLogOptions) -> SparkApplicationLogPager:
        def load() -> Iterator[SparkApplicationLogPage]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = SparkApplicationConverter.log_payload(
                        options, page_token=page_token, dto_module=self._dto_module
                    ).to_payload()
                    if not seen_tokens and page_token:
                        seen_tokens.add(page_token)
                    page = SparkApplicationConverter.to_log_page(
                        self._api.list_log(payload), dto_module=self._dto_module
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listSparkApplicationLog", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listSparkApplicationLog", reason="pagination returned a repeated nextPageToken"
                    )
                seen_tokens.add(next_token)
                page_token = next_token

        return SparkApplicationLogPager(load)
