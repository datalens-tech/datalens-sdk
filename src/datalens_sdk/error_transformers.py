from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from datalens_sdk.errors import (
    APIErrorContext,
    BadRequestError,
    ConflictError,
    DatalensAPIError,
    ForbiddenError,
    LockedError,
    NotFoundError,
    RateLimitError,
    ServerError,
    UnauthorizedError,
)


class ErrorTransformerProtocol(Protocol):
    def transform(self, exception: DatalensAPIError) -> Exception | None: ...


class ExceptionFactoryProtocol(Protocol):
    def __call__(self, context: APIErrorContext, /) -> Exception: ...


@dataclass(frozen=True, slots=True)
class NullErrorTransformer:
    def transform(self, exception: DatalensAPIError) -> Exception | None:
        return None


NULL_ERROR_TRANSFORMER: Final[ErrorTransformerProtocol] = NullErrorTransformer()


@dataclass(frozen=True, slots=True)
class ChainTransformer:
    transformers: Sequence[ErrorTransformerProtocol]

    def transform(self, exception: DatalensAPIError) -> Exception | None:
        for transformer in self.transformers:
            transformed = transformer.transform(exception)
            if transformed is not None:
                return transformed
        return None


@dataclass(frozen=True, slots=True)
class CodeMapTransformer:
    code_map: Mapping[str, ExceptionFactoryProtocol]

    def transform(self, exception: DatalensAPIError) -> Exception | None:
        if exception.context.code is None:
            return None
        factory = self.code_map.get(exception.context.code)
        if factory is None:
            return None
        return factory(exception.context)


@dataclass(frozen=True, slots=True)
class StatusMapTransformer:
    status_map: Mapping[int, ExceptionFactoryProtocol]

    def transform(self, exception: DatalensAPIError) -> Exception | None:
        factory = self.status_map.get(exception.context.status_code)
        if factory is None:
            return None
        return factory(exception.context)


def _default_status_map() -> dict[int, ExceptionFactoryProtocol]:
    result: dict[int, ExceptionFactoryProtocol] = {
        400: BadRequestError,
        401: UnauthorizedError,
        403: ForbiddenError,
        404: NotFoundError,
        409: ConflictError,
        423: LockedError,
        429: RateLimitError,
    }
    for status_code in range(500, 600):
        result[status_code] = ServerError
    return result


DATALENS_ERROR_TRANSFORMER: Final[ErrorTransformerProtocol] = StatusMapTransformer(status_map=_default_status_map())


__all__ = [
    "DATALENS_ERROR_TRANSFORMER",
    "NULL_ERROR_TRANSFORMER",
    "ChainTransformer",
    "CodeMapTransformer",
    "ErrorTransformerProtocol",
    "ExceptionFactoryProtocol",
    "NullErrorTransformer",
    "StatusMapTransformer",
]
