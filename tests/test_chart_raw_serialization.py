from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import partial
import inspect
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.raw_resource import (
    RawEditorChartCreate,
    RawEditorChartReplace,
    RawQLChartCreate,
    RawQLChartReplace,
    RawWizardChartCreate,
    RawWizardChartReplace,
)
from datalens_sdk.errors import DatalensValidationError, NotSupportedError
from datalens_sdk.serialization import artifacts as artifact_serialization
from datalens_sdk.serialization.json_types import normalize_json_object


class RecordedTransport:
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
        value: object = json.loads(self.requests[index].content)
        assert isinstance(value, dict)
        return cast(dict[str, object], value)


def _wizard_snapshot(
    *,
    chart_id: str = "wizard-source",
    wire_type: str = "d3_wizard_node",
) -> dict[str, object]:
    return {
        "entryId": chart_id,
        "type": wire_type,
        "key": "/source/Wizard Source",
        "revId": "source-revision",
        "permissions": {"edit": True},
        "futureOuter": {"mustNotBeWritten": True},
        "annotation": {"description": "Wizard source"},
        "data": {
            "datasetsIds": ["dataset-1"],
            "visualization": {
                "id": "line",
                "placeholders": [
                    {"id": "x", "items": []},
                    {"id": "y", "items": [{"guid": "measure-1"}]},
                ],
            },
            "futureData": {"nested": {"preserved": True}},
        },
    }


def _ql_snapshot(
    *,
    chart_id: str = "ql-source",
    wire_type: str = "d3_ql_node",
) -> dict[str, object]:
    return {
        "entryId": chart_id,
        "type": wire_type,
        "key": "/source/QL Source",
        "revId": "source-revision",
        "permissions": {"edit": True},
        "futureOuter": {"mustNotBeWritten": True},
        "annotation": {"description": "QL source"},
        "data": {
            "type": "ql",
            "chartType": "sql",
            "version": "7",
            "queryValue": "select 1",
            "params": [],
            "connection": {"entryId": "connection-1", "type": "postgres"},
            "visualization": {
                "id": "line",
                "placeholders": [
                    {"id": "x", "items": []},
                    {"id": "y", "items": []},
                    {"id": "y2", "items": []},
                ],
            },
            "futureData": {"nested": {"preserved": True}},
        },
    }


def _editor_snapshot(
    *,
    chart_id: str = "editor-source",
    wire_type: str = "advanced-chart_node",
) -> dict[str, object]:
    return {
        "entry": {
            "entryId": chart_id,
            "type": wire_type,
            "key": "/source/Editor Source",
            "revId": "source-revision",
            "annotation": {"description": "Editor source"},
            "meta": {"futureMeta": {"preserved": True}},
            "links": {"documentation": "https://example.test"},
            "data": {
                "sources": "module.exports = {source: true};\n",
                "params": "module.exports = {};\n",
                "controls": "module.exports = [];\n",
                "meta": "module.exports = {};\n",
                "prepare": "module.exports = {};\n",
                "futureTab": "module.exports = {future: true};\n",
            },
            "futureEntryField": {"mustNotBeWritten": True},
        },
        "permissions": {"edit": True},
        "futureOuter": {"mustNotBeWritten": True},
    }


def _expected_editor_mutable_entry() -> dict[str, object]:
    entry = cast(dict[str, object], _editor_snapshot()["entry"])
    return {
        "type": "advanced-chart_node",
        "data": entry["data"],
        "annotation": {"description": "Editor source"},
        "meta": {"futureMeta": {"preserved": True}},
        "links": {"documentation": "https://example.test"},
    }


def _raw(value: Mapping[str, object]) -> Mapping[str, dl.JsonValue]:
    return cast(Mapping[str, dl.JsonValue], value)


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


@pytest.mark.parametrize(
    ("get_path", "get_chart", "snapshot", "expected_raw"),
    [
        (
            "/rpc/getWizardChart",
            lambda client: client.get.wizard_chart(by_id="wizard-source"),
            _wizard_snapshot(),
            "root",
        ),
        (
            "/rpc/getEditorChart",
            lambda client: client.get.editor_chart(by_id="editor-source"),
            _editor_snapshot(),
            "entry",
        ),
        ("/rpc/getQLChart", lambda client: client.get.ql_chart(by_id="ql-source"), _ql_snapshot(), "root"),
    ],
)
def test_chart_get_captures_owned_full_response_snapshot(
    get_path: str,
    get_chart: Callable[[dl.DataLensClientYC], dl.Chart],
    snapshot: dict[str, object],
    expected_raw: str,
) -> None:
    expected = json.loads(json.dumps(snapshot))
    recorder = RecordedTransport({get_path: httpx.Response(200, json=snapshot)})

    chart = get_chart(_client(recorder))

    assert chart.response_snapshot == expected
    if expected_raw == "entry":
        assert chart.raw == cast(dict[str, object], expected)["entry"]
    else:
        assert chart.raw == expected
    snapshot["futureOuter"] = {"mustNotBeWritten": False}
    if "futureOuter" in chart.raw:
        cast(dict[str, object], chart.raw)["futureOuter"] = {"mustNotBeWritten": False}
    else:
        cast(dict[str, object], chart.raw)["futureEntryField"] = {"mustNotBeWritten": False}
    assert chart.response_snapshot == expected


