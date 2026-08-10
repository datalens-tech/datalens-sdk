from __future__ import annotations

from collections.abc import Mapping
import logging

import httpx
import pytest

from datalens_sdk import (
    DEFAULT_RETRY_POLICY,
    APIErrorContext,
    BadRequestError,
    ConflictError,
    DataLensClientYC,
    DataLensConfigurationError,
    DataLensHTTPClient,
    DataLensTransportError,
    LockedError,
    NotFoundError,
    ResponseAcceptancePredicate,
    RetryPolicy,
    ServerError,
    StatusMapTransformer,
)
from datalens_sdk.api.connection import ConnectionAPI
from datalens_sdk.api.dataset import DatasetAPI


def test_retry_policy_validates_and_calculates_capped_backoff() -> None:
    policy = RetryPolicy(max_attempts=4, backoff_factor=0.25, max_backoff=0.4)

    assert RetryPolicy() == DEFAULT_RETRY_POLICY
    assert DEFAULT_RETRY_POLICY.max_attempts == 1
    assert DEFAULT_RETRY_POLICY.total_timeout == 100.0
    assert DEFAULT_RETRY_POLICY.request_timeout == 30.0
    assert DEFAULT_RETRY_POLICY.connect_timeout == 30.0
    assert [policy.backoff_before_attempt(attempt) for attempt in range(1, 5)] == [0.0, 0.25, 0.4, 0.4]
    assert policy.retryable_status_codes == frozenset({429, 500, 501, 502, 503, 504, 521})
    assert policy.can_retry_error(503)
    assert not policy.can_retry_error(505)
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="total_timeout"):
        RetryPolicy(total_timeout=0)
    with pytest.raises(ValueError, match="request_timeout"):
        RetryPolicy(request_timeout=0)
    with pytest.raises(ValueError, match="connect_timeout"):
        RetryPolicy(connect_timeout=0)
    with pytest.raises(ValueError, match="backoff_factor"):
        RetryPolicy(backoff_factor=-0.1)
    with pytest.raises(ValueError, match="max_backoff"):
        RetryPolicy(max_backoff=-0.1)


def test_read_rpc_retries_transient_response_and_sets_canonical_headers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []
    responses = [
        httpx.Response(503, json={"message": "temporarily unavailable"}),
        httpx.Response(200, json={"id": "dataset-1", "dataset": {}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.http.time.sleep", sleeps.append)
    caplog.set_level(logging.DEBUG, logger="datalens_sdk.http")

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="42",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        payload = DatasetAPI(http_client).get("dataset-1")

    assert payload["id"] == "dataset-1"
    assert len(requests) == 2
    assert sleeps == [0.1]
    assert requests[0].headers["user-agent"] == "datalens-sdk/1.2.3 (yacloud)"
    assert requests[0].headers["x-dl-api-version"] == "42"
    assert "Retrying DataLens request after response" in caplog.text
    assert "operation=getDataset" in caplog.text


def test_mutating_rpc_is_not_retried_and_logs_no_request_body(caplog: pytest.LogCaptureFixture) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"message": "failed"})

    caplog.set_level(logging.DEBUG, logger="datalens_sdk.http")
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        ) as http_client,
        pytest.raises(ServerError, match="failed"),
    ):
        DatasetAPI(http_client).create({"secret": "must-not-be-logged"})

    assert len(requests) == 1
    assert requests[0].extensions["timeout"] == {
        "connect": 30.0,
        "read": 30.0,
        "write": None,
        "pool": None,
    }
    assert "must-not-be-logged" not in caplog.text
    assert "Retrying DataLens request" not in caplog.text


def test_retry_policy_applies_distinct_request_and_connect_timeouts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="2",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        http_client.post_json(
            "/rpc/getConnection",
            {},
            retry_policy=RetryPolicy(request_timeout=20.0, connect_timeout=5.0),
        )

    assert requests[0].extensions["timeout"] == {
        "connect": 5.0,
        "read": 20.0,
        "write": None,
        "pool": None,
    }


def test_retry_attempt_timeouts_are_capped_by_remaining_total_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    requests: list[httpx.Request] = []

    def perf_counter() -> float:
        return now

    def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal now
        requests.append(request)
        if len(requests) == 1:
            now += 75.0
            return httpx.Response(503, json={"message": "temporarily unavailable"})
        return httpx.Response(200, json={})

    monkeypatch.setattr("datalens_sdk.http.time.perf_counter", perf_counter)
    monkeypatch.setattr("datalens_sdk.http.time.sleep", sleep)

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="2",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    ) as http_client:
        http_client.post_json(
            "/rpc/getConnection",
            {},
            retry_policy=RetryPolicy(max_attempts=2, backoff_factor=0.1),
        )

    assert len(requests) == 2
    assert requests[0].extensions["timeout"] == {
        "connect": 30.0,
        "read": 30.0,
        "write": None,
        "pool": None,
    }
    assert requests[1].extensions["timeout"] == pytest.approx(
        {
            "connect": 24.9,
            "read": 24.9,
            "write": None,
            "pool": None,
        }
    )


