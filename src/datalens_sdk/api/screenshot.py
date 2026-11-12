from __future__ import annotations

import base64
import binascii
import logging
import time

from pydantic import ValidationError

from datalens_sdk.converter.screenshot import ScreenshotConverter, ScreenshotDtoModule
from datalens_sdk.domain.ports import ScreenshotOperations
from datalens_sdk.domain.screenshot import EntityScreenshot, ScreenshotRequest
from datalens_sdk.errors import RateLimitError, translate_dto_validation_error, translate_invalid_response_error
from datalens_sdk.http import DEFAULT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy

LOGGER = logging.getLogger(__name__)
SCREENSHOT_OPERATIONS = {"chart": "getChartScreenshot", "dashboard": "getDashScreenshot"}
MIN_RATE_LIMIT_WAIT = 1.0


def screenshot_retry_policy(timeout: float) -> RetryPolicy:
    """Wait up to ``timeout`` seconds for one render; the transport never repeats it."""
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
        response = self.__post_within_rate_limit(request, payload, operation=operation)
        try:
            return ScreenshotConverter.to_data(response, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc

    def __post_within_rate_limit(
        self, request: ScreenshotRequest, payload: dict[str, object], *, operation: str
    ) -> dict[str, object]:
        """Send the render request; a 429 is waited out by its Retry-After while ``timeout`` allows.

        A rate-limited request never started a render, so sending it again is safe.
        Any other failure is raised at once.
        """
        deadline = time.monotonic() + request.timeout
        remaining = request.timeout
        while True:
            retry_policy = screenshot_retry_policy(remaining)
            try:
                if request.entity_kind == "chart":
                    return self._api.get_chart_screenshot(payload, retry_policy=retry_policy)
                return self._api.get_dash_screenshot(payload, retry_policy=retry_policy)
            except RateLimitError as error:
                retry_after = error.context.retry_after
                if retry_after is None:
                    raise
                wait = max(retry_after, MIN_RATE_LIMIT_WAIT)
                if wait >= deadline - time.monotonic():
                    raise
                LOGGER.warning(
                    "Screenshot rate limit reached, waiting before the next attempt: operation=%s request_id=%s "
                    "wait=%.0fs",
                    operation,
                    error.context.request_id,
                    wait,
                )
                time.sleep(wait)
                remaining = deadline - time.monotonic()
