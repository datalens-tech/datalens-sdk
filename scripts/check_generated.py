from __future__ import annotations

from pathlib import Path
import tempfile

from generate_sdk import INSTALLATIONS, ROOT, build_metadata, write_outputs

GENERATED_FILES = [
    "src/datalens_sdk/_generated/__init__.py",
    "src/datalens_sdk/_generated/installations.json",
    "src/datalens_sdk/_generated/dto.py",
    "src/datalens_sdk/_generated/builders/__init__.py",
    "src/datalens_sdk/_generated/builders/charts.py",
    "src/datalens_sdk/_generated/builders/enterprise.py",
    "src/datalens_sdk/_generated/builders/yacloud.py",
    "src/datalens_sdk/_generated/builders/dataset_sources.py",
]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        write_outputs(out, build_metadata(INSTALLATIONS))
        mismatches = [
            relative for relative in GENERATED_FILES if (out / relative).read_text() != (ROOT / relative).read_text()
        ]
    if mismatches:
        joined = "\n".join(f"  - {item}" for item in mismatches)
        raise SystemExit(f"Generated files are stale:\n{joined}\nRun `nox -s generate`.")


if __name__ == "__main__":
    main()
