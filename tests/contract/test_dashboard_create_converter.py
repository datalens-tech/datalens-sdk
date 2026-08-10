"""Contract tests for DashboardConverter.from_domain_create (D2.4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk import (
    DashboardChartTab,
    DashboardCreate,
    DashboardTab,
    Dataset,
    DateInterval,
    EntryLocation,
    Position,
    ThemedColor,
)
from datalens_sdk.converter.dashboard import DashboardConverter
from datalens_sdk.domain.dashboard_types import Affects, ShowOnTabs
from datalens_sdk.domain.specs.dashboard import (
    DashboardCreateSpec,
    DashboardSettingsSpec,
    LayoutItemSpec,
    TabSpec,
    TextItem,
    WidgetItem,
    WidgetTabSpec,
)
from datalens_sdk.errors import DataLensValidationError

_AT = (0, 0, 12, 6)


def _builder(*, location: EntryLocation | None = None, name: str = "Dash") -> DashboardCreate:
    return DashboardCreate(
        installation="yacloud",
        name=name,
        location=location if location is not None else EntryLocation.path("/Users/me"),
    )


def _tab(**kwargs: object) -> DashboardTab:
    return DashboardTab("Tab", **kwargs)  # type: ignore[arg-type]


def _payload(builder: DashboardCreate) -> dict[str, object]:
    return DashboardConverter.from_domain_create(builder.to_spec()).to_payload()


def _entry(builder: DashboardCreate) -> dict[str, object]:
    return cast(dict[str, object], _payload(builder)["entry"])


def _data(builder: DashboardCreate) -> dict[str, object]:
    return cast(dict[str, object], _entry(builder)["data"])


def _first_item(data: dict[str, object]) -> dict[str, object]:
    tabs = cast(list[dict[str, object]], data["tabs"])
    items = cast(list[dict[str, object]], tabs[0]["items"])
    return items[0]


def _spec(*tabs: TabSpec, generated: int = 0) -> DashboardCreateSpec:
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
        generated_id_count=generated,
    )


def _text_tab(tab_id: str = "tab_1", item_id: str = "el_1") -> TabSpec:
    return TabSpec(
        id=tab_id,
        title="Tab",
        items=(TextItem(id=item_id, text="hello"),),
        layout=(LayoutItemSpec(i=item_id, x=0, y=0, w=12, h=6),),
    )


# -- document canon ---------------------------------------------------------------


def test_empty_builder_produces_full_canonical_document() -> None:
    data = _data(_builder())

    assert data["schemeVersion"] == 8
    assert isinstance(data["salt"], str)
    assert data["salt"]
    assert data["counter"] == 1
    assert data["tabs"] == []
    assert data["settings"] == {
        "autoupdateInterval": None,
        "maxConcurrentRequests": None,
        "silentLoading": False,
        "dependentSelectors": True,
        "expandTOC": False,
        "globalParams": {},
        "hideDashTitle": False,
        "hideTabs": False,
    }
    assert "description" not in data
    assert "accessDescription" not in data
    assert "supportDescription" not in data


def test_counter_counts_generated_ids_and_stays_deterministic() -> None:
    builder = _builder().add_tab(DashboardTab("Overview").add_text("a", at=_AT))

    first = _data(builder)
    second = _data(builder)

    assert first["counter"] == 2  # generated ids: tab_1 + el_1
    assert first == second


def test_counter_floors_at_one_when_all_ids_are_explicit() -> None:
    builder = _builder().add_tab(DashboardTab("Overview", tab_id="intro").add_text("a", item_id="txt", at=_AT))

    assert _data(builder)["counter"] == 1


def test_settings_merge_defaults_without_overwriting_user_values() -> None:
    builder = _builder().settings(hide_tabs=True, autoupdate_interval=60)

    settings = cast(dict[str, object], _data(builder)["settings"])

    assert settings["hideTabs"] is True
    assert settings["autoupdateInterval"] == 60
    assert settings["maxConcurrentRequests"] is None
    assert settings["silentLoading"] is False
    assert settings["dependentSelectors"] is True


def test_required_nullable_fields_survive_as_nulls() -> None:
    entry = _entry(_builder())
    data = cast(dict[str, object], entry["data"])
    settings = cast(dict[str, object], data["settings"])

    assert "meta" in entry
    assert entry["meta"] is None
    assert "autoupdateInterval" in settings
    assert settings["autoupdateInterval"] is None
    assert "maxConcurrentRequests" in settings
    assert settings["maxConcurrentRequests"] is None


def test_meta_is_passed_through_when_set() -> None:
    entry = _entry(_builder().meta({"is_release": True}))

    assert entry["meta"] == {"is_release": True}


def test_description_channels_go_to_data_not_annotation() -> None:
    entry = _entry(_builder().description("Main").access_description("Access").support_description("Support"))
    data = cast(dict[str, object], entry["data"])

    assert data["description"] == "Main"
    assert data["accessDescription"] == "Access"
    assert data["supportDescription"] == "Support"
    assert "annotation" not in entry


# -- location XOR ---------------------------------------------------------------


def test_path_location_sends_key_without_name_and_workbook() -> None:
    entry = _entry(_builder(location=EntryLocation.path("/Users/me"), name="Dash"))

    assert entry["key"] == "/Users/me/Dash"
    assert "name" not in entry
    assert "workbookId" not in entry


def test_workbook_location_sends_name_and_workbook_without_key() -> None:
    entry = _entry(_builder(location=EntryLocation.workbook("wb-1"), name="Dash"))

    assert "key" not in entry
    assert entry["name"] == "Dash"
    assert entry["workbookId"] == "wb-1"


# -- items wire mapping ------------------------------------------------------------


def test_every_item_carries_default_namespace() -> None:
    builder = _builder().add_tab(
        _tab()
        .add_text("a", at=_AT)
        .add_title("b", at=(0, 6, 12, 2))
        .add_image(src="https://img.test/x.png", at=(0, 8, 12, 6))
        .add_chart("ch-1", title="Chart", at=(12, 0, 12, 6))
    )

    data = _data(builder)
    tabs = cast(list[dict[str, object]], data["tabs"])
    items = cast(list[dict[str, object]], tabs[0]["items"])
    assert [item["namespace"] for item in items] == ["default"] * 4
    assert [item["type"] for item in items] == ["text", "title", "image", "widget"]


def test_tab_always_carries_empty_connections_and_aliases() -> None:
    data = _data(_builder().add_tab(_tab().add_text("a", at=_AT)))

    tabs = cast(list[dict[str, object]], data["tabs"])
    assert tabs[0]["connections"] == []
    assert tabs[0]["aliases"] == {"default": []}


def test_widget_maps_show_title_to_inverted_hide_title() -> None:
    shown = _first_item(_data(_builder().add_tab(_tab().add_chart("ch-1", title="T", at=_AT, show_title=True))))
    hidden = _first_item(_data(_builder().add_tab(_tab().add_chart("ch-1", title="T", at=_AT, show_title=False))))

    assert cast(dict[str, object], shown["data"])["hideTitle"] is False
    assert cast(dict[str, object], hidden["data"])["hideTitle"] is True


def test_chart_description_emits_enable_description_only_when_set() -> None:
    with_description = _first_item(
        _data(_builder().add_tab(_tab().add_chart("ch-1", title="T", at=_AT, description="About")))
    )
    without_description = _first_item(_data(_builder().add_tab(_tab().add_chart("ch-1", title="T", at=_AT))))

    chart_tab = cast(list[dict[str, object]], cast(dict[str, object], with_description["data"])["tabs"])[0]
    assert chart_tab["description"] == "About"
    assert chart_tab["enableDescription"] is True

    bare_tab = cast(list[dict[str, object]], cast(dict[str, object], without_description["data"])["tabs"])[0]
    assert "description" not in bare_tab
    assert "enableDescription" not in bare_tab


def test_title_styling_mapping() -> None:
    item = _first_item(
        _data(
            _builder().add_tab(
                _tab().add_title(
                    "Header",
                    at=_AT,
                    text_color="#027bfeb3",
                    background=ThemedColor(light="#ffffff", dark="#000000"),
                    hint="Hover me",
                )
            )
        )
    )

    data = cast(dict[str, object], item["data"])
    assert data["textSettings"] == {"color": "#027bfeb3"}
    assert data["backgroundSettings"] == {"color": {"light": "#ffffff", "dark": "#000000"}}
    assert data["hint"] == {"enabled": True, "text": "Hover me"}


def test_text_defaults_to_opaque_themed_background() -> None:
    item = _first_item(_data(_builder().add_tab(_tab().add_text("plain", at=_AT))))

    data = cast(dict[str, object], item["data"])
    assert data == {
        "text": "plain",
        "autoHeight": True,
        "backgroundSettings": {"color": {"light": "#FFFFFF", "dark": "#343535"}},
    }


def test_optional_styling_is_omitted_not_nulled() -> None:
    # background=None opts out of the default text background: nothing is nulled
    item = _first_item(_data(_builder().add_tab(_tab().add_text("plain", at=_AT, background=None))))

    data = cast(dict[str, object], item["data"])
    assert data == {"text": "plain", "autoHeight": True}


def test_pinned_layout_parent_is_serialized_verbatim() -> None:
    data = _data(_builder().add_tab(_tab().add_text("a", at=_AT, pinned=True).add_text("b", at=(0, 6, 12, 6))))

    tabs = cast(list[dict[str, object]], data["tabs"])
    layout = cast(list[dict[str, object]], tabs[0]["layout"])
    assert layout[0]["parent"] == "__fixGCont"
    assert "parent" not in layout[1]


def test_chart_group_wire_shape() -> None:
    builder = _builder().add_tab(
        _tab().add_chart_group(
            [
                DashboardChartTab(chart="ch-plan", title="Plan"),
                DashboardChartTab(chart="ch-fact", title="Fact", default=True, params={"mode": "fact"}),
            ],
            at=_AT,
        )
    )

    item = _first_item(_data(builder))
    chart_tabs = cast(list[dict[str, object]], cast(dict[str, object], item["data"])["tabs"])
    assert [tab["chartId"] for tab in chart_tabs] == ["ch-plan", "ch-fact"]
    assert [tab["isDefault"] for tab in chart_tabs] == [False, True]
    assert chart_tabs[1]["params"] == {"mode": ["fact"]}


# -- fail-loud validators ------------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "match"),
    [
        ((0, 0, 40, 6), "x \\+ w must be <= 36"),
        ((30, 0, 7, 6), "x \\+ w must be <= 36"),
        ((-1, 0, 6, 6), "x and y must be >= 0"),
        ((0, 0, 0, 6), "w and h must be > 0"),
        ((0, 0, 6, 0), "w and h must be > 0"),
        ((True, 0, 6, 6), "must be an int"),
        ((0, 0, 6.5, 6), "must be an int"),
    ],
)
def test_grid_validator_rejects_bad_placements(at: tuple[int, int, int, int], match: str) -> None:
    # Position validates at the add_* call site now (fail-fast), before convert.
    with pytest.raises(DataLensValidationError, match=match):
        _tab().add_text("a", at=at)


def test_converter_grid_validator_defends_against_raw_spec() -> None:
    # A TabSpec assembled directly bypasses Position; the converter still guards.
    spec = _spec(
        TabSpec(
            id="tab_1",
            title="Tab",
            items=(TextItem(id="el_1", text="x"),),
            layout=(LayoutItemSpec(i="el_1", x=30, y=0, w=12, h=6),),
        )
    )
    with pytest.raises(DataLensValidationError, match="x \\+ w must be <= 36"):
        DashboardConverter.from_domain_create(spec)


def test_grid_validator_accepts_full_width() -> None:
    builder = _builder().add_tab(_tab().add_text("a", at=(0, 0, 36, 6)))

    DashboardConverter.from_domain_create(builder.to_spec())


def test_overlap_in_default_group_is_rejected() -> None:
    tab = _tab().add_text("a", at=(0, 0, 12, 6)).add_text("b", at=(6, 2, 12, 6))
    with pytest.raises(DataLensValidationError, match="items 'el_1' and 'el_2' overlap"):
        DashboardConverter.from_domain_create(_builder().add_tab(tab).to_spec())


def test_pinned_and_default_at_same_cell_do_not_overlap() -> None:
    # different pin-groups (default vs __fixGCont) are never compared
    tab = _tab().add_text("a", at=(0, 0, 12, 6), pinned=True).add_text("b", at=(0, 0, 12, 6))
    DashboardConverter.from_domain_create(_builder().add_tab(tab).to_spec())


def test_position_and_tuple_at_produce_identical_payload() -> None:
    from_tuple = _data(_builder().add_tab(_tab().add_text("x", at=(0, 0, 12, 6))))
    from_position = _data(_builder().add_tab(_tab().add_text("x", at=Position(0, 0, 12, 6))))
    assert from_tuple == from_position


def test_duplicate_tab_ids_are_rejected() -> None:
    spec = _spec(_text_tab("tab_1", "el_1"), _text_tab("tab_1", "el_2"))

    with pytest.raises(DataLensValidationError, match="Duplicate tab id 'tab_1'"):
        DashboardConverter.from_domain_create(spec)


def test_duplicate_item_ids_across_tabs_are_rejected() -> None:
    spec = _spec(_text_tab("tab_1", "el_1"), _text_tab("tab_2", "el_1"))

    with pytest.raises(DataLensValidationError, match="Duplicate item id 'el_1'"):
        DashboardConverter.from_domain_create(spec)


def test_duplicate_widget_tab_ids_are_rejected() -> None:
    def widget_tab(tab_id: str, item_id: str) -> TabSpec:
        item = WidgetItem(
            id=item_id,
            tabs=(WidgetTabSpec(id="wt_1", chart_id="ch-1", title="T", is_default=True, params={}),),
        )
        return TabSpec(
            id=tab_id,
            title="Tab",
            items=(item,),
            layout=(LayoutItemSpec(i=item_id, x=0, y=0, w=12, h=6),),
        )

    spec = _spec(widget_tab("tab_1", "el_1"), widget_tab("tab_2", "el_2"))

    with pytest.raises(DataLensValidationError, match="Duplicate widget tab id 'wt_1'"):
        DashboardConverter.from_domain_create(spec)


def test_items_layout_bijection_is_enforced() -> None:
    missing_layout = TabSpec(
        id="tab_1",
        title="Tab",
        items=(TextItem(id="el_1", text="x"),),
        layout=(),
    )
    with pytest.raises(DataLensValidationError, match="items without layout \\['el_1'\\]"):
        DashboardConverter.from_domain_create(_spec(missing_layout))

    orphan_layout = TabSpec(
        id="tab_1",
        title="Tab",
        items=(),
        layout=(LayoutItemSpec(i="ghost", x=0, y=0, w=6, h=6),),
    )
    with pytest.raises(DataLensValidationError, match="layout without items \\['ghost'\\]"):
        DashboardConverter.from_domain_create(_spec(orphan_layout))

    duplicated_layout = TabSpec(
        id="tab_1",
        title="Tab",
        items=(TextItem(id="el_1", text="x"),),
        layout=(
            LayoutItemSpec(i="el_1", x=0, y=0, w=6, h=6),
            LayoutItemSpec(i="el_1", x=6, y=0, w=6, h=6),
        ),
    )
    with pytest.raises(DataLensValidationError, match="more than once"):
        DashboardConverter.from_domain_create(_spec(duplicated_layout))


# -- UAT additions wire mapping ------------------------------------------------------


def test_hidden_tab_is_emitted_only_when_true() -> None:
    data = _data(_builder().add_tab(DashboardTab("Visible")).add_tab(DashboardTab("Hidden", hidden=True)))

    tabs = cast(list[dict[str, object]], data["tabs"])
    assert "hidden" not in tabs[0]
    assert tabs[1]["hidden"] is True


def test_chart_hint_maps_to_hint_and_enable_hint() -> None:
    with_hint = _first_item(_data(_builder().add_tab(_tab().add_chart("ch-1", title="T", at=_AT, hint="Hover"))))
    without_hint = _first_item(_data(_builder().add_tab(_tab().add_chart("ch-1", title="T", at=_AT))))

    hint_tab = cast(list[dict[str, object]], cast(dict[str, object], with_hint["data"])["tabs"])[0]
    assert hint_tab["hint"] == "Hover"
    assert hint_tab["enableHint"] is True

    bare_tab = cast(list[dict[str, object]], cast(dict[str, object], without_hint["data"])["tabs"])[0]
    assert "hint" not in bare_tab
    assert "enableHint" not in bare_tab


def test_border_radius_maps_to_wire_field() -> None:
    item = _first_item(_data(_builder().add_tab(_tab().add_text("x", at=_AT, border_radius=12))))

    assert cast(dict[str, object], item["data"])["borderRadius"] == 12


def test_load_priority_is_emitted_only_when_set() -> None:
    default_settings = cast(dict[str, object], _data(_builder())["settings"])
    assert "loadPriority" not in default_settings

    tuned = cast(
        dict[str, object],
        _data(_builder().settings(load_priority="selectors", max_concurrent_requests=2))["settings"],
    )
    assert tuned["loadPriority"] == "selectors"
    assert tuned["maxConcurrentRequests"] == 2


def test_payloads_do_not_share_mutable_settings_state() -> None:
    first = _data(_builder())
    first_settings = cast(dict[str, object], first["settings"])
    cast(dict[str, object], first_settings["globalParams"])["leak"] = "oops"

    second_settings = cast(dict[str, object], _data(_builder())["settings"])
    assert second_settings["globalParams"] == {}


# -- show_on_tabs: shared selectors and impact mapping (epic D4, stage 11) ----------


def _shared_builder(show_on_tabs: ShowOnTabs, *, members: int = 1) -> DashboardCreate:
    home = DashboardTab("Home", tab_id="home")
    if members == 1:
        home.add_selector(
            item_id="sel_1",
            param_name="region",
            element="input",
            show_on_tabs=show_on_tabs,
            at=(0, 0, 12, 2),
        )
    else:
        for index in range(members):
            home.add_selector(item_id=f"sel_{index}", param_name=f"p{index}", element="input", group="g")
        home.add_group_selector(group="g", item_id="grp_1", at=(0, 0, 36, 2), show_on_tabs=show_on_tabs)
    # "hi" sits below the shared selector's row so it never overlaps the copy
    # propagated into this tab when show_on_tabs covers it.
    other = DashboardTab("Other", tab_id="other").add_text("hi", at=(0, 2, 12, 2))
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    return builder.add_tab(home).add_tab(other)


def _wire_tabs(builder: DashboardCreate) -> list[dict[str, object]]:
    entry = cast("dict[str, object]", _payload(builder)["entry"])
    data = cast("dict[str, object]", entry["data"])
    return cast("list[dict[str, object]]", data["tabs"])


def test_shared_all_propagates_to_global_items_of_every_tab_with_identical_ids() -> None:
    tabs = _wire_tabs(_shared_builder("all"))
    for tab in tabs:
        globals_ = cast("list[dict[str, object]]", tab.get("globalItems", []))
        assert len(globals_) == 1, f"tab {tab['id']} must carry the shared selector"
        layout_ids = [entry["i"] for entry in cast("list[dict[str, object]]", tab["layout"])]
        assert globals_[0]["id"] in layout_ids
    home_items = cast("list[dict[str, object]]", tabs[0]["items"])
    assert home_items == []  # shared selector left the home items
    ids = {cast("list[dict[str, object]]", tab["globalItems"])[0]["id"] for tab in tabs}
    assert len(ids) == 1  # the identical-id contract


def test_shared_copies_are_independent_dicts() -> None:
    tabs = _wire_tabs(_shared_builder("all"))
    first = cast("list[dict[str, object]]", tabs[0]["globalItems"])[0]
    second = cast("list[dict[str, object]]", tabs[1]["globalItems"])[0]
    assert first == second
    assert first is not second


def test_shared_single_member_impact_lands_in_group_zero() -> None:
    tabs = _wire_tabs(_shared_builder("all"))
    item = cast("list[dict[str, object]]", tabs[0]["globalItems"])[0]
    data = cast("dict[str, object]", item["data"])
    assert "impactType" not in data  # single-member quirk
    member = cast("list[dict[str, object]]", data["group"])[0]
    assert member["impactType"] == "allTabs"


def test_shared_multi_member_impact_lands_on_data() -> None:
    tabs = _wire_tabs(_shared_builder("all", members=2))
    item = cast("list[dict[str, object]]", tabs[0]["globalItems"])[0]
    data = cast("dict[str, object]", item["data"])
    assert data["impactType"] == "allTabs"
    members = cast("list[dict[str, object]]", data["group"])
    assert all("impactType" not in member for member in members)


def test_shared_tab_list_maps_to_selected_tabs_and_targets_only_those_tabs() -> None:
    tabs = _wire_tabs(_shared_builder(("home",)))
    home, other = tabs
    home_globals = cast("list[dict[str, object]]", home["globalItems"])
    member = cast("list[dict[str, object]]", cast("dict[str, object]", home_globals[0]["data"])["group"])[0]
    assert member["impactType"] == "selectedTabs"
    assert member["impactTabsIds"] == ["home"]
    assert "globalItems" not in other


def test_shared_unknown_tab_id_fails_loud() -> None:
    with pytest.raises(DataLensValidationError, match="unknown tab ids"):
        _payload(_shared_builder(("nope",)))


def test_current_selector_emits_no_impact_fields_and_stays_in_items() -> None:
    tabs = _wire_tabs(_shared_builder("current"))
    home_items = cast("list[dict[str, object]]", tabs[0]["items"])
    assert len(home_items) == 1
    data = cast("dict[str, object]", home_items[0]["data"])
    assert "impactType" not in data
    member = cast("list[dict[str, object]]", data["group"])[0]
    assert "impactType" not in member
    assert "globalItems" not in tabs[0]


def test_shared_matches_global_items_fixture_contract() -> None:
    # the live contract pinned by global_items_shared_selectors.json:
    # the same item ids appear in globalItems of every tab, home included
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "dashboards" / "global_items_shared_selectors.json").read_text()
    )
    fixture_tabs = fixture["data"]["tabs"]
    per_tab_ids = [sorted(str(item["id"]) for item in tab.get("globalItems", [])) for tab in fixture_tabs]
    assert len({tuple(ids) for ids in per_tab_ids}) == 1

    ours = _wire_tabs(_shared_builder("all", members=2))
    ours_ids = [
        sorted(str(item["id"]) for item in cast("list[dict[str, object]]", tab.get("globalItems", []))) for tab in ours
    ]
    assert len({tuple(ids) for ids in ours_ids}) == 1


# -- affects: per-member influence axis inside a shared group ----------------------


def _affects_group(*affects_values: Affects) -> DashboardCreate:
    """A shared (show_on_tabs="all") multi-member group whose members carry the
    given per-member ``affects`` scopes. Two tabs so tuple scopes can target."""
    home = DashboardTab("Home", tab_id="home")
    for index, affects in enumerate(affects_values):
        home.add_selector(item_id=f"m{index}", param_name=f"p{index}", element="input", group="g", affects=affects)
    home.add_group_selector(group="g", item_id="grp", at=(0, 0, 36, 2), show_on_tabs="all")
    other = DashboardTab("Other", tab_id="other").add_text("hi", at=(0, 4, 12, 2))
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    return builder.add_tab(home).add_tab(other)


def _members_wire(builder: DashboardCreate) -> list[dict[str, object]]:
    item = cast("list[dict[str, object]]", _wire_tabs(builder)[0]["globalItems"])[0]
    return cast("list[dict[str, object]]", cast("dict[str, object]", item["data"])["group"])


def test_affects_all_tabs_member_emits_all_tabs() -> None:
    member = _members_wire(_affects_group("all_tabs", "as_group"))[0]
    assert member["impactType"] == "allTabs"
    assert "impactTabsIds" not in member


def test_affects_tab_tuple_member_emits_selected_tabs() -> None:
    member = _members_wire(_affects_group(("other",), "as_group"))[0]
    assert member["impactType"] == "selectedTabs"
    assert member["impactTabsIds"] == ["other"]


def test_affects_as_group_member_emits_no_impact_fields() -> None:
    member = _members_wire(_affects_group("as_group", "all_tabs"))[0]
    assert "impactType" not in member  # inherits the group


def test_affects_reproduces_mixed_scope_group() -> None:
    # a realistic filter bar: some members scoped to a tab, one shared across
    # all tabs, one inheriting the group default
    members = _members_wire(_affects_group(("other",), ("other",), "all_tabs", "as_group"))
    assert [m.get("impactType") for m in members] == ["selectedTabs", "selectedTabs", "allTabs", None]


def test_affects_unknown_tab_id_fails_loud() -> None:
    with pytest.raises(DataLensValidationError, match="unknown tab ids"):
        _payload(_affects_group(("nope",), "as_group"))


def test_affects_single_member_group_rejects_conflicting_axes() -> None:
    # a single-member shared group serializes ONE impact slot (data.group[0]):
    # setting both the group show_on_tabs and a member affects is rejected rather
    # than silently dropping one axis
    with pytest.raises(DataLensValidationError, match="single-member shared group"):
        _affects_group(("other",))


def test_affects_single_member_as_group_inherits_group_scope_cleanly() -> None:
    # as_group single member: the group scope fills group[0] with allTabs and no
    # impactTabsIds (the preserved D4 single-member quirk)
    member = _members_wire(_affects_group("as_group"))[0]
    assert member["impactType"] == "allTabs"
    assert "impactTabsIds" not in member


def test_affects_rejected_on_group_show_on_tabs_member() -> None:
    home = DashboardTab("Home", tab_id="home")
    with pytest.raises(DataLensValidationError, match="show_on_tabs is a group-level"):
        home.add_selector(param_name="p", element="input", group="g", show_on_tabs=("home",))


def test_affects_rejected_on_standalone_selector() -> None:
    home = DashboardTab("Home", tab_id="home")
    with pytest.raises(DataLensValidationError, match="affects applies to group members"):
        home.add_selector(param_name="p", element="input", affects="all_tabs", at=(0, 0, 12, 2))


# -- wiring validation accounts for shared propagation (review fix) -----------------


def _shared_wiring_builder(show_on_tabs: ShowOnTabs) -> DashboardCreate:
    home = DashboardTab("Home", tab_id="home")
    home.add_chart("ch-1", title="W", item_id="w_1", at=(0, 2, 12, 6))
    home.add_selector(
        item_id="sel_1", param_name="region", element="input", at=(0, 0, 12, 2), show_on_tabs=show_on_tabs
    )
    home.add_connection(from_item="w_1", to_item="sel_1")
    other = DashboardTab("Other", tab_id="other").add_text("hi", at=(0, 2, 12, 2))
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    return builder.add_tab(home).add_tab(other)


def test_shared_selector_overlapping_a_target_tab_item_is_rejected() -> None:
    # sel_1 propagates to "other" at (0,0,12,2) where "hi" also sits: the
    # overlap is invisible on the home tab but real on the target (review fix).
    home = DashboardTab("Home", tab_id="home").add_selector(
        item_id="sel_1", param_name="region", element="input", at=(0, 0, 12, 2), show_on_tabs="all"
    )
    other = DashboardTab("Other", tab_id="other").add_text("hi", at=(0, 0, 12, 2))
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    with pytest.raises(DataLensValidationError, match="overlap"):
        DashboardConverter.from_domain_create(builder.add_tab(home).add_tab(other).to_spec())


def test_connection_to_shared_selector_that_left_its_home_tab_fails_loud() -> None:
    # sel_1 moves to globalItems of "other" ONLY: the home-tab edge would ship
    # a dangling endpoint (HTTP 500 territory, P019)
    with pytest.raises(DataLensValidationError, match="show_on_tabs target"):
        _payload(_shared_wiring_builder(("other",)))


def test_connection_to_shared_selector_present_on_its_home_tab_is_allowed() -> None:
    for show_on_tabs in ("all", ("home", "other")):
        tabs = _wire_tabs(_shared_wiring_builder(cast("ShowOnTabs", show_on_tabs)))
        home = tabs[0]
        edges = cast("list[dict[str, object]]", home["connections"])
        assert any(edge.get("to") == "sel_1" for edge in edges)


# -- datetime fields keep time precision end-to-end (review fix) --------------------


def test_datetime_field_interval_default_keeps_the_time_part() -> None:
    dataset = Dataset(
        id="ds-1",
        installation="yacloud",
        result_schema=({"guid": "dt_1", "title": "created", "data_type": "genericdatetime", "type": "DIMENSION"},),
    )
    tab = DashboardTab("T").add_selector(
        dataset=dataset,
        field="created",
        element="date",
        is_range=True,
        default_value=DateInterval("2024-01-01T12:30:00Z", "2024-02-01"),
        at=(0, 0, 12, 2),
    )
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    data = _data(builder.add_tab(tab))
    items = cast("list[dict[str, object]]", cast("dict[str, object]", cast("list[object]", data["tabs"])[0])["items"])
    member = cast("list[dict[str, object]]", cast("dict[str, object]", items[0]["data"])["group"])[0]
    source = cast("dict[str, object]", member["source"])
    assert source["fieldType"] == "genericdatetime"
    # DATETIME edges keep full ISO+Z; the date-only edge expands to day bounds
    assert source["defaultValue"] == "__interval_2024-01-01T12:30:00Z_2024-02-01T23:59:59.999Z"
