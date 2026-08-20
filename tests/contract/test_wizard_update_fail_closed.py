from __future__ import annotations

import copy
from typing import Any, cast

import pytest

from datalens_sdk._generated.dto import WIZARD_VISUALIZATION_STRUCTURE
from datalens_sdk._runtime.wizard_semantics import (
    WIZARD_VISUALIZATION_TRANSITIONS,
)
from datalens_sdk._runtime.wizard_structure import WizardSlotStructure, WizardVisualizationRegistry
from datalens_sdk.converter.wizard._update import _validate_update_structure
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError


def _chart(*, visualization_id: str = "line", slots: dict[str, list[dict[str, object]]] | None = None) -> WizardChart:
    structure = WIZARD_VISUALIZATION_STRUCTURE.get(visualization_id)
    named_slots: dict[str, object] = (
        {slot_name: {"items": []} for slot_name in structure["slots"]} if structure is not None else {}
    )
    for slot_name, items in (slots or {}).items():
        named_slots[slot_name] = {"items": items}
    return WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "sources": {"datasetsIds": ["dataset-1"]},
            "visualization": {
                "type": visualization_id,
                **named_slots,
            },
        },
    )


def _payload_data(update: object) -> dict[str, object]:
    dto = WizardChartConverter.from_domain_update(cast(Any, update))
    return cast(dict[str, object], dto.to_payload()["data"])


def _structure(
    visualization_id: str,
    *,
    chart_settings: tuple[str, ...] = (),
    slot_settings: dict[str, tuple[str, ...]] | None = None,
) -> WizardVisualizationRegistry:
    slots: dict[str, WizardSlotStructure] = {
        slot_name: {
            "required": False,
            "items_required": False,
            "settings": {setting_name: {} for setting_name in setting_names},
        }
        for slot_name, setting_names in (slot_settings or {}).items()
    }
    return {
        visualization_id: {
            "properties": ["type", *slots],
            "required": ["type"],
            "slots": slots,
            "chart_settings": {setting_name: {} for setting_name in chart_settings},
            "layers": {},
        }
    }


def test_update_helper_requires_every_declared_chart_setting_before_mutation() -> None:
    chart = _chart()
    original = copy.deepcopy(chart.data)
    update = chart.update.chart_title(text="Title")

    with pytest.raises(DataLensConfigurationError, match=r"chart_title.*not supported by generated structure"):
        _validate_update_structure(
            cast(Any, chart.data),
            update,
            _structure("line", chart_settings=("title",)),
        )

    assert chart.data == original


def test_update_axis_helper_rejects_a_partial_slot_setting_carrier() -> None:
    chart = _chart(slots={"x": []})
    update = chart.update.axis_title("x", mode="auto")

    with pytest.raises(DataLensConfigurationError, match=r"axis_title.*not supported by generated structure"):
        _validate_update_structure(
            cast(Any, chart.data),
            update,
            _structure("line", slot_settings={"x": ("title",)}),
        )


def test_update_labels_position_accepts_either_declared_schema_carrier() -> None:
    for setting_name in ("labelsPosition", "position"):
        chart = _chart(visualization_id="funnel", slots={"labels": []})
        update = chart.update.labels_position(mode="inside")

        _validate_update_structure(
            cast(Any, chart.data),
            update,
            _structure("funnel", slot_settings={"labels": (setting_name,)}),
        )


def test_update_labels_position_rejects_a_missing_schema_carrier() -> None:
    chart = _chart(visualization_id="funnel", slots={"labels": []})
    update = chart.update.labels_position(mode="inside")

    with pytest.raises(DataLensConfigurationError, match=r"labels_position.*not supported by generated structure"):
        _validate_update_structure(
            cast(Any, chart.data),
            update,
            _structure("funnel", slot_settings={"labels": ()}),
        )


def test_slot_typo_is_rejected_at_the_public_update_call() -> None:
    with pytest.raises(
        DataLensConfigurationError,
        match=r"axis_visibility: slot 'typo'.*active visualization 'line'.*Allowed slots",
    ):
        _chart().update.axis_visibility("typo", mode="show")


def test_converter_rejects_an_invalid_staged_slot_as_defense_in_depth() -> None:
    update = _chart().update
    cast(dict[str, list[Any]], update.slot_edits)["typo"] = []

    with pytest.raises(DataLensConfigurationError, match=r"typo.*Allowed slots"):
        _payload_data(update)


def test_pivot_rejects_legacy_y_and_accepts_canonical_measures() -> None:
    chart = _chart(visualization_id="pivotTable")

    with pytest.raises(DataLensConfigurationError, match=r"slot 'y'.*visualization 'pivotTable'"):
        chart.update.y([])

    assert chart.update.measures([]).slot_edits == {"measures": []}


def test_change_visualization_to_rejects_unknown_target_locally() -> None:
    with pytest.raises(
        DataLensConfigurationError,
        match=r"change_visualization_to: target visualization 'not-a-viz'.*Supported visualizations",
    ):
        _chart().update.change_visualization_to(visualization_id="not-a-viz")


