from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from typing_extensions import Self

from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    dir_path_from_location,
    key_from_location,
    resolve_entry_location,
    validate_entry_name,
    workbook_id_from_location,
)
from datalens_sdk.domain.entry_types import EntryUpdateMode, validate_entry_update_mode
from datalens_sdk.domain.navigation import Pager
from datalens_sdk.domain.ports import HtmlPageOperations
from datalens_sdk.domain.revisions import EntryRevision, EntryRevisionsOptions
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
    id: str | None
    name: str | None = None
    installation: str = ""
    location: EntryLocation | None = None
    scope: Literal["artifact"] = "artifact"
    type: Literal["html-page"] = "html-page"
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

    def __post_init__(self) -> None:
        if self.name is None:
            name = self.raw.get("name")
            self.name = name if isinstance(name, str) else None

    @property
    def key(self) -> str | None:
        key = self.raw.get("key")
        return (key if isinstance(key, str) and key else None) or key_from_location(self.location, name=self.name)

    @property
    def dir_path(self) -> str | None:
        return dir_path_from_location(self.location)

    @property
    def workbook_id(self) -> str | None:
        return workbook_id_from_location(self.location)

    @property
    def collection_id(self) -> str | None:
        return collection_id_from_location(self.location)

    @property
    def update(self) -> HtmlPageUpdate:
        return HtmlPageUpdate(page=self, operations=self._operations)

    def publish_revision(self, *, rev_id: str) -> HtmlPage:
        """Publish an explicitly selected existing revision without creating a new one.

        Select a saved draft or a historical revision without resending its HTML.
        Write and publish new source with ``page.update.content(...).mode("publish").execute()``.
        """
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot publish an HTML page without an id")
        if not isinstance(rev_id, str) or not rev_id:
            raise DataLensValidationError("rev_id must be a non-empty string")
        return self.update.revision(rev_id).mode("publish").execute()

    def get_revisions(
        self,
        *,
        page_size: int = 200,
        page_token: str | None = None,
        rev_ids: Sequence[str] | None = None,
    ) -> Pager[EntryRevision]:
        """Lazily list this entry's revisions, optionally filtered or resumed."""
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot get revisions for an HTML page without an id")
        return self._operations.get_entry_revisions(
            self.id,
            EntryRevisionsOptions.create(page_size=page_size, page_token=page_token, rev_ids=rev_ids),
        )

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
        self._mode = validate_entry_update_mode(value)
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
