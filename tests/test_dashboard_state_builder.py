from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import cast
import warnings

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dashboard_state import DashboardState
from datalens_sdk.domain.dashboard_state_builder import MAX_STATE_DATA_SYMBOLS, state_data_symbols
from datalens_sdk.domain.dashboard_types import DateInterval
from datalens_sdk.domain.fields import DatasetField

FIXTURES = Path(__file__).parent / "contract" / "fixtures" / "dashboard_state"


class RecordedTransport:
    def __init__(self, entry: dict[str, object], hashes: list[str] | None = None) -> None:
        self.entry = entry
        self.hashes = list(hashes or [])
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/rpc/getDashboard":
            return httpx.Response(200, json={"entry": self.entry})
        assert request.url.path == "/rpc/createEntryState"
        assert self.hashes, "Unexpected createEntryState"
        return httpx.Response(200, json={"hash": self.hashes.pop(0)})

    def created(self) -> list[dict[str, object]]:
        return [
            cast(dict[str, object], json.loads(request.content))
            for request in self.requests
            if request.url.path == "/rpc/createEntryState"
        ]


def _load(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((FIXTURES / f"{name}.json").read_text()))


def _dashboard(entry: dict[str, object], recorder: RecordedTransport | None = None) -> dl.Dashboard:
    transport = recorder or RecordedTransport(entry)
    client = dl.DataLensClientYC(
        auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(transport.handler)
    )
    return client.get.dashboard(by_id=cast(str, entry["entryId"]))


def _items(entry: dict[str, object], tab_index: int = 0) -> list[object]:
    tabs = cast(list[dict[str, object]], cast(dict[str, object], entry["data"])["tabs"])
    return cast(list[object], tabs[tab_index]["items"])


def _dataset_selector(item_id: str, guid: str, title: str, *, multiselect: bool = True) -> dict[str, object]:
    return {
        "data": {
            "source": {
                "datasetFieldId": guid,
                "datasetId": "ds1",
                "elementType": "select",
                "multiselectable": multiselect,
            },
            "sourceType": "dataset",
            "title": title,
        },
        "defaults": {guid: []},
        "id": item_id,
        "namespace": "default",
        "type": "control",
    }


def _field(guid: str, title: str = "Field") -> DatasetField:
    return DatasetField(guid=guid, title=title, name=title, calc_mode="direct")


def _group_dashboard(recorder: RecordedTransport | None = None) -> dl.Dashboard:
    entry = recorder.entry if recorder else _load("dashboard_group_interval_widget_tab")
    return _dashboard(entry, recorder)


