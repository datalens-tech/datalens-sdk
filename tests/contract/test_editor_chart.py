from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk._runtime.chart_builder_base import _BaseEditorNodeCreate, _BaseWizardChartCreate
from datalens_sdk.converter.editor_chart import EditorChartConverter
from datalens_sdk.domain.editor_chart import EditorChart, EditorChartUpdate
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.specs.editor_chart import EditorChartCreateSpec
from datalens_sdk.domain.wizard_chart import WizardChart, WizardChartUpdate
from datalens_sdk.errors import DataLensValidationError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _FakeOps:
    """Minimal ChartOperations stand-in for unit tests."""

    def create_wizard_chart(self, builder: _BaseWizardChartCreate) -> WizardChart:
        raise NotImplementedError

    def get_wizard_chart(self, chart_id: str, workbook_id: str | None = None) -> WizardChart:
        raise NotImplementedError

    def update_wizard_chart(self, builder: WizardChartUpdate) -> WizardChart:
        raise NotImplementedError

    def delete_wizard_chart(self, chart_id: str) -> None:
        raise NotImplementedError

    def create_editor_chart(self, builder: _BaseEditorNodeCreate) -> EditorChart:
        raise NotImplementedError

    def get_editor_chart(self, entry_id: str, workbook_id: str | None = None) -> EditorChart:
        raise NotImplementedError

    def update_editor_chart(self, builder: EditorChartUpdate) -> EditorChart:
        raise NotImplementedError

    def delete_editor_chart(self, entry_id: str) -> None:
        raise NotImplementedError


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
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        resp = responses.pop(0)
        resp.request = request
        return resp

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)


# ---------------------------------------------------------------------------
# 1. EditorChartReadDTO: extra=ignore + raw capture
# ---------------------------------------------------------------------------


def test_editor_chart_read_dto_captures_raw() -> None:
    raw = {
        "entryId": "e1",
        "type": "advanced-chart_node",
        "data": {"sources": "", "params": "", "controls": "", "meta": "", "prepare": ""},
        "future_field": "ignored",
    }
    dto = generated_dto.EditorChartReadDTO.model_validate(raw)
    assert dto.entry_id == "e1"
    assert dto.type == "advanced-chart_node"
    assert dto.raw == raw
    assert "future_field" in dto.raw


def test_editor_chart_read_dto_extra_ignore() -> None:
    dto = generated_dto.EditorChartReadDTO.model_validate({"entryId": "x", "unknown": 42})
    assert dto.entry_id == "x"
    assert "unknown" in dto.raw


# ---------------------------------------------------------------------------
# 2. from_domain_create: payload shape per type
# ---------------------------------------------------------------------------

_PUBLIC_WIRE_TYPES_WITH_REQUIRED: list[tuple[str, dict[str, str]]] = [
    ("advanced-chart_node", {"controls": "c", "meta": "m", "params": "p", "prepare": "pr", "sources": "s"}),
    ("control_node", {"controls": "c", "meta": "m", "params": "p", "sources": "s"}),
    ("d3_node", {"config": "cfg", "controls": "c", "meta": "m", "params": "p", "prepare": "pr", "sources": "s"}),
    ("markdown_node", {"controls": "c", "meta": "m", "params": "p", "prepare": "pr", "sources": "s"}),
    ("table_node", {"config": "cfg", "controls": "c", "meta": "m", "params": "p", "prepare": "pr", "sources": "s"}),
]


class _SimpleBuilder:
    _name: str
    _location: EntryLocation
    _tabs: dict[str, str]
    _description: str | None

    def __init__(
        self,
        wire_type: str,
        tabs: dict[str, str],
        name: str = "test",
        save_to: str = "/dir",
        description: str | None = None,
    ) -> None:
        self._wire_type = wire_type
        self._name = name
        self._location = EntryLocation.path(save_to)
        self._tabs = dict(tabs)
        self._description = description

    @property
    def wire_type(self) -> str:
        return self._wire_type

    def to_spec(self) -> EditorChartCreateSpec:
        return EditorChartCreateSpec(
            wire_type=self._wire_type,
            name=self._name,
            tabs=dict(self._tabs),
            location=self._location,
            description=self._description,
        )


