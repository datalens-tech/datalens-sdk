from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import cast

import httpx
from pydantic import ValidationError
import pytest
from typing_extensions import assert_type

import datalens_sdk as dl
from datalens_sdk._generated import dto
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.domain.entry_types import EntryBranch, EntryUpdateMode
from datalens_sdk.domain.raw_resource import RawDatasetReplace
from datalens_sdk.errors import (
    BadRequestError,
    DataLensAPIError,
    DataLensValidationError,
    ForbiddenError,
    InvalidResponseError,
    NotFoundError,
)


def _snapshot(*, description: str = "Original", revision: str = "published-a") -> dict[str, object]:
    return {
        "id": "dataset-id",
        "name": "Dataset",
        "key": "folder/Dataset",
        "revId": revision,
        "savedId": "saved-b",
        "publishedId": "published-a",
        "dataset": {
            "description": description,
            "sources": [],
            "source_avatars": [],
            "avatar_relations": [],
            "result_schema": [],
            "obligatory_filters": [],
            "rls2": {},
        },
    }


def _client(
    installation: str, routes: dict[str, list[dict[str, object] | httpx.Response]]
) -> tuple[DataLensClientBase, list[dict[str, object]]]:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"path": request.url.path, "body": body})
        responses = routes[request.url.path]
        response = responses.pop(0)
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)

    client_class = dl.DataLensClientYC if installation == "yacloud" else dl.DataLensClientEnterprise
    return client_class(auth=None, base_url="http://test", transport=httpx.MockTransport(handler)), requests


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
@pytest.mark.parametrize("mode", [None, "save", "publish"])
def test_dataset_typed_update_sends_mode_only_in_update_data(installation: str, mode: EntryUpdateMode | None) -> None:
    client, requests = _client(
        installation,
        {
            "/rpc/getDataset": [_snapshot()],
            "/rpc/validateDataset": [_snapshot(description="Typed B")],
            "/rpc/updateDataset": [_snapshot(description="Typed B", revision="new-b")],
        },
    )
    dataset = client.get.dataset(by_id="dataset-id")
    update = dataset.update.description("Typed B")
    if mode is not None:
        assert_type(update.mode(mode), dl.DatasetUpdate)
    result = update.execute()

    assert result.description == "Typed B"
    assert result.rev_id == "new-b"
    assert [request["path"] for request in requests] == [
        "/rpc/getDataset",
        "/rpc/validateDataset",
        "/rpc/updateDataset",
    ]
    validated_body = cast(dict[str, object], requests[1]["body"])
    assert "mode" not in cast(dict[str, object], validated_body["data"])
    expected_data: dict[str, object] = {"dataset": _snapshot(description="Typed B")["dataset"]}
    expected_data["mode"] = mode or "save"
    assert requests[2]["body"] == {"datasetId": "dataset-id", "data": expected_data}


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
@pytest.mark.parametrize("mode", [None, "save", "publish"])
@pytest.mark.parametrize("from_file", [False, True], ids=["snapshot", "from_file"])
def test_dataset_raw_replace_uses_current_target_revision_without_entry_revision_selectors(
    installation: str, mode: EntryUpdateMode | None, from_file: bool, tmp_path: Path
) -> None:
    source = _snapshot(description="Raw B", revision="source-entry")
    source["id"] = "source-id"
    cast(dict[str, object], source["dataset"]).update(rev_id="nested-source-entry", revision_id="source-token")
    old_target = _snapshot(description="Old target", revision="historical-entry")
    cast(dict[str, object], old_target["dataset"])["revision_id"] = "old-target-token"
    fresh_target = _snapshot(description="Target A")
    cast(dict[str, object], fresh_target["dataset"])["revision_id"] = "fresh-target-token"
    client, requests = _client(
        installation,
        {
            "/rpc/getDataset": [old_target, fresh_target],
            "/rpc/updateDataset": [_snapshot(description="Raw B", revision="new-b")],
        },
    )
    target = client.get.dataset(by_id="dataset-id", rev_id="historical-entry")
    before = json.dumps(source)
    if from_file:
        artifact = dl.Dataset(
            id="source-id", name="Source", response_snapshot=cast(Mapping[str, dl.JsonValue], source)
        ).to_file(tmp_path)
        update = client.raw.replace.dataset.from_file(artifact, target=target)
    else:
        update = client.raw.replace.dataset(target=target, response_snapshot=cast(Mapping[str, dl.JsonValue], source))
    if mode is not None:
        assert_type(update.mode(mode), RawDatasetReplace)
    assert requests == [{"path": "/rpc/getDataset", "body": {"datasetId": "dataset-id", "rev_id": "historical-entry"}}]

    result = update.execute()

    assert result.id == "dataset-id"
    assert result.description == "Raw B"
    assert result.rev_id == "new-b"
    expected_content = cast(dict[str, object], _snapshot(description="Raw B")["dataset"])
    expected_content["revision_id"] = "fresh-target-token"
    assert requests[1:] == [
        {"path": "/rpc/getDataset", "body": {"datasetId": "dataset-id"}},
        {
            "path": "/rpc/updateDataset",
            "body": {"datasetId": "dataset-id", "data": {"dataset": expected_content, "mode": mode or "save"}},
        },
    ]
    assert json.dumps(source) == before
    if from_file:
        assert json.loads((artifact / "dataset.json").read_text(encoding="utf-8"))["dataset"] == source["dataset"]


