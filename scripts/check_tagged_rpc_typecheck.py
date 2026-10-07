from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from mypy import api

from datalens_sdk import codegen


def main() -> None:
    metadata = codegen.build_metadata(
        codegen.INSTALLATIONS,
        rpc_namespace_configs=({"tag": "Subscriptions", "namespace": "subscriptions"},),
    )
    with TemporaryDirectory(prefix="datalens-sdk-tagged-rpc-typecheck-") as temporary_directory:
        generated_module = Path(temporary_directory) / "dto.py"
        generated_module.write_text(codegen.emit_dto(metadata), encoding="utf-8")
        stdout, stderr, exit_status = api.run(
            ["--strict", "--follow-imports=silent", "--no-incremental", str(generated_module)]
        )
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="")
    if exit_status:
        raise SystemExit(exit_status)


if __name__ == "__main__":
    main()
