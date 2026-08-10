"""Wire-assembly tests for group_control selectors (epic D4, stage 3).

Specs are constructed directly (the builder surface arrives in later stages);
expected wire forms are pinned against real UI payloads from the golden
fixtures (group_control_manual.json member shapes) and probe P016 verdicts.
"""

from __future__ import annotations

import pytest

from datalens_sdk.converter.dashboard import _validate_unique_ids
from datalens_sdk.converter.dashboard_control import (
    _external_control_wire,
    _group_control_data,
    _member_wire,
    encode_selector_default,
)
from datalens_sdk.converter.dashboard_items import _wire_item
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDateInterval
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.specs.dashboard import (
    DashboardCreateSpec,
    DashboardSettingsSpec,
    DatasetSelectorSource,
    ExternalControlItem,
    GroupControlItem,
    LayoutItemSpec,
    ManualSelectorSource,
    SelectorMemberSpec,
    TabSpec,
    WidgetItem,
    WidgetTabSpec,
)
from datalens_sdk.errors import DataLensValidationError

# -- encode_selector_default -------------------------------------------------------


def test_relative_interval_encodes_the_fixture_form() -> None:
    value = RelativeDateInterval("-14d", "-0d")
    assert (
        encode_selector_default(value, field_type="date", operation=None) == "__interval___relative_-14d___relative_-0d"
    )


def test_interval_with_between_operation_gets_generic_prefix() -> None:
    # group_control_manual.json member 7o: __between___interval___relative_-14d___relative_-0d
    value = RelativeDateInterval("-14d", "-0d")
    assert (
        encode_selector_default(value, field_type="date", operation="BETWEEN")
        == "__between___interval___relative_-14d___relative_-0d"
    )


def test_absolute_interval_on_date_field_is_date_only() -> None:
    value = DateInterval("2024-01-01", "2024-03-31")
    assert encode_selector_default(value, field_type="date", operation=None) == "__interval_2024-01-01_2024-03-31"


def test_absolute_interval_on_datetime_field_expands_day_bounds() -> None:
    value = DateInterval("2024-01-01", "2024-03-31")
    assert (
        encode_selector_default(value, field_type="genericdatetime", operation=None)
        == "__interval_2024-01-01T00:00:00.000Z_2024-03-31T23:59:59.999Z"
    )


def test_hybrid_interval_mixes_absolute_and_relative_edges() -> None:
    value = DateInterval("2024-01-01", "-0d")
    assert encode_selector_default(value, field_type="date", operation=None) == "__interval_2024-01-01___relative_-0d"


def test_list_default_prefixes_every_entry() -> None:
    # group_control_manual.json member om: ['__eq_Value 5']
    assert encode_selector_default(("Value 5",), field_type="", operation="EQ") == ["__eq_Value 5"]


def test_plain_default_without_operation_stays_raw() -> None:
    assert encode_selector_default(("Furniture",), field_type="string", operation=None) == ["Furniture"]


def test_string_default_with_operation() -> None:
    assert encode_selector_default("Value 1", field_type="", operation="EQ") == "__eq_Value 1"


def test_bool_default_serializes_lowercase() -> None:
    assert encode_selector_default(True, field_type="", operation=None) == "true"
    assert encode_selector_default(False, field_type="", operation="EQ") == "__eq_false"


# -- member wire -------------------------------------------------------------------


def _dataset_member(**overrides: object) -> SelectorMemberSpec:
    defaults: dict[str, object] = {
        "id": "el_1",
        "title": "Категория",
        "source": DatasetSelectorSource(dataset_id="ds-1", field_guid="category_g71a", field_type="string"),
    }
    defaults.update(overrides)
    return SelectorMemberSpec(**defaults)  # type: ignore[arg-type]


def test_manual_select_member_matches_fixture_shape() -> None:
    member = SelectorMemberSpec(
        id="om",
        title="Title 10",
        source=ManualSelectorSource(
            param_name="field_0004",
            element="select",
            options=(("Title 6", "Title 6"), ("Value 5", "Value 5")),
            operation="EQ",
            required=True,
        ),
        default_value=("Value 5",),
        inner_title="=",
    )
    wire = _member_wire(member)
    assert wire["id"] == "om"
    assert wire["sourceType"] == "manual"
    assert wire["namespace"] == "default"
    assert wire["placementMode"] == "auto"
    assert wire["width"] == ""
    assert wire["defaults"] == {"field_0004": ["__eq_Value 5"]}
    source = wire["source"]
    assert isinstance(source, dict)
    assert source["fieldName"] == "field_0004"
    assert source["elementType"] == "select"
    assert source["multiselectable"] is False
    assert source["operation"] == "EQ"
    assert source["required"] is True
    assert source["innerTitle"] == "="
    assert source["defaultValue"] == ["Value 5"]
    assert source["acceptableValues"] == [
        {"title": "Title 6", "value": "Title 6"},
        {"title": "Value 5", "value": "Value 5"},
    ]


