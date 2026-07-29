"""Regression tests for wizard visualization-id canonicalization (Finding 1).

After the refactoring the viz identifier has a single source of truth: the
wire ``data["visualization"]["id"]`` (the canonical ``visualization_id``).
The legacy ``WizardChart.viz_id`` dataclass field is gone — replaced by the
computed :pyattr:`WizardChart.visualization_id` property (parity with
``QLChart``). VIZ_SPECS keys and method_specs membership sets are keyed by
the wire-id. These tests pin both invariants:

* ``WizardChart`` has no ``viz_id`` dataclass field / slot.
* For every wizard wire-id the property reads ``data.visualization.id`` and
  the update applicability guard resolves the method_specs set without
  raising (no spec-key/wire-id mismatch).
"""

from __future__ import annotations

import dataclasses
from typing import Any, cast

import pytest

from datalens_sdk._runtime.method_specs import METHOD_SPECS
from datalens_sdk._runtime.viz_specs import VIZ_SPECS
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DatalensConfigurationError

# Representative method_specs scoped to a viz_ids set, one per viz where
# possible. Used to exercise the update applicability guard with the wire-id
# resolved from data — the regression core of Finding 1.
# Universal helper methods that every viz exposes (no viz_ids restriction).
_UNIVERSAL_HELPERS = {
    name for name, spec in METHOD_SPECS.items() if spec["kind"] == "helper" and not spec.get("viz_ids")
}

# Representative viz-scoped helpers per wizard wire-id (regression samples for
# the update applicability guard). Excludes ``geolayer`` — it has no helper
# scoped to it that is also applicable, so it is covered only by the universal
# guard test.
_SCOPED_HELPER_SAMPLES: dict[str, str] = {
    "line": "navigator",
    "area": "navigator",
    "area100p": "label_mode",
    "column": "axis_title",
    "column100p": "label_mode",
    "bar": "axis_scale",
    "bar100p": "label_mode",
    "pie": "label_mode",
    "donut": "label_mode",
    "treemap": "color_by_measure",
    "scatter": "shape_by_dimension",
    "metric": "font_size",
    "flatTable": "pagination",
    "funnel": "shape",
    "pivotTable": "subtotals",
    "combined-chart": "add_filter",
}


def _wizard_chart_with_visualization(visualization_id: str) -> WizardChart:
    return WizardChart(
        id="chart-canonical",
        installation="yacloud",
        data={"visualization": {"id": visualization_id, "placeholders": []}},
    )


def test_wizard_chart_has_no_viz_id_field_or_slot() -> None:

    assert "viz_id" not in {f.name for f in dataclasses.fields(WizardChart)}
    assert not hasattr(WizardChart(id="c", installation="yacloud", data={}), "viz_id")


@pytest.mark.parametrize("visualization_id", sorted(VIZ_SPECS))
def test_visualization_id_reads_data_visualization_id(visualization_id: str) -> None:
    chart = _wizard_chart_with_visualization(visualization_id)
    assert chart.visualization_id == visualization_id


def test_visualization_id_is_none_when_data_lacks_visualization_id() -> None:
    chart = WizardChart(id="c", installation="yacloud", data={})
    assert chart.visualization_id is None

    chart_empty_viz = WizardChart(
        id="c",
        installation="yacloud",
        data={"visualization": {"placeholders": []}},
    )
    assert chart_empty_viz.visualization_id is None


@pytest.mark.parametrize("visualization_id", sorted(VIZ_SPECS))
def test_update_applicability_resolves_for_every_wire_viz(visualization_id: str) -> None:
    """Finding 1 regression: no spec-key/wire-id mismatch in the applicability guard.

    For each wizard wire-id, exercising the universal helper methods must not
    raise ``DatalensConfigurationError``. Universal helpers carry no ``viz_ids``
    restriction, so they are applicable to every viz — if the property read
    failed or the lookup used a stale spec-key, this would raise.
    """
    chart = _wizard_chart_with_visualization(visualization_id)
    update = chart.update
    for helper in _UNIVERSAL_HELPERS:
        # Touching the applicability guard is enough: the universal helpers
        # resolve to the current wire-id and the check must pass.
        update._check_viz_applicability(helper)


