from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dataset import SourcesProxy
from datalens_sdk.domain.raw_resource import RawDatasetCreate, RawDatasetReplace
from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.serialization import artifacts, json_io
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


def _snapshot(*, dataset_id: str = "source-id", description: str = "Original") -> dict[str, object]:
    return {
        "id": dataset_id,
        "name": "Source",
        "key": "source/folder/Source",
        "revId": "source-revision",
        "permissions": {"edit": True},
        "raw": {"future_backend_field": True},
        "future_outer": {"must_not_be_written": True},
        "dataset": {
            "name": "Source content name",
            "description": description,
            "revision_id": "source-dataset-revision",
            "sources": [
                {
                    "id": "source-1",
                    "connection_id": "connection-1",
                    "future_source_field": {"preserved": True},
                }
            ],
            "source_avatars": [{"id": "avatar-1", "source_id": "source-1"}],
            "avatar_relations": [{"id": "relation-1", "left_avatar_id": "avatar-1"}],
            "result_schema": [{"guid": "field-1", "future_field": True}],
            "obligatory_filters": [],
            "rls": {"unsupported": True},
            "rls2": {"field-1": []},
            "future_dataset_field": {"preserved": True},
        },
    }


def _expected_dataset_content(*, description: str = "Original") -> dict[str, object]:
    return {
        "description": description,
        "sources": [
            {
                "id": "source-1",
                "connection_id": "connection-1",
                "future_source_field": {"preserved": True},
            }
        ],
        "source_avatars": [{"id": "avatar-1", "source_id": "source-1"}],
        "avatar_relations": [{"id": "relation-1", "left_avatar_id": "avatar-1"}],
        "result_schema": [{"guid": "field-1", "future_field": True}],
        "obligatory_filters": [],
        "rls2": {"field-1": []},
        "future_dataset_field": {"preserved": True},
    }


def _client(recorder: RecordedTransport) -> dl.DataLensClientYC:
    return dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))


def test_response_snapshot_does_not_shift_existing_dataset_positional_arguments() -> None:
    dataset = dl.Dataset(
        "dataset-id",
        "Dataset",
        "yacloud",
        "Description",
        None,
        SourcesProxy(()),
        (),
        (),
        (),
        (),
        {},
        {"dataset": {}},
        True,
    )

    assert dataset.raw == {"dataset": {}}
    assert dataset.is_favorite is True
    assert dataset.response_snapshot == {}


def test_dataset_get_captures_owned_response_snapshot_before_typed_normalization(tmp_path: Path) -> None:
    snapshot = _snapshot()
    expected_snapshot = _snapshot()
    recorder = RecordedTransport({"/rpc/getDataset": httpx.Response(200, json=snapshot)})
    dataset = _client(recorder).get.dataset(by_id="source-id")

    assert dataset.response_snapshot == expected_snapshot
    assert dataset.raw["raw"] == {"future_backend_field": True}
    typed_dataset = cast(Mapping[str, object], dataset.raw["dataset"])
    assert "rls" not in typed_dataset
    assert typed_dataset["rls2"] == {"field-1": []}

    cast(dict[str, object], snapshot["future_outer"])["must_not_be_written"] = False
    raw_sources = cast(list[dict[str, object]], typed_dataset["sources"])
    cast(dict[str, object], raw_sources[0]["future_source_field"])["preserved"] = False
    assert dataset.response_snapshot == expected_snapshot

    artifact = dataset.to_file(tmp_path)

    assert artifact == tmp_path / "Source [source-id]"
    assert json.loads((artifact / "dataset.json").read_text(encoding="utf-8")) == expected_snapshot
    assert [request.url.path for request in recorder.requests] == ["/rpc/getDataset"]
    with pytest.raises(DataLensValidationError, match="already exists"):
        dataset.to_file(tmp_path)


