from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
import json
import subprocess
import threading
import time

import httpx
import jwt
import pytest

from datalens_sdk import (
    DataLensClientEnterprise,
    DataLensClientYC,
    DataLensConfigurationError,
    EnterpriseServiceAccountCredentialsAuthProvider,
    EntryLocation,
    NoAuthProvider,
    NotSupportedError,
    OAuthAuthProvider,
    StaticYCIAMAuthProvider,
    YCIAMAuthProvider,
    YCServiceAccountCredentialsAuthProvider,
)
from datalens_sdk.auth import _ExpiringToken

AUTH_ENV_NAMES = (
    "DATALENS_OAUTH_TOKEN",
    "DATALENS_ORG_ID",
    "DATALENS_YC_BIN",
    "DATALENS_YC_PROFILE",
)


@pytest.fixture(autouse=True)
def clear_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AUTH_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _read_attr(obj: object, name: str) -> object:
    return getattr(obj, name)


def test_oauth_provider_builds_authorization_header() -> None:
    auth = OAuthAuthProvider(token="token-1")

    assert auth.get_headers() == {"Authorization": "OAuth token-1"}


def test_oauth_provider_reads_default_token_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATALENS_OAUTH_TOKEN", "token-from-env")

    assert OAuthAuthProvider().get_headers() == {"Authorization": "OAuth token-from-env"}
    assert OAuthAuthProvider(token="explicit").get_headers() == {"Authorization": "OAuth explicit"}


def test_oauth_provider_requires_explicit_or_environment_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATALENS_OAUTH_TOKEN", raising=False)

    with pytest.raises(DataLensConfigurationError, match="DATALENS_OAUTH_TOKEN"):
        OAuthAuthProvider()


def test_yacloud_provider_builds_required_headers() -> None:
    auth = StaticYCIAMAuthProvider(token="token-1", org_id="org-1")

    assert auth.get_headers() == {
        "Authorization": "Bearer token-1",
        "x-dl-org-id": "org-1",
    }


def test_auth_provider_repr_hides_static_tokens() -> None:
    secret = "repr-secret-sentinel"
    oauth = OAuthAuthProvider(token=secret)
    iam = StaticYCIAMAuthProvider(token=secret, org_id="org-1")

    assert secret not in repr(oauth)
    assert "token_type='OAuth'" in repr(oauth)
    assert secret not in repr(iam)
    assert "org_id='org-1'" in repr(iam)


def test_cached_expiring_token_repr_hides_value() -> None:
    secret = "repr-secret-sentinel"
    token = _ExpiringToken(value=secret, expires_at=123.0)

    assert secret not in repr(token)
    assert "expires_at=123.0" in repr(token)


def test_no_auth_provider_builds_no_headers() -> None:
    assert NoAuthProvider().get_headers() == {}


def test_client_applies_auth_headers_and_public_sdk_version(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    distributions: list[str] = []

    def package_version(distribution: str) -> str:
        distributions.append(distribution)
        return "1.2.3"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg"})

    monkeypatch.setattr("datalens_sdk.client.version", package_version)
    client = DataLensClientYC(
        auth=StaticYCIAMAuthProvider(token="token-1", org_id="org-1"),
        transport=httpx.MockTransport(handler),
    )

    client.get.connection(by_id="conn-1")

    assert seen
    assert seen[0].headers["authorization"] == "Bearer token-1"
    assert seen[0].headers["x-dl-org-id"] == "org-1"
    assert seen[0].headers["x-dl-api-version"] == "3"
    assert seen[0].headers["user-agent"] == "datalens-sdk/1.2.3 (yacloud)"
    assert distributions == ["datalens-sdk"]


def test_client_uses_unknown_sdk_version_without_distribution_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def missing_package(distribution: str) -> str:
        assert distribution == "datalens-sdk"
        raise PackageNotFoundError(distribution)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg"})

    monkeypatch.setattr("datalens_sdk.client.version", missing_package)
    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handler))

    client.get.connection(by_id="conn-1")

    assert seen[0].headers["user-agent"] == "datalens-sdk/unknown (yacloud)"