@pytest.mark.parametrize("visualization_id", sorted(_SCOPED_HELPER_SAMPLES))
def test_update_applicability_guard_accepts_scoped_helper_for_wire_viz(visualization_id: str) -> None:
    """Finding 1 regression: a viz-scoped helper does not raise on its own wire-id.

    Picks a representative viz-scoped helper for each wizard wire-id and calls
    the applicability guard. Before the fix the guard looked up the spec via a
    spec-key while the chart carried a wire-id, raising on the five
    diverging types (pivotTable, flatTable, metric, combined-chart, *100p).
    """
    helper = _SCOPED_HELPER_SAMPLES[visualization_id]
    chart = _wizard_chart_with_visualization(visualization_id)
    chart.update._check_viz_applicability(helper)


@pytest.mark.parametrize("visualization_id", sorted(VIZ_SPECS))
def test_update_applicability_guard_rejects_inapplicable_scoped_helper(visualization_id: str) -> None:
    """A helper scoped to a different viz raises when the wire-id is excluded."""
    # Find a helper that is NOT applicable to this viz (declared viz_ids excludes it).
    excluded = next(
        (
            name
            for name, spec in METHOD_SPECS.items()
            if spec["kind"] == "helper"
            and (viz_ids := cast(dict[str, Any], spec).get("viz_ids"))
            and visualization_id not in viz_ids
        ),
        None,
    )
    if excluded is None:
        pytest.skip(f"{visualization_id}: no viz-scoped helper to exclude")
    chart = _wizard_chart_with_visualization(visualization_id)
    with pytest.raises(DatalensConfigurationError):
        chart.update._check_viz_applicability(excluded)


def test_visualization_id_reflects_data_change_in_place() -> None:
    chart = _wizard_chart_with_visualization("line")
    assert chart.visualization_id == "line"
    cast(dict[str, Any], chart.data["visualization"])["id"] = "pivotTable"
    assert chart.visualization_id == "pivotTable"


def test_update_change_visualization_to_uses_wire_id_keyword() -> None:
    """``change_visualization_to`` accepts the wire ``visualization_id`` keyword."""
    chart = _wizard_chart_with_visualization("line")
    update = chart.update.change_visualization_to(visualization_id="bar")
    assert update.visualization_id == "bar"


# ---------------------------------------------------------------------------
# Finding 2: create response missing data.visualization.id is enriched from
# the create-spec fallback, so chart.update works without a get-refetch.
# ---------------------------------------------------------------------------


def test_to_domain_fills_visualization_id_from_fallback_when_response_lacks_it() -> None:
    """The create response omits ``data.visualization.id``; fallback fills it."""
    create_response = {
        "entryId": "chart-1",
        "type": "d3_wizard_node",
        "data": {"visualization": {"placeholders": []}},
    }
    chart = WizardChartConverter.to_domain(
        create_response,
        installation="yacloud",
        visualization_id_fallback="pivotTable",
    )
    assert chart.visualization_id == "pivotTable"


def test_to_domain_fallback_is_ignored_when_response_already_carries_visualization_id() -> None:
    """A response that already carries a viz-id wins over the fallback."""
    create_response = {
        "entryId": "chart-1",
        "type": "d3_wizard_node",
        "data": {"visualization": {"id": "line", "placeholders": []}},
    }
    chart = WizardChartConverter.to_domain(
        create_response,
        installation="yacloud",
        visualization_id_fallback="pivotTable",
    )
    assert chart.visualization_id == "line"


def test_to_domain_without_fallback_leaves_visualization_id_none() -> None:
    """No fallback and no response viz-id leaves the property None."""
    create_response = {
        "entryId": "chart-1",
        "type": "d3_wizard_node",
        "data": {"visualization": {"placeholders": []}},
    }
    chart = WizardChartConverter.to_domain(create_response, installation="yacloud")
    assert chart.visualization_id is None
