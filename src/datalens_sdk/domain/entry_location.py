from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Set
from dataclasses import dataclass
from typing import Literal, TypeAlias

from datalens_sdk.errors import DataLensValidationError, NotSupportedError

EntryLocationKind: TypeAlias = Literal["path", "workbook", "collection"]


def _required_string(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DataLensValidationError(f"{field} must not be empty")
    return value


class EntryLocation(ABC):
    """A destination container for a new DataLens entry."""

    @classmethod
    def path(cls, dir_path: str) -> EntryLocation:
        normalized = _required_string(dir_path, field="dir_path").rstrip("/") or "/"
        return _EntryLocationRef(kind="path", value=normalized)

    @classmethod
    def workbook(cls, workbook_id: str) -> EntryLocation:
        return _EntryLocationRef(
            kind="workbook",
            value=_required_string(workbook_id, field="workbook_id"),
        )

    @classmethod
    def collection(cls, collection_id: str) -> EntryLocation:
        return _EntryLocationRef(
            kind="collection",
            value=_required_string(collection_id, field="collection_id"),
        )

    @abstractmethod
    def _as_entry_location(self) -> EntryLocation:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _EntryLocationRef(EntryLocation):
    kind: EntryLocationKind
    value: str
    installation: str = ""

    def _as_entry_location(self) -> EntryLocation:
        return self


def _location_ref(location: EntryLocation) -> _EntryLocationRef:
    ref = location._as_entry_location()
    if not isinstance(ref, _EntryLocationRef):
        raise DataLensValidationError("EntryLocation did not resolve to a supported destination")
    return ref


def resolve_entry_location(
    *,
    location: EntryLocation,
    installation: str,
    allowed_kinds: Set[EntryLocationKind] | None = None,
    context: str = "Entry creation",
) -> EntryLocation:
    if not isinstance(location, EntryLocation):
        raise DataLensValidationError("location must be an EntryLocation")
    source_installation = getattr(location, "installation", "")
    if source_installation and source_installation != installation:
        raise NotSupportedError(f"Cannot use a {source_installation!r} destination on installation {installation!r}")
    ref = _location_ref(location)
    if allowed_kinds is not None and ref.kind not in allowed_kinds:
        expected = ", ".join(sorted(allowed_kinds))
        raise DataLensValidationError(f"{context} requires location kind {expected!r}, got {ref.kind!r}")
    return ref


def validate_entry_name(*, name: str, location: EntryLocation | None = None) -> None:
    _required_string(name, field="name")
    if location is not None and dir_path_from_location(location) is not None and "/" in name:
        raise DataLensValidationError("name must not contain '/' for path locations")


def _dir_path_from_key(key: str | None) -> str | None:
    if not key:
        return None
    trimmed = key.rstrip("/")
    if not trimmed or "/" not in trimmed:
        return None
    dir_path = trimmed.rsplit("/", 1)[0]
    return dir_path or "/"


def _path_from_parts(*, dir_path: str | None, name: str | None) -> str | None:
    if not dir_path or not name:
        return None
    return f"{dir_path.rstrip('/')}/{name}"


def resolve_entry_location_from_api_fields(
    *,
    dir_path: str | None,
    key: str | None,
    collection_id: str | None,
    workbook_id: str | None,
    fallback: EntryLocation | None = None,
) -> EntryLocation | None:
    if collection_id is not None and workbook_id is not None:
        raise DataLensValidationError("collection_id and workbook_id can not both be set")
    if collection_id is not None:
        return EntryLocation.collection(collection_id)
    if workbook_id is not None:
        return EntryLocation.workbook(workbook_id)
    path_dir = dir_path or _dir_path_from_key(key)
    if path_dir is not None:
        return EntryLocation.path(path_dir)
    return fallback


def location_kind(location: EntryLocation) -> EntryLocationKind:
    return _location_ref(location).kind


def dir_path_from_location(location: EntryLocation | None) -> str | None:
    if location is None:
        return None
    ref = _location_ref(location)
    return ref.value if ref.kind == "path" else None


def key_from_location(location: EntryLocation | None, *, name: str | None) -> str | None:
    return _path_from_parts(dir_path=dir_path_from_location(location), name=name)


def collection_id_from_location(location: EntryLocation | None) -> str | None:
    if location is None:
        return None
    ref = _location_ref(location)
    return ref.value if ref.kind == "collection" else None


def workbook_id_from_location(location: EntryLocation | None) -> str | None:
    if location is None:
        return None
    ref = _location_ref(location)
    return ref.value if ref.kind == "workbook" else None
