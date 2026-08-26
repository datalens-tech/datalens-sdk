from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Any, Literal, cast

import pytest

from datalens_sdk._generated.dto import WIZARD_VISUALIZATION_STRUCTURE
from datalens_sdk._runtime.wizard_semantics import resolve_slot_name
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError

Carrier = Literal["slot", "filter", "sort", "color", "label", "segment", "shape", "hierarchy"]
Operation = Literal["replace", "delete", "aggregation", "dataset"]

_OLD_GUID = "old-guid"
_NEW_GUID = "new-guid"
_OLD_DATASET = "old-dataset"
_NEW_DATASET = "new-dataset"
_CARRIERS: tuple[Carrier, ...] = (
    "slot",
    "filter",
    "sort",
    "color",
    "label",
    "segment",
    "shape",
    "hierarchy",
)
_SLOT_NAMES: dict[Carrier, str] = {
    "slot": "x",
    "sort": "sort",
    "color": "colors",
    "label": "labels",
    "segment": "segments",
    "shape": "shapes",
}


def _field(
    guid: str = _OLD_GUID,
    *,
    title: str = "Old field",
    dataset_id: str = _OLD_DATASET,
) -> dict[str, Any]:
    return {
        "guid": guid,
        "title": title,
        "type": "DIMENSION",
        "data_type": "string",
        "calc_mode": "direct",
        "source": f"{guid}-source",
        "datasetId": dataset_id,
        "formatting": {"precision": 1},
    }


def _replacement_field() -> DatasetField:
    return DatasetField(
        guid=_NEW_GUID,
        title="New field",
        name="New field",
        type="MEASURE",
        data_type="float",
        calc_mode="direct",
        source="new-source",
        aggregation="sum",
        dataset_id=_NEW_DATASET,
    )


def _data_for_carrier(carrier: Carrier, *, visualization_id: str = "line") -> dict[str, Any]:
    target = _field()
    keep = _field("keep-guid", title="Keep field")
    if carrier == "filter":
        target["filter"] = {"operation": {"code": "EQ"}, "value": ["old"]}
        keep["filter"] = {"operation": {"code": "EQ"}, "value": ["keep"]}
    if carrier == "sort":
        target["direction"] = "DESC"
        keep["direction"] = "ASC"
    structure = WIZARD_VISUALIZATION_STRUCTURE[visualization_id]
    visualization: dict[str, Any] = {
        "type": visualization_id,
        **{slot_name: {"items": []} for slot_name in structure["slots"]},
    }
    data: dict[str, Any] = {
        "sources": {"datasetsIds": [_OLD_DATASET]},
        "visualization": visualization,
    }
    if carrier == "filter":
        cast(dict[str, Any], data["sources"])["filters"] = [target, keep]
    elif carrier == "hierarchy":
        cast(dict[str, Any], data["sources"])["hierarchies"] = [
            {"guid": "hierarchy-guid", "title": "Hierarchy", "fields": [target, keep]}
        ]
    else:
        slot_name = resolve_slot_name(visualization_id, _SLOT_NAMES[carrier])
        visualization[slot_name]["items"] = [target, keep]
    return data


def _chart(data: dict[str, Any]) -> WizardChart:
    return WizardChart(
        id="chart-1",
        installation="yacloud",
        data=data,
    )


def _loaded_chart(data: dict[str, Any]) -> WizardChart:
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


def _data_with_links() -> dict[str, Any]:
    data = _data_for_carrier("slot")
    sources = cast(dict[str, Any], data["sources"])
    sources["datasetsIds"] = [_OLD_DATASET, "peer-dataset"]
    sources["links"] = [
        {
            "id": "link-1",
            "futureLink": {"keep": True},
            "fields": {
                _OLD_DATASET: {
                    "futureEntry": {"keep": True},
                    "dataset": {"id": _OLD_DATASET, "realName": "Old dataset", "future": True},
                    "field": {"guid": _OLD_GUID, "title": "Old field", "future": True},
                },
                "peer-dataset": {
                    "dataset": {"id": "peer-dataset", "realName": "Peer dataset"},
                    "field": {"guid": "peer-guid", "title": "Peer field"},
                },
            },
        }
    ]
    return data


