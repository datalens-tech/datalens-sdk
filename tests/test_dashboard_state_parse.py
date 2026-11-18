from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import cast
import warnings

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dashboard import ControlMemberView, ControlView, DashboardItemView
from datalens_sdk.domain.dashboard_state import DashboardState
from datalens_sdk.domain.dashboard_types import DateInterval

FIXTURES = Path(__file__).parent / "contract" / "fixtures" / "dashboard_state"


def _load(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((FIXTURES / f"{name}.json").read_text()))


def _dashboard(entry: dict[str, object]) -> dl.Dashboard:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rpc/getDashboard"
        return httpx.Response(200, json={"entry": entry})

    client = dl.DataLensClientYC(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(handler))
    return client.get.dashboard(by_id=cast(str, entry["entryId"]))


def _state_data(name: str) -> dict[str, object]:
    return cast(dict[str, object], _load(name)["data"])


def _parse(
    dashboard_name: str,
    state_name: str,
    *,
    data: dict[str, object] | None = None,
    tab: str | None = None,
    strict: bool = False,
) -> DashboardState:
    dashboard = _dashboard(_load(dashboard_name))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return DashboardState.from_raw(
            dashboard,
            _state_data(state_name) if data is None else data,
            tab=tab,
            hash="h1",
            strict=strict,
        )


def _group_state() -> DashboardState:
    return _parse("dashboard_group_interval_widget_tab", "state_group_interval_widget_tab")


def test_selections_follow_the_queue_order() -> None:
    state = _group_state()

    assert [(_.item_id, _.group_item_id, _.widget_tab_id) for _ in state.selections] == [
        ("6n", "E7Z", None),
        ("6n", "e3G", None),
        ("Wyk", "78A", None),
        ("LEN", None, "dM3"),
    ]
    assert state.version == 2
    assert state.tab_id == "Mk"
    assert state.dashboard_id == "hcnbhimzpyg63"
    assert state.rev_id == "hcnbhimzprev1"
    assert state.issues == ()
    assert state.raw == _state_data("state_group_interval_widget_tab")


def test_selection_kinds_items_and_interval_decoding() -> None:
    period, scale, department, chart = _group_state().selections

    assert period.kind == "group_selector"
    assert isinstance(period.item, ControlMemberView)
    assert period.item.title == "Period"
    assert period.values[0].param == "date_interval"
    assert period.values[0].operation == "BETWEEN"
    assert period.values[0].values == (DateInterval("2026-11-10T00:00:00.000Z", "2026-11-16T23:59:59.999Z"),)
    assert scale.values[0].values == ("day",)
    assert scale.values[0].operation == "IN"
    assert department.params == {"department_param": "User"}
    assert chart.kind == "chart"
    assert isinstance(chart.item, DashboardItemView)
    assert chart.values == ()
    assert not any(_.is_orphan for _ in (period, scale, department, chart))


def test_action_params_expose_field_guid() -> None:
    state = _parse("dashboard_action_params", "state_action_params")

    owners, environments = state.selections
    assert (owners.item_id, environments.item_id) == ("Rnn", "Lj")
    value = environments.values[0]
    assert value.is_action_param
    assert value.field_guid == "171030c0-21bc-11ef-909c-4f6e9f670c50"
    assert value.values == ("Prod",)
    assert value.raw == ("Prod",)
    assert owners.values[0].values == ("98 DWH_",)
    assert state.issues == ()


def test_standalone_selector_uses_control_view_and_default_operation() -> None:
    entry = _load("dashboard_action_params")
    tabs = cast(list[dict[str, object]], cast(dict[str, object], entry["data"])["tabs"])
    cast(list[object], tabs[0]["items"]).append(
        {
            "data": {
                "source": {"datasetFieldId": "guid-1", "datasetId": "ds1", "elementType": "select", "operation": "NE"},
                "sourceType": "dataset",
                "title": "Region",
            },
            "defaults": {"guid-1": ""},
            "id": "Sel",
            "namespace": "default",
            "type": "control",
        }
    )
    data = {"Sel": {"params": {"guid-1": ["EU"]}}, "__meta__": {"queue": [{"id": "Sel"}], "version": 2}}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        state = DashboardState.from_raw(_dashboard(entry), data)

    selection = state.selections[0]
    assert selection.kind == "selector"
    assert isinstance(selection.item, ControlView)
    assert selection.values[0].operation == "NE"
    assert selection.values[0].field_guid == "guid-1"


