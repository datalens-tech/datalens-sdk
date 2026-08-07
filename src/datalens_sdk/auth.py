from __future__ import annotations

import abc
import asyncio
from collections.abc import AsyncGenerator, Generator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import os
import re
import subprocess
import threading
import time
from typing import Protocol
import warnings

import httpx
import jwt

from datalens_sdk.errors import DatalensConfigurationError

_DATALENS_API_TOKEN_ENV = "DATALENS_API_TOKEN"
_IAM_TOKEN_ENDPOINT = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
_IAM_TOKEN_EXPIRY_MARGIN_SECONDS = 60
_JWT_LIFETIME_SECONDS = 3600
_YC_CLI_COMMAND_TIMEOUT_SECONDS = 30.0
_RFC3339_SUBSECOND_OVERFLOW_RE = re.compile(r"(\.\d{6})\d+(?=(?:Z|[+-]\d{2}:\d{2})$)")


class AuthProviderProtocol(Protocol):
    def get_headers(self) -> dict[str, str]: ...

    async def get_headers_async(self) -> dict[str, str]: ...


class BaseAuthProvider(abc.ABC):
    @abc.abstractmethod
    def get_headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def get_headers_async(self) -> dict[str, str]:
        return self.get_headers()


class NoAuthProvider(BaseAuthProvider):
    def get_headers(self) -> dict[str, str]:
        return {}


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizationTokenAuthProvider(BaseAuthProvider):
    token: str = field(repr=False)
    token_type: str

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"{self.token_type} {self.token}"}


class OAuthAuthProvider(AuthorizationTokenAuthProvider):
    def __init__(self, *, token: str | None = None) -> None:
        resolved_token = token if token is not None else os.getenv(_DATALENS_API_TOKEN_ENV)
        if not resolved_token:
            raise DatalensConfigurationError(f"OAuth token is required: pass token= or set {_DATALENS_API_TOKEN_ENV}.")
        super().__init__(token=resolved_token, token_type="OAuth")


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticYCIAMAuthProvider(BaseAuthProvider):
    org_id: str
    token: str = field(repr=False)

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "x-dl-org-id": self.org_id,
        }


@dataclass(frozen=True, slots=True)
class _IAMToken:
    value: str = field(repr=False)
    expires_at: float