@pytest.mark.parametrize(
    ("chart", "directory_name"),
    [
        (
            dl.WizardChart(
                id="wizard-source",
                name="Wizard/Source",
                wire_type="d3_wizard_node",
                response_snapshot=_raw(_wizard_snapshot()),
            ),
            "Wizard_Source [wizard-source]",
        ),
        (
            dl.EditorChart(
                id="editor-source",
                name="Editor/Source",
                wire_type="advanced-chart_node",
                response_snapshot=_raw(_editor_snapshot()),
            ),
            "Editor_Source [editor-source]",
        ),
        (
            dl.QLChart(
                id="ql-source",
                name="QL/Source",
                wire_type="d3_ql_node",
                response_snapshot=_raw(_ql_snapshot()),
            ),
            "QL_Source [ql-source]",
        ),
    ],
)
def test_chart_to_file_writes_canonical_full_snapshot(
    tmp_path: Path,
    chart: dl.Chart,
    directory_name: str,
) -> None:
    artifact = chart.to_file(tmp_path)

    assert artifact == tmp_path / directory_name
    assert json.loads((artifact / "chart.json").read_text(encoding="utf-8")) == chart.response_snapshot


def test_editor_split_tabs_is_export_only_and_preserves_main_document(tmp_path: Path) -> None:
    snapshot = _editor_snapshot()
    chart = dl.EditorChart(
        id="editor-source",
        name="Editor Source",
        wire_type="advanced-chart_node",
        response_snapshot=_raw(snapshot),
    )

    artifact = chart.to_file(tmp_path, split_tabs=True)

    assert "split_tabs" in inspect.signature(chart.to_file).parameters
    assert json.loads((artifact / "chart.json").read_text(encoding="utf-8")) == snapshot
    assert (artifact / "Tabs" / "sources.js").read_text(encoding="utf-8") == cast(
        dict[str, object],
        cast(dict[str, object], snapshot["entry"])["data"],
    )["sources"]
    assert (artifact / "Tabs" / "futureTab.js").is_file()


@pytest.mark.parametrize(
    "chart",
    [
        dl.WizardChart(
            id="wizard-source",
            name="Wizard",
            wire_type="d3_wizard_node",
            response_snapshot=_raw(_wizard_snapshot()),
        ),
        dl.QLChart(
            id="ql-source",
            name="QL",
            wire_type="d3_ql_node",
            response_snapshot=_raw(_ql_snapshot()),
        ),
    ],
)
def test_split_tabs_is_not_exposed_by_non_editor_charts(tmp_path: Path, chart: dl.Chart) -> None:
    assert "split_tabs" not in inspect.signature(chart.to_file).parameters
    to_file_with_options = cast(Callable[..., Path], chart.to_file)
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        to_file_with_options(tmp_path, split_tabs=True)
    assert tuple(tmp_path.iterdir()) == ()


def test_raw_wizard_create_and_update_project_only_mutable_content() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createWizardChart": httpx.Response(200, json={"entryId": "wizard-clone"}),
            "/rpc/getWizardChart": httpx.Response(200, json=_wizard_snapshot(chart_id="wizard-target")),
            "/rpc/updateWizardChart": httpx.Response(200, json={"entryId": "wizard-target"}),
        }
    )
    client = _client(recorder)
    create = client.raw.create.wizard_chart(
        response_snapshot=_raw(_wizard_snapshot()),
        name="Wizard Clone",
        location=dl.EntryLocation.path("/target"),
    )
    assert isinstance(create, RawWizardChartCreate)
    created = create.build()
    target = client.get.wizard_chart(by_id="wizard-target")
    replace = client.raw.replace.wizard_chart(
        target=target,
        response_snapshot=_raw(_wizard_snapshot()),
    ).mode("publish")
    assert isinstance(replace, RawWizardChartReplace)
    updated = replace.execute()

    assert created.id == "wizard-clone"
    assert created.wire_type == "d3_wizard_node"
    assert updated.id == "wizard-target"
    create_payload = recorder.request_json(0)
    assert create_payload["template"] == "datalens"
    assert create_payload["key"] == "/target/Wizard Clone"
    assert create_payload["annotation"] == {"description": "Wizard source"}
    assert cast(dict[str, object], create_payload["data"])["futureData"] == {"nested": {"preserved": True}}
    assert not ({"entryId", "revId", "permissions", "futureOuter", "type"} & create_payload.keys())
    update_payload = recorder.request_json(2)
    assert update_payload["entryId"] == "wizard-target"
    assert update_payload["mode"] == "publish"
    assert "revId" not in update_payload
    assert cast(dict[str, object], update_payload["data"])["futureData"] == {"nested": {"preserved": True}}


def test_raw_ql_create_and_update_project_only_mutable_content() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createQLChart": httpx.Response(200, json={"entryId": "ql-clone"}),
            "/rpc/getQLChart": httpx.Response(200, json=_ql_snapshot(chart_id="ql-target")),
            "/rpc/updateQLChart": httpx.Response(200, json={"entryId": "ql-target"}),
        }
    )
    client = _client(recorder)
    create = client.raw.create.ql_chart(
        response_snapshot=_raw(_ql_snapshot()),
        name="QL Clone",
        location=dl.EntryLocation.workbook("workbook-1"),
    )
    assert isinstance(create, RawQLChartCreate)
    created = create.build()
    target = client.get.ql_chart(by_id="ql-target")
    replace = client.raw.replace.ql_chart(
        target=target,
        response_snapshot=_raw(_ql_snapshot()),
    )
    assert isinstance(replace, RawQLChartReplace)
    updated = replace.execute()

    assert created.id == "ql-clone"
    assert created.wire_type == "d3_ql_node"
    assert updated.id == "ql-target"
    create_payload = recorder.request_json(0)
    assert create_payload["template"] == "ql"
    assert create_payload["name"] == "QL Clone"
    assert create_payload["workbookId"] == "workbook-1"
    assert cast(dict[str, object], create_payload["data"])["futureData"] == {"nested": {"preserved": True}}
    assert not ({"entryId", "revId", "permissions", "futureOuter", "type"} & create_payload.keys())
    update_payload = recorder.request_json(2)
    assert update_payload["entryId"] == "ql-target"
    assert update_payload["mode"] == "save"
    assert "revId" not in update_payload


