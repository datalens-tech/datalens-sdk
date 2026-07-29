"""Behavioral tests for the DashboardCreate builder (epic D2).

Item-level validation lives on the DashboardTab entity and is covered in
test_dashboard_tab.py; this file covers the builder surface: construction,
attach (add_tab), id assignment, plumbing, and spec snapshots.
"""

from __future__ import annotations

import pytest

from datalens_sdk import DashboardCreate, DashboardTab, EntryLocation
from datalens_sdk.domain.dashboard_types import PARENT_FIX_GCONT
from datalens_sdk.domain.specs.dashboard import DashboardSettingsSpec, WidgetItem
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DatalensValidationError

_AT = (0, 0, 12, 6)


def _builder(*, location: EntryLocation | None = None, name: str = "Dash") -> DashboardCreate:
    return DashboardCreate(
        installation="yacloud",
        name=name,
        location=location if location is not None else EntryLocation.path("/Users/me"),
    )


# -- construction ------------------------------------------------------------


def test_collection_location_is_rejected() -> None:
    with pytest.raises(DatalensValidationError, match="location kind"):
        _builder(location=EntryLocation.collection("collection-1"))


def test_workbook_location_is_accepted() -> None:
    spec = _builder(location=EntryLocation.workbook("wb-1")).to_spec()

    assert spec.name == "Dash"


def test_name_with_slash_is_rejected_for_path_locations() -> None:
    with pytest.raises(DatalensValidationError, match="must not contain '/'"):
        _builder(name="a/b")


# -- add_tab / id assignment -----------------------------------------------------


def test_add_tab_generates_deterministic_ids_and_tracks_last_tab_id() -> None:
    builder = _builder()

    with pytest.raises(DatalensValidationError, match="No tabs"):
        _ = builder.last_tab_id

    builder.add_tab(DashboardTab("Overview"))
    assert builder.last_tab_id == "tab_1"

    builder.add_tab(DashboardTab("Details", hidden=True))
    assert builder.last_tab_id == "tab_2"

    spec = builder.to_spec()
    assert [tab.id for tab in spec.tabs] == ["tab_1", "tab_2"]
    assert [tab.title for tab in spec.tabs] == ["Overview", "Details"]
    assert [tab.hidden for tab in spec.tabs] == [False, True]


def test_add_tab_rejects_non_tab_arguments_with_actionable_message() -> None:
    builder = _builder()

    with pytest.raises(DatalensValidationError, match="Build the tab first: DashboardTab"):
        builder.add_tab("Overview")  # type: ignore[arg-type]

    assert builder.to_spec().tabs == ()


def test_explicit_tab_id_reserves_the_value_for_the_auto_counter() -> None:
    builder = _builder()

    builder.add_tab(DashboardTab("First", tab_id="tab_1"))
    builder.add_tab(DashboardTab("Second"))

    assert [tab.id for tab in builder.to_spec().tabs] == ["tab_1", "tab_2"]


def test_duplicate_tab_id_across_attaches_is_rejected() -> None:
    builder = _builder().add_tab(DashboardTab("First", tab_id="intro"))

    with pytest.raises(DatalensValidationError, match="Duplicate tab id 'intro'"):
        builder.add_tab(DashboardTab("Second", tab_id="intro"))


def test_item_ids_are_assigned_in_document_order_across_tabs() -> None:
    builder = (
        _builder()
        .add_tab(DashboardTab("One").add_text("a", at=_AT).add_chart("ch-1", title="T", at=(12, 0, 12, 6)))
        .add_tab(DashboardTab("Two").add_text("b", at=_AT))
    )

    spec = builder.to_spec()
    assert [item.id for tab in spec.tabs for item in tab.items] == ["el_1", "el_2", "el_3"]
    widget = spec.tabs[0].items[1]
    assert isinstance(widget, WidgetItem)
    assert [wt.id for wt in widget.tabs] == ["wt_1"]
    assert spec.generated_id_count == 6  # tab_1, tab_2, el_1..el_3, wt_1


def test_explicit_item_id_is_reserved_across_attaches() -> None:
    builder = _builder().add_tab(DashboardTab("One").add_text("a", item_id="el_1", at=_AT))

    builder.add_tab(DashboardTab("Two").add_text("b", at=_AT))

    spec = builder.to_spec()
    assert [item.id for tab in spec.tabs for item in tab.items] == ["el_1", "el_2"]


def test_explicit_ids_are_claimed_before_autos_within_one_attach() -> None:
    tab = DashboardTab("One").add_text("auto", at=_AT).add_text("explicit", item_id="el_1", at=(0, 6, 12, 6))

    spec = _builder().add_tab(tab).to_spec()

    assert [item.id for item in spec.tabs[0].items] == ["el_2", "el_1"]


def test_duplicate_explicit_item_id_across_attaches_is_rejected() -> None:
    builder = _builder().add_tab(DashboardTab("One").add_text("a", item_id="shared", at=_AT))

    with pytest.raises(DatalensValidationError, match="Duplicate item id 'shared'"):
        builder.add_tab(DashboardTab("Two").add_text("b", item_id="shared", at=_AT))


def test_same_id_is_allowed_across_namespaces() -> None:
    builder = _builder().add_tab(DashboardTab("One", tab_id="shared").add_text("a", item_id="shared", at=_AT))

    spec = builder.to_spec()
    assert spec.tabs[0].id == "shared"
    assert spec.tabs[0].items[0].id == "shared"


def test_pinned_items_get_fix_gcont_parent_at_attach() -> None:
    spec = (
        _builder()
        .add_tab(DashboardTab("One").add_text("pinned", at=_AT, pinned=True).add_text("free", at=(0, 6, 12, 6)))
        .to_spec()
    )

    layout = spec.tabs[0].layout
    assert layout[0].parent == PARENT_FIX_GCONT
    assert layout[1].parent is None


