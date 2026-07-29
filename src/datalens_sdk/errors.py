from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class APIErrorContext:
    status_code: int
    code: str | None
    message: str
    details: dict[str, object] | None = None
    request_url: str | None = None
    request_id: str | None = None
    request_method: str | None = None
    attempts: int = 1


class DatalensError(Exception):
    """Base class for SDK exceptions."""


class DatalensValidationError(DatalensError, ValueError):
    """Client-side validation failed before a request was sent."""


class DatalensConfigurationError(DatalensError):
    """The client is missing configuration required for an operation."""


class NotSupportedError(DatalensError, AttributeError):
    """The selected installation does not support the requested SDK surface."""


class DatalensAPIError(DatalensError):
    def __init__(self, context: APIErrorContext) -> None:
        self.context = context
        code = f" code={context.code}" if context.code else ""
        request_id = f" x-request-id={context.request_id}" if context.request_id else ""
        request = ""
        if context.request_method or context.request_url:
            request = f" request={context.request_method or '<unknown>'} {context.request_url or '<unknown>'}"
        attempts = f" attempts={context.attempts}" if context.attempts > 1 else ""
        super().__init__(
            f"DataLens API error ({context.status_code}{code}{request_id}{request}{attempts}): {context.message}"
        )


class DatalensTransportError(DatalensError):
    def __init__(self, *, method: str, url: str, attempts: int, reason: str) -> None:
        self.method = method
        self.url = url
        self.attempts = attempts
        self.reason = reason
        super().__init__(f"DataLens transport error (request={method} {url} attempts={attempts}): {reason}")


class BadRequestError(DatalensAPIError):
    pass


class UnauthorizedError(DatalensAPIError):
    pass


class ForbiddenError(DatalensAPIError):
    pass


class NotFoundError(DatalensAPIError):
    pass


class ConflictError(DatalensAPIError):
    pass


class LockedError(DatalensAPIError):
    pass


class RateLimitError(DatalensAPIError):
    pass


class ServerError(DatalensAPIError):
    pass


class InvalidResponseError(DatalensAPIError):
    pass


class DTOValidationError(DatalensAPIError):
    pass


def translate_invalid_response_error(
    *,
    operation: str,
    reason: str,
    request_url: str | None = None,
    request_id: str | None = None,
    attempts: int = 1,
) -> InvalidResponseError:
    return InvalidResponseError(
        APIErrorContext(
            status_code=502,
            code="ERR.DATALENS_SDK.INVALID_RESPONSE",
            message=f"Invalid response for {operation}: {reason}",
            request_url=request_url,
            request_id=request_id,
            request_method="POST" if request_url is not None else None,
            attempts=attempts,
        )
    )


def translate_dto_validation_error(*, operation: str, reason: str) -> DTOValidationError:
    return DTOValidationError(
        APIErrorContext(
            status_code=502,
            code="ERR.DATALENS_SDK.DTO_VALIDATION",
            message=f"Failed to parse response for {operation}: {reason}",
        )
    )
