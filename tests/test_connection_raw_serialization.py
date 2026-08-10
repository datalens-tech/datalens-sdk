from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk._generated.dto import ConnectionReadDTO
from datalens_sdk.converter.connection import ConnectionConverter
from datalens_sdk.domain.raw_resource import RawConnectionCreate, RawConnectionReplace
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec
from datalens_sdk.errors import DataLensValidationError, NotSupportedError
from datalens_sdk.serialization import connection as connection_serialization
from datalens_sdk.serialization import json_io
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


def _snapshot(
    *,
    connection_id: str = "source-id",
    connector: str = "postgres",
    description: str = "Original",
) -> dict[str, object]:
    return {
        "id": connection_id,
        "type": connector,
        "name": "Source",
        "key": "/source/Source",
        "dir_path": "/source",
        "revId": "source-revision",
        "permissions": {"edit": True},
        "options": {"allow_dataset_usage": True},
        "created_at": "2026-07-25T00:00:00Z",
        "description": description,
        "host": "db.local",
        "port": 5432,
        "username": "robot",
        "future_connection_field": {"preserved": True},
    }


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def test_connection_get_captures_owned_response_snapshot_and_writes_artifact(tmp_path: Path) -> None:
    snapshot = _snapshot()
    expected_snapshot = _snapshot()
    recorder = RecordedTransport({"/rpc/getConnection": httpx.Response(200, json=snapshot)})
    connection = _client(recorder).get.connection(by_id="source-id")

    assert connection.response_snapshot == expected_snapshot
    assert connection.raw == expected_snapshot
    cast(dict[str, object], snapshot["future_connection_field"])["preserved"] = False
    cast(dict[str, object], connection.raw["future_connection_field"])["preserved"] = False
    assert connection.response_snapshot == expected_snapshot

    artifact = connection.to_file(tmp_path)

    assert artifact == tmp_path / "Source [source-id]"
    assert json.loads((artifact / "connection.json").read_text(encoding="utf-8")) == expected_snapshot
    assert [request.url.path for request in recorder.requests] == ["/rpc/getConnection"]


def test_connection_get_without_name_uses_key_for_artifact_identity(tmp_path: Path) -> None:
    snapshot = _snapshot()
    del snapshot["name"]
    recorder = RecordedTransport({"/rpc/getConnection": httpx.Response(200, json=snapshot)})

    connection = _client(recorder).get.connection(by_id="source-id")
    artifact = connection.to_file(tmp_path)

    assert connection.name == "Source"
    assert artifact == tmp_path / "Source [source-id]"


