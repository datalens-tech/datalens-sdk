"""Golden snapshot of the full dashboard-create scenario payload (D2.4/D2.5).

The fixture pins the exact wire document the converter assembles for a
dashboard exercising every D2 builder feature: two tabs, a single chart
widget, a multi-tab chart group, texts, titles, a section divider, an image,
pinning, styling, all three description channels, and the canonical settings
with required-nullable nulls (``meta``, ``autoupdateInterval``,
``maxConcurrentRequests``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from datalens_sdk import DashboardChartTab, DashboardCreate, DashboardTab, EntryLocation, ThemedColor
from datalens_sdk.converter.dashboard import DashboardConverter

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "dashboard_create" / "full_scenario_payload.json"


def full_scenario_builder() -> DashboardCreate:
    overview = (
        DashboardTab("Overview")
        .add_title("Sales overview", at=(0, 0, 36, 2), show_in_toc=True, text_color="#027bfeb3")
        .add_chart(
            "ch-single",
            title="Sales dynamics",
            at=(0, 2, 24, 12),
            params={"region": "RU"},
            description="Weekly numbers",
        )
        .add_chart_group(
            [
                DashboardChartTab(chart="ch-plan", title="Plan"),
                DashboardChartTab(
                    chart="ch-fact",
                    title="Fact",
                    default=True,
                    auto_height=True,
                    params={"mode": ["fact", "raw"]},
                ),
            ],
            at=(24, 2, 12, 12),
            show_title=False,
            background=ThemedColor(light="#ffffff", dark="#000000"),
        )
        .add_text("**Notes** for the overview", at=(0, 14, 36, 4), background="#E0F7FA")
    )
    details = (
        DashboardTab("Details")
        .add_section_divider("Raw data", at=(0, 0, 36, 2))
        .add_image(src="https://img.test/logo.png", alt="Logo", at=(0, 2, 12, 6), pinned=True)
    )
    builder = DashboardCreate(
        installation="yacloud",
        name="Snapshot Dash",
        location=EntryLocation.path("/Users/me"),
    )
    (
        builder.add_tab(overview)
        .add_tab(details)
        .description("Snapshot dashboard")
        .access_description("Ask BI team")
        .support_description("Contact support")
        .settings(hide_tabs=True)
    )
    return builder


def test_full_scenario_payload_matches_golden_snapshot() -> None:
    payload = DashboardConverter.from_domain_create(full_scenario_builder().to_spec()).to_payload()

    golden = json.loads(_FIXTURE_PATH.read_text())
    assert payload == golden


def test_golden_snapshot_pins_required_nullable_nulls() -> None:
    golden = cast(dict[str, object], json.loads(_FIXTURE_PATH.read_text()))
    entry = cast(dict[str, object], golden["entry"])
    data = cast(dict[str, object], entry["data"])
    settings = cast(dict[str, object], data["settings"])

    assert "meta" in entry
    assert entry["meta"] is None
    assert "autoupdateInterval" in settings
    assert settings["autoupdateInterval"] is None
    assert "maxConcurrentRequests" in settings
    assert settings["maxConcurrentRequests"] is None
