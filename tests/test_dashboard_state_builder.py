from __future__ import annotations

from collections.abc import Mapping
import copy
import json
from pathlib import Path
from typing import Any, cast
import warnings

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_state import DashboardStateConverter
from datalens_sdk.domain.dashboard_state import DashboardState
from datalens_sdk.domain.dashboard_state_builder import DashboardStateBuilder
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDate
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


def _payload(builder: DashboardStateBuilder) -> dict[str, Any]:
    return DashboardStateConverter.to_payload(builder.to_data())


def _from_json(dashboard: dl.Dashboard, data: Mapping[str, object], **kwargs: Any) -> DashboardState:
    return DashboardState.from_data(dashboard, DashboardStateConverter.to_domain(data), raw=data, **kwargs)


def _dashboard(entry: dict[str, object], recorder: RecordedTransport | None = None) -> dl.Dashboard:
    transport = recorder or RecordedTransport(entry)
    client = dl.DataLensClientYC(
        auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(transport.handler)
    )
    return client.get.dashboard(by_id=cast(str, entry["entryId"]))


def _items(entry: dict[str, object], tab_index: int = 0) -> list[object]:
    tabs = cast(list[dict[str, object]], cast(dict[str, object], entry["data"])["tabs"])
    return cast(list[object], tabs[tab_index]["items"])


