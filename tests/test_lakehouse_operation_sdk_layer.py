from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from importlib import import_module
import json
import math
import time
from types import ModuleType, SimpleNamespace
from typing import cast

import httpx
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.lakehouse_operation import LakehouseOperationAPI, LakehouseOperationService
from datalens_sdk.converter.lakehouse_operation import LakehouseOperationDtoModule
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation, LakehouseOperationError, LakehouseTimestamp
from datalens_sdk.errors import (
    APIErrorContext,
    DataLensAPIError,
    DataLensConfigurationError,
    DataLensError,
    DataLensOperationTimeoutError,
    DataLensTransportError,
    DataLensValidationError,
    DTOValidationError,
    ForbiddenError,
    InvalidResponseError,
)
from datalens_sdk.http import DataLensHTTPClient


class RecordedLakehouseTransport:
    def __init__(self, *responses: dict[str, object]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, content=json.dumps(self.responses.pop(0)))

    def bodies(self) -> list[object]:
        return [json.loads(request.content) for request in self.requests]


def _lakehouse_service(
    http_client: DataLensHTTPClient, *, dto_module: LakehouseOperationDtoModule | None = None
) -> LakehouseOperationService:
    return LakehouseOperationService(api=LakehouseOperationAPI(http_client), dto_module=dto_module)


def test_yc_get_lakehouse_operation_calls_public_surface() -> None:
    recorder = RecordedLakehouseTransport({"id": "operation-1", "done": False, "metadata": {}})
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with client:
        operation = client.get.lakehouse_operation(by_id="operation-1")

    assert isinstance(operation, LakehouseOperation)
    assert operation.id == "operation-1"
    assert [request.url.path for request in recorder.requests] == ["/rpc/getLakehouseOperation"]
    assert recorder.bodies() == [{"operationId": "operation-1"}]


def test_lakehouse_get_rejects_response_for_another_operation() -> None:
    recorder = RecordedLakehouseTransport({"id": "operation-2", "done": False, "metadata": {}})
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client, pytest.raises(InvalidResponseError, match="getLakehouseOperation") as error:
        client.get.lakehouse_operation(by_id="operation-1")

    assert "operation-1" in error.value.context.message
    assert "operation-2" in error.value.context.message
    assert recorder.bodies() == [{"operationId": "operation-1"}]


def test_lakehouse_wait_stops_on_mismatched_response_before_polling_another_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    recorder = RecordedLakehouseTransport(
        {"id": "operation-1", "done": False, "metadata": {}},
        {"id": "operation-2", "done": False, "metadata": {}},
        {"id": "operation-2", "done": True, "metadata": {}},
    )
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        source = client.get.lakehouse_operation(by_id="operation-1")
        with pytest.raises(InvalidResponseError, match="getLakehouseOperation") as error:
            source.wait(timeout=10.0, poll_interval=1.0)

    assert "operation-1" in error.value.context.message
    assert "operation-2" in error.value.context.message
    assert recorder.bodies() == [{"operationId": "operation-1"}] * 2
    assert clock.sleeps == []


