"""Behavioral tests for the DashboardTab entity (epic D2).

The tab is a standalone accumulator (the dataset.source pattern): everything
checkable without document context is validated eagerly here; attach-time
behavior (id assignment, cross-tab uniqueness, installation) is covered in
its own section below.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from typing import cast

import pytest

from datalens_sdk import DashboardChartTab, DashboardCreate, DashboardTab, Dataset, EntryLocation, ThemedColor
from datalens_sdk.converter.dashboard import DashboardConverter
from datalens_sdk.domain.dashboard_types import PARENT_FIX_GCONT
from datalens_sdk.domain.specs.dashboard import (
    DashboardItemSpec,
    DatasetSelectorSource,
    ExternalControlItem,
    GroupControlItem,
    ImageItem,
    LayoutItemSpec,
    TabSpec,
    TextItem,
    TitleItem,
    WidgetItem,
)
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DatalensValidationError

_AT = (0, 0, 12, 6)


def _builder(*, name: str = "Dash") -> DashboardCreate:
    return DashboardCreate(
        installation="yacloud",
        name=name,
        location=EntryLocation.path("/Users/me"),
    )


def _chart(*, id: str | None = "ch-1", name: str | None = "Sales", installation: str = "yacloud") -> WizardChart:
    return WizardChart(id=id, installation=installation, name=name)


def _attached_tab(tab: DashboardTab) -> tuple[DashboardItemSpec, ...]:
    return _builder().add_tab(tab).to_spec().tabs[0].items


def test_failed_auto_adder_does_not_advance_the_cursor() -> None:
    # a rejected add must leave the auto-cursor untouched: the next valid item
    # flows into the slot the failed one would have taken, not past it
    tab = DashboardTab("T").add_text("first", item_id="dup")  # auto -> (0, 0, 12, 6)
    with pytest.raises(DatalensValidationError, match="Duplicate item id"):
        tab.add_text("again", item_id="dup")  # rejected AFTER the cursor would have moved
    tab.add_text("second", item_id="ok")  # auto -> should be (12, 0), not (24, 0)
    layout = {entry.i: entry for entry in _builder().add_tab(tab).to_spec().tabs[0].layout}
    entry_ok = layout["ok"]
    assert isinstance(entry_ok, LayoutItemSpec)  # create path resolves autos eagerly
    assert (entry_ok.x, entry_ok.y) == (12, 0)


def test_at_accepts_a_list_of_four() -> None:
    # pre-D5 behavior: at= took any 4-element sequence, not just a tuple
    tab = DashboardTab("T").add_text("x", item_id="x", at=[0, 6, 12, 6])  # type: ignore[arg-type]
    layout = {entry.i: entry for entry in _builder().add_tab(tab).to_spec().tabs[0].layout}
    entry = layout["x"]
    assert isinstance(entry, LayoutItemSpec)
    assert (entry.x, entry.y, entry.w, entry.h) == (0, 6, 12, 6)


# -- construction -----------------------------------------------------------------


def test_tab_rejects_empty_title_and_empty_tab_id() -> None:
    with pytest.raises(DatalensValidationError, match="Tab title"):
        DashboardTab("")
    with pytest.raises(DatalensValidationError, match="tab id"):
        DashboardTab("Tabbed", tab_id="")


def test_item_methods_chain_on_the_same_instance() -> None:
    tab = DashboardTab("One")

    result = tab.add_text("a", at=_AT).add_title("b", at=(0, 6, 12, 2))

    assert result is tab


# -- eager validation ---------------------------------------------------------------


def test_add_chart_with_string_id_requires_non_empty_title() -> None:
    tab = DashboardTab("One")

    with pytest.raises(DatalensValidationError, match="title is required"):
        tab.add_chart("ch-raw", at=_AT)
    with pytest.raises(DatalensValidationError, match="title is required"):
        tab.add_chart("ch-raw", title="", at=_AT)

    tab.add_chart("ch-raw", title="Raw chart", at=_AT)
    item = _attached_tab(tab)[0]
    assert isinstance(item, WidgetItem)
    assert item.tabs[0].chart_id == "ch-raw"
    assert item.tabs[0].title == "Raw chart"


def test_add_chart_rejects_domain_chart_without_id_or_title() -> None:
    with pytest.raises(DatalensValidationError, match="without an id"):
        DashboardTab("One").add_chart(_chart(id=None), at=_AT)
    with pytest.raises(DatalensValidationError, match="has no name"):
        DashboardTab("One").add_chart(_chart(name=None), at=_AT)


def test_add_chart_takes_title_from_domain_chart() -> None:
    item = _attached_tab(DashboardTab("One").add_chart(_chart(), at=_AT, description="Weekly"))[0]

    assert isinstance(item, WidgetItem)
    assert item.tabs[0].title == "Sales"
    assert item.tabs[0].is_default is True
    assert item.tabs[0].description == "Weekly"


def test_chart_params_normalization_keeps_strings_whole() -> None:
    item = _attached_tab(
        DashboardTab("One").add_chart(_chart(), at=_AT, params={"region": "RU", "cities": ["msk", "spb"]})
    )[0]

    assert isinstance(item, WidgetItem)
    assert item.tabs[0].params == {"region": ("RU",), "cities": ("msk", "spb")}


def test_chart_params_reject_non_string_values() -> None:
    with pytest.raises(DatalensValidationError, match="param 'limit'"):
        DashboardTab("One").add_chart(_chart(), at=_AT, params={"limit": 10})  # type: ignore[dict-item]


def test_add_chart_group_default_policy() -> None:
    with pytest.raises(DatalensValidationError, match="at least one chart"):
        DashboardTab("One").add_chart_group([], at=_AT)
    with pytest.raises(DatalensValidationError, match="exactly one chart marked"):
        DashboardTab("One").add_chart_group(
            [
                DashboardChartTab(chart="ch-1", title="A", default=True),
                DashboardChartTab(chart="ch-2", title="B", default=True),
            ],
            at=_AT,
        )

    unmarked = _attached_tab(
        DashboardTab("One").add_chart_group(
            [DashboardChartTab(chart="ch-1", title="A"), DashboardChartTab(chart="ch-2", title="B")],
            at=_AT,
        )
    )[0]
    assert isinstance(unmarked, WidgetItem)
    assert [wt.is_default for wt in unmarked.tabs] == [True, False]

    marked = _attached_tab(
        DashboardTab("Two").add_chart_group(
            [
                DashboardChartTab(chart="ch-1", title="A"),
                DashboardChartTab(chart="ch-2", title="B", default=True),
            ],
            at=_AT,
        )
    )[0]
    assert isinstance(marked, WidgetItem)
    assert [wt.is_default for wt in marked.tabs] == [False, True]


def test_add_chart_group_member_uses_the_shared_chart_resolver() -> None:
    with pytest.raises(DatalensValidationError, match="title is required"):
        DashboardTab("One").add_chart_group([DashboardChartTab(chart="ch-1")], at=_AT)


@pytest.mark.parametrize(
    "bad_call",
    [
        lambda tab: tab.add_chart("ch-1", title="T", at=_AT, hint=""),
        lambda tab: tab.add_chart("ch-1", title="T", at=_AT, description=""),
        lambda tab: tab.add_title("x", at=_AT, hint=""),
        lambda tab: tab.add_chart_group([DashboardChartTab(chart="ch-1", title="T", hint="")], at=_AT),
        lambda tab: tab.add_chart_group([DashboardChartTab(chart="ch-1", title="T", description="")], at=_AT),
    ],
)
def test_empty_hint_and_description_are_rejected(bad_call: Callable[[DashboardTab], object]) -> None:
    with pytest.raises(DatalensValidationError, match="must not be an empty string"):
        bad_call(DashboardTab("One"))


def test_add_title_rejects_empty_text_and_unknown_size() -> None:
    with pytest.raises(DatalensValidationError, match="Title text"):
        DashboardTab("One").add_title("", at=_AT)
    with pytest.raises(DatalensValidationError, match="Unknown title size"):
        DashboardTab("One").add_title("x", at=_AT, size="xxl")  # type: ignore[arg-type]


def test_add_text_and_image_reject_empty_payloads() -> None:
    with pytest.raises(DatalensValidationError, match="Text must not be"):
        DashboardTab("One").add_text("", at=_AT)
    with pytest.raises(DatalensValidationError, match="Image src"):
        DashboardTab("One").add_image(src="", at=_AT)


def test_malformed_at_is_rejected() -> None:
    with pytest.raises(DatalensValidationError, match="at must be"):
        DashboardTab("One").add_text("hello", at=(0, 0, 12))  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "#12345Z", "#fff", "#12345678aa"])
def test_color_validation_rejects_bad_values(bad: str) -> None:
    with pytest.raises(DatalensValidationError):
        DashboardTab("One").add_title("x", at=_AT, text_color=bad)
    with pytest.raises(DatalensValidationError):
        ThemedColor(light=bad, dark="#ffffff")


@pytest.mark.parametrize("good", ["#027bfeb3", "#ffffff", "garbage", "base-brand"])
def test_color_validation_accepts_hex_and_opaque_tokens(good: str) -> None:
    item = _attached_tab(
        DashboardTab("One").add_title("x", at=_AT, text_color=good, background=ThemedColor(light=good, dark=good))
    )[0]

    assert isinstance(item, TitleItem)
    assert item.text_color == good


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (7, "step 2"),
        (26, "step 2"),
        (-2, "step 2"),
        (True, "must be an int"),
        (8.0, "must be an int"),
    ],
)
def test_border_radius_validation(value: object, match: str) -> None:
    with pytest.raises(DatalensValidationError, match=match):
        DashboardTab("One").add_text("x", at=_AT, border_radius=value)  # type: ignore[arg-type]


def test_duplicate_explicit_item_id_is_rejected_at_call_site() -> None:
    tab = DashboardTab("One").add_text("a", item_id="shared", at=_AT)

    with pytest.raises(DatalensValidationError, match="Duplicate item id 'shared'"):
        tab.add_text("b", item_id="shared", at=(0, 6, 12, 6))
    with pytest.raises(DatalensValidationError, match="item id must not be an empty string"):
        tab.add_text("b", item_id="", at=(0, 6, 12, 6))


def test_failed_add_leaves_tab_pending_unchanged() -> None:
    tab = DashboardTab("One").add_text("a", at=_AT)

    bad_calls: tuple[Callable[[], object], ...] = (
        lambda: tab.add_text("b", at=(0, 0, 12)),  # type: ignore[arg-type]
        lambda: tab.add_text("b", at=_AT, border_radius=7),
        lambda: tab.add_title("b", at=_AT, text_color="#12345Z"),
        lambda: tab.add_chart("ch-1", at=_AT),
    )
    for bad_call in bad_calls:
        with pytest.raises(DatalensValidationError):
            bad_call()

    items = _attached_tab(tab)
    assert len(items) == 1
    assert items[0].id == "el_1"


# -- spec shapes ------------------------------------------------------------------


def test_item_spec_shapes_survive_attach() -> None:
    tab = (
        DashboardTab("One")
        .add_title(
            "Header",
            at=_AT,
            size="xl",
            show_in_toc=True,
            hint="Hover",
            auto_height=False,
            border_radius=8,
        )
        .add_text("**md**", at=(0, 6, 12, 6), background="#FFF3B0", auto_height=False)
        .add_image(src="https://img.test/logo.png", alt="Logo", preserve_aspect_ratio=False, at=(0, 12, 12, 6))
    )

    title, text, image = _attached_tab(tab)
    assert title == TitleItem(
        id="el_1",
        text="Header",
        size="xl",
        show_in_toc=True,
        hint="Hover",
        auto_height=False,
        border_radius=8,
    )
    assert text == TextItem(id="el_2", text="**md**", auto_height=False, background="#FFF3B0")
    assert image == ImageItem(id="el_3", src="https://img.test/logo.png", alt="Logo", preserve_aspect_ratio=False)


def test_text_item_has_no_text_color_or_hint_fields() -> None:
    field_names = {field.name for field in dataclasses.fields(TextItem)}

    assert "text_color" not in field_names
    assert "hint" not in field_names


def test_section_divider_is_sugar_over_title() -> None:
    divider_items = _attached_tab(
        DashboardTab("One").add_section_divider("Block", item_id="el_x", at=_AT, background="#FFF3B0", pinned=True)
    )
    title_items = _attached_tab(
        DashboardTab("One").add_title(
            "Block", item_id="el_x", at=_AT, size="l", show_in_toc=True, background="#FFF3B0", pinned=True
        )
    )

    assert divider_items == title_items


def test_pinned_flows_into_layout_parent() -> None:
    spec = (
        _builder().add_tab(DashboardTab("One").add_image(src="https://img.test/x.png", at=_AT, pinned=True)).to_spec()
    )

    assert spec.tabs[0].layout[0].parent == PARENT_FIX_GCONT


def test_spec_params_snapshot_is_immutable() -> None:
    builder = _builder().add_tab(DashboardTab("One").add_chart("ch-1", title="T", at=_AT, params={"a": "x"}))
    spec = builder.to_spec()

    item = spec.tabs[0].items[0]
    assert isinstance(item, WidgetItem)
    with pytest.raises(TypeError):
        item.tabs[0].params["a"] = ("mutated",)  # type: ignore[index]

    second = builder.to_spec().tabs[0].items[0]
    assert isinstance(second, WidgetItem)
    assert second.tabs[0].params == {"a": ("x",)}


# -- add_selector (epic D4, stage 5) ------------------------------------------------


def _dataset(**overrides: object) -> Dataset:
    defaults: dict[str, object] = {
        "id": "ds-1",
        "installation": "yacloud",
        "result_schema": (
            {"guid": "category_g71a", "title": "category", "data_type": "string", "type": "DIMENSION"},
            {"guid": "order_date_x1", "title": "order date", "data_type": "genericdatetime", "type": "DIMENSION"},
        ),
    }
    defaults.update(overrides)
    return Dataset(**defaults)  # type: ignore[arg-type]


def test_add_selector_rejects_measure_fields() -> None:
    # a measure has no value dictionary: the UI renders an empty list, so the
    # SDK fails loud instead of shipping a dead selector
    ds = _dataset(result_schema=({"guid": "sales_g1", "title": "sales", "data_type": "integer", "type": "MEASURE"},))
    with pytest.raises(DatalensValidationError, match="MEASURE"):
        DashboardTab("T").add_selector(dataset=ds, field="sales", at=_AT)


def test_add_selector_singleton_is_a_single_member_group_control() -> None:
    tab = DashboardTab("T").add_selector(dataset=_dataset(), field="category", at=_AT, default_value="Furniture")
    items = _attached_tab(tab)
    assert len(items) == 1
    group = items[0]
    assert isinstance(group, GroupControlItem)
    assert group.id == "el_1"  # wrapper id is auto-assigned
    assert len(group.members) == 1
    member = group.members[0]
    assert member.id == "el_2"  # member id from the same namespace
    assert member.title == "category"
    assert member.default_value == ("Furniture",)
    source = member.source
    assert isinstance(source, DatasetSelectorSource)
    assert source.dataset_id == "ds-1"
    assert source.field_guid == "category_g71a"
    assert source.field_type == "string"
    assert source.operation is None  # not emitted unless the user sets it (P016)


def test_add_selector_explicit_item_id_names_the_member() -> None:
    tab = DashboardTab("T").add_selector(item_id="sel_cat", dataset=_dataset(), field="category_g71a", at=_AT)
    group = _attached_tab(tab)[0]
    assert isinstance(group, GroupControlItem)
    assert group.members[0].id == "sel_cat"
    assert group.id == "el_1"


def test_add_selector_resolves_field_by_guid_and_title_with_suggestions() -> None:
    by_guid = DashboardTab("T").add_selector(dataset=_dataset(), field="order_date_x1", at=_AT, element="date")
    group = _attached_tab(by_guid)[0]
    assert isinstance(group, GroupControlItem)
    source = group.members[0].source
    assert isinstance(source, DatasetSelectorSource)
    # datetime data types pass through: interval encoding must keep the time
    # part for them (only fieldType == "date" gets date-only edges)
    assert source.field_type == "genericdatetime"

    with pytest.raises(DatalensValidationError, match="Did you mean: category"):
        DashboardTab("T").add_selector(dataset=_dataset(), field="catgory", at=_AT)


def test_add_selector_manual_derives_title_from_param_name() -> None:
    tab = DashboardTab("T").add_selector(param_name="date_interval", element="input", at=_AT)
    group = _attached_tab(tab)[0]
    assert isinstance(group, GroupControlItem)
    assert group.members[0].title == "Date Interval"


def test_add_selector_manual_select_requires_options() -> None:
    with pytest.raises(DatalensValidationError, match="options are required"):
        DashboardTab("T").add_selector(param_name="region", element="select", at=_AT)


def test_add_selector_source_xor_is_enforced() -> None:
    with pytest.raises(DatalensValidationError, match="exactly one selector source"):
        DashboardTab("T").add_selector(at=_AT)
    with pytest.raises(DatalensValidationError, match="exactly one selector source"):
        DashboardTab("T").add_selector(dataset=_dataset(), field="category", param_name="region", at=_AT)
    with pytest.raises(DatalensValidationError, match="both dataset= and field="):
        DashboardTab("T").add_selector(dataset=_dataset(), at=_AT)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"param_name": "flag", "element": "checkbox"}, "requires a bool default_value"),
        ({"param_name": "p", "element": "input", "is_range": True}, "is_range applies"),
        ({"param_name": "p", "element": "input", "multiselect": True}, "multiselect applies"),
        ({"param_name": "p", "element": "input", "options": ["a"]}, "options apply"),
        ({"param_name": "p", "element": "input", "operation": "NEQ"}, "Unknown selector operation"),
        ({"param_name": "p", "element": "input", "title": ""}, "must not be an empty string"),
        ({"param_name": "p", "element": "input", "at": _AT, "show_on_tabs": "everywhere"}, "show_on_tabs must be"),
        ({"param_name": "p", "element": "input", "at": _AT, "show_on_tabs": []}, "must not be empty"),
        (
            {"dataset": None, "field": None, "param_name": "p", "element": "date", "at": _AT, "default_value": ("x",)},
            "sequence default_value",
        ),
    ],
)
def test_add_selector_fail_loud_matrix(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(DatalensValidationError, match=match):
        DashboardTab("T").add_selector(**kwargs)  # type: ignore[arg-type]


def test_add_selector_failed_call_leaves_tab_unchanged() -> None:
    tab = DashboardTab("T")
    with pytest.raises(DatalensValidationError):
        tab.add_selector(item_id="sel_1", param_name="p", element="select", at=_AT)  # no options
    assert tab._pending_snapshot() == ()
    # the failed call must not have burned the explicit id
    tab.add_selector(item_id="sel_1", param_name="p", element="input", at=_AT)
    assert len(tab._pending_snapshot()) == 1


def test_add_selector_duplicate_member_id_fails_early() -> None:
    tab = DashboardTab("T").add_selector(item_id="sel_1", param_name="p", element="input", at=_AT)
    with pytest.raises(DatalensValidationError, match="Duplicate item id"):
        tab.add_selector(item_id="sel_1", param_name="q", element="input", at=_AT)


def test_add_selector_group_registration_defers_and_requires_assembly() -> None:
    tab = DashboardTab("T").add_selector(param_name="p", element="input", group="filters")
    assert tab._pending_snapshot() == ()  # nothing attached yet
    with pytest.raises(DatalensValidationError, match="never assembled"):
        _attached_tab(tab)


def test_add_selector_group_rejects_at_and_auto_height() -> None:
    with pytest.raises(DatalensValidationError, match="at=/size= belong to add_group_selector"):
        DashboardTab("T").add_selector(param_name="p", element="input", group="g", at=_AT)
    with pytest.raises(DatalensValidationError, match="auto_height belongs to add_group_selector"):
        DashboardTab("T").add_selector(param_name="p", element="input", group="g", auto_height=True)


def test_add_selector_checkbox_takes_bool_default() -> None:
    tab = DashboardTab("T").add_selector(param_name="only_active", element="checkbox", default_value=True, at=_AT)
    group = _attached_tab(tab)[0]
    assert isinstance(group, GroupControlItem)
    assert group.members[0].default_value is True


def test_add_selector_end_to_end_wire_document() -> None:
    builder = _builder().add_tab(
        DashboardTab("T").add_selector(
            item_id="sel_cat",
            dataset=_dataset(),
            field="category",
            at=(0, 0, 12, 2),
            default_value=["Furniture"],
            operation="IN",
        )
    )
    payload = DashboardConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = cast("dict[str, object]", payload["entry"])
    data = cast("dict[str, object]", entry["data"])
    tabs = cast("list[dict[str, object]]", data["tabs"])
    items = cast("list[dict[str, object]]", tabs[0]["items"])
    assert len(items) == 1
    wire = items[0]
    assert wire["type"] == "group_control"
    wire_data = cast("dict[str, object]", wire["data"])
    members = cast("list[dict[str, object]]", wire_data["group"])
    assert members[0]["id"] == "sel_cat"
    assert members[0]["defaults"] == {"category_g71a": ["__in_Furniture"]}
    layout = cast("list[dict[str, object]]", tabs[0]["layout"])
    assert [entry["i"] for entry in layout] == [wire["id"]]


# -- add_selector(chart=) — external selectors (epic D4, stage 7) -------------------


def test_add_selector_external_is_a_standalone_control_item() -> None:
    tab = DashboardTab("T").add_selector(chart=_chart(id="ch-ext", name="Regions"), at=_AT)
    items = _attached_tab(tab)
    assert len(items) == 1
    control = items[0]
    assert isinstance(control, ExternalControlItem)
    assert control.id == "el_1"  # the item id IS the selector identity
    assert control.title == "Regions"
    assert control.chart_id == "ch-ext"


def test_add_selector_external_explicit_item_id_names_the_item() -> None:
    tab = DashboardTab("T").add_selector(item_id="ext_1", chart="ch-ext", title="Regions", at=_AT)
    control = _attached_tab(tab)[0]
    assert isinstance(control, ExternalControlItem)
    assert control.id == "ext_1"


def test_add_selector_external_requires_title_for_str_chart() -> None:
    with pytest.raises(DatalensValidationError, match="title is required"):
        DashboardTab("T").add_selector(chart="ch-ext", at=_AT)


def test_add_selector_external_rejects_selector_only_params() -> None:
    with pytest.raises(DatalensValidationError, match="does not combine with: element, options"):
        DashboardTab("T").add_selector(chart="ch-ext", title="X", at=_AT, element="select", options=["a"])
    with pytest.raises(DatalensValidationError, match="does not combine with: group"):
        DashboardTab("T").add_selector(chart="ch-ext", title="X", at=_AT, group="filters")
    with pytest.raises(DatalensValidationError, match="does not combine with: dataset"):
        DashboardTab("T").add_selector(chart="ch-ext", title="X", at=_AT, dataset=_dataset())


def test_add_selector_external_checks_installation_at_attach() -> None:
    tab = DashboardTab("T").add_selector(chart=_chart(id="ch-ext", installation="yateam"), at=_AT)
    with pytest.raises(DatalensValidationError, match="Cannot place a 'yateam' chart"):
        _attached_tab(tab)


def test_add_selector_external_end_to_end_wire_document() -> None:
    builder = _builder().add_tab(
        DashboardTab("T").add_selector(item_id="ext_1", chart="ch-ext", title="Regions", at=(0, 0, 8, 2))
    )
    payload = DashboardConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = cast("dict[str, object]", payload["entry"])
    data = cast("dict[str, object]", entry["data"])
    tabs = cast("list[dict[str, object]]", data["tabs"])
    items = cast("list[dict[str, object]]", tabs[0]["items"])
    assert items[0] == {
        "id": "ext_1",
        "type": "control",
        "namespace": "default",
        "defaults": {},
        "data": {"title": "Regions", "sourceType": "external", "source": {"chartId": "ch-ext"}},
    }


# -- enable_action_params (epic D4, stage 8) ----------------------------------------


def test_add_chart_enable_action_params_reaches_the_wire_tab() -> None:
    tab = DashboardTab("T").add_chart(_chart(), at=_AT, enable_action_params=True)
    item = _attached_tab(tab)[0]
    assert isinstance(item, WidgetItem)
    assert item.tabs[0].enable_action_params is True

    plain = _attached_tab(DashboardTab("T").add_chart(_chart(), at=_AT))[0]
    assert isinstance(plain, WidgetItem)
    assert plain.tabs[0].enable_action_params is False


def test_add_chart_group_enable_action_params_is_per_chart_tab() -> None:
    tab = DashboardTab("T").add_chart_group(
        [
            DashboardChartTab(chart="ch-1", title="A", enable_action_params=True),
            DashboardChartTab(chart="ch-2", title="B"),
        ],
        at=_AT,
    )
    item = _attached_tab(tab)[0]
    assert isinstance(item, WidgetItem)
    assert [wt.enable_action_params for wt in item.tabs] == [True, False]


def test_enable_action_params_wire_emission_only_when_true() -> None:
    builder = _builder().add_tab(
        DashboardTab("T")
        .add_chart(_chart(id="ch-on"), at=(0, 0, 12, 6), enable_action_params=True)
        .add_chart(_chart(id="ch-off"), at=(12, 0, 12, 6))
    )
    payload = DashboardConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = cast("dict[str, object]", payload["entry"])
    data = cast("dict[str, object]", entry["data"])
    tabs = cast("list[dict[str, object]]", data["tabs"])
    items = cast("list[dict[str, object]]", tabs[0]["items"])
    on_tab = cast("list[dict[str, object]]", cast("dict[str, object]", items[0]["data"])["tabs"])[0]
    off_tab = cast("list[dict[str, object]]", cast("dict[str, object]", items[1]["data"])["tabs"])[0]
    assert on_tab["enableActionParams"] is True
    assert "enableActionParams" not in off_tab


# -- add_group_selector (epic D4, stage 10) -----------------------------------------


def test_add_group_selector_assembles_registered_members_in_order() -> None:
    tab = (
        DashboardTab("T")
        .add_selector(item_id="sel_a", param_name="alpha", element="input", group="filters")
        .add_selector(item_id="sel_b", param_name="beta", element="input", group="filters")
        .add_group_selector(group="filters", item_id="grp_1", at=_AT, apply_button=True)
    )
    items = _attached_tab(tab)
    assert len(items) == 1
    grp = items[0]
    assert isinstance(grp, GroupControlItem)
    assert grp.id == "grp_1"
    assert [m.id for m in grp.members] == ["sel_a", "sel_b"]
    assert grp.apply_button is True
    assert grp.reset_button is False


def test_add_group_selector_unknown_or_empty_group_fails_loud() -> None:
    tab = DashboardTab("T").add_selector(param_name="alpha", element="input", group="filters")
    with pytest.raises(DatalensValidationError, match=r"no registered members.*Known groups: filters"):
        tab.add_group_selector(group="other", at=_AT)
    with pytest.raises(DatalensValidationError, match="must not be an empty string"):
        tab.add_group_selector(group="", at=_AT)


def test_add_group_selector_consumes_the_group() -> None:
    tab = (
        DashboardTab("T")
        .add_selector(param_name="alpha", element="input", group="filters")
        .add_group_selector(group="filters", at=_AT)
    )
    assert tab._unclaimed_group_names() == ()
    with pytest.raises(DatalensValidationError, match="no registered members"):
        tab.add_group_selector(group="filters", at=(0, 2, 12, 2))


def test_add_group_selector_failed_call_keeps_members_registered() -> None:
    tab = DashboardTab("T").add_selector(param_name="alpha", element="input", group="filters")
    with pytest.raises(DatalensValidationError, match="at must be"):
        tab.add_group_selector(group="filters", at=(0, 0, 12))  # type: ignore[arg-type]
    assert tab._unclaimed_group_names() == ("filters",)
    tab.add_group_selector(group="filters", at=_AT)
    assert len(tab._pending_snapshot()) == 1


def test_group_selector_wire_matches_fixture_group_shape() -> None:
    builder = _builder().add_tab(
        DashboardTab("T", tab_id="GJ")
        .add_selector(
            item_id="no",
            param_name="field_0002",
            element="input",
            title="Title 2",
            inner_title="=",
            default_value="Value 1",
            operation="EQ",
            required=True,
            group="g",
        )
        .add_selector(
            item_id="om",
            param_name="field_0004",
            element="select",
            title="Title 10",
            inner_title="=",
            options=[("Title 6", "Title 6"), ("Value 5", "Value 5")],
            default_value=["Value 5"],
            operation="EQ",
            required=True,
            group="g",
        )
        .add_group_selector(group="g", item_id="2j", at=(0, 0, 36, 2), apply_button=True, reset_button=True)
    )
    payload = DashboardConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = cast("dict[str, object]", payload["entry"])
    data = cast("dict[str, object]", entry["data"])
    tabs = cast("list[dict[str, object]]", data["tabs"])
    item = cast("list[dict[str, object]]", tabs[0]["items"])[0]
    assert item["id"] == "2j"
    assert item["type"] == "group_control"
    wire_data = cast("dict[str, object]", item["data"])
    assert wire_data["buttonApply"] is True
    assert wire_data["buttonReset"] is True
    members = cast("list[dict[str, object]]", wire_data["group"])
    # pin against group_control_manual.json member shapes
    assert members[0]["defaults"] == {"field_0002": "__eq_Value 1"}
    assert members[1]["defaults"] == {"field_0004": ["__eq_Value 5"]}
    first_source = cast("dict[str, object]", members[0]["source"])
    assert first_source["defaultValue"] == "Value 1"
    assert first_source["operation"] == "EQ"
    assert first_source["required"] is True


# -- connections and aliases (epic D4, stage 13) ------------------------------------


def _wired_tab() -> DashboardTab:
    return (
        DashboardTab("T")
        .add_chart(_chart(id="ch-1"), item_id="w_sales", at=(0, 2, 24, 10))
        .add_selector(item_id="sel_cat", param_name="category", element="input", at=(0, 0, 12, 2))
    )


def _tab_spec(tab: DashboardTab) -> TabSpec:
    return _builder().add_tab(tab).to_spec().tabs[0]


def test_add_connection_translates_logical_ids_to_wire_endpoints() -> None:
    spec = _tab_spec(_wired_tab().add_connection(from_item="w_sales", to_item="sel_cat"))
    # widget expands to its chart-tab id (wt_*), the selector to its member id
    assert [(edge.from_id, edge.to_id) for edge in spec.connections] == [("wt_1", "sel_cat")]


def test_add_connection_mutual_and_idempotency() -> None:
    tab = _wired_tab()
    tab.add_connection(from_item="w_sales", to_item="sel_cat", mutual=True)
    tab.add_connection(from_item="w_sales", to_item="sel_cat")  # duplicate: silent skip
    spec = _tab_spec(tab)
    assert [(edge.from_id, edge.to_id) for edge in spec.connections] == [
        ("wt_1", "sel_cat"),
        ("sel_cat", "wt_1"),
    ]


def test_multi_tab_widget_expands_to_all_chart_tabs() -> None:
    tab = (
        DashboardTab("T")
        .add_chart_group(
            [DashboardChartTab(chart="ch-1", title="A"), DashboardChartTab(chart="ch-2", title="B")],
            item_id="w_group",
            at=(0, 2, 24, 10),
        )
        .add_selector(item_id="sel_cat", param_name="category", element="input", at=(0, 0, 12, 2))
        .add_connection(from_item="w_group", to_item="sel_cat")
    )
    spec = _tab_spec(tab)
    assert [(edge.from_id, edge.to_id) for edge in spec.connections] == [
        ("wt_1", "sel_cat"),
        ("wt_2", "sel_cat"),
    ]


def test_group_wrapper_reference_expands_to_all_members() -> None:
    tab = (
        DashboardTab("T")
        .add_chart(_chart(id="ch-1"), item_id="w_sales", at=(0, 2, 24, 10))
        .add_selector(item_id="m_a", param_name="a", element="input", group="g")
        .add_selector(item_id="m_b", param_name="b", element="input", group="g")
        .add_group_selector(group="g", item_id="grp", at=(0, 0, 24, 2))
        .add_connection(from_item="w_sales", to_item="grp")
        .add_connection(from_item="w_sales", to_item="m_a")  # member-level ref also works
    )
    spec = _tab_spec(tab)
    assert [(edge.from_id, edge.to_id) for edge in spec.connections] == [
        ("wt_1", "m_a"),
        ("wt_1", "m_b"),
    ]


def test_disconnect_all_builds_the_full_mesh_both_directions() -> None:
    spec = _tab_spec(_wired_tab().disconnect_all("w_sales", "sel_cat"))
    assert {(edge.from_id, edge.to_id) for edge in spec.connections} == {
        ("wt_1", "sel_cat"),
        ("sel_cat", "wt_1"),
    }


def test_connection_refs_must_be_explicit_ids_of_connectable_items() -> None:
    tab = _wired_tab().add_text("note", item_id="txt", at=(12, 0, 12, 2))
    tab.add_connection(from_item="txt", to_item="sel_cat")
    with pytest.raises(DatalensValidationError, match="cannot filter or be filtered"):
        _tab_spec(tab)

    dangling = _wired_tab().add_connection(from_item="nope", to_item="sel_cat")
    with pytest.raises(DatalensValidationError, match="not an explicit item_id"):
        _tab_spec(dangling)


def test_add_connection_call_time_validations() -> None:
    tab = _wired_tab()
    with pytest.raises(DatalensValidationError, match="must differ"):
        tab.add_connection(from_item="a", to_item="a")
    with pytest.raises(DatalensValidationError, match="must not be an empty string"):
        tab.add_connection(from_item="", to_item="a")
    with pytest.raises(DatalensValidationError, match="at least two"):
        tab.disconnect_all("only")


def test_add_alias_dedup_and_validation() -> None:
    tab = _wired_tab().add_alias("guid_a", "guid_b").add_alias("guid_b", "guid_a")
    spec = _tab_spec(tab)
    assert spec.aliases == (("guid_a", "guid_b"),)

    with pytest.raises(DatalensValidationError, match="at least two"):
        _wired_tab().add_alias("only")
    with pytest.raises(DatalensValidationError, match="must be unique"):
        _wired_tab().add_alias("same", "same")


def test_wiring_reaches_the_wire_document() -> None:
    builder = _builder().add_tab(
        _wired_tab().add_connection(from_item="w_sales", to_item="sel_cat").add_alias("guid_a", "guid_b")
    )
    payload = DashboardConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = cast("dict[str, object]", payload["entry"])
    data = cast("dict[str, object]", entry["data"])
    wire_tab = cast("list[dict[str, object]]", data["tabs"])[0]
    assert wire_tab["connections"] == [{"from": "wt_1", "to": "sel_cat", "kind": "ignore"}]
    assert wire_tab["aliases"] == {"default": [["guid_a", "guid_b"]]}
