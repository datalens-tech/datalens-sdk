"""End-to-end D5 scenario: create with auto-cursor + Layout + pin, then update
with layout ops + compaction (epic acceptance smoke)."""

from __future__ import annotations

from typing import cast

from datalens_sdk import DashboardCreate, DashboardTab, EntryLocation, Layout
from datalens_sdk.converter.dashboard import DashboardConverter
from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard


def _payload_data(builder: DashboardCreate) -> dict[str, object]:
    entry = cast("dict[str, object]", DashboardConverter.from_domain_create(builder.to_spec()).to_payload()["entry"])
    return cast("dict[str, object]", entry["data"])


def _layout(data: dict[str, object], tab_index: int = 0) -> dict[str, tuple[int, int, int, int, str | None]]:
    tab = cast("list[dict[str, object]]", data["tabs"])[tab_index]
    out: dict[str, tuple[int, int, int, int, str | None]] = {}
    for e in cast("list[dict[str, object]]", tab["layout"]):
        parent = e.get("parent")
        out[cast(str, e["i"])] = (
            cast(int, e["x"]),
            cast(int, e["y"]),
            cast(int, e["w"]),
            cast(int, e["h"]),
            parent if isinstance(parent, str) else None,
        )
    return out


def test_create_auto_cursor_with_pin_and_layout_row() -> None:
    tab = (
        DashboardTab("Overview")
        .add_title("Sales", item_id="hdr", pinned=True)  # pinned header, auto in its group
        .add_chart("ch-a", title="A", item_id="a")  # auto default flow
        .add_chart("ch-b", title="B", item_id="b")
        .add_chart("ch-c", title="C", item_id="c")
        .apply_layout(Layout.row("a", "b", "c", y=2, h=14))  # arrange the three charts in a row
    )
    builder = DashboardCreate(installation="yacloud", name="D", location=EntryLocation.path("/Users/me"))
    layout = _layout(_payload_data(builder.add_tab(tab)))

    assert layout["hdr"] == (0, 0, 36, 2, "__fixGCont")  # pinned, own group cursor
    assert layout["a"] == (0, 2, 12, 14, None)  # Layout.row overrides the auto placements
    assert layout["b"] == (12, 2, 12, 14, None)
    assert layout["c"] == (24, 2, 12, 14, None)


def test_update_move_pin_compact_pipeline() -> None:
    # a dashboard with a vertical gap and two stacked charts
    data: dict[str, object] = {
        "counter": 1,
        "salt": "s",
        "settings": {},
        "tabs": [
            {
                "id": "t1",
                "title": "T",
                "connections": [],
                "aliases": {"default": []},
                "items": [
                    {
                        "id": "a",
                        "type": "widget",
                        "data": {"tabs": [{"id": "wta", "chartId": "c1", "isDefault": True}]},
                    },
                    {
                        "id": "b",
                        "type": "widget",
                        "data": {"tabs": [{"id": "wtb", "chartId": "c2", "isDefault": True}]},
                    },
                ],
                "layout": [
                    {"i": "a", "x": 0, "y": 0, "w": 18, "h": 10},
                    {"i": "b", "x": 0, "y": 20, "w": 18, "h": 10},  # interior gap below a
                ],
            }
        ],
    }
    dashboard = Dashboard(id="d", installation="yacloud", data=data, raw={"entryId": "d", "data": data})

    applied = _apply_update(dashboard.update.move_item("a", x=0, y=0).resize_item("b", w=36).compact_layout().to_spec())
    layout = _layout(applied)
    assert layout["a"] == (0, 0, 18, 10, None)
    assert layout["b"] == (0, 10, 36, 10, None)  # widened and compacted up under a


def test_validate_flags_reflow_then_compact_clears_it() -> None:
    data: dict[str, object] = {
        "counter": 1,
        "salt": "s",
        "settings": {},
        "tabs": [
            {
                "id": "t1",
                "title": "T",
                "connections": [],
                "aliases": {"default": []},
                "items": [{"id": "a", "type": "text", "data": {"text": "x"}}],
                "layout": [{"i": "a", "x": 0, "y": 6, "w": 12, "h": 4}],  # gap above -> reflow
            }
        ],
    }
    dashboard = Dashboard(id="d", installation="yacloud", data=data, raw={"entryId": "d", "data": data})
    assert any(issue.kind == "layout_reflow" for issue in dashboard.validate())

    compacted = _apply_update(dashboard.update.compact_layout().to_spec())
    settled = Dashboard(id="d", installation="yacloud", data=compacted, raw={})
    assert not any(issue.kind == "layout_reflow" for issue in settled.validate())
