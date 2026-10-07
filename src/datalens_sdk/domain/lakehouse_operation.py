from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from numbers import Real
import time

from datalens_sdk.domain.ports import LakehouseOperationOperations
from datalens_sdk.errors import (
    DataLensConfigurationError,
    DataLensOperationTimeoutError,
    DataLensValidationError,
)


def _finite_number(value: object, *, name: str, allow_zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DataLensValidationError(f"{name} must be a finite real number")
    if value < 0 or (value == 0 and not allow_zero):
        comparison = "non-negative" if allow_zero else "positive"
        raise DataLensValidationError(f"{name} must be a finite {comparison} real number")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise DataLensValidationError(f"{name} must be a finite real number") from exc
    if numeric == 0 and value != 0:
        numeric = math.nextafter(0.0, math.inf)
    if not math.isfinite(numeric) or (numeric == 0 and not allow_zero):
        comparison = "non-negative" if allow_zero else "positive"
        raise DataLensValidationError(f"{name} must be a finite {comparison} real number")
    return numeric


@dataclass(frozen=True, slots=True)
class LakehouseTimestamp:
    seconds: str
    nanos: int | float | None = None


@dataclass(frozen=True, slots=True)
class LakehouseOperationError:
    code: int | float
    message: str
    details: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class LakehouseOperation:
    id: str
    done: bool
    metadata: Mapping[str, object]
    created_by: str | None = None
    description: str | None = None
    created_at: LakehouseTimestamp | None = None
    modified_at: LakehouseTimestamp | None = None
    error: LakehouseOperationError | None = None
    response: Mapping[str, object] | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    _operations: LakehouseOperationOperations | None = field(default=None, repr=False, compare=False)

    def refresh(self) -> LakehouseOperation:
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("operation id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Lakehouse operation is not bound to client operations")
        return self._operations.get_lakehouse_operation(self.id)

    def wait(
        self,
        *,
        timeout: float | None = 600.0,
        poll_interval: float = 2.0,
    ) -> LakehouseOperation:
        validated_timeout = None if timeout is None else _finite_number(timeout, name="timeout", allow_zero=True)
        interval = _finite_number(poll_interval, name="poll_interval", allow_zero=False)
        if self.done:
            return self
        if not isinstance(self.id, str) or not self.id:
            raise DataLensValidationError("operation id must be a non-empty string")
        if self._operations is None:
            raise DataLensConfigurationError("Lakehouse operation is not bound to client operations")

        current = self
        deadline = None if validated_timeout is None else time.monotonic() + validated_timeout
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                assert validated_timeout is not None
                raise DataLensOperationTimeoutError(
                    operation_id=self.id,
                    timeout=validated_timeout,
                    last_operation=current,
                )
            current = current.refresh()
            if current.done:
                return current
            if deadline is None:
                time.sleep(interval)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                assert validated_timeout is not None
                raise DataLensOperationTimeoutError(
                    operation_id=self.id,
                    timeout=validated_timeout,
                    last_operation=current,
                )
            time.sleep(min(interval, remaining))
