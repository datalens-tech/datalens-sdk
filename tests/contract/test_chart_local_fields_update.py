"""Wizard V1 update parity for ``add_local_field`` and aggregation helpers.

These tests pin merge semantics against a chart loaded through the API-v3
response envelope while keeping the embedded chart on the Wizard V1 document
contract:

* field definitions are appended to ``data.sources.updates``;
* guid collisions fail instead of silently dropping an addition;
* newly added fields are immediately resolvable by subsequent mutations;
* existing source field definitions retain their order and contents.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk.converter.wizard.converter import WizardChartConverter
from datalens_sdk.domain.fields import DatasetField, WizardAggregatedMeasure, WizardLocalField
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError


def _line_chart_with_data(data: dict[str, Any]) -> WizardChart:
    return WizardChartConverter.to_domain(
        {
            "entry": {
                "createdAt": "2026-01-01T00:00:00.000Z",
                "createdBy": "user-1",
                "hidden": False,
                "key": "Users/example/chart-1",
                "meta": {},
                "public": False,
                "publishedId": "revision-1",
                "revId": "revision-1",
                "savedId": "revision-1",
                "scope": "widget",
                "tenantId": "tenant-1",
                "updatedAt": "2026-01-02T00:00:00.000Z",
                "updatedBy": "user-1",
                "version": 1,
                "entryId": "chart-1",
                "type": "d3_wizard_node",
                "workbookId": None,
                "data": data,
            },
            "isFavorite": False,
            "permissions": {"admin": True, "edit": True, "execute": True, "read": True},
        },
        installation="yacloud",
    )


def _region_definition() -> dict[str, Any]:
    return {
        "guid": "g_reg",
        "title": "Region",
        "type": "DIMENSION",
        "data_type": "string",
        "calc_mode": "direct",
        "source": "region",
        "datasetId": "ds1",
    }


def _base_line_data() -> dict[str, Any]:
    region = _region_definition()
    return {
        "sources": {
            "datasetsIds": ["ds1"],
            "updates": [{"action": "update_field", "field": dict(region)}],
        },
        "visualization": {
            "type": "line",
            "x": {"items": [{**region, "fakeTitle": "Region"}]},
            "y": {"items": []},
            "y2": {"items": []},
            "sort": {"items": []},
        },
    }


def _payload(update: Any) -> dict[str, Any]:
    return cast(dict[str, Any], WizardChartConverter.from_domain_update(update).to_payload()["data"])


def _source_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], data["sources"]["updates"])


def _added_field(data: dict[str, Any], guid: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        next(
            operation["field"]
            for operation in _source_updates(data)
            if operation.get("action") == "add_field" and operation["field"].get("guid") == guid
        ),
    )


def _x_item(data: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], data["visualization"]["x"]["items"][0])


def test_add_local_field_appends_add_field_to_updates() -> None:
    chart = _line_chart_with_data(_base_line_data())
    local = WizardLocalField.dimension(title="GMV/trip", formula="[gmv]/[trips]", guid="lf1")
    data = _payload(chart.update.add_local_field(local))
    field = _added_field(data, "lf1")
    assert field["guid"] == "lf1"
    assert field["calc_mode"] == "formula"
    assert field["formula"] == "[gmv]/[trips]"
    assert field["local"] is True
    assert field["datasetId"] == "ds1"


def test_add_local_field_measure_default_is_none_aggregation() -> None:
    chart = _line_chart_with_data(_base_line_data())
    local = WizardLocalField.measure(title="M", formula="[x]", guid="m1")
    data = _payload(chart.update.add_local_field(local))
    field = _added_field(data, "m1")
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "none"
    assert field["autoaggregated"] is True


def test_add_aggregated_measure_appends_direct_field() -> None:
    chart = _line_chart_with_data(_base_line_data())
    field_ref = DatasetField(
        guid="g_gmv",
        title="GMV",
        name="gmv",
        calc_mode="direct",
        data_type="float",
        type="DIMENSION",
        source="g_gmv_src",
    )
    measure = WizardAggregatedMeasure(
        field=field_ref,
        aggregation="sum",
        guid="agg1",
        title="GMV (sum)",
    )
    data = _payload(chart.update.add_aggregated_measure(measure).add_sort(measure))
    field = _added_field(data, "agg1")
    assert field["guid"] == "agg1"
    assert field["calc_mode"] == "direct"
    assert field["source"] == "g_gmv_src"
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "sum"
    assert field["autoaggregated"] is False
    assert field["local"] is True
    sort_item = cast(dict[str, Any], data["visualization"]["sort"]["items"][0])
    assert sort_item["guid"] == measure.guid


def test_add_aggregated_measure_copies_formula_dimension() -> None:
    chart = _line_chart_with_data(_base_line_data())
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
            WizardAggregatedMeasure(
                field=formula_dimension,
                aggregation="avg",
                title="Average GMV",
                guid="agg_formula",
            )
        )
    )
    field = _added_field(data, "agg_formula")
    assert field["guid"] == "agg_formula"
    assert field["title"] == "Average GMV"
    assert field["calc_mode"] == "formula"
    assert field["formula"] == "IF([flag], [gmv], [gmv] * [rate])"
    assert field["source"] == ""
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "avg"


def test_change_aggregation_replaces_placed_dimension_with_local_measure() -> None:
    data_in = _base_line_data()
    placed = cast(dict[str, Any], data_in["visualization"]["x"]["items"][0])
    placed.update({"id": "dimension-0", "formatting": {"precision": 0}})
    chart = _line_chart_with_data(data_in)
    data = _payload(
        chart.update.change_aggregation(
            chart.fields.by_guid("g_reg"),
            aggregation="count",
            name="Region count",
            guid="region_count",
        )
    )

    field = _added_field(data, "region_count")
    assert field["calc_mode"] == "direct"
    assert field["source"] == "region"
    assert field["data_type"] == "integer"
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "count"

    item = _x_item(data)
    assert item["guid"] == "region_count"
    assert item["datasetId"] == "ds1"
    assert item["id"] == "dimension-0"
    assert item["formatting"] == {"precision": 0}


def test_change_aggregation_copies_placed_formula_dimension() -> None:
    data_in = _base_line_data()
    placed = cast(dict[str, Any], data_in["visualization"]["x"]["items"][0])
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
    chart = _line_chart_with_data(data_in)
    data = _payload(
        chart.update.change_aggregation(
            chart.fields.by_guid("g_formula"),
            aggregation="sum",
            name="GMV",
            guid="gmv_sum",
        )
    )
    field = _added_field(data, "gmv_sum")
    assert field["guid"] == "gmv_sum"
    assert field["calc_mode"] == "formula"
    assert field["formula"] == "IF([flag], [gmv], [gmv] * [rate])"
    assert field["source"] == ""
    assert field["type"] == "MEASURE"
    assert field["aggregation"] == "sum"
    item = _x_item(data)
    assert item["guid"] == "gmv_sum"
    assert item["datasetId"] == "ds1"


def test_change_aggregation_replaces_existing_manual_measure() -> None:
    data_in = _base_line_data()
    placed = cast(dict[str, Any], data_in["visualization"]["x"]["items"][0])
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
    chart = _line_chart_with_data(data_in)
    data = _payload(
        chart.update.change_aggregation(
            chart.fields.by_guid("gmv_sum"),
            aggregation="avg",
            name="Average GMV",
            guid="gmv_avg",
        )
    )
    field = _added_field(data, "gmv_avg")
    assert field["guid"] == "gmv_avg"
    assert field["calc_mode"] == "direct"
    assert field["source"] == "gmv"
    assert field["aggregation"] == "avg"
    item = _x_item(data)
    assert item["guid"] == "gmv_avg"
    assert item["datasetId"] == "ds1"


def test_change_aggregation_rejects_automatic_measure() -> None:
    data_in = _base_line_data()
    placed = cast(dict[str, Any], data_in["visualization"]["x"]["items"][0])
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
    chart = _line_chart_with_data(data_in)
    with pytest.raises(DataLensValidationError, match="automatic aggregation"):
        chart.update.change_aggregation(chart.fields.by_guid("g_trips"), aggregation="sum", name="Trips sum")


def test_add_local_field_resolves_in_add_sort_same_update_race_fix() -> None:
    """A field added in this update is available to subsequent mutations."""
    chart = _line_chart_with_data(_base_line_data())
    local = WizardLocalField.measure(title="GMV/trip", formula="[gmv]/[trips]", guid="lf_race")
    data = _payload(chart.update.add_local_field(local).add_sort(local))
    sort = cast(list[dict[str, Any]], data["visualization"]["sort"]["items"])
    assert sort == [{"guid": "lf_race", "datasetId": "ds1", "direction": "ASC"}]


def test_add_local_field_formatting_stays_on_carrier_in_same_update() -> None:
    chart = _line_chart_with_data(_base_line_data())
    local = WizardLocalField.measure(
        title="GMV/trip",
        formula="[gmv]/[trips]",
        guid="lf_formatted",
        formatting={"format": "number", "precision": 2},
    )

    data = _payload(chart.update.add_local_field(local).y([local]).add_sort(local, direction="desc"))

    source_field = _added_field(data, local.guid)
    assert "formatting" not in source_field
    y_items = cast(list[dict[str, Any]], data["visualization"]["y"]["items"])
    assert y_items[0]["formatting"] == {"format": "number", "precision": 2}
    assert data["visualization"]["sort"]["items"] == [{"guid": local.guid, "datasetId": "ds1", "direction": "DESC"}]


def test_remembered_local_field_handle_resolves_after_fetch_by_guid() -> None:
    local = WizardLocalField.measure(
        title="GMV/trip",
        formula="[gmv]/[trips]",
        guid="lf-remembered",
        formatting={"format": "number", "precision": 3},
    )
    data_in = _base_line_data()
    data_in["sources"]["updates"].append(
        {
            "action": "add_field",
            "field": {
                "guid": local.guid,
                "title": local.title,
                "formula": local.formula,
                "calc_mode": "formula",
                "cast": "float",
                "data_type": "float",
                "type": "MEASURE",
                "aggregation": "none",
                "autoaggregated": True,
                "local": True,
                "datasetId": "ds1",
            },
        }
    )
    data_in["visualization"]["y"]["items"] = [{"guid": local.guid, "datasetId": "ds1"}]
    chart = _line_chart_with_data(data_in)

    fetched = chart.fields.by_guid(local.guid)
    assert isinstance(fetched, DatasetField)
    assert fetched.title == local.title

    data = _payload(chart.update.y([local]).add_sort(local))
    y_item = cast(dict[str, Any], data["visualization"]["y"]["items"][0])
    assert y_item["formatting"] == {"format": "number", "precision": 3}
    sort = cast(list[dict[str, Any]], data["visualization"]["sort"]["items"])
    assert sort == [{"guid": local.guid, "datasetId": "ds1", "direction": "ASC"}]


def test_remembered_aggregated_measure_handle_resolves_after_fetch_by_guid() -> None:
    source = DatasetField(
        guid="g_city",
        title="City",
        name="City",
        calc_mode="direct",
        data_type="string",
        type="DIMENSION",
        source="city",
        dataset_id="ds1",
    )
    measure = WizardAggregatedMeasure(
        field=source,
        aggregation="countunique",
        title="Unique cities",
        guid="agg-remembered",
    )
    data_in = _base_line_data()
    data_in["sources"]["updates"].append(
        {
            "action": "add_field",
            "field": {
                "guid": measure.guid,
                "title": measure.title,
                "calc_mode": "direct",
                "source": "city",
                "cast": "string",
                "data_type": "integer",
                "type": "MEASURE",
                "aggregation": "countunique",
                "autoaggregated": False,
                "local": True,
                "datasetId": "ds1",
            },
        }
    )
    data_in["visualization"]["y"]["items"] = [{"guid": measure.guid, "datasetId": "ds1"}]
    chart = _line_chart_with_data(data_in)

    assert isinstance(chart.fields.by_guid(measure.guid), DatasetField)
    data = _payload(chart.update.add_sort(measure))
    sort = cast(list[dict[str, Any]], data["visualization"]["sort"]["items"])
    assert sort == [{"guid": measure.guid, "datasetId": "ds1", "direction": "ASC"}]


def test_add_local_field_preserves_existing_source_updates() -> None:
    data_in = _base_line_data()
    existing = {"action": "update_field", "field": {"guid": "g_reg", "title": "Region Renamed"}}
    data_in["sources"]["updates"] = [existing]
    chart = _line_chart_with_data(data_in)
    data = _payload(chart.update.add_local_field(WizardLocalField.dimension(title="M", formula="[x]", guid="lf_keep")))
    updates = _source_updates(data)
    assert updates[0] == existing
    assert updates[1]["action"] == "add_field"
    assert updates[1]["field"]["guid"] == "lf_keep"


def test_add_local_field_collision_raises() -> None:
    data_in = _base_line_data()
    data_in["sources"]["updates"].append({"action": "add_field", "field": {"guid": "dup", "title": "Old"}})
    chart = _line_chart_with_data(data_in)
    update = chart.update.add_local_field(WizardLocalField.dimension(title="New", formula="[x]", guid="dup"))
    with pytest.raises(DataLensValidationError, match="already exists"):
        _payload(update)


def test_add_local_field_preserves_existing_field_definition() -> None:
    data_in = _base_line_data()
    existing = {"action": "add_field", "field": {**_region_definition(), "local": True}}
    data_in["sources"]["updates"] = [existing]
    chart = _line_chart_with_data(data_in)
    data = _payload(chart.update.add_local_field(WizardLocalField.dimension(title="M", formula="[x]", guid="lf_dp")))
    updates = _source_updates(data)
    assert updates[0] == existing
    assert updates[1]["action"] == "add_field"
    assert updates[1]["field"]["guid"] == "lf_dp"


def test_add_local_field_alone_counts_as_mutation() -> None:
    chart = _line_chart_with_data(_base_line_data())
    update = chart.update.add_local_field(WizardLocalField.dimension(title="M", formula="[x]", guid="lf_only"))
    data = _payload(update)
    assert _added_field(data, "lf_only")["guid"] == "lf_only"


def test_add_local_field_preserves_existing_field_definition_order() -> None:
    data_in = _base_line_data()
    existing = [
        {"action": "add_field", "field": {**_region_definition(), "local": True}},
        {
            "action": "add_field",
            "field": {
                "guid": "g_city",
                "title": "City",
                "type": "DIMENSION",
                "data_type": "string",
                "calc_mode": "direct",
                "source": "city",
                "datasetId": "ds1",
                "local": True,
            },
        },
    ]
    data_in["sources"]["updates"] = existing
    chart = _line_chart_with_data(data_in)
    data = _payload(chart.update.add_local_field(WizardLocalField.dimension(title="M", formula="[x]", guid="lf_snap")))
    updates = _source_updates(data)
    assert updates[:2] == existing
    assert updates[2]["action"] == "add_field"
    assert updates[2]["field"]["guid"] == "lf_snap"
