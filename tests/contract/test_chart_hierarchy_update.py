from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any, cast

import pytest

from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensConfigurationError

_REFERENCE_CHARTS_DIR = Path(__file__).parent / "fixtures" / "reference_charts" / "wizard"


def _reference_chart(chart_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REFERENCE_CHARTS_DIR / f"{chart_id}.json").read_text()))


def _flat_table_chart_for_update() -> WizardChart:
    """Minimal flatTable chart with two dataset fields resolvable by guid."""
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "visualization": {
                    "id": "flatTable",
                    "placeholders": [
                        {
                            "id": "flat-table-columns",
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
                        }
                    ],
                },
            },
        },
        installation="yacloud",
    )


def test_add_hierarchy_merges_into_data_hierarchies() -> None:
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy("Loc", ["g_reg", "g_city"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data.get("hierarchies", []))
    assert len(hierarchies) == 1
    hier = hierarchies[0]
    assert hier["title"] == "Loc"
    assert hier["type"] == "PSEUDO"
    assert hier["data_type"] == "hierarchy"
    fields = cast(list[dict[str, Any]], hier["fields"])
    assert len(fields) == 2
    # Full snapshot dicts, not guid strings.
    assert isinstance(fields[0], dict)
    assert fields[0]["guid"] == "g_reg"


def test_add_hierarchy_fields_are_full_snapshots() -> None:
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy("Loc", ["g_reg", "g_city"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["hierarchies"])
    field0 = cast(dict[str, Any], hierarchies[0]["fields"][0])
    assert field0["calc_mode"] == "direct"
    assert field0.get("datasetId") == "ds1"
    assert "guid" in field0
    assert "title" in field0


def test_add_hierarchy_dedup_by_guid_replaces_existing() -> None:
    chart = WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": {
                "datasetsIds": ["ds1"],
                "hierarchies": [{"guid": "g1", "title": "Old", "type": "PSEUDO", "fields": []}],
                "visualization": {
                    "id": "flatTable",
                    "placeholders": [
                        {
                            "id": "flat-table-columns",
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
                        }
                    ],
                },
            },
        },
        installation="yacloud",
    )
    update = chart.update.add_hierarchy("New", ["g_reg"], guid="g1")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["hierarchies"])
    guids = [h["guid"] for h in hierarchies]
    assert guids.count("g1") == 1
    replaced = next(h for h in hierarchies if h["guid"] == "g1")
    assert replaced["title"] == "New"


