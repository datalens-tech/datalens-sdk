from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_state import DashboardStateConverter
from datalens_sdk.domain.dashboard_state import DashboardState


def _from_json(dashboard: dl.Dashboard, data: Mapping[str, object] | None, **kwargs: Any) -> DashboardState:
    return DashboardState.from_data(dashboard, DashboardStateConverter.to_domain(data), raw=data or {}, **kwargs)


WIRE_TYPES = {"wiz1": "d3_wizard_node", "ql1": "d3_ql_node", "ed1": "advanced-chart_node", "ed2": "advanced-chart_node"}
DATASET_FIELDS = {
    "ds1": [{"guid": "guid-region", "title": "Region", "calc_mode": "direct", "type": "DIMENSION"}],
    "ds2": [{"guid": "guid-city", "title": "City", "calc_mode": "direct", "type": "DIMENSION"}],
}


def _wizard(chart_id: str) -> dict[str, object]:
    return {
        "entry": {
            "createdAt": "2026-01-01T00:00:00.000Z",
            "createdBy": "user-1",
            "version": 1,
            "entryId": chart_id,
            "hidden": False,
            "key": f"/Charts/{chart_id}",
            "meta": {},
            "public": False,
            "publishedId": "r1",
            "revId": "r1",
            "savedId": "r1",
            "scope": "widget",
            "tenantId": "tenant-1",
            "type": "d3_wizard_node",
            "updatedAt": "2026-01-02T00:00:00.000Z",
            "updatedBy": "user-1",
            "data": {
                "sources": {"datasetsIds": ["ds1", "ds2"]},
                "visualization": {"type": "line", "x": {"items": []}},
            },
            "workbookId": None,
        },
        "isFavorite": False,
        "permissions": {"admin": True, "edit": True, "execute": True, "read": True},
    }


def _ql(chart_id: str) -> dict[str, object]:
    params = [
        {"name": "interval", "type": "date-interval", "defaultValue": {"from": "a", "to": "b"}},
        {"name": "segment", "type": "string", "defaultValue": ""},
    ]
    return {
        "entryId": chart_id,
        "key": f"/Charts/{chart_id}",
        "type": "d3_ql_node",
        "data": {"chartType": "sql", "type": "ql", "version": "7", "queryValue": "SELECT 1", "params": params},
    }


def _editor(chart_id: str) -> dict[str, object]:
    return {
        "entryId": chart_id,
        "key": f"/Charts/{chart_id}",
        "type": "advanced-chart_node",
        "data": {"sources": "", "params": "", "controls": "", "meta": "", "prepare": ""},
    }


class ChartsTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = cast(dict[str, object], json.loads(request.content))
        path = request.url.path
        self.requests.append((path, body))
        if path == "/rpc/getEntries":
            ids = cast(list[str], body["ids"])
            entries = [
                {"entryId": _, "scope": "widget", "type": WIRE_TYPES[_], "key": f"/Charts/{_}"}
                for _ in ids
                if _ in WIRE_TYPES
            ]
            return httpx.Response(200, json={"entries": entries})
        if path == "/rpc/getWizardChart":
            return httpx.Response(200, json=_wizard(cast(str, body["chartId"])))
        if path == "/rpc/getQLChart":
            return httpx.Response(200, json=_ql(cast(str, body["chartId"])))
        if path == "/rpc/getEditorChart":
            return httpx.Response(200, json=_editor(cast(str, body["chartId"])))
        if path == "/rpc/getDataset":
            dataset_id = cast(str, body["datasetId"])
            dataset = {"description": "", "sources": [], "result_schema": DATASET_FIELDS[dataset_id]}
            return httpx.Response(200, json={"id": dataset_id, "name": dataset_id, "dataset": dataset})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": path})

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]


def _selector(
    item_id: str, source: dict[str, object], source_type: str, defaults: dict[str, object]
) -> dict[str, object]:
    return {
        "data": {"source": {"elementType": "select", **source}, "sourceType": source_type, "title": item_id},
        "defaults": defaults,
        "id": item_id,
        "namespace": "default",
        "type": "control",
    }


def _widget(item_id: str, chart_id: str, params: dict[str, object] | None = None) -> dict[str, object]:
    tabs = [{"chartId": chart_id, "id": f"{item_id}-t", "params": params or {}}]
    return {"data": {"tabs": tabs}, "id": item_id, "namespace": "default", "type": "widget"}


def _dashboard_data() -> dict[str, object]:
    items = [
        _selector("C", {"datasetFieldId": "guid-region", "datasetId": "ds1"}, "dataset", {"guid-region": ""}),
        _selector("M", {"fieldName": "Region"}, "manual", {"Region": ""}),
        _selector("Q", {"fieldName": "interval_from"}, "manual", {"interval_from": ""}),
        _selector("QI", {"fieldName": "interval"}, "manual", {"interval": ""}),
        _selector("S2", {"datasetFieldId": "guid-region", "datasetId": "ds2"}, "dataset", {"guid-region": ""}),
        _widget("WZ", "wiz1"),
        _widget("WZ2", "wiz1"),
        _widget("QL", "ql1"),
        _widget("ED", "ed1", {"guid-region": ""}),
        _widget("ED2", "ed2"),
    ]
    return {"tabs": [{"id": "T", "title": "Main", "items": items, "connections": [], "aliases": {}}]}


