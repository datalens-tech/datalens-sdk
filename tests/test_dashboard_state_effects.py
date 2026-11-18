"""Parameter delivery under a state. Expected values follow DashKit ``getItemsParams`` for the same config."""

from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Any

import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_state import DashboardStateConverter
from datalens_sdk.domain.dashboard_state import DashboardState


def _manual(member_id: str, param: str, default: object, **extra: object) -> dict[str, object]:
    return {
        "defaults": {param: default},
        "id": member_id,
        "namespace": "default",
        "source": {"elementType": "select", "fieldName": param},
        "sourceType": "manual",
        "title": member_id,
        **extra,
    }


def _widget(item_id: str, tabs: list[tuple[str, dict[str, object]]], namespace: str = "default") -> dict[str, object]:
    return {
        "data": {"tabs": [{"chartId": f"chart-{tab_id}", "id": tab_id, "params": params} for tab_id, params in tabs]},
        "id": item_id,
        "namespace": namespace,
        "type": "widget",
    }


def _control(item_id: str, param: str, default: object) -> dict[str, object]:
    return {
        "data": {"source": {"elementType": "select", "fieldName": param}, "sourceType": "manual", "title": item_id},
        "defaults": {param: default},
        "id": item_id,
        "namespace": "default",
        "type": "control",
    }


def _data() -> dict[str, Any]:
    return {
        "settings": {"globalParams": {"region": "GLOBAL", "g": "1"}},
        "tabs": [
            {
                "id": "T",
                "title": "Main",
                "items": [
                    {
                        "data": {"group": [_manual("m1", "region", "ALL"), _manual("m2", "city", "")]},
                        "id": "G",
                        "namespace": "default",
                        "type": "group_control",
                    },
                    _control("C", "region", "RU"),
                    _widget("W1", [("w1t", {"metric": "sales", "currency": "EUR"})]),
                    _widget("W2", [("w2a", {}), ("w2b", {"metric": "count"})]),
                    _widget("N", [("nt", {})], namespace="other"),
                    {"data": {"text": "x"}, "id": "Txt", "namespace": "default", "type": "text"},
                ],
                "globalItems": [_control("GI", "scale", "day")],
                "connections": [],
                "aliases": {"default": [["city", "town"]]},
                "layout": [],
            },
            {"id": "T2", "title": "Other", "items": [], "globalItems": [], "connections": [], "aliases": {}},
        ],
    }


def _from_json(dashboard: dl.Dashboard, data: Mapping[str, object], **kwargs: Any) -> DashboardState:
    return DashboardState.from_data(dashboard, DashboardStateConverter.to_domain(data), raw=data, **kwargs)


def _state(
    queue: list[dict[str, object]],
    widgets: dict[str, object],
    dashboard_data: dict[str, Any] | None = None,
) -> DashboardState:
    dashboard = dl.Dashboard(id="dash", data=dashboard_data or _data(), rev_id="rev")
    return _from_json(dashboard, {**widgets, "__meta__": {"queue": queue, "version": 2}}, tab="T")


def _with_connections(*connections: tuple[str, str]) -> dict[str, Any]:
    data = copy.deepcopy(_data())
    data["tabs"][0]["connections"] = [
        {"from": source, "kind": "ignore", "to": target} for source, target in connections
    ]
    return data


def _receivers(state: DashboardState) -> list[tuple[str, str | None]]:
    return [
        (effect.selection.group_item_id or effect.selection.item_id, effect.receiver.id) for effect in state.effects()
    ]


def test_layers_follow_dashkit_order() -> None:
    state = _state([], {})

    assert dict(state.params_for("W1")) == {
        "metric": "sales",
        "currency": "EUR",
        "region": "ALL",
        "g": "1",
        "city": "",
        "town": "",
        "scale": "day",
    }


def test_first_selector_default_wins() -> None:
    assert _state([], {}).params_for("W2")["region"] == "ALL"


def test_chart_tab_params_stay_on_their_chart() -> None:
    state = _state([], {})

    assert "currency" not in state.params_for("W2")
    assert state.params_for("W1")["currency"] == "EUR"


def test_later_queue_entries_win_on_key_conflicts() -> None:
    widgets = {"G": {"params": {"m1": {"region": ["EU"]}}}, "C": {"params": {"region": "US"}}}

    assert _state([{"id": "G", "groupItemId": "m1"}, {"id": "C"}], widgets).params_for("W1")["region"] == "US"
    assert _state([{"id": "C"}, {"id": "G", "groupItemId": "m1"}], widgets).params_for("W1")["region"] == ("EU",)


def test_other_namespaces_do_not_receive() -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}})

    assert state.params_for("N")["region"] == "GLOBAL"
    assert _receivers(state) == [("C", "m1"), ("C", "m2"), ("C", "W1"), ("C", "W2"), ("C", "GI")]


def test_ignore_on_the_active_widget_tab_stops_delivery() -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}}, _with_connections(("w2a", "C")))

    assert state.params_for("W2")["region"] == "ALL"
    assert ("C", "W2") not in _receivers(state)


