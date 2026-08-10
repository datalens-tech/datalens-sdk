from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import partial
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk._generated.dto import DashboardReadDTO
from datalens_sdk.converter.dashboard import DashboardConverter
from datalens_sdk.domain.raw_dashboard import RawDashboardCreate, RawDashboardReplace
from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.serialization.artifacts import DashboardSnapshotView


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


def _snapshot(
    *,
    dashboard_id: str = "source-id",
    description: str = "Original",
) -> dict[str, object]:
    return {
        "entry": {
            "entryId": dashboard_id,
            "key": "/source/Source",
            "revId": "source-revision",
            "savedId": "saved-revision",
            "publishedId": "published-revision",
            "permissions": {"edit": True},
            "future_outer": {"must_not_be_written": True},
            "data": {
                "description": description,
                "tabs": [],
                "future_data": {"preserved": True},
            },
            "meta": {"future_meta": {"preserved": True}},
            "annotation": {"description": "Annotation", "future_annotation": True},
        },
        "permissions": {"execute": True},
        "future_response": {"inspection_only": True},
    }


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def test_dashboard_get_captures_owned_response_snapshot_and_writes_without_extra_http(tmp_path: Path) -> None:
    snapshot = _snapshot()
    expected = _snapshot()
    recorder = RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json=snapshot)})
    dashboard = _client(recorder).get.dashboard(by_id="source-id")

    assert dashboard.response_snapshot == expected
    assert dashboard.raw == expected["entry"]
    cast(dict[str, object], cast(dict[str, object], dashboard.raw["data"])["future_data"])["preserved"] = False
    assert dashboard.response_snapshot == expected

    artifact = dashboard.to_file(tmp_path)

    assert artifact == tmp_path / "Source [source-id]"
    assert json.loads((artifact / "dashboard.json").read_text(encoding="utf-8")) == expected
    assert [request.url.path for request in recorder.requests] == ["/rpc/getDashboard"]


def test_bound_dashboard_dependency_export_uses_service_wiring(tmp_path: Path) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json=_snapshot()),
            "/rpc/getEntriesRelations": [
                httpx.Response(200, json={"relations": []}),
                httpx.Response(200, json={"relations": []}),
            ],
        }
    )
    dashboard = _client(recorder).get.dashboard(by_id="source-id")

    artifact = dashboard.to_file(tmp_path, with_dependencies=True)

    assert artifact == tmp_path / "Source [source-id]"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getDashboard",
        "/rpc/getEntriesRelations",
        "/rpc/getEntriesRelations",
    ]
    assert sorted(path.name for path in artifact.iterdir()) == [
        "charts",
        "dashboard.json",
        "datasets",
    ]