def _same_dataset_replacement_field() -> DatasetField:
    return DatasetField(
        guid=_NEW_GUID,
        title="New linked field",
        name="New linked field",
        type="MEASURE",
        data_type="float",
        calc_mode="direct",
        source="new-source",
        aggregation="sum",
        dataset_id=_OLD_DATASET,
    )


def _payload(update: object) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        WizardChartConverter.from_domain_update(cast(Any, update)).to_payload()["data"],
    )


def test_fields_proxy_enriches_compact_active_local_reference_from_definition() -> None:
    data = _data_for_carrier("slot")
    visualization = cast(dict[str, Any], data["visualization"])
    visualization["x"]["items"] = [{"guid": _OLD_GUID, "datasetId": _OLD_DATASET}]
    cast(dict[str, Any], data["sources"])["updates"] = [
        {
            "action": "add_field",
            "field": {
                "guid": _OLD_GUID,
                "title": "Local count",
                "type": "MEASURE",
                "data_type": "integer",
                "aggregation": "count",
                "local": True,
            },
        }
    ]

    field = _chart(data).fields.by_guid(_OLD_GUID)

    assert field.title == "Local count"
    assert field.type == "MEASURE"
    assert field.data_type == "integer"
    assert field.aggregation == "count"
    assert field.dataset_id == _OLD_DATASET


def _carrier_items(data: Mapping[str, Any], carrier: Carrier) -> list[dict[str, Any]]:
    if carrier == "filter":
        return cast(list[dict[str, Any]], data["sources"]["filters"])
    if carrier == "hierarchy":
        return cast(list[dict[str, Any]], data["sources"]["hierarchies"][0]["fields"])
    visualization = cast(Mapping[str, Any], data["visualization"])
    return cast(list[dict[str, Any]], visualization[_SLOT_NAMES[carrier]]["items"])


@pytest.mark.parametrize("carrier", _CARRIERS)
def test_replace_field_replaces_complete_snapshot_in_every_carrier(carrier: Carrier) -> None:
    chart = _chart(_data_for_carrier(carrier))

    items = _carrier_items(_payload(chart.update.replace_field(_OLD_GUID, _replacement_field())), carrier)

    assert [item["guid"] for item in items] == [_NEW_GUID, "keep-guid"]
    replaced = items[0]
    if carrier in {"filter", "sort", "hierarchy"}:
        assert replaced["title"] == "Old field"
        assert replaced["type"] == "DIMENSION"
        assert replaced["data_type"] == "string"
        assert replaced["source"] == f"{_OLD_GUID}-source"
    else:
        assert set(replaced) == {"guid", "datasetId", "formatting"}
    assert replaced["datasetId"] == _NEW_DATASET
    assert replaced["formatting"] == {"precision": 1}
    if carrier == "filter":
        assert replaced["filter"] == {"operation": {"code": "EQ"}, "value": ["old"]}
    if carrier == "sort":
        assert replaced["direction"] == "DESC"


@pytest.mark.parametrize("carrier", _CARRIERS)
def test_delete_field_removes_every_carrier_item_and_preserves_order(carrier: Carrier) -> None:
    chart = _chart(_data_for_carrier(carrier))

    items = _carrier_items(_payload(chart.update.delete_field(_OLD_GUID)), carrier)

    assert [item["guid"] for item in items] == ["keep-guid"]


@pytest.mark.parametrize("carrier", _CARRIERS)
def test_change_aggregation_replaces_every_carrier_snapshot(carrier: Carrier) -> None:
    chart = _chart(_data_for_carrier(carrier))
    placed = chart.fields.by_guid(_OLD_GUID)

    data = _payload(
        chart.update.change_aggregation(
            placed,
            aggregation="count",
            name="Old field count",
            guid="aggregated-guid",
        )
    )
    items = _carrier_items(data, carrier)

    assert [item["guid"] for item in items] == ["aggregated-guid", "keep-guid"]
    assert items[0]["formatting"] == {"precision": 1}
    definition = cast(list[dict[str, Any]], data["sources"]["updates"])[0]["field"]
    assert definition["type"] == "MEASURE"
    assert definition["aggregation"] == "count"