def _dataset_selector(
    item_id: str,
    guid: str,
    title: str,
    *,
    multiselect: bool = True,
    operation: str | None = None,
) -> dict[str, object]:
    source: dict[str, object] = {
        "datasetFieldId": guid,
        "datasetId": "ds1",
        "elementType": "select",
        "multiselectable": multiselect,
    }
    if operation is not None:
        source["operation"] = operation
    return {
        "data": {"source": source, "sourceType": "dataset", "title": title},
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

    assert _payload(builder) == _load("state_group_interval_widget_tab")["data"]


def test_builder_reproduces_action_params_state() -> None:
    builder = (
        _dashboard(_load("dashboard_action_params"))
        .new_state("Main")
        .select(item="Rnn", field=_field("bdd0e5c0-2fcd-11ef-84b1-a9313a50298d"), values="98 DWH_")
        .select(item="Lj", widget_tab="0x", field=_field("171030c0-21bc-11ef-909c-4f6e9f670c50"), values=["Prod"])
    )

    assert _payload(builder) == _load("state_action_params")["data"]


def test_choosing_a_non_default_chart_tab_sets_widget_state() -> None:
    builder = _group_dashboard().new_state("Mk").select(item="LEN", widget_tab="kQ1")

    payload = _payload(builder)

    assert payload["LEN"] == {"params": {}, "state": {"tabId": "kQ1"}}
    assert payload["__meta__"]["queue"] == [{"id": "LEN", "tabId": "kQ1"}]
    assert [(_.widget_tab_id, _.applied) for _ in builder.selections] == [("kQ1", True)]


def test_choosing_the_default_chart_tab_back_drops_the_state() -> None:
    builder = (
        _group_dashboard().new_state("Mk").select(item="LEN", widget_tab="kQ1").select(item="LEN", widget_tab="dM3")
    )

    assert _payload(builder)["LEN"] == {"params": {}}


def test_chart_without_widget_tab_keeps_its_active_tab() -> None:
    payload = _payload(_group_dashboard().new_state("Mk").select(item="LEN", values={"date_scale": "week"}))

    assert payload["__meta__"]["queue"] == [{"id": "LEN", "tabId": "dM3"}]
    assert payload["LEN"] == {"params": {"date_scale": "week"}}


def test_repeated_select_moves_source_to_the_end() -> None:
    builder = _group_dashboard().new_state("Mk").select("Scale", "day").select("department_param", "A")

    builder.select("Scale", "week")

    payload = _payload(builder)
    assert payload["__meta__"]["queue"] == [{"id": "Wyk", "groupItemId": "78A"}, {"id": "6n", "groupItemId": "e3G"}]
    assert payload["6n"] == {"params": {"e3G": {"date_scale": "week"}}}


def test_clear_removes_source_from_queue_and_keeps_widget_state() -> None:
    builder = _group_dashboard().new_state("Mk").select("Scale", "day").select(item="LEN", widget_tab="kQ1")

    builder.clear("e3G").clear("LEN")

    assert _payload(builder) == {"LEN": {"state": {"tabId": "kQ1"}}, "__meta__": {"queue": [], "version": 2}}


def test_selector_operation_is_written_like_the_ui() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    _items(entry).append(_dataset_selector("S1", "guid-1", "Region", operation="NE"))
    dashboard = _dashboard(entry)

    own = _payload(dashboard.new_state("Mk").select("S1", ["EU"]))
    explicit = _payload(dashboard.new_state("Mk").select("S1", ["EU"], operation="IN"))

    assert own["S1"] == {"params": {"guid-1": ["__ne_EU"]}}
    assert explicit["S1"] == {"params": {"guid-1": ["__in_EU"]}}
    assert _from_json(dashboard, explicit).selections[0].values[0].operation == "IN"
    assert _from_json(dashboard, own).selections[0].values[0].operation == "NE"


def test_select_by_views_and_operation_prefix() -> None:
    dashboard = _group_dashboard()
    group = dashboard.tabs[0].controls[0]
    member = group.member("e3G")
    assert member is not None

    payload = _payload(dashboard.new_state(dashboard.tabs[0]).select(member, "week", operation="NE"))

    assert payload["6n"] == {"params": {"e3G": {"date_scale": "__ne_week"}}}
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
    _items(entry).extend([_dataset_selector("S1", "guid-1", "Region"), _dataset_selector("S2", "guid-1", "Region")])
    builder = _dashboard(entry).new_state("Mk")

    with pytest.raises(dl.DataLensValidationError, match="title 'Region' matches several selectors"):
        builder.select("Region", ["EU"])
    with pytest.raises(dl.DataLensValidationError, match="parameter 'guid-1' matches several selectors"):
        builder.select("guid-1", ["EU"])
    with pytest.raises(dl.DataLensValidationError, match="field matches several selectors"):
        builder.select(field=_field("guid-1"), values=["EU"])
    assert _payload(builder.select("S1", ["EU"]))["S1"] == {"params": {"guid-1": ["EU"]}}


def test_select_by_field_finds_dataset_selector() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    _items(entry).append(_dataset_selector("S1", "guid-1", "Region", multiselect=False))

    payload = _payload(_dashboard(entry).new_state("Mk").select(field=_field("guid-1"), values="EU"))

    assert payload["S1"] == {"params": {"guid-1": "EU"}}


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
    assert state.raw == recorder.created()[0]["data"]


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
    builder = _group_dashboard(recorder).new_state("Mk").select("department_param", "Ж" * 50_000)

    with pytest.raises(dl.DataLensValidationError, match="limit is 50000"):
        builder.create()
    assert recorder.created() == []


def test_create_state_accepts_raw_mappings() -> None:
    recorder = RecordedTransport(_load("dashboard_action_params"), hashes=["h2"])
    dashboard = _dashboard(recorder.entry, recorder)

    state = dashboard.create_state(
        "Ab",
        [
            {"id": "Rnn", "tabId": "lJr", "params": {"_ap_bdd0e5c0-2fcd-11ef-84b1-a9313a50298d": ["98 DWH_"]}},
            {"id": "Lj", "tabId": "0x", "params": {"_ap_171030c0-21bc-11ef-909c-4f6e9f670c50": ["Prod"]}},
        ],
    )

    assert state.hash == "h2"
    assert recorder.created()[0]["data"] == _load("state_action_params")["data"]


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


def test_edit_keeps_widget_states_and_moves_the_reselected_source() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["second"])
    dashboard = _group_dashboard(recorder)
    data = copy.deepcopy(cast(dict[str, Any], _load("state_group_interval_widget_tab")["data"]))
    data["Zt9"] = {"state": {"tabId": "p0", "zoom": 2}}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        original = _from_json(dashboard, data, hash="21e04f18384")

    edited = original.edit().select("Scale", "week").create()

    assert edited.hash == "second"
    assert [(_.item_id, _.group_item_id) for _ in edited.selections] == [
        ("6n", "E7Z"),
        ("Wyk", "78A"),
        ("LEN", None),
        ("6n", "e3G"),
    ]
    sent = cast(dict[str, Any], recorder.created()[0]["data"])
    assert sent["Zt9"] == {"state": {"tabId": "p0", "zoom": 2}}
    assert sent["6n"]["params"]["e3G"] == {"date_scale": "week"}
    assert original.raw == data


