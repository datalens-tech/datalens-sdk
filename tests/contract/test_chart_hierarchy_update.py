from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.fields import WizardHierarchy
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensConfigurationError


def _flat_table_chart_for_update() -> WizardChart:
    """Minimal flatTable chart with two dataset fields resolvable by guid."""
    return WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "sources": {"datasetsIds": ["ds1"]},
            "visualization": {
                "type": "flatTable",
                "colors": {"items": []},
                "columns": {
                    "items": [
                        {
                            "guid": "g_reg",
                            "title": "Region",
                            "type": "DIMENSION",
                            "data_type": "string",
                            "calc_mode": "direct",
                            "datasetId": "ds1",
                        },
                        {
                            "guid": "g_city",
                            "title": "City",
                            "type": "DIMENSION",
                            "data_type": "string",
                            "calc_mode": "direct",
                            "datasetId": "ds1",
                        },
                    ],
                },
                "sort": {"items": []},
            },
        },
    )


def test_add_hierarchy_merges_into_data_hierarchies() -> None:
    chart = _flat_table_chart_for_update()
    hierarchy = WizardHierarchy(title="Loc", fields=["g_reg", "g_city"])
    update = chart.update.add_hierarchy(hierarchy)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"].get("hierarchies", []))
    assert len(hierarchies) == 1
    hier = hierarchies[0]
    assert hier["title"] == "Loc"
    assert set(hier) == {"guid", "title", "fields"}
    fields = cast(list[dict[str, Any]], hier["fields"])
    assert len(fields) == 2
    # Wizard V1 sources keep hierarchy children as minimal field references.
    assert isinstance(fields[0], dict)
    assert fields[0]["guid"] == "g_reg"


def test_add_hierarchy_fields_are_wizard_v1_minimal_references() -> None:
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy(WizardHierarchy(title="Loc", fields=["g_reg", "g_city"]))
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"]["hierarchies"])
    field0 = cast(dict[str, Any], hierarchies[0]["fields"][0])
    assert field0 == {"guid": "g_reg", "datasetId": "ds1"}


def test_add_hierarchy_dedup_by_guid_replaces_existing() -> None:
    chart = WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "sources": {
                "datasetsIds": ["ds1"],
                "hierarchies": [{"guid": "g1", "title": "Old", "fields": []}],
            },
            "visualization": {
                "type": "flatTable",
                "colors": {"items": []},
                "columns": {
                    "items": [
                        {
                            "guid": "g_reg",
                            "title": "Region",
                            "type": "DIMENSION",
                            "data_type": "string",
                            "calc_mode": "direct",
                            "datasetId": "ds1",
                        }
                    ],
                },
                "sort": {"items": []},
            },
        },
    )
    update = chart.update.add_hierarchy(WizardHierarchy(title="New", fields=["g_reg"], guid="g1"))
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"]["hierarchies"])
    guids = [h["guid"] for h in hierarchies]
    assert guids.count("g1") == 1
    replaced = next(h for h in hierarchies if h["guid"] == "g1")
    assert replaced["title"] == "New"


def test_add_hierarchy_placement_via_columns_mounts_seven_key_object() -> None:
    chart = _flat_table_chart_for_update()
    hierarchy = WizardHierarchy(title="Geo", fields=["g_reg", "g_city"])
    update = chart.update.add_hierarchy(hierarchy).columns([hierarchy])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    items = cast(list[dict[str, Any]], data["visualization"]["columns"]["items"])
    hier_items = [i for i in items if i.get("data_type") == "hierarchy"]
    assert len(hier_items) == 1
    mounted = hier_items[0]
    assert set(mounted) == {"guid", "title", "data_type", "fields"}
    assert mounted["title"] == "Geo"
    assert mounted["fields"] == [
        {"guid": "g_reg", "datasetId": "ds1"},
        {"guid": "g_city", "datasetId": "ds1"},
    ]


def test_remembered_hierarchy_handle_resolves_after_fetch_by_guid() -> None:
    hierarchy = WizardHierarchy(title="Geo", fields=["g_reg", "g_city"], guid="geo-remembered")
    chart = _flat_table_chart_for_update()
    data = cast(dict[str, Any], chart.data)
    data["sources"]["hierarchies"] = [
        {
            "guid": hierarchy.guid,
            "title": hierarchy.title,
            "fields": [
                {"guid": "g_reg", "datasetId": "ds1"},
                {"guid": "g_city", "datasetId": "ds1"},
            ],
        }
    ]

    data = cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(chart.update.columns([hierarchy])).to_payload()["data"],
    )
    mounted = cast(list[dict[str, Any]], data["visualization"]["columns"]["items"])[0]
    assert mounted["guid"] == hierarchy.guid
    assert mounted["data_type"] == "hierarchy"


def test_add_hierarchy_only_counts_as_mutation() -> None:
    """Only .add_hierarchy(...) and no other mutations should still register as a change."""
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy(WizardHierarchy(title="Loc", fields=["g_reg"]))
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    # If not treated as a mutation, the converter would be a no-op for hierarchies.
    hierarchies = cast(list[dict[str, Any]], data["sources"].get("hierarchies", []))
    assert any(h.get("title") == "Loc" for h in hierarchies)