@pytest.mark.parametrize("carrier", _CARRIERS)
def test_replace_dataset_updates_every_carrier_snapshot(carrier: Carrier) -> None:
    chart = _chart(_data_for_carrier(carrier))

    data = _payload(chart.update.replace_dataset(old=_OLD_DATASET, new=_NEW_DATASET))
    items = _carrier_items(data, carrier)

    assert data["sources"]["datasetsIds"] == [_NEW_DATASET]
    assert {item["datasetId"] for item in items} == {_NEW_DATASET}


@pytest.mark.parametrize("operation", ["replace", "delete", "aggregation"])
def test_structural_mutations_update_color_and_shape_config_pointers(operation: Operation) -> None:
    data = _data_for_carrier("slot")
    visualization = cast(dict[str, Any], data["visualization"])
    visualization["colors"] = {
        "items": [_field()],
        "settings": {"fieldGuid": _OLD_GUID, "palette": "datalens-classic-20"},
    }
    visualization["shapes"] = {
        "items": [_field()],
        "settings": {"fieldGuid": _OLD_GUID, "mountedShapes": {"Old field": "Solid"}},
    }
    chart = _chart(data)

    if operation == "replace":
        result = _payload(chart.update.replace_field(_OLD_GUID, _replacement_field()))
        assert result["visualization"]["colors"]["settings"]["fieldGuid"] == _NEW_GUID
        assert result["visualization"]["shapes"]["settings"]["fieldGuid"] == _NEW_GUID
    elif operation == "delete":
        result = _payload(chart.update.delete_field(_OLD_GUID))
        assert result["visualization"]["colors"]["settings"] == {"palette": "datalens-classic-20"}
        assert result["visualization"]["shapes"]["settings"] == {"mountedShapes": {"Old field": "Solid"}}
    else:
        result = _payload(
            chart.update.change_aggregation(
                chart.fields.by_guid(_OLD_GUID),
                aggregation="sum",
                name="Old field sum",
                guid="aggregated-guid",
            )
        )
        assert result["visualization"]["colors"]["settings"]["fieldGuid"] == "aggregated-guid"
        assert result["visualization"]["shapes"]["settings"]["fieldGuid"] == "aggregated-guid"


def _combined_data() -> dict[str, Any]:
    return {
        "sources": {
            "datasetsIds": [_OLD_DATASET],
            "filters": [{**_field(), "filter": {"operation": {"code": "IN"}, "value": ["old"]}}],
            "updates": [{"action": "add_field", "field": _field()}],
        },
        "visualization": {
            "type": "combined-chart",
            "selectedLayerId": "layer-1",
            "layers": [
                {
                    "type": "line",
                    "layerSettings": {"id": "layer-1", "name": "Line"},
                    "x": {"items": [_field()]},
                    "y": {"items": [_field()]},
                    "colors": {
                        "items": [_field()],
                        "settings": {"fieldGuid": _OLD_GUID, "palette": "classic20"},
                    },
                    "labels": {"items": [_field()]},
                    "shapes": {
                        "items": [_field()],
                        "settings": {"fieldGuid": _OLD_GUID, "mountedShapes": {_OLD_GUID: "Solid"}},
                    },
                    "sort": {"items": [{**_field(), "direction": "ASC"}]},
                }
            ],
        },
    }


def _all_field_guids(value: object) -> list[str]:
    guids: list[str] = []
    if isinstance(value, Mapping):
        guid = value.get("guid")
        if isinstance(guid, str):
            guids.append(guid)
        field_guid = value.get("fieldGuid")
        if isinstance(field_guid, str):
            guids.append(field_guid)
        for nested in value.values():
            guids.extend(_all_field_guids(nested))
    elif isinstance(value, list):
        for nested in value:
            guids.extend(_all_field_guids(nested))
    return guids