def test_edit_keeps_orphans_until_pruned() -> None:
    dashboard = _group_dashboard()
    data = copy.deepcopy(cast(dict[str, Any], _load("state_group_interval_widget_tab")["data"]))
    data["__meta__"]["queue"].append({"id": "Gone"})
    data["Gone"] = {"params": {}}
    with pytest.warns(UserWarning, match="unknown_state_item"):
        state = _from_json(dashboard, data, tab="Mk")

    builder = state.edit()

    assert [_.item_id for _ in builder.prune()] == ["Gone"]
    assert len(builder.selections) == 4


def test_unbound_dashboard_cannot_create() -> None:
    entry = _load("dashboard_action_params")
    dashboard = dl.Dashboard(id="rmxuwz8j1mqmd", data=cast(dict[str, object], entry["data"]))

    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        dashboard.new_state("Ab").select(item="Pv").create()


def test_create_state_from_selections_keeps_a_non_default_chart_tab_active() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["copy"])
    dashboard = _group_dashboard(recorder)
    data = {
        "LEN": {"params": {}, "state": {"tabId": "kQ1"}},
        "__meta__": {"queue": [{"id": "LEN", "tabId": "kQ1"}], "version": 2},
    }
    original = _from_json(dashboard, data, tab="Mk")
    assert original.selections[0].applied

    copy_state = dashboard.create_state(original.tab, original.selections)

    assert copy_state.selections[0].applied
    assert recorder.created()[0]["data"] == data


def test_create_rejects_undeclared_params_on_other_item_types() -> None:
    entry = _load("dashboard_group_interval_widget_tab")
    _items(entry).append({"data": {"text": "x"}, "id": "text-item", "namespace": "default", "type": "text"})
    recorder = RecordedTransport(entry)
    builder = _dashboard(entry, recorder).new_state("Mk").add({"id": "text-item", "params": {"undeclared": "x"}})

    with pytest.raises(dl.DataLensValidationError, match="Parameter 'undeclared' of text 'text-item'"):
        builder.create()
    assert recorder.created() == []


def test_select_rejects_non_string_parameter_names() -> None:
    builder = _group_dashboard().new_state("Mk")

    with pytest.raises(dl.DataLensValidationError, match="Parameter names must be non-empty strings"):
        builder.select("Scale", {1: "week"})  # type: ignore[dict-item]


def test_legacy_state_cannot_be_edited_as_a_queue() -> None:
    dashboard = _dashboard(_load("dashboard_action_params"))
    with pytest.warns(UserWarning, match="legacy_state_version"):
        state = _from_json(dashboard, {"Lj": {"params": {"_ap_a": ["1"]}}})

    with pytest.raises(dl.DataLensValidationError, match="version 1 state"):
        state.edit()


def test_untouched_edit_keeps_every_stored_record() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["same"])
    dashboard = _group_dashboard(recorder)
    data = copy.deepcopy(cast(dict[str, Any], _load("state_group_interval_widget_tab")["data"]))
    data["Zt9"] = {"params": {"stale": "x"}, "future": 1}
    data["LEN"]["layout"] = {"w": 2}
    data["__meta__"]["queue"][0]["extra"] = True
    data["__meta__"]["note"] = "kept"
    state = _from_json(dashboard, data, tab="Mk")

    state.edit().create()

    assert recorder.created()[0]["data"] == data


def test_copying_an_inactive_chart_source_that_would_activate_is_rejected() -> None:
    dashboard = _group_dashboard()
    data = {
        "LEN": {"params": {"_ap_guid": ["x"]}, "state": {"tabId": "kQ1"}},
        "__meta__": {"queue": [{"id": "LEN", "tabId": "dM3"}], "version": 2},
    }
    state = _from_json(dashboard, data, tab="Mk")
    assert not state.selections[0].applied

    with pytest.raises(dl.DataLensValidationError, match="would start applying"):
        dashboard.create_state(state.tab, state.selections)


