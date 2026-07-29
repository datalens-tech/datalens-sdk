from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.chart import Chart
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.wizard_chart import WizardChart


class _RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: list(response) if isinstance(response, list) else [response] for path, response in routes.items()
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responses = self._routes.get(request.url.path)
        if not responses:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": f"Unexpected {request.url.path}"})
        response = responses.pop(0)
        response.request = request
        return response

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def _dataset() -> dl.Dataset:
    return dl.Dataset(
        id="ds-1",
        name="sales",
        location=dl.EntryLocation.path("/"),
        result_schema=(
            {"guid": "g_date", "title": "Order Date", "type": "DIMENSION", "data_type": "date", "calc_mode": "direct"},
            {"guid": "g_amt", "title": "Amount", "type": "MEASURE", "data_type": "float", "calc_mode": "direct"},
            {"guid": "g_reg", "title": "Region", "type": "DIMENSION", "data_type": "string", "calc_mode": "direct"},
        ),
    )


def _wizard_response(*, entry_id: str = "chart-1", viz_id: str = "line") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "key": "/Users/me/Sales",
        "type": "d3_wizard_node",
        "data": {
            "visualization": {
                "id": viz_id,
                "placeholders": [
                    {
                        "id": "x",
                        "items": [
                            {"guid": "g_date", "datasetId": "ds-1", "title": "Order Date"},
                            {"guid": "g_reg", "datasetId": "ds-1", "title": "Region"},
                        ],
                    },
                    {"id": "y", "items": [{"guid": "g_amt", "datasetId": "ds-1", "title": "Amount"}]},
                ],
            },
            "datasetsIds": ["ds-1"],
            "filters": [],
        },
    }


def _sparse_wizard_response(*, entry_id: str) -> dict[str, object]:
    return {
        "entryId": entry_id,
        "type": "d3_wizard_node",
        "data": {"visualization": {"id": "line", "placeholders": []}},
    }


