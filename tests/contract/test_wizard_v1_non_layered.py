from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._generated.dto import WIZARD_VISUALIZATION_STRUCTURE
from datalens_sdk.converter.wizard.converter import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation


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
        ),
    )


def _configure_xy(builder: Any, x: str, y: str) -> Any:
    return builder.x([x]).y([y])


def _configure_flat_table(builder: Any) -> Any:
    return builder.columns(["Region", "Amount"])


def _configure_pivot_table(builder: Any) -> Any:
    return builder.columns(["Region"]).rows(["Date"]).measures(["Amount"])


_CASE_BUILDERS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "area": ("area", lambda builder: _configure_xy(builder, "Date", "Amount")),
    "area100p": ("area_100p", lambda builder: _configure_xy(builder, "Date", "Amount")),
    "bar": ("bar", lambda builder: _configure_xy(builder, "Amount", "Region")),
    "bar100p": ("bar_100p", lambda builder: _configure_xy(builder, "Amount", "Region")),
    "column": ("column", lambda builder: _configure_xy(builder, "Date", "Amount")),
    "column100p": ("column_100p", lambda builder: _configure_xy(builder, "Date", "Amount")),
    "donut": ("donut", lambda builder: _configure_xy(builder, "Region", "Amount")),
    "flatTable": ("flat_table", _configure_flat_table),
    "funnel": ("funnel", lambda builder: _configure_xy(builder, "Region", "Amount")),
    "line": ("line", lambda builder: _configure_xy(builder, "Date", "Amount")),
    "metric": ("indicator", lambda builder: builder.y(["Amount"])),
    "pie": ("pie", lambda builder: _configure_xy(builder, "Region", "Amount")),
    "pivotTable": ("pivot_table", _configure_pivot_table),
    "scatter": ("scatter", lambda builder: _configure_xy(builder, "Amount", "Count")),
    "treemap": ("treemap", lambda builder: _configure_xy(builder, "Region", "Amount")),
}

_CASE_UPDATES: dict[str, tuple[str, str, str, str]] = {
    "area": ("x", "Region", "x", "region-guid"),
    "area100p": ("x", "Region", "x", "region-guid"),
    "bar": ("y", "Date", "y", "date-guid"),
    "bar100p": ("y", "Date", "y", "date-guid"),
    "column": ("x", "Region", "x", "region-guid"),
    "column100p": ("x", "Region", "x", "region-guid"),
    "donut": ("x", "Date", "dimensions", "date-guid"),
    "flatTable": ("columns", "Date", "columns", "date-guid"),
    "funnel": ("x", "Date", "dimensions", "date-guid"),
    "line": ("y", "Count", "y", "count-guid"),
    "metric": ("y", "Count", "measures", "count-guid"),
    "pie": ("x", "Date", "dimensions", "date-guid"),
    "pivotTable": ("rows", "Region", "rows", "region-guid"),
    "scatter": ("x", "Count", "x", "count-guid"),
    "treemap": ("x", "Date", "dimensions", "date-guid"),
}

_TRANSITIONS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("line", "column", {"x": "date-guid", "y": "amount-guid"}),
    ("column", "line", {"x": "date-guid", "y": "amount-guid"}),
    ("line", "bar", {"x": "amount-guid", "y": "date-guid"}),
    ("bar", "line", {"x": "region-guid", "y": "amount-guid"}),
)


def _builder(visualization_type: str) -> Any:
    factory_method, configure = _CASE_BUILDERS[visualization_type]
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method)(
        name=visualization_type,
        location=EntryLocation.path("/Charts"),
    ).dataset(_dataset())
    return configure(builder)


def _read_response(*, entry_id: str, data: object) -> dict[str, object]:
    return {
        "entry": {
            "createdAt": "2026-01-01T00:00:00.000Z",
            "createdBy": "user-1",
            "data": data,
            "entryId": entry_id,
            "hidden": False,
            "key": f"Users/example/{entry_id}",
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
            "version": 1,
            "workbookId": None,
        },
        "isFavorite": False,
        "permissions": {"admin": True, "edit": True, "execute": True, "read": True},
    }