class _RefreshingIAMAuthProvider(BaseAuthProvider, abc.ABC):
    def __init__(
        self,
        *,
        org_id: str,
        token_expiry_margin_seconds: int = _IAM_TOKEN_EXPIRY_MARGIN_SECONDS,
    ) -> None:
        resolved_org_id = org_id.strip()
        if not resolved_org_id:
            raise DatalensConfigurationError("YC organization ID is required: pass org_id=.")
        self._org_id = resolved_org_id
        self._cached_token: _IAMToken | None = None
        self._refresh_lock = threading.Lock()
        self._token_expiry_margin_seconds = token_expiry_margin_seconds

    @abc.abstractmethod
    def _fetch_token(self) -> _IAMToken:
        raise NotImplementedError

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "x-dl-org-id": self._org_id,
        }

    async def get_headers_async(self) -> dict[str, str]:
        return await asyncio.to_thread(self.get_headers)

    def _get_token(self) -> str:
        now = time.time()
        cached_token = self._cached_token
        if cached_token is not None and now < cached_token.expires_at - self._token_expiry_margin_seconds:
            return cached_token.value

        with self._refresh_lock:
            # Another thread may have refreshed the token while this thread waited for the lock.
            now = time.time()
            cached_token = self._cached_token
            if cached_token is not None and now < cached_token.expires_at - self._token_expiry_margin_seconds:
                return cached_token.value
            try:
                refreshed_token = self._fetch_token()
            except Exception:
                fallback_now = time.time()
                if cached_token is not None and fallback_now < cached_token.expires_at:
                    warnings.warn(
                        "Failed to refresh the YC IAM token; using the cached token until it expires.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    return cached_token.value
                raise
            self._cached_token = refreshed_token
            return refreshed_token.value


class YCServiceAccountCredentialsAuthProvider(_RefreshingIAMAuthProvider):
    def __init__(
        self,
        *,
        org_id: str,
        key_id: str,
        service_account_id: str,
        private_key: str,
        iam_token_endpoint: str = _IAM_TOKEN_ENDPOINT,
        token_expiry_margin_seconds: int = _IAM_TOKEN_EXPIRY_MARGIN_SECONDS,
        jwt_lifetime_seconds: int = _JWT_LIFETIME_SECONDS,
    ) -> None:
        super().__init__(org_id=org_id, token_expiry_margin_seconds=token_expiry_margin_seconds)
        self._key_id = key_id
        self._service_account_id = service_account_id
        self._private_key = private_key
        self._iam_token_endpoint = iam_token_endpoint
        self._jwt_lifetime_seconds = jwt_lifetime_seconds

    def _fetch_token(self) -> _IAMToken:
        now = int(time.time())
        encoded_jwt = jwt.encode(
            {
                "aud": self._iam_token_endpoint,
                "iss": self._service_account_id,
                "iat": now,
                "exp": now + self._jwt_lifetime_seconds,
            },
            self._private_key,
            algorithm="PS256",
            headers={"kid": self._key_id, "typ": "JWT"},
        )
        response = httpx.post(
            self._iam_token_endpoint,
            json={"jwt": encoded_jwt},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        response.raise_for_status()
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise DatalensConfigurationError(
                "YC IAM returned invalid JSON while exchanging the service-account JWT."
            ) from exc
        return _parse_iam_token(payload, token_field="iamToken", expiry_field="expiresAt", source="YC IAM")


def _run_yc_command(
    command: list[str],
    *,
    action: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise DatalensConfigurationError(
            "yc CLI was not found. Install it from https://yandex.cloud/docs/cli/quickstart."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DatalensConfigurationError(
            f"{action} timed out after {timeout_seconds:g} seconds. "
            "Check that the yc CLI can complete in the current environment before retrying."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else "unknown error"
        raise DatalensConfigurationError(f"{action} failed: {detail}") from exc


def _get_yc_org_id(*, profile: str | None, command_timeout_seconds: float) -> str:
    command = ["yc", "config", "get", "organization-id"]
    if profile is not None:
        command.extend(["--profile", profile])
    org_id = _run_yc_command(
        command,
        action="yc config get organization-id",
        timeout_seconds=command_timeout_seconds,
    ).stdout.strip()
    if not org_id:
        raise DatalensConfigurationError(
            "YC organization ID is required: pass org_id= or run "
            "`yc config set organization-id <org-id>` for the selected yc profile."
        )
    return org_id


class YCIAMAuthProvider(_RefreshingIAMAuthProvider):
    def __init__(
        self,
        *,
        org_id: str | None = None,
        profile: str | None = None,
        token_expiry_margin_seconds: int = _IAM_TOKEN_EXPIRY_MARGIN_SECONDS,
        command_timeout_seconds: float = _YC_CLI_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        if not math.isfinite(command_timeout_seconds) or command_timeout_seconds <= 0:
            raise DatalensConfigurationError("command_timeout_seconds must be a finite positive number.")
        resolved_org_id = (
            org_id
            if org_id is not None
            else _get_yc_org_id(
                profile=profile,
                command_timeout_seconds=command_timeout_seconds,
            )
        )
        super().__init__(org_id=resolved_org_id, token_expiry_margin_seconds=token_expiry_margin_seconds)
        self._profile = profile
        self._command_timeout_seconds = command_timeout_seconds

    def _fetch_token(self) -> _IAMToken:
        command = ["yc", "iam", "create-token", "--format", "json"]
        if self._profile is not None:
            command.extend(["--profile", self._profile])
        result = _run_yc_command(
            command,
            action="yc iam create-token",
            timeout_seconds=self._command_timeout_seconds,
        )
        try:
            payload: object = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DatalensConfigurationError("yc iam create-token returned invalid JSON.") from exc
        return _parse_iam_token(
            payload,
            token_field="iam_token",
            expiry_field="expires_at",
            source="yc iam create-token",
        )


def _parse_iam_token(payload: object, *, token_field: str, expiry_field: str, source: str) -> _IAMToken:
    if not isinstance(payload, Mapping):
        raise DatalensConfigurationError(f"{source} returned a JSON value that is not an object.")

    raw_token = payload.get(token_field)
    token = raw_token.strip() if isinstance(raw_token, str) else ""
    if not token:
        raise DatalensConfigurationError(f"{source} returned an empty {token_field}.")

    raw_expiry = payload.get(expiry_field)
    if not isinstance(raw_expiry, str):
        raise DatalensConfigurationError(f"{source} returned an invalid {expiry_field}.")
    try:
        normalized_expiry = _RFC3339_SUBSECOND_OVERFLOW_RE.sub(r"\1", raw_expiry)
        parsed_expiry = datetime.fromisoformat(normalized_expiry.replace("Z", "+00:00"))
        if parsed_expiry.tzinfo is None:
            raise ValueError("timezone is missing")
        expires_at = parsed_expiry.timestamp()
    except ValueError as exc:
        raise DatalensConfigurationError(f"{source} returned an invalid {expiry_field}.") from exc
    if expires_at <= time.time():
        raise DatalensConfigurationError(f"{source} returned an already expired token.")
    return _IAMToken(value=token, expires_at=expires_at)


class _AuthProviderHTTPXAuth(httpx.Auth):
    def __init__(self, provider: AuthProviderProtocol) -> None:
        self._provider = provider

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers.update(self._provider.get_headers())
        yield request

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers.update(await self._provider.get_headers_async())
        yield request
