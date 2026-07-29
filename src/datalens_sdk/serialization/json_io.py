from __future__ import annotations

from collections.abc import Callable
import ctypes
import errno
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import NoReturn

from datalens_sdk.errors import DatalensConfigurationError, DatalensValidationError
from datalens_sdk.serialization.json_types import JsonObject, JsonValue, normalize_json_object

_ATOMIC_NO_REPLACE_UNSUPPORTED_ERRNOS = frozenset(
    {
        errno.EINVAL,
        errno.ENOSYS,
        *(
            error_number
            for name in ("ENOTSUP", "EOPNOTSUPP")
            if (error_number := getattr(errno, name, None)) is not None
        ),
    }
)


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant {value}")


def read_json_object(path: Path) -> dict[str, JsonValue]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value: object = json.load(stream, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise DatalensValidationError(f"Cannot read JSON object from {path}: invalid JSON") from exc
    except OSError as exc:
        raise DatalensValidationError(f"Cannot read JSON object from {path}: {exc.strerror or exc}") from exc
    return normalize_json_object(value, context=f"JSON file {path}")


def write_artifact_directory(
    path: str | os.PathLike[str],
    *,
    filename: str,
    value: JsonObject,
    populate: Callable[[Path], None] | None = None,
) -> Path:
    target = Path(path)
    parent = target.parent
    if target.exists():
        raise DatalensValidationError(f"Artifact path already exists: {target}")
    if not parent.is_dir():
        raise DatalensValidationError(f"Artifact parent directory does not exist: {parent}")

    snapshot = normalize_json_object(value, context=f"{filename} snapshot")
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=parent))
    try:
        _write_json_file_exclusive(staging / filename, snapshot)
        if populate is not None:
            populate(staging)
        _rename_directory_no_replace(staging, target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return target


def _write_json_file_exclusive(path: Path, value: JsonObject) -> None:
    _write_text_file_exclusive(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    )


def _write_text_file_exclusive(path: Path, value: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _rename_directory_no_replace(source: Path, target: Path) -> None:
    if sys.platform.startswith("linux"):
        _rename_directory_linux(source, target)
        return
    if sys.platform == "darwin":
        _rename_directory_macos(source, target)
        return
    if _is_windows():  # type: ignore[unreachable]
        _rename_directory_windows(source, target)
        return
    raise DatalensConfigurationError(f"Atomic no-replace artifact commit is not supported on platform {sys.platform!r}")


def _is_windows() -> bool:
    return os.name == "nt"


def _rename_directory_linux(source: Path, target: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    if renameat2 is None:
        raise DatalensConfigurationError("Atomic no-replace artifact commit requires renameat2 on Linux")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(target),
        1,
    )
    if result != 0:
        _raise_rename_error(target)


def _rename_directory_macos(source: Path, target: Path) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    renamex_np = getattr(library, "renamex_np", None)
    if renamex_np is None:
        raise DatalensConfigurationError("Atomic no-replace artifact commit requires renamex_np on macOS")
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    result = renamex_np(os.fsencode(source), os.fsencode(target), 0x00000004)
    if result != 0:
        _raise_rename_error(target)


def _rename_directory_windows(source: Path, target: Path) -> None:
    try:
        os.rename(source, target)
    except OSError as exc:
        if exc.errno in (errno.EEXIST, errno.ENOTEMPTY) or target.exists():
            raise DatalensValidationError(f"Artifact path already exists: {target}") from exc
        raise


def _raise_rename_error(target: Path) -> NoReturn:
    error_number = ctypes.get_errno()
    if error_number in (errno.EEXIST, errno.ENOTEMPTY):
        raise DatalensValidationError(f"Artifact path already exists: {target}")
    if error_number in _ATOMIC_NO_REPLACE_UNSUPPORTED_ERRNOS:
        raise DatalensConfigurationError(
            "Atomic no-replace artifact commit is not supported by the current operating system or filesystem"
        )
    raise OSError(error_number, os.strerror(error_number), target)