@pytest.mark.parametrize("visualization_type", sorted(_CASE_BUILDERS))
def test_non_layered_create_uses_named_wizard_v1_slots(visualization_type: str) -> None:
    payload = WizardChartConverter.from_domain_create(_builder(visualization_type).to_spec()).to_payload()

    data = cast(dict[str, Any], payload["data"])
    visualization = data["visualization"]
    structure = WIZARD_VISUALIZATION_STRUCTURE[visualization_type]
    assert visualization["type"] == visualization_type
    assert set(visualization) == {"type", *structure["slots"]}
    assert all(isinstance(visualization[slot]["items"], list) for slot in structure["slots"])
    assert data["sources"]["datasetsIds"] == ["dataset-1"]


@pytest.mark.parametrize("visualization_type", sorted(_CASE_BUILDERS))
def test_non_layered_noop_update_preserves_target_shape(visualization_type: str) -> None:
    create_payload = WizardChartConverter.from_domain_create(_builder(visualization_type).to_spec()).to_payload()
    chart = WizardChartConverter.to_domain(
        _read_response(entry_id=f"{visualization_type}-chart", data=create_payload["data"]),
        installation="yacloud",
    )

    update_payload = WizardChartConverter.from_domain_update(chart.update).to_payload()

    assert update_payload["data"] == create_payload["data"]


@pytest.mark.parametrize("visualization_type", sorted(_CASE_BUILDERS))
def test_non_layered_slot_update_mutates_the_named_slot(visualization_type: str) -> None:
    create_payload = WizardChartConverter.from_domain_create(_builder(visualization_type).to_spec()).to_payload()
    chart = WizardChartConverter.to_domain(
        _read_response(entry_id=f"{visualization_type}-chart", data=create_payload["data"]),
        installation="yacloud",
    )
    method_name, field_name, slot_name, expected_guid = _CASE_UPDATES[visualization_type]
    update = getattr(chart.update, method_name)([_dataset().fields.by_name(field_name)])

    update_payload = WizardChartConverter.from_domain_update(update).to_payload()

    data = cast(dict[str, Any], update_payload["data"])
    assert data["visualization"][slot_name]["items"] == [{"guid": expected_guid, "datasetId": "dataset-1"}]


@pytest.mark.parametrize(("source_type", "target_type", "expected_axes"), _TRANSITIONS)
def test_verified_cartesian_transition_rebuilds_target_named_slots(
    source_type: str,
    target_type: str,
    expected_axes: dict[str, str],
) -> None:
    create_payload = WizardChartConverter.from_domain_create(_builder(source_type).to_spec()).to_payload()
    chart = WizardChartConverter.to_domain(
        _read_response(entry_id=f"{source_type}-chart", data=create_payload["data"]),
        installation="yacloud",
    )

    update_payload = WizardChartConverter.from_domain_update(
        chart.update.change_visualization_to(visualization_id=target_type)
    ).to_payload()

    data = cast(dict[str, Any], update_payload["data"])
    visualization = data["visualization"]
    assert visualization["type"] == target_type
    assert set(visualization) == {"type", *WIZARD_VISUALIZATION_STRUCTURE[target_type]["slots"]}
    for slot_name, expected_guid in expected_axes.items():
        assert visualization[slot_name]["items"] == [{"guid": expected_guid, "datasetId": "dataset-1"}]


def test_area_update_inserts_measure_names_when_a_second_y_measure_is_added() -> None:
    created = WizardChartConverter.from_domain_create(_builder("area").to_spec()).to_payload()
    chart = WizardChartConverter.to_domain(
        _read_response(entry_id="area-chart", data=created["data"]), installation="yacloud"
    )
    dataset = _dataset()

    changed = WizardChartConverter.from_domain_update(
        chart.update.y([dataset.fields.by_name("Amount"), dataset.fields.by_name("Count")])
    ).to_payload()

    visualization = cast(dict[str, Any], changed["data"])["visualization"]
    for axis, guids in (("x", ["date-guid"]), ("y", ["amount-guid", "count-guid"])):
        assert [item["guid"] for item in visualization[axis]["items"]] == guids
    assert visualization["colors"]["items"] == [{"title": "Measure Names", "type": "PSEUDO", "data_type": "string"}]


