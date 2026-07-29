from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar, Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.license import License, LicenseLimit, LicenseLimits, LicenseListOptions


class LicenseWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class LicenseReadDTOProtocol(Protocol):
    license_id: str
    user_id: str
    tenant_id: str
    license_type: Literal["creator"]
    is_active: bool
    expires_at: str | None
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    last_login_at: str | None
    meta: Mapping[str, object]
    raw: dict[str, object]


class LicenseLimitReadDTOProtocol(Protocol):
    type: Literal["regular", "forced"]
    value: int
    started_at: str
    active_licenses_count: int | None


class LicenseListResultDTOProtocol(Protocol):
    licenses: tuple[LicenseReadDTOProtocol, ...]
    next_page_token: str | None


class LicenseLimitsReadDTOProtocol(Protocol):
    current: LicenseLimitReadDTOProtocol | None
    next: LicenseLimitReadDTOProtocol | None


class LicenseAssignArgsDTOClass(Protocol):
    def __call__(self, *, user_ids: tuple[str, ...]) -> LicenseWriteDTOProtocol: ...


class LicenseListArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        user_ids: tuple[str, ...],
        status: str | None,
        sort_by: str | None,
        order: str,
        limit: int,
        page_token: str | None,
    ) -> LicenseWriteDTOProtocol: ...


class LicenseReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> LicenseReadDTOProtocol: ...


class LicenseListResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> LicenseListResultDTOProtocol: ...


class LicenseLimitsReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> LicenseLimitsReadDTOProtocol: ...


class LicenseSetLimitArgsDTOClass(Protocol):
    def __call__(self, *, value: int) -> LicenseWriteDTOProtocol: ...


class LicenseDtoModule(Protocol):
    LicenseAssignArgsDTO: LicenseAssignArgsDTOClass
    LicenseListArgsDTO: LicenseListArgsDTOClass
    LicenseReadDTO: LicenseReadDTOClass
    LicenseListResultDTO: LicenseListResultDTOClass
    LicenseLimitsReadDTO: LicenseLimitsReadDTOClass
    LicenseSetLimitArgsDTO: LicenseSetLimitArgsDTOClass


def _dto_module(dto_module: LicenseDtoModule | None) -> LicenseDtoModule:
    return cast(LicenseDtoModule, generated_dto if dto_module is None else dto_module)


class LicenseConverter:
    _SORT_FIELDS: ClassVar[dict[str, str]] = {
        "created_at": "createdAt",
        "updated_at": "updatedAt",
    }

    @staticmethod
    def assign_payload(
        user_ids: Sequence[str],
        *,
        dto_module: LicenseDtoModule | None = None,
    ) -> dict[str, object]:
        return _dto_module(dto_module).LicenseAssignArgsDTO(user_ids=tuple(user_ids)).to_payload()

    @classmethod
    def list_payload(
        cls,
        options: LicenseListOptions,
        *,
        page_token: str | None,
        dto_module: LicenseDtoModule | None = None,
    ) -> dict[str, object]:
        sort_by = cls._SORT_FIELDS[options.sort_by] if options.sort_by is not None else None
        return (
            _dto_module(dto_module)
            .LicenseListArgsDTO(
                user_ids=options.user_ids,
                status=options.status,
                sort_by=sort_by,
                order=options.order,
                limit=options.page_size,
                page_token=page_token,
            )
            .to_payload()
        )

    @staticmethod
    def set_limit_payload(
        value: int,
        *,
        dto_module: LicenseDtoModule | None = None,
    ) -> dict[str, object]:
        return _dto_module(dto_module).LicenseSetLimitArgsDTO(value=value).to_payload()

    @staticmethod
    def _to_domain(dto: LicenseReadDTOProtocol) -> License:
        return License(
            id=dto.license_id,
            user_id=dto.user_id,
            tenant_id=dto.tenant_id,
            type=dto.license_type,
            is_active=dto.is_active,
            expires_at=dto.expires_at,
            created_by=dto.created_by,
            created_at=dto.created_at,
            updated_by=dto.updated_by,
            updated_at=dto.updated_at,
            last_login_at=dto.last_login_at,
            meta=dict(dto.meta),
            raw=dto.raw,
        )

    @classmethod
    def assign_result(
        cls,
        raw: Sequence[Mapping[str, object]],
        *,
        dto_module: LicenseDtoModule | None = None,
    ) -> tuple[License, ...]:
        generated = _dto_module(dto_module)
        return tuple(cls._to_domain(generated.LicenseReadDTO.model_validate(item)) for item in raw)

    @classmethod
    def list_result(
        cls,
        raw: Mapping[str, object],
        *,
        dto_module: LicenseDtoModule | None = None,
    ) -> tuple[tuple[License, ...], str | None]:
        result = _dto_module(dto_module).LicenseListResultDTO.model_validate(raw)
        return tuple(cls._to_domain(item) for item in result.licenses), result.next_page_token

    @staticmethod
    def _limit_to_domain(dto: LicenseLimitReadDTOProtocol | None) -> LicenseLimit | None:
        if dto is None:
            return None
        return LicenseLimit(
            type=dto.type,
            value=dto.value,
            started_at=dto.started_at,
            active_licenses_count=dto.active_licenses_count,
        )

    @classmethod
    def limits_result(
        cls,
        raw: Mapping[str, object],
        *,
        dto_module: LicenseDtoModule | None = None,
    ) -> LicenseLimits:
        result = _dto_module(dto_module).LicenseLimitsReadDTO.model_validate(raw)
        return LicenseLimits(
            current=cls._limit_to_domain(result.current),
            next=cls._limit_to_domain(result.next),
        )