def test_raw_wizard_namespace_defers_captures_inputs_and_repeats_terminal_calls() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createWizardChart": [
                httpx.Response(200, json={"entryId": "wizard-clone-1"}),
                httpx.Response(200, json={"entryId": "wizard-clone-2"}),
            ],
            "/rpc/updateWizardChart": [
                httpx.Response(200, json={"entryId": "wizard-target"}),
                httpx.Response(200, json={"entryId": "wizard-target"}),
            ],
        }
    )
    client = _client(recorder)
    snapshot = _wizard_snapshot()
    target = dl.WizardChart(
        id="wizard-target",
        installation="yacloud",
        name="Wizard Target",
        location=dl.EntryLocation.path("/existing"),
        wire_type="d3_wizard_node",
    )

    create = client.raw.create.wizard_chart(
        response_snapshot=_raw(snapshot),
        name="Wizard Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.wizard_chart(
        target=target,
        response_snapshot=_raw(snapshot),
    ).mode("publish")

    assert isinstance(create, RawWizardChartCreate)
    assert isinstance(replace, RawWizardChartReplace)
    assert recorder.requests == []

    nested = cast(
        dict[str, object],
        cast(dict[str, object], cast(dict[str, object], snapshot["data"])["futureData"])["nested"],
    )
    nested["preserved"] = False
    target.id = "mutated-id"
    target.name = "Mutated"
    target.location = dl.EntryLocation.path("/mutated")
    target.wire_type = "mutated-type"

    assert create.build().id == "wizard-clone-1"
    assert create.build().id == "wizard-clone-2"
    first_updated = replace.execute()
    second_updated = replace.execute()

    assert first_updated.id == second_updated.id == "wizard-target"
    assert first_updated.name == second_updated.name == "Wizard Target"
    assert first_updated.location == second_updated.location == dl.EntryLocation.path("/existing")
    assert first_updated.wire_type == second_updated.wire_type == "d3_wizard_node"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createWizardChart",
        "/rpc/createWizardChart",
        "/rpc/updateWizardChart",
        "/rpc/updateWizardChart",
    ]
    for index in range(4):
        data = cast(dict[str, object], recorder.request_json(index)["data"])
        assert data["futureData"] == {"nested": {"preserved": True}}
    assert recorder.request_json(2)["entryId"] == "wizard-target"
    assert recorder.request_json(2)["mode"] == "publish"


def test_raw_ql_namespace_defers_captures_inputs_and_repeats_terminal_calls() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createQLChart": [
                httpx.Response(200, json={"entryId": "ql-clone-1"}),
                httpx.Response(200, json={"entryId": "ql-clone-2"}),
            ],
            "/rpc/updateQLChart": [
                httpx.Response(200, json={"entryId": "ql-target"}),
                httpx.Response(200, json={"entryId": "ql-target"}),
            ],
        }
    )
    client = _client(recorder)
    snapshot = _ql_snapshot()
    target = dl.QLChart(
        id="ql-target",
        installation="yacloud",
        name="QL Target",
        location=dl.EntryLocation.workbook("workbook-1"),
        wire_type="d3_ql_node",
    )

    create = client.raw.create.ql_chart(
        response_snapshot=_raw(snapshot),
        name="QL Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.ql_chart(
        target=target,
        response_snapshot=_raw(snapshot),
    )

    assert isinstance(create, RawQLChartCreate)
    assert isinstance(replace, RawQLChartReplace)
    assert recorder.requests == []

    nested = cast(
        dict[str, object],
        cast(dict[str, object], cast(dict[str, object], snapshot["data"])["futureData"])["nested"],
    )
    nested["preserved"] = False
    target.id = "mutated-id"
    target.name = "Mutated"
    target.location = dl.EntryLocation.path("/mutated")
    target.wire_type = "mutated-type"

    assert create.build().id == "ql-clone-1"
    assert create.build().id == "ql-clone-2"
    first_updated = replace.execute()
    second_updated = replace.execute()

    assert first_updated.id == second_updated.id == "ql-target"
    assert first_updated.name == second_updated.name == "QL Target"
    assert first_updated.location == second_updated.location == dl.EntryLocation.workbook("workbook-1")
    assert first_updated.wire_type == second_updated.wire_type == "d3_ql_node"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createQLChart",
        "/rpc/createQLChart",
        "/rpc/updateQLChart",
        "/rpc/updateQLChart",
    ]
    for index in range(4):
        data = cast(dict[str, object], recorder.request_json(index)["data"])
        assert data["futureData"] == {"nested": {"preserved": True}}
    assert recorder.request_json(2)["entryId"] == "ql-target"
    assert recorder.request_json(2)["mode"] == "save"


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_chart_builder_owns_prevalidated_snapshot_view(boundary: str) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createWizardChart": httpx.Response(200, json={"entryId": "wizard-clone"}),
            "/rpc/updateWizardChart": httpx.Response(200, json={"entryId": "wizard-target"}),
        }
    )
    snapshot = artifact_serialization.ChartSnapshotView.from_raw(
        _raw(_wizard_snapshot()),
        expected_category="wizard",
    )
    client = _client(recorder)
    terminal: Callable[[], dl.WizardChart]
    if boundary == "create":
        terminal = client.raw.create.wizard_chart(
            response_snapshot=snapshot,
            name="Wizard Clone",
            location=dl.EntryLocation.path("/target"),
        ).build
    else:
        terminal = client.raw.replace.wizard_chart(
            target=dl.WizardChart(id="wizard-target", wire_type="d3_wizard_node"),
            response_snapshot=snapshot,
        ).execute

    future_data = cast(dict[str, dl.JsonValue], snapshot.data["futureData"])
    cast(dict[str, dl.JsonValue], future_data["nested"])["preserved"] = False

    terminal()

    data = cast(dict[str, object], recorder.request_json(0)["data"])
    assert data["futureData"] == {"nested": {"preserved": True}}


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_chart_builder_revalidates_forged_snapshot_view_before_http(boundary: str) -> None:
    recorder = RecordedTransport({})
    snapshot = cast(dict[str, dl.JsonValue], _wizard_snapshot())
    snapshot.pop("entryId")
    data = cast(dict[str, dl.JsonValue], snapshot["data"])
    forged = artifact_serialization.ChartSnapshotView(
        snapshot=snapshot,
        entry=snapshot,
        category="wizard",
        wire_type="d3_wizard_node",
        data=data,
    )
    client = _client(recorder)

    def construct_with_forged_snapshot() -> None:
        if boundary == "create":
            client.raw.create.wizard_chart(
                response_snapshot=forged,
                name="Wizard Clone",
                location=dl.EntryLocation.path("/target"),
            )
        else:
            client.raw.replace.wizard_chart(
                target=dl.WizardChart(id="wizard-target", wire_type="d3_wizard_node"),
                response_snapshot=forged,
            )

    with pytest.raises(DatalensValidationError, match="source id"):
        construct_with_forged_snapshot()

    assert recorder.requests == []