def test_unsaved_builder_data_cannot_be_checked_as_a_state() -> None:
    dashboard = _group_dashboard()
    builder = dashboard.new_state("Mk").select("Scale", "week")

    with pytest.raises(dl.DataLensValidationError, match="not stored yet"):
        DashboardState.from_data(dashboard, builder.to_data(), tab="Mk")


def _duplicate_tab_state(first: str, second: str) -> dict[str, Any]:
    return {
        "LEN": {"params": {"_ap_f": ["x"]}},
        "__meta__": {"queue": [{"id": "LEN", "tabId": first}, {"id": "LEN", "tabId": second}], "version": 2},
    }


@pytest.mark.parametrize(("first", "second"), [("dM3", "kQ1"), ("kQ1", "dM3")])
def test_copying_two_tab_records_of_one_widget_keeps_both(first: str, second: str) -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["copy"])
    dashboard = _group_dashboard(recorder)
    data = _duplicate_tab_state(first, second)
    state = _from_json(dashboard, data, tab="Mk")

    copy_state = dashboard.create_state(state.tab, state.selections)

    assert recorder.created()[0]["data"] == data
    assert copy_state.params_for("Zt9")["f"] == ("x",)


def test_prune_keeps_params_still_used_by_a_surviving_record() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["pruned"])
    dashboard = _group_dashboard(recorder)
    data = _duplicate_tab_state("gone", "dM3")
    with pytest.warns(UserWarning, match="unknown_widget_tab"):
        state = _from_json(dashboard, data, tab="Mk")

    builder = state.edit()
    removed = builder.prune()
    saved = builder.create()

    assert [_.widget_tab_id for _ in removed] == ["gone"]
    assert saved.params_for("Zt9")["f"] == ("x",)
    assert cast(dict[str, Any], recorder.created()[0]["data"])["LEN"] == {"params": {"_ap_f": ["x"]}}


def test_untouched_edit_keeps_empty_records_and_per_record_queue_fields() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["same"])
    dashboard = _group_dashboard(recorder)
    data = _duplicate_tab_state("dM3", "kQ1")
    data["__meta__"]["queue"][0]["note"] = "first"
    data["__meta__"]["queue"][1]["note"] = "last"
    data["Zt9"] = {}
    state = _from_json(dashboard, data, tab="Mk")

    state.edit().create()

    assert recorder.created()[0]["data"] == data


def test_failed_select_leaves_the_builder_unchanged() -> None:
    recorder = RecordedTransport(_load("dashboard_group_interval_widget_tab"), hashes=["after"])
    builder = (
        _group_dashboard(recorder).new_state("Mk").select(item="LEN", widget_tab="dM3", values={"date_scale": "w"})
    )

    with pytest.raises(dl.DataLensValidationError, match="need field="):
        builder.select(item="LEN", widget_tab="kQ1", values="scalar")
    builder.create()

    assert cast(dict[str, Any], recorder.created()[0]["data"])["LEN"] == {"params": {"date_scale": "w"}}


def test_explicit_operation_is_always_written() -> None:
    payload = _payload(_group_dashboard().new_state("Mk").select("Scale", "day", operation="IN"))

    assert payload["6n"] == {"params": {"e3G": {"date_scale": "__in_day"}}}


def test_interval_start_in_milliseconds_is_rejected() -> None:
    interval = DateInterval(RelativeDate("-500ms"), RelativeDate("+0s"))

    with pytest.raises(dl.DataLensValidationError, match="milliseconds"):
        _group_dashboard().new_state("Mk").select("Period", interval)


def test_raw_values_added_to_a_builder_cannot_be_checked_before_storing() -> None:
    dashboard = _group_dashboard()
    builder = dashboard.new_state("Mk").add({"id": "6n", "groupItemId": "e3G", "params": {"date_scale": "__ne_week"}})

    with pytest.raises(dl.DataLensValidationError, match="not stored yet"):
        DashboardState.from_data(dashboard, builder.to_data(), tab="Mk")