def test_client_resolves_auth_headers_for_every_request() -> None:
    class RotatingAuthProvider:
        def __init__(self) -> None:
            self.calls = 0

        def get_headers(self) -> dict[str, str]:
            self.calls += 1
            return {"Authorization": f"Bearer token-{self.calls}"}

        async def get_headers_async(self) -> dict[str, str]:
            return self.get_headers()

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg"})

    provider = RotatingAuthProvider()
    client = DataLensClientYC(auth=provider, transport=httpx.MockTransport(handler))

    client.get.connection(by_id="conn-1")
    client.get.connection(by_id="conn-1")

    assert provider.calls == 2
    assert [request.headers["authorization"] for request in seen] == ["Bearer token-1", "Bearer token-2"]


def _expiry(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _access_token(expiry: float) -> str:
    return jwt.encode({"exp": expiry}, "test-secret-key-with-at-least-32-bytes", algorithm="HS256")


def test_enterprise_service_account_provider_signs_exchanges_and_caches_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_token = _access_token(2000.0)
    encoded_payloads: list[dict[str, object]] = []
    encoded_headers: list[dict[str, str]] = []
    exchange_requests: list[tuple[str, object, object]] = []

    def fake_encode(
        payload: dict[str, object],
        key: str,
        *,
        algorithm: str,
        headers: dict[str, str],
    ) -> str:
        assert key == "private-key"
        assert algorithm == "PS256"
        encoded_payloads.append(payload)
        encoded_headers.append(headers)
        return "signed-jwt"

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: object,
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        assert timeout.connect == 10.0
        exchange_requests.append((url, headers, json))
        return httpx.Response(
            200,
            json={"accessToken": access_token},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: 1000.0)
    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        base_url="https://provider.example.test",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )
    client = DataLensClientEnterprise(
        base_url="https://enterprise.example.test/prefix",
        auth=provider,
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
    )

    try:
        expected_headers = {"Authorization": f"Bearer {access_token}"}
        assert provider.get_headers() == expected_headers
        assert provider.get_headers() == expected_headers
        assert encoded_payloads == [{"iss": "sa-id", "iat": 1000, "exp": 1300}]
        assert encoded_headers == [{"kid": "key-id", "typ": "JWT"}]
        assert exchange_requests == [
            (
                "https://enterprise.example.test/rpc/exchangeServiceAccountToken",
                {"x-dl-api-version": "3"},
                {"saToken": "signed-jwt"},
            )
        ]
        assert "private-key" not in repr(provider)
        assert access_token not in repr(provider)
    finally:
        client.close()


def test_enterprise_service_account_provider_requires_base_url_when_used_standalone() -> None:
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    with pytest.raises(DataLensConfigurationError, match="use the provider with DataLensClientEnterprise"):
        provider.get_headers()


def test_enterprise_service_account_provider_refreshes_before_access_token_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    access_tokens = [_access_token(1120.0), _access_token(1240.0)]
    calls = 0

    def fake_encode(*_: object, **__: object) -> str:
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        nonlocal calls
        access_token = access_tokens[calls]
        calls += 1
        return httpx.Response(
            200,
            json={"accessToken": access_token},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: now[0])
    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        base_url="https://enterprise.example.test",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
        token_expiry_margin_seconds=30,
    )

    assert provider.get_headers() == {"Authorization": f"Bearer {access_tokens[0]}"}
    now[0] = 1091.0
    assert provider.get_headers() == {"Authorization": f"Bearer {access_tokens[1]}"}
    assert calls == 2


def test_enterprise_service_account_provider_supports_async_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    access_token = _access_token(time.time() + 3600)

    def fake_encode(*_: object, **__: object) -> str:
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"accessToken": access_token},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        base_url="https://enterprise.example.test",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    assert asyncio.run(provider.get_headers_async()) == {"Authorization": f"Bearer {access_token}"}