def test_ignore_on_an_inactive_widget_tab_changes_nothing() -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}}, _with_connections(("w2b", "C")))

    assert state.params_for("W2")["region"] == "US"
    assert ("C", "W2") in _receivers(state)


def test_ignore_follows_the_widget_state_tab() -> None:
    widgets: dict[str, object] = {"C": {"params": {"region": "US"}}, "W2": {"state": {"tabId": "w2b"}}}

    state = _state([{"id": "C"}], widgets, _with_connections(("w2b", "C")))

    assert state.params_for("W2")["region"] == "ALL"
    assert state.params_for("W2")["metric"] == "count"


def test_ignore_by_one_group_member_leaves_its_sibling_receiving() -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}}, _with_connections(("m2", "C")))

    assert state.params_for("m1")["region"] == "US"
    assert state.params_for("m2")["region"] == "ALL"
    assert ("C", "m1") in _receivers(state)
    assert ("C", "m2") not in _receivers(state)


def test_ignore_of_one_source_member_affects_only_that_member() -> None:
    state = _state(
        [{"id": "G", "groupItemId": "m1"}, {"id": "G", "groupItemId": "m2"}],
        {"G": {"params": {"m1": {"region": "EU"}, "m2": {"city": "Paris"}}}},
        _with_connections(("w1t", "m2")),
    )

    params = state.params_for("W1")

    assert params["region"] == "EU"
    assert "city" not in params
    assert ("m2", "W1") not in _receivers(state)


def test_aliases_extend_delivered_params() -> None:
    state = _state([{"id": "G", "groupItemId": "m2"}], {"G": {"params": {"m2": {"city": "Paris"}}}})

    effect = next(effect for effect in state.effects() if effect.receiver.id == "W1")

    assert state.params_for("W1")["town"] == "Paris"
    assert effect.params == ("city", "town")
    assert effect.certainty == "received"
    assert effect.matched_by is None


def test_action_params_lose_prefix_on_other_receivers_only() -> None:
    state = _state([{"id": "W1", "tabId": "w1t"}], {"W1": {"params": {"_ap_guid-1": ["Prod"]}}})

    assert state.params_for("W2")["guid-1"] == ("Prod",)
    assert "_ap_guid-1" not in state.params_for("W2")
    assert state.params_for("W1")["_ap_guid-1"] == ("Prod",)
    assert {effect.params for effect in state.effects()} == {("guid-1",)}


def test_undeclared_queue_params_are_not_delivered() -> None:
    with pytest.warns(UserWarning, match="unknown_state_param"):
        state = _state([{"id": "C"}], {"C": {"params": {"region": "US", "stale": "x"}}})

    assert "stale" not in state.params_for("W1")


def test_chart_source_on_an_inactive_tab_is_not_applied() -> None:
    state = _state([{"id": "W2", "tabId": "w2b"}], {"W2": {"params": {"_ap_guid-1": ["x"]}}})

    assert "guid-1" not in state.params_for("W1")
    assert state.effects() == ()


def test_global_items_receive_and_send() -> None:
    state = _state([{"id": "GI"}], {"GI": {"params": {"scale": "week"}}})

    assert state.params_for("W1")["scale"] == "week"
    assert state.params_for("GI")["scale"] == "week"


def test_global_group_member_of_another_tab_has_no_defaults_here() -> None:
    data = copy.deepcopy(_data())
    group = {
        "data": {"group": [_manual("gm", "segment", "ALL", impactType="selectedTabs", impactTabsIds=["T2"])]},
        "id": "GG",
        "namespace": "default",
        "type": "group_control",
    }
    data["tabs"][0]["globalItems"].append(group)

    state = _state([], {}, data)

    assert "segment" not in state.params_for("W1")
    with pytest.raises(dl.DataLensValidationError, match="receives no parameters here"):
        state.params_for("gm")


def test_legacy_state_keeps_params_per_receiver() -> None:
    dashboard = dl.Dashboard(id="dash", data=_data(), rev_id="rev")
    with pytest.warns(UserWarning, match="legacy_state_version"):
        state = _from_json(dashboard, {"W1": {"params": {"region": "EU"}}, "W2": {"params": {"region": "US"}}})

    assert state.params_for("W1")["region"] == "EU"
    assert state.params_for("W2")["region"] == "US"
    assert state.effects() == ()


def test_group_is_addressed_by_its_selectors() -> None:
    state = _state([], {})
    tab = state.dashboard.tabs[0]

    assert state.params_for(tab.items[2]) == state.params_for("W1")
    assert state.params_for("m1")["region"] == "ALL"
    with pytest.raises(dl.DataLensValidationError, match="pass one of its selectors"):
        state.params_for("G")
    with pytest.raises(dl.DataLensValidationError, match="not on this tab"):
        state.params_for("Missing")


def test_effects_items_limit_receivers_and_skip_orphans() -> None:
    with pytest.warns(UserWarning, match="unknown_state_item"):
        state = _state(
            [{"id": "C"}, {"id": "Gone"}], {"C": {"params": {"region": "US"}}, "Gone": {"params": {"x": "1"}}}
        )

    assert [effect.receiver.id for effect in state.effects(items=["W2", "G"])] == ["m1", "m2", "W2"]
