from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

_T = TypeVar("_T")

_RLS2_FIELD = "rls2"
_RLS_FIELD_PREFIX = _RLS2_FIELD.removesuffix("2")


def with_supported_rls2_state(state: Mapping[str, _T]) -> dict[str, _T]:
    """Keep only the supported representation from the row-level-security field family."""

    return {key: value for key, value in state.items() if not key.startswith(_RLS_FIELD_PREFIX) or key == _RLS2_FIELD}