@pytest.mark.parametrize("by_id", ["", 123, None])
def test_yc_get_lakehouse_operation_rejects_empty_and_non_string_by_id_before_service(
    by_id: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_get(*args: object, **kwargs: object) -> LakehouseOperation:
        raise AssertionError("Invalid operation ID reached the service")

    monkeypatch.setattr(LakehouseOperationService, "get_lakehouse_operation", unexpected_get)
    recorder = RecordedLakehouseTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with client, pytest.raises(DataLensValidationError, match="by_id must be a non-empty string"):
        client.get.lakehouse_operation(by_id=cast(str, by_id))
    assert recorder.requests == []


def test_enterprise_get_lakehouse_operation_is_absent_without_dto_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DtoWithoutLakehouse(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "Lakehouse" in name:
                raise AssertionError(f"Unexpected Lakehouse DTO access: {name}")
            return getattr(generated_dto, name)

    original_import = import_module
    dto_stub = DtoWithoutLakehouse("datalens_sdk._generated.dto")

    def import_without_lakehouse(name: str) -> ModuleType:
        if name == "datalens_sdk._generated.dto":
            return dto_stub
        return original_import(name)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("Lakehouse service initialized on Enterprise")

    monkeypatch.setattr(client_module, "import_module", import_without_lakehouse)
    monkeypatch.setattr(LakehouseOperationService, "__init__", unexpected_service)
    recorder = RecordedLakehouseTransport()
    with DataLensClientEnterprise(
        auth=None, base_url="https://enterprise.test", transport=httpx.MockTransport(recorder.handle)
    ) as client:
        action_name = "lakehouse_operation"
        with pytest.raises(AttributeError) as exc_info:
            _ = getattr(client.get, action_name)
        assert type(exc_info.value) is AttributeError
    assert recorder.requests == []


def test_list_action_object_has_installation_specific_type() -> None:
    enterprise = DataLensClientEnterprise(auth=None, base_url="https://enterprise.test")
    yacloud = DataLensClientYC(auth=None)

    with enterprise, yacloud:
        assert type(enterprise.list) is client_module.ListNamespace
        assert type(yacloud.list) is client_module.YCListNamespace


def test_yateam_style_get_lakehouse_operation_is_absent_without_dto_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class YaTeamStyleClient(client_module.DataLensClientBase):
        INSTALLATION = "yateam"
        GENERATED_PACKAGE = "test_yateam_generated"
        DEFAULT_BASE_URL = "https://yateam.test"

    class DtoWithoutLakehouse(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "Lakehouse" in name:
                raise AssertionError(f"Unexpected Lakehouse DTO access: {name}")
            return getattr(generated_dto, name)

    sources = import_module("datalens_sdk._generated.builders.dataset_sources")
    charts = import_module("datalens_sdk._generated.builders.charts")
    monkeypatch.setattr(sources, "YateamSourceCreateFactory", sources.EnterpriseSourceCreateFactory, raising=False)
    monkeypatch.setattr(
        charts, "YateamEditorChartCreateFactory", charts.EnterpriseEditorChartCreateFactory, raising=False
    )
    modules = {
        "test_yateam_generated.dto": DtoWithoutLakehouse("test_yateam_generated.dto"),
        "test_yateam_generated.builders.yateam": import_module("datalens_sdk._generated.builders.enterprise"),
        "test_yateam_generated.builders.dataset_sources": sources,
        "test_yateam_generated.builders.charts": charts,
    }
    monkeypatch.setattr(
        client_module,
        "_load_installations",
        lambda package: {
            "yateam": {
                "connectors": {},
                "dataset_sources": {},
                "namespaces": [],
                "chart_factories": {"wizard": [], "ql": [], "editor": []},
            }
        },
    )
    monkeypatch.setattr(client_module, "import_module", modules.__getitem__)

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("Lakehouse service initialized on YaTeam")

    monkeypatch.setattr(LakehouseOperationService, "__init__", unexpected_service)
    recorder = RecordedLakehouseTransport()
    client = YaTeamStyleClient(auth=None, transport=httpx.MockTransport(recorder.handle))
    with client:
        action_name = "lakehouse_operation"
        with pytest.raises(AttributeError) as exc_info:
            _ = getattr(client.get, action_name)
        assert type(exc_info.value) is AttributeError
        assert type(client.list) is client_module.ListNamespace
    assert recorder.requests == []


def test_unknown_get_action_remains_attribute_error() -> None:
    unknown_action = "unknown_action"
    for client in (
        DataLensClientYC(auth=None, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))),
        DataLensClientEnterprise(
            auth=None,
            base_url="https://enterprise.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        ),
    ):
        with client:
            with pytest.raises(AttributeError) as exc_info:
                _ = getattr(client.get, unknown_action)
            assert type(exc_info.value) is AttributeError


def test_lakehouse_get_and_refresh_send_exact_payload_and_convert_snapshots() -> None:
    pending: dict[str, object] = {
        "id": "operation-1",
        "done": False,
        "metadata": {},
        "createdBy": "user-1",
        "description": "build cluster",
        "createdAt": {"seconds": "1727700000", "nanos": 0},
        "modifiedAt": {"seconds": "1727700001", "nanos": 0},
        "response": {},
    }
    terminal: dict[str, object] = {
        "id": "operation-1",
        "done": True,
        "metadata": {},
        "error": {"code": 0, "message": "backend failed", "details": []},
        "response": {},
        "futureField": {"new": True},
    }
    after_refresh: dict[str, object] = {"id": "operation-1", "done": True, "metadata": {"phase": "verified"}}
    recorder = RecordedLakehouseTransport(pending, terminal, after_refresh)
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://lakehouse.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _lakehouse_service(http_client)
        source = service.get_lakehouse_operation("operation-1")
        refreshed = source.refresh()
        latest = refreshed.refresh()

    assert [request.url.path for request in recorder.requests] == ["/rpc/getLakehouseOperation"] * 3
    assert recorder.bodies() == [{"operationId": "operation-1"}] * 3
    assert source == LakehouseOperation(
        id="operation-1",
        done=False,
        metadata={},
        created_by="user-1",
        description="build cluster",
        created_at=LakehouseTimestamp(seconds="1727700000", nanos=0),
        modified_at=LakehouseTimestamp(seconds="1727700001", nanos=0),
        response={},
        raw=pending,
    )
    assert refreshed == LakehouseOperation(
        id="operation-1",
        done=True,
        metadata={},
        error=LakehouseOperationError(code=0, message="backend failed"),
        response={},
        raw=terminal,
    )
    assert latest == LakehouseOperation(id="operation-1", done=True, metadata={"phase": "verified"}, raw=after_refresh)
    assert type(source.done) is bool
    assert type(refreshed.done) is bool
    assert source.created_at is not None
    assert type(source.created_at.nanos) is int
    assert refreshed.error is not None
    assert type(refreshed.error.code) is int


@pytest.mark.parametrize("nanos", [None, 0, 2**53 + 1, 0.125])
def test_lakehouse_get_and_refresh_preserve_raw_timestamp_nanos(nanos: int | float | None) -> None:
    first_timestamp: dict[str, object] = {"seconds": "1727700000"}
    second_timestamp: dict[str, object] = {"seconds": "1727700001"}
    if nanos is not None:
        first_timestamp["nanos"] = nanos
        second_timestamp["nanos"] = nanos
    response: dict[str, object] = {
        "id": "operation-1",
        "done": False,
        "metadata": {},
        "createdAt": first_timestamp,
        "modifiedAt": second_timestamp,
    }
    recorder = RecordedLakehouseTransport(response, {**response, "done": True})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://lakehouse.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _lakehouse_service(http_client)
        source = service.get_lakehouse_operation("operation-1")
        refreshed = source.refresh()

    assert recorder.bodies() == [{"operationId": "operation-1"}] * 2
    for snapshot in (source, refreshed):
        assert (snapshot.created_at, snapshot.modified_at) == (
            LakehouseTimestamp(seconds="1727700000", nanos=nanos),
            LakehouseTimestamp(seconds="1727700001", nanos=nanos),
        )
        assert snapshot.created_at is not None
        assert snapshot.modified_at is not None
        assert type(snapshot.created_at.nanos) is type(nanos)
        assert type(snapshot.modified_at.nanos) is type(nanos)


def test_lakehouse_get_and_refresh_preserve_raw_nanos_when_injected_dto_rounds() -> None:
    class RoundedLakehouseOperationReadDTO:
        @staticmethod
        def model_validate(raw: object) -> object:
            validated = generated_dto.LakehouseOperationReadDTO.model_validate(raw)
            assert validated.created_at is not None
            assert validated.modified_at is not None
            validated.created_at.nanos = float(validated.created_at.nanos)
            validated.modified_at.nanos = float(validated.modified_at.nanos)
            return validated

    injected = cast(
        "LakehouseOperationDtoModule",
        SimpleNamespace(
            GetLakehouseOperationArgsDTO=generated_dto.GetLakehouseOperationArgsDTO,
            LakehouseOperationReadDTO=RoundedLakehouseOperationReadDTO,
        ),
    )
    big_nanos = 2**53 + 1
    response: dict[str, object] = {
        "id": "operation-1",
        "done": False,
        "metadata": {},
        "createdAt": {"seconds": "1727700000", "nanos": big_nanos},
        "modifiedAt": {"seconds": "1727700001", "nanos": big_nanos},
    }
    recorder = RecordedLakehouseTransport(response, {**response, "done": True})
    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://lakehouse.test",
        transport=httpx.MockTransport(recorder.handle),
    ) as http_client:
        service = _lakehouse_service(http_client, dto_module=injected)
        source = service.get_lakehouse_operation("operation-1")
        refreshed = source.refresh()

    assert recorder.bodies() == [{"operationId": "operation-1"}] * 2
    for snapshot in (source, refreshed):
        assert (snapshot.created_at, snapshot.modified_at) == (
            LakehouseTimestamp(seconds="1727700000", nanos=big_nanos),
            LakehouseTimestamp(seconds="1727700001", nanos=big_nanos),
        )
        assert snapshot.created_at is not None
        assert snapshot.modified_at is not None
        assert type(snapshot.created_at.nanos) is int
        assert type(snapshot.modified_at.nanos) is int


def _operation_with_nonfinite_number(field: str, value: float) -> dict[str, object]:
    response: dict[str, object] = {"id": "operation-1", "done": False, "metadata": {}}
    if field == "error.code":
        response["error"] = {"code": value, "message": "failed"}
    else:
        response[field] = {"seconds": "1727700000", "nanos": value}
    return response


@pytest.mark.parametrize("field", ["createdAt", "modifiedAt", "error.code"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf], ids=["nan", "infinity", "negative-infinity"])
def test_lakehouse_get_rejects_nonfinite_numeric_response(field: str, value: float) -> None:
    recorder = RecordedLakehouseTransport(_operation_with_nonfinite_number(field, value))
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client, pytest.raises(InvalidResponseError, match="getLakehouseOperation"):
        client.get.lakehouse_operation(by_id="operation-1")

    assert recorder.bodies() == [{"operationId": "operation-1"}]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.reads = 0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        self.reads += 1
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeOperations:
    def __init__(self, *snapshots: LakehouseOperation, clock: FakeClock | None = None, delay: float = 0.0) -> None:
        self.snapshots = list(snapshots)
        self.calls: list[str] = []
        self.call_times: list[float] = []
        self.clock = clock
        self.delay = delay
        self.last_returned: LakehouseOperation | None = None

    def get_lakehouse_operation(self, operation_id: str) -> LakehouseOperation:
        self.calls.append(operation_id)
        if self.clock is not None:
            self.call_times.append(self.clock.now)
            self.clock.now += self.delay
        self.last_returned = replace(self.snapshots.pop(0), _operations=self)
        return self.last_returned


def _snapshot(*, operation_id: str = "operation-1", done: bool = False) -> LakehouseOperation:
    return LakehouseOperation(id=operation_id, done=done, metadata={})


def _bind(source: LakehouseOperation, operations: FakeOperations) -> LakehouseOperation:
    return replace(source, _operations=operations)


def _install_clock(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)


def test_lakehouse_refresh_rejects_empty_id_before_operations() -> None:
    operations = FakeOperations()
    source = _bind(_snapshot(operation_id=""), operations)

    with pytest.raises(DataLensValidationError):
        source.refresh()

    assert operations.calls == []


def test_lakehouse_unbound_refresh_and_pending_wait_raise_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    source = _snapshot()

    with pytest.raises(DataLensConfigurationError):
        source.refresh()
    with pytest.raises(DataLensConfigurationError):
        source.wait()

    assert clock.reads == 0
    assert clock.sleeps == []


def test_lakehouse_pending_wait_validates_id_and_binding_before_zero_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()

    with pytest.raises(DataLensValidationError):
        _bind(_snapshot(operation_id=""), operations).wait(timeout=0)
    with pytest.raises(DataLensConfigurationError):
        _snapshot().wait(timeout=0)

    assert operations.calls == []
    assert clock.reads == 0
    assert clock.sleeps == []


def test_lakehouse_unbound_terminal_wait_returns_same_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    source = _snapshot(operation_id="", done=True)

    assert source.wait(timeout=0) is source
    assert clock.reads == 0
    assert clock.sleeps == []


def test_lakehouse_wait_returns_terminal_snapshot_by_identity_without_io(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()
    source = _bind(_snapshot(done=True), operations)

    assert source.wait() is source
    assert operations.calls == []
    assert clock.reads == 0
    assert clock.sleeps == []


def test_lakehouse_wait_refreshes_immediately_then_sleeps_fixed_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    pending_with_fields = replace(
        _snapshot(),
        error=LakehouseOperationError(code=0, message="not terminal"),
        response={"progress": 50},
    )
    operations = FakeOperations(pending_with_fields, _snapshot(), _snapshot(done=True), clock=clock)
    source = _bind(_snapshot(), operations)

    result = source.wait(timeout=10, poll_interval=2)

    assert result is operations.last_returned
    assert operations.calls == ["operation-1"] * 3
    assert operations.call_times == [0.0, 2.0, 4.0]
    assert clock.sleeps == [2.0, 2.0]


def test_lakehouse_wait_returns_terminal_error_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    terminal = replace(_snapshot(done=True), error=LakehouseOperationError(code=0, message="failed", details=()))
    operations = FakeOperations(terminal)

    result = _bind(_snapshot(), operations).wait()

    assert result == terminal
    assert result is operations.last_returned
    assert operations.calls == ["operation-1"]
    assert clock.sleeps == []


def test_lakehouse_wait_timeout_zero_raises_before_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()
    source = _bind(_snapshot(), operations)

    with pytest.raises(DataLensOperationTimeoutError) as raised:
        source.wait(timeout=0)

    assert raised.value.last_operation is source
    assert raised.value.operation_id == "operation-1"
    assert raised.value.timeout == 0
    assert operations.calls == []
    assert clock.sleeps == []


def test_lakehouse_wait_timeout_keeps_latest_snapshot_and_truncates_final_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations(_snapshot(), _snapshot(), _snapshot())
    source = _bind(_snapshot(), operations)

    with pytest.raises(DataLensOperationTimeoutError) as raised:
        source.wait(timeout=5.0, poll_interval=2.0)

    assert raised.value.last_operation is operations.last_returned
    assert operations.calls == ["operation-1"] * 3
    assert clock.sleeps == [2.0, 2.0, 1.0]


def test_lakehouse_wait_returns_terminal_refresh_that_finishes_after_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations(_snapshot(done=True), clock=clock, delay=3.0)

    result = _bind(_snapshot(), operations).wait(timeout=2.0)

    assert result is operations.last_returned
    assert operations.calls == ["operation-1"]
    assert clock.now == 3.0
    assert clock.sleeps == []


def test_lakehouse_wait_without_timeout_continues_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations(_snapshot(), _snapshot(done=True))
    source = _bind(_snapshot(), operations)

    result = source.wait(timeout=None, poll_interval=1)

    assert result is operations.last_returned
    assert operations.calls == ["operation-1", "operation-1"]
    assert clock.sleeps == [1.0]
    assert clock.reads == 0


@pytest.mark.parametrize("timeout", [True, "1", -1, math.inf, -math.inf, math.nan])
def test_lakehouse_wait_rejects_invalid_timeout_before_io(monkeypatch: pytest.MonkeyPatch, timeout: object) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()

    with pytest.raises(DataLensValidationError):
        _bind(_snapshot(), operations).wait(timeout=cast(float | None, timeout))

    assert clock.reads == 0
    assert clock.sleeps == []
    assert operations.calls == []


@pytest.mark.parametrize("argument", ["timeout", "poll_interval"])
def test_lakehouse_wait_rejects_fractional_negative_before_io(monkeypatch: pytest.MonkeyPatch, argument: str) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()
    source = _bind(_snapshot(), operations)
    negative = cast(float, Fraction(-1, 10**1000))

    if argument == "timeout":
        with pytest.raises(DataLensValidationError):
            source.wait(timeout=negative)
    else:
        with pytest.raises(DataLensValidationError):
            source.wait(poll_interval=negative)

    assert clock.reads == 0
    assert clock.sleeps == []
    assert operations.calls == []


def test_lakehouse_wait_accepts_positive_fractional_interval_that_underflows_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations(_snapshot(), _snapshot(done=True))
    source = _bind(_snapshot(), operations)

    result = source.wait(timeout=None, poll_interval=cast(float, Fraction(1, 10**1000)))

    assert result.done is True
    assert operations.calls == ["operation-1", "operation-1"]
    assert clock.reads == 0
    assert len(clock.sleeps) == 1
    assert 0 < clock.sleeps[0] < 1


def test_lakehouse_wait_preserves_positive_fractional_timeout_that_underflows_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    clock.now = 1.0
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()

    with pytest.raises(DataLensOperationTimeoutError) as exc_info:
        _bind(_snapshot(), operations).wait(timeout=cast(float, Fraction(1, 10**1000)))

    assert 0 < exc_info.value.timeout < 1
    assert operations.calls == []


@pytest.mark.parametrize("poll_interval", [None, True, "2", 0, -1, math.inf, -math.inf, math.nan])
def test_lakehouse_wait_rejects_invalid_poll_interval_before_io(
    monkeypatch: pytest.MonkeyPatch, poll_interval: object
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    operations = FakeOperations()

    with pytest.raises(DataLensValidationError):
        _bind(_snapshot(), operations).wait(poll_interval=cast(float, poll_interval))

    assert clock.reads == 0
    assert clock.sleeps == []
    assert operations.calls == []


def test_lakehouse_terminal_wait_rejects_invalid_poll_interval_before_identity_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)

    with pytest.raises(DataLensValidationError):
        _snapshot(done=True).wait(poll_interval=0)

    assert clock.reads == 0
    assert clock.sleeps == []


@pytest.mark.parametrize(("timeout", "poll_interval"), [(0, 1), (0.0, 1.5), (None, 1.0)])
def test_lakehouse_wait_accepts_finite_integer_float_and_none_polling_values(
    monkeypatch: pytest.MonkeyPatch, timeout: float | None, poll_interval: float
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    source = _snapshot(done=True)

    assert source.wait(timeout=timeout, poll_interval=poll_interval) is source
    assert clock.reads == 0
    assert clock.sleeps == []


def test_lakehouse_get_retries_one_transient_failure_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    responses = [
        httpx.Response(503, json={"code": "UNAVAILABLE", "message": "try again"}),
        httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}}),
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    sleeps: list[float] = []
    monkeypatch.setattr("datalens_sdk.http.time.sleep", sleeps.append)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client:
        operation = client.get.lakehouse_operation(by_id="operation-1")

    assert operation.id == "operation-1"
    assert [json.loads(request.content) for request in requests] == [{"operationId": "operation-1"}] * 2
    assert sleeps == [0.1]


def test_lakehouse_wait_uses_service_retry_without_outer_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    requests: list[httpx.Request] = []
    responses = [
        httpx.Response(503, json={"message": "try again"}),
        httpx.Response(200, json={"id": "operation-1", "done": True, "metadata": {}}),
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)

    class CountingService(LakehouseOperationService):
        def __init__(self, *, api: LakehouseOperationAPI) -> None:
            super().__init__(api=api)
            self.calls: list[str] = []

        def get_lakehouse_operation(self, operation_id: str) -> LakehouseOperation:
            self.calls.append(operation_id)
            return super().get_lakehouse_operation(operation_id)

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://lakehouse.test",
        transport=httpx.MockTransport(handle),
    ) as http_client:
        service = CountingService(api=LakehouseOperationAPI(http_client))
        result = replace(_snapshot(), _operations=service).wait(timeout=5.0)

    assert result.done is True
    assert service.calls == ["operation-1"]
    assert [json.loads(request.content) for request in requests] == [{"operationId": "operation-1"}] * 2
    assert clock.sleeps == [0.1]


