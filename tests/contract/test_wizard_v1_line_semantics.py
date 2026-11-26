from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk.converter.wizard.converter import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError


def _dataset() -> Dataset:
    return Dataset(
        id="dataset-1",
        name="sales",
        location=EntryLocation.path("/"),
        result_schema=(
            {
                "guid": "date-guid",
                "title": "Date",
                "type": "DIMENSION",
                "data_type": "date",
                "calc_mode": "direct",
            },
            {
                "guid": "region-guid",
                "title": "Region",
                "type": "DIMENSION",
                "data_type": "string",
                "calc_mode": "direct",
            },
            {
                "guid": "amount-guid",
                "title": "Amount",
                "type": "MEASURE",
                "data_type": "float",
                "calc_mode": "direct",
            },
            {
                "guid": "count-guid",
                "title": "Count",
                "type": "MEASURE",
                "data_type": "integer",
                "calc_mode": "direct",
            },
            {
                "guid": "unused-guid",
                "title": "Unused",
                "type": "MEASURE",
                "data_type": "float",
                "calc_mode": "direct",
            },
            {
                "guid": "threshold-guid",
                "title": "Threshold",
                "calc_mode": "parameter",
                "data_type": "float",
            },
        ),
    )


def _line_builder() -> Any:
    return WizardChartCreateFactory(cast(Any, None)).line(
        name="Line",
        location=EntryLocation.path("/Charts"),
    )


def _create_data(builder: Any) -> dict[str, Any]:
    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()
    return cast(dict[str, Any], payload["data"])


def _line_response() -> dict[str, object]:
    return {
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
            "data": {
                "sources": {"datasetsIds": ["dataset-1"]},
                "visualization": {
                    "type": "line",
                    "x": {
                        "items": [
                            {
                                "guid": "date-guid",
                                "datasetId": "dataset-1",
                                "fakeTitle": "Date",
                                "type": "DIMENSION",
                                "data_type": "date",
                            }
                        ]
                    },
                    "y": {
                        "items": [
                            {
                                "guid": "amount-guid",
                                "datasetId": "dataset-1",
                                "fakeTitle": "Amount",
                                "type": "MEASURE",
                                "data_type": "float",
                            }
                        ]
                    },
                    "y2": {
                        "items": [
                            {
                                "guid": "count-guid",
                                "datasetId": "dataset-1",
                                "fakeTitle": "Count",
                                "type": "MEASURE",
                                "data_type": "integer",
                            }
                        ]
                    },
                    "colors": {
                        "items": [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}],
                        "settings": {
                            "coloredByMeasure": True,
                            "mountedColors": {"amount-guid": "#111111", "count-guid": "#222222"},
                            "futureSetting": {"kept": True},
                        },
                        "futureSlot": {"kept": True},
                    },
                },
            },
        },
        "isFavorite": False,
        "permissions": {"admin": True, "edit": True, "execute": True, "read": True},
    }


def test_measure_name_color_and_shape_bind_only_placed_line_measures() -> None:
    data = _create_data(
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .y2(["Count"])
        .color_by_measure_name(colors_map={"Amount": "#001122", "Count": "#334455"})
        .shape_by_measure_name(shapes_map={"Amount": "Solid", "Count": "Dash"})
    )

    visualization = data["visualization"]
    assert visualization["colors"]["items"] == [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}]
    assert visualization["colors"]["settings"]["mountedColors"] == {
        "amount-guid": "#001122",
        "count-guid": "#334455",
    }
    assert visualization["shapes"]["items"] == [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}]
    assert visualization["shapes"]["settings"]["mountedShapes"] == {
        "amount-guid": "Solid",
        "count-guid": "Dash",
    }


@pytest.mark.parametrize("encoding", ["color", "shape"])
def test_measure_name_encoding_requires_two_placed_measures(encoding: str) -> None:
    builder = _line_builder().dataset(_dataset()).x(["Date"]).y(["Amount"])
    if encoding == "color":
        builder.color_by_measure_name()
    else:
        builder.shape_by_measure_name()

    with pytest.raises(DataLensConfigurationError, match="at least two measures"):
        _create_data(builder)


