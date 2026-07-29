from __future__ import annotations

from collections.abc import Mapping

_ENTRY_ID_KEYS: tuple[str, ...] = ("entryId", "entry_id", "id")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _read_response_id(raw: Mapping[str, object], *, keys: tuple[str, ...] = _ENTRY_ID_KEYS) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None