@pytest.mark.parametrize(
    ("failure", "expected_error", "attempts"),
    [
        ("api", ForbiddenError, 1),
        ("transport", DataLensTransportError, 3),
        ("dto", DTOValidationError, 1),
        ("invalid_response", InvalidResponseError, 1),
    ],
)
def test_lakehouse_wait_propagates_api_transport_and_dto_errors(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_error: type[Exception],
    attempts: int,
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "api":
            return httpx.Response(
                403,
                json={"code": "DENIED", "message": "access denied"},
                headers={"x-request-id": "lakehouse-denied"},
            )
        if failure == "transport":
            raise httpx.ConnectError("network down", request=request)
        if failure == "dto":
            return httpx.Response(200, json={"id": "operation-1", "done": "yes", "metadata": {}})
        return httpx.Response(200, json=["not an operation"])

    with DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://lakehouse.test",
        transport=httpx.MockTransport(handle),
    ) as http_client:
        source = replace(_snapshot(), _operations=_lakehouse_service(http_client))
        with pytest.raises(expected_error) as raised:
            source.wait(timeout=10.0)

    assert len(requests) == attempts
    assert clock.sleeps == ([0.1, 0.2] if failure == "transport" else [])
    if failure == "api":
        api_error = cast(DataLensAPIError, raised.value)
        assert api_error.context == APIErrorContext(
            status_code=403,
            code="DENIED",
            message="access denied",
            request_url="https://lakehouse.test/rpc/getLakehouseOperation",
            request_id="lakehouse-denied",
            request_method="POST",
        )
    elif failure == "transport":
        transport_error = cast(DataLensTransportError, raised.value)
        assert transport_error.attempts == 3
        assert transport_error.reason == "network down"
    else:
        assert "getLakehouseOperation" in str(raised.value)


