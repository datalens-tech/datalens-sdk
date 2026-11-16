from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TypeAlias

from datalens_sdk.errors import DataLensValidationError

RuntimeParamValue: TypeAlias = str | Sequence[str]
RuntimeParams: TypeAlias = Mapping[str, RuntimeParamValue]
NormalizedRuntimeParams: TypeAlias = Mapping[str, str | tuple[str, ...]]


def normalize_param_value(key: str, value: object, *, context: str = "Runtime") -> str | tuple[str, ...]:
    """Snapshot a scalar string or an ordered sequence of strings."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)) or not isinstance(value, Sequence):
        raise DataLensValidationError(f"{context} parameter {key!r} must be a string or a sequence of strings")
    items = tuple(value)
    if any(not isinstance(item, str) for item in items):
        raise DataLensValidationError(f"{context} parameter {key!r} must contain only strings")
    return items


def normalize_params(params: RuntimeParams | None, *, context: str = "Runtime") -> NormalizedRuntimeParams:
    """Own parameter containers without applying an operation's name policy."""
    if params is None:
        return MappingProxyType({})
    if not isinstance(params, Mapping):
        raise DataLensValidationError(f"{context} params must be a mapping of parameter names to values")
    normalized: dict[str, str | tuple[str, ...]] = {}
    for key, value in params.items():
        if not isinstance(key, str):
            raise DataLensValidationError(f"{context} parameter names must be strings")
        normalized[key] = normalize_param_value(key, value, context=context)
    return MappingProxyType(normalized)
