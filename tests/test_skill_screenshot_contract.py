from __future__ import annotations

import inspect
import json
from pathlib import Path

import datalens_sdk as dl

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"
REFERENCE = SKILL_DIR / "references" / "screenshots.md"


def test_skill_routes_screenshot_tasks_to_the_reference() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text()

    assert "screenshotting the DataLens web UI" not in skill
    assert "UI viewing or screenshots" not in skill
    assert skill.count("references/screenshots.md") >= 3
    assert "server-rendered chart and dashboard screenshots" in skill
    assert "browsing the web UI" in skill


def test_screenshot_reference_documents_the_public_surface() -> None:
    reference = REFERENCE.read_text()

    for fragment in (
        "chart.screenshot()",
        "dashboard.screenshot(",
        ".save(",
        "get_temp_s3_url()",
        "EntityScreenshot",
        "revId",
        "DataLensValidationError",
        "NotSupportedError",
        "before HTTP",
        "RateLimitError",
        "3 screenshots per minute",
        "error.context.retry_after",
        "Only parameters declared in the dashboard settings are read",
        "rejects an undeclared name",
        "The SDK checks the declaration only",
        "reserves some names for the page itself",
        "is linked to that selector",
        "explicit alias",
        "the guid of a field",
        "the name of a parameter declared in the dataset",
        "global_params",
        "BadRequestError",
        "DataLensTransportError",
        "https://yandex.cloud/en/docs/datalens/security/embedded-objects",
    ):
        assert fragment in reference
    for method in (dl.Dashboard.screenshot, dl.Chart.screenshot):
        for argument in inspect.signature(method).parameters:
            if argument != "self":
                assert f"`{argument}`" in reference
    assert "TODO" not in reference
    assert "yandex-team" not in reference


def test_screenshot_reference_keeps_the_result_handling_rule() -> None:
    reference = REFERENCE.read_text()

    assert "## Result-handling permission is mandatory" in reference
    assert "Always save it to a file" in reference
    assert "only when the user asked for a visual check" in reference
    assert "is not\npermission to inspect its screenshot" in reference
    assert "new render" in reference
    assert "opens without DataLens credentials" in reference


def test_screenshot_evals_cover_saving_without_viewing_and_requested_visual_checks() -> None:
    evals = json.loads((SKILL_DIR / "evals" / "evals.json").read_text())["evals"]
    names = {item["name"] for item in evals}

    assert {"dashboard-screenshot-save-without-viewing", "chart-screenshot-visual-check-on-request"} <= names
    assert len({item["id"] for item in evals}) == len(evals)