def test_lakehouse_read_ignores_unknown_fields_at_every_object_level() -> None:
    response: dict[str, object] = {
        "id": "operation-1",
        "done": True,
        "metadata": {"futureMetadata": {"nested": True}},
        "createdAt": {"seconds": "1727700000", "nanos": 0, "futureTimestamp": "value"},
        "modifiedAt": {"seconds": "1727700001", "futureTimestamp": 1},
        "error": {"code": 0, "message": "failed", "details": [{"futureDetail": True}], "futureError": "value"},
        "response": {"futureResponse": {"nested": False}},
        "futureOperation": "value",
    }
    recorder = RecordedLakehouseTransport(response)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with client:
        operation = client.get.lakehouse_operation(by_id="operation-1")

    assert operation == LakehouseOperation(
        id="operation-1",
        done=True,
        metadata={"futureMetadata": {"nested": True}},
        created_at=LakehouseTimestamp(seconds="1727700000", nanos=0),
        modified_at=LakehouseTimestamp(seconds="1727700001"),
        error=LakehouseOperationError(code=0, message="failed", details=({"futureDetail": True},)),
        response={"futureResponse": {"nested": False}},
        raw=response,
    )


def test_lakehouse_read_normalizes_null_metadata_and_preserves_raw_response() -> None:
    response: dict[str, object] = {"id": "operation-1", "done": False, "metadata": None}
    recorder = RecordedLakehouseTransport(response)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        operation = client.get.lakehouse_operation(by_id="operation-1")

    assert operation == LakehouseOperation(id="operation-1", done=False, metadata={}, raw=response)


