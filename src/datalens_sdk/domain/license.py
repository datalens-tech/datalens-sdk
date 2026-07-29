from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from datalens_sdk.errors import DatalensValidationError

LicenseType: TypeAlias = Literal["creator"]
LicenseStatus: TypeAlias = Literal["active", "expired", "expiring"]
LicenseSortField: TypeAlias = Literal["created_at", "updated_at"]
LicenseLimitType: TypeAlias = Literal["regular", "forced"]


@dataclass(frozen=True, slots=True)
class License:
    id: str
    user_id: str
    tenant_id: str
    type: LicenseType
    is_active: bool
    expires_at: str | None
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    last_login_at: str | None = None
    meta: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LicenseLimit:
    type: LicenseLimitType
    value: int
    started_at: str
    active_licenses_count: int | None


@dataclass(frozen=True, slots=True)
class LicenseLimits:
    current: LicenseLimit | None
    next: LicenseLimit | None


@dataclass(frozen=True, slots=True)
class LicenseListOptions:
    user_ids: tuple[str, ...] = ()
    status: LicenseStatus | None = None
    sort_by: LicenseSortField | None = None
    order: Literal["asc", "desc"] = "asc"
    page_size: int = 100

    def __post_init__(self) -> None:
        if len(self.user_ids) > 1000:
            raise DatalensValidationError("user_ids must contain at most 1000 items")
        if self.status is not None and self.status not in {"active", "expired", "expiring"}:
            raise DatalensValidationError("status must be one of: active, expired, expiring")
        if self.sort_by is not None and self.sort_by not in {"created_at", "updated_at"}:
            raise DatalensValidationError("sort_by must be one of: created_at, updated_at")
        if self.order not in {"asc", "desc"}:
            raise DatalensValidationError("order must be one of: asc, desc")
        if not 1 <= self.page_size <= 200:
            raise DatalensValidationError("page_size must be between 1 and 200")

    @classmethod
    def create(
        cls,
        *,
        user_ids: Sequence[str] = (),
        status: LicenseStatus | None = None,
        sort_by: LicenseSortField | None = None,
        order: Literal["asc", "desc"] = "asc",
        page_size: int = 100,
    ) -> LicenseListOptions:
        return cls(
            user_ids=tuple(user_ids),
            status=status,
            sort_by=sort_by,
            order=order,
            page_size=page_size,
        )