@pytest.mark.parametrize(("wire_type", "tabs"), _PUBLIC_WIRE_TYPES_WITH_REQUIRED)
def test_from_domain_create_payload_shape(wire_type: str, tabs: dict[str, str]) -> None:
    builder = _SimpleBuilder(wire_type=wire_type, tabs=tabs)
    dto_obj = EditorChartConverter.from_domain_create(builder.to_spec())
    payload = dto_obj.to_payload()
    assert "entry" in payload
    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["type"] == wire_type
    assert "data" in entry
    data = entry["data"]
    assert isinstance(data, dict)
    for tab_name in tabs:
        assert tab_name in data


def test_from_domain_create_required_tabs_autofilled() -> None:
    builder = _SimpleBuilder(wire_type="advanced-chart_node", tabs={})
    dto_obj = EditorChartConverter.from_domain_create(builder.to_spec())
    payload = dto_obj.to_payload()
    entry = payload["entry"]
    assert isinstance(entry, dict)
    data = entry["data"]
    assert isinstance(data, dict)
    for req_tab in ("controls", "meta", "params", "prepare", "sources"):
        assert req_tab in data
        assert data[req_tab] == ""


def test_from_domain_create_meta_tab_accepted() -> None:
    builder = _SimpleBuilder(wire_type="advanced-chart_node", tabs={"meta": "my-meta"})
    dto_obj = EditorChartConverter.from_domain_create(builder.to_spec())
    payload = dto_obj.to_payload()
    entry = payload["entry"]
    assert isinstance(entry, dict)
    data = entry["data"]
    assert isinstance(data, dict)
    assert data["meta"] == "my-meta"


def test_from_domain_create_passes_nonempty_description_to_annotation() -> None:
    builder = _SimpleBuilder(wire_type="advanced-chart_node", tabs={}, description="Editor description")
    payload = EditorChartConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["annotation"] == {"description": "Editor description"}


@pytest.mark.parametrize("description", [None, ""])
def test_from_domain_create_omits_annotation_without_description(description: str | None) -> None:
    builder = _SimpleBuilder(wire_type="advanced-chart_node", tabs={}, description=description)
    payload = EditorChartConverter.from_domain_create(builder.to_spec()).to_payload()
    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert "annotation" not in entry


# ---------------------------------------------------------------------------
# 3. Unit: DTO choice by wire_type
# ---------------------------------------------------------------------------


def test_from_domain_create_unknown_wire_type_raises() -> None:
    builder = _SimpleBuilder(wire_type="unknown_type", tabs={})
    with pytest.raises(ValueError, match="Unknown editor wire_type"):
        EditorChartConverter.from_domain_create(builder.to_spec())


# ---------------------------------------------------------------------------
# 4. to_domain: builds EditorChart
# ---------------------------------------------------------------------------


def test_to_domain_builds_editor_chart() -> None:
    raw = {
        "entryId": "chart-1",
        "type": "advanced-chart_node",
        "data": {"sources": "s", "params": "p", "controls": "c", "meta": "m", "prepare": "pr"},
        "name": "My Chart",
        "key": "/dir/My Chart",
        "annotation": {"description": "Editor read description"},
    }
    chart = EditorChartConverter.to_domain(raw, installation="yacloud", operations=None)
    assert chart.id == "chart-1"
    assert chart.wire_type == "advanced-chart_node"
    assert chart.installation == "yacloud"
    assert chart.name == "My Chart"
    assert chart.location == EntryLocation.path("/dir")
    assert chart.dir_path == "/dir"
    assert chart.key == "/dir/My Chart"
    assert chart.description == "Editor read description"


@pytest.mark.parametrize("wrapped", [False, True])
def test_to_domain_redacts_read_only_secrets_from_all_domain_state(wrapped: bool) -> None:
    sentinel = "must-not-leak-editor-token"
    entry: dict[str, object] = {
        "entryId": "chart-1",
        "type": "advanced-chart_node",
        "data": {
            "sources": "s",
            "params": "p",
            "controls": "c",
            "meta": "m",
            "prepare": "pr",
            "secrets": [{"token": sentinel}],
        },
    }
    raw = {"entry": entry} if wrapped else entry

    chart = EditorChartConverter.to_domain(raw, installation="yacloud")

    assert "secrets" not in chart.data
    assert "secrets" not in cast(dict[str, object], chart.raw["data"])
    snapshot_entry = cast(
        dict[str, object],
        chart.response_snapshot["entry"] if wrapped else chart.response_snapshot,
    )
    assert "secrets" not in cast(dict[str, object], snapshot_entry["data"])
    assert sentinel not in repr(chart)
    assert sentinel not in json.dumps(chart.response_snapshot)