def test_connection_get_in_workbook_uses_explicit_name_for_artifact_identity(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.pop("key")
    snapshot.pop("dir_path")
    snapshot["name"] = "Workbook Connection"
    snapshot["workbook_id"] = "workbook-1"
    recorder = RecordedTransport({"/rpc/getConnection": httpx.Response(200, json=snapshot)})

    connection = _client(recorder).get.connection(by_id="source-id", workbook_id="workbook-1")
    artifact = connection.to_file(tmp_path)

    assert connection.name == "Workbook Connection"
    assert connection.location == dl.EntryLocation.workbook("workbook-1")
    assert artifact == tmp_path / "Workbook Connection [source-id]"


@pytest.mark.parametrize("raw_field", ["future-value", ["future-value"], None])
def test_connection_get_preserves_top_level_raw_field_without_dto_collision(raw_field: object) -> None:
    snapshot = _snapshot()
    snapshot["raw"] = raw_field
    recorder = RecordedTransport({"/rpc/getConnection": httpx.Response(200, json=snapshot)})

    connection = _client(recorder).get.connection(by_id="source-id")

    assert connection.response_snapshot["raw"] == raw_field
    assert connection.raw["raw"] == raw_field


def test_connection_prebuilt_dto_does_not_reconstruct_response_snapshot() -> None:
    dto = ConnectionReadDTO.model_validate(_snapshot())
    connection = ConnectionConverter.to_domain(dto, installation="yacloud")

    assert connection.raw["host"] == "db.local"
    assert connection.response_snapshot == {}


def test_connection_to_file_rejects_short_mutation_response(tmp_path: Path) -> None:
    recorder = RecordedTransport({"/rpc/createConnection": httpx.Response(200, json={"id": "clone-id"})})
    connection = (
        _client(recorder)
        .raw.create.connection(
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )
        .build()
    )

    with pytest.raises(DataLensValidationError, match=r"client\.get\.connection"):
        connection.to_file(tmp_path)
    assert [request.url.path for request in recorder.requests] == ["/rpc/createConnection"]


def test_raw_connection_create_uses_new_identity_overrides_and_one_rpc() -> None:
    source = _snapshot()
    recorder = RecordedTransport({"/rpc/createConnection": httpx.Response(200, json={"id": "clone-id"})})
    operation = _client(recorder).raw.create.connection(
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
        overrides={"password": "write-only"},
    )
    assert isinstance(operation, RawConnectionCreate)
    cast(dict[str, object], source["future_connection_field"])["preserved"] = False

    created = operation.build()

    assert created.id == "clone-id"
    assert created.type == "postgres"
    assert created.name == "Clone"
    assert [request.url.path for request in recorder.requests] == ["/rpc/createConnection"]
    payload = recorder.request_json(0)
    assert payload["name"] == "Clone"
    assert payload["dir_path"] == "/target"
    assert payload["type"] == "postgres"
    assert payload["password"] == "write-only"
    assert cast(dict[str, object], payload["future_connection_field"])["preserved"] is True
    assert not ({"id", "key", "revId", "permissions", "options", "created_at"} & payload.keys())


def test_raw_connection_create_from_file_reads_snapshot_eagerly(tmp_path: Path) -> None:
    source = dl.Connection(
        id="source-id",
        type="postgres",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    recorder = RecordedTransport({"/rpc/createConnection": httpx.Response(200, json={"id": "clone-id"})})
    operation = _client(recorder).raw.create.connection.from_file(
        artifact,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    stored = cast(dict[str, object], json.loads((artifact / "connection.json").read_text(encoding="utf-8")))
    stored["description"] = "Changed after command creation"
    (artifact / "connection.json").write_text(json.dumps(stored), encoding="utf-8")

    operation.build()

    assert recorder.request_json(0)["description"] == "Original"


def test_raw_connection_replace_uses_target_identity_and_preserves_target_connector() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getConnection": httpx.Response(
                200,
                json=_snapshot(connection_id="target-id", description="Target"),
            ),
            "/rpc/updateConnection": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    client = _client(recorder)
    target = client.get.connection(by_id="target-id")
    operation = client.raw.replace.connection(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        overrides={"password": "replacement-secret"},
    )
    assert isinstance(operation, RawConnectionReplace)

    updated = operation.execute()

    assert updated.id == "target-id"
    assert updated.type == "postgres"
    assert updated.name == target.name == "Source"
    assert [request.url.path for request in recorder.requests] == ["/rpc/getConnection", "/rpc/updateConnection"]
    payload = recorder.request_json(1)
    assert payload["connectionId"] == "target-id"
    assert set(payload) == {"connectionId", "data"}
    data = cast(dict[str, object], payload["data"])
    assert data["description"] == "Original"
    assert data["password"] == "replacement-secret"
    assert "name" not in data
    assert "type" not in data
    assert "dir_path" not in data
    assert "revId" not in data


def test_raw_connection_replace_from_file_reads_snapshot_eagerly(tmp_path: Path) -> None:
    source = dl.Connection(
        id="source-id",
        type="postgres",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    recorder = RecordedTransport({"/rpc/updateConnection": httpx.Response(200, json={"id": "target-id"})})
    client = _client(recorder)
    target = client.domain_connection(id="target-id", type="postgres", name="Target")
    operation = client.raw.replace.connection.from_file(artifact, target=target)
    stored = cast(dict[str, object], json.loads((artifact / "connection.json").read_text(encoding="utf-8")))
    stored["description"] = "Changed after command creation"
    (artifact / "connection.json").write_text(json.dumps(stored), encoding="utf-8")

    updated = operation.execute()

    data = cast(dict[str, object], recorder.request_json(0)["data"])
    assert data["description"] == "Original"
    assert updated.name == "Target"


def test_raw_connection_namespace_defers_and_captures_create_and_replace_inputs() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": httpx.Response(200, json={"id": "clone-id"}),
            "/rpc/updateConnection": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    client = _client(recorder)
    source = _snapshot()
    create_overrides: dict[str, dl.JsonValue] = {"password": "create-secret"}
    replace_overrides: dict[str, dl.JsonValue] = {"password": "replace-secret"}
    target = dl.Connection(
        id="target-id",
        type="postgres",
        name="Target",
        installation="yacloud",
        location=dl.EntryLocation.path("/existing"),
    )

    create = client.raw.create.connection(
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
        overrides=create_overrides,
    )
    replace = client.raw.replace.connection(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
        overrides=replace_overrides,
    )

    assert isinstance(create, RawConnectionCreate)
    assert isinstance(replace, RawConnectionReplace)
    assert recorder.requests == []

    source["description"] = "Changed after builder creation"
    create_overrides["password"] = "changed"
    replace_overrides["password"] = "changed"
    target.id = "mutated-id"
    target.name = "Mutated"
    target.location = dl.EntryLocation.path("/mutated")
    target.type = "clickhouse"

    created = create.build()
    updated = replace.execute()

    assert created.id == "clone-id"
    assert updated.id == "target-id"
    assert updated.name == "Target"
    assert updated.location == dl.EntryLocation.path("/existing")
    assert updated.type == "postgres"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createConnection",
        "/rpc/updateConnection",
    ]
    create_payload = recorder.request_json(0)
    replace_payload = recorder.request_json(1)
    assert create_payload["description"] == "Original"
    assert create_payload["password"] == "create-secret"
    assert replace_payload["connectionId"] == "target-id"
    assert cast(dict[str, object], replace_payload["data"])["password"] == "replace-secret"


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_connection_builder_owns_prevalidated_snapshot_and_override_views(boundary: str) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": httpx.Response(200, json={"id": "clone-id"}),
            "/rpc/updateConnection": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    snapshot = connection_serialization.ConnectionSnapshotView.from_raw(cast(Mapping[str, dl.JsonValue], _snapshot()))
    overrides = connection_serialization.ConnectionOverridesView.from_raw({"future_credentials": {"token": "original"}})
    client = _client(recorder)
    terminal: Callable[[], dl.Connection]
    if boundary == "create":
        terminal = client.raw.create.connection(
            response_snapshot=snapshot,
            name="Clone",
            location=dl.EntryLocation.path("/target"),
            overrides=overrides,
        ).build
    else:
        terminal = client.raw.replace.connection(
            target=dl.Connection(id="target-id", type="postgres", name="Target"),
            response_snapshot=snapshot,
            overrides=overrides,
        ).execute

    snapshot.snapshot["description"] = "Changed after builder creation"
    cast(dict[str, dl.JsonValue], snapshot.snapshot["future_connection_field"])["preserved"] = False
    cast(dict[str, dl.JsonValue], overrides.data["future_credentials"])["token"] = "changed"

    terminal()

    payload = recorder.request_json(0)
    mutable_payload = payload if boundary == "create" else cast(dict[str, object], payload["data"])
    assert mutable_payload["description"] == "Original"
    assert mutable_payload["future_connection_field"] == {"preserved": True}
    assert mutable_payload["future_credentials"] == {"token": "original"}


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_connection_builder_revalidates_forged_snapshot_and_override_views_before_http(
    boundary: str,
) -> None:
    recorder = RecordedTransport({})
    forged_snapshot = connection_serialization.ConnectionSnapshotView(
        snapshot={"type": "postgres", "name": "Source"},
        connector="postgres",
    )
    forged_overrides = connection_serialization.ConnectionOverridesView(data={"id": "forbidden"})
    client = _client(recorder)

    def construct_with_forged_snapshot() -> None:
        if boundary == "create":
            client.raw.create.connection(
                response_snapshot=forged_snapshot,
                name="Clone",
                location=dl.EntryLocation.path("/target"),
            )
        else:
            client.raw.replace.connection(
                target=dl.Connection(id="target-id", type="postgres", name="Target"),
                response_snapshot=forged_snapshot,
            )

    def construct_with_forged_overrides() -> None:
        if boundary == "create":
            client.raw.create.connection(
                response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
                name="Clone",
                location=dl.EntryLocation.path("/target"),
                overrides=forged_overrides,
            )
        else:
            client.raw.replace.connection(
                target=dl.Connection(id="target-id", type="postgres", name="Target"),
                response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
                overrides=forged_overrides,
            )

    with pytest.raises(DataLensValidationError, match="source id"):
        construct_with_forged_snapshot()
    with pytest.raises(DataLensValidationError, match="cannot set identity"):
        construct_with_forged_overrides()

    assert recorder.requests == []


def test_raw_connection_namespace_direct_and_file_payloads_match(tmp_path: Path) -> None:
    snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())
    artifact = dl.Connection(
        id="source-id",
        type="postgres",
        name="Source",
        response_snapshot=snapshot,
    ).to_file(tmp_path)
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": [httpx.Response(200, json={"id": f"clone-{index}"}) for index in range(2)],
            "/rpc/updateConnection": [httpx.Response(200, json={"id": "target-id"}) for _ in range(2)],
        }
    )
    client = _client(recorder)
    target = client.domain_connection(id="target-id", type="postgres", name="Target")
    location = dl.EntryLocation.path("/target")
    overrides = {"password": "secret"}

    client.raw.create.connection(
        response_snapshot=snapshot,
        name="Clone",
        location=location,
        overrides=overrides,
    ).build()
    client.raw.create.connection.from_file(
        artifact,
        name="Clone",
        location=location,
        overrides=overrides,
    ).build()
    client.raw.replace.connection(
        target=target,
        response_snapshot=snapshot,
        overrides=overrides,
    ).execute()
    client.raw.replace.connection.from_file(
        artifact,
        target=target,
        overrides=overrides,
    ).execute()

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createConnection",
        "/rpc/createConnection",
        "/rpc/updateConnection",
        "/rpc/updateConnection",
    ]
    payloads = [recorder.request_json(index) for index in range(4)]
    assert payloads[0] == payloads[1]
    assert payloads[2] == payloads[3]


