from __future__ import annotations

import json
from pathlib import Path
import shutil

import nox

PYTHON_VERSIONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]
JSON_SPECS = [
    Path("spec") / "enterprise.json",
    Path("spec") / "yacloud.json",
]
CHECK_SESSIONS = [
    "generated-check",
    "lint",
    "format-check",
    "format-json-check",
    "typecheck",
    "artifacts-check",
    "dependency-lower-bounds",
    *(f"tests-{version}" for version in PYTHON_VERSIONS),
]
nox.options.default_venv_backend = "uv|virtualenv"
nox.options.sessions = CHECK_SESSIONS


def format_json_file(path: Path) -> str:
    return json.dumps(json.loads(path.read_text()), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def format_json_specs(session: nox.Session, *, check: bool) -> None:
    mismatches: list[str] = []
    for path in JSON_SPECS:
        formatted = format_json_file(path)
        if check:
            if path.read_text() != formatted:
                mismatches.append(path.as_posix())
        else:
            path.write_text(formatted)
    if mismatches:
        joined = "\n".join(f"  - {path}" for path in mismatches)
        session.error(f"JSON specs are not formatted:\n{joined}\nRun `nox -s format-json`.")


@nox.session
def generate(session: nox.Session) -> None:
    session.install("-e", ".")
    session.run("python", "scripts/generate_sdk.py")


@nox.session(name="generated-check")
def generated_check(session: nox.Session) -> None:
    session.install("-e", ".")
    session.run("python", "scripts/check_generated.py")


@nox.session
def lint(session: nox.Session) -> None:
    session.install("--group", "dev")
    session.run("ruff", "check", ".")


@nox.session(name="format")
def format_(session: nox.Session) -> None:
    """Format Python and JSON files and apply safe lint fixes."""
    session.install("--group", "dev")
    format_json_specs(session, check=False)
    session.run("ruff", "format", ".")
    session.run("ruff", "check", "--fix", ".")


@nox.session(name="format-check")
def format_check(session: nox.Session) -> None:
    session.install("--group", "dev")
    session.run("ruff", "format", "--check", ".")


@nox.session(name="format-json")
def format_json(session: nox.Session) -> None:
    format_json_specs(session, check=False)


@nox.session(name="format-json-check")
def format_json_check(session: nox.Session) -> None:
    format_json_specs(session, check=True)


@nox.session(venv_backend="none")
def check(session: nox.Session) -> None:
    """Run the complete local pull-request gate."""
    if session.posargs:
        session.error("The check session does not accept arguments")
    for session_name in CHECK_SESSIONS:
        session.notify(session_name)


@nox.session(name="update-specs")
def update_specs(session: nox.Session) -> None:
    session.run("python", "scripts/update_specs.py", *session.posargs)


@nox.session
def typecheck(session: nox.Session) -> None:
    session.install("--group", "dev")
    session.install("-e", ".")
    session.run("mypy")


def build_artifacts(session: nox.Session, output_dir: Path) -> tuple[Path, Path]:
    session.run("python", "-m", "build", "--outdir", str(output_dir))
    wheels = list(output_dir.glob("*.whl"))
    sdists = list(output_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        session.error(f"Expected one wheel and one sdist, found {wheels} and {sdists}")
    return wheels[0], sdists[0]


def check_artifact_contract(
    session: nox.Session,
    wheel: Path,
    sdist: Path,
    *,
    reference_wheel: Path | None = None,
) -> None:
    args = [
        "python",
        "scripts/check_artifacts.py",
        "--wheel",
        str(wheel),
        "--sdist",
        str(sdist),
        "--package",
        "datalens_sdk",
        "--required-wheel-member",
        "datalens_sdk/_generated/installations.json",
        "--required-wheel-member",
        "datalens_sdk/codegen.py",
        "--required-sdist-path",
        "LICENSE",
        "--required-sdist-path",
        "README.md",
        "--required-sdist-path",
        "CHANGELOG.md",
        "--required-sdist-path",
        "pyproject.toml",
        "--required-sdist-path",
        "noxfile.py",
        "--required-sdist-path",
        "spec/yacloud.json",
        "--required-sdist-path",
        "spec/enterprise.json",
        "--required-sdist-path",
        "scripts/generate_sdk.py",
        "--required-sdist-path",
        "tests/test_smoke.py",
        "--forbidden-text",
        "datalens" + "_sdk_ya",
        "--forbidden-text",
        "yandex" + "_datalens_sdk",
    ]
    if reference_wheel is not None:
        args.extend(("--reference-wheel", str(reference_wheel)))
    session.run(*args)


def validate_artifacts(session: nox.Session, wheel: Path, sdist: Path, temp_dir: Path) -> None:
    session.run("twine", "check", str(wheel), str(sdist))
    # The legacy converter module and its package facade intentionally have
    # identical re-export contents.
    session.run("check-wheel-contents", "--ignore", "W002", str(wheel))
    check_artifact_contract(session, wheel, sdist)

    extracted = temp_dir / "extracted"
    shutil.unpack_archive(sdist, extracted)
    sdist_roots = list(extracted.iterdir())
    if len(sdist_roots) != 1:
        session.error(f"Expected one extracted sdist root, found {sdist_roots}")
    rebuilt = temp_dir / "rebuilt"
    rebuilt.mkdir()
    session.run("python", "-m", "build", "--wheel", "--outdir", str(rebuilt), str(sdist_roots[0]))
    rebuilt_wheels = list(rebuilt.glob("*.whl"))
    if len(rebuilt_wheels) != 1:
        session.error(f"Expected one wheel rebuilt from the sdist, found {rebuilt_wheels}")
    check_artifact_contract(session, rebuilt_wheels[0], sdist, reference_wheel=wheel)

    session.install("--force-reinstall", str(wheel))
    session.run(
        "python",
        "-I",
        "-c",
        (
            "import importlib.metadata as m; import importlib.resources as r; "
            "import datalens_sdk as sdk; "
            "assert sdk.__version__ == m.version('datalens-sdk'); "
            "assert sdk.DataLensClientYC; "
            "assert sdk.DataLensClientEnterprise; "
            "assert r.files('datalens_sdk._generated').joinpath('installations.json').is_file()"
        ),
    )
    typing_fixture = temp_dir / "typing_smoke.py"
    typing_fixture.write_text(
        "from datalens_sdk import DataLensClientEnterprise, DataLensClientYC\n"
        "yc: type[DataLensClientYC] = DataLensClientYC\n"
        "enterprise: type[DataLensClientEnterprise] = DataLensClientEnterprise\n"
    )
    session.run("mypy", "--strict", str(typing_fixture))


@nox.session(name="build")
def build(session: nox.Session) -> None:
    session.install("--group", "dev")
    output_dir = Path("dist")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir()
    wheel, sdist = build_artifacts(session, output_dir)
    validate_artifacts(session, wheel, sdist, Path(session.create_tmp()))


@nox.session(name="artifacts-check")
def artifacts_check(session: nox.Session) -> None:
    session.install("--group", "dev")
    temp_dir = Path(session.create_tmp())
    output_dir = temp_dir / "dist"
    output_dir.mkdir()
    wheel, sdist = build_artifacts(session, output_dir)
    validate_artifacts(session, wheel, sdist, temp_dir)


@nox.session(name="dependency-lower-bounds", python="3.10")
def dependency_lower_bounds(session: nox.Session) -> None:
    session.install(
        "httpx==0.27.0",
        "pydantic==2.0.0",
        "PyJWT[crypto]==2.10.0",
        "typing_extensions==4.12.0",
        "pytest",
    )
    session.install(".", "--no-deps")
    session.run("pytest")


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.Session) -> None:
    session.install("--group", "dev")
    session.install("-e", ".")
    session.run("pytest", *session.posargs)
