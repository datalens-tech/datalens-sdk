from __future__ import annotations

from collections.abc import Sequence
from dataclasses import FrozenInstanceError
import json
from typing import Literal, cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain import EntryRevision

EntryKind = Literal["connection", "dataset", "dashboard", "wizard", "ql", "editor"]
EntryObject = dl.Connection | dl.Dataset | dl.Dashboard | dl.WizardChart | dl.QLChart | dl.EditorChart
Client = dl.DataLensClientYC | dl.DataLensClientEnterprise
ENTRY_KINDS: tuple[EntryKind, ...] = ("connection", "dataset", "dashboard", "wizard", "ql", "editor")


class RecordedTransport:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/rpc/getRevisions"
        assert self._responses, "Unexpected revision request"
        response = self._responses.pop(0)
        response.request = request
        return response

    def bodies(self) -> list[dict[str, object]]:
        return [cast(dict[str, object], json.loads(request.content)) for request in self.requests]


def _client(recorder: RecordedTransport, installation: str = "yacloud") -> Client:
    client_type = dl.DataLensClientYC if installation == "yacloud" else dl.DataLensClientEnterprise
    return client_type(auth=None, base_url="https://datalens.test", transport=httpx.MockTransport(recorder.handler))


def _entry(kind: EntryKind, client: Client | None, *, entry_id: str | None = "entry-1") -> EntryObject:
    raw: dict[str, object] = {"revId": "historical-revision"}
    if kind == "connection":
        return dl.Connection(
            id=entry_id, type="postgres", raw=raw, _operations=client._connection_service if client else None
        )
    if kind == "dataset":
        return dl.Dataset(id=entry_id, raw=raw, _operations=client._dataset_service if client else None)
    if kind == "dashboard":
        return dl.Dashboard(id=entry_id, raw=raw, _operations=client._dashboard_service if client else None)
    if kind == "wizard":
        return dl.WizardChart(id=entry_id, raw=raw, _operations=client._chart_service if client else None)
    if kind == "ql":
        return dl.QLChart(id=entry_id, raw=raw, _operations=client._chart_service if client else None)
    return dl.EditorChart(id=entry_id, raw=raw, _operations=client._chart_service if client else None)


def _revision(rev_id: str = "rev-1", *, is_saved: bool = False, is_published: bool = False) -> dict[str, object]:
    return {
        "revId": rev_id,
        "updatedAt": "date format is not specified",
        "updatedBy": "user-1",
        "isSaved": is_saved,
        "isPublished": is_published,
    }


def _page(rev_ids: Sequence[str] = (), *, token: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"entries": [_revision(rev_id) for rev_id in rev_ids]}
    if token is not None:
        body["nextPageToken"] = token
    return httpx.Response(200, json=body)


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
@pytest.mark.parametrize("kind", ENTRY_KINDS)
def test_all_entry_models_get_revisions_for_their_entry_id(kind: EntryKind, installation: str) -> None:
    recorder = RecordedTransport([_page(["rev-1"])])
    entry = _entry(kind, _client(recorder, installation), entry_id=f"{kind}-1")

    pager = entry.get_revisions(page_size=1, page_token="opaque/+==", rev_ids=["rev-1"])

    assert recorder.requests == []
    assert list(pager) == [EntryRevision("rev-1", "date format is not specified", "user-1", False, False)]
    assert recorder.bodies() == [
        {"entryId": f"{kind}-1", "pageSize": 1, "pageToken": "opaque/+==", "revIds": ["rev-1"]}
    ]


def test_revisions_are_lazy_and_do_not_prefetch() -> None:
    recorder = RecordedTransport([_page(["rev-1", "rev-2"], token="next"), _page(["rev-3"])])
    pager = _entry("connection", _client(recorder)).get_revisions()
    iterator = iter(pager)

    assert recorder.requests == []
    assert next(iterator).rev_id == "rev-1"
    assert len(recorder.requests) == 1
    assert next(iterator).rev_id == "rev-2"
    assert len(recorder.requests) == 1
    assert next(iterator).rev_id == "rev-3"
    assert len(recorder.requests) == 2
    with pytest.raises(StopIteration):
        next(iterator)
    assert recorder.bodies() == [
        {"entryId": "entry-1", "pageSize": 200},
        {"entryId": "entry-1", "pageSize": 200, "pageToken": "next"},
    ]


