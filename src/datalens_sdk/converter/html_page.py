from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.domain.entry_location import key_from_location, workbook_id_from_location
from datalens_sdk.domain.entry_types import EntryBranch
from datalens_sdk.domain.html_page import HtmlPage, HtmlPagePermissions
from datalens_sdk.domain.ports import HtmlPageOperations
from datalens_sdk.domain.specs.html_page import (
    HtmlPageContentUpdateSpec,
    HtmlPageCreateSpec,
    HtmlPageRevisionUpdateSpec,
)
from datalens_sdk.errors import translate_invalid_response_error


class HtmlPageWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class HtmlPageWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> HtmlPageWriteDTOProtocol: ...


class HtmlPageReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> object: ...


class HtmlPageDtoModule(Protocol):
    CreateHtmlPageArgsDTO: HtmlPageWriteDTOClass
    GetHtmlPageArgsDTO: HtmlPageWriteDTOClass
    DeleteHtmlPageArgsDTO: HtmlPageWriteDTOClass
    UpdateHtmlPageArgsAnyOf0DTO: HtmlPageWriteDTOClass
    UpdateHtmlPageArgsAnyOf1DTO: HtmlPageWriteDTOClass
    GetHtmlPageResultReadDTO: HtmlPageReadDTOClass
    CreateHtmlPageResultReadDTO: HtmlPageReadDTOClass
    UpdateHtmlPageResultReadDTO: HtmlPageReadDTOClass


def _dto_module(dto_module: HtmlPageDtoModule | None) -> HtmlPageDtoModule:
    return cast(HtmlPageDtoModule, generated_dto if dto_module is None else dto_module)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _optional_permissions(value: object) -> HtmlPagePermissions | None:
    if not isinstance(value, Mapping):
        return None
    execute = value.get("execute")
    read = value.get("read")
    edit = value.get("edit")
    admin = value.get("admin")
    if not all(isinstance(item, bool) for item in (execute, read, edit, admin)):
        return None
    return HtmlPagePermissions(
        execute=cast(bool, execute),
        read=cast(bool, read),
        edit=cast(bool, edit),
        admin=cast(bool, admin),
    )


