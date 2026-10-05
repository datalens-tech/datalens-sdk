from __future__ import annotations

from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from importlib import import_module
import json
from types import ModuleType
from typing import cast

import httpx
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC
from datalens_sdk import client as client_module
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.spark_application import SparkApplicationAPI, SparkApplicationService
from datalens_sdk.client import DataLensClientBase
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.lakehouse_operation import LakehouseTimestamp
from datalens_sdk.domain.spark_application import (
    SparkApplication,
    SparkApplicationLogOptions,
    SparkApplicationLogPage,
    SparkApplicationLogPager,
)
from datalens_sdk.domain.spark_cluster import (
    SparkCluster,
    SparkClusterConfig,
    SparkClusterDependencies,
    SparkFixedScalePolicy,
    SparkResourcePoolConfig,
    SparkResourcePoolsConfig,
)
from datalens_sdk.errors import BadRequestError, DataLensValidationError, DTOValidationError, InvalidResponseError
from datalens_sdk.http import DataLensHTTPClient


def _cluster(*, cluster_id: str = "managed", installation: str = "yacloud") -> SparkCluster:
    pool = SparkResourcePoolConfig(resource_preset_id="preset", scale_policy=SparkFixedScalePolicy(size=1))
    return SparkCluster(
        id="entry",
        cluster_id=cluster_id,
        installation=installation,
        location=EntryLocation.collection("collection"),
        cloud_environment_id="environment",
        name="cluster",
        description="",
        labels={},
        config=SparkClusterConfig(
            spark_version="3.5",
            resource_pools=SparkResourcePoolsConfig(driver=pool, executor=pool),
            dependencies=SparkClusterDependencies(pip_packages=(), deb_packages=()),
            logging=None,
        ),
        health="ALIVE",
        status="RUNNING",
        entry_id="entry",
        raw={},
    )


def _application(
    *, cluster_id: str = "managed", installation: str = "yacloud", application_id: str = "application"
) -> SparkApplication:
    return SparkApplication(
        id=application_id,
        cluster_id=cluster_id,
        installation=installation,
        name="application",
        created_by="user",
        status="RUNNING",
        connect_url="",
        catalogs=(),
        created_at=LakehouseTimestamp("1", 0),
        started_at=None,
        finished_at=None,
        spec=None,
        raw={},
    )


def test_log_pager_yields_exact_fragments_and_pages_without_prefetch() -> None:
    pages = (
        SparkApplicationLogPage("", "A"),
        SparkApplicationLogPage("one\r\ntwo\n", "B"),
        SparkApplicationLogPage("☃ last", ""),
    )
    loads = 0

    def loader() -> Iterator[SparkApplicationLogPage]:
        nonlocal loads
        loads += 1
        yield from pages

    pager = SparkApplicationLogPager(loader)
    assert loads == 0
    assert tuple(pager) == ("", "one\r\ntwo\n", "☃ last")
    assert tuple(pager.pages()) == pages
    assert loads == 2


def test_log_page_and_options_are_frozen_slotted_values() -> None:
    page = SparkApplicationLogPage("", "")
    options = SparkApplicationLogOptions.create(
        installation="yacloud", cluster="managed", application="application", page_size=0, page_token=""
    )
    assert options == SparkApplicationLogOptions("managed", "application", 0, "")
    assert (
        SparkApplicationLogOptions.create(
            installation="yacloud", cluster="managed", application="application"
        ).page_token
        is None
    )
    for value, field_name in ((page, "content"), (options, "cluster_id")):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(value, field_name, "changed")