@pytest.mark.parametrize("category", ["wizard", "ql"])
def test_raw_chart_namespaces_direct_and_file_payloads_match(
    tmp_path: Path,
    category: str,
) -> None:
    if category == "wizard":
        snapshot = _raw(_wizard_snapshot())
        source: dl.WizardChart | dl.QLChart = dl.WizardChart(
            id="wizard-source",
            name="Wizard Source",
            wire_type="d3_wizard_node",
            response_snapshot=snapshot,
        )
        create_path = "/rpc/createWizardChart"
        update_path = "/rpc/updateWizardChart"
        create_responses = [httpx.Response(200, json={"entryId": f"wizard-clone-{index}"}) for index in range(2)]
        update_responses = [httpx.Response(200, json={"entryId": "wizard-target"}) for _ in range(2)]
    else:
        snapshot = _raw(_ql_snapshot())
        source = dl.QLChart(
            id="ql-source",
            name="QL Source",
            wire_type="d3_ql_node",
            response_snapshot=snapshot,
        )
        create_path = "/rpc/createQLChart"
        update_path = "/rpc/updateQLChart"
        create_responses = [httpx.Response(200, json={"entryId": f"ql-clone-{index}"}) for index in range(2)]
        update_responses = [httpx.Response(200, json={"entryId": "ql-target"}) for _ in range(2)]
    artifact = source.to_file(tmp_path)
    recorder = RecordedTransport({create_path: create_responses, update_path: update_responses})
    client = _client(recorder)
    location = dl.EntryLocation.path("/target")

    if isinstance(source, dl.WizardChart):
        wizard_target = dl.WizardChart(
            id="wizard-target",
            installation="yacloud",
            name="Wizard Target",
            wire_type="d3_wizard_node",
            _operations=client.chart_ops,
        )
        client.raw.create.wizard_chart(response_snapshot=snapshot, name="Clone", location=location).build()
        client.raw.create.wizard_chart.from_file(artifact, name="Clone", location=location).build()
        client.raw.replace.wizard_chart(
            target=wizard_target,
            response_snapshot=snapshot,
        ).mode("publish").execute()
        client.raw.replace.wizard_chart.from_file(
            artifact,
            target=wizard_target,
        ).mode("publish").execute()
    else:
        ql_target = dl.QLChart(
            id="ql-target",
            installation="yacloud",
            name="QL Target",
            wire_type="d3_ql_node",
            _operations=client.chart_ops,
        )
        client.raw.create.ql_chart(response_snapshot=snapshot, name="Clone", location=location).build()
        client.raw.create.ql_chart.from_file(artifact, name="Clone", location=location).build()
        client.raw.replace.ql_chart(
            target=ql_target,
            response_snapshot=snapshot,
        ).mode("publish").execute()
        client.raw.replace.ql_chart.from_file(
            artifact,
            target=ql_target,
        ).mode("publish").execute()

    assert [request.url.path for request in recorder.requests] == [
        create_path,
        create_path,
        update_path,
        update_path,
    ]
    payloads = [recorder.request_json(index) for index in range(4)]
    assert payloads[0] == payloads[1]
    assert payloads[2] == payloads[3]


