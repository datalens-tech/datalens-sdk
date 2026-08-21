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

from datalens_sdk.api_version import API_VERSION
from datalens_sdk.errors import DataLensConfigurationError

_DATALENS_OAUTH_TOKEN_ENV = "DATALENS_OAUTH_TOKEN"
_DATALENS_ORG_ID_ENV = "DATALENS_ORG_ID"
_DATALENS_YC_BIN_ENV = "DATALENS_YC_BIN"
_DATALENS_YC_PROFILE_ENV = "DATALENS_YC_PROFILE"
_ENTERPRISE_JWT_LIFETIME_SECONDS = 300
_ENTERPRISE_MAX_JWT_LIFETIME_SECONDS = 600
_ENTERPRISE_TOKEN_EXCHANGE_PATH = "/rpc/exchangeServiceAccountToken"
_IAM_TOKEN_ENDPOINT = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
_IAM_TOKEN_EXPIRY_MARGIN_SECONDS = 60
_JWT_LIFETIME_SECONDS = 3600
_TOKEN_EXCHANGE_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
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
        resolved_token = token if token is not None else os.getenv(_DATALENS_OAUTH_TOKEN_ENV)
        if not resolved_token:
            raise DataLensConfigurationError(
                f"OAuth token is required: pass token= or set {_DATALENS_OAUTH_TOKEN_ENV}."
            )
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
class _ExpiringToken:
    value: str = field(repr=False)
    expires_at: float


class _RefreshingTokenAuthProvider(BaseAuthProvider, abc.ABC):
    def __init__(
        self,
        *,
        token_expiry_margin_seconds: int = _IAM_TOKEN_EXPIRY_MARGIN_SECONDS,
        token_description: str,
    ) -> None:
        self._cached_token: _ExpiringToken | None = None
        self._refresh_lock = threading.Lock()
        self._token_expiry_margin_seconds = token_expiry_margin_seconds
        self._token_description = token_description

    @abc.abstractmethod
    def _fetch_token(self) -> _ExpiringToken:
        raise NotImplementedError

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

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
                        f"Failed to refresh the {self._token_description}; using the cached token until it expires.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    return cached_token.value
                raise
            self._cached_token = refreshed_token
            return refreshed_token.value


class _RefreshingIAMAuthProvider(_RefreshingTokenAuthProvider, abc.ABC):
    def __init__(
        self,
        *,
        org_id: str,
        token_expiry_margin_seconds: int = _IAM_TOKEN_EXPIRY_MARGIN_SECONDS,
    ) -> None:
        resolved_org_id = org_id.strip()
        if not resolved_org_id:
            raise DataLensConfigurationError("YC organization ID is required: pass org_id=.")
        super().__init__(
            token_expiry_margin_seconds=token_expiry_margin_seconds,
            token_description="YC IAM token",
        )
        self._org_id = resolved_org_id

    def get_headers(self) -> dict[str, str]:
        return {
            **super().get_headers(),
            "x-dl-org-id": self._org_id,
        }


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

    def _fetch_token(self) -> _ExpiringToken:
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
            raise DataLensConfigurationError(
                "YC IAM returned invalid JSON while exchanging the service-account JWT."
            ) from exc
        return _parse_iam_token(payload, token_field="iamToken", expiry_field="expiresAt", source="YC IAM")


class EnterpriseServiceAccountCredentialsAuthProvider(_RefreshingTokenAuthProvider):
    def __init__(
        self,
        *,
        key_id: str,
        service_account_id: str,
        private_key: str,
        base_url: str | None = None,
        token_expiry_margin_seconds: int = _IAM_TOKEN_EXPIRY_MARGIN_SECONDS,
        jwt_lifetime_seconds: int = _ENTERPRISE_JWT_LIFETIME_SECONDS,
    ) -> None:
        if token_expiry_margin_seconds < 0:
            raise DataLensConfigurationError("token_expiry_margin_seconds must not be negative.")
        if not 1 <= jwt_lifetime_seconds <= _ENTERPRISE_MAX_JWT_LIFETIME_SECONDS:
            raise DataLensConfigurationError(
                f"jwt_lifetime_seconds must be between 1 and {_ENTERPRISE_MAX_JWT_LIFETIME_SECONDS}."
            )

        super().__init__(
            token_expiry_margin_seconds=token_expiry_margin_seconds,
            token_description="Enterprise access token",
        )
        self._token_endpoint = self._resolve_token_endpoint(base_url) if base_url is not None else None
        self._key_id = key_id
        self._service_account_id = service_account_id
        self._private_key = private_key
        self._jwt_lifetime_seconds = jwt_lifetime_seconds

    @staticmethod
    def _resolve_token_endpoint(base_url: str) -> str:
        resolved_base_url = base_url.strip()
        if not resolved_base_url:
            raise DataLensConfigurationError("Enterprise base URL must not be empty.")
        try:
            base_url_value = httpx.URL(resolved_base_url)
        except httpx.InvalidURL as exc:
            raise DataLensConfigurationError("Enterprise base URL is invalid.") from exc
        if not base_url_value.is_absolute_url:
            raise DataLensConfigurationError("Enterprise base URL must be absolute.")
        return str(base_url_value.join(_ENTERPRISE_TOKEN_EXCHANGE_PATH))

    def set_base_url(self, base_url: str) -> None:
        self._token_endpoint = self._resolve_token_endpoint(base_url)

    def _fetch_token(self) -> _ExpiringToken:
        token_endpoint = self._token_endpoint
        if token_endpoint is None:
            raise DataLensConfigurationError(
                "Enterprise base URL is required: pass base_url= or use the provider with DataLensClientEnterprise."
            )
        now = int(time.time())
        encoded_jwt = jwt.encode(
            {
                "iss": self._service_account_id,
                "iat": now,
                "exp": now + self._jwt_lifetime_seconds,
            },
            self._private_key,
            algorithm="PS256",
            headers={"kid": self._key_id, "typ": "JWT"},
        )
        response = httpx.post(
            token_endpoint,
            headers={"x-dl-api-version": API_VERSION},
            json={"saToken": encoded_jwt},
            timeout=_TOKEN_EXCHANGE_TIMEOUT,
        )
        response.raise_for_status()
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise DataLensConfigurationError(
                "DataLens Enterprise returned invalid JSON while exchanging the service-account JWT."
            ) from exc
        return _parse_enterprise_access_token(payload)


