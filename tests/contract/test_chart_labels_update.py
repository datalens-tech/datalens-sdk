"""Wizard v3 label updates use the named labels slot and explicit settings."""

from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._generated.dto import WIZARD_VISUALIZATION_STRUCTURE
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensConfigurationError


def _chart_with_viz(viz_id: str, *, fields: list[dict[str, Any]] | None = None) -> WizardChart:
    """Build a Wizard v3 chart snapshot with resolvable named-slot items."""
    field_items = (
        fields
        if fields is not None
        else [
            {"guid": "g_reg", "title": "Region", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ]
    )
    structure = WIZARD_VISUALIZATION_STRUCTURE[viz_id]
    slots: dict[str, Any] = {slot_name: {"items": []} for slot_name in structure["slots"]}
    carrier = next(name for name in ("y", "measures", "columns") if name in slots)
    slots[carrier]["items"] = [{**field, "datasetId": "ds1"} for field in field_items]
    return WizardChartConverter.to_domain(
        {
            "entry": {
                "version": 1,
                "entryId": "chart-1",
                "type": "d3_wizard_node",
                "data": {
                    "sources": {"datasetsIds": ["ds1"]},
                    "visualization": {"type": viz_id, **slots},
                },
            }
        },
        installation="yacloud",
    )


def _update_data(update: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])


def test_update_labels_writes_minimal_refs_to_the_named_slot() -> None:
    chart = _chart_with_viz("column")
    update = chart.update.labels(["Amount"])
    data = _update_data(update)
    labels = cast(list[dict[str, Any]], data["visualization"]["labels"]["items"])
    assert len(labels) == 1
    assert isinstance(labels[0], dict)
    assert labels[0]["guid"] == "g_amt"
    assert labels[0].get("datasetId") == "ds1"
    assert set(labels[0]) == {"guid", "datasetId"}


def test_explicit_colors_getter_false_then_true() -> None:
    """The flag turns true when a semantic Color method is selected."""
    chart = _chart_with_viz("bar100p")
    update = chart.update
    assert update.explicit_colors is False
    update.color_by_dimension("Region")
    assert update.explicit_colors is True


def test_update_color_by_dimension_routes_cartesian_color_to_data() -> None:
    chart = _chart_with_viz("line")
    update = chart.update.color_by_dimension("Region")
    assert update.explicit_colors is True
    data = _update_data(update)
    colors = cast(list[dict[str, Any]], data["visualization"]["colors"]["items"])
    assert len(colors) == 1
    assert colors[0]["guid"] == "g_reg"


def test_update_dimension_color_rejected_for_measure_only_viz() -> None:
    chart = _chart_with_viz("flatTable")
    with pytest.raises(DataLensConfigurationError, match="not applicable"):
        chart.update.color_by_dimension("Region")


def test_labels_update_does_not_inject_a_position_without_an_explicit_call() -> None:
    chart = _chart_with_viz("bar")
    update = chart.update.labels(["Amount"])
    data = _update_data(update)
    settings = cast(dict[str, Any], data["visualization"]["labels"].get("settings", {}))
    assert "labelsPosition" not in settings


def test_explicit_labels_position_is_stored_in_label_slot_settings() -> None:
    chart = _chart_with_viz("bar")
    update = chart.update.labels(["Amount"]).labels_position(mode="inside")
    data = _update_data(update)
    settings = cast(dict[str, Any], data["visualization"]["labels"]["settings"])
    assert settings["labelsPosition"] == "inside"


def test_labels_position_auto_removes_the_explicit_carrier() -> None:
    chart = _chart_with_viz("bar")
    chart.data = _update_data(chart.update.labels(["Amount"]).labels_position(mode="outside"))
    data = _update_data(chart.update.labels_position(mode="auto"))
    settings = cast(dict[str, Any], data["visualization"]["labels"].get("settings", {}))
    assert "labelsPosition" not in settings


def test_non_label_update_preserves_absence_of_position() -> None:
    chart = _chart_with_viz("bar")
    update = chart.update.add_sort("Amount", direction="asc")
    data = _update_data(update)
    settings = cast(dict[str, Any], data["visualization"]["labels"].get("settings", {}))
    assert "labelsPosition" not in settings


def test_labels_applicability_gate_on_metric() -> None:
    """`.labels([...])` on a viz without allowLabels (metric) -> DataLensConfigurationError."""
    chart = WizardChart(
        id="metric-chart",
        installation="yacloud",
        wire_type="metric_wizard_node",
        data={
            "sources": {"datasetsIds": ["ds1"]},
            "visualization": {
                "type": "metric",
                **{slot_name: {"items": []} for slot_name in WIZARD_VISUALIZATION_STRUCTURE["metric"]["slots"]},
            },
        },
    )
    with pytest.raises(DataLensConfigurationError, match="labels"):
        chart.update.labels(["Amount"])
