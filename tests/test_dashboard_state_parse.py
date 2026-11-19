from __future__ import annotations

from collections.abc import Mapping
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, cast
import warnings

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_state import DashboardStateConverter
from datalens_sdk.domain.dashboard import ControlMemberView, ControlView, DashboardItemView
from datalens_sdk.domain.dashboard_state import DashboardState
from datalens_sdk.domain.dashboard_types import DateInterval


def _from_json(dashboard: dl.Dashboard, data: Mapping[str, object] | None, **kwargs: Any) -> DashboardState:
    return DashboardState.from_data(dashboard, DashboardStateConverter.to_domain(data), raw=data or {}, **kwargs)


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
        return _from_json(
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


def test_unprefixed_value_is_in_even_for_a_selector_with_an_operation() -> None:
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
        state = _from_json(_dashboard(entry), data)

    selection = state.selections[0]
    assert selection.kind == "selector"
    assert isinstance(selection.item, ControlView)
    assert selection.values[0].operation == "IN"
    assert selection.values[0].operands[0].operation is None
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
        state = _from_json(dashboard, data, tab="Mk", hash="h1")

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
            _from_json(_dashboard(_load("dashboard_action_params")), data, tab="Ab", strict=True)


def test_unknown_chart_param_is_reported_but_action_params_are_not() -> None:
    data = {
        "LEN": {"params": {"date_scale": "day", "other": "x", "_ap_guid": ["v"]}},
        "__meta__": {"queue": [{"id": "LEN", "tabId": "dM3"}], "version": 2},
    }

    with pytest.warns(UserWarning, match="unknown_state_param"):
        state = _from_json(_dashboard(_load("dashboard_group_interval_widget_tab")), data)

    assert [(_.kind, _.item_id) for _ in state.issues] == [("unknown_state_param", "LEN")]
    assert "'other'" in state.issues[0].message


def test_legacy_v1_state_follows_key_order() -> None:
    data: dict[str, object] = {"Lj": {"params": {"_ap_a": ["1"]}}, "Rnn": {"params": {"_ap_b": ["2"]}}}

    with pytest.warns(UserWarning, match="legacy_state_version"):
        state = _from_json(_dashboard(_load("dashboard_action_params")), data)

    assert state.version == 1
    assert [_.item_id for _ in state.selections] == ["Lj", "Rnn"]
    assert [_.kind for _ in state.issues] == ["legacy_state_version"]


def test_data_entries_outside_the_queue_are_not_sources() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    data["__meta__"] = {"queue": [{"id": "LEN", "tabId": "dM3"}], "version": 2}

    state = _parse("dashboard_group_interval_widget_tab", "state_group_interval_widget_tab", data=data)

    assert [(_.item_id, _.group_item_id) for _ in state.selections] == [("LEN", None)]
    assert state.params_for("78A")["department_param"] == ""
    assert state.raw == data


def test_chart_source_applies_only_on_the_active_widget_tab() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    data["LEN"] = {"params": {"date_scale": "month"}, "state": {"tabId": "kQ1"}}

    state = _parse("dashboard_group_interval_widget_tab", "state_group_interval_widget_tab", data=data)

    chart = state.selections[-1]
    assert (chart.item_id, chart.widget_tab_id, chart.applied) == ("LEN", "dM3", False)
    assert state.issues == ()
    assert not any(_.selection is chart for _ in state.effects())


def test_spec_example_round_trips_with_the_widget_state() -> None:
    spec = json.loads((Path(__file__).parents[1] / "spec" / "yacloud.json").read_text())
    example = cast(dict[str, object], spec["components"]["schemas"]["DashboardState"]["examples"][0])
    dashboard = _dashboard(_load("dashboard_spec_example"))

    state = _from_json(dashboard, example)
    payload = DashboardStateConverter.to_payload(state.edit().to_data())

    assert payload == example
    assert cast(dict[str, dict[str, object]], payload)["chart-widget-id"]["state"] == {"tabId": "chart-tab-id"}
    assert [(_.item_id, _.applied) for _ in state.selections] == [
        ("selector-widget-id", True),
        ("group-widget-id", True),
        ("chart-widget-id", True),
    ]


def test_empty_or_null_state_has_no_selections() -> None:
    dashboard = _dashboard(_load("dashboard_action_params"))

    assert _from_json(dashboard, None).selections == ()
    assert _from_json(dashboard, {}).version == 2


def test_tab_is_inferred_from_queue_items() -> None:
    assert _group_state().tab_id == "Mk"


def test_state_of_global_items_uses_the_first_fitting_tab_unless_tab_is_passed() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    tabs = cast(list[dict[str, object]], cast(dict[str, object], entry["data"])["tabs"])
    tabs[1]["globalItems"] = copy.deepcopy(tabs[0]["items"])
    shared = _dashboard(entry)
    data = _state_data("state_group_interval_widget_tab")

    assert _from_json(shared, data).tab_id == "Mk"
    assert _from_json(shared, data, tab="Details").tab_id == "Qa"


def test_tab_inference_rejects_states_that_fit_no_tab() -> None:
    data = _state_data("state_action_params")

    with pytest.raises(dl.DataLensValidationError, match="No dashboard tab contains"):
        _from_json(_dashboard(_load("dashboard_group_interval_widget_tab")), data)


def test_one_tab_dashboard_reports_orphans_without_tab() -> None:
    data = _state_data("state_group_interval_widget_tab")

    with pytest.warns(UserWarning, match="unknown_state_item"):
        state = _from_json(_dashboard(_load("dashboard_action_params")), data)

    assert state.tab_id == "Ab"
    assert all(_.is_orphan for _ in state.selections)


def test_explicit_tab_by_id_title_or_view() -> None:
    dashboard = _dashboard(_load("dashboard_group_interval_widget_tab"))
    data = _state_data("state_group_interval_widget_tab")

    assert _from_json(dashboard, data, tab="Overview").tab_id == "Mk"
    assert _from_json(dashboard, data, tab=dashboard.tabs[0]).tab_id == "Mk"
    with pytest.raises(dl.DataLensValidationError, match="Unknown tab 'Nope'"):
        _from_json(dashboard, data, tab="Nope")


def test_created_at_and_hash_are_kept() -> None:
    created_at = datetime(2026, 11, 16, 9, 31, tzinfo=timezone.utc)
    dashboard = _dashboard(_load("dashboard_action_params"))

    state = _from_json(dashboard, _state_data("state_action_params"), hash="298725dd251", created_at=created_at)

    assert state.hash == "298725dd251"
    assert state.created_at == created_at


def test_state_is_immutable() -> None:
    with pytest.raises(AttributeError):
        _group_state().tab_id = "Qa"  # type: ignore[misc]


def test_state_snapshot_is_read_only_and_independent_of_its_input() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    state = _parse("dashboard_group_interval_widget_tab", "state_group_interval_widget_tab", data=data)

    cast(dict[str, Any], data["LEN"])["state"] = {"tabId": "kQ1"}
    with pytest.raises(TypeError):
        state.data.widgets["LEN"] = dl.StateWidget()  # type: ignore[index]
    widget_params = state.data.widgets["6n"].params
    assert widget_params is not None
    with pytest.raises(TypeError):
        widget_params["E7Z"] = {}  # type: ignore[index]
    raw = state.raw
    raw["LEN"] = {"params": {"x": "1"}}

    assert state.raw == _state_data("state_group_interval_widget_tab")
    assert state.active_chart_id("LEN") == "qlchart000001"


def test_active_chart_id_follows_the_widget_state() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    data["LEN"] = {"params": {}, "state": {"tabId": "kQ1"}}

    state = _parse("dashboard_group_interval_widget_tab", "state_group_interval_widget_tab", data=data)

    assert state.active_chart_id("LEN") == "wizchart00001"
    with pytest.raises(dl.DataLensValidationError, match="not a chart widget"):
        state.active_chart_id("6n")


def test_empty_params_map_marks_a_version_1_state() -> None:
    data = DashboardStateConverter.to_domain({"W2": {"params": {}}})

    assert data.version == 1


def test_version_1_state_keyed_by_a_group_selector_resolves_it() -> None:
    dashboard = _dashboard(_load("dashboard_group_interval_widget_tab"))

    with pytest.warns(UserWarning, match="legacy_state_version"):
        state = _from_json(dashboard, {"e3G": {"params": {"date_scale": "week"}}})

    selection = state.selections[0]
    assert (state.tab_id, selection.item_id, selection.group_item_id, selection.applied) == ("Mk", "6n", "e3G", True)
    assert state.params_for("e3G")["date_scale"] == "week"


def test_group_item_id_on_a_chart_is_reported_and_not_applied() -> None:
    data = {
        "LEN": {"params": {"x": {"_ap_f": ["A"]}}},
        "__meta__": {"queue": [{"id": "LEN", "groupItemId": "x", "tabId": "dM3"}], "version": 2},
    }

    with pytest.warns(UserWarning, match="is not a selector group"):
        state = _from_json(_dashboard(_load("dashboard_group_interval_widget_tab")), data, tab="Mk")

    assert not state.selections[0].applied
    assert "f" not in state.params_for("Zt9")


def test_stale_active_widget_tab_is_reported_and_falls_back_to_the_default() -> None:
    data = copy.deepcopy(_state_data("state_group_interval_widget_tab"))
    data["LEN"] = {"params": {}, "state": {"tabId": "deleted"}}
    dashboard = _dashboard(_load("dashboard_group_interval_widget_tab"))

    with pytest.raises(dl.DataLensValidationError, match=r"state\.tabId"):
        _from_json(dashboard, data, tab="Mk", strict=True)
    with pytest.warns(UserWarning, match=r"state\.tabId"):
        state = _from_json(dashboard, data, tab="Mk")

    assert state.active_chart_id("LEN") == "qlchart000001"


def test_python_field_names_in_extensions_stay_extensions() -> None:
    raw = {
        "LEN": {"params": {}, "state": {"tab_id": "kQ1"}},
        "__meta__": {"queue": [{"id": "LEN", "tabId": "dM3", "tab_id": "x", "group_item_id": "y"}], "version": 2},
    }

    data = DashboardStateConverter.to_domain(raw)
    state = _from_json(_dashboard(_load("dashboard_group_interval_widget_tab")), raw, tab="Mk")

    widget_state = data.widgets["LEN"].state
    assert widget_state is not None
    assert (widget_state.tab_id, dict(widget_state.extra)) == (None, {"tab_id": "kQ1"})
    assert data.queue[0].group_item_id is None
    assert state.active_chart_id("LEN") == "qlchart000001"
    assert DashboardStateConverter.to_payload(data) == raw