@pytest.mark.parametrize(
    ("base_url", "token_expiry_margin_seconds", "jwt_lifetime_seconds", "message"),
    [
        ("", 60, 300, "base URL must not be empty"),
        ("relative", 60, 300, "base URL must be absolute"),
        ("https://enterprise.example.test", -1, 300, "must not be negative"),
        ("https://enterprise.example.test", 60, 0, "must be between 1 and 600"),
        ("https://enterprise.example.test", 60, 601, "must be between 1 and 600"),
    ],
)
def test_enterprise_service_account_provider_validates_configuration(
    base_url: str,
    token_expiry_margin_seconds: int,
    jwt_lifetime_seconds: int,
    message: str,
) -> None:
    with pytest.raises(DataLensConfigurationError, match=message):
        EnterpriseServiceAccountCredentialsAuthProvider(
            base_url=base_url,
            key_id="key-id",
            service_account_id="sa-id",
            private_key="private-key",
            token_expiry_margin_seconds=token_expiry_margin_seconds,
            jwt_lifetime_seconds=jwt_lifetime_seconds,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "not an object"),
        ({}, "empty accessToken"),
        ({"accessToken": "not-a-jwt"}, "invalid accessToken JWT"),
        (
            {"accessToken": jwt.encode({}, "test-secret-key-with-at-least-32-bytes", algorithm="HS256")},
            "invalid exp claim",
        ),
        ({"accessToken": _access_token(999.0)}, "already expired"),
    ],
)
def test_enterprise_service_account_provider_rejects_invalid_exchange_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    message: str,
) -> None:
    def fake_encode(*_: object, **__: object) -> str:
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: 1000.0)
    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        base_url="https://enterprise.example.test",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    with pytest.raises(DataLensConfigurationError, match=message):
        provider.get_headers()


def test_enterprise_service_account_provider_rejects_invalid_exchange_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_encode(*_: object, **__: object) -> str:
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        return httpx.Response(200, text="not-json", request=httpx.Request("POST", url))

    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        base_url="https://enterprise.example.test",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    with pytest.raises(DataLensConfigurationError, match="invalid JSON"):
        provider.get_headers()