@pytest.mark.parametrize("remove_field", [False, True], ids=["replace-y", "delete-field"])
def test_area_update_clears_measure_names_when_a_y_measure_is_removed(*, remove_field: bool) -> None:
    payload = WizardChartConverter.from_domain_create(_builder("area").y(["Amount", "Count"]).to_spec()).to_payload()
    data = cast(dict[str, Any], payload["data"])
    colors = data["visualization"]["colors"]
    colors["futureSlotValue"] = True
    colors["settings"].update(
        {
            "coloredByMeasure": True,
            "colorMode": "palette",
            "mountedColors": {"amount-guid": "#112233", "count-guid": "1"},
            "palette": "classic20",
            "polygonBorders": "show",
            "futureSetting": True,
        }
    )
    chart = WizardChartConverter.to_domain(_read_response(entry_id="area-chart", data=data), installation="yacloud")
    update = (
        chart.update.delete_field(chart.fields.by_guid("count-guid"))
        if remove_field
        else chart.update.y([chart.fields.by_guid("amount-guid")])
    )

    changed = WizardChartConverter.from_domain_update(update).to_payload()

    visualization = cast(dict[str, Any], changed["data"])["visualization"]
    assert [item["guid"] for item in visualization["y"]["items"]] == ["amount-guid"]
    assert visualization["colors"] == {"items": [], "settings": {"futureSetting": True}, "futureSlotValue": True}


@pytest.mark.parametrize(
    ("retained_guid", "retained_color"),
    [("amount-guid", "#112233"), ("count-guid", "1")],
)
def test_area_update_preserves_existing_measure_colors_and_adds_defaults_for_new_guids(
    retained_guid: str,
    retained_color: str,
) -> None:
    builder = _builder("area").y(["Amount", "Count"]).color_by_measure_name(colors_map={"Amount": "#112233"})
    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()
    chart = WizardChartConverter.to_domain(
        _read_response(entry_id="area-chart", data=payload["data"]),
        installation="yacloud",
    )
    extra = Dataset(
        id="dataset-1",
        result_schema=(
            {"guid": "extra-guid", "title": "Extra", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
        ),
    ).fields.by_guid("extra-guid")

    changed = WizardChartConverter.from_domain_update(
        chart.update.y([chart.fields.by_guid(retained_guid), extra])
    ).to_payload()

    visualization = cast(dict[str, Any], changed["data"])["visualization"]
    assert [item["guid"] for item in visualization["y"]["items"]] == [retained_guid, "extra-guid"]
    assert visualization["colors"]["settings"]["mountedColors"] == {
        retained_guid: retained_color,
        "extra-guid": "0" if retained_color == "1" else "1",
    }


def test_area_update_preserves_an_explicit_dimension_color_when_y_changes() -> None:
    builder = _builder("area").color_by_dimension("Region").palette(id="classic20")
    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()
    chart = WizardChartConverter.to_domain(
        _read_response(entry_id="area-chart", data=payload["data"]),
        installation="yacloud",
    )
    dataset = _dataset()

    changed = WizardChartConverter.from_domain_update(
        chart.update.y([dataset.fields.by_name("Amount"), dataset.fields.by_name("Count")])
    ).to_payload()

    colors = cast(dict[str, Any], changed["data"])["visualization"]["colors"]
    assert colors["items"] == [{"guid": "region-guid", "datasetId": "dataset-1"}]
    assert colors["settings"]["palette"] == "classic20"


@pytest.mark.parametrize("legacy_empty_colors", [False, True], ids=["saved-measure-names", "legacy-empty"])
def test_area_update_without_y_changes_preserves_saved_colors(*, legacy_empty_colors: bool) -> None:
    builder = _builder("area").y(["Amount", "Count"]).color_by_measure_name(colors_map={"Count": "#112233"})
    payload = WizardChartConverter.from_domain_create(builder.to_spec()).to_payload()
    data = cast(dict[str, Any], payload["data"])
    visualization = data["visualization"]
    if legacy_empty_colors:
        visualization["colors"] = {"items": [], "settings": {"futureSetting": True}}
    chart = WizardChartConverter.to_domain(_read_response(entry_id="area-chart", data=data), installation="yacloud")

    changed = WizardChartConverter.from_domain_update(chart.update.legend(mode="hide")).to_payload()

    assert cast(dict[str, Any], changed["data"])["visualization"]["colors"] == visualization["colors"]