def test_failed_add_tab_leaves_builder_untouched() -> None:
    builder = _builder().add_tab(DashboardTab("One").add_text("a", item_id="taken", at=_AT))
    baseline = builder.to_spec()

    conflicting = DashboardTab("Two", tab_id="tab_9").add_text("b", item_id="taken", at=_AT)
    with pytest.raises(DatalensValidationError, match="Duplicate item id 'taken'"):
        builder.add_tab(conflicting)

    spec = builder.to_spec()
    assert spec.tabs == baseline.tabs
    assert spec.generated_id_count == baseline.generated_id_count
    assert "tab_9" not in {tab.id for tab in spec.tabs}

    builder.add_tab(DashboardTab("Three"))
    assert builder.last_tab_id == "tab_2"  # the failed attach consumed nothing


def test_snapshot_at_attach_isolates_from_later_tab_mutation() -> None:
    tab = DashboardTab("One").add_text("a", at=_AT)
    builder = _builder().add_tab(tab)

    tab.add_text("added later", at=(0, 6, 12, 6))
    tab.title = "Renamed"

    spec = builder.to_spec()
    assert spec.tabs[0].title == "One"
    assert len(spec.tabs[0].items) == 1


def test_tab_is_a_reusable_template() -> None:
    tab = DashboardTab("Shared").add_text("a", at=_AT)

    first = _builder().add_tab(tab)
    second = _builder().add_tab(tab).add_tab(DashboardTab("Extra"))
    twice = _builder().add_tab(tab).add_tab(tab)

    assert [t.id for t in first.to_spec().tabs] == ["tab_1"]
    assert [t.id for t in second.to_spec().tabs] == ["tab_1", "tab_2"]
    assert [t.id for t in twice.to_spec().tabs] == ["tab_1", "tab_2"]
    assert [item.id for t in twice.to_spec().tabs for item in t.items] == ["el_1", "el_2"]


def test_reattaching_tab_with_explicit_ids_fails_loud() -> None:
    tab = DashboardTab("Pinned ids", tab_id="fixed").add_text("a", item_id="el_x", at=_AT)
    builder = _builder().add_tab(tab)

    with pytest.raises(DatalensValidationError, match="Duplicate"):
        builder.add_tab(tab)


def test_installation_mismatch_is_checked_at_attach() -> None:
    foreign_chart = WizardChart(id="ch-1", installation="yateam", name="Sales")
    tab = DashboardTab("One").add_chart(foreign_chart, at=_AT)

    builder = _builder()
    with pytest.raises(DatalensValidationError, match="'yateam' chart"):
        builder.add_tab(tab)
    assert builder.to_spec().tabs == ()

    unset_chart = WizardChart(id="ch-2", installation="", name="Sales")
    builder.add_tab(DashboardTab("Two").add_chart(unset_chart, at=_AT))
    assert builder.last_tab_id == "tab_1"


# -- plumbing -------------------------------------------------------------------


def test_descriptions_flow_into_spec() -> None:
    spec = (
        _builder()
        .description("Main markdown")
        .access_description("How to get access")
        .support_description("Support contacts")
        .to_spec()
    )

    assert spec.description == "Main markdown"
    assert spec.access_description == "How to get access"
    assert spec.support_description == "Support contacts"


def test_descriptions_default_to_not_set() -> None:
    spec = _builder().to_spec()

    assert spec.description is None
    assert spec.access_description is None
    assert spec.support_description is None
    assert spec.meta is None
    assert spec.settings == DashboardSettingsSpec()


def test_settings_calls_merge_and_keep_unset_fields_none() -> None:
    spec = _builder().settings(hide_tabs=True).settings(autoupdate_interval=60).to_spec()

    assert spec.settings.hide_tabs is True
    assert spec.settings.autoupdate_interval == 60
    assert spec.settings.silent_loading is None
    assert spec.settings.dependent_selectors is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"autoupdate_interval": 10}, "autoupdate_interval must be >= 30"),
        ({"autoupdate_interval": True}, "autoupdate_interval must be an int"),
        ({"max_concurrent_requests": 0}, "max_concurrent_requests must be >= 1"),
        ({"max_concurrent_requests": True}, "max_concurrent_requests must be an int"),
        ({"hide_tabs": 1}, "hide_tabs must be a bool"),
        ({"silent_loading": "yes"}, "silent_loading must be a bool"),
        ({"load_priority": "widgets"}, "Unknown load_priority"),
    ],
)
def test_settings_runtime_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(DatalensValidationError, match=match):
        _builder().settings(**kwargs)  # type: ignore[arg-type]


def test_settings_boundary_values_are_accepted() -> None:
    spec = _builder().settings(autoupdate_interval=30, max_concurrent_requests=1, load_priority="selectors").to_spec()

    assert spec.settings.autoupdate_interval == 30
    assert spec.settings.max_concurrent_requests == 1
    assert spec.settings.load_priority == "selectors"


def test_meta_is_defensively_copied() -> None:
    payload: dict[str, str | bool] = {"is_release": True}
    builder = _builder().meta(payload)

    payload["is_release"] = False
    payload["extra"] = "mutated"

    spec = builder.to_spec()
    assert spec.meta == {"is_release": True}

    builder.meta(None)
    assert builder.to_spec().meta is None


def test_to_spec_snapshot_is_isolated_from_later_builder_mutation() -> None:
    builder = _builder().add_tab(DashboardTab("Overview"))
    spec = builder.to_spec()

    builder.add_tab(DashboardTab("Later"))

    assert [tab.id for tab in spec.tabs] == ["tab_1"]
    assert spec.generated_id_count == 1