def test_enterprise_service_account_provider_surfaces_exchange_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_encode(*_: object, **__: object) -> str:
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = EnterpriseServiceAccountCredentialsAuthProvider(
        base_url="https://enterprise.example.test",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    with pytest.raises(httpx.HTTPStatusError):
        provider.get_headers()


def test_yc_iam_provider_fetches_with_profile_and_caches_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], object]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs.get("timeout")))
        if command[:4] == ["yc", "config", "get", "organization-id"]:
            return subprocess.CompletedProcess(command, 0, stdout="org-1\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "iam-1", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(profile="sdk")

    expected_headers = {"Authorization": "Bearer iam-1", "x-dl-org-id": "org-1"}
    assert provider.get_headers() == expected_headers
    assert provider.get_headers() == expected_headers
    assert calls == [
        (["yc", "config", "get", "organization-id", "--profile", "sdk"], 30.0),
        (["yc", "iam", "create-token", "--format", "json", "--profile", "sdk"], 30.0),
    ]


def test_yc_iam_provider_reads_cli_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1:4] == ["config", "get", "organization-id"]:
            return subprocess.CompletedProcess(command, 0, stdout="org-from-profile\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "iam-1", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    monkeypatch.setenv("DATALENS_YC_BIN", "custom-yc")
    monkeypatch.setenv("DATALENS_YC_PROFILE", "environment-profile")
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    headers = YCIAMAuthProvider().get_headers()

    assert headers["x-dl-org-id"] == "org-from-profile"
    assert calls == [
        ["custom-yc", "config", "get", "organization-id", "--profile", "environment-profile"],
        ["custom-yc", "iam", "create-token", "--format", "json", "--profile", "environment-profile"],
    ]


def test_yc_iam_provider_reads_org_id_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "iam-1", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    monkeypatch.setenv("DATALENS_ORG_ID", "environment-org")
    monkeypatch.setenv("DATALENS_YC_PROFILE", "environment-profile")
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    headers = YCIAMAuthProvider().get_headers()

    assert headers["x-dl-org-id"] == "environment-org"
    assert calls == [
        ["yc", "iam", "create-token", "--format", "json", "--profile", "environment-profile"],
    ]


def test_yc_iam_provider_explicit_values_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "iam-1", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    monkeypatch.setenv("DATALENS_ORG_ID", "environment-org")
    monkeypatch.setenv("DATALENS_YC_BIN", "custom-yc")
    monkeypatch.setenv("DATALENS_YC_PROFILE", "environment-profile")
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    headers = YCIAMAuthProvider(org_id="explicit-org", profile="explicit-profile").get_headers()

    assert headers["x-dl-org-id"] == "explicit-org"
    assert calls == [
        ["custom-yc", "iam", "create-token", "--format", "json", "--profile", "explicit-profile"],
    ]


def test_yc_iam_provider_treats_empty_environment_values_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1:4] == ["config", "get", "organization-id"]:
            return subprocess.CompletedProcess(command, 0, stdout="org-from-profile\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "iam-1", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    for name in ("DATALENS_ORG_ID", "DATALENS_YC_BIN", "DATALENS_YC_PROFILE"):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    YCIAMAuthProvider().get_headers()

    assert calls == [
        ["yc", "config", "get", "organization-id"],
        ["yc", "iam", "create-token", "--format", "json"],
    ]


def test_yc_iam_provider_passes_custom_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    timeouts: list[object] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        timeouts.append(kwargs.get("timeout"))
        if command[:4] == ["yc", "config", "get", "organization-id"]:
            return subprocess.CompletedProcess(command, 0, stdout="org-1\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "iam-1", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(command_timeout_seconds=12.5)

    provider.get_headers()

    assert timeouts == [12.5, 12.5]


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("-inf"), float("nan")])
def test_yc_iam_provider_rejects_invalid_command_timeout(timeout: float) -> None:
    with pytest.raises(DataLensConfigurationError, match="finite positive"):
        YCIAMAuthProvider(org_id="org-1", command_timeout_seconds=timeout)


def test_yc_iam_provider_reports_org_discovery_timeout_without_command_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "timeout-secret-sentinel"

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 4.5, output=secret, stderr=secret)

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    with pytest.raises(DataLensConfigurationError, match="yc config get organization-id timed out") as error:
        YCIAMAuthProvider(command_timeout_seconds=4.5)

    assert secret not in str(error.value)


def test_yc_iam_provider_reports_token_timeout_without_command_output(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "timeout-secret-sentinel"

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 6.0, output=secret, stderr=secret)

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    with pytest.raises(DataLensConfigurationError, match="yc iam create-token timed out") as error:
        YCIAMAuthProvider(org_id="org-1", command_timeout_seconds=6.0).get_headers()

    assert secret not in str(error.value)


def test_yc_iam_provider_requires_org_id_in_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    with pytest.raises(DataLensConfigurationError, match=r"yc config set organization-id <org-id>"):
        YCIAMAuthProvider()


def test_yc_iam_provider_refreshes_inside_expiry_margin(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    calls = 0

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": f"iam-{calls}", "expires_at": _expiry(now[0] + 120)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: now[0])
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(org_id="org-1", token_expiry_margin_seconds=30)

    assert provider.get_headers()["Authorization"] == "Bearer iam-1"
    now[0] += 91
    assert provider.get_headers()["Authorization"] == "Bearer iam-2"
    assert calls == 2


def test_yc_iam_provider_serializes_concurrent_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "shared", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(org_id="org-1")
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(provider.get_headers) for _ in range(4)]
        assert started.wait(timeout=2)
        release.set()
        headers = [future.result() for future in futures]

    assert headers == [{"Authorization": "Bearer shared", "x-dl-org-id": "org-1"}] * 4
    assert calls == 1