def test_dataset_get_without_name_uses_key_for_artifact_identity(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.pop("name")
    recorder = RecordedTransport({"/rpc/getDataset": httpx.Response(200, json=snapshot)})

    dataset = _client(recorder).get.dataset(by_id="source-id")
    artifact = dataset.to_file(tmp_path)

    assert dataset.name == "Source"
    assert artifact == tmp_path / "Source [source-id]"


@pytest.mark.parametrize("raw_field", ["future-value", ["future-value"], None])
def test_dataset_get_preserves_top_level_raw_field_without_dto_collision(raw_field: object) -> None:
    snapshot = _snapshot()
    snapshot["raw"] = raw_field
    recorder = RecordedTransport({"/rpc/getDataset": httpx.Response(200, json=snapshot)})

    dataset = _client(recorder).get.dataset(by_id="source-id")

    assert dataset.response_snapshot["raw"] == raw_field
    assert dataset.raw["raw"] == raw_field


def test_dataset_to_file_rejects_short_mutation_response(tmp_path: Path) -> None:
    recorder = RecordedTransport({"/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"})})
    dataset = (
        _client(recorder)
        .raw.create.dataset(
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )
        .build()
    )

    with pytest.raises(DataLensValidationError, match=r"client\.get\.dataset"):
        dataset.to_file(tmp_path)

    assert [request.url.path for request in recorder.requests] == ["/rpc/createDataset"]


def test_dataset_empty_mapping_does_not_reconstruct_snapshot_from_dto_dump(tmp_path: Path) -> None:
    recorder = RecordedTransport({"/rpc/getDataset": httpx.Response(200, json={})})
    dataset = _client(recorder).get.dataset(by_id="source-id")

    assert dataset.response_snapshot == {}
    with pytest.raises(DataLensValidationError, match="complete 'dataset' content"):
        dataset.to_file(tmp_path)


def test_raw_dataset_create_uses_new_identity_and_preserves_only_mutable_content() -> None:
    snapshot = _snapshot()
    recorder = RecordedTransport({"/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"})})
    operation = _client(recorder).raw.create.dataset(
        response_snapshot=cast(Mapping[str, dl.JsonValue], snapshot),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    assert isinstance(operation, RawDatasetCreate)

    cast(dict[str, object], cast(dict[str, object], snapshot["dataset"])["future_dataset_field"])["preserved"] = False
    created = operation.build()

    assert created.id == "clone-id"
    assert created.name == "Clone"
    assert [request.url.path for request in recorder.requests] == ["/rpc/createDataset"]
    payload = recorder.request_json(0)
    assert payload["name"] == "Clone"
    assert payload["dir_path"] == "/target"
    assert not ({"id", "key", "revId", "permissions", "future_outer"} & payload.keys())
    dataset_payload = cast(dict[str, object], payload["dataset"])
    assert cast(dict[str, object], dataset_payload["future_dataset_field"])["preserved"] is True
    assert cast(list[dict[str, object]], dataset_payload["sources"])[0]["id"] == "source-1"
    assert "name" not in dataset_payload
    assert "rls" not in dataset_payload
    assert "revision_id" not in dataset_payload
    assert dataset_payload["rls2"] == {"field-1": []}


def test_raw_dataset_create_from_file_reads_snapshot_eagerly(tmp_path: Path) -> None:
    source = dl.Dataset(
        id="source-id",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    recorder = RecordedTransport({"/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"})})
    operation = _client(recorder).raw.create.dataset.from_file(
        artifact,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    stored = cast(dict[str, object], json.loads((artifact / "dataset.json").read_text(encoding="utf-8")))
    cast(dict[str, object], stored["dataset"])["description"] = "Changed after command creation"
    (artifact / "dataset.json").write_text(json.dumps(stored), encoding="utf-8")

    operation.build()

    payload = recorder.request_json(0)
    assert cast(dict[str, object], payload["dataset"])["description"] == "Original"


def test_raw_dataset_update_uses_target_identity_and_one_rpc(tmp_path: Path) -> None:
    source_snapshot = _snapshot()
    target_snapshot = _snapshot(dataset_id="target-id", description="Target")
    response = _snapshot(dataset_id="target-id", description="Replacement")
    target_snapshot["name"] = "Target"
    target_snapshot["key"] = "target/folder/Target"
    response.pop("name")
    response.pop("key")
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=target_snapshot),
            "/rpc/updateDataset": httpx.Response(200, json=response),
        }
    )
    client = _client(recorder)
    target = client.get.dataset(by_id="target-id")
    artifact_source = dl.Dataset(
        id="source-id",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], source_snapshot),
    )
    artifact = artifact_source.to_file(tmp_path)

    operation = client.raw.replace.dataset.from_file(artifact, target=target)
    assert isinstance(operation, RawDatasetReplace)
    updated = operation.execute()

    assert updated.id == "target-id"
    assert updated.name == target.name == "Target"
    assert [request.url.path for request in recorder.requests] == ["/rpc/getDataset", "/rpc/updateDataset"]
    payload = recorder.request_json(1)
    assert payload["datasetId"] == "target-id"
    assert set(payload) == {"datasetId", "data"}
    data = cast(dict[str, object], payload["data"])
    dataset_payload = cast(dict[str, object], data["dataset"])
    assert dataset_payload["description"] == "Original"
    assert "name" not in dataset_payload
    assert "rls" not in dataset_payload
    assert "revision_id" not in dataset_payload