def test_dashboard_dependency_export_uses_relation_types_and_workbook_ids_without_metadata_lookup(
    tmp_path: Path,
) -> None:
    dashboard_snapshot = _snapshot()
    dashboard_entry = cast(dict[str, object], dashboard_snapshot["entry"])
    dashboard_entry.pop("key")
    dashboard_entry["name"] = "Workbook Dashboard"
    dashboard_entry["workbookId"] = "dashboard-workbook"
    wizard_snapshot: dict[str, object] = {
        "entryId": "chart-wizard",
        "type": "d3_wizard_node",
        "name": "Named Wizard",
        "workbookId": "wizard-workbook",
        "data": {"datasetsIds": ["dataset-1"]},
    }
    editor_snapshot: dict[str, object] = {
        "entry": {
            "entryId": "chart-editor",
            "type": "advanced-chart_node",
            "name": "Named Editor",
            "workbookId": "editor-workbook",
            "data": {"sources": ""},
        }
    }
    ql_snapshot: dict[str, object] = {
        "entryId": "chart-ql",
        "type": "d3_ql_node",
        "name": "Named QL",
        "workbookId": "ql-workbook",
        "data": {"queryValue": "select 1"},
    }
    dataset_snapshot: dict[str, object] = {
        "id": "dataset-1",
        "name": "Named Dataset",
        "workbook_id": "dataset-workbook",
        "dataset": {"description": "server snapshot"},
    }
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(200, json=dashboard_snapshot),
            "/rpc/getEntriesRelations": [
                httpx.Response(
                    200,
                    json={
                        "relations": [
                            {
                                "entryId": "chart-wizard",
                                "scope": "widget",
                                "type": "d3_wizard_node",
                                "workbookId": "wizard-workbook",
                            },
                            {
                                "entryId": "chart-editor",
                                "scope": "widget",
                                "type": "advanced-chart_node",
                                "workbookId": "editor-workbook",
                            },
                            {
                                "entryId": "chart-ql",
                                "scope": "widget",
                                "type": "d3_ql_node",
                                "workbookId": "ql-workbook",
                            },
                        ]
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "relations": [
                            {
                                "entryId": "dataset-1",
                                "scope": "dataset",
                                "type": "dataset",
                                "workbookId": "dataset-workbook",
                            }
                        ]
                    },
                ),
                httpx.Response(200, json={"relations": []}),
                httpx.Response(200, json={"relations": []}),
                httpx.Response(
                    200,
                    json={
                        "relations": [
                            {
                                "entryId": "dataset-1",
                                "scope": "dataset",
                                "type": "dataset",
                            }
                        ]
                    },
                ),
            ],
            "/rpc/getWizardChart": httpx.Response(200, json=wizard_snapshot),
            "/rpc/getEditorChart": httpx.Response(200, json=editor_snapshot),
            "/rpc/getQLChart": httpx.Response(200, json=ql_snapshot),
            "/rpc/getDataset": httpx.Response(200, json=dataset_snapshot),
        }
    )
    dashboard = _client(recorder).get.dashboard(by_id="source-id", workbook_id="dashboard-workbook")

    artifact = dashboard.to_file(tmp_path, with_dependencies=True)

    assert artifact == tmp_path / "Workbook Dashboard [source-id]"
    paths = [request.url.path for request in recorder.requests]
    assert paths == [
        "/rpc/getDashboard",
        "/rpc/getEntriesRelations",
        "/rpc/getEntriesRelations",
        "/rpc/getEntriesRelations",
        "/rpc/getEntriesRelations",
        "/rpc/getEntriesRelations",
        "/rpc/getEditorChart",
        "/rpc/getQLChart",
        "/rpc/getWizardChart",
        "/rpc/getDataset",
    ]
    assert "/rpc/getEntries" not in paths
    expected_get_bodies = {
        "/rpc/getEditorChart": {"chartId": "chart-editor", "workbookId": "editor-workbook"},
        "/rpc/getQLChart": {"chartId": "chart-ql", "workbookId": "ql-workbook"},
        "/rpc/getWizardChart": {"chartId": "chart-wizard", "workbookId": "wizard-workbook"},
        "/rpc/getDataset": {"datasetId": "dataset-1", "workbookId": "dataset-workbook"},
    }
    for request in recorder.requests:
        if request.url.path not in expected_get_bodies:
            continue
        body = cast(dict[str, object], json.loads(request.content))
        assert body == expected_get_bodies[request.url.path]
        assert "branch" not in body
        assert "revId" not in body
        assert "rev_id" not in body

    assert json.loads((artifact / "dashboard.json").read_text(encoding="utf-8")) == dashboard_snapshot
    assert (
        json.loads((artifact / "charts" / "Named Wizard [chart-wizard]" / "chart.json").read_text(encoding="utf-8"))
        == wizard_snapshot
    )
    assert (
        json.loads((artifact / "charts" / "Named Editor [chart-editor]" / "chart.json").read_text(encoding="utf-8"))
        == editor_snapshot
    )
    assert (
        json.loads((artifact / "charts" / "Named QL [chart-ql]" / "chart.json").read_text(encoding="utf-8"))
        == ql_snapshot
    )
    assert (
        json.loads((artifact / "datasets" / "Named Dataset [dataset-1]" / "dataset.json").read_text(encoding="utf-8"))
        == dataset_snapshot
    )


@pytest.mark.parametrize("raw_field", ["future-value", ["future-value"], None])
def test_dashboard_get_preserves_entry_raw_field_without_dto_collision(raw_field: object) -> None:
    snapshot = _snapshot()
    cast(dict[str, object], snapshot["entry"])["raw"] = raw_field
    recorder = RecordedTransport({"/rpc/getDashboard": httpx.Response(200, json=snapshot)})

    dashboard = _client(recorder).get.dashboard(by_id="source-id")

    assert cast(Mapping[str, object], dashboard.response_snapshot["entry"])["raw"] == raw_field
    assert dashboard.raw["raw"] == raw_field


