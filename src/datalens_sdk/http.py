from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
import logging
import time
from typing import Protocol, cast

import httpx

from datalens_sdk.error_transformers import (
    DATALENS_ERROR_TRANSFORMER,
    ErrorTransformerProtocol,
)
from datalens_sdk.errors import (
    APIErrorContext,
    DataLensAPIError,
    DataLensTransportError,
    translate_invalid_response_error,
)

LOGGER = logging.getLogger(__name__)

HTTPEventHook = Callable[[httpx.Request | httpx.Response], object]
HTTPEventHooks = Mapping[str, list[HTTPEventHook]]
ResponseAcceptancePredicate = Callable[[int, object | None], bool]

_DEFAULT_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.NOT_IMPLEMENTED,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
        521,
    }
)


def _dict_with_string_keys(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry settings selected explicitly by an API operation."""

    total_timeout: float = 100.0
    request_timeout: float = 30.0
    connect_timeout: float = 30.0
    max_attempts: int = 1
    backoff_factor: float = 0.1
    max_backoff: float = 1.0
    retryable_status_codes: frozenset[int] = field(default_factory=lambda: _DEFAULT_RETRYABLE_STATUS_CODES)
    retry_transport_errors: bool = True

    def __post_init__(self) -> None:
        if self.total_timeout <= 0:
            raise ValueError("total_timeout must be positive")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        if self.connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_factor < 0:
            raise ValueError("backoff_factor must not be negative")
        if self.max_backoff < 0:
            raise ValueError("max_backoff must not be negative")

    def backoff_before_attempt(self, attempt: int) -> float:
        """Return the delay before a one-based retry attempt."""

        if attempt <= 1:
            return 0.0
        return min(self.backoff_factor * (2.0 ** (attempt - 2)), self.max_backoff)

    def can_retry_error(self, error_code: int) -> bool:
        return error_code in self.retryable_status_codes


DEFAULT_RETRY_POLICY = RetryPolicy()
TRANSIENT_RETRY_POLICY = RetryPolicy(max_attempts=3)


class HTTPClientProtocol(Protocol):
    def post_json(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        accept_response: ResponseAcceptancePredicate | None = None,
    ) -> object | None: ...

    def post_json_object(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        accept_response: ResponseAcceptancePredicate | None = None,
    ) -> dict[str, object]: ...


class DataLensHTTPClient:
    """Thin synchronous transport shared by the DataLens API namespaces."""

    def __init__(
        self,
        *,
        installation: str,
        sdk_version: str,
        api_version: str,
        base_url: str,
        auth: httpx.Auth | None = None,
        transport: httpx.BaseTransport | None = None,
        event_hooks: HTTPEventHooks | None = None,
        error_transformer: ErrorTransformerProtocol = DATALENS_ERROR_TRANSFORMER,
    ) -> None:
        self._installation = installation
        self._error_transformer = error_transformer
        self._client = httpx.Client(
            base_url=base_url,
            auth=auth,
            headers={
                "User-Agent": f"datalens-sdk/{sdk_version} ({installation})",
                "x-dl-api-version": api_version,
            },
            transport=transport,
            event_hooks=event_hooks,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DataLensHTTPClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return str(self._client.base_url.join(path))

    @staticmethod
    def _operation(path: str) -> str:
        return path.removeprefix("/rpc/")

    @staticmethod
    def _timeout_for_remaining_budget(*, policy: RetryPolicy, remaining: float) -> httpx.Timeout:
        return httpx.Timeout(
            None,
            connect=min(policy.connect_timeout, remaining),
            read=min(policy.request_timeout, remaining),
        )

    def _timeout_before_attempt(
        self,
        *,
        policy: RetryPolicy,
        attempt: int,
        deadline: float,
    ) -> httpx.Timeout | None:
        delay = policy.backoff_before_attempt(attempt)
        remaining = deadline - time.perf_counter()
        if delay >= remaining:
            return None
        if delay > 0:
            time.sleep(delay)
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return None
        return self._timeout_for_remaining_budget(policy=policy, remaining=remaining)

    def _log_api_error(self, error: DataLensAPIError, *, operation: str) -> None:
        context = error.context
        LOGGER.error(
            "DataLens request failed: installation=%s operation=%s method=%s url=%s status=%s code=%s "
            "request_id=%s attempts=%s message=%s details=%r",
            self._installation,
            operation,
            context.request_method or "POST",
            context.request_url,
            context.status_code,
            context.code,
            context.request_id,
            context.attempts,
            context.message,
            context.details,
        )

    @staticmethod
    def _api_error(exc: httpx.HTTPStatusError, *, attempts: int) -> DataLensAPIError:
        response = exc.response
        payload: dict[str, object] = {}
        try:
            raw: object = response.json()
            payload = _dict_with_string_keys(raw)
        except ValueError:
            payload = {}

        code = payload.get("code")
        message = payload.get("message") or payload.get("error") or response.text or "Request failed"
        details = _dict_with_string_keys(payload.get("details"))
        return DataLensAPIError(
            APIErrorContext(
                status_code=response.status_code,
                code=str(code) if code is not None else None,
                message=str(message),
                details=details or None,
                request_url=str(exc.request.url),
                request_id=response.headers.get("x-request-id"),
                request_method=exc.request.method,
                attempts=attempts,
            )
        )

    def _transform_api_error(
        self,
        error: DataLensAPIError,
    ) -> Exception:
        transformed = self._error_transformer.transform(error)
        if transformed is not None:
            return transformed
        return error

    def post_json(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        accept_response: ResponseAcceptancePredicate | None = None,
    ) -> object | None:
        operation = self._operation(path)
        url = self._url(path)
        deadline = time.perf_counter() + retry_policy.total_timeout
        attempt_timeout = self._timeout_for_remaining_budget(
            policy=retry_policy,
            remaining=retry_policy.total_timeout,
        )

        for attempt in range(1, retry_policy.max_attempts + 1):
            started = time.perf_counter()
            LOGGER.debug(
                "Sending DataLens request: installation=%s operation=%s method=POST url=%s attempt=%s",
                self._installation,
                operation,
                url,
                attempt,
            )
            try:
                response = self._client.post(path, json=dict(body), timeout=attempt_timeout)
            except httpx.TransportError as exc:
                duration = time.perf_counter() - started
                next_timeout = None
                if retry_policy.retry_transport_errors and attempt < retry_policy.max_attempts:
                    next_timeout = self._timeout_before_attempt(
                        policy=retry_policy,
                        attempt=attempt + 1,
                        deadline=deadline,
                    )
                if next_timeout is not None:
                    LOGGER.warning(
                        "Retrying DataLens request after transport error: installation=%s operation=%s method=POST "
                        "url=%s attempt=%s next_attempt=%s duration=%.3f error=%s",
                        self._installation,
                        operation,
                        url,
                        attempt,
                        attempt + 1,
                        duration,
                        exc,
                    )
                    attempt_timeout = next_timeout
                    continue
                transport_error = DataLensTransportError(
                    method="POST",
                    url=url,
                    attempts=attempt,
                    reason=str(exc) or exc.__class__.__name__,
                )
                LOGGER.error(
                    "DataLens transport failed: installation=%s operation=%s method=POST url=%s attempts=%s message=%s",
                    self._installation,
                    operation,
                    url,
                    attempt,
                    transport_error.reason,
                )
                raise transport_error from exc

            duration = time.perf_counter() - started
            request_id = response.headers.get("x-request-id")
            LOGGER.debug(
                "Received DataLens response: installation=%s operation=%s method=POST url=%s attempt=%s "
                "status=%s request_id=%s duration=%.3f",
                self._installation,
                operation,
                response.request.url,
                attempt,
                response.status_code,
                request_id,
                duration,
            )

            next_timeout = None
            if retry_policy.can_retry_error(response.status_code) and attempt < retry_policy.max_attempts:
                next_timeout = self._timeout_before_attempt(
                    policy=retry_policy,
                    attempt=attempt + 1,
                    deadline=deadline,
                )
            if next_timeout is not None:
                LOGGER.warning(
                    "Retrying DataLens request after response: installation=%s operation=%s method=POST url=%s "
                    "status=%s request_id=%s attempt=%s next_attempt=%s",
                    self._installation,
                    operation,
                    response.request.url,
                    response.status_code,
                    request_id,
                    attempt,
                    attempt + 1,
                )
                response.close()
                attempt_timeout = next_timeout
                continue

            if response.status_code >= 400 and accept_response is not None:
                candidate_payload: object | None = None
                candidate_is_decoded = not response.content
                if response.content:
                    try:
                        candidate_payload = response.json()
                    except ValueError:
                        candidate_is_decoded = False
                    else:
                        candidate_is_decoded = True
                if candidate_is_decoded and accept_response(response.status_code, candidate_payload):
                    LOGGER.warning(
                        "Accepting DataLens error response as API payload: installation=%s operation=%s "
                        "method=POST url=%s status=%s request_id=%s attempt=%s",
                        self._installation,
                        operation,
                        response.request.url,
                        response.status_code,
                        request_id,
                        attempt,
                    )
                    response.close()
                    return candidate_payload

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                api_error = self._api_error(exc, attempts=attempt)
                self._log_api_error(api_error, operation=operation)
                response.close()
                raise self._transform_api_error(api_error) from exc

            if not response.content:
                response.close()
                return None
            try:
                payload: object = response.json()
            except ValueError as exc:
                invalid_error = translate_invalid_response_error(
                    operation=operation,
                    reason="response is not valid JSON",
                    request_url=str(response.request.url),
                    request_id=request_id,
                    attempts=attempt,
                )
                self._log_api_error(invalid_error, operation=operation)
                response.close()
                raise invalid_error from exc
            response.close()
            return payload

        raise AssertionError("retry loop must return or raise")

    def post_json_object(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        accept_response: ResponseAcceptancePredicate | None = None,
    ) -> dict[str, object]:
        payload = self.post_json(
            path,
            body,
            retry_policy=retry_policy,
            accept_response=accept_response,
        )
        if payload is None:
            return {}
        if not isinstance(payload, Mapping):
            invalid_error = translate_invalid_response_error(
                operation=self._operation(path),
                reason="response root is not an object",
            )
            self._log_api_error(invalid_error, operation=self._operation(path))
            raise invalid_error
        return cast(dict[str, object], dict(payload))