def test_exhausted_total_timeout_prevents_another_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    requests: list[httpx.Request] = []

    def perf_counter() -> float:
        return now

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal now
        requests.append(request)
        now = 100.0
        return httpx.Response(503, json={"message": "temporarily unavailable"})

    monkeypatch.setattr("datalens_sdk.http.time.perf_counter", perf_counter)

    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        ) as http_client,
        pytest.raises(ServerError) as exc_info,
    ):
        http_client.post_json(
            "/rpc/getConnection",
            {},
            retry_policy=RetryPolicy(max_attempts=2),
        )

    assert len(requests) == 1
    assert exc_info.value.context.attempts == 1


def test_conflict_status_is_not_retried_even_for_read_rpc() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            423,
            json={"code": "ERR.LOCKED", "message": "locked"},
            headers={"x-request-id": "request-423"},
        )

    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        ) as http_client,
        pytest.raises(LockedError) as exc_info,
    ):
        DatasetAPI(http_client).get("dataset-1")

    assert len(requests) == 1
    assert exc_info.value.context.request_method == "POST"
    assert exc_info.value.context.request_id == "request-423"
    assert exc_info.value.context.attempts == 1
    assert "request=POST https://example.test/rpc/getDataset" in str(exc_info.value)


def test_unlisted_server_status_is_not_retried_for_read_rpc() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(505, json={"message": "HTTP version not supported"})

    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        ) as http_client,
        pytest.raises(ServerError, match="HTTP version not supported"),
    ):
        DatasetAPI(http_client).get("dataset-1")

    assert len(requests) == 1


def test_transport_errors_retry_then_raise_typed_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("network down", request=request)

    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.http.time.sleep", sleeps.append)
    caplog.set_level(logging.WARNING, logger="datalens_sdk.http")

    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(handler),
        ) as http_client,
        pytest.raises(DataLensTransportError) as exc_info,
    ):
        DatasetAPI(http_client).get("dataset-1")

    assert len(requests) == 3
    assert sleeps == [0.1, 0.2]
    assert exc_info.value.method == "POST"
    assert exc_info.value.url == "https://example.test/rpc/getDataset"
    assert exc_info.value.attempts == 3
    assert exc_info.value.reason == "network down"
    assert caplog.text.count("Retrying DataLens request after transport error") == 2
    assert "DataLens transport failed" in caplog.text


def test_dataset_http_400_with_component_errors_is_returned_with_base_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    component_errors = {"items": [{"code": "ERR.DATASET.SOURCE", "message": "source failed"}]}
    caplog.set_level(logging.WARNING, logger="datalens_sdk.http")

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="2",
        base_url="https://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"dataset": {"component_errors": component_errors}})
        ),
    ) as http_client:
        payload = DatasetAPI(http_client).get("dataset-1")

    assert payload == {"dataset": {"component_errors": component_errors}}
    assert caplog.text.count("Accepting DataLens error response as API payload") == 1
    assert "DataLens dataset component errors" not in caplog.text


def test_validate_dataset_http_400_error_envelope_is_unwrapped_and_logs_component_errors_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    component_errors = {
        "items": [
            {
                "type": "field",
                "id": "field-1",
                "errors": [
                    {
                        "code": "ERR.DS_API.FORMULA.UNKNOWN_FIELD_IN_FORMULA",
                        "message": "Unknown field found in formula: missing",
                    }
                ],
            }
        ]
    }
    validate_payload = {
        "savedId": "dataset-1",
        "revId": "dataset-1",
        "dataset": {
            "description": "Dataset with an invalid field",
            "component_errors": component_errors,
        },
    }
    caplog.set_level(logging.WARNING, logger="datalens_sdk.http")

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="1.2.3",
        api_version="2",
        base_url="https://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "code": "ERR.DS_API.VALIDATION.ERROR",
                    "message": "Validation finished with errors.",
                    "details": {"data": validate_payload},
                },
            )
        ),
    ) as http_client:
        payload = DatasetAPI(http_client).validate({"datasetId": "dataset-1"})

    assert payload == validate_payload
    assert caplog.text.count("Accepting DataLens error response as API payload") == 1
    assert caplog.text.count("DataLens dataset component errors") == 1
    assert "operation=validateDataset" in caplog.text
    assert "ERR.DS_API.FORMULA.UNKNOWN_FIELD_IN_FORMULA" in caplog.text