def test_revision_pages_preserve_empty_continuations_and_opaque_tokens() -> None:
    recorder = RecordedTransport([_page(token="next"), _page(["rev-2"], token="opaque/+=="), _page()])
    pager = _entry("connection", _client(recorder)).get_revisions(page_size=2, rev_ids=["rev-1", "rev-2"])
    iterator = pager.pages()

    assert recorder.requests == []
    first = next(iterator)
    assert first.items == ()
    assert first.next_page_token == "next"
    assert len(recorder.requests) == 1
    pages = [first, *iterator]
    assert [[revision.rev_id for revision in page.items] for page in pages] == [[], ["rev-2"], []]
    assert [page.next_page_token for page in pages] == ["next", "opaque/+==", None]
    common = {"entryId": "entry-1", "pageSize": 2, "revIds": ["rev-1", "rev-2"]}
    assert recorder.bodies() == [common, {**common, "pageToken": "next"}, {**common, "pageToken": "opaque/+=="}]


@pytest.mark.parametrize("initial_token", [None, ""])
@pytest.mark.parametrize("rev_ids", [[], ["rev-1"]])
def test_empty_revision_token_ends_pagination(initial_token: str | None, rev_ids: list[str]) -> None:
    recorder = RecordedTransport([_page(rev_ids, token="")])
    pages = list(_entry("connection", _client(recorder)).get_revisions(page_token=initial_token).pages())

    assert len(pages) == 1
    assert [revision.rev_id for revision in pages[0].items] == rev_ids
    assert pages[0].next_page_token == ""
    assert len(recorder.requests) == 1


def test_revision_pager_restarts_each_traversal_without_caching() -> None:
    recorder = RecordedTransport([_page(token="next"), _page(["rev-1"]), _page(token="next"), _page(["rev-2"])])
    pager = _entry("connection", _client(recorder)).get_revisions(page_token="start")

    assert [revision.rev_id for revision in pager] == ["rev-1"]
    assert [revision.rev_id for revision in pager] == ["rev-2"]
    assert [body["pageToken"] for body in recorder.bodies()] == ["start", "next", "start", "next"]


def test_revision_pager_iterators_have_independent_token_state() -> None:
    recorder = RecordedTransport(
        [_page(["first-1"], token="next"), _page(["second-1"], token="next"), _page(["first-2"]), _page(["second-2"])]
    )
    pager = _entry("connection", _client(recorder)).get_revisions()
    first = iter(pager)
    second = iter(pager)

    assert next(first).rev_id == "first-1"
    assert next(second).rev_id == "second-1"
    assert next(first).rev_id == "first-2"
    assert next(second).rev_id == "second-2"
    assert list(first) == list(second) == []
    assert [body.get("pageToken") for body in recorder.bodies()] == [None, None, "next", "next"]


@pytest.mark.parametrize(
    ("initial_token", "tokens"),
    [(None, ["A", "A"]), (None, ["A", "B", "A"]), ("start", ["start"])],
)
def test_revision_token_cycles_fail_after_yielding_the_page(initial_token: str | None, tokens: list[str]) -> None:
    recorder = RecordedTransport([_page([f"rev-{index}"], token=token) for index, token in enumerate(tokens)])
    pages = _entry("connection", _client(recorder)).get_revisions(page_token=initial_token).pages()

    for index in range(len(tokens)):
        assert next(pages).items[0].rev_id == f"rev-{index}"
    with pytest.raises(dl.InvalidResponseError, match=r"getRevisions.*repeated nextPageToken"):
        next(pages)
    assert len(recorder.requests) == len(tokens)


def test_revision_filters_are_snapshotted_before_lazy_iteration() -> None:
    recorder = RecordedTransport([_page(token="next"), _page(), _page()])
    rev_ids = ["rev-1", "rev-2"]
    pager = _entry("connection", _client(recorder)).get_revisions(rev_ids=rev_ids)
    rev_ids[:] = ["changed"]

    assert list(pager) == []
    assert list(pager) == []
    assert [body["revIds"] for body in recorder.bodies()] == [["rev-1", "rev-2"]] * 3


@pytest.mark.parametrize("page_size", [1, 200])
@pytest.mark.parametrize("filter_size", [1, 1000])
def test_revision_argument_bounds_and_unrestricted_id_strings(page_size: int, filter_size: int) -> None:
    recorder = RecordedTransport([_page()])
    rev_ids = [""] * filter_size

    assert list(_entry("connection", _client(recorder)).get_revisions(page_size=page_size, rev_ids=rev_ids)) == []
    assert recorder.bodies() == [{"entryId": "entry-1", "pageSize": page_size, "revIds": rev_ids}]


@pytest.mark.parametrize("page_size", [0, 201, 1000, 1001, -1, True, False, 1.5, "1", None])
def test_invalid_revision_page_sizes_fail_eagerly(page_size: object) -> None:
    recorder = RecordedTransport([])
    entry = _entry("connection", _client(recorder))

    with pytest.raises(dl.DataLensValidationError):
        entry.get_revisions(page_size=cast(int, page_size))
    assert recorder.requests == []


