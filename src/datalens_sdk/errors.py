from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class APIErrorContext:
    status_code: int
    code: str | None
    message: str
    details: dict[str, object] | list[object] | None = None
    request_url: str | None = None
    request_id: str | None = None
    request_method: str | None = None
    attempts: int = 1


class DataLensError(Exception):
    """Base class for SDK exceptions."""


class DataLensValidationError(DataLensError, ValueError):
    """Client-side validation failed before a request was sent."""


class DataLensConfigurationError(DataLensError):
    """The client is missing configuration required for an operation."""


class NotSupportedError(DataLensError, AttributeError):
    """The selected installation does not support the requested SDK surface."""


class DataLensAPIError(DataLensError):
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


class DataLensTransportError(DataLensError):
    def __init__(self, *, method: str, url: str, attempts: int, reason: str) -> None:
        self.method = method
        self.url = url
        self.attempts = attempts
        self.reason = reason
        super().__init__(f"DataLens transport error (request={method} {url} attempts={attempts}): {reason}")


class BadRequestError(DataLensAPIError):
    pass


class UnauthorizedError(DataLensAPIError):
    pass


class ForbiddenError(DataLensAPIError):
    pass


class NotFoundError(DataLensAPIError):
    pass


class ConflictError(DataLensAPIError):
    pass


class LockedError(DataLensAPIError):
    pass


class RateLimitError(DataLensAPIError):
    pass


class ServerError(DataLensAPIError):
    pass


class InvalidResponseError(DataLensAPIError):
    pass


class DTOValidationError(DataLensAPIError):
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