def test_change_visualization_to_rejects_unknown_source_and_active_target_locally() -> None:
    with pytest.raises(
        DataLensConfigurationError,
        match=r"active visualization 'not-a-viz' is unknown.*Supported visualizations",
    ):
        _chart(visualization_id="not-a-viz").update.change_visualization_to(visualization_id="line")
    with pytest.raises(
        DataLensConfigurationError,
        match=r"target visualization 'line' is already active",
    ):
        _chart().update.change_visualization_to(visualization_id="line")


def test_change_visualization_to_rejects_unsupported_and_funnel_transitions_locally() -> None:
    with pytest.raises(
        DataLensConfigurationError,
        match=r"transition from active visualization 'line' to 'pie'.*Verified targets",
    ):
        _chart().update.change_visualization_to(visualization_id="pie")
    with pytest.raises(
        DataLensConfigurationError,
        match=r"transition from active visualization 'line' to 'funnel'.*Verified targets",
    ):
        _chart().update.change_visualization_to(visualization_id="funnel")


def test_verified_visualization_transition_matrix_remains_explicit() -> None:
    assert set(WIZARD_VISUALIZATION_TRANSITIONS) == {
        ("line", "column"),
        ("column", "line"),
        ("line", "bar"),
        ("bar", "line"),
    }


@pytest.mark.parametrize(
    ("source_visualization_id", "target_visualization_id", "slot_mapping"),
    [
        (source, target, transition["slot_mapping"])
        for (source, target), transition in WIZARD_VISUALIZATION_TRANSITIONS.items()
    ],
    ids=[f"{source}-to-{target}" for source, target in WIZARD_VISUALIZATION_TRANSITIONS],
)
def test_every_verified_visualization_transition_preserves_declared_axes(
    source_visualization_id: str,
    target_visualization_id: str,
    slot_mapping: tuple[tuple[str, str], ...],
) -> None:
    source_items: dict[str, list[dict[str, object]]] = {
        slot_name: [
            {
                "guid": f"g_{slot_name}",
                "datasetId": "dataset-1",
            }
        ]
        for slot_name, _ in slot_mapping
    }
    chart = _chart(
        visualization_id=source_visualization_id,
        slots=source_items,
    )

    data = _payload_data(chart.update.change_visualization_to(visualization_id=target_visualization_id))
    visualization = cast(dict[str, object], data["visualization"])
    target_slots = WIZARD_VISUALIZATION_STRUCTURE[target_visualization_id]["slots"]
    expected_items = {
        target_slot_name: source_items[source_slot_name] for source_slot_name, target_slot_name in slot_mapping
    }

    assert visualization["type"] == target_visualization_id
    assert set(visualization) == {"type", *target_slots}
    assert {slot_name: cast(dict[str, Any], visualization[slot_name])["items"] for slot_name in target_slots} == {
        slot_name: expected_items.get(slot_name, []) for slot_name in target_slots
    }


def test_change_visualization_to_rebuilds_metadata_maps_axes_and_drops_incompatible_state() -> None:
    dimension: dict[str, object] = {
        "guid": "g_date",
        "datasetId": "dataset-1",
        "title": "Date",
        "type": "DIMENSION",
        "data_type": "date",
    }
    measure: dict[str, object] = {
        "guid": "g_amount",
        "datasetId": "dataset-1",
        "title": "Amount",
        "type": "MEASURE",
        "data_type": "float",
    }
    chart = _chart(slots={"x": [dimension], "y": [measure], "y2": [measure], "shapes": [dimension]})
    source_visualization = cast(dict[str, object], chart.data["visualization"])
    source_visualization["chartSettings"] = {"navigatorSettings": {"navigatorMode": "show"}}
    source_visualization["colors"] = {"items": [dimension]}
    source_visualization["labels"] = {"items": [dimension]}
    source_visualization["shapes"] = {"items": [dimension], "settings": {"fieldGuid": "g_date"}}

    data = _payload_data(chart.update.change_visualization_to(visualization_id="bar"))
    visualization = cast(dict[str, object], data["visualization"])
    untyped_visualization = cast(dict[str, Any], visualization)
    assert visualization["type"] == "bar"
    assert set(visualization) == {"type", *WIZARD_VISUALIZATION_STRUCTURE["bar"]["slots"]}
    assert untyped_visualization["x"]["items"] == [measure]
    assert untyped_visualization["y"]["items"] == [dimension]
    assert untyped_visualization["colors"]["items"] == []
    assert untyped_visualization["labels"]["items"] == []
    assert "chartSettings" not in visualization
    assert cast(dict[str, object], untyped_visualization["y"]["settings"])["axisModeMap"] == {"g_date": "continuous"}


def test_change_visualization_to_validates_retained_target_slot_capacity_before_rpc() -> None:
    chart = _chart(slots={"x": [{"guid": guid, "datasetId": "dataset-1"} for guid in ("a", "b", "c")]})

    with pytest.raises(DataLensValidationError, match=r"transition to 'bar'.*slot 'y'.*capacity is 2"):
        _payload_data(chart.update.change_visualization_to(visualization_id="bar"))


def test_update_method_after_transition_uses_target_applicability() -> None:
    update = _chart().update.change_visualization_to(visualization_id="bar")

    update.axis_scale("x", scale="linear")
    with pytest.raises(DataLensConfigurationError, match=r"shape_by_dimension.*not applicable.*visualization 'bar'"):
        update.shape_by_dimension("g_category")
