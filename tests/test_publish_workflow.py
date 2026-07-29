from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import runpy
import subprocess
import sys
from types import FunctionType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_publish_ref.py"
RELEASE_CHECK_SCRIPT = ROOT / "scripts" / "check_release.py"


def _load_release_validation() -> tuple[FunctionType, type[Any]]:
    namespace = runpy.run_path(str(SCRIPT))
    validate = cast(FunctionType, namespace["validate_publish_ref"])
    publish_target = cast(type[Any], namespace["PublishTarget"])
    return validate, publish_target


def test_current_release_metadata_passes_release_check() -> None:
    subprocess.run([sys.executable, str(RELEASE_CHECK_SCRIPT)], cwd=ROOT, check=True)


def test_testpypi_dispatch_must_run_from_main(monkeypatch: pytest.MonkeyPatch) -> None:
    validate, publish_target = _load_release_validation()
    checked_tags: list[str | None] = []
    monkeypatch.setitem(validate.__globals__, "_check_release", lambda tag=None: checked_tags.append(tag))

    target = cast(
        Callable[[Mapping[str, str]], object],
        validate,
    )(
        {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REF_NAME": "main",
        }
    )

    assert target == publish_target(package_index="testpypi")
    assert checked_tags == [None]


def test_testpypi_dispatch_rejects_other_branches() -> None:
    validate, _ = _load_release_validation()
    with pytest.raises(SystemExit, match="TestPyPI runs must be dispatched from main"):
        validate(
            {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/feature",
                "GITHUB_REF_NAME": "feature",
            }
        )


def test_production_tag_must_belong_to_matching_release_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    validate, publish_target = _load_release_validation()
    git_commands: list[tuple[str, ...]] = []
    checked_tags: list[str | None] = []

    def run_git(
        *args: str,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        git_commands.append(args)
        stdout = "tag-commit\n" if args[0] == "rev-parse" else ""
        return subprocess.CompletedProcess(["git", *args], returncode=0, stdout=stdout)

    monkeypatch.setitem(validate.__globals__, "_run_git", run_git)
    monkeypatch.setitem(validate.__globals__, "_check_release", checked_tags.append)

    target = validate(
        {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/tags/v1.7.3",
            "GITHUB_REF_NAME": "v1.7.3",
        }
    )

    assert target == publish_target(package_index="pypi", release_branch="release/1.7")
    assert git_commands == [
        (
            "fetch",
            "--no-tags",
            "origin",
            "refs/heads/release/1.7:refs/remotes/origin/release/1.7",
        ),
        ("rev-parse", "refs/tags/v1.7.3^{commit}"),
        (
            "merge-base",
            "--is-ancestor",
            "tag-commit",
            "refs/remotes/origin/release/1.7",
        ),
    ]
    assert checked_tags == ["v1.7.3"]


def test_production_tag_requires_stable_version_form() -> None:
    validate, _ = _load_release_validation()
    with pytest.raises(SystemExit, match=r"stable vX\.Y\.Z form"):
        validate(
            {
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/tags/v1.7.3rc1",
                "GITHUB_REF_NAME": "v1.7.3rc1",
            }
        )


def test_workflows_do_not_contain_multiline_shell_scripts() -> None:
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        contents = workflow.read_text()
        assert "shell: bash" not in contents, workflow
        assert "run: |" not in contents, workflow


def test_committed_documentation_does_not_reference_private_release_notes() -> None:
    for document in ROOT.glob("*.md"):
        if document.name != "RELEASE.md":
            assert "RELEASE.md" not in document.read_text(), document
