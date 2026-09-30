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
from datalens_sdk.errors import DataLensValidationError


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
    installation: str, routes: dict[str, list[dict[str, object]]]
) -> tuple[DataLensClientBase, list[dict[str, object]]]:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"path": request.url.path, "body": body})
        responses = routes[request.url.path]
        return httpx.Response(200, json=responses.pop(0))

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
    if mode is not None:
        expected_data["mode"] = mode
    assert requests[2]["body"] == {"datasetId": "dataset-id", "data": expected_data}


@pytest.mark.parametrize("installation", ["enterprise", "yacloud"])
@pytest.mark.parametrize("mode", [None, "save", "publish"])
@pytest.mark.parametrize("from_file", [False, True], ids=["snapshot", "from_file"])
def test_dataset_raw_replace_creates_revision_from_content_without_revision_selectors(
    installation: str, mode: EntryUpdateMode | None, from_file: bool, tmp_path: Path
) -> None:
    source = _snapshot(description="Raw B", revision="source-revision")
    cast(dict[str, object], source["dataset"])["rev_id"] = "nested-source-revision"
    client, requests = _client(
        installation,
        {
            "/rpc/getDataset": [_snapshot(description="Target A")],
            "/rpc/updateDataset": [_snapshot(description="Raw B", revision="new-b")],
        },
    )
    target = client.get.dataset(by_id="dataset-id")
    if from_file:
        artifact = dl.Dataset(
            id="source-id", name="Source", response_snapshot=cast(Mapping[str, dl.JsonValue], source)
        ).to_file(tmp_path)
        update = client.raw.replace.dataset.from_file(artifact, target=target)
    else:
        update = client.raw.replace.dataset(target=target, response_snapshot=cast(Mapping[str, dl.JsonValue], source))
    if mode is not None:
        assert_type(update.mode(mode), RawDatasetReplace)
    result = update.execute()

    assert result.id == "dataset-id"
    assert result.description == "Raw B"
    assert result.rev_id == "new-b"
    expected_data: dict[str, object] = {"dataset": _snapshot(description="Raw B")["dataset"]}
    if mode is not None:
        expected_data["mode"] = mode
    assert requests[-1]["body"] == {"datasetId": "dataset-id", "data": expected_data}
    assert [request["path"] for request in requests] == ["/rpc/getDataset", "/rpc/updateDataset"]


@pytest.mark.parametrize("branch", ["saved", "published"])
def test_dataset_branch_resolves_pointer_then_reads_exact_revision(branch: EntryBranch) -> None:
    revision = "saved-b" if branch == "saved" else "published-a"
    client, requests = _client(
        "yacloud", {"/rpc/getDataset": [_snapshot(), _snapshot(description=branch, revision=revision)]}
    )

    dataset = client.get.dataset(by_id="dataset-id", branch=branch, workbook_id="workbook-id")

    assert dataset.description == branch
    assert dataset.rev_id == revision
    assert [request["body"] for request in requests] == [
        {"datasetId": "dataset-id", "workbookId": "workbook-id"},
        {"datasetId": "dataset-id", "workbookId": "workbook-id", "rev_id": revision},
    ]


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