def _all_dataset_ids(value: object) -> list[str]:
    dataset_ids: list[str] = []
    if isinstance(value, Mapping):
        dataset_id = value.get("datasetId")
        if isinstance(dataset_id, str):
            dataset_ids.append(dataset_id)
        for nested in value.values():
            dataset_ids.extend(_all_dataset_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            dataset_ids.extend(_all_dataset_ids(nested))
    return dataset_ids


@pytest.mark.parametrize("operation", ["replace", "delete", "aggregation", "dataset"])
def test_structural_mutations_traverse_combined_layers(operation: Operation) -> None:
    chart = _chart(_combined_data())
    if operation == "replace":
        data = _payload(chart.update.replace_field(_OLD_GUID, _replacement_field()))
        active_guids = _all_field_guids(cast(dict[str, Any], data["visualization"]))
        assert _OLD_GUID not in active_guids
        assert _NEW_GUID in active_guids
    elif operation == "delete":
        data = _payload(chart.update.delete_field(_OLD_GUID))
        assert _OLD_GUID not in _all_field_guids(cast(dict[str, Any], data["visualization"]))
    elif operation == "aggregation":
        data = _payload(
            chart.update.change_aggregation(
                chart.fields.by_guid(_OLD_GUID),
                aggregation="sum",
                name="Old field sum",
                guid="aggregated-guid",
            )
        )
        active_guids = _all_field_guids(cast(dict[str, Any], data["visualization"]))
        assert _OLD_GUID not in active_guids
        assert "aggregated-guid" in active_guids
    else:
        data = _payload(chart.update.replace_dataset(old=_OLD_DATASET, new=_NEW_DATASET))
        assert _OLD_DATASET not in _all_dataset_ids(data)
        assert _NEW_DATASET in _all_dataset_ids(data)


def test_wizard_chart_fields_includes_combined_layer_carriers() -> None:
    data = _combined_data()
    layer = cast(dict[str, Any], data["visualization"]["layers"][0])
    layer["colors"] = {"items": [_field("color-guid", title="Color")]}
    layer["shapes"] = {"items": [_field("shape-guid", title="Shape")]}
    layer["labels"] = {"items": [_field("label-guid", title="Label")]}
    layer["x"] = {"items": [_field("layer-guid", title="Layer")]}

    assert {field.guid for field in _chart(data).fields} >= {
        "color-guid",
        "shape-guid",
        "label-guid",
        "layer-guid",
    }


def test_wizard_chart_fields_rejects_conflicting_snapshots_for_one_guid() -> None:
    data = _data_for_carrier("slot")
    conflicting = _field()
    conflicting["formatting"] = {"precision": 2}
    data["visualization"]["colors"]["items"] = [conflicting]

    with pytest.raises(DataLensValidationError, match="conflicting snapshots"):
        list(_chart(data).fields)


def test_replace_field_rejects_unknown_string_replacement() -> None:
    chart = _chart(_data_for_carrier("slot"))

    with pytest.raises(DataLensValidationError, match="not placed"):
        _payload(chart.update.replace_field(_OLD_GUID, "unknown-guid"))


def test_replace_field_rejects_ambiguous_string_replacement() -> None:
    data = _data_for_carrier("slot")
    data["visualization"]["colors"]["items"] = [
        _field("duplicate-1", title="Duplicate"),
        _field("duplicate-2", title="Duplicate"),
    ]
    chart = _chart(data)

    with pytest.raises(DataLensValidationError, match="ambiguous"):
        _payload(chart.update.replace_field(_OLD_GUID, "Duplicate"))


def test_structural_mutations_reject_unknown_targets_instead_of_becoming_noops() -> None:
    chart = _chart(_data_for_carrier("slot"))

    with pytest.raises(DataLensValidationError, match="not referenced"):
        _payload(chart.update.replace_field("unknown-guid", _replacement_field()))
    with pytest.raises(DataLensValidationError, match="not referenced"):
        _payload(chart.update.delete_field("unknown-guid"))
    with pytest.raises(DataLensValidationError, match="chart datasets"):
        _payload(chart.update.replace_dataset(old="unknown-dataset", new=_NEW_DATASET))


@pytest.mark.parametrize("operation", ["delete", "replace"])
@pytest.mark.parametrize("carrier", ["slot", "data_field"])
@pytest.mark.parametrize("edit_first", [False, True], ids=["structural-first", "edit-first"])
def test_structural_mutations_reject_staged_edits_that_restore_old_guid(
    operation: Literal["delete", "replace"],
    carrier: Literal["slot", "data_field"],
    edit_first: bool,
) -> None:
    chart = _chart(_data_for_carrier("slot"))
    old = chart.fields.by_guid(_OLD_GUID)
    update = chart.update

    def apply_edit() -> None:
        if carrier == "slot":
            update.x([old])
        else:
            update.labels([old])

    def apply_structural_mutation() -> None:
        if operation == "delete":
            update.delete_field(old)
        else:
            update.replace_field(old, _replacement_field())

    if edit_first:
        apply_edit()
        apply_structural_mutation()
    else:
        apply_structural_mutation()
        apply_edit()

    with pytest.raises(DataLensValidationError, match=r"left stale guid 'old-guid'"):
        _payload(update)


def test_funnel_uses_the_shared_structural_mutation_path() -> None:
    chart = _chart(_data_for_carrier("slot", visualization_id="funnel"))

    visualization = _payload(chart.update.replace_field(_OLD_GUID, _replacement_field()))["visualization"]
    items = cast(list[dict[str, Any]], visualization["dimensions"]["items"])

    assert items[0]["guid"] == _NEW_GUID
    assert items[0] == {"guid": _NEW_GUID, "datasetId": _NEW_DATASET, "formatting": {"precision": 1}}


def test_read_to_update_replace_field_updates_link_identity_and_preserves_open_fields() -> None:
    chart = _loaded_chart(_data_with_links())

    data = _payload(chart.update.replace_field(_OLD_GUID, _same_dataset_replacement_field()))

    link = data["sources"]["links"][0]
    assert link["futureLink"] == {"keep": True}
    assert set(link["fields"]) == {_OLD_DATASET, "peer-dataset"}
    linked = link["fields"][_OLD_DATASET]
    assert linked["field"] == {"guid": _NEW_GUID, "title": "New linked field", "future": True}
    assert linked["dataset"] == {"id": _OLD_DATASET, "realName": "Old dataset", "future": True}
    assert linked["futureEntry"] == {"keep": True}


@pytest.mark.parametrize("operation", ["delete_field", "replace_dataset", "replace_across_datasets"])
def test_read_to_update_link_mutations_fail_before_owned_snapshot_changes(operation: str) -> None:
    chart = _loaded_chart(_data_with_links())
    before = copy.deepcopy(chart.data)
    if operation == "delete_field":
        update = chart.update.delete_field(_OLD_GUID)
        message = "Deleting linked field"
    elif operation == "replace_dataset":
        update = chart.update.replace_dataset(old=_OLD_DATASET, new=_NEW_DATASET)
        message = "explicit link mapping"
    else:
        update = chart.update.replace_field(_OLD_GUID, _replacement_field())
        message = "explicit link mapping"

    with pytest.raises(DataLensValidationError, match=message):
        _payload(update)

    assert chart.data == before


def test_read_to_update_link_field_map_collision_fails_closed() -> None:
    data = _data_with_links()
    fields = data["sources"]["links"][0]["fields"]
    fields[_NEW_DATASET] = {
        "dataset": {"id": _NEW_DATASET, "realName": "New dataset"},
        "field": {"guid": "occupied-guid", "title": "Occupied field"},
    }
    chart = _loaded_chart(data)
    before = copy.deepcopy(chart.data)

    with pytest.raises(DataLensValidationError, match="collide"):
        _payload(chart.update.replace_field(_OLD_GUID, _replacement_field()))

    assert chart.data == before
