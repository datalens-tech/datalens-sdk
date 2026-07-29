from __future__ import annotations

import json
from pathlib import Path

import pytest

from datalens_sdk.domain.dashboard import ControlView, Dashboard, DashboardItemView
from datalens_sdk.domain.dashboard_types import PARENT_FIX_GCONT, PARENT_FIX_HEAD
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.ports import DashboardOperations
from datalens_sdk.errors import DatalensConfigurationError, DatalensValidationError

_WIDGET_ITEM = {
    "id": "it-widget",
    "namespace": "default",
    "type": "widget",
    "orderId": 1,
    "data": {
        "hideTitle": False,
        "tabs": [
            {"id": "wt-1", "title": "Sales", "chartId": "chart-1", "enableActionParams": True},
            {"id": "wt-2", "title": "Costs", "chartId": "chart-2"},
        ],
    },
}

_CONTROL_ITEM = {
    "id": "it-control",
    "namespace": "default",
    "type": "control",
    "data": {"sourceType": "dataset", "source": {"datasetId": "ds-1"}, "title": "Region"},
    "defaults": {"region": "RU"},
}

_UNKNOWN_ITEM = {
    "id": "it-future",
    "namespace": "default",
    "type": "future_widget",
    "data": {"prompt": "sales summary", "novel": {"deeply": ["nested"]}},
}

_SYNTHETIC_DATA = {
    "counter": 12,
    "salt": "0.42",
    "schemeVersion": 8,
    "settings": {"hideTabs": False},
    "tabs": [
        {
            "id": "tab-1",
            "title": "Overview",
            "items": [
                {"id": "it-text", "namespace": "default", "type": "text", "data": {"text": "hello"}},
                {"id": "it-title", "namespace": "default", "type": "title", "data": {"text": "Header", "size": "m"}},
                _WIDGET_ITEM,
                {"id": "it-image", "namespace": "default", "type": "image", "data": {"src": "https://x/img.png"}},
                {"id": "it-neuro", "namespace": "default", "type": "neuro_widget", "data": {"prompt": "explain"}},
                _CONTROL_ITEM,
                {
                    "id": "it-group",
                    "namespace": "default",
                    "type": "group_control",
                    "data": {"group": [{"id": "gc-1", "title": "City", "source": {"datasetId": "ds-2"}}]},
                },
            ],
            "layout": [
                {"i": "it-widget", "x": 0, "y": 0, "w": 12, "h": 6},
                {"i": "it-control", "x": 0, "y": 6, "w": 6, "h": 2, "parent": PARENT_FIX_HEAD},
                {"i": "it-text", "x": 12, "y": 0, "w": 6, "h": 2, "parent": PARENT_FIX_GCONT},
            ],
            "connections": [{"from": "it-control", "to": "it-widget", "kind": "ignore"}],
            "aliases": {"default": [["ds-1.field", "ds-2.field"]]},
            "globalItems": [
                {
                    "id": "it-shared",
                    "namespace": "default",
                    "type": "group_control",
                    "data": {"group": [{"id": "sg-1", "title": "Period"}]},
                }
            ],
        },
        {
            "id": "tab-2",
            "title": "Details",
            "hidden": True,
            "items": [_UNKNOWN_ITEM],
            "layout": [],
            "connections": [],
            "aliases": {},
        },
    ],
}


def _dashboard(**overrides: object) -> Dashboard:
    kwargs: dict[str, object] = {
        "id": "dash-1",
        "installation": "yacloud",
        "data": _SYNTHETIC_DATA,
        "raw": {"entryId": "dash-1", "key": "Folder/sales", "scope": "dash"},
        "rev_id": "rev-2",
        "saved_id": "rev-2",
        "published_id": "rev-1",
        "workbook_id": "wb-1",
    }
    kwargs.update(overrides)
    return Dashboard(**kwargs)  # type: ignore[arg-type]


