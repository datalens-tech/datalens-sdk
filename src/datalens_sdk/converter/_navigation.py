from __future__ import annotations


def name_from_key(key: str | None) -> str | None:
    if not key:
        return None
    trimmed = key.rstrip("/")
    if not trimmed:
        return None
    name = trimmed.rsplit("/", 1)[-1]
    return name or None


def dir_path_from_key(key: str | None) -> str | None:
    if not key:
        return None
    trimmed = key.rstrip("/")
    if not trimmed or "/" not in trimmed:
        return None
    dir_path = trimmed.rsplit("/", 1)[0]
    return dir_path or "/"


def key_from_parts(*, dir_path: str | None, name: str | None) -> str | None:
    if not dir_path or not name:
        return None
    return f"{dir_path.rstrip('/')}/{name}"