def test_raw_editor_create_and_update_preserve_supported_blocks_without_revision() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-clone"}}),
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_snapshot(chart_id="editor-target")),
            "/rpc/updateEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-target"}}),
        }
    )
    client = _client(recorder)
    create = client.raw.create.editor_chart(
        response_snapshot=_raw(_editor_snapshot()),
        name="Editor Clone",
        location=dl.EntryLocation.path("/target"),
    )
    assert isinstance(create, RawEditorChartCreate)
    created = create.build()
    target = client.get.editor_chart(by_id="editor-target")
    replace = client.raw.replace.editor_chart(
        target=target,
        response_snapshot=_raw(_editor_snapshot()),
    )
    assert isinstance(replace, RawEditorChartReplace)
    updated = replace.execute()

    assert created.id == "editor-clone"
    assert created.wire_type == "advanced-chart_node"
    assert updated.id == "editor-target"
    create_payload = recorder.request_json(0)
    create_entry = cast(dict[str, object], create_payload["entry"])
    assert create_entry["type"] == "advanced-chart_node"
    assert create_entry["key"] == "/target/Editor Clone"
    assert create_entry["annotation"] == {"description": "Editor source"}
    assert create_entry["meta"] == {"futureMeta": {"preserved": True}}
    assert create_entry["links"] == {"documentation": "https://example.test"}
    assert cast(dict[str, object], create_entry["data"])["futureTab"] == "module.exports = {future: true};\n"
    assert not ({"entryId", "revId", "futureEntryField"} & create_entry.keys())
    update_payload = recorder.request_json(2)
    update_entry = cast(dict[str, object], update_payload["entry"])
    assert update_payload["mode"] == "save"
    assert update_entry["entryId"] == "editor-target"
    assert update_entry["type"] == "advanced-chart_node"
    assert "revId" not in update_entry


def test_raw_editor_namespace_defers_create_and_replace_until_terminal_call() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-clone"}}),
            "/rpc/updateEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-target"}}),
        }
    )
    client = _client(recorder)
    response_snapshot = _raw(_editor_snapshot())

    create = client.raw.create.editor_chart(
        response_snapshot=response_snapshot,
        name="Editor Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.editor_chart(
        target=dl.EditorChart(
            id="editor-target",
            name="Editor Target",
            wire_type="advanced-chart_node",
        ),
        response_snapshot=response_snapshot,
    )

    assert isinstance(create, RawEditorChartCreate)
    assert isinstance(replace, RawEditorChartReplace)
    assert recorder.requests == []

    snapshot_entry = cast(dict[str, object], response_snapshot["entry"])
    cast(dict[str, object], snapshot_entry["data"])["sources"] = "changed after builder creation"
    created = create.build()
    updated = replace.mode("publish").execute()

    assert created.id == "editor-clone"
    assert updated.id == "editor-target"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createEditorChart",
        "/rpc/updateEditorChart",
    ]
    create_entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    update_payload = recorder.request_json(1)
    update_entry = cast(dict[str, object], update_payload["entry"])
    mutable_entry = _expected_editor_mutable_entry()
    assert create_entry == {**mutable_entry, "key": "/target/Editor Clone"}
    assert update_payload == {
        "entry": {**mutable_entry, "entryId": "editor-target"},
        "mode": "publish",
    }
    assert update_entry["entryId"] == "editor-target"


def test_raw_editor_namespace_file_methods_use_chart_json(tmp_path: Path) -> None:
    source = dl.EditorChart(
        id="editor-source",
        name="Editor Source",
        wire_type="advanced-chart_node",
        response_snapshot=_raw(_editor_snapshot()),
    )
    artifact = source.to_file(tmp_path, split_tabs=True)
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-clone"}}),
            "/rpc/updateEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-target"}}),
        }
    )
    client = _client(recorder)

    create = client.raw.create.editor_chart.from_file(
        artifact,
        name="Editor Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.editor_chart.from_file(
        artifact,
        target=dl.EditorChart(
            id="editor-target",
            name="Editor Target",
            wire_type="advanced-chart_node",
        ),
    )
    assert recorder.requests == []

    create.build()
    replace.execute()

    create_entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    update_payload = recorder.request_json(1)
    update_entry = cast(dict[str, object], update_payload["entry"])
    assert update_payload["mode"] == "save"
    assert create_entry["data"] == update_entry["data"]
    assert create_entry["links"] == update_entry["links"]


@pytest.mark.parametrize("source_kind", ["raw", "file"])
def test_editor_raw_projection_captures_source_at_builder_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_kind: str,
) -> None:
    normalize_calls = 0
    snapshot = _editor_snapshot()
    source_chart = dl.EditorChart(
        id="editor-source",
        name="Editor Source",
        wire_type="advanced-chart_node",
        response_snapshot=_raw(snapshot),
    )
    artifact = source_chart.to_file(tmp_path)

    def counted_normalize(value: object, *, context: str) -> dict[str, dl.JsonValue]:
        nonlocal normalize_calls
        normalize_calls += 1
        return normalize_json_object(value, context=context)

    monkeypatch.setattr(artifact_serialization, "normalize_json_object", counted_normalize)
    recorder = RecordedTransport(
        {"/rpc/createEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-clone"}})}
    )
    factory = _client(recorder).raw.create.editor_chart
    if source_kind == "raw":
        operation = factory(
            response_snapshot=_raw(snapshot),
            name="Editor Clone",
            location=dl.EntryLocation.path("/target"),
        )
    else:
        operation = factory.from_file(
            artifact,
            name="Editor Clone",
            location=dl.EntryLocation.path("/target"),
        )
    operation.build()

    assert normalize_calls == (1 if source_kind == "raw" else 2)