def test_raw_connection_direct_and_file_paths_capture_snapshot_at_builder_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_contexts: list[str] = []
    file_contexts: list[str] = []

    def count_connection_normalization(value: object, *, context: str = "JSON object") -> dict[str, dl.JsonValue]:
        connection_contexts.append(context)
        return normalize_json_object(value, context=context)

    def count_file_normalization(value: object, *, context: str = "JSON object") -> dict[str, dl.JsonValue]:
        file_contexts.append(context)
        return normalize_json_object(value, context=context)

    monkeypatch.setattr(connection_serialization, "normalize_json_object", count_connection_normalization)
    monkeypatch.setattr(json_io, "normalize_json_object", count_file_normalization)

    artifact = tmp_path / "source"
    artifact.mkdir()
    (artifact / "connection.json").write_text(json.dumps(_snapshot()), encoding="utf-8")
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": [
                httpx.Response(200, json={"id": "direct-id"}),
                httpx.Response(200, json={"id": "file-id"}),
            ]
        }
    )
    client = _client(recorder)

    client.raw.create.connection(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        name="Direct",
        location=dl.EntryLocation.path("/target"),
        overrides={"password": "direct-secret"},
    ).build()
    client.raw.create.connection.from_file(
        artifact,
        name="File",
        location=dl.EntryLocation.path("/target"),
        overrides={"password": "file-secret"},
    ).build()

    assert connection_contexts.count("Connection response snapshot") == 2
    assert connection_contexts.count("Connection raw overrides") == 2
    assert len(file_contexts) == 1