def _optional_links(value: object) -> Mapping[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        return None
    return cast(Mapping[str, str], dict(value))


def _warnings(value: object, *, operation: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise translate_invalid_response_error(operation=operation, reason="warnings is not an array of strings")
    return tuple(value)


class HtmlPageConverter:
    @staticmethod
    def from_domain_create(
        spec: HtmlPageCreateSpec,
        *,
        dto_module: HtmlPageDtoModule | None = None,
    ) -> HtmlPageWriteDTOProtocol:
        generated = _dto_module(dto_module)
        key = key_from_location(spec.location, name=spec.name)
        payload: dict[str, object] = {"content": spec.content}
        if key is not None:
            payload["key"] = key
        else:
            payload["name"] = spec.name
            workbook_id = workbook_id_from_location(spec.location)
            if workbook_id is not None:
                payload["workbook_id"] = workbook_id
        if spec.description is not None:
            payload["annotation"] = {"description": spec.description}
        return generated.CreateHtmlPageArgsDTO.model_validate(payload)

    @staticmethod
    def from_domain_get(
        entry_id: str,
        *,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
        include_favorite: bool | None = None,
        include_permissions: bool | None = None,
        dto_module: HtmlPageDtoModule | None = None,
    ) -> HtmlPageWriteDTOProtocol:
        generated = _dto_module(dto_module)
        payload: dict[str, object] = {"entry_id": entry_id}
        if rev_id is not None:
            payload["rev_id"] = rev_id
        elif branch is not None:
            payload["branch"] = branch
        if include_favorite is not None:
            payload["include_favorite"] = include_favorite
        if include_permissions is not None:
            payload["include_permissions"] = include_permissions
        return generated.GetHtmlPageArgsDTO.model_validate(payload)

    @staticmethod
    def from_domain_update(
        spec: HtmlPageContentUpdateSpec | HtmlPageRevisionUpdateSpec,
        *,
        dto_module: HtmlPageDtoModule | None = None,
    ) -> HtmlPageWriteDTOProtocol:
        generated = _dto_module(dto_module)
        if isinstance(spec, HtmlPageRevisionUpdateSpec):
            return generated.UpdateHtmlPageArgsAnyOf1DTO.model_validate(
                {"entry_id": spec.entry_id, "rev_id": spec.rev_id, "mode": spec.mode}
            )
        payload: dict[str, object] = {"entry_id": spec.entry_id, "content": spec.content, "mode": spec.mode}
        if spec.description is not None:
            payload["annotation"] = {"description": spec.description}
        return generated.UpdateHtmlPageArgsAnyOf0DTO.model_validate(payload)

    @staticmethod
    def from_domain_delete(entry_id: str, *, dto_module: HtmlPageDtoModule | None = None) -> HtmlPageWriteDTOProtocol:
        return _dto_module(dto_module).DeleteHtmlPageArgsDTO.model_validate({"entry_id": entry_id})

    @staticmethod
    def to_domain(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: HtmlPageOperations | None = None,
        operation: Literal["createHtmlPage", "getHtmlPage", "updateHtmlPage"] = "getHtmlPage",
        name: str | None = None,
        dto_module: HtmlPageDtoModule | None = None,
    ) -> HtmlPage:
        generated = _dto_module(dto_module)
        if operation == "getHtmlPage":
            generated.GetHtmlPageResultReadDTO.model_validate(raw)
            entry = raw
            warning_codes: tuple[str, ...] = ()
        else:
            read_class = (
                generated.CreateHtmlPageResultReadDTO
                if operation == "createHtmlPage"
                else generated.UpdateHtmlPageResultReadDTO
            )
            read_class.model_validate(raw)
            entry_value = raw.get("entry")
            if not isinstance(entry_value, Mapping):
                raise translate_invalid_response_error(operation=operation, reason="entry is not an object")
            entry = _object(entry_value)
            warning_codes = _warnings(raw.get("warnings"), operation=operation)

        entry_id = _optional_string(entry.get("entryId"))
        if not entry_id:
            raise translate_invalid_response_error(operation=operation, reason="entry is missing an HTML page id")
        if entry.get("scope") != "artifact" or entry.get("type") != "html-page":
            raise translate_invalid_response_error(operation=operation, reason="entry is not an HTML page")
        key = _optional_string(entry.get("key"))
        if key is None:
            raise translate_invalid_response_error(operation=operation, reason="entry is missing a key")
        metadata = _object(entry.get("meta"))
        policy_value = metadata.get("policyVersion")
        policy_version = float(policy_value) if isinstance(policy_value, (int, float)) else None
        version_value = entry.get("version")
        version = int(version_value) if isinstance(version_value, (int, float)) else None
        annotation = _object(entry.get("annotation"))
        return HtmlPage(
            id=entry_id,
            name=name_from_key(key) or name,
            key=key,
            installation=installation,
            workbook_id=_optional_string(entry.get("workbookId")),
            collection_id=_optional_string(entry.get("collectionId")),
            rev_id=_optional_string(entry.get("revId")),
            saved_id=_optional_string(entry.get("savedId")),
            published_id=_optional_string(entry.get("publishedId")),
            object_id=_optional_string(metadata.get("objectId")),
            policy_version=policy_version,
            version=version,
            description=_optional_string(annotation.get("description")),
            created_by=_optional_string(entry.get("createdBy")),
            created_at=_optional_string(entry.get("createdAt")),
            updated_by=_optional_string(entry.get("updatedBy")),
            updated_at=_optional_string(entry.get("updatedAt")),
            rev_updated_by=_optional_string(entry.get("revUpdatedBy")),
            rev_updated_at=_optional_string(entry.get("revUpdatedAt")),
            tenant_id=_optional_string(entry.get("tenantId")),
            hidden=_optional_bool(entry.get("hidden")) or False,
            public=_optional_bool(entry.get("public")) or False,
            is_favorite=_optional_bool(entry.get("isFavorite")),
            permissions=_optional_permissions(entry.get("permissions")),
            links=_optional_links(entry.get("links")),
            warnings=warning_codes,
            data=_object(entry.get("data")),
            raw=dict(entry),
            _operations=operations,
        )