def test_raw_dataset_replace_uses_owned_snapshot_with_target_identity() -> None:
    source_snapshot = _snapshot()
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=_snapshot(dataset_id="target-id", description="Target")),
            "/rpc/updateDataset": httpx.Response(
                200,
                json=_snapshot(dataset_id="target-id", description="Original"),
            ),
        }
    )
    client = _client(recorder)
    target = client.get.dataset(by_id="target-id")
    operation = client.raw.replace.dataset(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], source_snapshot),
    )
    cast(dict[str, object], source_snapshot["dataset"])["description"] = "Changed after command creation"

    updated = operation.execute()

    assert updated.id == "target-id"
    assert updated.name == target.name == "Source"
    assert [request.url.path for request in recorder.requests] == ["/rpc/getDataset", "/rpc/updateDataset"]
    payload = recorder.request_json(1)
    assert payload["datasetId"] == "target-id"
    data = cast(dict[str, object], payload["data"])
    assert cast(dict[str, object], data["dataset"])["description"] == "Original"


def test_raw_dataset_namespace_defers_create_and_replace_until_terminal_call() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"}),
            "/rpc/updateDataset": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    client = _client(recorder)
    response_snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())

    create = client.raw.create.dataset(
        response_snapshot=response_snapshot,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dataset(
        target=dl.Dataset(
            id="target-id",
            name="Target",
            location=dl.EntryLocation.path("/existing"),
        ),
        response_snapshot=response_snapshot,
    )

    assert isinstance(create, RawDatasetCreate)
    assert isinstance(replace, RawDatasetReplace)
    assert recorder.requests == []

    created = create.build()
    updated = replace.execute()

    assert created.id == "clone-id"
    assert updated.id == "target-id"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createDataset",
        "/rpc/updateDataset",
    ]
    create_payload = recorder.request_json(0)
    update_payload = recorder.request_json(1)
    expected_content = _expected_dataset_content()
    assert create_payload == {
        "name": "Clone",
        "dataset": expected_content,
        "dir_path": "/target",
    }
    assert update_payload == {
        "datasetId": "target-id",
        "data": {"dataset": expected_content},
    }


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_dataset_builder_owns_prevalidated_snapshot_view(boundary: str) -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"}),
            "/rpc/updateDataset": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    snapshot = artifacts.DatasetSnapshotView.from_raw(cast(Mapping[str, dl.JsonValue], _snapshot()))
    client = _client(recorder)
    terminal: Callable[[], dl.Dataset]
    if boundary == "create":
        terminal = client.raw.create.dataset(
            response_snapshot=snapshot,
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        ).build
    else:
        terminal = client.raw.replace.dataset(
            target=dl.Dataset(id="target-id", name="Target"),
            response_snapshot=snapshot,
        ).execute

    snapshot.dataset["description"] = "Changed after builder creation"
    cast(dict[str, dl.JsonValue], snapshot.dataset["future_dataset_field"])["preserved"] = False

    terminal()

    request = recorder.request_json(0)
    data = request if boundary == "create" else cast(dict[str, object], request["data"])
    payload = cast(dict[str, object], data["dataset"])
    assert payload["description"] == "Original"
    assert payload["future_dataset_field"] == {"preserved": True}


