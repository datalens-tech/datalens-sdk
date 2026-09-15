from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, get_args

from typing_extensions import Self

from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.ports import HtmlPageOperations
from datalens_sdk.domain.specs.html_page import (
    HtmlPageContentUpdateSpec,
    HtmlPageCreateSpec,
    HtmlPageRevisionUpdateSpec,
)
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

_UNBOUND = "Object is not bound to client operations. Use a client namespace."
_MAX_CONTENT_LENGTH = 10485760


def _validate_content(value: str) -> str:
    if not isinstance(value, str):
        raise DataLensValidationError("content must be a string")
    if len(value) > _MAX_CONTENT_LENGTH:
        raise DataLensValidationError("content must be at most 10485760 characters")
    try:
        byte_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise DataLensValidationError("content must be valid UTF-8") from exc
    if byte_length > _MAX_CONTENT_LENGTH:
        raise DataLensValidationError("UTF-8 content must be at most 10485760 bytes")
    return value


class HtmlPageCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        operations: HtmlPageOperations | None = None,
    ) -> None:
        resolved = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="HTML page creation",
        )
        validate_entry_name(name=name, location=resolved)
        self._installation = installation
        self._name = name
        self._location = resolved
        self._operations = operations
        self._content: str | None = None
        self._description: str | None = None

    def content(self, value: str) -> Self:
        self._content = _validate_content(value)
        return self

    def description(self, value: str) -> Self:
        if not isinstance(value, str):
            raise DataLensValidationError("description must be a string")
        self._description = value
        return self

    def to_spec(self) -> HtmlPageCreateSpec:
        if self._content is None:
            raise DataLensValidationError("HTML page creation requires content")
        return HtmlPageCreateSpec(
            name=self._name,
            location=self._location,
            content=self._content,
            description=self._description,
        )

    def build(self) -> HtmlPage:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.create_html_page(self)


@dataclass(frozen=True, slots=True)
class HtmlPagePermissions:
    execute: bool
    read: bool
    edit: bool
    admin: bool


@dataclass(slots=True)
class HtmlPage:
    id: str
    name: str | None
    key: str
    installation: str = ""
    scope: Literal["artifact"] = "artifact"
    type: Literal["html-page"] = "html-page"
    workbook_id: str | None = None
    collection_id: str | None = None
    rev_id: str | None = None
    saved_id: str | None = None
    published_id: str | None = None
    object_id: str | None = None
    policy_version: float | None = None
    version: int | None = None
    description: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None
    rev_updated_by: str | None = None
    rev_updated_at: str | None = None
    tenant_id: str | None = None
    hidden: bool = False
    public: bool = False
    is_favorite: bool | None = None
    permissions: HtmlPagePermissions | None = None
    links: Mapping[str, str] | None = None
    warnings: tuple[str, ...] = ()
    data: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    _operations: HtmlPageOperations | None = field(default=None, repr=False, compare=False)

    @property
    def update(self) -> HtmlPageUpdate:
        return HtmlPageUpdate(page=self, operations=self._operations)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete an HTML page without an id")
        self._operations.delete_html_page(self.id)


class HtmlPageUpdate:
    def __init__(self, *, page: HtmlPage, operations: HtmlPageOperations | None = None) -> None:
        self._page = page
        self._operations = operations
        self._content: str | None = None
        self._rev_id: str | None = None
        self._mode: EntryUpdateMode = "save"
        self._description: str | None = None

    @property
    def page(self) -> HtmlPage:
        return self._page

    def content(self, value: str) -> Self:
        if self._rev_id is not None:
            raise DataLensValidationError("HTML page update cannot combine content and rev_id")
        self._content = _validate_content(value)
        return self

    def revision(self, rev_id: str) -> Self:
        if self._content is not None or self._description is not None:
            raise DataLensValidationError("HTML page revision update cannot combine content or description")
        if not isinstance(rev_id, str) or not rev_id:
            raise DataLensValidationError("rev_id must not be empty")
        self._rev_id = rev_id
        return self

    def mode(self, value: EntryUpdateMode) -> Self:
        if value not in get_args(EntryUpdateMode):
            raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
        self._mode = value
        return self

    def description(self, value: str) -> Self:
        if self._rev_id is not None:
            raise DataLensValidationError("HTML page revision update cannot include description")
        if not isinstance(value, str):
            raise DataLensValidationError("description must be a string")
        self._description = value
        return self

    def to_spec(self) -> HtmlPageContentUpdateSpec | HtmlPageRevisionUpdateSpec:
        if not self._page.id:
            raise DataLensValidationError("Cannot update an HTML page without an id")
        if self._rev_id is not None:
            return HtmlPageRevisionUpdateSpec(entry_id=self._page.id, rev_id=self._rev_id, mode=self._mode)
        if self._content is None:
            raise DataLensValidationError("HTML page update requires content or rev_id")
        return HtmlPageContentUpdateSpec(
            entry_id=self._page.id,
            content=self._content,
            mode=self._mode,
            description=self._description,
        )

    def execute(self) -> HtmlPage:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_html_page(self)