def test_add_hierarchy_viz_applicability_gate_on_metric() -> None:
    chart = WizardChart(
        id="metric-chart",
        installation="yacloud",
        wire_type="d3_wizard_node",
        data={"sources": {"datasetsIds": []}, "visualization": {"type": "metric", "measures": {"items": []}}},
    )
    with pytest.raises(DataLensConfigurationError, match="add_hierarchy"):
        chart.update.add_hierarchy(WizardHierarchy(title="X", fields=["f1"]))


def test_add_hierarchy_preserves_unknown_wizard_v1_snapshot_fields() -> None:
    existing_hierarchy = {
        "guid": "existing-hierarchy",
        "title": "Existing Grouping",
        "futureHierarchy": {"kept": True},
        "fields": [
            {"guid": "g_reg", "datasetId": "ds1", "futureField": {"kept": True}},
            {"guid": "g_city", "datasetId": "ds1"},
        ],
    }
    chart = WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "sources": {
                "datasetsIds": ["ds1"],
                "hierarchies": [existing_hierarchy],
                "futureSources": {"kept": True},
            },
            "visualization": {
                "type": "flatTable",
                "colors": {"items": []},
                "columns": {
                    "items": [
                        {"guid": "g_reg", "datasetId": "ds1"},
                        {"guid": "g_city", "datasetId": "ds1"},
                    ]
                },
                "sort": {"items": []},
                "futureVisualization": {"kept": True},
            },
            "futureRoot": {"kept": True},
        },
    )

    update = chart.update.add_hierarchy(
        WizardHierarchy(title="New Grouping", fields=["g_reg", "g_city"], guid="new-hierarchy")
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"]["hierarchies"])

    assert data["futureRoot"] == {"kept": True}
    assert data["sources"]["futureSources"] == {"kept": True}
    assert data["visualization"]["futureVisualization"] == {"kept": True}
    assert hierarchies[0] == existing_hierarchy
    assert hierarchies[1] == {
        "guid": "new-hierarchy",
        "title": "New Grouping",
        "fields": [
            {"guid": "g_reg", "datasetId": "ds1"},
            {"guid": "g_city", "datasetId": "ds1"},
        ],
    }


# ---------------------------------------------------------------------------
# Regression: RecursionError when hierarchy title/guid matches a child ref
# ---------------------------------------------------------------------------


def test_add_hierarchy_self_ref_by_title_does_not_recurse() -> None:
    chart = _flat_table_chart_for_update()
    # "g_reg" has title "Region"; use that as the hierarchy title so that the
    # child ref "Region" would match the hierarchy by title.
    update = chart.update.add_hierarchy(WizardHierarchy(title="Region", fields=["g_reg"]))
    # Must not raise RecursionError.
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"].get("hierarchies", []))
    assert any(h.get("title") == "Region" for h in hierarchies)
    hier = next(h for h in hierarchies if h.get("title") == "Region")
    assert set(hier) == {"guid", "title", "fields"}
    assert isinstance(hier["fields"][0], dict)
    assert hier["fields"][0].get("guid") == "g_reg"


def test_add_hierarchy_self_ref_by_guid_does_not_recurse() -> None:
    """Regression child ref matching hierarchy guid must not recurse."""
    chart = _flat_table_chart_for_update()
    # guid of the hierarchy matches the child ref guid string.
    update = chart.update.add_hierarchy(WizardHierarchy(title="Loc", fields=["g_reg"], guid="g_reg"))
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"].get("hierarchies", []))
    assert any(h.get("title") == "Loc" for h in hierarchies)
    hier = next(h for h in hierarchies if h.get("title") == "Loc")
    assert set(hier) == {"guid", "title", "fields"}
    # Inner field should resolve to the actual field, not be another hierarchy.
    field0 = hier["fields"][0]
    assert isinstance(field0, dict)
    assert field0 == {"guid": "g_reg", "datasetId": "ds1"}


def test_add_hierarchy_mutual_ref_does_not_recurse() -> None:
    """Regression mutual A↔B hierarchy refs must not recurse.

    Hierarchy A has a child ref that matches hierarchy B's title, and B's child
    ref matches A's title.  With the fix, inner-field normalization is done in a
    hierarchy-lookup-free context, so neither ref triggers another
    build_hierarchy_object call.
    """
    chart = _flat_table_chart_for_update()
    # A references "City" (which is B's title), B references "Region" (A's title).
    region = WizardHierarchy(title="Region", fields=["g_city"])
    city = WizardHierarchy(title="City", fields=["g_reg"])
    update = chart.update.add_hierarchy(region).add_hierarchy(city)
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["sources"].get("hierarchies", []))
    titles = {h.get("title") for h in hierarchies}
    assert "Region" in titles
    assert "City" in titles
    # Both source hierarchy objects keep the exact Wizard V1 source shape.
    for hier in hierarchies:
        assert set(hier) == {"guid", "title", "fields"}


def test_add_hierarchy_placement_does_not_inject_datasetid_into_mounted_object() -> None:
    """A hierarchy mounted in a named slot must remain a closed object.

    Slot updates must not inject datasetId into hierarchy objects.
    """
    chart = _flat_table_chart_for_update()
    hierarchy = WizardHierarchy(title="Geo", fields=["g_reg", "g_city"])
    update = chart.update.add_hierarchy(hierarchy).columns([hierarchy])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    items = cast(list[dict[str, Any]], data["visualization"]["columns"]["items"])
    hier_items = [i for i in items if i.get("data_type") == "hierarchy"]
    assert len(hier_items) == 1
    mounted = hier_items[0]
    assert set(mounted) == {"guid", "title", "data_type", "fields"}
    assert "datasetId" not in mounted
