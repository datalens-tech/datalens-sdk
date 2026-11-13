from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.screenshot import REVISION_PARAM, STATE_PARAM, TAB_PARAM, ScreenshotRequest
from datalens_sdk.errors import NotSupportedError

SCREENSHOT_FORMAT = "png"
EMBEDDED_PARAM = "_embedded"
NO_CONTROLS_PARAM = "_no_controls"
THEME_PARAM = "_theme"
NO_TITLE_PARAM = "_no_title"
NO_TABS_PARAM = "_no_tabs"
ENABLED = "1"
SCREENSHOT_DTO_NAMES = ("GetChartScreenshotArgsDTO", "GetDashScreenshotArgsDTO", "GetScreenshotResultReadDTO")


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
    """Return the generated DTO module, or fail when its API contract has no screenshot routes."""
    module = generated_dto if dto_module is None else dto_module
    for name in SCREENSHOT_DTO_NAMES:
        if not hasattr(module, name):
            raise NotSupportedError("Screenshots are not part of the API contract generated for this installation")
    return cast(ScreenshotDtoModule, module)


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
        payload["query_params"] = ScreenshotConverter.query_params(request)
        if request.entity_kind == "chart":
            return generated.GetChartScreenshotArgsDTO.model_validate({"chart_id": request.entity_id, **payload})
        return generated.GetDashScreenshotArgsDTO.model_validate({"dash_id": request.entity_id, **payload})

    @staticmethod
    def query_params(request: ScreenshotRequest) -> dict[str, str | list[str]]:
        """Encode caller params and the SDK-owned view, revision, tab and state as page query parameters.

        The page is always rendered embedded, so the picture holds the entity alone
        and not the DataLens navigation around it.
        """
        result: dict[str, str | list[str]] = {}
        for key, value in request.params.items():
            result[key] = value if isinstance(value, str) else list(value)
        result[EMBEDDED_PARAM] = ENABLED
        if request.entity_kind == "chart":
            result[NO_CONTROLS_PARAM] = ENABLED
        if request.theme is not None:
            result[THEME_PARAM] = request.theme
        if not request.show_title:
            result[NO_TITLE_PARAM] = ENABLED
        if not request.show_tabs:
            result[NO_TABS_PARAM] = ENABLED
        if request.rev_id is not None:
            result[REVISION_PARAM] = request.rev_id
        if request.tab is not None:
            result[TAB_PARAM] = request.tab
        if request.state is not None:
            result[STATE_PARAM] = request.state
        return result

    @staticmethod
    def to_data(raw: Mapping[str, object], *, dto_module: ScreenshotDtoModule | None = None) -> str:
        return resolve_dto_module(dto_module).GetScreenshotResultReadDTO.model_validate(raw).data