# ---------------------------------------------------------------------------
# 5. mode validation
# ---------------------------------------------------------------------------


def test_editor_chart_update_invalid_mode_raises() -> None:
    ops = cast(ChartOperations, _FakeOps())
    chart = EditorChart(id="e1", wire_type="advanced-chart_node", _operations=ops)
    update = chart.update
    with pytest.raises(DataLensValidationError, match="mode must be"):
        update.mode("invalid_mode")  # type: ignore[arg-type]


def test_editor_chart_update_valid_modes() -> None:
    ops = cast(ChartOperations, _FakeOps())
    chart = EditorChart(id="e1", wire_type="advanced-chart_node", _operations=ops)
    update_save = chart.update.mode("save")
    assert update_save.mode_value == "save"
    update_pub = chart.update.mode("publish")
    assert update_pub.mode_value == "publish"


# ---------------------------------------------------------------------------
# 6. from_domain_update
# ---------------------------------------------------------------------------


def test_from_domain_update_builds_update_dto() -> None:
    ops = cast(ChartOperations, _FakeOps())
    chart = EditorChart(
        id="e1",
        wire_type="advanced-chart_node",
        data={"sources": "old", "params": "p", "controls": "c", "meta": "m", "prepare": "pr"},
        _operations=ops,
    )
    update = chart.update.sources("new_sources").mode("save")
    dto_obj = EditorChartConverter.from_domain_update(update)
    payload = dto_obj.to_payload()
    assert "entry" in payload
    assert payload["mode"] == "save"
    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["entryId"] == "e1"
    data = entry["data"]
    assert isinstance(data, dict)
    assert data["sources"] == "new_sources"


@pytest.mark.parametrize("description", ["Updated description", ""])
def test_from_domain_update_passes_description_to_annotation(description: str) -> None:
    ops = cast(ChartOperations, _FakeOps())
    chart = EditorChart(
        id="e1",
        wire_type="advanced-chart_node",
        data={"sources": "s", "params": "p", "controls": "c", "meta": "m", "prepare": "pr"},
        _operations=ops,
    )

    payload = EditorChartConverter.from_domain_update(chart.update.description(description)).to_payload()

    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["annotation"] == {"description": description}


def test_from_domain_update_without_description_preserves_existing_annotation() -> None:
    ops = cast(ChartOperations, _FakeOps())
    chart = EditorChart(
        id="e1",
        wire_type="advanced-chart_node",
        data={"sources": "s", "params": "p", "controls": "c", "meta": "m", "prepare": "pr"},
        raw={"annotation": {"description": "keep", "futureAnnotationField": {"keep": True}}},
        _operations=ops,
    )

    payload = EditorChartConverter.from_domain_update(chart.update.sources("updated")).to_payload()

    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["annotation"] == {
        "description": "keep",
        "futureAnnotationField": {"keep": True},
    }


def test_from_domain_update_merges_description_into_existing_annotation() -> None:
    ops = cast(ChartOperations, _FakeOps())
    chart = EditorChart(
        id="e1",
        wire_type="advanced-chart_node",
        data={"sources": "s", "params": "p", "controls": "c", "meta": "m", "prepare": "pr"},
        raw={"annotation": {"description": "old", "futureAnnotationField": {"keep": True}}},
        _operations=ops,
    )

    payload = EditorChartConverter.from_domain_update(chart.update.description("new")).to_payload()

    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["annotation"] == {
        "description": "new",
        "futureAnnotationField": {"keep": True},
    }


def test_nullable_update_tabs_preserve_explicit_none() -> None:
    ops = cast(ChartOperations, _FakeOps())
    update = EditorChart(id="e1", wire_type="advanced-chart_node", _operations=ops).update

    assert update.activities(None).tab_edits == {"activities": None}