@pytest.mark.parametrize("encoding", ["color", "shape"])
def test_measure_name_encoding_rejects_unplaced_measure_mapping(encoding: str) -> None:
    builder = _line_builder().dataset(_dataset()).x(["Date"]).y(["Amount", "Count"])
    if encoding == "color":
        builder.color_by_measure_name(colors_map={"Unused": "#001122"})
    else:
        builder.shape_by_measure_name(shapes_map={"Unused": "Dash"})

    with pytest.raises(DataLensConfigurationError, match="not placed as a measure"):
        _create_data(builder)


def test_measure_name_color_rejects_non_hex_value() -> None:
    builder = (
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount", "Count"])
        .color_by_measure_name(colors_map={"Amount": "red"})
    )

    with pytest.raises(DataLensConfigurationError, match="#RRGGBB"):
        _create_data(builder)


def test_dimension_shape_mapping_keeps_dimension_values_as_map_keys() -> None:
    data = _create_data(
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .shape_by_dimension("Region", shapes_map={"North": "Solid", "South": "Dash"})
    )

    settings = data["visualization"]["shapes"]["settings"]
    assert settings["fieldGuid"] == "region-guid"
    assert settings["mountedShapes"] == {"North": "Solid", "South": "Dash"}


def test_encoding_update_preserves_unknown_document_v1_slot_and_settings() -> None:
    chart = WizardChartConverter.to_domain(_line_response(), installation="yacloud")

    payload = WizardChartConverter.from_domain_update(
        chart.update.color_by_measure_name(colors_map={"Amount": "#001122", "Count": "#334455"})
    ).to_payload()

    data = cast(dict[str, Any], payload["data"])
    colors = data["visualization"]["colors"]
    assert colors["futureSlot"] == {"kept": True}
    assert colors["settings"]["futureSetting"] == {"kept": True}
    assert colors["settings"]["mountedColors"] == {
        "amount-guid": "#001122",
        "count-guid": "#334455",
    }


def test_measure_format_update_merges_existing_document_v1_formatting() -> None:
    response = _line_response()
    entry = cast(dict[str, Any], response["entry"])
    data = cast(dict[str, Any], entry["data"])
    amount = data["visualization"]["y"]["items"][0]
    amount["formatting"] = {
        "format": "number",
        "unit": "k",
        "futureFormatting": {"kept": True},
    }
    chart = WizardChartConverter.to_domain(response, installation="yacloud")

    payload = WizardChartConverter.from_domain_update(chart.update.measure_format("Amount", precision=2)).to_payload()

    updated_data = cast(dict[str, Any], payload["data"])
    updated_amount = updated_data["visualization"]["y"]["items"][0]
    assert updated_amount["formatting"] == {
        "format": "number",
        "unit": "k",
        "futureFormatting": {"kept": True},
        "precision": 2,
    }


def test_label_mode_built_chart_remains_readable_with_different_placement_formatting() -> None:
    data = _create_data(
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .labels(["Amount"])
        .measure_format("Amount", precision=2)
        .label_mode(mode="absolute")
    )
    response = _line_response()
    cast(dict[str, Any], response["entry"])["data"] = data
    chart = WizardChartConverter.to_domain(response, installation="yacloud")

    visualization = cast(dict[str, Any], chart.data["visualization"])
    assert chart.fields.by_guid("amount-guid").raw == visualization["labels"]["items"][0]
    assert visualization["y"]["items"][0]["formatting"] == {"precision": 2}
    assert visualization["labels"]["items"][0]["formatting"] == {
        "precision": 2,
        "labelMode": "absolute",
    }


