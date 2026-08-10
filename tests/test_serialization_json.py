from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization import json_io
from datalens_sdk.serialization.artifacts import artifact_directory_path, sanitize_artifact_component
from datalens_sdk.serialization.json_io import read_json_object, write_artifact_directory
from datalens_sdk.serialization.json_types import JsonObject, normalize_json_object


def test_normalize_json_object_returns_an_owned_deep_copy() -> None:
    source: dict[str, object] = {"nested": [{"value": 1}], "unicode": "Привет"}

    normalized = normalize_json_object(source)
    cast(dict[str, object], cast(list[object], source["nested"])[0])["value"] = 2

    assert normalized == {"nested": [{"value": 1}], "unicode": "Привет"}


def test_normalize_json_object_accepts_every_json_value_type_and_preserves_key_order() -> None:
    source: dict[str, object] = {
        "null": None,
        "boolean": True,
        "integer": 7,
        "float": 1.25,
        "string": "Привет",
        "array": [None, False, 3, 2.5, "value", {"nested": []}],
        "object": {"first": 1, "second": 2},
    }

    normalized = normalize_json_object(source)

    assert normalized == source
    assert list(normalized) == list(source)
    assert list(cast(dict[str, object], normalized["object"])) == ["first", "second"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_normalize_json_object_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(DataLensValidationError, match="non-finite"):
        normalize_json_object({"value": value})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({1: "value"}, "non-string"),
        ({"value": ("not", "json")}, "unsupported Python value tuple"),
        (["not", "an", "object"], "must be an object"),
    ],
)
def test_normalize_json_object_rejects_non_json_shapes(value: object, message: str) -> None:
    with pytest.raises(DataLensValidationError, match=message):
        normalize_json_object(value)


def test_normalize_json_object_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)

    with pytest.raises(DataLensValidationError, match="cycle"):
        normalize_json_object({"value": value})


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_read_json_object_rejects_nonstandard_constants(tmp_path: Path, constant: str) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(f'{{"value": {constant}}}', encoding="utf-8")

    with pytest.raises(DataLensValidationError, match="invalid JSON"):
        read_json_object(path)


def test_read_json_object_rejects_invalid_utf8_and_non_object_root(tmp_path: Path) -> None:
    invalid_utf8 = tmp_path / "invalid-utf8.json"
    invalid_utf8.write_bytes(b'{"value":"\xff"}')

    with pytest.raises(DataLensValidationError, match="invalid JSON"):
        read_json_object(invalid_utf8)


@pytest.mark.parametrize("document", ["[]", '"text"', "42", "true", "null"])
def test_read_json_object_rejects_non_object_roots(tmp_path: Path, document: str) -> None:
    path = tmp_path / "non-object.json"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(DataLensValidationError, match="must be an object"):
        read_json_object(path)


def test_read_json_object_reports_broken_json_without_echoing_content(tmp_path: Path) -> None:
    secret_marker = "do-not-echo-this-secret"
    path = tmp_path / "broken.json"
    path.write_text(f'{{"secret": "{secret_marker}"', encoding="utf-8")

    with pytest.raises(DataLensValidationError, match="invalid JSON") as exc_info:
        read_json_object(path)

    assert secret_marker not in str(exc_info.value)


def test_write_artifact_directory_formats_utf8_and_commits_exclusively(tmp_path: Path) -> None:
    target = tmp_path / "artifact"
    value: JsonObject = {"unicode": "Привет", "nested": {"value": 1}}

    result = write_artifact_directory(target, filename="dataset.json", value=value)

    assert result == target
    main_file = target / "dataset.json"
    assert main_file.read_text(encoding="utf-8") == (
        '{\n  "unicode": "Привет",\n  "nested": {\n    "value": 1\n  }\n}\n'
    )
    assert json.loads(main_file.read_text(encoding="utf-8")) == value
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o700
        assert main_file.stat().st_mode & 0o777 == 0o600

    with pytest.raises(DataLensValidationError, match="already exists"):
        write_artifact_directory(target, filename="dataset.json", value=value)
    assert not tuple(tmp_path.glob(".artifact.staging-*"))


