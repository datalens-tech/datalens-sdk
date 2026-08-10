from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._runtime.viz_specs import VIZ_SPECS
from datalens_sdk._runtime.wizard_visualization_transitions import WIZARD_VISUALIZATION_TRANSITIONS
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError


def _chart(*, visualization_id: str = "line", placeholders: list[dict[str, object]] | None = None) -> WizardChart:
    return WizardChart(
        id="chart-1",
        installation="yacloud",
        data={
            "visualization": {
                "id": visualization_id,
                "placeholders": placeholders or [],
            }
        },
    )


def _payload_data(update: object) -> dict[str, object]:
    dto = WizardChartConverter.from_domain_update(cast(Any, update))
    return cast(dict[str, object], dto.to_payload()["data"])


def test_placeholder_typo_is_rejected_at_the_public_update_call() -> None:
    with pytest.raises(
        DataLensConfigurationError,
        match=r"axis_visibility: placeholder 'typo'.*active visualization 'line'.*Allowed placeholders",
    ):
        _chart().update.axis_visibility("typo", mode="show")


def test_converter_rejects_an_invalid_staged_placeholder_as_defense_in_depth() -> None:
    update = _chart().update
    update._placeholder_edits["typo"] = []

    with pytest.raises(DataLensConfigurationError, match=r"typo.*Allowed placeholders"):
        _payload_data(update)


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
    ("source_visualization_id", "target_visualization_id", "placeholder_mapping"),
    [
        (source, target, transition["placeholder_mapping"])
        for (source, target), transition in WIZARD_VISUALIZATION_TRANSITIONS.items()
    ],
    ids=[f"{source}-to-{target}" for source, target in WIZARD_VISUALIZATION_TRANSITIONS],
)
def test_every_verified_visualization_transition_preserves_declared_axes(
    source_visualization_id: str,
    target_visualization_id: str,
    placeholder_mapping: tuple[tuple[str, str], ...],
) -> None:
    source_items = {
        placeholder_id: [
            {
                "guid": f"g_{placeholder_id}",
                "title": placeholder_id.upper(),
                "type": "DIMENSION" if placeholder_id == "x" else "MEASURE",
            }
        ]
        for placeholder_id, _ in placeholder_mapping
    }
    chart = _chart(
        visualization_id=source_visualization_id,
        placeholders=[{"id": placeholder_id, "items": items} for placeholder_id, items in source_items.items()],
    )

    data = _payload_data(chart.update.change_visualization_to(visualization_id=target_visualization_id))
    visualization = cast(dict[str, object], data["visualization"])
    placeholders = cast(list[dict[str, object]], visualization["placeholders"])
    items_by_id = {cast(str, placeholder["id"]): placeholder["items"] for placeholder in placeholders}
    target_spec = VIZ_SPECS[target_visualization_id]
    target_meta = cast(dict[str, object], target_spec["viz"])
    target_placeholders = cast(dict[str, object], target_spec["placeholders"])
    expected_items = {
        target_placeholder_id: source_items[source_placeholder_id]
        for source_placeholder_id, target_placeholder_id in placeholder_mapping
    }

    assert visualization["id"] == target_visualization_id
    assert visualization["type"] == target_meta["type"]
    assert set(items_by_id) == set(target_placeholders)
    assert items_by_id == {
        placeholder_id: expected_items.get(placeholder_id, []) for placeholder_id in target_placeholders
    }


def test_change_visualization_to_rebuilds_metadata_maps_axes_and_drops_incompatible_state() -> None:
    dimension = {"guid": "g_date", "title": "Date", "type": "DIMENSION", "data_type": "date"}
    measure = {"guid": "g_amount", "title": "Amount", "type": "MEASURE", "data_type": "float"}
    chart = _chart(
        placeholders=[
            {"id": "x", "items": [dimension]},
            {"id": "y", "items": [measure]},
            {"id": "y2", "items": [measure]},
            {"id": "shapes", "items": [dimension]},
        ]
    )
    cast(dict[str, object], chart.data).update(
        {
            "colors": [dimension],
            "extraSettings": {"navigatorSettings": {"navigatorMode": "show"}},
            "labels": [dimension],
            "shapesConfig": {"fieldGuid": "g_date"},
            "tooltips": [measure],
        }
    )

    data = _payload_data(chart.update.change_visualization_to(visualization_id="bar"))
    visualization = cast(dict[str, object], data["visualization"])
    placeholders = cast(list[dict[str, object]], visualization["placeholders"])
    items_by_id = {cast(str, placeholder["id"]): placeholder["items"] for placeholder in placeholders}

    assert visualization["id"] == "bar"
    assert visualization["type"] == "column"
    assert set(items_by_id) == {"x", "y"}
    assert items_by_id["x"] == [measure]
    assert items_by_id["y"] == [dimension]
    for key in ("colors", "extraSettings", "labels", "shapesConfig", "tooltips"):
        assert key not in data
    y_placeholder = next(placeholder for placeholder in placeholders if placeholder["id"] == "y")
    assert cast(dict[str, object], y_placeholder["settings"])["axisModeMap"] == {"g_date": "continuous"}


def test_change_visualization_to_validates_retained_target_placeholder_capacity_before_rpc() -> None:
    chart = _chart(placeholders=[{"id": "x", "items": [{"guid": "a"}, {"guid": "b"}, {"guid": "c"}]}])

    with pytest.raises(DataLensValidationError, match=r"transition to 'bar'.*placeholder 'y'.*capacity is 2"):
        _payload_data(chart.update.change_visualization_to(visualization_id="bar"))


def test_update_method_after_transition_uses_target_applicability() -> None:
    update = _chart().update.change_visualization_to(visualization_id="bar")

    update.axis_scale("x", scale="linear")
    with pytest.raises(DataLensConfigurationError, match=r"shape_by_dimension.*not applicable.*viz 'bar'"):
        update.shape_by_dimension("g_category")