@pytest.mark.parametrize(
    (
        "get_path",
        "update_path",
        "get_chart",
        "source_chart",
        "target_snapshot",
        "update_response",
        "expected_command_type",
    ),
    [
        pytest.param(
            "/rpc/getWizardChart",
            "/rpc/updateWizardChart",
            lambda client: client.get.wizard_chart(by_id="wizard-target"),
            dl.WizardChart(
                id="wizard-source",
                name="Wizard Source",
                wire_type="d3_wizard_node",
                response_snapshot=_raw(_wizard_snapshot()),
            ),
            _wizard_snapshot(chart_id="wizard-target"),
            {"entryId": "wizard-target"},
            RawWizardChartReplace,
            id="wizard",
        ),
        pytest.param(
            "/rpc/getEditorChart",
            "/rpc/updateEditorChart",
            lambda client: client.get.editor_chart(by_id="editor-target"),
            dl.EditorChart(
                id="editor-source",
                name="Editor Source",
                wire_type="advanced-chart_node",
                response_snapshot=_raw(_editor_snapshot()),
            ),
            _editor_snapshot(chart_id="editor-target"),
            {"entry": {"entryId": "editor-target"}},
            RawEditorChartReplace,
            id="editor",
        ),
        pytest.param(
            "/rpc/getQLChart",
            "/rpc/updateQLChart",
            lambda client: client.get.ql_chart(by_id="ql-target"),
            dl.QLChart(
                id="ql-source",
                name="QL Source",
                wire_type="d3_ql_node",
                response_snapshot=_raw(_ql_snapshot()),
            ),
            _ql_snapshot(chart_id="ql-target"),
            {"entryId": "ql-target"},
            RawQLChartReplace,
            id="ql",
        ),
    ],
)
def test_chart_replace_from_file_matches_direct_snapshot_and_reads_artifact_eagerly(
    tmp_path: Path,
    get_path: str,
    update_path: str,
    get_chart: Callable[[dl.DataLensClientYC], dl.WizardChart | dl.EditorChart | dl.QLChart],
    source_chart: dl.WizardChart | dl.EditorChart | dl.QLChart,
    target_snapshot: dict[str, object],
    update_response: dict[str, object],
    expected_command_type: type[RawWizardChartReplace | RawEditorChartReplace | RawQLChartReplace],
) -> None:
    if isinstance(source_chart, dl.EditorChart):
        artifact = source_chart.to_file(tmp_path, split_tabs=True)
    else:
        artifact = source_chart.to_file(tmp_path)
    recorder = RecordedTransport(
        {
            get_path: httpx.Response(200, json=target_snapshot),
            update_path: [
                httpx.Response(200, json=update_response),
                httpx.Response(200, json=update_response),
            ],
        }
    )
    target = get_chart(_client(recorder))
    raw_operation: RawWizardChartReplace | RawEditorChartReplace | RawQLChartReplace
    file_operation: RawWizardChartReplace | RawEditorChartReplace | RawQLChartReplace
    if isinstance(source_chart, dl.EditorChart):
        editor_target = cast(dl.EditorChart, target)
        raw_operation = (
            _client(recorder)
            .raw.replace.editor_chart(
                target=editor_target,
                response_snapshot=source_chart.response_snapshot,
            )
            .mode("publish")
        )
        file_operation = (
            _client(recorder)
            .raw.replace.editor_chart.from_file(
                artifact,
                target=editor_target,
            )
            .mode("publish")
        )
    elif isinstance(source_chart, dl.WizardChart):
        wizard_target = cast(dl.WizardChart, target)
        raw_operation = (
            _client(recorder)
            .raw.replace.wizard_chart(
                target=wizard_target,
                response_snapshot=source_chart.response_snapshot,
            )
            .mode("publish")
        )
        file_operation = (
            _client(recorder)
            .raw.replace.wizard_chart.from_file(
                artifact,
                target=wizard_target,
            )
            .mode("publish")
        )
    else:
        ql_target = cast(dl.QLChart, target)
        raw_operation = (
            _client(recorder)
            .raw.replace.ql_chart(
                target=ql_target,
                response_snapshot=source_chart.response_snapshot,
            )
            .mode("publish")
        )
        file_operation = (
            _client(recorder)
            .raw.replace.ql_chart.from_file(
                artifact,
                target=ql_target,
            )
            .mode("publish")
        )
    assert isinstance(raw_operation, expected_command_type)
    assert isinstance(file_operation, expected_command_type)

    (artifact / "chart.json").write_text("{}", encoding="utf-8")
    requests_before_raw = len(recorder.requests)
    raw_updated = raw_operation.execute()
    assert len(recorder.requests) == requests_before_raw + 1
    raw_payload = recorder.request_json(-1)

    requests_before_file = len(recorder.requests)
    file_updated = file_operation.execute()
    assert len(recorder.requests) == requests_before_file + 1
    file_payload = recorder.request_json(-1)

    assert raw_updated.id == file_updated.id == target.id
    assert raw_updated.name == file_updated.name == target.name
    assert file_payload == raw_payload
    assert [request.url.path for request in recorder.requests] == [get_path, update_path, update_path]
    payload_text = json.dumps(file_payload)
    assert target.id is not None
    assert target.id in payload_text
    assert source_chart.id is not None
    assert source_chart.id not in payload_text
    assert "source-revision" not in payload_text