def test_log_options_validate_application_model_against_raw_and_model_clusters() -> None:
    assert (
        SparkApplicationLogOptions.create(
            installation="yacloud", cluster="managed", application=_application()
        ).application_id
        == "application"
    )
    assert (
        SparkApplicationLogOptions.create(
            installation="yacloud", cluster=_cluster(), application=_application()
        ).cluster_id
        == "managed"
    )
    for cluster, application in (
        ("", "application"),
        ("managed", ""),
        ("managed", _application(cluster_id="other")),
        (_cluster(), _application(cluster_id="other")),
        (_cluster(installation="enterprise"), _application()),
        ("managed", _application(installation="enterprise")),
        ("managed", _application(application_id="")),
        ("managed", _application(installation="")),
        ("managed", cast(str, 42)),
    ):
        with pytest.raises(DataLensValidationError):
            SparkApplicationLogOptions.create(installation="yacloud", cluster=cluster, application=application)


class _Transport:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, f"unexpected request: {request.url.path}"
        return self.responses.pop(0)

    def bodies(self) -> list[dict[str, object]]:
        return [cast(dict[str, object], json.loads(request.content)) for request in self.requests]


def _service(transport: _Transport) -> tuple[DataLensHTTPClient, SparkApplicationService]:
    client = DataLensHTTPClient(
        installation="yacloud",
        sdk_version="test",
        base_url="https://spark.test",
        transport=httpx.MockTransport(transport.handle),
    )
    return client, SparkApplicationService(installation="yacloud", api=SparkApplicationAPI(client))


def _log(content: str, token: str, **extra: object) -> httpx.Response:
    return httpx.Response(200, json={"content": content, "nextPageToken": token, **extra})


def test_log_requests_preserve_omitted_and_explicit_empty_options() -> None:
    transport = _Transport([_log("first", ""), _log("second", "")])
    client, service = _service(transport)
    with client:
        omitted = service.list_spark_application_log(
            SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
        )
        explicit = service.list_spark_application_log(
            SparkApplicationLogOptions.create(
                installation="yacloud", cluster="managed", application="application", page_size=0, page_token=""
            )
        )
        iterator = iter(explicit)
        assert transport.requests == []
        assert tuple(omitted) == ("first",)
        assert next(iterator) == "second"
    assert transport.bodies() == [
        {"clusterId": "managed", "applicationId": "application"},
        {"clusterId": "managed", "applicationId": "application", "pageSize": 0, "pageToken": ""},
    ]


def test_log_empty_and_multiline_fragments_are_not_end_markers() -> None:
    responses = [_log("", "A", futureField=True), _log("one\r\ntwo\n", "B"), _log("☃ last", "")]
    transport = _Transport(responses * 2)
    client, service = _service(transport)
    with client:
        pager = service.list_spark_application_log(
            SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
        )
        assert tuple(pager) == ("", "one\r\ntwo\n", "☃ last")
        assert tuple(pager.pages()) == (
            SparkApplicationLogPage("", "A"),
            SparkApplicationLogPage("one\r\ntwo\n", "B"),
            SparkApplicationLogPage("☃ last", ""),
        )
    assert [body.get("pageToken") for body in transport.bodies()] == [None, "A", "B", None, "A", "B"]
    assert all(request.url.path == "/rpc/listSparkApplicationLog" for request in transport.requests)


def test_log_interleaved_and_abandoned_traversals_restart_original_options() -> None:
    transport = _Transport(
        [_log("first", "A"), _log("other", "B"), _log("again", "A"), _log("last", ""), _log("restart", "")]
    )
    client, service = _service(transport)
    with client:
        pager = service.list_spark_application_log(
            SparkApplicationLogOptions.create(
                installation="yacloud", cluster="managed", application="application", page_token="resume"
            )
        )
        first, second = pager.pages(), pager.pages()
        assert next(first).content == "first"
        assert next(first).content == "other"
        assert next(second).content == "again"
        assert next(first).content == "last"
        assert tuple(pager) == ("restart",)
    assert [body["pageToken"] for body in transport.bodies()] == ["resume", "A", "resume", "B", "resume"]


