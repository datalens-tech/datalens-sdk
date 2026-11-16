from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl


@pytest.mark.parametrize("hidden", [None, False, True])
@pytest.mark.parametrize("client_type", [dl.DataLensClientEnterprise, dl.DataLensClientYC])
def test_mobile_visibility_and_switch_survive_typed_create_and_update(
    hidden: bool | None,
    client_type: type[dl.DataLensClientEnterprise] | type[dl.DataLensClientYC],
) -> None:
    entry = cast(dict[str, object], json.loads((Path(__file__).parent / "fixtures/dashboards/simple.json").read_text()))
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, object], json.loads(request.content))
        requests.append(payload)
        written = cast(dict[str, object], payload["entry"])
        return httpx.Response(200, json={"entry": {**entry, **written}})

    tab = (
        dl.DashboardTab("Overview", tab_id="overview")
        .add_text("Text", item_id="text", hidden_on_mobile=hidden)
        .add_title("Title", item_id="title", hidden_on_mobile=hidden)
        .add_chart("chart-1", title="Chart", item_id="chart", hidden_on_mobile=hidden)
        .add_chart_group(
            [dl.DashboardChartTab("chart-2", title="Grouped chart")], item_id="charts", hidden_on_mobile=hidden
        )
        .add_image(src="https://example.test/image.png", item_id="image", hidden_on_mobile=hidden)
        .add_selector(chart="external-chart", title="External", item_id="external", hidden_on_mobile=hidden)
        .add_selector(
            param_name="enabled", element="switch", default_value=True, item_id="enabled", hidden_on_mobile=hidden
        )
        .add_selector(param_name="grouped", element="switch", default_value=False, item_id="grouped", group="flags")
        .add_group_selector(group="flags", item_id="flags", hidden_on_mobile=hidden)
        .add_section_divider("Section", item_id="section", hidden_on_mobile=hidden)
    )
    with client_type(auth=None, base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        dashboard = (
            client.create.dashboard(name="Mobile", location=dl.EntryLocation.path("/Tests")).add_tab(tab).build()
        )
        assert all(item.hidden_on_mobile is (hidden is True) for item in dashboard.tabs[0].items)
        updated = (
            dashboard.update.add_text("Added", tab="overview", item_id="added", hidden_on_mobile=hidden)
            .update_selector(item_id="enabled", default_value=False)
            .execute(publish=False)
        )
        assert all(item.hidden_on_mobile is (hidden is True) for item in updated.tabs[0].items)

    for payload in requests:
        written = cast(dict[str, object], payload["entry"])
        data = cast(dict[str, object], written["data"])
        tabs = cast(list[dict[str, object]], data["tabs"])
        items = cast(list[dict[str, object]], tabs[0]["items"])
        for item in items:
            if hidden is None:
                assert "hiddenOnMobile" not in item
            else:
                assert item["hiddenOnMobile"] is hidden
        members = [
            member
            for item in items
            for member in cast(list[dict[str, object]], cast(dict[str, object], item["data"]).get("group", []))
        ]
        enabled = next(member for member in members if member["id"] == "enabled")
        source = cast(dict[str, object], enabled["source"])
        assert source["elementType"] == "switch"
        assert source["defaultValue"] == ("true" if payload is requests[0] else "false")
        assert enabled["defaults"] == {"enabled": source["defaultValue"]}


@pytest.mark.parametrize("value", [None, "true", 1])
def test_switch_requires_a_boolean_default(value: object) -> None:
    with pytest.raises(dl.DataLensValidationError, match="switch selector requires a bool default_value"):
        dl.DashboardTab("Tab").add_selector(param_name="enabled", element="switch", default_value=cast(bool, value))


def test_mobile_visibility_is_validated_before_tab_mutation() -> None:
    tab = dl.DashboardTab("Tab")
    with pytest.raises(dl.DataLensValidationError, match="hidden_on_mobile must be a bool"):
        tab.add_text("Text", hidden_on_mobile=cast(bool, 1))
    assert tab._pending_snapshot() == ()

    with pytest.raises(dl.DataLensValidationError, match="hidden_on_mobile belongs to add_group_selector"):
        tab.add_selector(param_name="flag", element="switch", default_value=False, group="flags", hidden_on_mobile=True)
    assert tab._unclaimed_group_names() == ()
