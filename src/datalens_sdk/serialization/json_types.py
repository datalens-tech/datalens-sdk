from __future__ import annotations

from collections.abc import Mapping
import math
from typing import TYPE_CHECKING, TypeAlias

from typing_extensions import TypeAliasType

from datalens_sdk.errors import DataLensValidationError

JsonScalar: TypeAlias = str | int | float | bool | None
if TYPE_CHECKING:
    JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
else:
    JsonValue = TypeAliasType(
        "JsonValue",
        JsonScalar | list["JsonValue"] | dict[str, "JsonValue"],
    )
JsonObject: TypeAlias = Mapping[str, JsonValue]


def normalize_json_value(value: object, *, context: str = "JSON value") -> JsonValue:
    """Validate a JSON value and return an owned, acyclic deep copy."""

    return _normalize_json_value(value, context=context, active_containers=set())


def normalize_json_object(value: object, *, context: str = "JSON object") -> dict[str, JsonValue]:
    normalized = normalize_json_value(value, context=context)
    if not isinstance(normalized, dict):
        raise DataLensValidationError(f"{context} must be an object")
    return normalized


def _normalize_json_value(
    value: object,
    *,
    context: str,
    active_containers: set[int],
) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DataLensValidationError(f"{context} contains a non-finite number")
        return value
    if isinstance(value, list):
        container_id = id(value)
        if container_id in active_containers:
            raise DataLensValidationError(f"{context} contains a cycle")
        active_containers.add(container_id)
        try:
            return [
                _normalize_json_value(
                    item,
                    context=f"{context}[{index}]",
                    active_containers=active_containers,
                )
                for index, item in enumerate(value)
            ]
        finally:
            active_containers.remove(container_id)
    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_containers:
            raise DataLensValidationError(f"{context} contains a cycle")
        active_containers.add(container_id)
        try:
            normalized: dict[str, JsonValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise DataLensValidationError(f"{context} contains a non-string object key")
                normalized[key] = _normalize_json_value(
                    item,
                    context=f"{context}.{key}",
                    active_containers=active_containers,
                )
            return normalized
        finally:
            active_containers.remove(container_id)
    raise DataLensValidationError(f"{context} contains unsupported Python value {type(value).__name__}")