def test_chart_from_file_reads_main_document_eagerly_and_ignores_changed_sidecar(tmp_path: Path) -> None:
    snapshot = _editor_snapshot()
    chart = dl.EditorChart(
        id="editor-source",
        name="Editor Source",
        wire_type="advanced-chart_node",
        response_snapshot=_raw(snapshot),
    )
    artifact = chart.to_file(tmp_path, split_tabs=True)
    (artifact / "Tabs" / "sources.js").write_text("changed sidecar", encoding="utf-8")
    recorder = RecordedTransport(
        {"/rpc/createEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-clone"}})}
    )
    operation = _client(recorder).raw.create.editor_chart.from_file(
        artifact,
        name="Editor Clone",
        location=dl.EntryLocation.path("/target"),
    )
    stored = cast(dict[str, object], json.loads((artifact / "chart.json").read_text(encoding="utf-8")))
    entry = cast(dict[str, object], stored["entry"])
    cast(dict[str, object], entry["data"])["sources"] = "changed main after command"
    (artifact / "chart.json").write_text(json.dumps(stored), encoding="utf-8")

    operation.build()

    payload_entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    assert cast(dict[str, object], payload_entry["data"])["sources"] == "module.exports = {source: true};\n"


def test_chart_category_mismatch_fails_before_http() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(DatalensValidationError, match="category mismatch"):
        client.raw.create.wizard_chart(
            response_snapshot=_raw(_editor_snapshot()),
            name="Wrong",
            location=dl.EntryLocation.path("/target"),
        )
    with pytest.raises(DatalensValidationError, match="category mismatch"):
        client.raw.replace.wizard_chart(
            target=cast(dl.WizardChart, dl.QLChart(id="target", wire_type="d3_wizard_node")),
            response_snapshot=_raw(_wizard_snapshot()),
        )
    assert recorder.requests == []


def test_raw_editor_rejects_incomplete_file_before_builder_or_http(tmp_path: Path) -> None:
    artifact = tmp_path / "Incomplete [editor-source]"
    artifact.mkdir()
    (artifact / "chart.json").write_text(
        '{"entry": {"entryId": "editor-source", "type": "advanced-chart_node"}}',
        encoding="utf-8",
    )
    recorder = RecordedTransport({})

    with pytest.raises(DatalensValidationError, match="complete 'data' content"):
        _client(recorder).raw.create.editor_chart.from_file(
            artifact,
            name="Editor Clone",
            location=dl.EntryLocation.path("/target"),
        )

    assert recorder.requests == []


def test_editor_type_unavailable_on_target_installation_fails_before_http() -> None:
    recorder = RecordedTransport({})
    operation = _client(recorder).raw.create.editor_chart(
        response_snapshot=_raw(_editor_snapshot(wire_type="graph_node")),
        name="Unsupported",
        location=dl.EntryLocation.path("/target"),
    )

    with pytest.raises(NotSupportedError, match="not available on installation 'yacloud'"):
        operation.build()
    assert recorder.requests == []


def test_editor_update_rejects_different_node_type_before_http() -> None:
    recorder = RecordedTransport(
        {"/rpc/getEditorChart": httpx.Response(200, json=_editor_snapshot(wire_type="table_node"))}
    )
    client = _client(recorder)
    target = client.get.editor_chart(by_id="editor-target")
    with pytest.raises(DatalensValidationError, match="wire type mismatch"):
        client.raw.replace.editor_chart(
            target=target,
            response_snapshot=_raw(_editor_snapshot(wire_type="advanced-chart_node")),
        )
    assert [request.url.path for request in recorder.requests] == ["/rpc/getEditorChart"]


@pytest.mark.parametrize("category", ["wizard", "ql"])
def test_raw_chart_replace_rejects_wire_type_mismatch_before_http(category: str) -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    replace_from_snapshot: Callable[[], object]
    if category == "wizard":
        replace_from_snapshot = partial(
            client.raw.replace.wizard_chart,
            target=dl.WizardChart(id="target", wire_type="d3_wizard_node_v2"),
            response_snapshot=_raw(_wizard_snapshot()),
        )
    else:
        replace_from_snapshot = partial(
            client.raw.replace.ql_chart,
            target=dl.QLChart(id="target", wire_type="d3_ql_node_v2"),
            response_snapshot=_raw(_ql_snapshot()),
        )

    with pytest.raises(DatalensValidationError, match="wire type mismatch"):
        replace_from_snapshot()

    assert recorder.requests == []


@pytest.mark.parametrize("category", ["wizard", "ql"])
def test_raw_chart_replace_rejects_target_installation_mismatch_before_http(category: str) -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    replace_from_snapshot: Callable[[], object]
    if category == "wizard":
        replace_from_snapshot = partial(
            client.raw.replace.wizard_chart,
            target=dl.WizardChart(
                id="target",
                installation="enterprise",
                wire_type="d3_wizard_node",
            ),
            response_snapshot=_raw(_wizard_snapshot()),
        )
    else:
        replace_from_snapshot = partial(
            client.raw.replace.ql_chart,
            target=dl.QLChart(
                id="target",
                installation="enterprise",
                wire_type="d3_ql_node",
            ),
            response_snapshot=_raw(_ql_snapshot()),
        )

    with pytest.raises(DatalensValidationError, match=r"'enterprise'.*'yacloud'"):
        replace_from_snapshot()

    assert recorder.requests == []