def test_lakehouse_get_ignores_unknown_python_timestamp_name() -> None:
    response: dict[str, object] = {
        "id": "operation-1",
        "done": False,
        "metadata": {},
        "created_at": {"seconds": "1727700000", "nanos": 0},
    }
    recorder = RecordedLakehouseTransport(response)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        operation = client.get.lakehouse_operation(by_id="operation-1")

    assert operation == LakehouseOperation(id="operation-1", done=False, metadata={}, raw=response)
    assert recorder.bodies() == [{"operationId": "operation-1"}]


def test_lakehouse_refresh_ignores_unknown_python_creator_name() -> None:
    initial: dict[str, object] = {"id": "operation-1", "done": False, "metadata": {}}
    refreshed_response: dict[str, object] = {
        "id": "operation-1",
        "done": True,
        "metadata": {},
        "created_by": "not-a-wire-field",
    }
    recorder = RecordedLakehouseTransport(initial, refreshed_response)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))

    with client:
        source = client.get.lakehouse_operation(by_id="operation-1")
        refreshed = source.refresh()

    assert source == LakehouseOperation(id="operation-1", done=False, metadata={}, raw=initial)
    assert refreshed == LakehouseOperation(id="operation-1", done=True, metadata={}, raw=refreshed_response)
    assert recorder.bodies() == [{"operationId": "operation-1"}] * 2