def test_validate_dataset_http_400_error_envelope_without_component_errors_still_raises() -> None:
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    json={
                        "code": "ERR.DS_API.VALIDATION.ERROR",
                        "message": "Validation failed without a usable dataset.",
                        "details": {"data": {"dataset": {}}},
                    },
                )
            ),
        ) as http_client,
        pytest.raises(BadRequestError, match="Validation failed without a usable dataset"),
    ):
        DatasetAPI(http_client).validate({"datasetId": "dataset-1"})


def test_dataset_http_400_without_component_errors_still_raises() -> None:
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(400, json={"dataset": {}, "message": "invalid dataset"})
            ),
        ) as http_client,
        pytest.raises(BadRequestError, match="invalid dataset"),
    ):
        DatasetAPI(http_client).get("dataset-1")


def test_unique_violation_http_400_raises_conflict_with_original_context() -> None:
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    json={
                        "code": "ERR.US.DB.UNIQUE_VIOLATION",
                        "message": "duplicate entry",
                        "details": {"entryId": "dataset-1"},
                    },
                    headers={"x-request-id": "request-unique"},
                )
            ),
        ) as http_client,
        pytest.raises(ConflictError) as exc_info,
    ):
        DatasetAPI(http_client).create({"name": "Sales"})

    assert exc_info.value.context.status_code == 400
    assert exc_info.value.context.code == "ERR.US.DB.UNIQUE_VIOLATION"
    assert exc_info.value.context.details == {"entryId": "dataset-1"}
    assert exc_info.value.context.request_url == "https://example.test/rpc/createDataset"
    assert exc_info.value.context.request_id == "request-unique"
    assert exc_info.value.context.request_method == "POST"
    assert exc_info.value.context.attempts == 1


def test_non_dataset_http_400_still_raises() -> None:
    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    json={"dataset": {"component_errors": {"items": []}}, "message": "bad connection"},
                )
            ),
        ) as http_client,
        pytest.raises(BadRequestError, match="bad connection"),
    ):
        ConnectionAPI(http_client).get("connection-1")


class _ClientLevelError(Exception):
    def __init__(self, context: APIErrorContext) -> None:
        self.context = context
        super().__init__(context.message)


def test_http_client_uses_its_error_transformer() -> None:
    client_transformer = StatusMapTransformer(status_map={404: _ClientLevelError})

    with (
        DataLensHTTPClient(
            installation="yacloud",
            sdk_version="1.2.3",
            api_version="2",
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    404,
                    json={"code": "ERR.NOT_FOUND", "message": "missing"},
                )
            ),
            error_transformer=client_transformer,
        ) as http_client,
        pytest.raises(_ClientLevelError) as exc_info,
    ):
        http_client.post_json_object("/rpc/getConnection", {})

    assert exc_info.value.context.code == "ERR.NOT_FOUND"


def test_high_level_client_uses_sdk_error_transformer() -> None:
    with (
        DataLensClientYC(
            auth=None,
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    404,
                    json={"code": "ERR.NOT_FOUND", "message": "missing"},
                )
            ),
        ) as client,
        pytest.raises(NotFoundError),
    ):
        client.get.connection(by_id="missing")


class _InjectedHTTPClient:
    def __init__(self) -> None:
        self.closed = False
        self.paths: list[str] = []

    def post_json(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        accept_response: ResponseAcceptancePredicate | None = None,
    ) -> object | None:
        self.paths.append(path)
        return self.post_json_object(
            path,
            body,
            retry_policy=retry_policy,
            accept_response=accept_response,
        )

    def post_json_object(
        self,
        path: str,
        body: Mapping[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        accept_response: ResponseAcceptancePredicate | None = None,
    ) -> dict[str, object]:
        self.paths.append(path)
        return {"id": "connection-1", "type": "postgres", "name": "Postgres"}

    def close(self) -> None:
        self.closed = True


class _ClosingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    def close(self) -> None:
        self.closed = True


def test_sdk_client_injection_is_caller_owned_and_construction_options_are_exclusive() -> None:
    injected = _InjectedHTTPClient()

    with DataLensClientYC(http_client=injected) as client:
        connection = client.get.connection(by_id="connection-1")

    assert connection.id == "connection-1"
    assert injected.paths == ["/rpc/getConnection"]
    assert injected.closed is False

    with pytest.raises(DataLensConfigurationError, match="http_client cannot be combined"):
        DataLensClientYC(http_client=injected, auth=None)


def test_sdk_client_closes_automatically_created_transport() -> None:
    transport = _ClosingTransport()

    with DataLensClientYC(auth=None, transport=transport):
        pass

    assert transport.closed is True