def test_chart_typed_and_raw_builders_have_separate_surfaces() -> None:
    client = _client(RecordedTransport({}))
    wizard_target = dl.WizardChart(id="wizard-target", wire_type="d3_wizard_node")
    editor_target = dl.EditorChart(id="editor-target", wire_type="advanced-chart_node")
    ql_target = dl.QLChart(id="ql-target", wire_type="d3_ql_node")
    wizard_create = client.raw.create.wizard_chart(
        response_snapshot=_raw(_wizard_snapshot()),
        name="Wizard clone",
        location=dl.EntryLocation.path("/target"),
    )
    editor_create = client.raw.create.editor_chart(
        response_snapshot=_raw(_editor_snapshot()),
        name="Editor clone",
        location=dl.EntryLocation.path("/target"),
    )
    ql_create = client.raw.create.ql_chart(
        response_snapshot=_raw(_ql_snapshot()),
        name="QL clone",
        location=dl.EntryLocation.path("/target"),
    )
    wizard_replace = client.raw.replace.wizard_chart(
        target=wizard_target,
        response_snapshot=_raw(_wizard_snapshot()),
    )
    editor_replace = client.raw.replace.editor_chart(
        target=editor_target,
        response_snapshot=_raw(_editor_snapshot()),
    )
    ql_replace = client.raw.replace.ql_chart(
        target=ql_target,
        response_snapshot=_raw(_ql_snapshot()),
    )

    assert not hasattr(wizard_create, "mode")
    assert not hasattr(wizard_create, "legend")
    assert not hasattr(wizard_replace, "legend")
    assert not hasattr(editor_create, "mode")
    assert not hasattr(editor_create, "sources")
    assert not hasattr(editor_replace, "sources")
    assert not hasattr(ql_create, "mode")
    assert not hasattr(ql_create, "query")
    assert not hasattr(ql_replace, "query")


def test_raw_editor_replace_captures_target_identity_before_target_mutation() -> None:
    recorder = RecordedTransport(
        {"/rpc/updateEditorChart": httpx.Response(200, json={"entry": {"entryId": "editor-target"}})}
    )
    client = _client(recorder)
    original_location = dl.EntryLocation.path("/original")
    target = dl.EditorChart(
        id="editor-target",
        installation="yacloud",
        name="Original target",
        location=original_location,
        wire_type="advanced-chart_node",
    )
    replace = client.raw.replace.editor_chart(
        target=target,
        response_snapshot=_raw(_editor_snapshot()),
    )

    target.id = "mutated-id"
    target.name = "Mutated target"
    target.location = dl.EntryLocation.path("/mutated")
    target.wire_type = "table_node"
    updated = replace.execute()

    payload_entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    assert payload_entry["entryId"] == "editor-target"
    assert payload_entry["type"] == "advanced-chart_node"
    assert updated.id == "editor-target"
    assert updated.name == "Original target"
    assert updated.location == original_location
    assert updated.wire_type == "advanced-chart_node"


def test_raw_editor_replace_rejects_target_installation_mismatch_before_http() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(DatalensValidationError, match=r"'enterprise'.*'yacloud'"):
        client.raw.replace.editor_chart(
            target=dl.EditorChart(
                id="editor-target",
                installation="enterprise",
                wire_type="advanced-chart_node",
            ),
            response_snapshot=_raw(_editor_snapshot()),
        )

    assert recorder.requests == []


def test_raw_editor_replace_validates_mode_immediately() -> None:
    replace = _client(RecordedTransport({})).raw.replace.editor_chart(
        target=dl.EditorChart(id="editor-target", wire_type="advanced-chart_node"),
        response_snapshot=_raw(_editor_snapshot()),
    )

    with pytest.raises(DatalensValidationError, match="mode must be one of"):
        replace.mode(cast(dl.EntryUpdateMode, "invalid"))


def test_raw_editor_terminal_calls_repeat_mutations() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": [
                httpx.Response(200, json={"entry": {"entryId": "clone-1"}}),
                httpx.Response(200, json={"entry": {"entryId": "clone-2"}}),
            ],
            "/rpc/updateEditorChart": [
                httpx.Response(200, json={"entry": {"entryId": "editor-target"}}),
                httpx.Response(200, json={"entry": {"entryId": "editor-target"}}),
            ],
        }
    )
    client = _client(recorder)
    create = client.raw.create.editor_chart(
        response_snapshot=_raw(_editor_snapshot()),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.editor_chart(
        target=dl.EditorChart(id="editor-target", wire_type="advanced-chart_node"),
        response_snapshot=_raw(_editor_snapshot()),
    )

    assert create.build().id == "clone-1"
    assert create.build().id == "clone-2"
    assert replace.execute().id == "editor-target"
    assert replace.execute().id == "editor-target"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createEditorChart",
        "/rpc/createEditorChart",
        "/rpc/updateEditorChart",
        "/rpc/updateEditorChart",
    ]


def test_chart_response_snapshot_is_excluded_from_repr_and_equality() -> None:
    first = dl.WizardChart(
        id="chart-id",
        wire_type="d3_wizard_node",
        response_snapshot={"secret_marker": "first"},
    )
    second = replace(first, response_snapshot={"secret_marker": "second"})

    assert first == second
    assert "secret_marker" not in repr(first)
    assert "first" not in repr(first)