@pytest.mark.parametrize("boundary", ["create", "replace"])
def test_raw_dataset_builder_revalidates_forged_snapshot_view_before_http(boundary: str) -> None:
    recorder = RecordedTransport({})
    forged = artifacts.DatasetSnapshotView(
        snapshot={"dataset": {}},
        dataset={},
    )
    client = _client(recorder)

    def construct_with_forged_snapshot() -> None:
        if boundary == "create":
            client.raw.create.dataset(
                response_snapshot=forged,
                name="Clone",
                location=dl.EntryLocation.path("/target"),
            )
        else:
            client.raw.replace.dataset(
                target=dl.Dataset(id="target-id", name="Target"),
                response_snapshot=forged,
            )

    with pytest.raises(DataLensValidationError, match="source id"):
        construct_with_forged_snapshot()

    assert recorder.requests == []


def test_raw_dataset_normalizes_each_snapshot_once_before_deferred_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normalization_count = 0

    def counting_normalize_json_object(
        value: object,
        *,
        context: str = "JSON object",
    ) -> dict[str, dl.JsonValue]:
        nonlocal normalization_count
        normalization_count += 1
        return normalize_json_object(value, context=context)

    monkeypatch.setattr(artifacts, "normalize_json_object", counting_normalize_json_object)
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"}),
            "/rpc/updateDataset": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    client = _client(recorder)
    snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())

    create = client.raw.create.dataset(
        response_snapshot=snapshot,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dataset(
        target=dl.Dataset(id="target-id"),
        response_snapshot=snapshot,
    )

    assert normalization_count == 2

    create.build()
    replace.execute()

    assert normalization_count == 2


def test_raw_dataset_file_snapshot_is_recaptured_at_builder_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dl.Dataset(
        id="source-id",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    normalization_count = 0

    def counting_normalize_json_object(
        value: object,
        *,
        context: str = "JSON object",
    ) -> dict[str, dl.JsonValue]:
        nonlocal normalization_count
        normalization_count += 1
        return normalize_json_object(value, context=context)

    monkeypatch.setattr(artifacts, "normalize_json_object", counting_normalize_json_object)
    monkeypatch.setattr(json_io, "normalize_json_object", counting_normalize_json_object)
    recorder = RecordedTransport({"/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"})})

    create = _client(recorder).raw.create.dataset.from_file(
        artifact,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )

    assert normalization_count == 2

    create.build()

    assert normalization_count == 2