def test_dashboard_prebuilt_dto_does_not_reconstruct_response_snapshot() -> None:
    entry = cast(dict[str, object], _snapshot()["entry"])
    dashboard = DashboardConverter.to_domain(DashboardReadDTO.model_validate(entry), installation="yacloud")

    assert dashboard.raw["entryId"] == "source-id"
    assert dashboard.response_snapshot == {}


def test_raw_dashboard_create_uses_new_identity_and_preserves_only_mutable_content() -> None:
    source = _snapshot()
    recorder = RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json=_snapshot(dashboard_id="clone-id"))})
    operation = _client(recorder).raw.create.dashboard(
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    assert isinstance(operation, RawDashboardCreate)
    cast(dict[str, object], cast(dict[str, object], cast(dict[str, object], source["entry"])["data"])["future_data"])[
        "preserved"
    ] = False

    created = operation.build()

    assert created.id == "clone-id"
    assert [request.url.path for request in recorder.requests] == ["/rpc/createDashboard"]
    payload = recorder.request_json(0)
    assert set(payload) == {"entry"}
    entry = cast(dict[str, object], payload["entry"])
    assert entry["key"] == "/target/Clone"
    assert "name" not in entry
    assert not ({"entryId", "revId", "savedId", "publishedId", "permissions", "future_outer"} & entry.keys())
    assert cast(dict[str, object], cast(dict[str, object], entry["data"])["future_data"])["preserved"] is True
    assert entry["meta"] == {"future_meta": {"preserved": True}}
    assert entry["annotation"] == {"description": "Annotation", "future_annotation": True}


def test_raw_dashboard_create_from_file_reads_only_main_snapshot_eagerly(tmp_path: Path) -> None:
    source = dl.Dashboard(
        id="source-id",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    (artifact / "charts").mkdir()
    (artifact / "datasets").mkdir()
    recorder = RecordedTransport({"/rpc/createDashboard": httpx.Response(200, json=_snapshot(dashboard_id="clone-id"))})
    operation = _client(recorder).raw.create.dashboard.from_file(
        artifact,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    stored = cast(dict[str, object], json.loads((artifact / "dashboard.json").read_text(encoding="utf-8")))
    cast(dict[str, object], cast(dict[str, object], stored["entry"])["data"])["description"] = "Changed"
    (artifact / "dashboard.json").write_text(json.dumps(stored), encoding="utf-8")

    operation.build()

    entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    assert cast(dict[str, object], entry["data"])["description"] == "Original"


def test_raw_dashboard_replace_uses_target_identity_publish_and_lock_without_revision() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDashboard": httpx.Response(
                200,
                json=_snapshot(dashboard_id="target-id", description="Target"),
            ),
            "/rpc/updateDashboard": httpx.Response(
                200,
                json=_snapshot(dashboard_id="target-id", description="Original"),
            ),
        }
    )
    client = _client(recorder)
    target = client.get.dashboard(by_id="target-id")
    operation = client.raw.replace.dashboard(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    assert isinstance(operation, RawDashboardReplace)

    updated = operation.execute(publish=True, lock_token="lock-1")

    assert updated.id == "target-id"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getDashboard",
        "/rpc/updateDashboard",
    ]
    payload = recorder.request_json(1)
    assert payload["mode"] == "publish"
    assert payload["lockToken"] == "lock-1"
    entry = cast(dict[str, object], payload["entry"])
    assert entry["entryId"] == "target-id"
    assert cast(dict[str, object], entry["data"])["description"] == "Original"
    assert "revId" not in entry
    assert not ({"key", "savedId", "publishedId", "permissions", "future_outer"} & entry.keys())


def test_raw_dashboard_replace_preserves_target_name_for_sparse_workbook_response() -> None:
    response = _snapshot(dashboard_id="target-id")
    response_entry = cast(dict[str, object], response["entry"])
    response_entry.pop("key")
    response_entry["workbookId"] = "wb-1"
    recorder = RecordedTransport({"/rpc/updateDashboard": httpx.Response(200, json=response)})
    client = _client(recorder)
    target = dl.Dashboard(
        id="target-id",
        name="Target",
        location=dl.EntryLocation.workbook("wb-1"),
        data={"tabs": []},
    )

    updated = client.raw.replace.dashboard(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    ).execute(publish=False)

    assert updated.name == "Target"
    assert updated.location == dl.EntryLocation.workbook("wb-1")