@pytest.mark.parametrize(
    ("initial", "responses", "requested"),
    [
        ("A", ["A"], ["A"]),
        ("A", ["B", "A"], ["A", "B"]),
        (None, ["A", "B", "A"], [None, "A", "B"]),
    ],
)
def test_log_cycles_fail_before_replaying_nonempty_tokens(
    initial: str | None, responses: list[str], requested: list[str | None]
) -> None:
    transport = _Transport([_log("fragment", token) for token in responses])
    client, service = _service(transport)
    with client, pytest.raises(InvalidResponseError, match="listSparkApplicationLog"):
        tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(
                    installation="yacloud", cluster="managed", application="application", page_token=initial
                )
            )
        )
    assert [body.get("pageToken") for body in transport.bodies()] == requested


@pytest.mark.parametrize(
    ("cluster_id", "application_id", "page_size", "page_token"),
    [
        ("managed", "application", -1, None),
        ("managed", "application", 1048577, None),
        ("x" * 51, "application", None, None),
        ("managed", "x" * 51, None, None),
        ("managed", "application", None, "x" * 201),
    ],
)
def test_log_generated_request_bounds_fail_without_http(
    cluster_id: str, application_id: str, page_size: int | None, page_token: str | None
) -> None:
    transport = _Transport([])
    client, service = _service(transport)
    with client, pytest.raises(DTOValidationError, match="listSparkApplicationLog"):
        next(
            iter(
                service.list_spark_application_log(
                    SparkApplicationLogOptions.create(
                        installation="yacloud",
                        cluster=cluster_id,
                        application=application_id,
                        page_size=page_size,
                        page_token=page_token,
                    )
                )
            )
        )
    assert transport.requests == []


def test_log_unhashable_initial_token_fails_dto_validation_without_http() -> None:
    transport = _Transport([])
    client, service = _service(transport)
    options = SparkApplicationLogOptions.create(
        installation="yacloud", cluster="managed", application="application", page_token=cast(str, ["A"])
    )
    with client, pytest.raises(DTOValidationError, match="listSparkApplicationLog"):
        next(iter(service.list_spark_application_log(options)))
    assert transport.requests == []


def test_log_maximum_request_values_reach_http() -> None:
    transport = _Transport([_log("", "")])
    client, service = _service(transport)
    with client:
        assert tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(
                    installation="yacloud",
                    cluster="x" * 50,
                    application="x" * 50,
                    page_size=1048576,
                    page_token="x" * 200,
                )
            )
        ) == ("",)
    assert transport.bodies() == [
        {"clusterId": "x" * 50, "applicationId": "x" * 50, "pageSize": 1048576, "pageToken": "x" * 200}
    ]


@pytest.mark.parametrize("field", ["content", "nextPageToken"])
@pytest.mark.parametrize("bad", ["missing", None, 42])
def test_log_required_response_strings_fail_with_rpc_context(field: str, bad: object) -> None:
    wire: dict[str, object] = {"content": "fragment", "nextPageToken": ""}
    if bad == "missing":
        wire.pop(field)
    else:
        wire[field] = bad
    transport = _Transport([httpx.Response(200, json=wire)])
    client, service = _service(transport)
    with client, pytest.raises((DTOValidationError, InvalidResponseError), match="listSparkApplicationLog"):
        tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
            )
        )
    assert len(transport.requests) == 1


def test_log_response_rejects_python_field_name_instead_of_required_wire_alias() -> None:
    transport = _Transport([httpx.Response(200, json={"content": "fragment", "next_page_token": ""})])
    client, service = _service(transport)
    with client, pytest.raises(DTOValidationError, match="listSparkApplicationLog"):
        tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
            )
        )
    assert len(transport.requests) == 1


def test_log_overlong_response_token_fails_before_followup() -> None:
    transport = _Transport([_log("fragment", "x" * 201)])
    client, service = _service(transport)
    with client, pytest.raises(DTOValidationError, match="listSparkApplicationLog"):
        tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
            )
        )
    assert len(transport.requests) == 1