@pytest.mark.parametrize("rev_ids", [[], (), ["rev"] * 1001, "rev", b"rev", [None], [1], {"rev": "id"}, 1])
def test_invalid_revision_filters_fail_eagerly(rev_ids: object) -> None:
    recorder = RecordedTransport([])
    entry = _entry("connection", _client(recorder))

    with pytest.raises(dl.DataLensValidationError):
        entry.get_revisions(rev_ids=cast(Sequence[str], rev_ids))
    assert recorder.requests == []


@pytest.mark.parametrize("page_token", [False, 1, b"token", ["token"]])
def test_invalid_revision_page_tokens_fail_eagerly(page_token: object) -> None:
    recorder = RecordedTransport([])
    entry = _entry("connection", _client(recorder))

    with pytest.raises(dl.DataLensValidationError):
        entry.get_revisions(page_token=cast(str, page_token))
    assert recorder.requests == []


@pytest.mark.parametrize("kind", ENTRY_KINDS)
def test_unbound_entry_revision_access_fails_eagerly(kind: EntryKind) -> None:
    with pytest.raises(dl.DataLensConfigurationError):
        _entry(kind, None).get_revisions()


@pytest.mark.parametrize("kind", ENTRY_KINDS)
@pytest.mark.parametrize("entry_id", [None, ""])
def test_entry_revision_access_without_id_fails_eagerly(kind: EntryKind, entry_id: str | None) -> None:
    recorder = RecordedTransport([])

    with pytest.raises(dl.DataLensValidationError):
        _entry(kind, _client(recorder), entry_id=entry_id).get_revisions()
    assert recorder.requests == []


@pytest.mark.parametrize(("is_saved", "is_published"), [(False, False), (False, True), (True, False), (True, True)])
def test_revision_read_model_preserves_flags_and_date_and_ignores_unknown_fields(
    is_saved: bool, is_published: bool
) -> None:
    raw = {**_revision(is_saved=is_saved, is_published=is_published), "futureRevisionField": {"nested": True}}
    recorder = RecordedTransport([httpx.Response(200, json={"entries": [raw], "futureResponseField": []})])

    revision = next(iter(_entry("connection", _client(recorder)).get_revisions()))

    assert revision == EntryRevision("rev-1", "date format is not specified", "user-1", is_saved, is_published)
    with pytest.raises(FrozenInstanceError):
        revision.rev_id = "changed"  # type: ignore[misc]  # Exercise frozen dataclass at runtime.


@pytest.mark.parametrize("field", ["revId", "updatedAt", "updatedBy", "isSaved", "isPublished"])
@pytest.mark.parametrize("missing", [True, False])
def test_revision_response_fields_are_required_and_nonnullable(field: str, missing: bool) -> None:
    raw = _revision()
    if missing:
        del raw[field]
    else:
        raw[field] = None
    recorder = RecordedTransport([httpx.Response(200, json={"entries": [raw]})])

    with pytest.raises(dl.DTOValidationError, match="getRevisions"):
        list(_entry("connection", _client(recorder)).get_revisions())


@pytest.mark.parametrize("body", [{}, {"entries": None}, {"entries": [None]}, {"entries": [], "nextPageToken": 12}])
def test_malformed_revision_response_is_not_an_empty_history(body: dict[str, object]) -> None:
    recorder = RecordedTransport([httpx.Response(200, json=body)])

    with pytest.raises(dl.DTOValidationError, match="getRevisions"):
        list(_entry("connection", _client(recorder)).get_revisions())


def test_revision_api_error_preserves_code_and_request_id() -> None:
    recorder = RecordedTransport(
        [
            httpx.Response(
                403,
                json={"code": "ERR.US.PERMISSION_DENIED", "message": "Access denied"},
                headers={"x-request-id": "revision-request"},
            )
        ]
    )
    pager = _entry("connection", _client(recorder)).get_revisions()

    with pytest.raises(dl.ForbiddenError) as error:
        list(pager)
    assert error.value.context.code == "ERR.US.PERMISSION_DENIED"
    assert error.value.context.request_id == "revision-request"
    assert len(recorder.requests) == 1


def test_revision_reads_retry_transient_failures() -> None:
    recorder = RecordedTransport([httpx.Response(503, json={"message": "temporarily unavailable"}), _page(["rev-1"])])

    assert [revision.rev_id for revision in _entry("connection", _client(recorder)).get_revisions()] == ["rev-1"]
    assert recorder.bodies() == [{"entryId": "entry-1", "pageSize": 200}] * 2