@pytest.mark.parametrize("target_kind", ["directory", "file"])
def test_write_artifact_directory_rejects_existing_empty_target(tmp_path: Path, target_kind: str) -> None:
    target = tmp_path / "artifact"
    if target_kind == "directory":
        target.mkdir()
    else:
        target.touch()

    with pytest.raises(DataLensValidationError, match="already exists"):
        write_artifact_directory(target, filename="dataset.json", value={"dataset": {}})

    assert target.exists()
    assert not tuple(tmp_path.glob(".artifact.staging-*"))


@pytest.mark.parametrize("dangling", [False, True])
def test_write_artifact_directory_rejects_existing_symlink(tmp_path: Path, dangling: bool) -> None:
    target = tmp_path / "artifact"
    destination = tmp_path / "destination"
    if not dangling:
        destination.mkdir()
    try:
        target.symlink_to(destination, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are not available: {exc}")

    with pytest.raises(DataLensValidationError, match="already exists"):
        write_artifact_directory(target, filename="dataset.json", value={"dataset": {}})

    assert target.is_symlink()
    assert not tuple(tmp_path.glob(".artifact.staging-*"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Sales", "Sales"),
        ("Sales/2026", "Sales_2026"),
        ("Sales\\2026", "Sales_2026"),
        ("..", "_"),
        (".", "_"),
        ("CON", "_CON"),
        ("CON.txt", "_CON.txt"),
        ("lpt9.report", "_lpt9.report"),
        ("bad\x00name.", "bad_name"),
        ("bad\nname", "bad_name"),
    ],
)
def test_sanitize_artifact_component_is_portable(value: str, expected: str) -> None:
    assert sanitize_artifact_component(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Sales/2026", "Sales_2026 [dataset_1]"),
    ],
)
def test_artifact_directory_path_uses_name_and_id(
    tmp_path: Path,
    name: str | None,
    expected: str,
) -> None:
    target = artifact_directory_path(
        tmp_path,
        name=name,
        resource_id="dataset:1",
        resource="Dataset",
    )

    assert target == tmp_path / expected


@pytest.mark.parametrize("name", [None, "", "   "])
def test_artifact_directory_path_requires_nonblank_resource_name(
    tmp_path: Path,
    name: str | None,
) -> None:
    with pytest.raises(DataLensValidationError, match="requires a resource name"):
        artifact_directory_path(tmp_path, name=name, resource_id="dataset-id", resource="Dataset")


@pytest.mark.parametrize("resource_id", [None, "", "   "])
def test_artifact_directory_path_requires_nonblank_resource_id(
    tmp_path: Path,
    resource_id: str | None,
) -> None:
    with pytest.raises(DataLensValidationError, match="requires a resource id"):
        artifact_directory_path(tmp_path, name=None, resource_id=resource_id, resource="Dataset")


def test_write_artifact_directory_cleans_staging_when_atomic_commit_loses_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact"

    def lose_race(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "foreign.txt").write_text("belongs to another writer", encoding="utf-8")
        raise DataLensValidationError(f"Artifact path already exists: {destination}")

    monkeypatch.setattr(json_io, "_rename_directory_no_replace", lose_race)

    with pytest.raises(DataLensValidationError, match="already exists"):
        write_artifact_directory(target, filename="dataset.json", value={"dataset": {}})

    assert target.is_dir()
    assert (target / "foreign.txt").read_text(encoding="utf-8") == "belongs to another writer"
    assert not tuple(tmp_path.glob(".artifact.staging-*"))


def test_write_artifact_directory_cleans_staging_and_keeps_target_absent_on_populate_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "artifact"

    def fail_populate(staging: Path) -> None:
        (staging / "partial").mkdir()
        raise RuntimeError("dependency export failed")

    with pytest.raises(RuntimeError, match="dependency export failed"):
        write_artifact_directory(
            target,
            filename="dashboard.json",
            value={"entry": {"data": {}}},
            populate=fail_populate,
        )

    assert not target.exists()
    assert not tuple(tmp_path.glob(".artifact.staging-*"))


@pytest.mark.parametrize("error_name", ["EINVAL", "ENOSYS", "ENOTSUP", "EOPNOTSUPP"])
def test_atomic_commit_reports_unsupported_operating_system_or_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
) -> None:
    error_number = getattr(errno, error_name, None)
    if error_number is None:
        pytest.skip(f"{error_name} is not defined on this platform")
    monkeypatch.setattr(ctypes, "get_errno", lambda: error_number)

    with pytest.raises(DataLensConfigurationError, match="operating system or filesystem"):
        json_io._raise_rename_error(tmp_path / "artifact")
