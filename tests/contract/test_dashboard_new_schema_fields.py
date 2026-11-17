from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl


@pytest.mark.parametrize("client_type", [dl.DataLensClientEnterprise, dl.DataLensClientYC])
def test_existing_mobile_visibility_and_switch_survive_typed_update(
    client_type: type[dl.DataLensClientEnterprise] | type[dl.DataLensClientYC],
) -> None:
    entry = cast(dict[str, object], json.loads((Path(__file__).parent / "fixtures/dashboards/simple.json").read_text()))
    data = cast(dict[str, object], entry["data"])
    tab = cast(list[dict[str, object]], data["tabs"])[0]
    items = cast(list[dict[str, object]], tab["items"])
    items[0]["hiddenOnMobile"] = True
    items.append(
        {
            "id": "enabled",
            "type": "control",
            "namespace": "default",
            "hiddenOnMobile": True,
            "defaults": {"enabled": "true"},
            "data": {
                "title": "Enabled",
                "sourceType": "manual",
                "source": {"elementType": "switch", "fieldName": "enabled", "defaultValue": "true"},
            },
        }
    )
    cast(list[dict[str, object]], tab["layout"]).append({"i": "enabled", "x": 0, "y": 16, "w": 36, "h": 2})
    requests: list[httpx.Request] = []
    written_entries: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/rpc/getDashboard":
            return httpx.Response(200, json={"entry": entry})
        assert request.url.path == "/rpc/updateDashboard"
        payload = cast(dict[str, object], json.loads(request.content))
        written = cast(dict[str, object], payload["entry"])
        written_entries.append(written)
        return httpx.Response(200, json={"entry": {**entry, **written}})

    with client_type(auth=None, base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        dashboard = client.get.dashboard(by_id=cast(str, entry["entryId"]))
        assert dashboard.tabs[0].items[0].raw["hiddenOnMobile"] is True
        updated = (
            dashboard.update.add_text("Added", tab="tab_1", item_id="added", at=(0, 18, 36, 2))
            .update_selector(item_id="enabled", default_value=False)
            .execute(publish=False)
        )

    assert [request.url.path for request in requests] == ["/rpc/getDashboard", "/rpc/updateDashboard"]
    written_data = cast(dict[str, object], written_entries[0]["data"])
    written_tab = cast(list[dict[str, object]], written_data["tabs"])[0]
    written_items = cast(list[dict[str, object]], written_tab["items"])
    assert written_items[:3] == items[:3]
    switch = next(item for item in written_items if item["id"] == "enabled")
    assert switch["hiddenOnMobile"] is True
    assert switch["defaults"] == {"enabled": "false"}
    switch_data = cast(dict[str, object], switch["data"])
    assert switch_data["source"] == {"elementType": "switch", "fieldName": "enabled", "defaultValue": "false"}
    assert "hiddenOnMobile" not in next(item for item in written_items if item["id"] == "added")
    assert updated.data == written_data
    assert items[-1]["defaults"] == {"enabled": "true"}