def test_raw_dashboard_replace_from_file_reads_snapshot_eagerly(tmp_path: Path) -> None:
    source = dl.Dashboard(
        id="source-id",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    recorder = RecordedTransport(
        {
            "/rpc/updateDashboard": httpx.Response(
                200,
                json=_snapshot(dashboard_id="target-id"),
            )
        }
    )
    client = _client(recorder)
    target = dl.Dashboard(
        id="target-id",
        name="Target",
        data={"tabs": []},
    )
    operation = client.raw.replace.dashboard.from_file(artifact, target=target)
    stored = cast(dict[str, object], json.loads((artifact / "dashboard.json").read_text(encoding="utf-8")))
    cast(dict[str, object], cast(dict[str, object], stored["entry"])["data"])["description"] = "Changed"
    (artifact / "dashboard.json").write_text(json.dumps(stored), encoding="utf-8")

    operation.execute(publish=False)

    payload = recorder.request_json(0)
    assert payload["mode"] == "save"
    entry = cast(dict[str, object], payload["entry"])
    assert cast(dict[str, object], entry["data"])["description"] == "Original"


def test_raw_dashboard_namespace_defers_and_captures_create_and_replace_inputs() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDashboard": httpx.Response(200, json=_snapshot(dashboard_id="clone-id")),
            "/rpc/updateDashboard": httpx.Response(
                200,
                json={"entry": {"entryId": "target-id", "data": {}}},
            ),
        }
    )
    client = _client(recorder)
    source = _snapshot()
    target = dl.Dashboard(
        id="target-id",
        name="Target",
        installation="yacloud",
        location=dl.EntryLocation.path("/existing"),
        data={"tabs": []},
    )

    create = client.raw.create.dashboard(
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dashboard(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
    )

    assert isinstance(create, RawDashboardCreate)
    assert isinstance(replace, RawDashboardReplace)
    assert recorder.requests == []

    cast(dict[str, object], cast(dict[str, object], source["entry"])["data"])["description"] = "Changed"
    target.id = "mutated-id"
    target.name = "Mutated"
    target.location = dl.EntryLocation.path("/mutated")

    created = create.build()
    updated = replace.execute(publish=True, lock_token="lock-1")

    assert created.id == "clone-id"
    assert updated.id == "target-id"
    assert updated.name == "Target"
    assert updated.location == dl.EntryLocation.path("/existing")
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createDashboard",
        "/rpc/updateDashboard",
    ]
    create_entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    replace_payload = recorder.request_json(1)
    replace_entry = cast(dict[str, object], replace_payload["entry"])
    assert cast(dict[str, object], create_entry["data"])["description"] == "Original"
    assert cast(dict[str, object], replace_entry["data"])["description"] == "Original"
    assert replace_entry["entryId"] == "target-id"
    assert replace_payload["mode"] == "publish"
    assert replace_payload["lockToken"] == "lock-1"


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_dashboard_builder_owns_prevalidated_snapshot_view(boundary: str) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDashboard": httpx.Response(200, json=_snapshot(dashboard_id="clone-id")),
            "/rpc/updateDashboard": httpx.Response(200, json=_snapshot(dashboard_id="target-id")),
        }
    )
    snapshot = DashboardSnapshotView.from_raw(cast(Mapping[str, dl.JsonValue], _snapshot()))
    client = _client(recorder)
    terminal: Callable[[], dl.Dashboard]
    if boundary == "create":
        terminal = client.raw.create.dashboard(
            response_snapshot=snapshot,
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        ).build
    else:
        terminal = partial(
            client.raw.replace.dashboard(
                target=dl.Dashboard(id="target-id", name="Target"),
                response_snapshot=snapshot,
            ).execute,
            publish=False,
        )

    snapshot.data["description"] = "Changed after builder creation"
    cast(dict[str, dl.JsonValue], snapshot.data["future_data"])["preserved"] = False

    terminal()

    entry = cast(dict[str, object], recorder.request_json(0)["entry"])
    data = cast(dict[str, object], entry["data"])
    assert data["description"] == "Original"
    assert data["future_data"] == {"preserved": True}


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_dashboard_builder_revalidates_forged_snapshot_view_before_http(boundary: str) -> None:
    recorder = RecordedTransport({})
    data: dict[str, dl.JsonValue] = {"tabs": []}
    entry: dict[str, dl.JsonValue] = {"data": data}
    forged = DashboardSnapshotView(
        snapshot={"entry": entry},
        entry=entry,
        data=data,
    )
    client = _client(recorder)

    def construct_with_forged_snapshot() -> None:
        if boundary == "create":
            client.raw.create.dashboard(
                response_snapshot=forged,
                name="Clone",
                location=dl.EntryLocation.path("/target"),
            )
        else:
            client.raw.replace.dashboard(
                target=dl.Dashboard(id="target-id", name="Target"),
                response_snapshot=forged,
            )

    with pytest.raises(DataLensValidationError, match="source id"):
        construct_with_forged_snapshot()

    assert recorder.requests == []