def test_builder_reproduces_group_interval_and_widget_tab_state() -> None:
    builder = (
        _group_dashboard()
        .new_state("Mk")
        .select("E7Z", DateInterval("2026-11-10T00:00:00.000Z", "2026-11-16T23:59:59.999Z"))
        .select("Scale", "day")
        .select("department_param", "User")
        .select(item="LEN", widget_tab="dM3")
    )

    expected = cast(dict[str, object], _load("state_group_interval_widget_tab")["data"])
    assert builder.to_raw() == expected
    assert json.dumps(builder.to_raw(), sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_builder_reproduces_action_params_state() -> None:
    builder = (
        _dashboard(_load("dashboard_action_params"))
        .new_state("Main")
        .select(item="Rnn", field=_field("bdd0e5c0-2fcd-11ef-84b1-a9313a50298d"), values="98 DWH_")
        .select(item="Lj", widget_tab="0x", field=_field("171030c0-21bc-11ef-909c-4f6e9f670c50"), values=["Prod"])
    )

    expected = cast(dict[str, object], _load("state_action_params")["data"])
    assert json.dumps(builder.to_raw(), sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_repeated_select_moves_source_to_the_end() -> None:
    builder = _group_dashboard().new_state("Mk").select("Scale", "day").select("department_param", "A")

    builder.select("Scale", "week")

    raw = builder.to_raw()
    assert cast(dict[str, object], raw["__meta__"])["queue"] == [
        {"id": "Wyk", "groupItemId": "78A"},
        {"id": "6n", "groupItemId": "e3G"},
    ]
    assert raw["6n"] == {"params": {"e3G": {"date_scale": "week"}}}


def test_clear_removes_source_from_queue_and_data() -> None:
    builder = _group_dashboard().new_state("Mk").select("Scale", "day").select(item="LEN")

    builder.clear("e3G").clear("LEN")

    assert builder.to_raw() == {"__meta__": {"queue": [], "version": 2}}


def test_chart_without_widget_tab_uses_its_first_tab() -> None:
    raw = _group_dashboard().new_state("Mk").select(item="LEN", values={"date_scale": "week"}).to_raw()

    assert raw["LEN"] == {"params": {"date_scale": "week"}}
    assert cast(dict[str, object], raw["__meta__"])["queue"] == [{"id": "LEN", "tabId": "kQ1"}]


def test_select_by_views_and_operation_prefix() -> None:
    dashboard = _group_dashboard()
    group = dashboard.tabs[0].controls[0]
    member = group.member("e3G")
    assert member is not None

    raw = dashboard.new_state(dashboard.tabs[0]).select(member, "week", operation="NE").to_raw()

    assert raw["6n"] == {"params": {"e3G": {"date_scale": "__ne_week"}}}
    with pytest.raises(dl.DataLensValidationError, match="matches several selectors"):
        dashboard.new_state("Mk").select(group, "x")


def test_prune_drops_orphans() -> None:
    builder = _group_dashboard().new_state("Mk").select("Scale", "day")
    builder.add({"id": "Gone", "params": {"x": "1"}})
    builder.add({"id": "LEN", "tabId": "zz", "params": {}})

    removed = builder.prune()

    assert [(_.item_id, _.kind) for _ in removed] == [("Gone", "unknown"), ("LEN", "chart")]
    assert [_.item_id for _ in builder.selections] == ["6n"]


def test_ambiguous_title_parameter_and_field_are_rejected() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    _items(entry).extend(
        [
            _dataset_selector("S1", "guid-1", "Region"),
            _dataset_selector("S2", "guid-1", "Region"),
        ]
    )
    builder = _dashboard(entry).new_state("Mk")

    with pytest.raises(dl.DataLensValidationError, match="title 'Region' matches several selectors"):
        builder.select("Region", ["EU"])
    with pytest.raises(dl.DataLensValidationError, match="parameter 'guid-1' matches several selectors"):
        builder.select("guid-1", ["EU"])
    with pytest.raises(dl.DataLensValidationError, match="field matches several selectors"):
        builder.select(field=_field("guid-1"), values=["EU"])
    assert builder.select("S1", ["EU"]).to_raw()["S1"] == {"params": {"guid-1": ["EU"]}}


def test_select_by_field_finds_dataset_selector() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    _items(entry).append(_dataset_selector("S1", "guid-1", "Region", multiselect=False))

    raw = _dashboard(entry).new_state("Mk").select(field=_field("guid-1"), values="EU").to_raw()

    assert raw["S1"] == {"params": {"guid-1": "EU"}}


@pytest.mark.parametrize(
    ("call", "match"),
    [
        ({"target": "Nope", "values": "x"}, "No selector 'Nope'"),
        ({"field": _field("guid-x"), "values": "x"}, "bound to field"),
        ({}, "needs a target"),
        ({"item": "LEN", "widget_tab": "zz"}, "has no tab 'zz'"),
        ({"item": "Wyk", "values": "x"}, "not a chart widget"),
        ({"item": "LEN", "values": "x"}, "need field="),
        ({"target": "Period", "values": "2026-01-01"}, "range selector"),
    ],
)
def test_select_rejects_invalid_requests(call: dict[str, object], match: str) -> None:
    builder = _group_dashboard().new_state("Mk")

    with pytest.raises(dl.DataLensValidationError, match=match):
        builder.select(**call)  # type: ignore[arg-type]


def test_create_posts_state_and_returns_dashboard_state() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["abc123"])
    dashboard = _group_dashboard(recorder)

    state = dashboard.new_state("Overview").select("Scale", "week").create()

    assert isinstance(state, DashboardState)
    assert state.hash == "abc123"
    assert state.tab_id == "Mk"
    assert state.created_at is None
    assert recorder.created() == [
        {
            "entryId": "hcnbhimzpyg63",
            "data": {
                "6n": {"params": {"e3G": {"date_scale": "week"}}},
                "__meta__": {"queue": [{"id": "6n", "groupItemId": "e3G"}], "version": 2},
            },
        }
    ]


def test_create_rejects_orphans_foreign_tab_items_and_unknown_params() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"))
    builder = _group_dashboard(recorder).new_state("Mk")
    builder.add({"id": "Gone", "params": {}})
    builder.add({"id": "X1", "tabId": "w1", "params": {}})
    builder.add({"id": "6n", "groupItemId": "zz", "params": {}})
    builder.add({"id": "LEN", "tabId": "dM3", "params": {"undeclared": "1"}})

    with pytest.raises(dl.DataLensValidationError) as exc_info:
        builder.create()

    message = str(exc_info.value)
    assert "Item 'Gone' is not on tab 'Mk'" in message
    assert "Item 'X1' is on tab 'Qa', not on tab 'Mk' and not global" in message
    assert "has no member 'zz'" in message
    assert "Parameter 'undeclared'" in message
    assert recorder.created() == []


def test_create_rejects_states_above_the_size_limit() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"))
    builder = _group_dashboard(recorder).new_state("Mk").select("department_param", "Ж" * MAX_STATE_DATA_SYMBOLS)

    with pytest.raises(dl.DataLensValidationError, match="limit is 50000"):
        builder.create()
    assert recorder.created() == []


def test_state_size_counts_utf16_code_units() -> None:
    assert state_data_symbols({"a": "😀"}) == len('{"a":"') + 2 + len('"}')
    assert state_data_symbols({"a": "Ж"}) == 9


def test_create_state_accepts_raw_mappings() -> None:
    recorder = RecordedTransport(_load("dashboard_action_params"), hashes=["h2"])
    dashboard = _dashboard(recorder.entry, recorder)
    raw = cast(dict[str, object], _load("state_action_params")["data"])

    state = dashboard.create_state(
        "Ab",
        [
            {"id": "Rnn", "tabId": "lJr", "params": {"_ap_bdd0e5c0-2fcd-11ef-84b1-a9313a50298d": ["98 DWH_"]}},
            {"id": "Lj", "tabId": "0x", "params": {"_ap_171030c0-21bc-11ef-909c-4f6e9f670c50": ["Prod"]}},
        ],
    )

    assert state.hash == "h2"
    assert json.dumps(recorder.created()[0]["data"], sort_keys=True) == json.dumps(raw, sort_keys=True)


@pytest.mark.parametrize(
    ("selection", "match"),
    [
        ({"id": "Lj", "extra": 1}, "Unknown selection keys"),
        ({"params": {}}, "non-empty 'id'"),
        ({"id": "Lj", "params": {"a": 1}}, "must map parameter names"),
        ({"id": "Lj", "tabId": ""}, "'tabId' must be a non-empty string"),
    ],
)
def test_create_state_validates_raw_mappings(selection: dict[str, object], match: str) -> None:
    dashboard = _dashboard(_load("dashboard_action_params"))

    with pytest.raises(dl.DataLensValidationError, match=match):
        dashboard.create_state("Ab", [selection])


def test_create_state_rejects_a_single_mapping() -> None:
    dashboard = _dashboard(_load("dashboard_action_params"))

    with pytest.raises(dl.DataLensValidationError, match="sequence"):
        dashboard.create_state("Ab", {"id": "Lj"})  # type: ignore[arg-type]


def test_edit_then_create_gives_a_new_hash() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["second"])
    dashboard = _group_dashboard(recorder)
    data = cast(dict[str, object], _load("state_group_interval_widget_tab")["data"])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        original = DashboardState.from_raw(dashboard, data, hash="21e04f18384")

    edited = original.edit().select("Scale", "week").create()

    assert edited.hash == "second"
    assert [(_.item_id, _.group_item_id) for _ in edited.selections] == [
        ("6n", "E7Z"),
        ("Wyk", "78A"),
        ("LEN", None),
        ("6n", "e3G"),
    ]
    sent = cast(dict[str, object], recorder.created()[0]["data"])
    assert sent["6n"] == {
        "params": {
            "E7Z": {"date_interval": "__interval_2026-11-10T00:00:00.000Z_2026-11-16T23:59:59.999Z"},
            "e3G": {"date_scale": "week"},
        }
    }
    assert original.raw == data


def test_edit_keeps_orphans_until_pruned() -> None:
    dashboard = _group_dashboard()
    data = copy.deepcopy(cast(dict[str, object], _load("state_group_interval_widget_tab")["data"]))
    cast(dict[str, list[object]], data["__meta__"])["queue"].append({"id": "Gone"})
    data["Gone"] = {"params": {}}
    with pytest.warns(UserWarning, match="unknown_state_item"):
        state = DashboardState.from_raw(dashboard, data, tab="Mk")

    builder = state.edit()

    assert [_.item_id for _ in builder.prune()] == ["Gone"]
    assert len(builder.selections) == 4


def test_unbound_dashboard_cannot_create() -> None:
    entry = _load("dashboard_action_params")
    dashboard = dl.Dashboard(id="rmxuwz8j1mqmd", data=cast(dict[str, object], entry["data"]))

    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dashboard.new_state("Ab").select(item="Pv").create()