@pytest.mark.parametrize("has_revision_key", [False, True], ids=["absent", "null"])
def test_raw_dataset_replace_without_internal_revision_preserves_legacy_payload(has_revision_key: bool) -> None:
    target = _snapshot()
    if has_revision_key:
        cast(dict[str, object], target["dataset"])["revision_id"] = None
    source = _snapshot(description="Replacement")
    cast(dict[str, object], source["dataset"])["revision_id"] = "source-token"
    client, requests = _client(
        "enterprise",
        {"/rpc/getDataset": [target], "/rpc/updateDataset": [_snapshot(description="Replacement")]},
    )

    client.raw.replace.dataset(
        target=dl.Dataset(id="dataset-id"),
        response_snapshot=cast(Mapping[str, dl.JsonValue], source),
    ).execute()

    assert requests == [
        {"path": "/rpc/getDataset", "body": {"datasetId": "dataset-id"}},
        {
            "path": "/rpc/updateDataset",
            "body": {
                "datasetId": "dataset-id",
                "data": {"dataset": _snapshot(description="Replacement")["dataset"], "mode": "save"},
            },
        },
    ]


@pytest.mark.parametrize(
    ("read_status", "read_payload", "expected_error"),
    [
        (403, {"message": "Forbidden"}, ForbiddenError),
        (404, {"message": "Not found"}, NotFoundError),
        (200, {"dataset": "malformed"}, InvalidResponseError),
        (200, {"dataset": {"revision_id": 42}}, InvalidResponseError),
    ],
)
def test_raw_dataset_replace_stops_when_target_read_fails(
    read_status: int, read_payload: dict[str, object], expected_error: type[DataLensAPIError]
) -> None:
    client, requests = _client(
        "enterprise",
        {
            "/rpc/getDataset": [httpx.Response(read_status, json=read_payload)],
            "/rpc/updateDataset": [_snapshot()],
        },
    )
    update = client.raw.replace.dataset(
        target=dl.Dataset(id="dataset-id"),
        response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()),
    )

    with pytest.raises(expected_error):
        update.execute()

    assert requests == [{"path": "/rpc/getDataset", "body": {"datasetId": "dataset-id"}}]


