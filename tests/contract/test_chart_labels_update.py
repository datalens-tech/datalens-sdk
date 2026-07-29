"""Phase 3c: ``WizardChartUpdate.labels`` writes ``data["labels"]`` (data_field
parity with the create side), the ``explicit_colors`` getter exposes what was
previously a write-only flag (P0-B1), and ``_apply_smart_labels_position`` runs
on update so bar/column get the same auto-``labelsPosition`` rendering as
create.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DatalensConfigurationError


def _chart_with_viz(viz_id: str, *, fields: list[dict[str, Any]] | None = None) -> WizardChart:
    """Build a WizardChart for update tests: viz_id + a ``y`` placeholder with
    resolvable field snapshots + a fallback dataset id.
    """
    field_items = (
        fields
        if fields is not None
        else [
            {"guid": "g_reg", "title": "Region", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ]
    )
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "visualization": {
                    "id": viz_id,
                    "placeholders": [
                        {
                            "id": "y",
                            "items": [{**f, "datasetId": "ds1"} for f in field_items],
                        }
                    ],
                },
            },
        },
        installation="yacloud",
    )


def _update_data(update: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])


def test_update_labels_writes_normalized_field_dict() -> None:
    """`.labels([field])` writes a full normalized snapshot dict to ``data['labels']``."""
    chart = _chart_with_viz("column")
    update = chart.update.labels(["Amount"])
    data = _update_data(update)
    labels = cast(list[dict[str, Any]], data["labels"])
    assert len(labels) == 1
    # Full snapshot dict, not a guid string.
    assert isinstance(labels[0], dict)
    assert labels[0]["guid"] == "g_amt"
    assert labels[0]["title"] == "Amount"
    assert labels[0].get("datasetId") == "ds1"


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
    colors = cast(list[dict[str, Any]], data["colors"])
    assert len(colors) == 1
    assert colors[0]["guid"] == "g_reg"


def test_update_dimension_color_rejected_for_measure_only_viz() -> None:
    chart = _chart_with_viz("flatTable")
    with pytest.raises(DatalensConfigurationError, match="not applicable"):
        chart.update.color_by_dimension("Region")


def test_smart_labels_position_outside_without_colors_on_bar() -> None:
    """Bar/column update with `.labels([...])` and no color split -> labelsPosition 'outside'."""
    chart = _chart_with_viz("bar")
    update = chart.update.labels(["Amount"])
    data = _update_data(update)
    extras = cast(dict[str, Any], data["extraSettings"])
    assert extras["labelsPosition"] == "outside"


def test_smart_labels_position_inside_with_explicit_colors() -> None:
    """Bar update with `.labels([...])` and an existing color split -> 'inside'.

    Bar/column don't expose a ``colors`` placeholder; a color split arrives
    either from an existing ``data['colors']`` (loaded from get) or via
    ``explicit_colors=True``. We pre-populate ``data['colors']`` to mirror a
    chart that was already colorized before the update.
    """
    chart = WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "colors": [{"guid": "g_amt", "title": "Amount", "datasetId": "ds1"}],
                "visualization": {
                    "id": "bar",
                    "placeholders": [
                        {
                            "id": "y",
                            "items": [{"guid": "g_amt", "title": "Amount", "datasetId": "ds1"}],
                        }
                    ],
                },
            },
        },
        installation="yacloud",
    )
    update = chart.update.labels(["Amount"])
    data = _update_data(update)
    extras = cast(dict[str, Any], data["extraSettings"])
    assert extras["labelsPosition"] == "inside"


def test_smart_labels_position_respects_explicit_labels_position() -> None:
    """Explicit `.labels_position(mode=...)` must NOT be overridden by smart_position."""
    chart = _chart_with_viz("bar")
    update = chart.update.labels(["Amount"]).labels_position(mode="inside")
    data = _update_data(update)
    extras = cast(dict[str, Any], data["extraSettings"])
    # Explicit 'inside' preserved (smart_position guard respects the existing key).
    assert extras["labelsPosition"] == "inside"


def test_smart_labels_position_not_applied_without_labels_edit() -> None:
    """A chart that already has labels from get (no `.labels()` edit) must NOT get
    smart_position injected — guard is ``'labels' in data_fields_edits``.
    """
    raw_labels = [{"guid": "g_amt", "title": "Amount", "type": "MEASURE", "datasetId": "ds1"}]
    chart = WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "labels": list(raw_labels),
                "visualization": {
                    "id": "bar",
                    "placeholders": [{"id": "y", "items": [{"guid": "g_amt", "title": "Amount", "datasetId": "ds1"}]}],
                },
            },
        },
        installation="yacloud",
    )
    # Touch the chart via a non-labels mutation so the update payload is built
    # but the labels data_field edit is not registered.
    update = chart.update.add_sort("Amount", direction="asc")
    data = _update_data(update)
    extras = data.get("extraSettings")
    # Smart_position should not have added labelsPosition (no labels edit).
    if isinstance(extras, dict):
        assert "labelsPosition" not in extras


def test_labels_applicability_gate_on_metric() -> None:
    """`.labels([...])` on a viz without allowLabels (metric) -> DatalensConfigurationError."""
    chart = WizardChart(
        id="metric-chart",
        installation="yacloud",
        wire_type="metric_wizard_node",
        data={"visualization": {"id": "metric", "placeholders": []}},
    )
    with pytest.raises(DatalensConfigurationError, match="labels"):
        chart.update.labels(["Amount"])