def test_raw_connection_namespace_rejects_target_installation_mismatch_before_http() -> None:
    recorder = RecordedTransport({})

    with pytest.raises(DataLensValidationError, match=r"'enterprise'.*'yacloud'"):
        _client(recorder).raw.replace.connection(
            target=dl.Connection(id="target-id", type="postgres", installation="enterprise"),
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        )

    assert recorder.requests == []


def test_raw_connection_namespace_terminal_calls_repeat_mutations() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createConnection": [
                httpx.Response(200, json={"id": "clone-1"}),
                httpx.Response(200, json={"id": "clone-2"}),
            ],
            "/rpc/updateConnection": [
                httpx.Response(200, json={"id": "target-id"}),
                httpx.Response(200, json={"id": "target-id"}),
            ],
        }
    )
    client = _client(recorder)
    snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())
    create = client.raw.create.connection(
        response_snapshot=snapshot,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.connection(
        target=dl.Connection(id="target-id", type="postgres"),
        response_snapshot=snapshot,
    )

    assert create.build().id == "clone-1"
    assert create.build().id == "clone-2"
    assert replace.execute().id == "target-id"
    assert replace.execute().id == "target-id"
    assert len(recorder.requests) == 4


def test_raw_connection_replace_rejects_connector_mismatch_before_http() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    target = client.domain_connection(id="target-id", type="postgres", name="Target")

    with pytest.raises(DataLensValidationError, match="connector type mismatch"):
        client.raw.replace.connection(
            target=target,
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot(connector="clickhouse")),
        )
    assert recorder.requests == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "other"},
        {"type": "clickhouse"},
        {"name": "Other"},
        {"dir_path": "/other"},
        {"workbook_id": "wb-other"},
        {"permissions": {"edit": True}},
        {"meta": {"author": "other"}},
        {"revId": "other-revision"},
    ],
)
def test_raw_connection_overrides_cannot_replace_identity_or_connector(
    overrides: Mapping[str, dl.JsonValue],
) -> None:
    recorder = RecordedTransport({})
    with pytest.raises(DataLensValidationError, match="cannot set identity"):
        _client(recorder).raw.create.connection(
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
            name="Clone",
            location=dl.EntryLocation.path("/target"),
            overrides=overrides,
        )
    with pytest.raises(DataLensValidationError, match="cannot set identity"):
        _client(recorder).raw.replace.connection(
            target=dl.Connection(id="target-id", type="postgres"),
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
            overrides=overrides,
        )
    assert recorder.requests == []


