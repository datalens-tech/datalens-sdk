from __future__ import annotations

import pytest

import datalens_sdk as dl


@pytest.mark.parametrize("chart_type", [dl.WizardChart, dl.QLChart, dl.EditorChart])
@pytest.mark.parametrize("snake_case", [False, True])
def test_chart_revision_metadata_describes_the_loaded_revision_and_current_branches(
    chart_type: type[dl.Chart], snake_case: bool
) -> None:
    raw = (
        {"rev_id": "historical", "saved_id": "draft", "published_id": "live"}
        if snake_case
        else {"revId": "historical", "savedId": "draft", "publishedId": "live"}
    )
    chart = chart_type(id="chart", raw=raw)

    assert chart.rev_id == "historical"
    assert chart.saved_id == "draft"
    assert chart.published_id == "live"


def test_dashboard_legacy_is_draft_retains_its_bool_behavior() -> None:
    dashboard = dl.Dashboard(id="dashboard")
    assert dashboard.is_draft is False
