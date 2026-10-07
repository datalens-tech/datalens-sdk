from __future__ import annotations

import json

import httpx
import pytest

from datalens_sdk import (
    CloudEnvironmentStorageObjectMetadata,
    CloudEnvironmentStorageSignedUrl,
    DataLensClientYC,
    DTOValidationError,
    InvalidResponseError,
    LakehouseTimestamp,
)
from datalens_sdk.domain.navigation import Page


@pytest.mark.parametrize("direction", ["upload", "download"])
def test_bucket_signed_url_preserves_payload_and_hides_credentials_in_repr(direction: str) -> None:
    requests: list[httpx.Request] = []
    url = "https://storage.example.com/object?signature=secret"

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"url": url, "futureField": True})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client:
        if direction == "upload":
            result = client.create.bucket_upload_url("environment-1", "data/файл.csv", "0", "1B2M2Y8AsgTpgAmY7PhCfg==")
            expected = {
                "cloudEnvironmentId": "environment-1",
                "path": "data/файл.csv",
                "size": "0",
                "contentMd5": "1B2M2Y8AsgTpgAmY7PhCfg==",
            }
        else:
            result = client.create.bucket_download_url("environment-1", "data/файл.csv")
            expected = {"cloudEnvironmentId": "environment-1", "path": "data/файл.csv"}

    assert isinstance(result, CloudEnvironmentStorageSignedUrl)
    assert result.url == url
    assert url not in repr(result)
    assert "secret" not in repr(result)
    assert [(request.url.path, json.loads(request.content)) for request in requests] == [
        (f"/rpc/createBucket{direction.title()}Url", expected)
    ]


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ({"seconds": "1780000000", "nanos": 250.5}, LakehouseTimestamp(seconds="1780000000", nanos=250.5)),
        ({"seconds": "1780000000"}, LakehouseTimestamp(seconds="1780000000")),
        (None, None),
    ],
)
def test_bucket_metadata_maps_optional_timestamp(timestamp: object, expected: LakehouseTimestamp | None) -> None:
    requests: list[httpx.Request] = []
    response: dict[str, object] = {"size": "9007199254740993", "futureField": True}
    if timestamp is not None:
        response["lastModified"] = timestamp

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response)

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client:
        metadata = client.get.bucket_object_metadata("environment-1", "data.csv")

    assert metadata == CloudEnvironmentStorageObjectMetadata(size="9007199254740993", last_modified=expected)
    assert [(request.url.path, json.loads(request.content)) for request in requests] == [
        ("/rpc/getBucketObjectMetadata", {"cloudEnvironmentId": "environment-1", "path": "data.csv"})
    ]


def test_bucket_objects_pager_is_lazy_and_resumes_with_prefix_and_page_size() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content)["pageToken"] == "resume":
            return httpx.Response(200, json={"keys": ["data/one.csv"], "nextPageToken": "next"})
        return httpx.Response(200, json={"keys": ["data/two.csv"], "nextPageToken": ""})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client:
        pager = client.list.bucket_objects("environment-1", "data/", 1, "resume")
        assert requests == []
        pages = list(pager.pages())

    assert pages == [
        Page(items=("data/one.csv",), next_page_token="next"),
        Page(items=("data/two.csv",), next_page_token=""),
    ]
    assert [(request.url.path, json.loads(request.content)) for request in requests] == [
        (
            "/rpc/listBucketObjects",
            {"cloudEnvironmentId": "environment-1", "prefix": "data/", "pageSize": 1, "pageToken": token},
        )
        for token in ("resume", "next")
    ]


def test_bucket_objects_default_request_omits_optional_filters_and_flattens_keys() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": ["one.csv", "two.csv"], "nextPageToken": ""})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client:
        assert list(client.list.bucket_objects("environment-1")) == ["one.csv", "two.csv"]

    assert [json.loads(request.content) for request in requests] == [
        {"cloudEnvironmentId": "environment-1", "pageSize": 1000}
    ]


def test_bucket_objects_rejects_repeated_continuation_token() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": ["one.csv"], "nextPageToken": "resume"})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client, pytest.raises(InvalidResponseError, match="repeated nextPageToken"):
        list(client.list.bucket_objects("environment-1", page_token="resume"))

    assert len(requests) == 1


@pytest.mark.parametrize("page_size", [-1, 1001])
def test_bucket_objects_rejects_invalid_page_size_before_http(page_size: int) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": [], "nextPageToken": ""})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))
    with client, pytest.raises(DTOValidationError):
        list(client.list.bucket_objects("environment-1", page_size=page_size))

    assert requests == []