@pytest.mark.parametrize("dataset_ids", [["dataset-1"], ["dataset-1", "dataset-2"]], ids=["single", "multiple"])
def test_new_placement_requires_a_resolvable_dataset_id(dataset_ids: list[str]) -> None:
    response = _line_response()
    entry = cast(dict[str, Any], response["entry"])
    entry["data"]["sources"]["datasetsIds"] = dataset_ids
    axis = entry["data"]["visualization"]["y"]["items"][0]
    axis["datasetId"] = ""
    chart = WizardChartConverter.to_domain(response, installation="yacloud")
    before = copy.deepcopy(chart.data)
    measure = chart.fields.by_guid("amount-guid")
    assert measure.dataset_id is None
    if len(dataset_ids) > 1:
        with pytest.raises(DataLensValidationError, match="DatasetField"):
            WizardChartConverter.from_domain_update(chart.update.labels([measure]))
        secondary = replace(_dataset(), id="dataset-2")
        measure = secondary.fields.by_guid("amount-guid")

    payload = WizardChartConverter.from_domain_update(chart.update.labels([measure])).to_payload()
    saved = cast(dict[str, Any], payload["data"])

    assert saved["visualization"]["y"]["items"][0] == axis
    assert saved["visualization"]["labels"]["items"][0]["datasetId"] == dataset_ids[-1]
    entry["data"] = saved
    reread = WizardChartConverter.to_domain(response, installation="yacloud").fields.by_guid("amount-guid")
    assert reread.dataset_id == dataset_ids[-1]
    assert chart.data == before


def test_measure_format_patches_unknown_dataset_placement_using_its_guid() -> None:
    response = _line_response()
    entry = cast(dict[str, Any], response["entry"])
    entry["data"]["sources"]["datasetsIds"] = ["dataset-1", "dataset-2"]
    axis = entry["data"]["visualization"]["y"]["items"][0]
    axis.update({"datasetId": "", "formatting": {"format": "number", "precision": 2}})
    chart = WizardChartConverter.to_domain(response, installation="yacloud")
    before = copy.deepcopy(chart.data)

    payload = WizardChartConverter.from_domain_update(chart.update.measure_format("amount-guid", precision=4))
    saved = cast(dict[str, Any], payload.to_payload()["data"])

    assert saved["visualization"]["y"]["items"] == [{**axis, "formatting": {"format": "number", "precision": 4}}]
    assert saved["sources"] == before["sources"]
    entry["data"] = saved
    reread = WizardChartConverter.to_domain(response, installation="yacloud").fields.by_guid("amount-guid")
    assert reread.dataset_id is None
    assert reread.raw["formatting"] == {"format": "number", "precision": 4}
    assert chart.data == before


@pytest.mark.parametrize("missing", [False, True], ids=["null", "absent"])
def test_typed_updates_normalize_legacy_slot_dataset_id_on_the_write_copy(missing: bool) -> None:
    response = _line_response()
    entry = cast(dict[str, Any], response["entry"])
    data = entry["data"]
    data["sources"]["datasetsIds"] = ["dataset-1", "dataset-2"]
    visualization = data["visualization"]
    axis = visualization["y"]["items"][0]
    if missing:
        del axis["datasetId"]
    else:
        axis["datasetId"] = None
    axis["formatting"] = {"format": "number", "precision": 2}
    visualization["futureConfig"] = {"items": [{"guid": "opaque-id"}]}
    legacy_filter = {"guid": "date-guid", "filter": {"operation": {"code": "ISNULL"}}, "datasetId": None}
    data["sources"]["filters"] = [legacy_filter]
    chart = WizardChartConverter.to_domain(response, installation="yacloud")
    before = copy.deepcopy(chart.data)
    measure = chart.fields.by_guid("amount-guid")
    assert measure.dataset_id is None

    secondary_measure = replace(_dataset(), id="dataset-2").fields.by_guid(measure.guid)
    update = chart.update.labels([secondary_measure]).measure_format(measure, precision=4)
    payload = WizardChartConverter.from_domain_update(update).to_payload()
    saved = cast(dict[str, Any], payload["data"])

    assert saved["visualization"]["y"]["items"] == [
        {**axis, "datasetId": "", "formatting": {"format": "number", "precision": 4}}
    ]
    assert saved["visualization"]["labels"]["items"][0]["datasetId"] == "dataset-2"
    assert saved["visualization"]["colors"] == visualization["colors"]
    assert saved["visualization"]["futureConfig"] == visualization["futureConfig"]
    assert saved["sources"]["filters"] == [{**legacy_filter, "datasetId": ""}]
    entry["data"] = saved
    assert WizardChartConverter.to_domain(response, installation="yacloud").fields.by_guid(measure.guid).dataset_id == (
        "dataset-2"
    )

    publish = WizardChartConverter.from_domain_publish_revision(chart, rev_id="revision-1").to_payload()
    assert publish["revId"] == "revision-1"
    published = cast(dict[str, Any], publish["data"])
    assert published["visualization"]["y"]["items"] == [{**axis, "datasetId": ""}]
    assert chart.data == before