def test_yc_iam_provider_uses_unexpired_cache_when_refresh_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    calls = 0

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise subprocess.CalledProcessError(1, command, stderr="temporary failure")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "cached", "expires_at": _expiry(1120)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: now[0])
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(org_id="org-1")

    assert provider.get_headers()["Authorization"] == "Bearer cached"
    now[0] = 1061
    with pytest.warns(RuntimeWarning, match="cached token"):
        assert provider.get_headers()["Authorization"] == "Bearer cached"
    now[0] = 1121
    with pytest.raises(DataLensConfigurationError, match="temporary failure"):
        provider.get_headers()


def test_yc_iam_provider_uses_unexpired_cache_when_refresh_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    calls = 0

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls > 1:
            now[0] = 1119.0
            raise subprocess.TimeoutExpired(command, 30.0)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "cached", "expires_at": _expiry(1120)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: now[0])
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(org_id="org-1")

    assert provider.get_headers()["Authorization"] == "Bearer cached"
    now[0] = 1061
    with pytest.warns(RuntimeWarning, match="cached token"):
        assert provider.get_headers()["Authorization"] == "Bearer cached"


def test_yc_iam_provider_does_not_use_cache_that_expires_during_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    calls = 0

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls > 1:
            now[0] = 1120.0
            raise subprocess.TimeoutExpired(command, 30.0)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "expired", "expires_at": _expiry(1120)}),
            stderr="",
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: now[0])
    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    provider = YCIAMAuthProvider(org_id="org-1")

    assert provider.get_headers()["Authorization"] == "Bearer expired"
    now[0] = 1061.0
    with pytest.raises(DataLensConfigurationError, match="yc iam create-token timed out"):
        provider.get_headers()


def test_yc_iam_provider_reports_missing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    with pytest.raises(DataLensConfigurationError, match="yc CLI was not found"):
        YCIAMAuthProvider(org_id="org-1").get_headers()


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("not-json", "invalid JSON"),
        (json.dumps({"iam_token": "", "expires_at": "2999-01-01T00:00:00Z"}), "empty iam_token"),
        (json.dumps({"iam_token": "token", "expires_at": "invalid"}), "invalid expires_at"),
    ],
)
def test_yc_iam_provider_rejects_invalid_cli_output(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    message: str,
) -> None:
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)

    with pytest.raises(DataLensConfigurationError, match=message):
        YCIAMAuthProvider(org_id="org-1").get_headers()