def test_editor_update_has_no_writable_secrets_surface() -> None:
    assert not hasattr(EditorChartUpdate, "secrets")


# ---------------------------------------------------------------------------
# 7. SDK-layer e2e via mock transport
# ---------------------------------------------------------------------------


def _editor_chart_response(entry_id: str = "e1", wire_type: str = "advanced-chart_node") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "type": wire_type,
        "data": {"sources": "s", "params": "p", "controls": "c", "meta": "m", "prepare": "pr"},
        "name": "Test",
        "key": "/dir/Test",
    }


def test_editor_chart_create_get_update_delete_flow() -> None:
    read_response = _editor_chart_response()
    read_data = cast(dict[str, object], read_response["data"])
    read_data["secrets"] = [{"token": "must-not-leak-editor-token"}]
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": httpx.Response(200, json=_editor_chart_response()),
            "/rpc/getEditorChart": httpx.Response(200, json=read_response),
            "/rpc/updateEditorChart": httpx.Response(200, json=_editor_chart_response()),
            "/rpc/deleteEditorChart": httpx.Response(200, json={}),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    chart = (
        client.create.editor_chart.advanced_chart(name="Test", location=dl.EntryLocation.path("/dir"))
        .sources("src")
        .params("par")
        .build()
    )
    assert isinstance(chart, EditorChart)
    assert chart.id == "e1"

    fetched = client.get.editor_chart(by_id="e1")
    assert isinstance(fetched, EditorChart)

    updated = fetched.update.sources("new_src").mode("save").execute()
    assert isinstance(updated, EditorChart)

    updated.delete()

    assert recorder.requests[0].url.path == "/rpc/createEditorChart"
    assert recorder.requests[1].url.path == "/rpc/getEditorChart"
    assert recorder.requests[2].url.path == "/rpc/updateEditorChart"
    assert recorder.requests[3].url.path == "/rpc/deleteEditorChart"
    update_entry = cast(dict[str, object], recorder.request_json(2)["entry"])
    update_data = cast(dict[str, object], update_entry["data"])
    assert "secrets" not in update_data
    assert update_data["sources"] == "new_src"
    assert update_data["params"] == "p"


def test_editor_chart_create_payload_wrapped() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": httpx.Response(200, json=_editor_chart_response()),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    client.create.editor_chart.advanced_chart(name="Test", location=dl.EntryLocation.path("/dir")).sources("s").build()
    payload = recorder.request_json(0)
    assert "entry" in payload
    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["type"] == "advanced-chart_node"
    assert "data" in entry


def test_editor_chart_create_payload_passes_description_to_annotation() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createEditorChart": httpx.Response(200, json=_editor_chart_response()),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    client.create.editor_chart.advanced_chart(name="Test", location=dl.EntryLocation.path("/dir")).description(
        "Editor description"
    ).build()
    payload = recorder.request_json(0)
    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["annotation"] == {"description": "Editor description"}


def test_editor_chart_get_sends_entry_id() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_chart_response()),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    client.get.editor_chart(by_id="my-entry-id")
    payload = recorder.request_json(0)
    assert payload["chartId"] == "my-entry-id"


def test_editor_chart_delete_sends_entry_id() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_chart_response("to-del")),
            "/rpc/deleteEditorChart": httpx.Response(200, json={}),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    chart = client.get.editor_chart(by_id="to-del")
    chart.delete()
    del_payload = recorder.request_json(1)
    assert del_payload["chartId"] == "to-del"


# ---------------------------------------------------------------------------
# 8. lock-retry on 409/423
# ---------------------------------------------------------------------------


def test_editor_chart_update_raises_on_409() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getEditorChart": httpx.Response(200, json=_editor_chart_response()),
            "/rpc/updateEditorChart": httpx.Response(409, json={"code": "ENTRY_IS_LOCKED", "message": "locked"}),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    chart = client.get.editor_chart(by_id="e1")
    with pytest.raises(dl.DataLensAPIError):
        chart.update.sources("new").execute()
    update_requests = [r for r in recorder.requests if r.url.path == "/rpc/updateEditorChart"]
    assert len(update_requests) == 1