def _parse_enterprise_access_token(payload: object) -> _ExpiringToken:
    if not isinstance(payload, Mapping):
        raise DataLensConfigurationError("DataLens Enterprise returned a JSON value that is not an object.")

    raw_token = payload.get("accessToken")
    token = raw_token.strip() if isinstance(raw_token, str) else ""
    if not token:
        raise DataLensConfigurationError("DataLens Enterprise returned an empty accessToken.")

    try:
        decoded: object = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise DataLensConfigurationError("DataLens Enterprise returned an invalid accessToken JWT.") from exc
    if not isinstance(decoded, Mapping):
        raise DataLensConfigurationError("DataLens Enterprise returned an invalid accessToken JWT payload.")

    raw_expiry = decoded.get("exp")
    if isinstance(raw_expiry, bool) or not isinstance(raw_expiry, (int, float)) or not math.isfinite(raw_expiry):
        raise DataLensConfigurationError("DataLens Enterprise accessToken has an invalid exp claim.")
    expires_at = float(raw_expiry)
    if expires_at <= time.time():
        raise DataLensConfigurationError("DataLens Enterprise returned an already expired accessToken.")
    return _ExpiringToken(value=token, expires_at=expires_at)


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
        raise DataLensConfigurationError(
            "yc CLI was not found. Install it from https://yandex.cloud/docs/cli/quickstart."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DataLensConfigurationError(
            f"{action} timed out after {timeout_seconds:g} seconds. "
            "Check that the yc CLI can complete in the current environment before retrying."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else "unknown error"
        raise DataLensConfigurationError(f"{action} failed: {detail}") from exc


def _get_yc_org_id(*, yc_bin: str, profile: str | None, command_timeout_seconds: float) -> str:
    command = [yc_bin, "config", "get", "organization-id"]
    if profile is not None:
        command.extend(["--profile", profile])
    org_id = _run_yc_command(
        command,
        action="yc config get organization-id",
        timeout_seconds=command_timeout_seconds,
    ).stdout.strip()
    if not org_id:
        raise DataLensConfigurationError(
            f"YC organization ID is required: pass org_id=, set {_DATALENS_ORG_ID_ENV}, or run "
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
            raise DataLensConfigurationError("command_timeout_seconds must be a finite positive number.")
        resolved_yc_bin = os.getenv(_DATALENS_YC_BIN_ENV) or "yc"
        resolved_profile = profile if profile is not None else os.getenv(_DATALENS_YC_PROFILE_ENV) or None
        environment_org_id = os.getenv(_DATALENS_ORG_ID_ENV) or None
        resolved_org_id = (
            org_id
            if org_id is not None
            else environment_org_id
            or _get_yc_org_id(
                yc_bin=resolved_yc_bin,
                profile=resolved_profile,
                command_timeout_seconds=command_timeout_seconds,
            )
        )
        super().__init__(org_id=resolved_org_id, token_expiry_margin_seconds=token_expiry_margin_seconds)
        self._yc_bin = resolved_yc_bin
        self._profile = resolved_profile
        self._command_timeout_seconds = command_timeout_seconds

    def _fetch_token(self) -> _ExpiringToken:
        command = [self._yc_bin, "iam", "create-token", "--format", "json"]
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
            raise DataLensConfigurationError("yc iam create-token returned invalid JSON.") from exc
        return _parse_iam_token(
            payload,
            token_field="iam_token",
            expiry_field="expires_at",
            source="yc iam create-token",
        )


def _parse_iam_token(payload: object, *, token_field: str, expiry_field: str, source: str) -> _ExpiringToken:
    if not isinstance(payload, Mapping):
        raise DataLensConfigurationError(f"{source} returned a JSON value that is not an object.")

    raw_token = payload.get(token_field)
    token = raw_token.strip() if isinstance(raw_token, str) else ""
    if not token:
        raise DataLensConfigurationError(f"{source} returned an empty {token_field}.")

    raw_expiry = payload.get(expiry_field)
    if not isinstance(raw_expiry, str):
        raise DataLensConfigurationError(f"{source} returned an invalid {expiry_field}.")
    try:
        normalized_expiry = _RFC3339_SUBSECOND_OVERFLOW_RE.sub(r"\1", raw_expiry)
        parsed_expiry = datetime.fromisoformat(normalized_expiry.replace("Z", "+00:00"))
        if parsed_expiry.tzinfo is None:
            raise ValueError("timezone is missing")
        expires_at = parsed_expiry.timestamp()
    except ValueError as exc:
        raise DataLensConfigurationError(f"{source} returned an invalid {expiry_field}.") from exc
    if expires_at <= time.time():
        raise DataLensConfigurationError(f"{source} returned an already expired token.")
    return _ExpiringToken(value=token, expires_at=expires_at)


class _AuthProviderHTTPXAuth(httpx.Auth):
    def __init__(self, provider: AuthProviderProtocol) -> None:
        self._provider = provider

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers.update(self._provider.get_headers())
        yield request

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers.update(await self._provider.get_headers_async())
        yield request