@pytest.mark.parametrize(
    "invalid_response",
    [
        {"done": False, "metadata": {}},
        {"id": "operation-1", "metadata": {}},
        {"id": "operation-1", "done": False},
        {"id": "operation-1", "done": False, "metadata": {}, "createdAt": {"nanos": 0}},
        {"id": "operation-1", "done": False, "metadata": {}, "error": {"message": "failed"}},
        {"id": "operation-1", "done": False, "metadata": {}, "error": {"code": 0}},
    ],
    ids=["id", "done", "metadata", "timestamp-seconds", "error-code", "error-message"],
)
def test_lakehouse_missing_required_or_malformed_nested_field_names_operation(
    invalid_response: dict[str, object],
) -> None:
    recorder = RecordedLakehouseTransport(invalid_response)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with (
        client,
        pytest.raises((DTOValidationError, InvalidResponseError)) as raised,
    ):
        client.get.lakehouse_operation(by_id="operation-1")

    assert "getLakehouseOperation" in str(raised.value)
    assert len(recorder.requests) == 1


def test_lakehouse_request_validation_does_not_leak_pydantic_error() -> None:
    recorder = RecordedLakehouseTransport()
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handle))
    with (
        client,
        pytest.raises(DTOValidationError, match="getLakehouseOperation"),
    ):
        client.get.lakehouse_operation(by_id="x" * 51)

    assert recorder.requests == []


def test_lakehouse_timeout_error_exposes_operation_id_timeout_and_latest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    _install_clock(monkeypatch, clock)
    latest = replace(_snapshot(), metadata={"stage": "processing"})
    operations = FakeOperations(latest, clock=clock, delay=3.0)
    source = _bind(_snapshot(), operations)

    with pytest.raises(DataLensOperationTimeoutError) as raised:
        source.wait(timeout=2.0)

    assert isinstance(raised.value, DataLensError)
    assert isinstance(raised.value, TimeoutError)
    assert raised.value.operation_id == "operation-1"
    assert raised.value.timeout == 2.0
    assert raised.value.last_operation is operations.last_returned
    assert raised.value.last_operation.metadata == {"stage": "processing"}
    assert "operation-1" in str(raised.value)
    assert "2.0" in str(raised.value)
    assert operations.calls == ["operation-1"]
    assert clock.sleeps == []
