from __future__ import annotations

import base64
import binascii

from pydantic import ValidationError

from datalens_sdk.converter.screenshot import ScreenshotConverter, ScreenshotDtoModule
from datalens_sdk.domain.ports import ScreenshotOperations
from datalens_sdk.domain.screenshot import EntityScreenshot, ScreenshotRequest
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import DEFAULT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy

SCREENSHOT_OPERATIONS = {"chart": "getChartScreenshot", "dashboard": "getDashScreenshot"}


def screenshot_retry_policy(timeout: float) -> RetryPolicy:
    """Wait up to ``timeout`` seconds for one render; a failed render is never repeated."""
    connect_timeout = DEFAULT_RETRY_POLICY.connect_timeout
    return RetryPolicy(
        total_timeout=timeout + connect_timeout,
        request_timeout=timeout,
        connect_timeout=connect_timeout,
        max_attempts=1,
    )


class ScreenshotAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get_chart_screenshot(self, payload: dict[str, object], *, retry_policy: RetryPolicy) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getChartScreenshot", payload, retry_policy=retry_policy)

    def get_dash_screenshot(self, payload: dict[str, object], *, retry_policy: RetryPolicy) -> dict[str, object]:
        return self._client.post_json_object("/rpc/getDashScreenshot", payload, retry_policy=retry_policy)


class ScreenshotService(ScreenshotOperations):
    def __init__(self, *, api: ScreenshotAPI, dto_module: ScreenshotDtoModule | None = None) -> None:
        self._api = api
        self._dto_module = dto_module

    def get_screenshot(self, request: ScreenshotRequest) -> EntityScreenshot:
        operation = SCREENSHOT_OPERATIONS[request.entity_kind]
        data = self.__request_data(request, s3=False)
        try:
            image = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise translate_invalid_response_error(operation=operation, reason="data is not valid base64") from exc
        return EntityScreenshot(
            image=image,
            width=request.width,
            height=request.height,
            params=request.params,
            entity_id=request.entity_id,
            _request=request,
            _operations=self,
        )

    def get_screenshot_url(self, request: ScreenshotRequest) -> str:
        return self.__request_data(request, s3=True)

    def __request_data(self, request: ScreenshotRequest, *, s3: bool) -> str:
        operation = SCREENSHOT_OPERATIONS[request.entity_kind]
        try:
            payload = ScreenshotConverter.from_domain_request(request, s3=s3, dto_module=self._dto_module).to_payload()
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
        retry_policy = screenshot_retry_policy(request.timeout)
        if request.entity_kind == "chart":
            response = self._api.get_chart_screenshot(payload, retry_policy=retry_policy)
        else:
            response = self._api.get_dash_screenshot(payload, retry_policy=retry_policy)
        try:
            return ScreenshotConverter.to_data(response, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
