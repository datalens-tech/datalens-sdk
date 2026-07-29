"""Golden snapshot of a full multi-op update request payload (D3.5).

One scripted scenario over the live ``group_control_manual`` fixture
exercises every operation family; the FULL /rpc/updateDashboard request is
pinned byte-for-byte. Only the REQUEST is golden: the server normalizes its
responses, so read-style roundtrip assertions do not apply here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import datalens_sdk as dl
from datalens_sdk.converter.dashboard import DashboardConverter
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_types import REMOVE_PARAM

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_GOLDEN_PATH = _FIXTURES_DIR / "dashboard_update" / "full_scenario_payload.json"


def _source_dashboard() -> Dashboard:
    entry: object = json.loads((_FIXTURES_DIR / "dashboards" / "group_control_manual.json").read_text())
    assert isinstance(entry, dict)
    typed = cast(dict[str, object], entry)
    return Dashboard(
        id=cast(str, typed["entryId"]),
        installation="yacloud",
        data=cast(dict[str, object], typed["data"]),
        raw=typed,
    )


def full_scenario_builder() -> dl.DashboardUpdate:
    update = _source_dashboard().update
    new_tab = (
        dl.DashboardTab("Added by SDK", hidden=True)
        .add_title("Section", at=(0, 0, 36, 2), size="l", show_in_toc=True)
        .add_chart("chart-added-1", title="Added chart", at=(0, 2, 18, 8), item_id="added_el")
    )
    update.update_tab("Title 22", title="Renamed 22")
    update.hide_tab("Title 23")
    update.replace_chart(item_id="Lp", chart="chart-replaced")
    # explicit alias removal: the cascade below would NOT touch this group —
    # its fields are widget-dataset fields no removal takes a user from
    # (diff-based self-repair semantics, P021)
    update.remove_alias("date", "date_1jp0")
    update.remove_item("gR")  # multi-tab widget: cascades layout + chart-tab-id connections + aliases
    update.set_chart_params(item_id="1l", params={"region": "north", "cities": ["a", "b"]})
    update.remove_connection(from_item="no", to_item="rB")
    update.add_chart(
        "chart-into-existing",
        title="Into existing",
        tab="Renamed 22",
        at=(0, 60, 12, 6),
        background="#11223344",
        pinned=True,
    )
    update.add_tab(new_tab)
    update.settings(hide_tabs=True, autoupdate_interval=None, max_concurrent_requests=4)
    update.global_params({"season": ["winter", "spring"], "stale_param": REMOVE_PARAM})
    update.description("Updated by the golden scenario")
    update.access_description("")  # clearing: the key is removed (P0.1)
    update.support_description("New support text")
    return update


def test_full_scenario_payload_matches_golden() -> None:
    update = full_scenario_builder()
    payload = DashboardConverter.from_domain_update(update.to_spec(), publish=True).to_payload()
    golden: object = json.loads(_GOLDEN_PATH.read_text())
    assert payload == golden


def test_full_scenario_is_repeatable() -> None:
    update = full_scenario_builder()
    first = DashboardConverter.from_domain_update(update.to_spec(), publish=False).to_payload()
    second = DashboardConverter.from_domain_update(update.to_spec(), publish=False).to_payload()
    assert first == second
    assert first["mode"] == "save"
