from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys

PRODUCTION_TAG_PATTERN = re.compile(
    r"^v(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?P<prerelease>rc[1-9][0-9]*)?$"
)


@dataclass(frozen=True)
class PublishTarget:
    package_index: str
    release_branch: str | None = None
    prerelease: bool = False


def _required_environment_value(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _run_git(*args: str, check: bool = True, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _check_release(tag: str | None = None) -> None:
    command = [sys.executable, "scripts/check_release.py"]
    if tag is not None:
        command.extend(("--tag", tag))
    subprocess.run(command, check=True)


def _validate_production_tag(tag: str, ref: str) -> PublishTarget:
    match = PRODUCTION_TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise SystemExit("Production tags must have the canonical vX.Y.Z or vX.Y.ZrcN form")

    release_branch = f"release/{match['major']}.{match['minor']}"
    remote_release_branch = f"refs/remotes/origin/{release_branch}"
    fetch = _run_git(
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{release_branch}:{remote_release_branch}",
        check=False,
    )
    if fetch.returncode != 0:
        raise SystemExit(f"Required release branch {release_branch!r} does not exist")

    tag_commit = _run_git("rev-parse", f"{ref}^{{commit}}", capture_output=True).stdout.strip()
    ancestry = _run_git(
        "merge-base",
        "--is-ancestor",
        tag_commit,
        remote_release_branch,
        check=False,
    )
    if ancestry.returncode != 0:
        raise SystemExit(f"Tag {tag!r} is not on {release_branch!r}")

    _check_release(tag)
    return PublishTarget(
        package_index="pypi",
        release_branch=release_branch,
        prerelease=match["prerelease"] is not None,
    )


def validate_publish_ref(environ: Mapping[str, str]) -> PublishTarget:
    event_name = _required_environment_value(environ, "GITHUB_EVENT_NAME")
    ref = _required_environment_value(environ, "GITHUB_REF")
    ref_name = _required_environment_value(environ, "GITHUB_REF_NAME")

    if event_name == "push":
        return _validate_production_tag(ref_name, ref)
    if event_name == "workflow_dispatch":
        if ref != "refs/heads/main":
            raise SystemExit("TestPyPI runs must be dispatched from main")
        _check_release()
        return PublishTarget(package_index="testpypi")
    raise SystemExit(f"Unsupported publish event {event_name!r}")


def _write_github_outputs(target: PublishTarget, output_path: Path) -> None:
    values = [f"value={target.package_index}"]
    if target.release_branch is not None:
        values.append(f"release-branch={target.release_branch}")
    values.append(f"prerelease={str(target.prerelease).lower()}")
    with output_path.open("a", encoding="utf-8") as output:
        output.write("\n".join(values) + "\n")


def main() -> None:
    target = validate_publish_ref(os.environ)
    output_path = Path(_required_environment_value(os.environ, "GITHUB_OUTPUT"))
    _write_github_outputs(target, output_path)


if __name__ == "__main__":
    main()
