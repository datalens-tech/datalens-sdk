from __future__ import annotations

from datalens_sdk import (
    DATALENS_ERROR_TRANSFORMER,
    NULL_ERROR_TRANSFORMER,
    APIErrorContext,
    BadRequestError,
    ChainTransformer,
    CodeMapTransformer,
    ConflictError,
    DatalensAPIError,
    StatusMapTransformer,
)


class _CodeMappedError(Exception):
    def __init__(self, context: APIErrorContext) -> None:
        self.context = context
        super().__init__(context.message)


class _StatusMappedError(Exception):
    def __init__(self, context: APIErrorContext) -> None:
        self.context = context
        super().__init__(context.message)


def _api_error(*, status_code: int = 404, code: str | None = "ERR.NOT_FOUND") -> DatalensAPIError:
    return DatalensAPIError(
        APIErrorContext(
            status_code=status_code,
            code=code,
            message="missing",
        )
    )


def test_null_error_transformer_passes_through() -> None:
    assert NULL_ERROR_TRANSFORMER.transform(_api_error()) is None


def test_code_and_status_transformers_return_mapped_exceptions() -> None:
    error = _api_error()

    code_result = CodeMapTransformer(code_map={"ERR.NOT_FOUND": _CodeMappedError}).transform(error)
    status_result = StatusMapTransformer(status_map={404: _StatusMappedError}).transform(error)

    assert isinstance(code_result, _CodeMappedError)
    assert code_result.context is error.context
    assert isinstance(status_result, _StatusMappedError)
    assert status_result.context is error.context


def test_chain_transformer_uses_first_match_and_returns_none_on_miss() -> None:
    error = _api_error()
    transformer = ChainTransformer(
        transformers=[
            CodeMapTransformer(code_map={"ERR.OTHER": _CodeMappedError}),
            StatusMapTransformer(status_map={404: _StatusMappedError}),
            CodeMapTransformer(code_map={"ERR.NOT_FOUND": _CodeMappedError}),
        ]
    )

    result = transformer.transform(error)

    assert isinstance(result, _StatusMappedError)
    assert ChainTransformer(transformers=[]).transform(error) is None


def test_default_transformer_maps_unique_violation_to_conflict_before_status() -> None:
    error = DatalensAPIError(
        APIErrorContext(
            status_code=400,
            code="ERR.US.DB.UNIQUE_VIOLATION",
            message="duplicate entry",
            details={"entryId": "dash-1"},
            request_url="https://example.test/rpc/createDashboard",
            request_id="request-unique",
            request_method="POST",
            attempts=2,
        )
    )

    result = DATALENS_ERROR_TRANSFORMER.transform(error)

    assert isinstance(result, ConflictError)
    assert result.context is error.context


def test_default_transformer_keeps_unrelated_bad_request_and_status_conflict_mappings() -> None:
    bad_request = DATALENS_ERROR_TRANSFORMER.transform(_api_error(status_code=400, code="ERR.OTHER"))
    conflict = DATALENS_ERROR_TRANSFORMER.transform(_api_error(status_code=409, code="ERR.OTHER"))

    assert isinstance(bad_request, BadRequestError)
    assert isinstance(conflict, ConflictError)