def test_typed_update_normalizes_legacy_mounted_hierarchy_members() -> None:
    response = _line_response()
    data = cast(dict[str, Any], response["entry"])["data"]
    hierarchy = {
        "guid": "hierarchy-guid",
        "title": "Date and region",
        "data_type": "hierarchy",
        "fields": [{"guid": "date-guid"}, {"guid": "region-guid", "datasetId": None}],
    }
    data["visualization"]["x"]["items"] = [hierarchy]
    declaration = {key: value for key, value in hierarchy.items() if key != "data_type"}
    data["sources"]["hierarchies"] = [declaration]
    chart = WizardChartConverter.to_domain(response, installation="yacloud")
    before = copy.deepcopy(chart.data)

    payload = WizardChartConverter.from_domain_update(chart.update.legend(mode="hide")).to_payload()
    saved = cast(dict[str, Any], payload["data"])

    assert saved["visualization"]["x"]["items"] == [
        {**hierarchy, "fields": [{"guid": "date-guid", "datasetId": ""}, {"guid": "region-guid", "datasetId": ""}]}
    ]
    assert saved["sources"]["hierarchies"] == [
        {**declaration, "fields": [{"guid": "date-guid", "datasetId": ""}, {"guid": "region-guid", "datasetId": ""}]}
    ]
    assert chart.data == before


def test_typed_updates_write_legacy_dataset_id_alias_using_the_wire_key() -> None:
    response = _line_response()
    data = cast(dict[str, Any], response["entry"])["data"]
    axis = data["visualization"]["y"]["items"][0]
    axis["dataset_id"] = axis.pop("datasetId")
    chart = WizardChartConverter.to_domain(response, installation="yacloud")
    before = copy.deepcopy(chart.data)

    payload = WizardChartConverter.from_domain_update(chart.update.legend(mode="hide")).to_payload()
    publish = WizardChartConverter.from_domain_publish_revision(chart, rev_id="revision-1").to_payload()

    expected = {key: value for key, value in axis.items() if key != "dataset_id"}
    expected["datasetId"] = "dataset-1"
    for result in (payload, publish):
        saved = cast(dict[str, Any], result["data"])
        assert saved["visualization"]["y"]["items"] == [expected]
    assert chart.data == before


def test_dataset_parameter_is_emitted_under_document_v1_sources_updates() -> None:
    data = _create_data(_line_builder().dataset(_dataset()).x(["Date"]).y(["Amount"]))

    updates = data["sources"]["updates"]
    parameter_update = next(update for update in updates if update["field"]["guid"] == "threshold-guid")
    assert parameter_update["action"] == "update_field"
    assert parameter_update["field"]["datasetId"] == "dataset-1"


def test_unmatched_line_item_decoration_fails_closed() -> None:
    builder = (
        _line_builder()
        .dataset(_dataset())
        .x(["Date"])
        .y(["Amount"])
        .measure_format("Unused", format="number", precision=2)
    )

    with pytest.raises(DataLensConfigurationError, match="not placed"):
        _create_data(builder)
