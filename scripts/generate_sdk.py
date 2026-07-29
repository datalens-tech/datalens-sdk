from __future__ import annotations

import argparse
from pathlib import Path

from datalens_sdk import codegen

ROOT = Path(__file__).resolve().parents[1]
INSTALLATIONS = {
    "enterprise": ROOT / "spec" / "enterprise.json",
    "yacloud": ROOT / "spec" / "yacloud.json",
}
NAMESPACES = codegen.NAMESPACES
PACKAGE_DIR = codegen.PACKAGE_DIR

build_metadata = codegen.build_metadata
write_outputs = codegen.write_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    write_outputs(args.output_root, build_metadata(INSTALLATIONS))


if __name__ == "__main__":
    main()
