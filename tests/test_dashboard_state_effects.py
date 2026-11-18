from __future__ import annotations

import copy

import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dashboard_state import DashboardState


def _manual(member_id: str, param: str, default: object, namespace: str = "default") -> dict[str, object]:
    return {
        "defaults": {param: default},
        "id": member_id,
        "namespace": namespace,
        "source": {"elementType": "select", "fieldName": param},
        "sourceType": "manual",
        "title": member_id,
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


def _data() -> dict[str, object]:
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
                    _widget("W1", [("w1t", {"metric": "sales"})]),
                    _widget("W2", [("w2a", {}), ("w2b", {"metric": "count"})]),
                    _widget("N", [("nt", {})], namespace="other"),
                    {"data": {"text": "x"}, "id": "Txt", "namespace": "default", "type": "text"},
                ],
                "globalItems": [_control("GI", "scale", "day")],
                "connections": [],
                "aliases": {"default": [["city", "town"]]},
                "layout": [],
            }
        ],
    }


def _state(
    queue: list[dict[str, object]], data: dict[str, object], dashboard_data: dict[str, object] | None = None
) -> DashboardState:
    dashboard = dl.Dashboard(id="dash", data=dashboard_data or _data(), rev_id="rev")
    return DashboardState.from_raw(dashboard, {**data, "__meta__": {"queue": queue, "version": 2}}, tab="T")


def _with_connections(*connections: tuple[str, str]) -> dict[str, object]:
    data = copy.deepcopy(_data())
    tab = data["tabs"][0]  # type: ignore[index]
    tab["connections"] = [{"from": source, "kind": "ignore", "to": target} for source, target in connections]
    return data


def test_global_params_defaults_and_queue_are_layered() -> None:
    state = _state([], {})

    assert dict(state.params_for("W1")) == {
        "region": "RU",
        "g": "1",
        "city": "",
        "town": "",
        "metric": "sales",
        "scale": "day",
    }


def test_later_queue_entries_win_on_key_conflicts() -> None:
    state = _state(
        [{"id": "G", "groupItemId": "m1"}, {"id": "C"}],
        {"G": {"params": {"m1": {"region": ["EU"]}}}, "C": {"params": {"region": "US"}}},
    )
    reordered = _state(
        [{"id": "C"}, {"id": "G", "groupItemId": "m1"}],
        {"G": {"params": {"m1": {"region": ["EU"]}}}, "C": {"params": {"region": "US"}}},
    )

    assert state.params_for("W1")["region"] == "US"
    assert reordered.params_for("W1")["region"] == ("EU",)


def test_other_namespaces_do_not_receive() -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}})

    assert state.params_for("N")["region"] == "GLOBAL"
    assert [effect.receiver.id for effect in state.effects()] == ["G", "W1", "W2", "GI"]


@pytest.mark.parametrize(
    ("connection", "receiver"),
    [(("W1", "C"), "W1"), (("w2b", "C"), "W2"), (("m2", "C"), "G")],
    ids=["item-id", "widget-tab-id", "group-member-id"],
)
def test_ignore_connections_stop_delivery(connection: tuple[str, str], receiver: str) -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}}, _with_connections(connection))

    assert state.params_for(receiver)["region"] != "US"
    assert receiver not in [effect.receiver.id for effect in state.effects()]


def test_ignore_by_source_group_member_affects_only_that_member() -> None:
    data = _with_connections(("W1", "m2"))
    state = _state(
        [{"id": "G", "groupItemId": "m1"}, {"id": "G", "groupItemId": "m2"}],
        {"G": {"params": {"m1": {"region": "EU"}, "m2": {"city": "Paris"}}}},
        data,
    )

    params = state.params_for("W1")

    assert params["region"] == "EU"
    assert "city" not in params
    assert [(effect.selection.group_item_id, effect.receiver.id) for effect in state.effects()].count(("m2", "W1")) == 0


def test_ignore_is_directed() -> None:
    state = _state([{"id": "C"}], {"C": {"params": {"region": "US"}}}, _with_connections(("C", "W1")))

    assert state.params_for("W1")["region"] == "US"


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


def test_global_items_receive_and_send() -> None:
    state = _state([{"id": "GI"}], {"GI": {"params": {"scale": "week"}}})

    assert state.params_for("W1")["scale"] == "week"
    assert state.params_for("GI")["scale"] == "week"


def test_chart_tab_from_queue_selects_own_defaults() -> None:
    state = _state([{"id": "W2", "tabId": "w2b"}], {"W2": {"params": {}}})

    assert state.params_for("W2")["metric"] == "count"
    assert state.effects() == ()


def test_params_for_accepts_views_and_member_ids() -> None:
    state = _state([], {})
    tab = state.dashboard.tabs[0]

    assert state.params_for(tab.items[2]) == state.params_for("W1")
    assert state.params_for("m1") == state.params_for("G")
    with pytest.raises(dl.DataLensValidationError, match="not on tab"):
        state.params_for("Missing")


def test_effects_items_limit_receivers_and_skip_orphans() -> None:
    with pytest.warns(UserWarning, match="unknown_state_item"):
        state = _state(
            [{"id": "C"}, {"id": "Gone"}], {"C": {"params": {"region": "US"}}, "Gone": {"params": {"x": "1"}}}
        )

    assert [effect.receiver.id for effect in state.effects(items=["W2"])] == ["W2"]
