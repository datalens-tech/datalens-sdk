"""Update-side parity for ``add_local_field`` / ``add_aggregated_measure``.

These tests pin the merge semantics of ``WizardChartUpdate.add_local_field``
and ``add_aggregated_measure`` against an existing chart payload:

* ``add_field`` entries are appended to ``data["updates"]`` (P1-UPDATES: legacy
  operations preserved via ``setdefault``).
* guid collisions raise ``DataLensValidationError`` (P1-DROP: no silent drop).
* New local fields are visible to every ref-resolving normalizer so
  ``.add_local_field(...).add_sort(guid)`` resolves in the same update
  (P1-RACE).
* ``datasetsPartialFields`` snapshot gets the new entries prepended while
  existing fields survive.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError


def _flat_table_chart_with_data(data: dict[str, Any]) -> WizardChart:
    return WizardChartConverter.to_domain(
        {
            "entryId": "chart-1",
            "type": "d3_wizard_node",
            "data": data,
        },
        installation="yacloud",
    )


def _base_flat_table_data() -> dict[str, Any]:
    placeholders: list[dict[str, Any]] = [
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
    ]
    return {
        "datasetsIds": ["ds1"],
        "visualization": {"id": "flatTable", "placeholders": placeholders},
    }


def _payload(update: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])


def test_add_local_field_appends_add_field_to_updates() -> None:
    chart = _flat_table_chart_with_data(_base_flat_table_data())
    data = _payload(chart.update.add_local_field(title="GMV/trip", formula="[gmv]/[trips]", guid="lf1"))
    updates = cast(list[dict[str, Any]], data.get("updates", []))
    add_field_ops = [op for op in updates if op.get("action") == "add_field"]
    assert len(add_field_ops) == 1
    field = cast(dict[str, Any], add_field_ops[0]["field"])
    assert field["guid"] == "lf1"
    assert field["calc_mode"] == "formula"
    assert field["formula"] == "[gmv]/[trips]"
    assert field["local"] is True
    assert field["datasetId"] == "ds1"


def test_add_local_field_measure_default_is_none_aggregation() -> None:
    chart = _flat_table_chart_with_data(_base_flat_table_data())
    data = _payload(chart.update.add_local_field(title="M", formula="[x]", guid="m1", measure=True))
    field = cast(
        dict[str, Any],
        next(op for op in cast(list[dict[str, Any]], data["updates"]) if op.get("action") == "add_field")["field"],
    )
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "none"
    assert field["autoaggregated"] is True


def test_add_aggregated_measure_appends_direct_field() -> None:
    chart = _flat_table_chart_with_data(_base_flat_table_data())
    field_ref = DatasetField(
        guid="g_gmv",
        title="GMV",
        name="gmv",
        calc_mode="direct",
        data_type="float",
        type="DIMENSION",
        source="g_gmv_src",
    )
    data = _payload(chart.update.add_aggregated_measure(field_ref, aggregation="sum", guid="agg1", name="GMV (sum)"))
    field = cast(
        dict[str, Any],
        next(op for op in cast(list[dict[str, Any]], data["updates"]) if op.get("action") == "add_field")["field"],
    )
    assert field["guid"] == "agg1"
    assert field["calc_mode"] == "direct"
    assert field["source"] == "g_gmv_src"
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "sum"
    assert field["autoaggregated"] is False
    assert field["local"] is True


def test_add_aggregated_measure_copies_formula_dimension() -> None:
    chart = _flat_table_chart_with_data(_base_flat_table_data())
    formula_dimension = DatasetField(
        guid="g_formula",
        title="GMV in currency",
        name="gmv_currency",
        calc_mode="formula",
        data_type="float",
        type="DIMENSION",
        formula="IF([flag], [gmv], [gmv] * [rate])",
    )
    data = _payload(
        chart.update.add_aggregated_measure(
            formula_dimension,
            aggregation="avg",
            name="Average GMV",
            guid="agg_formula",
        )
    )
    field = cast(
        dict[str, Any],
        next(op for op in cast(list[dict[str, Any]], data["updates"]) if op.get("action") == "add_field")["field"],
    )
    assert field["guid"] == "agg_formula"
    assert field["title"] == "Average GMV"
    assert field["calc_mode"] == "formula"
    assert field["formula"] == "IF([flag], [gmv], [gmv] * [rate])"
    assert field["source"] == ""
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "avg"


def test_change_aggregation_replaces_placed_dimension_with_local_measure() -> None:
    data_in = _base_flat_table_data()
    placed = cast(dict[str, Any], data_in["visualization"]["placeholders"][0]["items"][0])
    placed.update({"source": "region", "id": "dimension-0", "formatting": {"precision": 0}})
    chart = _flat_table_chart_with_data(data_in)
    data = _payload(
        chart.update.change_aggregation(
            chart.fields.by_guid("g_reg"),
            aggregation="count",
            name="Region count",
            guid="region_count",
        )
    )

    field = cast(
        dict[str, Any],
        next(op for op in cast(list[dict[str, Any]], data["updates"]) if op.get("action") == "add_field")["field"],
    )
    assert field["calc_mode"] == "direct"
    assert field["source"] == "region"
    assert field["data_type"] == "integer"
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "count"

    item = cast(dict[str, Any], data["visualization"]["placeholders"][0]["items"][0])
    assert item["guid"] == "region_count"
    assert item["type"] == "MEASURE"
    assert item["aggregation"] == "count"
    assert item["id"] == "dimension-0"
    assert item["formatting"] == {"precision": 0}


def test_change_aggregation_copies_placed_formula_dimension() -> None:
    data_in = _base_flat_table_data()
    placed = cast(dict[str, Any], data_in["visualization"]["placeholders"][0]["items"][0])
    placed.update(
        {
            "guid": "g_formula",
            "title": "GMV in currency",
            "type": "DIMENSION",
            "data_type": "float",
            "calc_mode": "formula",
            "formula": "IF([flag], [gmv], [gmv] * [rate])",
            "source": "",
        }
    )
    chart = _flat_table_chart_with_data(data_in)
    data = _payload(
        chart.update.change_aggregation(
            chart.fields.by_guid("g_formula"),
            aggregation="sum",
            name="GMV",
            guid="gmv_sum",
        )
    )
    item = cast(dict[str, Any], data["visualization"]["placeholders"][0]["items"][0])
    assert item["guid"] == "gmv_sum"
    assert item["calc_mode"] == "formula"
    assert item["formula"] == "IF([flag], [gmv], [gmv] * [rate])"
    assert item["source"] == ""
    assert item["type"] == "MEASURE"
    assert item["aggregation"] == "sum"


def test_change_aggregation_replaces_existing_manual_measure() -> None:
    data_in = _base_flat_table_data()
    placed = cast(dict[str, Any], data_in["visualization"]["placeholders"][0]["items"][0])
    placed.update(
        {
            "guid": "gmv_sum",
            "title": "GMV sum",
            "type": "MEASURE",
            "data_type": "float",
            "calc_mode": "direct",
            "source": "gmv",
            "aggregation": "sum",
            "autoaggregated": False,
            "has_auto_aggregation": False,
            "local": True,
        }
    )
    chart = _flat_table_chart_with_data(data_in)
    data = _payload(
        chart.update.change_aggregation(
            chart.fields.by_guid("gmv_sum"),
            aggregation="avg",
            name="Average GMV",
            guid="gmv_avg",
        )
    )
    item = cast(dict[str, Any], data["visualization"]["placeholders"][0]["items"][0])
    assert item["guid"] == "gmv_avg"
    assert item["calc_mode"] == "direct"
    assert item["source"] == "gmv"
    assert item["aggregation"] == "avg"


def test_change_aggregation_rejects_automatic_measure() -> None:
    data_in = _base_flat_table_data()
    placed = cast(dict[str, Any], data_in["visualization"]["placeholders"][0]["items"][0])
    placed.update(
        {
            "guid": "g_trips",
            "title": "Trips",
            "type": "MEASURE",
            "calc_mode": "formula",
            "formula": "COUNT_IF([success])",
            "aggregation": "none",
            "autoaggregated": True,
            "has_auto_aggregation": True,
        }
    )
    chart = _flat_table_chart_with_data(data_in)
    with pytest.raises(DataLensValidationError, match="automatic aggregation"):
        chart.update.change_aggregation(chart.fields.by_guid("g_trips"), aggregation="sum", name="Trips sum")


def test_add_local_field_resolves_in_add_sort_same_update_race_fix() -> None:
    """P1-RACE: add_local_field + add_sort in one update must resolve."""
    chart = _flat_table_chart_with_data(_base_flat_table_data())
    data = _payload(
        chart.update.add_local_field(title="GMV/trip", formula="[gmv]/[trips]", guid="lf_race").add_sort("lf_race")
    )
    sort = cast(list[dict[str, Any]], data.get("sort", []))
    assert sort, "expected sort to be populated by add_sort resolving the new local field guid"
    # Resolution succeeded: the sort entry is a field snapshot dict, not an error.
    assert sort[0]["guid"] == "lf_race"


def test_add_local_field_preserves_legacy_updates() -> None:
    """P1-UPDATES: existing data['updates'] entries are preserved on append."""
    data_in = _base_flat_table_data()
    data_in["updates"] = [{"action": "update_field", "field": {"guid": "g_reg", "title": "Region Renamed"}}]
    chart = _flat_table_chart_with_data(data_in)
    data = _payload(chart.update.add_local_field(title="M", formula="[x]", guid="lf_keep"))
    updates = cast(list[dict[str, Any]], data["updates"])
    # Legacy update_field survives, new add_field appended.
    assert any(op.get("action") == "update_field" for op in updates)
    add_field_ops = [op for op in updates if op.get("action") == "add_field"]
    assert len(add_field_ops) == 1
    assert add_field_ops[0]["field"]["guid"] == "lf_keep"


def test_add_local_field_collision_raises() -> None:
    """P1-DROP: colliding guid raises instead of silently dropping."""
    data_in = _base_flat_table_data()
    data_in["updates"] = [{"action": "add_field", "field": {"guid": "dup", "title": "Old"}}]
    chart = _flat_table_chart_with_data(data_in)
    update = chart.update.add_local_field(title="New", formula="[x]", guid="dup")
    with pytest.raises(DataLensValidationError):
        _payload(update)


def test_add_local_field_merges_datasets_partial_fields() -> None:
    data_in = _base_flat_table_data()
    data_in["datasetsPartialFields"] = [[{"guid": "g_reg", "title": "Region"}]]
    chart = _flat_table_chart_with_data(data_in)
    data = _payload(chart.update.add_local_field(title="M", formula="[x]", guid="lf_dp"))
    snapshot = cast(list[list[dict[str, Any]]], data["datasetsPartialFields"])
    # Existing field preserved.
    flat = [f for group in snapshot for f in group]
    assert any(f.get("guid") == "g_reg" for f in flat)
    # New field prepended.
    assert any(f.get("guid") == "lf_dp" for f in flat)


def test_add_local_field_alone_counts_as_mutation() -> None:
    """_has_update_mutations: only add_local_field (no other edits) is non-empty."""
    chart = _flat_table_chart_with_data(_base_flat_table_data())
    update = chart.update.add_local_field(title="M", formula="[x]", guid="lf_only")
    data = _payload(update)
    # The data carried a non-empty 'updates' (the add_field op), proving the
    # update did not get short-circuited as empty.
    updates = cast(list[dict[str, Any]], data.get("updates", []))
    assert any(op.get("action") == "add_field" and op["field"]["guid"] == "lf_only" for op in updates)


def test_add_local_field_datasets_partial_preserves_existing_snapshot() -> None:
    """P1-UPDATES for datasetsPartialFields: existing snapshot groups preserved."""
    data_in = _base_flat_table_data()
    data_in["datasetsPartialFields"] = [
        [{"guid": "g_reg", "title": "Region"}],
        [{"guid": "g_city", "title": "City"}],
    ]
    chart = _flat_table_chart_with_data(data_in)
    data = _payload(chart.update.add_local_field(title="M", formula="[x]", guid="lf_snap"))
    snapshot = cast(list[list[dict[str, Any]]], data["datasetsPartialFields"])
    # Three groups: new field prepended to group 0, other group survives.
    assert len(snapshot) == 2
    assert any(f.get("guid") == "lf_snap" for f in snapshot[0])
    assert any(f.get("guid") == "g_reg" for f in snapshot[0])
    assert snapshot[1]
    assert snapshot[1][0]["guid"] == "g_city"