def test_raw_dataset_namespace_file_methods_use_the_same_artifact(tmp_path: Path) -> None:
    source = dl.Dataset(
        id="source-id",
        name="Source",
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )
    artifact = source.to_file(tmp_path)
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": httpx.Response(200, json={"id": "clone-id"}),
            "/rpc/updateDataset": httpx.Response(200, json={"id": "target-id"}),
        }
    )
    client = _client(recorder)

    create = client.raw.create.dataset.from_file(
        artifact,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dataset.from_file(
        artifact,
        target=dl.Dataset(id="target-id", name="Target"),
    )
    assert recorder.requests == []

    create.build()
    replace.execute()

    create_payload = recorder.request_json(0)
    update_payload = recorder.request_json(1)
    assert cast(dict[str, object], create_payload["dataset"]) == cast(
        dict[str, object],
        cast(dict[str, object], update_payload["data"])["dataset"],
    )


def test_dataset_typed_and_raw_builders_have_separate_surfaces() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)
    create = client.raw.create.dataset(
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dataset(
        target=dl.Dataset(id="target-id"),
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )

    assert not hasattr(create, "description")
    assert not hasattr(replace, "description")


def test_raw_dataset_replace_captures_target_identity_before_target_mutation() -> None:
    recorder = RecordedTransport({"/rpc/updateDataset": httpx.Response(200, json={"id": "target-id"})})
    client = _client(recorder)
    original_location = dl.EntryLocation.path("/original")
    target = dl.Dataset(
        id="target-id",
        name="Original target",
        installation="yacloud",
        location=original_location,
    )
    replace = client.raw.replace.dataset(
        target=target,
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )

    target.id = "mutated-id"
    target.name = "Mutated target"
    target.location = dl.EntryLocation.path("/mutated")
    updated = replace.execute()

    assert recorder.request_json(0)["datasetId"] == "target-id"
    assert updated.id == "target-id"
    assert updated.name == "Original target"
    assert updated.location == original_location


def test_raw_dataset_replace_rejects_target_installation_mismatch_before_http() -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(DataLensValidationError, match=r"'enterprise'.*'yacloud'"):
        client.raw.replace.dataset(
            target=dl.Dataset(id="target-id", installation="enterprise"),
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
        )

    assert recorder.requests == []


def test_raw_dataset_terminal_calls_repeat_mutations() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createDataset": [
                httpx.Response(200, json={"id": "clone-1"}),
                httpx.Response(200, json={"id": "clone-2"}),
            ],
            "/rpc/updateDataset": [
                httpx.Response(200, json={"id": "target-id"}),
                httpx.Response(200, json={"id": "target-id"}),
            ],
        }
    )
    client = _client(recorder)
    snapshot = cast(Mapping[str, dl.JsonValue], _snapshot())
    create = client.raw.create.dataset(
        response_snapshot=snapshot,
        name="Clone",
        location=dl.EntryLocation.path("/target"),
    )
    replace = client.raw.replace.dataset(
        target=dl.Dataset(id="target-id"),
        response_snapshot=snapshot,
    )

    assert create.build().id == "clone-1"
    assert create.build().id == "clone-2"
    assert replace.execute().id == "target-id"
    assert replace.execute().id == "target-id"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/createDataset",
        "/rpc/createDataset",
        "/rpc/updateDataset",
        "/rpc/updateDataset",
    ]


def test_dataset_response_snapshot_is_excluded_from_repr_and_equality() -> None:
    first = dl.Dataset(
        id="dataset-id",
        response_snapshot={"secret_marker": "first"},
    )
    second = replace(first, response_snapshot={"secret_marker": "second"})

    assert first == second
    assert "secret_marker" not in repr(first)
    assert "first" not in repr(first)


def test_raw_dataset_rejects_incomplete_snapshot_before_builder_or_http(tmp_path: Path) -> None:
    recorder = RecordedTransport({})
    client = _client(recorder)

    with pytest.raises(DataLensValidationError, match="complete 'dataset' content"):
        client.raw.create.dataset(
            response_snapshot={"id": "source-id"},
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )

    assert recorder.requests == []

    with pytest.raises(DataLensValidationError, match="source id"):
        client.raw.create.dataset(
            response_snapshot={"dataset": {}},
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )

    assert recorder.requests == []

    artifact = tmp_path / "Incomplete [source-id]"
    artifact.mkdir()
    (artifact / "dataset.json").write_text('{"id": "source-id"}', encoding="utf-8")
    with pytest.raises(DataLensValidationError, match="complete 'dataset' content"):
        client.raw.create.dataset.from_file(
            artifact,
            name="Clone",
            location=dl.EntryLocation.path("/target"),
        )

    assert recorder.requests == []
