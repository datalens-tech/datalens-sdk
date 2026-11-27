from collections.abc import Callable
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk._generated import dto
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.domain.data import DatasetDataQuery
from datalens_sdk.domain.entry_types import EntryBranch, EntryUpdateMode

_CONTENT = {"description": "source dataset", "sources": []}
_SNAPSHOT: dict[str, object] = {"id": "ds-1", "name": "Dataset", "key": "folder/Dataset", "dataset": _CONTENT}
_DATA: dict[str, object] = {"schema": [], "rows": []}


class RecordedTransport:
    def __init__(self, routes: dict[str, dict[str, object] | Callable[[dict[str, object]], dict[str, object]]]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, dict[str, object]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = cast(dict[str, object], json.loads(request.content))
        self.requests.append((path, body))
        response = self.routes[path]
        return httpx.Response(200, json=response(body) if callable(response) else response)


@pytest.fixture(params=[dl.DataLensClientEnterprise, dl.DataLensClientYC])
def client(
    request: pytest.FixtureRequest,
) -> Callable[[RecordedTransport], DataLensClientBase]:
    cls = cast(type[dl.DataLensClientEnterprise] | type[dl.DataLensClientYC], request.param)

    def build(recorder: RecordedTransport) -> DataLensClientBase:
        return cls(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    return build


def test_get_dataset_data_sends_explicit_workbook_context(
    client: Callable[[RecordedTransport], DataLensClientBase],
) -> None:
    recorder = RecordedTransport({"/rpc/getDatasetData": _DATA})
    sdk = client(recorder)
    assert DatasetDataQuery.create(dataset_id="ds-1", columns=["amount"], workbook_id="wb-reader").workbook_id == (
        "wb-reader"
    )
    assert sdk.data.get_dataset_data(dataset_id="ds-1", columns=["amount"], workbook_id="wb-reader") == dl.DatasetData(
        schema=(), rows=()
    )
    assert recorder.requests == [
        ("/rpc/getDatasetData", {"datasetId": "ds-1", "columns": ["amount"], "limit": 500, "workbookId": "wb-reader"}),
    ]


@pytest.mark.parametrize(
    ("snapshot", "read_context", "expected_context"),
    [
        (_SNAPSHOT, "wb-read", "wb-read"),
        ({**_SNAPSHOT, "workbook_id": "wb-owner"}, None, "wb-owner"),
        ({**_SNAPSHOT, "workbook_id": "wb-owner"}, "wb-read", "wb-read"),
    ],
)
def test_bound_dataset_data_reuses_read_workbook_context(
    client: Callable[[RecordedTransport], DataLensClientBase],
    snapshot: dict[str, object],
    read_context: str | None,
    expected_context: str,
) -> None:
    recorder = RecordedTransport({"/rpc/getDataset": snapshot, "/rpc/getDatasetData": _DATA})
    dataset = client(recorder).get.dataset(by_id="ds-1", workbook_id=read_context)
    if "workbook_id" not in snapshot:
        assert dataset.location == dl.EntryLocation.path("folder")
    dataset.get_dataset_data(columns=["amount"])
    dataset.get_dataset_data(columns=["amount"], workbook_id="wb-override")
    dataset.get_dataset_data(columns=["amount"])
    assert [body.get("workbookId") for _, body in recorder.requests] == [
        read_context,
        expected_context,
        "wb-override",
        expected_context,
    ]


def test_bound_dataset_context_is_per_instance(
    client: Callable[[RecordedTransport], DataLensClientBase],
) -> None:
    recorder = RecordedTransport({"/rpc/getDataset": _SNAPSHOT, "/rpc/getDatasetData": _DATA})
    sdk = client(recorder)
    first = sdk.get.dataset(by_id="ds-1", workbook_id="wb-first")
    second = sdk.get.dataset(by_id="ds-1", workbook_id="wb-second")
    for dataset in (first, second, first):
        dataset.get_dataset_data(columns=["amount"])
    assert [body.get("workbookId") for _, body in recorder.requests[2:]] == ["wb-first", "wb-second", "wb-first"]


@pytest.mark.parametrize("branch", ["published", "saved"])
def test_dataset_revision_read_retains_workbook_context(
    client: Callable[[RecordedTransport], DataLensClientBase],
    branch: EntryBranch,
) -> None:
    def read(body: dict[str, object]) -> dict[str, object]:
        return {
            **_SNAPSHOT,
            "publishedId": "published-1",
            "savedId": "saved-1",
            "revId": body.get("rev_id", "published-1"),
        }

    recorder = RecordedTransport({"/rpc/getDataset": read, "/rpc/getDatasetData": _DATA})
    dataset = client(recorder).get.dataset(by_id="ds-1", workbook_id="wb-read", branch=branch)
    assert dataset.rev_id == f"{branch}-1"
    dataset.get_dataset_data(columns=["amount"])
    assert [body.get("workbookId") for _, body in recorder.requests] == ["wb-read"] * len(recorder.requests)


def test_empty_data_workbook_context_is_rejected_before_request(
    client: Callable[[RecordedTransport], DataLensClientBase],
) -> None:
    recorder = RecordedTransport({})
    with pytest.raises(dl.DTOValidationError, match="workbookId"):
        client(recorder).data.get_dataset_data(dataset_id="ds-1", columns=["amount"], workbook_id="")
    assert recorder.requests == []


@pytest.mark.parametrize(
    ("mode", "override", "name_only"),
    [("publish", None, False), ("save", "wb-other", False), ("save", None, True)],
)
def test_typed_update_sends_same_workbook_context_for_validation_and_write(
    client: Callable[[RecordedTransport], DataLensClientBase],
    mode: EntryUpdateMode,
    override: str | None,
    name_only: bool,
) -> None:
    validated = {**_CONTENT, "description": "new description"}
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": _SNAPSHOT,
            "/rpc/validateDataset": {"dataset": validated},
            "/rpc/updateDataset": {"id": "ds-1"},
            "/rpc/getDatasetData": _DATA,
        },
    )
    dataset = client(recorder).get.dataset(by_id="ds-1", workbook_id="wb-read")
    update = dataset.update.mode(mode)
    if override is not None:
        update.workbook_id(override)
    if name_only:
        update.name("Renamed")
    else:
        update.description("new description")
    result = update.execute()
    result.get_dataset_data(columns=["amount"])
    resolved = override or "wb-read"
    expected: list[tuple[str, dict[str, object]]] = [
        ("/rpc/getDataset", {"datasetId": "ds-1", "workbookId": "wb-read"})
    ]
    if not name_only:
        expected.append(
            (
                "/rpc/validateDataset",
                {
                    "datasetId": "ds-1",
                    "workbookId": resolved,
                    "data": {
                        "dataset": _CONTENT,
                        "updates": [{"action": "update_description", "description": "new description"}],
                    },
                },
            )
        )
    expected.extend(
        [
            (
                "/rpc/updateDataset",
                {
                    "datasetId": "ds-1",
                    "workbookId": resolved,
                    "data": {"dataset": {**_CONTENT, "name": "Renamed"} if name_only else validated, "mode": mode},
                },
            ),
            ("/rpc/getDatasetData", {"datasetId": "ds-1", "columns": ["amount"], "limit": 500, "workbookId": resolved}),
        ]
    )
    assert recorder.requests == expected


