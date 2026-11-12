from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.screenshot import ScreenshotRequest

SCREENSHOT_FORMAT = "png"


class ScreenshotWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class ScreenshotWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> ScreenshotWriteDTOProtocol: ...


class ScreenshotResultDTOProtocol(Protocol):
    data: str


class ScreenshotResultDTOClass(Protocol):
    def model_validate(self, obj: object) -> ScreenshotResultDTOProtocol: ...


class ScreenshotDtoModule(Protocol):
    GetChartScreenshotArgsDTO: ScreenshotWriteDTOClass
    GetDashScreenshotArgsDTO: ScreenshotWriteDTOClass
    GetScreenshotResultReadDTO: ScreenshotResultDTOClass


def resolve_dto_module(dto_module: ScreenshotDtoModule | None) -> ScreenshotDtoModule:
    return cast(ScreenshotDtoModule, generated_dto if dto_module is None else dto_module)


class ScreenshotConverter:
    @staticmethod
    def from_domain_request(
        request: ScreenshotRequest,
        *,
        s3: bool,
        dto_module: ScreenshotDtoModule | None = None,
    ) -> ScreenshotWriteDTOProtocol:
        """Build the request DTO: an inline base64 PNG by default, an S3 upload when ``s3`` is set."""
        generated = resolve_dto_module(dto_module)
        payload: dict[str, object] = {"type": SCREENSHOT_FORMAT}
        if s3:
            payload["s3"] = True
        else:
            payload["base64"] = True
        if request.width is not None:
            payload["width"] = request.width
        if request.height is not None:
            payload["height"] = request.height
        if request.full_page is not None:
            payload["full_page"] = request.full_page
        query_params = request.query_params()
        if query_params:
            payload["query_params"] = query_params
        if request.entity_kind == "chart":
            return generated.GetChartScreenshotArgsDTO.model_validate({"chart_id": request.entity_id, **payload})
        return generated.GetDashScreenshotArgsDTO.model_validate({"dash_id": request.entity_id, **payload})

    @staticmethod
    def to_data(raw: Mapping[str, object], *, dto_module: ScreenshotDtoModule | None = None) -> str:
        return resolve_dto_module(dto_module).GetScreenshotResultReadDTO.model_validate(raw).data
