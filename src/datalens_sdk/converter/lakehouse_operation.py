from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.lakehouse_operation import LakehouseOperation, LakehouseOperationError, LakehouseTimestamp
from datalens_sdk.domain.ports import LakehouseOperationOperations
from datalens_sdk.errors import translate_invalid_response_error


class LakehouseOperationWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class LakehouseOperationWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> LakehouseOperationWriteDTOProtocol: ...


class LakehouseOperationReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> object: ...


class LakehouseTimestampReadDTOProtocol(Protocol):
    @property
    def seconds(self) -> str: ...

    @property
    def nanos(self) -> int | float | None: ...


class LakehouseOperationReadDTOProtocol(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def done(self) -> bool: ...

    @property
    def created_by(self) -> str | None: ...

    @property
    def description(self) -> str | None: ...

    @property
    def created_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...

    @property
    def modified_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...


class LakehouseOperationReadDtoModule(Protocol):
    LakehouseOperationReadDTO: LakehouseOperationReadDTOClass


class LakehouseOperationDtoModule(LakehouseOperationReadDtoModule, Protocol):
    GetLakehouseOperationArgsDTO: LakehouseOperationWriteDTOClass


def _dto_module(dto_module: LakehouseOperationReadDtoModule | None) -> LakehouseOperationReadDtoModule:
    return cast(LakehouseOperationReadDtoModule, generated_dto if dto_module is None else dto_module)


def _numeric_from_raw(value: object, *, field: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} is not a JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} is not a finite JSON number")
    return value


def lakehouse_timestamp_from_dto(
    raw: Mapping[str, object] | None,
    *,
    dto: LakehouseTimestampReadDTOProtocol | None,
) -> LakehouseTimestamp | None:
    if raw is None and dto is None:
        return None
    if raw is None or dto is None:
        raise ValueError("timestamp response and validated DTO disagree")
    if not isinstance(raw, Mapping):
        raise TypeError("timestamp is not an object")
    if not isinstance(dto.seconds, str):
        raise TypeError("timestamp seconds is not a string")
    nanos = _numeric_from_raw(raw["nanos"], field="timestamp nanos") if "nanos" in raw else None
    return LakehouseTimestamp(seconds=dto.seconds, nanos=nanos)


def _raw_timestamp(raw: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} is not an object")
    return cast(Mapping[str, object], value)


class LakehouseOperationConverter:
    @staticmethod
    def from_domain_get(
        operation_id: str,
        *,
        dto_module: LakehouseOperationDtoModule | None = None,
    ) -> LakehouseOperationWriteDTOProtocol:
        generated = cast(LakehouseOperationDtoModule, _dto_module(dto_module))
        return generated.GetLakehouseOperationArgsDTO.model_validate({"operationId": operation_id})

    @staticmethod
    def to_operation(
        raw: Mapping[str, object],
        *,
        operations: LakehouseOperationOperations | None,
        operation: str = "getLakehouseOperation",
        dto_module: LakehouseOperationReadDtoModule | None = None,
    ) -> LakehouseOperation:
        if not isinstance(operation, str) or not operation:
            raise ValueError("operation context must be a non-empty string")
        generated = _dto_module(dto_module)
        validated = cast(LakehouseOperationReadDTOProtocol, generated.LakehouseOperationReadDTO.model_validate(raw))
        try:
            metadata = raw["metadata"]
            if not isinstance(metadata, Mapping):
                raise TypeError("metadata is not an object")
            created_at = lakehouse_timestamp_from_dto(_raw_timestamp(raw, "createdAt"), dto=validated.created_at)
            modified_at = lakehouse_timestamp_from_dto(_raw_timestamp(raw, "modifiedAt"), dto=validated.modified_at)
            raw_error = raw.get("error")
            error = None
            if raw_error is not None:
                if not isinstance(raw_error, Mapping):
                    raise TypeError("error is not an object")
                code = _numeric_from_raw(raw_error["code"], field="error code")
                details = raw_error.get("details", ())
                if not isinstance(details, (list, tuple)):
                    raise TypeError("error details is not an array")
                message = raw_error["message"]
                if not isinstance(message, str):
                    raise TypeError("error message is not a string")
                error = LakehouseOperationError(code=code, message=message, details=tuple(details))
            response = raw.get("response")
            if response is not None and not isinstance(response, Mapping):
                raise TypeError("response is not an object")
            return LakehouseOperation(
                id=validated.id,
                done=validated.done,
                metadata=cast(Mapping[str, object], metadata),
                created_by=validated.created_by,
                description=validated.description,
                created_at=created_at,
                modified_at=modified_at,
                error=error,
                response=cast(Mapping[str, object] | None, response),
                raw=dict(raw),
                _operations=operations,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation=operation, reason=str(exc)) from exc