class _FakeOperations:
    def __init__(self) -> None:
        self.get_calls: list[tuple[str, str | None, str | None, str | None]] = []
        self.delete_calls: list[tuple[str, str | None]] = []

    def create_dashboard(self, builder: object) -> Dashboard:
        raise NotImplementedError

    def create_dashboard_from_raw(self, spec: object) -> Dashboard:
        raise NotImplementedError

    def update_dashboard(
        self,
        builder: object,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard:
        raise NotImplementedError

    def replace_dashboard_from_raw(
        self,
        spec: object,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard:
        raise NotImplementedError

    def publish_dashboard(
        self,
        dashboard: Dashboard,
        rev_id: str,
        lock_token: str | None = None,
    ) -> Dashboard:
        raise NotImplementedError

    def get_dashboard(
        self,
        dashboard_id: str,
        workbook_id: str | None = None,
        branch: str | None = None,
        rev_id: str | None = None,
    ) -> Dashboard:
        self.get_calls.append((dashboard_id, workbook_id, branch, rev_id))
        return _dashboard(id=dashboard_id)

    def delete_dashboard(self, dashboard_id: str, lock_token: str | None = None) -> None:
        self.delete_calls.append((dashboard_id, lock_token))

    def rename_dashboard(self, dashboard: Dashboard, name: str) -> Dashboard:
        raise NotImplementedError

    def get_entry_relations(self, entry_id: str, options: object) -> object:
        raise NotImplementedError

    def export_dashboard_with_dependencies(self, dashboard: Dashboard, path: object) -> Path:
        raise NotImplementedError


def test_fake_operations_satisfy_runtime_checkable_port() -> None:
    assert isinstance(_FakeOperations(), DashboardOperations)


def test_tabs_views_expose_structure() -> None:
    dashboard = _dashboard()

    tabs = dashboard.tabs
    assert [tab.id for tab in tabs] == ["tab-1", "tab-2"]
    assert tabs[0].title == "Overview"
    assert tabs[0].hidden is False
    assert tabs[1].hidden is True

    first = tabs[0]
    assert [item.item_type for item in first.items] == [
        "text",
        "title",
        "widget",
        "image",
        "neuro_widget",
        "control",
        "group_control",
    ]
    assert all(item.is_known_type for item in first.items)
    assert first.connections == ({"from": "it-control", "to": "it-widget", "kind": "ignore"},)
    assert first.aliases == {"default": [["ds-1.field", "ds-2.field"]]}
    assert first.settings == {}


def test_item_views_expose_typed_accessors() -> None:
    tab = _dashboard().tabs[0]
    by_id = {item.id: item for item in tab.items}

    control = by_id["it-control"]
    assert control.namespace == "default"
    assert control.defaults == {"region": "RU"}
    assert control.data["sourceType"] == "dataset"

    widget = by_id["it-widget"]
    assert widget.order_id == 1
    assert widget.defaults == {}


def test_layout_views_expose_pinning_parents() -> None:
    layout = _dashboard().tabs[0].layout
    by_item = {entry.item_id: entry for entry in layout}

    assert by_item["it-widget"].parent is None
    assert (by_item["it-widget"].x, by_item["it-widget"].w) == (0, 12)
    assert by_item["it-control"].parent == PARENT_FIX_HEAD
    assert by_item["it-text"].parent == PARENT_FIX_GCONT


def test_global_items_are_item_views() -> None:
    tab = _dashboard().tabs[0]

    assert len(tab.global_items) == 1
    shared = tab.global_items[0]
    assert isinstance(shared, DashboardItemView)
    assert shared.id == "it-shared"
    assert shared.item_type == "group_control"

    assert _dashboard().tabs[1].global_items == ()


def test_unknown_item_type_is_tolerated_and_keeps_raw_verbatim() -> None:
    unknown = _dashboard().tabs[1].items[0]

    assert unknown.item_type == "future_widget"
    assert unknown.is_known_type is False
    assert unknown.raw is _UNKNOWN_ITEM
    assert unknown.data == {"prompt": "sales summary", "novel": {"deeply": ["nested"]}}


def test_action_params_enabled_is_read_from_widget_tabs() -> None:
    tab = _dashboard().tabs[0]
    by_id = {item.id: item for item in tab.items}

    assert by_id["it-widget"].action_params_enabled is True
    assert by_id["it-control"].action_params_enabled is False
    assert by_id["it-text"].action_params_enabled is False
    with pytest.raises((AttributeError, TypeError)):
        by_id["it-widget"].action_params_enabled = False  # type: ignore[misc]


def test_is_draft_reflects_saved_vs_published() -> None:
    assert _dashboard().is_draft is True
    assert _dashboard(published_id="rev-2").is_draft is False


def test_name_and_key_fall_back_between_fields_raw_and_location() -> None:
    unbound = _dashboard()
    assert unbound.name is None
    assert unbound.key == "Folder/sales"

    named = _dashboard(name="sales")
    assert named.name == "sales"

    located = _dashboard(name="sales", location=EntryLocation.path("Other"), raw={})
    assert located.key == "Other/sales"

    from_raw = _dashboard(raw={"name": "raw-name"})
    assert from_raw.name == "raw-name"


def test_raw_passthrough_via_getattr() -> None:
    dashboard = _dashboard()

    assert dashboard.scope == "dash"
    with pytest.raises(AttributeError):
        _ = dashboard.missing_field


def test_refresh_and_delete_delegate_to_operations() -> None:
    operations = _FakeOperations()
    dashboard = _dashboard(_operations=operations)

    refreshed = dashboard.refresh()
    assert refreshed.id == "dash-1"
    assert operations.get_calls == [("dash-1", "wb-1", None, None)]

    dashboard.delete(lock_token="lock-7")
    assert operations.delete_calls == [("dash-1", "lock-7")]


def test_unbound_dashboard_raises_on_operations() -> None:
    dashboard = _dashboard()

    with pytest.raises(DatalensConfigurationError):
        dashboard.refresh()
    with pytest.raises(DatalensConfigurationError):
        dashboard.delete()

    bound_without_id = _dashboard(id=None, _operations=_FakeOperations())
    with pytest.raises(DatalensValidationError):
        bound_without_id.refresh()
    with pytest.raises(DatalensValidationError):
        bound_without_id.delete()


def test_missing_optional_sections_are_tolerated() -> None:
    sparse = Dashboard(id="dash-2", data={"tabs": [{"id": "only", "title": "T"}]})

    tab = sparse.tabs[0]
    assert tab.items == ()
    assert tab.layout == ()
    assert tab.connections == ()
    assert tab.aliases == {}
    assert tab.global_items == ()

    empty = Dashboard(id="dash-3")
    assert empty.tabs == ()
    assert empty.name is None
    assert empty.key is None


# -- ControlView / ControlSourceView (epic D4, stage 4) ----------------------------
#
# Read-normalization of the three selector wire formats over golden fixtures;
# raw payloads stay reachable verbatim through every view.

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"


def _fixture_dashboard(stem: str) -> Dashboard:
    entry = json.loads((_FIXTURES_DIR / f"{stem}.json").read_text())
    return Dashboard(id=entry.get("entryId"), data=entry["data"], raw=entry)


def test_control_view_wraps_group_control_members() -> None:
    dashboard = _fixture_dashboard("group_control_manual")
    controls = [c for tab in dashboard.tabs for c in tab.controls if c.wire_format == "group_control"]
    assert controls, "fixture must carry a group_control"
    group = controls[0]
    assert group.id == "2j"
    member_ids = [m.id for m in group.members]
    assert member_ids[:3] == ["no", "7o", "om"]
    member = group.member("om")
    assert member is not None
    assert member.source_type == "manual"
    assert member.source.element_type == "select"
    assert member.source.param_name == "field_0004"
    assert member.source.default_value == ["Value 5"]
    assert member.defaults == {"field_0004": ["__eq_Value 5"]}
    assert member.impact_type == "asGroup"


def test_control_view_normalizes_standalone_control() -> None:
    dashboard = _fixture_dashboard("items_features")
    standalones = [c for tab in dashboard.tabs for c in tab.controls if c.wire_format == "standalone_control"]
    assert standalones, "fixture must carry a standalone control"
    control = standalones[0]
    members = control.members
    assert len(members) == 1
    member = members[0]
    # standalone: member identity == item id, defaults live at item level
    assert member.id == control.id
    assert member.source_type == "manual"
    assert member.source.element_type == "select"
    assert member.source.multiselect is True
    assert control.member(member.id or "") is member or control.member(member.id or "") == member


def test_control_view_reads_dataset_selectors_in_global_items() -> None:
    dashboard = _fixture_dashboard("global_items_shared_selectors")
    seen: dict[str | None, list[str | None]] = {}
    for tab in dashboard.tabs:
        for control in tab.controls:
            for member in control.members:
                if member.source_type == "dataset":
                    seen.setdefault(tab.id, []).append(member.source.dataset_field_id)
    assert seen, "fixture must carry dataset selectors in globalItems"
    # the shared-contract: the same selectors appear on every tab
    per_tab = [tuple(sorted(filter(None, guids))) for guids in seen.values()]
    assert len(set(per_tab)) == 1


def test_control_view_keeps_raw_reachable_and_unknown_fields() -> None:
    raw_member = {
        "id": "m1",
        "title": "T",
        "sourceType": "manual",
        "source": {"elementType": "input", "fieldName": "p", "futureKnob": {"x": 1}},
        "defaults": {"p": ""},
        "someFutureField": "kept",
    }
    item = DashboardItemView(
        raw={"id": "g1", "type": "group_control", "namespace": "default", "data": {"group": [raw_member]}}
    )
    view = ControlView.from_item(item)
    assert view is not None
    member = view.members[0]
    assert member.raw is raw_member
    assert member.raw["someFutureField"] == "kept"
    assert member.source.raw["futureKnob"] == {"x": 1}


def test_control_view_normalizes_tabs_wrapped_control() -> None:
    # the third historical wire format: control with data.tabs[] entries
    raw_entry = {
        "id": "t1",
        "title": "Tab selector",
        "sourceType": "manual",
        "source": {"elementType": "select", "fieldName": "p_tab", "defaultValue": ["v1"]},
        "defaults": {"p_tab": ["v1"]},
        "legacyKnob": True,
    }
    item = DashboardItemView(
        raw={"id": "c_tabs", "type": "control", "namespace": "default", "data": {"tabs": [raw_entry]}}
    )
    view = ControlView.from_item(item)
    assert view is not None
    assert view.wire_format == "tabs_control"
    members = view.members
    assert len(members) == 1
    member = members[0]
    assert member.id == "t1"
    assert member.title == "Tab selector"
    assert member.source_type == "manual"
    assert member.source.element_type == "select"
    assert member.source.default_value == ["v1"]
    assert member.defaults == {"p_tab": ["v1"]}
    # unknown fields stay reachable verbatim
    assert member.raw is raw_entry
    assert member.raw["legacyKnob"] is True
    assert view.member("t1") == member


def test_control_view_rejects_non_control_items() -> None:
    assert ControlView.from_item(DashboardItemView(raw={"id": "w", "type": "widget", "data": {}})) is None


def test_control_view_member_resolution_misses_return_none() -> None:
    dashboard = _fixture_dashboard("group_control_manual")
    group = next(c for tab in dashboard.tabs for c in tab.controls if c.wire_format == "group_control")
    assert group.member("definitely_missing") is None