def test_wizard_create_payload_carries_field_snapshots() -> None:
    recorder = _RecordedTransport({"/rpc/createWizardChart": httpx.Response(200, json=_wizard_response())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    dataset = _dataset()

    client.create.wizard_chart.line(name="Sales", location=dl.EntryLocation.path("/Users/me")).dataset(dataset).x(
        ["Order Date"]
    ).y(["Amount"]).build()

    payload = recorder.request_json(0)
    data = cast(dict[str, object], payload["data"])
    viz = cast(dict[str, object], data["visualization"])
    placeholders = cast(list[dict[str, object]], viz["placeholders"])
    x_ph = next(p for p in placeholders if p["id"] == "x")
    x_items = cast(list[dict[str, object]], x_ph["items"])
    assert x_items[0]["guid"] == "g_date"
    assert x_items[0]["title"] == "Order Date"
    assert x_items[0]["datasetId"] == "ds-1"


def test_chart_create_accepts_resource_objects_and_equivalent_location_refs() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/createWizardChart": [
                httpx.Response(200, json=_sparse_wizard_response(entry_id=f"wizard-{index}")) for index in range(4)
            ],
            "/rpc/createEditorChart": [
                httpx.Response(
                    200,
                    json={
                        "entryId": f"editor-{index}",
                        "type": "advanced-chart_node",
                        "data": {},
                    },
                )
                for index in range(4)
            ],
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    folder = dl.Folder(
        id="folder-1",
        name="Archive",
        key="/Users/me/Archive",
        installation="yacloud",
    )
    workbook = dl.Workbook(id="workbook-1", name="Sales", installation="yacloud")

    wizard_folder = client.create.wizard_chart.line(name="Chart", location=folder).build()
    wizard_path = client.create.wizard_chart.line(
        name="Chart", location=dl.EntryLocation.path("/Users/me/Archive")
    ).build()
    wizard_workbook = client.create.wizard_chart.line(name="Chart", location=workbook).build()
    wizard_workbook_ref = client.create.wizard_chart.line(
        name="Chart", location=dl.EntryLocation.workbook("workbook-1")
    ).build()

    editor_folder = client.create.editor_chart.advanced_chart(name="Chart", location=folder).build()
    editor_path = client.create.editor_chart.advanced_chart(
        name="Chart", location=dl.EntryLocation.path("/Users/me/Archive")
    ).build()
    editor_workbook = client.create.editor_chart.advanced_chart(name="Chart", location=workbook).build()
    editor_workbook_ref = client.create.editor_chart.advanced_chart(
        name="Chart", location=dl.EntryLocation.workbook("workbook-1")
    ).build()

    wizard_path_payloads = [recorder.request_json(index) for index in (0, 1)]
    wizard_workbook_payloads = [recorder.request_json(index) for index in (2, 3)]
    assert wizard_path_payloads[0] == wizard_path_payloads[1]
    assert wizard_path_payloads[0]["key"] == "/Users/me/Archive/Chart"
    assert "name" not in wizard_path_payloads[0]
    assert wizard_workbook_payloads[0] == wizard_workbook_payloads[1]
    assert wizard_workbook_payloads[0]["name"] == "Chart"
    assert wizard_workbook_payloads[0]["workbookId"] == "workbook-1"
    assert "key" not in wizard_workbook_payloads[0]

    editor_path_payloads = [cast(dict[str, object], recorder.request_json(index)["entry"]) for index in (4, 5)]
    editor_workbook_payloads = [cast(dict[str, object], recorder.request_json(index)["entry"]) for index in (6, 7)]
    assert editor_path_payloads[0] == editor_path_payloads[1]
    assert editor_path_payloads[0]["key"] == "/Users/me/Archive/Chart"
    assert "name" not in editor_path_payloads[0]
    assert editor_workbook_payloads[0] == editor_workbook_payloads[1]
    assert editor_workbook_payloads[0]["name"] == "Chart"
    assert editor_workbook_payloads[0]["workbookId"] == "workbook-1"
    assert "key" not in editor_workbook_payloads[0]

    path_charts: tuple[Chart, ...] = (wizard_folder, wizard_path, editor_folder, editor_path)
    for chart in path_charts:
        assert chart.name == "Chart"
        assert chart.location == dl.EntryLocation.path("/Users/me/Archive")
        assert chart.dir_path == "/Users/me/Archive"
        assert chart.key == "/Users/me/Archive/Chart"
    workbook_charts: tuple[Chart, ...] = (
        wizard_workbook,
        wizard_workbook_ref,
        editor_workbook,
        editor_workbook_ref,
    )
    for chart in workbook_charts:
        assert chart.name == "Chart"
        assert chart.location == dl.EntryLocation.workbook("workbook-1")
        assert chart.workbook_id == "workbook-1"
        assert chart.key is None


def test_chart_create_rejects_unsupported_or_foreign_destinations() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    with pytest.raises(dl.DatalensValidationError, match="Wizard chart creation requires location kind"):
        client.create.wizard_chart.line(name="Chart", location=dl.EntryLocation.collection("collection-1"))
    with pytest.raises(dl.DatalensValidationError, match="Editor chart creation requires location kind"):
        client.create.editor_chart.advanced_chart(name="Chart", location=dl.EntryLocation.collection("collection-1"))
    with pytest.raises(dl.NotSupportedError, match="destination"):
        client.create.wizard_chart.line(
            name="Chart",
            location=dl.Workbook(id="workbook-1", name="Sales", installation="enterprise"),
        )
    with pytest.raises(dl.NotSupportedError, match="destination"):
        client.create.editor_chart.advanced_chart(
            name="Chart",
            location=dl.Folder(
                id="folder-1",
                name="Archive",
                key="/Users/me/Archive",
                installation="enterprise",
            ),
        )


def test_wizard_get_sends_chart_id() -> None:
    recorder = _RecordedTransport({"/rpc/getWizardChart": httpx.Response(200, json=_wizard_response())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")

    assert isinstance(chart, WizardChart)
    assert chart.id == "chart-1"
    assert recorder.request_json(0) == {"chartId": "chart-1"}


def test_wizard_get_sends_branch() -> None:
    recorder = _RecordedTransport({"/rpc/getWizardChart": httpx.Response(200, json=_wizard_response())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    client.get.wizard_chart(by_id="chart-1", branch="published")

    assert recorder.request_json(0) == {"chartId": "chart-1", "branch": "published"}


def test_wizard_get_sends_rev_id_as_camel_case() -> None:
    recorder = _RecordedTransport({"/rpc/getWizardChart": httpx.Response(200, json=_wizard_response())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    client.get.wizard_chart(by_id="chart-1", rev_id="rev-7")

    assert recorder.request_json(0) == {"chartId": "chart-1", "revId": "rev-7"}


def test_wizard_get_rev_id_suppresses_branch_with_warning() -> None:
    recorder = _RecordedTransport({"/rpc/getWizardChart": httpx.Response(200, json=_wizard_response())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    with pytest.warns(UserWarning, match="branch is ignored"):
        client.get.wizard_chart(by_id="chart-1", branch="saved", rev_id="rev-7")

    body = recorder.request_json(0)
    assert body == {"chartId": "chart-1", "revId": "rev-7"}
    assert "branch" not in body


def test_wizard_delete_sends_chart_id() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/deleteWizardChart": httpx.Response(200),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    chart.delete()

    assert recorder.request_json(1) == {"chartId": "chart-1"}


def test_update_from_fetched_chart_sends_mode_and_entry_id() -> None:
    update_response = _wizard_response()
    update_response_data = cast(dict[str, object], update_response["data"])
    viz = cast(dict[str, object], update_response_data["visualization"])
    y_ph = next(p for p in cast(list[dict[str, object]], viz["placeholders"]) if p["id"] == "y")
    y_ph["items"] = [{"guid": "g_reg", "datasetId": "ds-1"}]

    recorder = _RecordedTransport(
        {
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/updateWizardChart": httpx.Response(200, json=update_response),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    updated = chart.update.y(["g_reg"]).mode("save").execute()

    assert isinstance(updated, WizardChart)
    assert recorder.paths() == ["/rpc/getWizardChart", "/rpc/updateWizardChart"]
    update_payload = recorder.request_json(1)
    assert update_payload["entryId"] == "chart-1"
    assert update_payload["mode"] == "save"
    assert update_payload["template"] == "datalens"
    update_data = cast(dict[str, object], update_payload["data"])
    update_viz = cast(dict[str, object], update_data["visualization"])
    y_items = cast(
        list[dict[str, object]],
        next(p for p in cast(list[dict[str, object]], update_viz["placeholders"]) if p["id"] == "y")["items"],
    )
    assert y_items[0]["guid"] == "g_reg"


def test_update_mode_defaults_to_save() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/updateWizardChart": httpx.Response(200, json=_wizard_response()),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    chart.update.x(["g_date"]).execute()

    update_payload = recorder.request_json(1)
    assert update_payload["mode"] == "save"


def test_update_change_visualization_to_changes_viz_id_in_payload() -> None:
    update_response = {
        "entryId": "chart-1",
        "key": "/Users/me/Sales",
        "type": "graph_wizard_node",
        "data": {"visualization": {"id": "bar", "placeholders": []}},
    }
    recorder = _RecordedTransport(
        {
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/updateWizardChart": httpx.Response(200, json=update_response),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    chart.update.change_visualization_to(visualization_id="bar").mode("publish").execute()

    update_payload = recorder.request_json(1)
    update_data = cast(dict[str, object], update_payload["data"])
    update_viz = cast(dict[str, object], update_data["visualization"])
    assert update_viz["id"] == "bar"


def test_update_deep_merge_preserves_untouched_placeholders() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/updateWizardChart": httpx.Response(200, json=_wizard_response()),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    chart.update.y(["g_reg"]).mode("publish").execute()

    update_payload = recorder.request_json(1)
    update_data = cast(dict[str, object], update_payload["data"])
    update_viz = cast(dict[str, object], update_data["visualization"])
    placeholder_ids = [p["id"] for p in cast(list[dict[str, object]], update_viz["placeholders"])]
    assert "x" in placeholder_ids
    x_ph = next(p for p in cast(list[dict[str, object]], update_viz["placeholders"]) if p["id"] == "x")
    x_items = cast(list[dict[str, object]], x_ph["items"])
    assert x_items[0]["guid"] == "g_date"


def test_update_replace_field_via_client_namespace() -> None:
    update_response = _wizard_response()
    update_data = cast(dict[str, object], update_response["data"])
    update_viz = cast(dict[str, object], update_data["visualization"])
    x_ph = next(p for p in cast(list[dict[str, object]], update_viz["placeholders"]) if p["id"] == "x")
    x_ph["items"] = [{"guid": "g_new", "datasetId": "ds-1"}]

    recorder = _RecordedTransport(
        {
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/updateWizardChart": httpx.Response(200, json=update_response),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    replacement = DatasetField(
        guid="g_new",
        title="New date",
        name="New date",
        calc_mode="direct",
        data_type="date",
        type="DIMENSION",
        dataset_id="ds-1",
    )
    chart.update.replace_field("g_date", replacement).mode("publish").execute()

    update_payload = recorder.request_json(1)
    update_data = cast(dict[str, object], update_payload["data"])
    update_viz = cast(dict[str, object], update_data["visualization"])
    x_items = cast(
        list[dict[str, object]],
        next(p for p in cast(list[dict[str, object]], update_viz["placeholders"]) if p["id"] == "x")["items"],
    )
    assert x_items[0]["guid"] == "g_new"


def test_update_invalid_mode_raises() -> None:
    recorder = _RecordedTransport({"/rpc/getWizardChart": httpx.Response(200, json=_wizard_response())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.wizard_chart(by_id="chart-1")
    with pytest.raises(dl.DatalensValidationError, match="mode must be"):
        chart.update.mode("invalid")  # type: ignore[arg-type]


def test_update_without_id_raises() -> None:
    chart = WizardChart(id=None, installation="yacloud")
    with pytest.raises(dl.DatalensValidationError, match="Cannot update a chart without an id"):
        _ = chart.update


def _ql_response(*, entry_id: str = "chart-1", wire_type: str = "d3_ql_node") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "key": "/dir/QL",
        "type": wire_type,
        "data": {"chartType": "sql", "type": "ql", "version": "7", "queryValue": "SELECT 1", "params": []},
    }


def _editor_response(*, entry_id: str = "chart-1", wire_type: str = "advanced-chart_node") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "key": "/dir/Editor",
        "type": wire_type,
        "data": {"sources": "", "params": "", "controls": "", "meta": "", "prepare": ""},
    }


def _entries_response(wire_type: str, *, entry_id: str = "chart-1") -> dict[str, object]:
    return {"entries": [{"entryId": entry_id, "scope": "widget", "type": wire_type}]}


def test_base_chart_is_abstract() -> None:
    with pytest.raises(TypeError):
        Chart(id="chart-1")  # type: ignore[abstract]


def test_get_chart_dispatches_wizard_and_deletes_via_wizard_route() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getEntries": httpx.Response(200, json=_entries_response("d3_wizard_node")),
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_response()),
            "/rpc/deleteWizardChart": httpx.Response(200),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.chart(by_id="chart-1")
    assert isinstance(chart, WizardChart)
    chart.delete()

    assert recorder.paths() == ["/rpc/getEntries", "/rpc/getWizardChart", "/rpc/deleteWizardChart"]
    assert recorder.request_json(2) == {"chartId": "chart-1"}


def test_get_chart_dispatches_editor_and_deletes_via_editor_route() -> None:
    recorder = _RecordedTransport(
        {
            "/rpc/getEntries": httpx.Response(200, json=_entries_response("advanced-chart_node")),
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_response()),
            "/rpc/deleteEditorChart": httpx.Response(200),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    chart = client.get.chart(by_id="chart-1")
    assert isinstance(chart, EditorChart)
    chart.delete()

    assert recorder.paths() == ["/rpc/getEntries", "/rpc/getEditorChart", "/rpc/deleteEditorChart"]
    assert recorder.request_json(2) == {"chartId": "chart-1"}


def test_get_chart_routes_d3_ql_node_to_ql_chart() -> None:
    """QL charts (``d3_ql_node``) route to the QL endpoint and return a QLChart."""
    recorder = _RecordedTransport(
        {
            "/rpc/getEntries": httpx.Response(200, json=_entries_response("d3_ql_node")),
            "/rpc/getQLChart": httpx.Response(200, json=_ql_response()),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))
    chart = client.get.chart(by_id="chart-1")
    assert chart.category == "ql"
    assert recorder.requests[-1].url.path == "/rpc/getQLChart"