def test_raw_dashboard_namespace_direct_and_file_payloads_match(tmp_path: Path) -> None:
    snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())
    artifact = dl.Dashboard(
        id="source-id",
        name="Source",
        response_snapshot=snapshot,
    ).to_file(tmp_path)
    recorder = RecordedTransport(
        {
            "/rpc/createDashboard": [
                httpx.Response(200, json=_snapshot(dashboard_id=f"clone-{index}")) for index in range(2)
            ],
            "/rpc/updateDashboard": [httpx.Response(200, json=_snapshot(dashboard_id="target-id")) for _ in range(2)],
        }
    )
    client = _client(recorder)
    target = dl.Dashboard(
        id="target-id",
        name="Target",
        installation="yacloud",
        data={"tabs": []},
        _operations=client.dashboard_ops,
    )
    location = dl.EntryLocation.path("/target")

    client.raw.create.dashboard(response_snapshot=snapshot, name="Clone", location=location).build()
    client.raw.create.dashboard.from_file(artifact, name="Clone", location=location).build()
    client.raw.replace.dashboard(target=target, response_snapshot=snapshot).execute(
        publish=True,
        lock_token="lock-1",
    )
    client.raw.replace.dashboard.from_file(artifact, target=target).execute(
        publish=True,
        lock_token="lock-1",
    )

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createDashboard",
        "/rpc/createDashboard",
        "/rpc/updateDashboard",
        "/rpc/updateDashboard",
    ]
    payloads = [recorder.request_json(index) for index in range(4)]
    assert payloads[0] == payloads[1]
    assert payloads[2] == payloads[3]


def test_raw_dashboard_namespace_rejects_target_installation_mismatch_before_http() -> None:
    recorder = RecordedTransport({})

    with pytest.raises(DataLensValidationError, match=r"'enterprise'.*'yacloud'"):
        _client(recorder).raw.replace.dashboard(
            target=dl.Dashboard(id="target-id", installation="enterprise"),
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        )

    assert recorder.requests == []


def test_raw_dashboard_namespace_terminal_calls_repeat_mutations() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDashboard": [
                httpx.Response(200, json=_snapshot(dashboard_id="clone-1")),
                httpx.Response(200, json=_snapshot(dashboard_id="clone-2")),
            ],
            "/rpc/updateDashboard": [
                httpx.Response(200, json=_snapshot(dashboard_id="target-id")),
                httpx.Response(200, json=_snapshot(dashboard_id="target-id")),
            ],
        }
    )
    client = _client(recorder)
    snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())
    create = client.raw.create.dashboard(
        response_snapshot=snapshot,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dashboard(
        target=dl.Dashboard(id="target-id"),
        response_snapshot=snapshot,
    )

    assert create.build().id == "clone-1"
    assert create.build().id == "clone-2"
    assert replace.execute(publish=False).id == "target-id"
    assert replace.execute(publish=False).id == "target-id"
    assert len(recorder.requests) == 4


def test_dashboard_response_snapshot_is_excluded_from_repr_and_equality() -> None:
    first = dl.Dashboard(id="dashboard-id", response_snapshot={"secret_marker": "first"})
    second = replace(first, response_snapshot={"secret_marker": "second"})

    assert first == second
    assert "secret_marker" not in repr(first)
    assert "first" not in repr(first)


def test_dashboard_typed_and_raw_builders_have_separate_surfaces() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    target = dl.Dashboard(id="target-id", data={"tabs": []})
    create = client.raw.create.dashboard(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dashboard(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )

    assert not hasattr(create, "add_tab")
    assert not hasattr(replace, "description")


def test_raw_dashboard_rejects_incomplete_snapshot_before_http() -> None:
    recorder = RecordedTransport({})

    with pytest.raises(DataLensValidationError, match="complete 'data' content"):
        _client(recorder).raw.create.dashboard(
            response_snapshot={"entry": {"entryId": "source-id"}},
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )

    assert recorder.requests == []
