from __future__ import annotations

import argparse
from pathlib import Path
import re

import tomllib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag")
    args = parser.parse_args()

    metadata = tomllib.loads(Path("pyproject.toml").read_text())
    version = metadata["project"]["version"]
    changelog = Path("CHANGELOG.md").read_text()
    if not re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE):
        raise SystemExit(f"CHANGELOG.md has no dated release heading for {version}")
    if args.tag is not None and args.tag != f"v{version}":
        raise SystemExit(f"Tag {args.tag!r} does not match package version {version!r}")


if __name__ == "__main__":
    main()
