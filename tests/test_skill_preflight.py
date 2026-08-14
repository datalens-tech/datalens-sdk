from pathlib import Path
import subprocess

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"
PREFLIGHT = SKILL_DIR / "scripts" / "preflight.sh"


def run_preflight(tmp_path: Path, *args: str, env: dict[str, str] | None = None) -> dict[str, str]:
    clean_env = {
        "PATH": "/usr/bin:/bin",
    }
    if env:
        clean_env.update(env)
    result = subprocess.run(
        ["bash", str(PREFLIGHT), *args],
        cwd=tmp_path,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    )
    marker, separator, fields = result.stdout.partition("---PREFLIGHT---\n")
    assert separator
    assert not marker
    return dict(line.split("=", 1) for line in fields.splitlines())


def test_enterprise_preflight_is_configuration_only(tmp_path: Path) -> None:
    fields = run_preflight(tmp_path, "enterprise", env={"DATALENS_BASE_URL": "https://example.test"})

    assert fields == {
        "INSTALLATION": "enterprise",
        "BASE_URL": "set",
        "TOKEN": "absent",
        "ENV_FILE": str(tmp_path / ".env"),
        "STATUS": "ready",
    }
    assert (tmp_path / ".env").is_file()
    assert not (tmp_path / ".venv").exists()


def test_enterprise_missing_base_url_is_blocked(tmp_path: Path) -> None:
    fields = run_preflight(tmp_path, "enterprise")

    assert fields["BASE_URL"] == "missing"
    assert fields["STATUS"] == "blocked"


def test_yc_static_credentials_do_not_require_cli(tmp_path: Path) -> None:
    fields = run_preflight(
        tmp_path,
        "yc",
        env={"DATALENS_ORG_ID": "org", "DATALENS_IAM_TOKEN": "opaque"},
    )

    assert fields["YC_CLI"] == "missing"
    assert fields["YC_STATIC"] == "ok"
    assert fields["STATUS"] == "ready"


def test_yc_preflight_uses_custom_binary_from_environment(tmp_path: Path) -> None:
    custom_yc = tmp_path / "custom-yc"
    custom_yc.write_text("#!/bin/sh\nexit 99\n")
    custom_yc.chmod(0o755)

    fields = run_preflight(tmp_path, "yc", env={"DATALENS_YC_BIN": str(custom_yc)})

    assert fields["YC_CLI"] == "found"
    assert fields["STATUS"] == "ready"


def test_yc_preflight_does_not_load_custom_binary_from_dotenv(tmp_path: Path) -> None:
    custom_yc = tmp_path / "custom-yc"
    custom_yc.write_text("#!/bin/sh\nexit 99\n")
    custom_yc.chmod(0o755)
    (tmp_path / ".env").write_text(f"DATALENS_YC_BIN={custom_yc}\n")

    fields = run_preflight(tmp_path, "yc")

    assert fields["YC_CLI"] == "missing"
    assert fields["STATUS"] == "blocked"


def test_detection_reports_ambiguous_signals(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    yc = tools / "yc"
    yc.write_text("#!/bin/sh\nexit 99\n")
    yc.chmod(0o755)

    fields = run_preflight(
        tmp_path,
        env={
            "PATH": f"{tools}:/usr/bin:/bin",
            "DATALENS_BASE_URL": "https://example.test",
        },
    )

    assert fields["INSTALLATION"] == "ambiguous"
    assert fields["INSTALLATION_HINTS"] == "enterprise,yc"
    assert fields["STATUS"] == "needs_input"


def test_dotenv_is_read_without_execution(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed"
    (tmp_path / ".env").write_text(f"DATALENS_BASE_URL=$(touch {sentinel})\nDATALENS_OAUTH_TOKEN=opaque\n")

    fields = run_preflight(tmp_path, "enterprise")

    assert fields["BASE_URL"] == "set"
    assert fields["TOKEN"] == "dotenv"
    assert fields["STATUS"] == "ready"
    assert not sentinel.exists()


def test_preflight_never_invokes_environment_or_package_tools(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    sentinel = tmp_path / "tool-called"
    for name in ("python3", "pip", "uv", "poetry"):
        tool = tools / name
        tool.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 99\n")
        tool.chmod(0o755)

    fields = run_preflight(
        tmp_path,
        "enterprise",
        env={
            "PATH": f"{tools}:/usr/bin:/bin",
            "DATALENS_BASE_URL": "https://example.test",
        },
    )

    assert fields["STATUS"] == "ready"
    assert not sentinel.exists()
    assert not (tmp_path / ".venv").exists()


def test_bundled_skill_does_not_name_external_wrapper_repository() -> None:
    coupled_files = [
        path.relative_to(SKILL_DIR)
        for path in SKILL_DIR.rglob("*")
        if path.is_file() and "datalens-skills" in path.read_text(errors="ignore").lower()
    ]

    assert coupled_files == []
