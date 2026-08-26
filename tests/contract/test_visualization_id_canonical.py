from __future__ import annotations

from datalens_sdk.converter.wizard.converter import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart


def test_visualization_id_reads_document_v1_type() -> None:
    chart = WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "sources": {"datasetsIds": []},
            "visualization": {"type": "line", "x": {"items": []}},
        },
    )

    assert chart.visualization_id == "line"


def test_visualization_id_is_none_when_document_v1_visualization_is_incomplete() -> None:
    assert WizardChart(id="chart-1", data={}).visualization_id is None
    assert WizardChart(id="chart-1", data={"visualization": []}).visualization_id is None
    assert WizardChart(id="chart-1", data={"visualization": {}}).visualization_id is None


def test_api_v3_read_uses_document_v1_visualization_type() -> None:
    chart = WizardChartConverter.to_domain(
        {
            "entry": {
                "createdAt": "2026-01-01T00:00:00.000Z",
                "createdBy": "user-1",
                "version": 1,
                "entryId": "chart-1",
                "hidden": False,
                "key": "/Charts/chart-1",
                "meta": {},
                "public": False,
                "publishedId": "revision-1",
                "revId": "revision-1",
                "savedId": "revision-1",
                "scope": "widget",
                "tenantId": "tenant-1",
                "type": "d3_wizard_node",
                "updatedAt": "2026-01-02T00:00:00.000Z",
                "updatedBy": "user-1",
                "data": {
                    "sources": {"datasetsIds": []},
                    "visualization": {"type": "line", "x": {"items": []}},
                },
                "workbookId": None,
            },
            "isFavorite": False,
            "permissions": {"admin": True, "edit": True, "execute": True, "read": True},
        },
        installation="yacloud",
    )

    assert chart.visualization_id == "line"