@pytest.mark.parametrize("read_context", [None, "wb-target"])
@pytest.mark.parametrize("from_file", [False, True])
def test_raw_replacement_uses_workbook_context_from_target_not_snapshot(
    client: Callable[[RecordedTransport], DataLensClientBase],
    tmp_path: Path,
    from_file: bool,
    read_context: str | None,
) -> None:
    snapshot = cast(
        dict[str, dl.JsonValue],
        {**_SNAPSHOT, "id": "source-id", "workbook_id": "source-workbook"},
    )
    recorder = RecordedTransport(
        {"/rpc/getDataset": _SNAPSHOT, "/rpc/updateDataset": {"id": "ds-1"}, "/rpc/getDatasetData": _DATA},
    )
    sdk = client(recorder)
    target = sdk.get.dataset(by_id="ds-1", workbook_id=read_context)
    factory = sdk.raw.replace.dataset
    if from_file:
        artifact = dl.Dataset(id="source-id", name="Source", response_snapshot=snapshot).to_file(tmp_path)
        update = factory.from_file(artifact, target=target, workbook_id="wb-override" if read_context else None)
    else:
        update = factory(target=target, response_snapshot=snapshot)
    result = update.mode("publish").execute()
    result.get_dataset_data(columns=["amount"])
    context = ("wb-override" if from_file else read_context) if read_context else None
    target_scope = {"workbookId": context} if context is not None else {}
    assert recorder.requests[1:] == [
        ("/rpc/updateDataset", {"datasetId": "ds-1", "data": {"dataset": _CONTENT, "mode": "publish"}, **target_scope}),
        ("/rpc/getDatasetData", {"datasetId": "ds-1", "columns": ["amount"], "limit": 500, **target_scope}),
    ]
    assert snapshot["workbook_id"] == "source-workbook"


@pytest.mark.parametrize("workbook_id", [None, "wb-destination"])
def test_create_validation_uses_workbook_from_destination(
    client: Callable[[RecordedTransport], DataLensClientBase],
    workbook_id: str | None,
) -> None:
    recorder = RecordedTransport(
        {"/rpc/validateDataset": {"dataset": _CONTENT}, "/rpc/createDataset": {"id": "ds-1"}},
    )
    location = dl.EntryLocation.workbook(workbook_id) if workbook_id else dl.EntryLocation.path("folder")
    client(recorder).create.dataset(name="Dataset", location=location).add_calculation(
        name="Constant",
        formula="1",
        kind="MEASURE",
        guid="calc-1",
    ).build()
    validate, create = recorder.requests
    assert validate[0] == "/rpc/validateDataset"
    if workbook_id is None:
        assert "workbookId" not in validate[1]
    else:
        assert validate[1]["workbookId"] == workbook_id
    assert validate[1]["datasetId"] == ""
    assert create[0] == "/rpc/createDataset"
    assert create[1].get("workbook_id") == workbook_id


@pytest.mark.parametrize("workbook_id", [None, "wb-reader"])
def test_mutation_dtos_serialize_optional_context(workbook_id: str | None) -> None:
    scope = {"workbookId": workbook_id} if workbook_id is not None else {}
    validate_data: dict[str, object] = {"dataset": {}, "updates": []}
    assert dto.DatasetValidateDTO(dataset_id="ds-1", data=validate_data, workbook_id=workbook_id).to_payload() == {
        "datasetId": "ds-1",
        "data": validate_data,
        **scope,
    }
    assert dto.DatasetUpdateDTO(
        dataset_id="ds-1",
        data=dto.DatasetUpdateDataDTO(dataset={}, mode="publish"),
        workbook_id=workbook_id,
    ).to_payload() == {"datasetId": "ds-1", "data": {"dataset": {}, "mode": "publish"}, **scope}