def _state(queue_ids: list[str], params: dict[str, dict[str, object]]) -> tuple[DashboardState, ChartsTransport]:
    transport = ChartsTransport()
    client = dl.DataLensClientYC(
        auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(transport.handler)
    )
    dashboard = dl.Dashboard(id="dash", data=_dashboard_data(), rev_id="rev", _operations=client._dashboard_service)
    data: dict[str, object] = {item_id: {"params": params[item_id]} for item_id in queue_ids}
    data["__meta__"] = {"queue": [{"id": _} for _ in queue_ids], "version": 2}
    return _from_json(dashboard, data, tab="T"), transport


def _summary(state: DashboardState, **kwargs: object) -> list[tuple[str, str | None, tuple[str, ...], str, str | None]]:
    return [
        (_.selection.item_id, _.receiver.id, _.params, _.certainty, _.matched_by)
        for _ in state.effects(resolve_charts=True, **kwargs)  # type: ignore[arg-type]
    ]


def test_dataset_selector_matches_wizard_by_guid_across_datasets_and_selectors_by_defaults() -> None:
    state, transport = _state(["C"], {"C": {"guid-region": ["EU"]}})

    assert _summary(state) == [
        ("C", "S2", ("guid-region",), "exact", None),
        ("C", "WZ", ("guid-region",), "exact", "guid"),
        ("C", "WZ2", ("guid-region",), "exact", "guid"),
        ("C", "ED", ("guid-region",), "declared", None),
        ("C", "ED2", ("guid-region",), "unknown", None),
    ]
    assert transport.paths().count("/rpc/getDataset") == 2


def test_manual_selector_matches_wizard_field_by_title() -> None:
    state, _ = _state(["M"], {"M": {"Region": ["EU"]}})

    assert ("M", "WZ", ("Region",), "exact", "title") in _summary(state)


def test_ql_interval_parameter_is_exact_and_its_bounds_are_declared() -> None:
    state, _ = _state(["QI"], {"QI": {"interval": "__interval_2026-01-01_2026-01-31"}})

    assert ("QI", "QL", ("interval",), "exact", None) in _summary(state)


def test_chart_missing_from_get_entries_is_unknown_and_not_read() -> None:
    data = _dashboard_data()
    cast(list[object], cast(list[dict[str, object]], data["tabs"])[0]["items"]).append(_widget("GONE", "missing1"))
    transport = ChartsTransport()
    client = dl.DataLensClientYC(
        auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(transport.handler)
    )
    dashboard = dl.Dashboard(id="dash", data=data, rev_id="rev", _operations=client._dashboard_service)
    raw = {"Q": {"params": {"interval_from": "x"}}, "__meta__": {"queue": [{"id": "Q"}], "version": 2}}
    state = _from_json(dashboard, raw, tab="T")

    summary = _summary(state, items=["GONE"])

    assert summary == [("Q", "GONE", ("interval_from",), "unknown", None)]
    assert transport.paths() == ["/rpc/getEntries"]


def test_ql_interval_bound_is_declared_not_exact() -> None:
    state, _ = _state(["Q"], {"Q": {"interval_from": "__relative_-7d"}})

    summary = _summary(state)

    assert ("Q", "QL", ("interval_from",), "declared", None) in summary
    assert not any(receiver == "WZ" for _, receiver, *_rest in summary)


def test_editor_chart_without_declared_params_is_unknown() -> None:
    state, _ = _state(["Q"], {"Q": {"interval_from": "x"}})

    summary = _summary(state)

    assert ("Q", "ED2", ("interval_from",), "unknown", None) in summary
    assert not any(receiver == "ED" for _, receiver, *_rest in summary)


def test_each_chart_and_dataset_is_read_once() -> None:
    state, transport = _state(["C", "M"], {"C": {"guid-region": ["EU"]}, "M": {"Region": ["EU"]}})

    state.effects(resolve_charts=True)

    assert transport.paths().count("/rpc/getEntries") == 1
    assert transport.paths().count("/rpc/getWizardChart") == 1
    assert transport.paths().count("/rpc/getQLChart") == 1
    assert transport.paths().count("/rpc/getEditorChart") == 2
    assert sorted(str(body["datasetId"]) for path, body in transport.requests if path == "/rpc/getDataset") == [
        "ds1",
        "ds2",
    ]
    assert next(body for path, body in transport.requests if path == "/rpc/getEntries")["ids"] == [
        "wiz1",
        "ql1",
        "ed1",
        "ed2",
    ]


def test_items_limit_loaded_charts() -> None:
    state, transport = _state(["Q"], {"Q": {"interval_from": "x"}})

    assert _summary(state, items=["QL"]) == [("Q", "QL", ("interval_from",), "declared", None)]
    assert transport.paths() == ["/rpc/getEntries", "/rpc/getQLChart"]


def test_without_resolve_charts_no_http_is_made() -> None:
    state, transport = _state(["C"], {"C": {"guid-region": ["EU"]}})

    effects = state.effects()

    assert {_.certainty for _ in effects} == {"received"}
    assert transport.requests == []


def test_resolve_charts_requires_bound_dashboard() -> None:
    dashboard = dl.Dashboard(id="dash", data=_dashboard_data(), rev_id="rev")
    data = {"C": {"params": {"guid-region": ["EU"]}}, "__meta__": {"queue": [{"id": "C"}], "version": 2}}
    state = _from_json(dashboard, data, tab="T")

    with pytest.raises(dl.DataLensConfigurationError, match="not bound"):
        state.effects(resolve_charts=True)
