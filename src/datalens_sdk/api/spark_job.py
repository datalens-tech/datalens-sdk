from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from datalens_sdk.converter.spark_job import SparkJobConverter, SparkJobDtoModule
from datalens_sdk.domain.navigation import Page, Pager
from datalens_sdk.domain.ports import SparkJobOperations
from datalens_sdk.domain.spark_job import SparkJob, SparkJobListOptions
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
    translate_invalid_response_error,
)
from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class SparkJobAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getSparkJob", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def list(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object("/rpc/listSparkJobs", payload, retry_policy=TRANSIENT_RETRY_POLICY)


class SparkJobService(SparkJobOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: SparkJobAPI,
        dto_module: SparkJobDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._dto_module = dto_module

    def get_spark_job(self, cluster_id: str, job_id: str) -> SparkJob:
        if not isinstance(cluster_id, str) or not cluster_id:
            raise DataLensValidationError("getSparkJob cluster_id must be a non-empty string")
        if not isinstance(job_id, str) or not job_id:
            raise DataLensValidationError("getSparkJob job_id must be a non-empty string")
        try:
            payload = SparkJobConverter.get_payload(cluster_id, job_id, dto_module=self._dto_module).to_payload()
            return SparkJobConverter.to_job(
                self._api.get(payload),
                installation=self._installation,
                operations=self,
                operation="getSparkJob",
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getSparkJob", reason=str(exc)) from exc

    def list_spark_jobs(self, options: SparkJobListOptions) -> Pager[SparkJob]:
        def load() -> Iterator[Page[SparkJob]]:
            page_token = options.page_token
            seen_tokens: set[str] = set()
            while True:
                try:
                    payload = SparkJobConverter.list_payload(
                        options, page_token=page_token, dto_module=self._dto_module
                    ).to_payload()
                    if page_token:
                        seen_tokens.add(page_token)
                    page = SparkJobConverter.to_page(
                        self._api.list(payload),
                        installation=self._installation,
                        operations=self,
                        dto_module=self._dto_module,
                    )
                except ValidationError as exc:
                    raise translate_dto_validation_error(operation="listSparkJobs", reason=str(exc)) from exc
                yield page
                next_token = page.next_page_token
                if not next_token:
                    return
                if next_token in seen_tokens:
                    raise translate_invalid_response_error(
                        operation="listSparkJobs", reason="pagination returned a repeated nextPageToken"
                    )
                page_token = next_token

        return Pager(load)
