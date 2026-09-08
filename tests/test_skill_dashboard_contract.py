from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"


def test_dashboard_skill_documents_the_non_empty_create_contract() -> None:
    dashboards = (SKILL_DIR / "references" / "dashboards.md").read_text()
    core_concepts = (SKILL_DIR / "references" / "core-concepts.md").read_text()
    skill = (SKILL_DIR / "SKILL.md").read_text()

    for text in (dashboards, core_concepts, skill):
        assert "at least one" in text
        assert "DataLensValidationError" in text
        assert ".add_tab(" in text
        assert "before HTTP" in text