def test_add_hierarchy_placement_via_columns_mounts_seven_key_object() -> None:
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy("Geo", ["g_reg", "g_city"]).columns(["Geo"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    phs = cast(list[dict[str, Any]], data["visualization"]["placeholders"])
    columns = next(p for p in phs if p["id"] == "flat-table-columns")
    items = cast(list[dict[str, Any]], columns["items"])
    hier_items = [i for i in items if i.get("data_type") == "hierarchy"]
    assert len(hier_items) == 1
    mounted = hier_items[0]
    assert set(mounted.keys()) == {
        "guid",
        "title",
        "className",
        "type",
        "data_type",
        "valid",
        "fields",
    }
    assert mounted["title"] == "Geo"
    assert mounted["className"] == "item dimension-item"


def test_add_hierarchy_only_counts_as_mutation() -> None:
    """Only .add_hierarchy(...) and no other mutations should still register as a change."""
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy("Loc", ["g_reg"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    # If not treated as a mutation, the converter would be a no-op for hierarchies.
    hierarchies = cast(list[dict[str, Any]], data.get("hierarchies", []))
    assert any(h.get("title") == "Loc" for h in hierarchies)


def test_add_hierarchy_viz_applicability_gate_on_metric() -> None:
    chart = WizardChart(
        id="metric-chart",
        installation="yacloud",
        wire_type="d3_wizard_node",
        data={"visualization": {"id": "metric", "placeholders": []}},
    )
    with pytest.raises(DataLensConfigurationError, match="add_hierarchy"):
        chart.update.add_hierarchy("X", ["f1"])


def test_round_trip_add_hierarchy_against_reference_fixture() -> None:
    """Realistic round-trip: load a ground-truth hierarchy chart, add a new hierarchy,
    ensure the existing one is preserved and the new one is appended with full
    field snapshots.
    """
    raw = _reference_chart("snh83szp2up8k")
    chart = WizardChartConverter.to_domain(
        {"entryId": raw["id"], "type": "d3_wizard_node", "data": raw["data"]},
        installation="yacloud",
    )
    assert chart.visualization_id == "flatTable"

    hierarchies_in = cast(list[dict[str, Any]], chart.data["hierarchies"])
    existing_hier = hierarchies_in[0]
    existing_guid = cast(str, existing_hier["guid"])
    # Reuse the existing hierarchy's full field snapshots as refs for the new one.
    existing_fields = cast(list[dict[str, Any]], existing_hier["fields"])
    new_field_refs = [dict(f) for f in existing_fields[:2]]

    update = chart.update.add_hierarchy("New Grouping", cast(Sequence[str], new_field_refs), guid="new-hier-roundtrip")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data["hierarchies"])

    # Existing hierarchy preserved.
    guids = [h["guid"] for h in hierarchies]
    assert existing_guid in guids
    assert "new-hier-roundtrip" in guids
    assert len(hierarchies) == 2

    existing_after = next(h for h in hierarchies if h["guid"] == existing_guid)
    new_after = next(h for h in hierarchies if h["guid"] == "new-hier-roundtrip")
    # Existing hierarchy retains its full field snapshots (15+ keys per field).
    existing_field0 = cast(dict[str, Any], existing_after["fields"][0])
    assert len(existing_field0) >= 15
    assert existing_field0.get("calc_mode") == "direct"
    # New hierarchy also has full field snapshots (not strings, not guids only).
    new_field0 = cast(dict[str, Any], new_after["fields"][0])
    assert isinstance(new_field0, dict)
    assert new_field0.get("calc_mode") == "direct"
    assert "datasetId" in new_field0
    assert len(new_field0) >= 15


# ---------------------------------------------------------------------------
# Regression: RecursionError when hierarchy title/guid matches a child ref
# ---------------------------------------------------------------------------


def test_add_hierarchy_self_ref_by_title_does_not_recurse() -> None:
    chart = _flat_table_chart_for_update()
    # "g_reg" has title "Region"; use that as the hierarchy title so that the
    # child ref "Region" would match the hierarchy by title.
    update = chart.update.add_hierarchy("Region", ["g_reg"])
    # Must not raise RecursionError.
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data.get("hierarchies", []))
    assert any(h.get("title") == "Region" for h in hierarchies)
    hier = next(h for h in hierarchies if h.get("title") == "Region")
    # Must still be exactly 7 keys.
    assert set(hier.keys()) == {"guid", "title", "className", "type", "data_type", "valid", "fields"}
    # Inner field must be a full snapshot, not a string.
    assert isinstance(hier["fields"][0], dict)
    assert hier["fields"][0].get("guid") == "g_reg"


def test_add_hierarchy_self_ref_by_guid_does_not_recurse() -> None:
    """Regression child ref matching hierarchy guid must not recurse."""
    chart = _flat_table_chart_for_update()
    # guid of the hierarchy matches the child ref guid string.
    update = chart.update.add_hierarchy("Loc", ["g_reg"], guid="g_reg")
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data.get("hierarchies", []))
    assert any(h.get("title") == "Loc" for h in hierarchies)
    hier = next(h for h in hierarchies if h.get("title") == "Loc")
    assert set(hier.keys()) == {"guid", "title", "className", "type", "data_type", "valid", "fields"}
    # Inner field should resolve to the actual field, not be another hierarchy.
    field0 = hier["fields"][0]
    assert isinstance(field0, dict)
    assert field0.get("data_type") != "hierarchy"


def test_add_hierarchy_mutual_ref_does_not_recurse() -> None:
    """Regression mutual A↔B hierarchy refs must not recurse.

    Hierarchy A has a child ref that matches hierarchy B's title, and B's child
    ref matches A's title.  With the fix, inner-field normalization is done in a
    hierarchy-lookup-free context, so neither ref triggers another
    build_hierarchy_object call.
    """
    chart = _flat_table_chart_for_update()
    # A references "City" (which is B's title), B references "Region" (A's title).
    update = (
        chart.update.add_hierarchy("Region", ["g_city"]).add_hierarchy(  # A: title "Region", child by guid
            "City", ["g_reg"]
        )  # B: title "City", child by guid
    )
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    hierarchies = cast(list[dict[str, Any]], data.get("hierarchies", []))
    titles = {h.get("title") for h in hierarchies}
    assert "Region" in titles
    assert "City" in titles
    # Both must remain exactly 7 keys (no extra datasetId injection into hierarchy objects).
    for hier in hierarchies:
        assert set(hier.keys()) == {"guid", "title", "className", "type", "data_type", "valid", "fields"}


def test_add_hierarchy_placement_does_not_inject_datasetid_into_mounted_object() -> None:
    """Regression hierarchy mounted in a placeholder must stay exactly 7 keys.

    _apply_placeholder_edits was injecting datasetId into every item that lacked
    one, including hierarchy objects.  The fix skips items with data_type=="hierarchy".
    """
    chart = _flat_table_chart_for_update()
    update = chart.update.add_hierarchy("Geo", ["g_reg", "g_city"]).columns(["Geo"])
    data = cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])
    phs = cast(list[dict[str, Any]], data["visualization"]["placeholders"])
    columns = next(p for p in phs if p["id"] == "flat-table-columns")
    items = cast(list[dict[str, Any]], columns["items"])
    hier_items = [i for i in items if i.get("data_type") == "hierarchy"]
    assert len(hier_items) == 1
    mounted = hier_items[0]
    # Must stay exactly 7 keys — no injected datasetId.
    assert set(mounted.keys()) == {"guid", "title", "className", "type", "data_type", "valid", "fields"}
