from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.revisions import EntryRevision, EntryRevisionsOptions


class EntryRevisionsWriteDTOProtocol(Protocol):
    def model_dump(
        self,
        *,
        mode: Literal["json"],
        by_alias: bool,
        exclude_unset: bool,
    ) -> dict[str, object]: ...


class EntryRevisionsRequestDTOClass(Protocol):
    def model_validate(self, obj: object) -> EntryRevisionsWriteDTOProtocol: ...


class EntryRevisionReadDTOProtocol(Protocol):
    rev_id: str
    updated_at: str
    updated_by: str
    is_saved: bool
    is_published: bool


class EntryRevisionsReadDTOProtocol(Protocol):
    entries: Sequence[EntryRevisionReadDTOProtocol]
    next_page_token: str | None


class EntryRevisionsReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> EntryRevisionsReadDTOProtocol: ...


class EntryRevisionsDtoModule(Protocol):
    EntryRevisionsRequestDTO: EntryRevisionsRequestDTOClass
    EntryRevisionsReadDTO: EntryRevisionsReadDTOClass


def _dto_module(dto_module: EntryRevisionsDtoModule | None) -> EntryRevisionsDtoModule:
    return cast(EntryRevisionsDtoModule, generated_dto if dto_module is None else dto_module)


class EntryRevisionsConverter:
    @staticmethod
    def to_payload(
        entry_id: str,
        options: EntryRevisionsOptions,
        *,
        page_token: str | None,
        dto_module: EntryRevisionsDtoModule | None = None,
    ) -> dict[str, object]:
        generated = _dto_module(dto_module)
        payload: dict[str, object] = {"entryId": entry_id, "pageSize": options.page_size}
        if page_token is not None:
            payload["pageToken"] = page_token
        if options.rev_ids is not None:
            payload["revIds"] = list(options.rev_ids)
        return generated.EntryRevisionsRequestDTO.model_validate(payload).model_dump(
            mode="json", by_alias=True, exclude_unset=True
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object],
        *,
        dto_module: EntryRevisionsDtoModule | None = None,
    ) -> Page[EntryRevision]:
        generated = _dto_module(dto_module)
        result = generated.EntryRevisionsReadDTO.model_validate(raw)
        return Page(
            items=tuple(
                EntryRevision(
                    rev_id=revision.rev_id,
                    updated_at=revision.updated_at,
                    updated_by=revision.updated_by,
                    is_saved=revision.is_saved,
                    is_published=revision.is_published,
                )
                for revision in result.entries
            ),
            next_page_token=result.next_page_token,
        )