def test_service_account_provider_signs_and_exchanges_jwt_with_nanosecond_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_payloads: list[dict[str, object]] = []
    encoded_headers: list[dict[str, str]] = []
    exchange_bodies: list[object] = []

    def fake_encode(
        payload: dict[str, object],
        key: str,
        *,
        algorithm: str,
        headers: dict[str, str],
    ) -> str:
        assert key == "private-key"
        assert algorithm == "PS256"
        encoded_payloads.append(payload)
        encoded_headers.append(headers)
        return "signed-jwt"

    def fake_post(url: str, *, json: object, timeout: httpx.Timeout) -> httpx.Response:
        assert url == "https://iam.api.cloud.yandex.net/iam/v1/tokens"
        assert timeout.connect == 10.0
        exchange_bodies.append(json)
        return httpx.Response(
            200,
            json={"iamToken": "iam-sa", "expiresAt": "2026-07-22T03:16:03.492455005+00:00"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: 1000.0)
    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = YCServiceAccountCredentialsAuthProvider(
        org_id="org-1",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    expected_headers = {"Authorization": "Bearer iam-sa", "x-dl-org-id": "org-1"}
    assert provider.get_headers() == expected_headers
    assert provider.get_headers() == expected_headers
    assert encoded_payloads == [
        {
            "aud": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
            "iss": "sa-id",
            "iat": 1000,
            "exp": 4600,
        }
    ]
    assert encoded_headers == [{"kid": "key-id", "typ": "JWT"}]
    assert exchange_bodies == [{"jwt": "signed-jwt"}]


def test_service_account_provider_accepts_custom_exchange_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded_payloads: list[dict[str, object]] = []
    posted_urls: list[str] = []
    now = [1000.0]

    def fake_encode(payload: dict[str, object], *_: object, **__: object) -> str:
        encoded_payloads.append(payload)
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        posted_urls.append(url)
        return httpx.Response(
            200,
            json={"iamToken": f"iam-{len(posted_urls)}", "expiresAt": _expiry(now[0] + 120)},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("datalens_sdk.auth.time.time", lambda: now[0])
    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = YCServiceAccountCredentialsAuthProvider(
        org_id="org-1",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
        iam_token_endpoint="https://iam.example.test/tokens",
        token_expiry_margin_seconds=30,
        jwt_lifetime_seconds=120,
    )

    assert provider.get_headers() == {"Authorization": "Bearer iam-1", "x-dl-org-id": "org-1"}
    now[0] += 91
    assert provider.get_headers() == {"Authorization": "Bearer iam-2", "x-dl-org-id": "org-1"}
    assert posted_urls == ["https://iam.example.test/tokens"] * 2
    assert encoded_payloads == [
        {"aud": "https://iam.example.test/tokens", "iss": "sa-id", "iat": 1000, "exp": 1120},
        {"aud": "https://iam.example.test/tokens", "iss": "sa-id", "iat": 1091, "exp": 1211},
    ]


def test_service_account_provider_surfaces_exchange_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_encode(*_: object, **__: object) -> str:
        return "signed-jwt"

    def fake_post(url: str, **_: object) -> httpx.Response:
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr("datalens_sdk.auth.jwt.encode", fake_encode)
    monkeypatch.setattr("datalens_sdk.auth.httpx.post", fake_post)
    provider = YCServiceAccountCredentialsAuthProvider(
        org_id="org-1",
        key_id="key-id",
        service_account_id="sa-id",
        private_key="private-key",
    )

    with pytest.raises(httpx.HTTPStatusError):
        provider.get_headers()


def test_yacloud_client_uses_yc_iam_provider_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    seen: list[httpx.Request] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:4] == ["yc", "config", "get", "organization-id"]:
            return subprocess.CompletedProcess(command, 0, stdout="org-default\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"iam_token": "default-iam", "expires_at": _expiry(time.time() + 3600)}),
            stderr="",
        )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg"})

    monkeypatch.setattr("datalens_sdk.auth.subprocess.run", fake_run)
    client = DataLensClientYC(transport=httpx.MockTransport(handler))

    client.get.connection(by_id="conn-1")

    assert commands == [
        ["yc", "config", "get", "organization-id"],
        ["yc", "iam", "create-token", "--format", "json"],
    ]
    assert seen[0].headers["authorization"] == "Bearer default-iam"
    assert seen[0].headers["x-dl-org-id"] == "org-default"


def test_explicit_none_disables_yacloud_default_auth() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg"})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handler))

    client.get.connection(by_id="conn-1")

    assert "authorization" not in seen[0].headers


def test_enterprise_client_requires_base_url() -> None:
    with pytest.raises(DataLensConfigurationError, match="DataLensClientEnterprise requires base_url"):
        DataLensClientEnterprise(auth=None)


def test_public_clients_expose_installation_specific_create_surface() -> None:
    yc = DataLensClientYC(auth=None, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    enterprise = DataLensClientEnterprise(
        auth=None,
        base_url="https://enterprise.example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    yc_connection_factory = yc.create.connection
    enterprise_connection_factory = enterprise.create.connection

    assert callable(yc_connection_factory.postgres)
    assert callable(yc_connection_factory.bigquery)
    assert not hasattr(enterprise_connection_factory, "bigquery")
    assert callable(enterprise_connection_factory.chyt)
    for client in (yc, enterprise):
        assert {"collections", "folders", "workbooks"} <= set(client.capabilities["namespaces"])
        chart_factories = client.capabilities["chart_factories"]
        assert chart_factories["wizard"] == sorted(
            name
            for name, value in vars(type(client.create.wizard_chart)).items()
            if not name.startswith("_") and callable(value)
        )
        assert chart_factories["ql"] == sorted(
            name
            for name, value in vars(type(client.create.ql_chart)).items()
            if not name.startswith("_") and callable(value)
        )
        assert chart_factories["editor"] == sorted(
            name
            for name, value in vars(type(client.create.editor_chart)).items()
            if not name.startswith("_") and callable(value)
        )
        assert callable(client.create.collection)
        assert callable(client.create.workbook)
        assert callable(client.create.folder)
        assert callable(client.get.collection)
        assert callable(client.get.workbook)
        assert callable(client.get.folder)


def test_yacloud_licenses_namespace_is_yc_only() -> None:
    yc = DataLensClientYC(auth=None, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    enterprise = DataLensClientEnterprise(
        auth=None,
        base_url="https://enterprise.example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    assert hasattr(yc, "licenses")
    with pytest.raises(NotSupportedError, match="Namespace 'licenses' is not available"):
        _read_attr(enterprise, "licenses")


def test_connection_crud_uses_foreign_namespace_shape() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/rpc/createConnection":
            return httpx.Response(200, json={"id": "conn-1"})
        if request.url.path == "/rpc/getConnection":
            return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg"})
        if request.url.path == "/rpc/updateConnection":
            return httpx.Response(200, json={"id": "conn-1", "type": "postgres", "name": "pg2"})
        if request.url.path == "/rpc/deleteConnection":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": "unexpected"})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handler))

    created = (
        client.create.connection.postgres(name="pg", location=EntryLocation.path("/sdk")).host("h").port(5432).build()
    )
    fetched = client.get.connection(by_id=created.id or "")
    updated = fetched.update.name("pg2").execute()
    updated.delete()

    assert created.id == "conn-1"
    assert fetched.type == "postgres"
    assert updated.name == "pg2"
    assert [request.url.path for request in requests] == [
        "/rpc/createConnection",
        "/rpc/getConnection",
        "/rpc/getConnection",
        "/rpc/updateConnection",
        "/rpc/deleteConnection",
    ]


def test_dataset_create_supports_raw_source_and_generated_shortcut() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/rpc/validateDataset":
            body = json.loads(request.content.decode())
            updates = body["data"]["updates"]
            source_id = updates[0]["source"]["id"]
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "description": "",
                        "sources": [
                            {
                                "id": source_id,
                                "source_type": "PG_TABLE",
                                "valid": True,
                                "raw_schema": [],
                            }
                        ],
                        "source_avatars": [],
                        "avatar_relations": [],
                        "result_schema": [],
                    },
                },
            )
        if request.url.path == "/rpc/createDataset":
            return httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "dataset": {
                        "description": "",
                        "sources": [],
                        "source_avatars": [],
                        "avatar_relations": [],
                    },
                },
            )
        return httpx.Response(404, json={"message": "unexpected"})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handler))
    connection = client.domain_connection(id="conn-1", type="postgres")
    source_factory = client.create.source(using=connection)
    raw = source_factory.raw(
        alias="orders",
        source_type="PG_TABLE",
        parameters={"table_name": "orders"},
    )
    shortcut = source_factory.pg_table(alias="orders2", table_name="orders2").build()

    dataset = client.create.dataset(name="sales", location=EntryLocation.path("/sdk")).sources([raw, shortcut]).build()

    assert dataset.id == "ds-1"
    assert len(requests) == 3
    assert requests[0].url.path == "/rpc/validateDataset"
    validate_body_source = json.loads(requests[0].read())
    assert validate_body_source["data"]["updates"][0]["source"]["parameters"]["table_name"] == "orders2"
    assert requests[1].url.path == "/rpc/validateDataset"
    validate_body_dataset = json.loads(requests[1].read())
    assert validate_body_dataset["data"]["updates"][0]["source"]["source_type"] == "PG_TABLE"
    assert requests[2].url.path == "/rpc/createDataset"