@pytest.mark.parametrize("has_component_errors", [False, True])
def test_raw_dataset_replace_reports_revision_mismatch_without_retry(has_component_errors: bool) -> None:
    target = _snapshot()
    cast(dict[str, object], target["dataset"])["revision_id"] = "token-before-concurrent-edit"
    code = "ERR.DS_API.DATASET_REVISION_MISMATCH"
    error: dict[str, object] = {"code": code, "message": "Dataset revision mismatch"}
    if has_component_errors:
        error["details"] = {"data": {"dataset": {"component_errors": {"items": []}}}}
    client, requests = _client(
        "enterprise",
        {
            "/rpc/getDataset": [target],
            "/rpc/updateDataset": [httpx.Response(400, json=error, headers={"x-request-id": "conflict-request"})],
        },
    )

    with pytest.raises(BadRequestError) as exc:
        client.raw.replace.dataset(
            target=dl.Dataset(id="dataset-id", location=dl.EntryLocation.workbook("target-workbook")),
            response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot(description="Replacement")),
        ).mode("publish").execute()

    assert exc.value.context.code == code
    assert exc.value.context.status_code == 400
    assert exc.value.context.request_id == "conflict-request"
    assert exc.value.context.attempts == 1
    assert requests[0] == {
        "path": "/rpc/getDataset",
        "body": {"datasetId": "dataset-id", "workbookId": "target-workbook"},
    }
    assert [request["path"] for request in requests] == ["/rpc/getDataset", "/rpc/updateDataset"]
    body = cast(dict[str, object], requests[-1]["body"])
    data = cast(dict[str, object], body["data"])
    assert data["mode"] == "publish"
    assert cast(dict[str, object], data["dataset"])["revision_id"] == "token-before-concurrent-edit"


@pytest.mark.parametrize("branch", ["saved", "published"])
def test_dataset_branch_resolves_pointer_then_reads_exact_revision(branch: EntryBranch) -> None:
    revision = "saved-b" if branch == "saved" else "published-a"
    client, requests = _client(
        "yacloud",
        {
            "/rpc/getDataset": [
                _snapshot(revision="published-a" if branch == "saved" else "saved-b"),
                _snapshot(description=branch, revision=revision),
            ]
        },
    )

    dataset = client.get.dataset(by_id="dataset-id", branch=branch, workbook_id="workbook-id")

    assert dataset.description == branch
    assert dataset.rev_id == revision
    assert [request["body"] for request in requests] == [
        {"datasetId": "dataset-id", "workbookId": "workbook-id"},
        {"datasetId": "dataset-id", "workbookId": "workbook-id", "rev_id": revision},
    ]


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
@pytest.mark.parametrize("branch", ["saved", "published"])
@pytest.mark.parametrize("clean", [False, True], ids=["different-pointers", "same-pointers"])
def test_dataset_branch_reuses_response_already_at_selected_revision(
    installation: str, branch: EntryBranch, clean: bool
) -> None:
    revision = "saved-b" if branch == "saved" else "published-a"
    snapshot = _snapshot(description="Already loaded", revision=revision)
    if clean:
        snapshot["savedId"] = snapshot["publishedId"] = revision
    client, requests = _client(installation, {"/rpc/getDataset": [snapshot]})

    dataset = client.get.dataset(by_id="dataset-id", branch=branch, workbook_id="workbook-id")

    assert dataset.rev_id == revision
    assert dataset.description == "Already loaded"
    assert dataset.response_snapshot == snapshot
    assert [request["body"] for request in requests] == [{"datasetId": "dataset-id", "workbookId": "workbook-id"}]


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
@pytest.mark.parametrize("mode", [None, "save", "publish"], ids=["default", "save", "publish"])
def test_dataset_mode_only_update_preserves_loaded_draft_content_without_validation(
    installation: str, mode: EntryUpdateMode | None
) -> None:
    draft = _snapshot(description="Stored draft B", revision="saved-b")
    client, requests = _client(
        installation,
        {
            "/rpc/getDataset": [draft],
            "/rpc/updateDataset": [_snapshot(description="Stored draft B", revision="new-c")],
        },
    )
    dataset = client.get.dataset(by_id="dataset-id", branch="saved")
    update = dataset.update
    if mode is not None:
        update.mode(mode)
    result = update.execute()

    assert result.description == "Stored draft B"
    assert result.rev_id == "new-c"
    assert [request["path"] for request in requests] == ["/rpc/getDataset", "/rpc/updateDataset"]
    assert requests[-1]["body"] == {
        "datasetId": "dataset-id",
        "data": {"dataset": draft["dataset"], "mode": mode or "save"},
    }