def test_connection_update_preserves_dynamic_typed_setters() -> None:
    update = dl.ConnectionUpdate(connection_id="connection-id", connection_type="postgres")

    assert update.host("db.remote") is update
    assert update.to_spec().changes == {"host": "db.remote"}


def test_connection_typed_and_raw_builders_have_separate_surfaces() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    target = dl.Connection(id="target-id", type="postgres")
    create = client.raw.create.connection(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.connection(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )

    assert not hasattr(create, "description")
    assert not hasattr(replace, "description")


def test_connection_response_snapshot_is_excluded_from_repr_and_equality() -> None:
    first = dl.Connection(id="connection-id", type="postgres", response_snapshot={"secret_marker": "first"})
    second = replace(first, response_snapshot={"secret_marker": "second"})

    assert first == second
    assert "secret_marker" not in repr(first)
    assert "first" not in repr(first)


def test_raw_connection_rejects_incomplete_snapshot_before_http() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(DataLensValidationError, match="connector type"):
        client.raw.create.connection(
            response_snapshot={"id": "source-id", "name": "Source"},
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )
    assert recorder.requests == []


def test_raw_connection_create_rejects_connector_unavailable_on_target_installation_before_http() -> None:
    recorder = RecordedTransport({})
    operation = _client(recorder).raw.create.connection(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot(connector="usage_tracking_ya_team")),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )

    with pytest.raises(NotSupportedError, match="not available on installation 'yacloud'"):
        operation.build()
    assert recorder.requests == []


def test_raw_connection_replace_rejects_connector_unavailable_on_target_installation_before_http() -> None:
    recorder = RecordedTransport({})
    operation = _client(recorder).raw.replace.connection(
        target=dl.Connection(
            id="target-id",
            type="usage_tracking_ya_team",
            installation="yacloud",
        ),
        response_snapshot=cast(
            Mapping[str, dl.JsonValue],
            _snapshot(connector="usage_tracking_ya_team"),
        ),
    )

    with pytest.raises(NotSupportedError, match="not available on installation 'yacloud'"):
        operation.execute()
    assert recorder.requests == []


def test_raw_connection_operation_repr_does_not_contain_snapshot_or_overrides() -> None:
    spec = RawCreateSpec(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot(description="sensitive-snapshot-marker")),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    operation = _client(RecordedTransport({})).raw.create.connection(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
        overrides={"password": "sensitive-override-marker"},
    )

    spec_repr = repr(spec)
    assert "sensitive-snapshot-marker" not in spec_repr
    assert "sensitive-override-marker" not in repr(operation)