def test_log_each_fragment_retries_transient_failures() -> None:
    unavailable = httpx.Response(503, json={"code": "TEMPORARY", "message": "retry"})
    transport = _Transport([unavailable, _log("", "A"), unavailable, _log("done", "")])
    client, service = _service(transport)
    with client:
        assert tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
            )
        ) == ("", "done")
    assert transport.bodies() == [
        {"clusterId": "managed", "applicationId": "application"},
        {"clusterId": "managed", "applicationId": "application"},
        {"clusterId": "managed", "applicationId": "application", "pageToken": "A"},
        {"clusterId": "managed", "applicationId": "application", "pageToken": "A"},
    ]


def test_log_backend_error_retains_code_and_request_id() -> None:
    transport = _Transport(
        [httpx.Response(400, json={"code": "BAD_LOG", "message": "bad"}, headers={"x-request-id": "request-1"})]
    )
    client, service = _service(transport)
    with client, pytest.raises(BadRequestError) as exc:
        tuple(
            service.list_spark_application_log(
                SparkApplicationLogOptions.create(installation="yacloud", cluster="managed", application="application")
            )
        )
    assert exc.value.context.code == "BAD_LOG"
    assert exc.value.context.request_id == "request-1"
    assert len(transport.requests) == 1


def test_log_action_uses_managed_cluster_and_application_ids() -> None:
    transport = _Transport([_log("one", ""), _log("two", ""), _log("three", "")])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        assert tuple(client.list.spark_application_log(cluster=_cluster(), application=_application())) == ("one",)
        assert tuple(client.list.spark_application_log(cluster="managed", application=_application())) == ("two",)
        assert tuple(client.list.spark_application_log(cluster=_cluster(), application="application")) == ("three",)
    assert transport.bodies() == [{"clusterId": "managed", "applicationId": "application"}] * 3


def test_log_action_rejects_known_reference_errors_before_http() -> None:
    transport = _Transport([])
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(transport.handle))
    with client:
        for cluster, application in (
            ("", "application"),
            ("managed", ""),
            (_cluster(cluster_id=""), "application"),
            (_cluster(installation="enterprise"), "application"),
            ("managed", _application(application_id="")),
            ("managed", _application(cluster_id="other")),
            ("managed", _application(installation="enterprise")),
        ):
            with pytest.raises(DataLensValidationError):
                client.list.spark_application_log(cluster=cluster, application=application)
    assert transport.requests == []


def test_log_is_unavailable_without_spark_service(monkeypatch: pytest.MonkeyPatch) -> None:
    class DtoWithoutSparkApplications(ModuleType):
        def __getattr__(self, name: str) -> object:
            if "SparkApplication" in name:
                raise AssertionError(f"Unexpected SparkApplications DTO access: {name}")
            return getattr(generated_dto, name)

    original_import = import_module
    dto_stub = DtoWithoutSparkApplications("datalens_sdk._generated.dto")
    monkeypatch.setattr(
        client_module,
        "import_module",
        lambda name: dto_stub if name == "datalens_sdk._generated.dto" else original_import(name),
    )

    def unexpected_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("SparkApplications service initialized")

    monkeypatch.setattr(SparkApplicationService, "__init__", unexpected_service)
    transport = _Transport([])
    action_name = "spark_application_log"
    with DataLensClientEnterprise(
        auth=None, base_url="https://enterprise.test", transport=httpx.MockTransport(transport.handle)
    ) as client:
        with pytest.raises(AttributeError) as exc:
            getattr(client.list, action_name)
        assert type(exc.value) is AttributeError

    class YaTeamStyleClient(DataLensClientBase):
        INSTALLATION = "yacloud"
        DEFAULT_BASE_URL = "https://yateam.test"

    with YaTeamStyleClient(auth=None, transport=httpx.MockTransport(transport.handle)) as client:
        with pytest.raises(AttributeError) as exc:
            getattr(client.list, action_name)
        assert type(exc.value) is AttributeError
    assert transport.requests == []
