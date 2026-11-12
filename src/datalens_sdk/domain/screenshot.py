from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeAlias

from typing_extensions import Self

from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.artifacts import ArtifactPath

if TYPE_CHECKING:
    from datalens_sdk.domain.ports import ScreenshotOperations

ScreenshotParamValue: TypeAlias = str | Sequence[str]
ScreenshotParams: TypeAlias = Mapping[str, ScreenshotParamValue]
ScreenshotEntityKind: TypeAlias = Literal["chart", "dashboard"]

DEFAULT_SCREENSHOT_TIMEOUT = 120.0
CHART_SCREENSHOT_WIDTH = 1024
CHART_SCREENSHOT_HEIGHT = 768
MAX_SCREENSHOT_SIDE = 6000
REVISION_PARAM = "revId"
TAB_PARAM = "tab"

UNBOUND_SCREENSHOT = "Screenshot is not bound to client operations. Take it from a client-loaded chart or dashboard."


def validate_side(value: int | None, *, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataLensValidationError(f"Screenshot {name} must be an integer number of pixels")
    if not 1 <= value <= MAX_SCREENSHOT_SIDE:
        raise DataLensValidationError(f"Screenshot {name} must be between 1 and {MAX_SCREENSHOT_SIDE}")


def normalize_param_value(key: str, value: object) -> str | tuple[str, ...]:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)) or not isinstance(value, Sequence):
        raise DataLensValidationError(f"Screenshot parameter {key!r} must be a string or a sequence of strings")
    items = tuple(value)
    for item in items:
        if not isinstance(item, str):
            raise DataLensValidationError(f"Screenshot parameter {key!r} must contain only strings")
    return items


def normalize_params(
    params: ScreenshotParams | None, *, reserved: frozenset[str]
) -> Mapping[str, str | tuple[str, ...]]:
    if params is None:
        return MappingProxyType({})
    if not isinstance(params, Mapping):
        raise DataLensValidationError("Screenshot params must be a mapping of parameter names to values")
    normalized: dict[str, str | tuple[str, ...]] = {}
    for key, value in params.items():
        if not isinstance(key, str) or not key:
            raise DataLensValidationError("Screenshot parameter names must be non-empty strings")
        if key in reserved:
            raise DataLensValidationError(
                f"Screenshot parameter {key!r} is set by the SDK and cannot be passed in params"
            )
        normalized[key] = normalize_param_value(key, value)
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class ScreenshotRequest:
    entity_kind: ScreenshotEntityKind
    entity_id: str
    width: int | None = None
    height: int | None = None
    full_page: bool | None = None
    params: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    rev_id: str | None = None
    tab: str | None = None
    timeout: float = DEFAULT_SCREENSHOT_TIMEOUT

    def __post_init__(self) -> None:
        if self.entity_kind not in ("chart", "dashboard"):
            raise DataLensValidationError(f"Unsupported screenshot entity kind: {self.entity_kind!r}")
        if not self.entity_id:
            raise DataLensValidationError(f"Cannot take a screenshot of a {self.entity_kind} without an id")
        validate_side(self.width, name="width")
        validate_side(self.height, name="height")
        if self.full_page is not None and not isinstance(self.full_page, bool):
            raise DataLensValidationError("Screenshot full_page must be a boolean")
        if self.tab is not None and (self.entity_kind != "dashboard" or not self.tab):
            raise DataLensValidationError("Screenshot tab must be a non-empty dashboard tab id")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)):
            raise DataLensValidationError("Screenshot timeout must be a number of seconds")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise DataLensValidationError("Screenshot timeout must be a positive number of seconds")

    @classmethod
    def create(
        cls,
        *,
        entity_kind: ScreenshotEntityKind,
        entity_id: str | None,
        width: int | None = None,
        height: int | None = None,
        full_page: bool | None = None,
        params: ScreenshotParams | None = None,
        rev_id: str | None = None,
        tab: str | None = None,
        timeout: float = DEFAULT_SCREENSHOT_TIMEOUT,
    ) -> Self:
        reserved = frozenset({REVISION_PARAM, TAB_PARAM} if entity_kind == "dashboard" else {REVISION_PARAM})
        return cls(
            entity_kind=entity_kind,
            entity_id=entity_id or "",
            width=width,
            height=height,
            full_page=full_page,
            params=normalize_params(params, reserved=reserved),
            rev_id=rev_id,
            tab=tab,
            timeout=timeout,
        )

    def query_params(self) -> dict[str, str | list[str]]:
        """Return page query parameters: caller params plus the SDK-owned revision and tab."""
        result: dict[str, str | list[str]] = {}
        for key, value in self.params.items():
            result[key] = value if isinstance(value, str) else list(value)
        if self.rev_id is not None:
            result[REVISION_PARAM] = self.rev_id
        if self.tab is not None:
            result[TAB_PARAM] = self.tab
        return result


@dataclass(frozen=True, slots=True)
class EntityScreenshot:
    """A server-rendered PNG of a chart or dashboard."""

    image: bytes = field(repr=False)
    width: int | None
    height: int | None
    params: Mapping[str, str | tuple[str, ...]]
    entity_id: str
    _request: ScreenshotRequest = field(repr=False, compare=False)
    _operations: ScreenshotOperations | None = field(default=None, repr=False, compare=False)

    def save(self, path: ArtifactPath) -> Path:
        """Write the PNG bytes to ``path``, creating parent directories."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.image)
        return target

    def get_temp_s3_url(self) -> str:
        """Render the same screenshot again on the server and return its temporary S3 URL.

        Every call triggers a new render and a new uploaded file; nothing is cached.
        """
        if self._operations is None:
            raise DataLensConfigurationError(UNBOUND_SCREENSHOT)
        return self._operations.get_screenshot_url(self._request)