def test_orphans_of_every_kind_become_issues_and_one_warning() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    data["Gone"] = {"params": {"x": "1"}}
    data["Wyk"] = {"params": {"zzz": {"department_param": "User"}}}
    data["6n"] = {"params": {"E7Z": {"unknown_param": "1"}}}
    data["__meta__"] = {
        "queue": [
            {"id": "6n", "groupItemId": "E7Z"},
            {"id": "Wyk", "groupItemId": "zzz"},
            {"id": "LEN", "tabId": "nope"},
            {"id": "Gone"},
        ],
        "version": 2,
    }
    dashboard = _dashboard(_load("dashboard_group_interval_widget_tab"))

    with pytest.warns(UserWarning, match="does not fully match") as record:
        state = DashboardState.from_raw(dashboard, data, tab="Mk", hash="h1")

    assert len(record) == 1
    assert "h1" in str(record[0].message)
    assert [issue.kind for issue in state.issues] == [
        "unknown_state_param",
        "unknown_group_item",
        "unknown_widget_tab",
        "unknown_state_item",
    ]
    assert [(_.item_id, _.kind, _.is_orphan) for _ in state.selections] == [
        ("6n", "group_selector", False),
        ("Wyk", "group_selector", True),
        ("LEN", "chart", True),
        ("Gone", "unknown", True),
    ]
    assert state.issues[0].suggestions == ("date_interval",)


def test_strict_mode_raises_instead_of_warning() -> None:
    data = copy.deepcopy(_state_data("state_action_params"))
    data["__meta__"] = {"queue": [{"id": "Missing"}], "version": 2}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(dl.DataLensValidationError, match="unknown_state_item"):
            DashboardState.from_raw(_dashboard(_load("dashboard_action_params")), data, tab="Ab", strict=True)


def test_unknown_chart_param_is_reported_but_action_params_are_not() -> None:
    data = {
        "LEN": {"params": {"date_scale": "day", "other": "x", "_ap_guid": ["v"]}},
        "__meta__": {"queue": [{"id": "LEN", "tabId": "dM3"}], "version": 2},
    }

    with pytest.warns(UserWarning, match="unknown_state_param"):
        state = DashboardState.from_raw(_dashboard(_load("dashboard_group_interval_widget_tab")), data)

    assert [(_.kind, _.item_id) for _ in state.issues] == [("unknown_state_param", "LEN")]
    assert "'other'" in state.issues[0].message


def test_legacy_v1_state_follows_key_order() -> None:
    data: dict[str, object] = {"Lj": {"params": {"_ap_a": ["1"]}}, "Rnn": {"params": {"_ap_b": ["2"]}}}

    with pytest.warns(UserWarning, match="legacy_state_version"):
        state = DashboardState.from_raw(_dashboard(_load("dashboard_action_params")), data)

    assert state.version == 1
    assert [_.item_id for _ in state.selections] == ["Lj", "Rnn"]
    assert [_.kind for _ in state.issues] == ["legacy_state_version"]


def test_unqueued_data_entries_follow_the_queue() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    data["__meta__"] = {"queue": [{"id": "LEN", "tabId": "dM3"}], "version": 2}

    state = _parse("dashboard_group_interval_widget_tab", "state_group_interval_widget_tab", data=data)

    assert [(_.item_id, _.group_item_id) for _ in state.selections] == [
        ("LEN", None),
        ("6n", "E7Z"),
        ("6n", "e3G"),
        ("Wyk", "78A"),
    ]


def test_empty_or_null_state_has_no_selections() -> None:
    dashboard = _dashboard(_load("dashboard_action_params"))

    assert DashboardState.from_raw(dashboard, None).selections == ()
    assert DashboardState.from_raw(dashboard, {}).version == 2


def test_tab_is_inferred_from_queue_items() -> None:
    assert _group_state().tab_id == "Mk"


def test_tab_inference_rejects_ambiguous_and_missing_tabs() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    tabs = cast(list[dict[str, object]], cast(dict[str, object], entry["data"])["tabs"])
    tabs[1]["globalItems"] = copy.deepcopy(tabs[0]["items"])
    ambiguous = _dashboard(entry)
    data = _state_data("state_group_interval_widget_tab")

    with pytest.raises(dl.DataLensValidationError, match=r"several tabs \['Mk', 'Qa'\]"):
        DashboardState.from_raw(ambiguous, data)
    with pytest.raises(dl.DataLensValidationError, match="No dashboard tab contains"):
        DashboardState.from_raw(_dashboard(_load("dashboard_action_params")), data)


def test_explicit_tab_by_id_title_or_view() -> None:
    dashboard = _dashboard(_load("dashboard_group_interval_widget_tab"))
    data = _state_data("state_group_interval_widget_tab")

    assert DashboardState.from_raw(dashboard, data, tab="Overview").tab_id == "Mk"
    assert DashboardState.from_raw(dashboard, data, tab=dashboard.tabs[0]).tab_id == "Mk"
    with pytest.raises(dl.DataLensValidationError, match="Unknown tab 'Nope'"):
        DashboardState.from_raw(dashboard, data, tab="Nope")


def test_created_at_and_hash_are_kept() -> None:
    created_at = datetime(2026, 11, 16, 9, 31, tzinfo=timezone.utc)
    dashboard = _dashboard(_load("dashboard_action_params"))

    state = DashboardState.from_raw(
        dashboard, _state_data("state_action_params"), hash="298725dd251", created_at=created_at
    )

    assert state.hash == "298725dd251"
    assert state.created_at == created_at


def test_state_is_immutable() -> None:
    with pytest.raises(AttributeError):
        _group_state().tab_id = "Qa"  # type: ignore[misc]