def test_manual_date_member_matches_fixture_shape() -> None:
    member = SelectorMemberSpec(
        id="7o",
        title="Title 4",
        source=ManualSelectorSource(param_name="field_0003", element="date", is_range=True, operation="BETWEEN"),
        default_value=RelativeDateInterval("-14d", "-0d"),
    )
    wire = _member_wire(member)
    assert wire["defaults"] == {"field_0003": "__between___interval___relative_-14d___relative_-0d"}
    source = wire["source"]
    assert isinstance(source, dict)
    assert source["isRange"] is True
    assert source["defaultValue"] == "__interval___relative_-14d___relative_-0d"
    assert "multiselectable" not in source
    assert "acceptableValues" not in source


def test_dataset_member_carries_dataset_wiring() -> None:
    wire = _member_wire(_dataset_member())
    source = wire["source"]
    assert isinstance(source, dict)
    assert source["datasetId"] == "ds-1"
    assert source["datasetFieldId"] == "category_g71a"
    assert source["datasetFieldType"] == "DIMENSION"
    assert source["fieldType"] == "string"
    assert "defaultValue" not in source


def test_dataset_select_without_default_gets_empty_list_defaults() -> None:
    # selectors_dataset.json / group_control_dataset.json: defaults {guid: []}
    wire = _member_wire(_dataset_member())
    assert wire["defaults"] == {"category_g71a": []}


def test_member_hint_toggles_show_hint() -> None:
    with_hint = _member_wire(_dataset_member(hint="подсказка"))
    without_hint = _member_wire(_dataset_member())
    with_source, without_source = with_hint["source"], without_hint["source"]
    assert isinstance(with_source, dict)
    assert isinstance(without_source, dict)
    assert with_source["showHint"] is True
    assert with_source["hint"] == "подсказка"
    assert without_source["showHint"] is False
    assert "hint" not in without_source


def test_external_control_wire_matches_probe_form() -> None:
    # P017: standalone control, item-level defaults, no showTitle in source
    item = ExternalControlItem(id="c1", title="Внешний", chart_id="ch-1")
    wire = _external_control_wire(item, namespace="default")
    assert wire == {
        "id": "c1",
        "type": "control",
        "namespace": "default",
        "defaults": {},
        "data": {"title": "Внешний", "sourceType": "external", "source": {"chartId": "ch-1"}},
    }


# -- group_control data ------------------------------------------------------------


def test_group_control_data_emits_required_booleans() -> None:
    group = GroupControlItem(id="g1", members=(_dataset_member(),))
    data = _group_control_data(group)
    assert data["buttonApply"] is False
    assert data["buttonReset"] is False
    assert data["updateControlsOnChange"] is True
    assert data["showGroupName"] is False
    assert data["autoHeight"] is False
    assert "borderRadius" not in data
    group_wire = data["group"]
    assert isinstance(group_wire, list)
    assert len(group_wire) == 1


def test_group_control_data_emits_border_radius_when_set() -> None:
    group = GroupControlItem(id="g1", members=(_dataset_member(),), border_radius=10)
    assert _group_control_data(group)["borderRadius"] == 10


def test_wire_item_dispatches_group_control() -> None:
    group = GroupControlItem(id="g1", members=(_dataset_member(),))
    tab = TabSpec(id="t1", title="Tab", items=(group,), layout=(LayoutItemSpec("g1", 0, 0, 12, 2),))
    wire = _wire_item(tab, group)
    assert wire["type"] == "group_control"
    assert wire["id"] == "g1"
    assert wire["namespace"] == "default"


# -- uniqueness across wrapper/member ids ------------------------------------------


def _create_spec(*tabs: TabSpec) -> DashboardCreateSpec:
    return DashboardCreateSpec(
        installation="yacloud",
        name="Dash",
        location=EntryLocation.path("/Users/me"),
        tabs=tabs,
        description=None,
        access_description=None,
        support_description=None,
        settings=DashboardSettingsSpec(),
        meta=None,
        generated_id_count=0,
    )


def test_member_id_colliding_with_item_id_is_rejected() -> None:
    widget = WidgetItem(
        id="el_1",
        tabs=(WidgetTabSpec(id="wt_1", chart_id="ch-1", title="A", is_default=True, params={}),),
    )
    group = GroupControlItem(id="g1", members=(_dataset_member(),))  # member id el_1
    tab = TabSpec(
        id="t1",
        title="Tab",
        items=(widget, group),
        layout=(LayoutItemSpec("el_1", 0, 0, 12, 2), LayoutItemSpec("g1", 12, 0, 12, 2)),
    )
    with pytest.raises(DataLensValidationError, match="Duplicate item id 'el_1'"):
        _validate_unique_ids(_create_spec(tab))
