from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from datalens_sdk.errors import DatalensValidationError
from datalens_sdk.serialization.artifacts import sanitize_artifact_component
from datalens_sdk.serialization.json_io import _write_text_file_exclusive

TABS_DIRECTORY = "Tabs"
_MARKDOWN_TABS = frozenset({"documentation_en", "documentation_ru"})


def materialize_editor_tabs(artifact_root: Path, data: Mapping[str, object]) -> None:
    tabs_directory = artifact_root / TABS_DIRECTORY
    tabs_directory.mkdir(mode=0o700)
    for tab, content in sorted(data.items()):
        if content is None:
            continue
        if not isinstance(content, str):
            continue
        suffix = ".md" if tab in _MARKDOWN_TABS else ".js"
        filename = f"{sanitize_artifact_component(tab)}{suffix}"
        try:
            _write_text_file_exclusive(tabs_directory / filename, content)
        except FileExistsError as exc:
            raise DatalensValidationError(f"Editor tab names collide after artifact sanitization: {tab!r}") from exc
