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
    assert chart.has_unpublished_changes is True


@pytest.mark.parametrize(
    ("saved_id", "published_id", "expected"),
    [
        ("draft", "live", True),
        ("same", "same", False),
        (None, None, None),
        ("draft", None, None),
        (None, "live", None),
    ],
)
def test_unpublished_changes_preserves_unknown_metadata_for_every_supported_entry(
    saved_id: str | None, published_id: str | None, expected: bool | None
) -> None:
    charts = [
        chart_type(id="chart", raw={"savedId": saved_id, "publishedId": published_id})
        for chart_type in (dl.WizardChart, dl.QLChart, dl.EditorChart)
    ]
    entries = [
        dl.Dataset(id="dataset", saved_id=saved_id, published_id=published_id),
        dl.Dashboard(id="dashboard", saved_id=saved_id, published_id=published_id),
        dl.HtmlPage(id="html", saved_id=saved_id, published_id=published_id),
        *charts,
    ]
    for entry in entries:
        assert entry.has_unpublished_changes is expected


def test_dashboard_legacy_is_draft_retains_its_bool_behavior() -> None:
    dashboard = dl.Dashboard(id="dashboard")
    assert dashboard.is_draft is False
    assert dashboard.has_unpublished_changes is None