@pytest.mark.parametrize("branch", ["saved", "published", "invalid"])
def test_dataset_explicit_revision_overrides_branch_with_warning(branch: str) -> None:
    client, requests = _client("yacloud", {"/rpc/getDataset": [_snapshot(revision="historical-c")]})

    with pytest.warns(UserWarning, match="branch is ignored"):
        dataset = client.get.dataset(by_id="dataset-id", branch=cast(EntryBranch, branch), rev_id="historical-c")

    assert dataset.rev_id == "historical-c"
    assert [request["body"] for request in requests] == [{"datasetId": "dataset-id", "rev_id": "historical-c"}]


@pytest.mark.parametrize("branch", ["saved", "published"])
def test_dataset_branch_rejects_missing_pointer_without_falling_back(branch: EntryBranch) -> None:
    snapshot = _snapshot()
    snapshot.pop("savedId" if branch == "saved" else "publishedId")
    client, requests = _client("yacloud", {"/rpc/getDataset": [snapshot]})

    with pytest.raises(DataLensValidationError, match="revision pointer"):
        client.get.dataset(by_id="dataset-id", branch=branch)

    assert len(requests) == 1


def test_dataset_modes_and_branches_reject_invalid_values_before_http() -> None:
    client, requests = _client("yacloud", {})
    target = dl.Dataset(id="dataset-id", installation="yacloud")
    raw = client.raw.replace.dataset(target=target, response_snapshot=cast(Mapping[str, dl.JsonValue], _snapshot()))

    for update in (target.update, raw):
        with pytest.raises(DataLensValidationError, match="mode"):
            update.mode(cast(EntryUpdateMode, "invalid"))
    with pytest.raises(DataLensValidationError, match="branch"):
        client.get.dataset(by_id="dataset-id", branch=cast(EntryBranch, "invalid"))
    assert requests == []


def test_generated_dataset_update_dto_places_mode_inside_strict_data_envelope() -> None:
    content = {"description": "B", "future_field": {"preserved": True}}
    assert dto.DatasetUpdateDTO(
        dataset_id="dataset-id", data=dto.DatasetUpdateDataDTO(dataset=content)
    ).to_payload() == {"datasetId": "dataset-id", "data": {"dataset": content}}
    assert dto.DatasetUpdateDTO(
        dataset_id="dataset-id", data=dto.DatasetUpdateDataDTO(dataset=content, mode="save")
    ).to_payload() == {"datasetId": "dataset-id", "data": {"dataset": content, "mode": "save"}}
    assert dto.DatasetUpdateDTO.model_validate(
        {"dataset_id": "dataset-id", "data": {"dataset": content, "mode": "publish"}}
    ).to_payload() == {"datasetId": "dataset-id", "data": {"dataset": content, "mode": "publish"}}
    with pytest.raises(ValidationError):
        dto.DatasetUpdateDTO.model_validate({"dataset_id": "dataset-id", "data": {"dataset": content}, "mode": "save"})
    with pytest.raises(ValidationError):
        dto.DatasetUpdateDataDTO.model_validate({"dataset": content, "mode": "invalid"})
    with pytest.raises(ValidationError):
        dto.DatasetUpdateDataDTO.model_validate({"dataset": content, "revId": "existing"})
