from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter._utils import _optional_str
from datalens_sdk.converter.raw.connection import (
    RawConnectionCreateEnvelope,
    RawConnectionReplaceEnvelope,
    connection_params_from_snapshot,
)
from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    dir_path_from_location,
    resolve_entry_location_from_api_fields,
    workbook_id_from_location,
)
from datalens_sdk.domain.ports import ConnectionOperations
from datalens_sdk.domain.specs.connection import ConnectionCreateSpec, ConnectionUpdateSpec
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import DataLensValidationError, NotSupportedError
from datalens_sdk.serialization.connection import ConnectionSnapshotView
from datalens_sdk.serialization.json_types import JsonObject, JsonValue, normalize_json_object


class ConnectionCreateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class ConnectionReadDTOProtocol(Protocol):
    raw: dict[str, object]

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, object]: ...


class ConnectionCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        installation: str,
        connection_type: str,
        params: Mapping[str, object],
    ) -> ConnectionCreateDTOProtocol: ...


class ConnectionReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> ConnectionReadDTOProtocol: ...


class ConnectionDtoModule(Protocol):
    INSTALLATION_CONNECTORS: Mapping[str, frozenset[str]]
    ConnectionCreateDTO: ConnectionCreateDTOClass
    ConnectionReadDTO: ConnectionReadDTOClass


def _dto_module(dto_module: ConnectionDtoModule | None) -> ConnectionDtoModule:
    return cast(ConnectionDtoModule, generated_dto if dto_module is None else dto_module)


def _require_connector_available(
    *,
    connector: str,
    installation: str,
    dto_module: ConnectionDtoModule | None,
) -> None:
    supported = _dto_module(dto_module).INSTALLATION_CONNECTORS.get(installation, frozenset())
    if connector not in supported:
        raise NotSupportedError(f"Connection type {connector!r} is not available on installation {installation!r}")


class ConnectionConverter:
    @staticmethod
    def from_domain_create(
        spec: ConnectionCreateSpec,
        *,
        dto_module: ConnectionDtoModule | None = None,
    ) -> ConnectionCreateDTOProtocol:
        generated = _dto_module(dto_module)
        params = dict(spec.params)
        params["name"] = spec.name
        dir_path = dir_path_from_location(spec.location)
        workbook_id = workbook_id_from_location(spec.location)
        collection_id = collection_id_from_location(spec.location)
        if dir_path is not None:
            params["dir_path"] = dir_path
        if workbook_id is not None:
            params["workbook_id"] = workbook_id
        if collection_id is not None:
            params["collection_id"] = collection_id
        return generated.ConnectionCreateDTO(
            installation=spec.installation,
            connection_type=spec.connector,
            params=params,
        )

    @staticmethod
    def from_domain_update(spec: ConnectionUpdateSpec) -> dict[str, object]:
        return {
            "connectionId": spec.connection_id,
            "data": dict(spec.changes),
        }

    @staticmethod
    def from_raw_create(
        spec: RawCreateSpec,
        *,
        overrides: JsonObject | None,
        installation: str,
        dto_module: ConnectionDtoModule | None = None,
    ) -> RawConnectionCreateEnvelope:
        source = ConnectionSnapshotView.from_raw(spec.response_snapshot)
        connector = source.connector
        _require_connector_available(
            connector=connector,
            installation=installation,
            dto_module=dto_module,
        )
        params = connection_params_from_snapshot(source, overrides=overrides)
        params["type"] = connector
        params["name"] = spec.name
        dir_path = dir_path_from_location(spec.location)
        workbook_id = workbook_id_from_location(spec.location)
        collection_id = collection_id_from_location(spec.location)
        if dir_path is not None:
            params["dir_path"] = dir_path
        if workbook_id is not None:
            params["workbook_id"] = workbook_id
        if collection_id is not None:
            params["collection_id"] = collection_id
        return RawConnectionCreateEnvelope(params=params)

    @staticmethod
    def from_raw_replace(
        spec: RawReplaceSpec,
        *,
        target_connector_type: str,
        overrides: JsonObject | None,
        installation: str,
        dto_module: ConnectionDtoModule | None = None,
    ) -> RawConnectionReplaceEnvelope:
        source = ConnectionSnapshotView.from_raw(spec.response_snapshot)
        source_connector = source.connector
        if source_connector != target_connector_type:
            raise DataLensValidationError(
                "Connection connector type mismatch: "
                f"source is {source_connector!r}, target is {target_connector_type!r}"
            )
        _require_connector_available(
            connector=target_connector_type,
            installation=installation,
            dto_module=dto_module,
        )
        return RawConnectionReplaceEnvelope(
            connection_id=spec.target_id,
            data=connection_params_from_snapshot(source, overrides=overrides),
        )

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | ConnectionReadDTOProtocol,
        *,
        installation: str,
        operations: ConnectionOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        id_fallback: str | None = None,
        connection_type_fallback: str | None = None,
        dto_module: ConnectionDtoModule | None = None,
    ) -> Connection:
        response_snapshot: dict[str, JsonValue] = {}
        data: Mapping[str, object]
        generated = _dto_module(dto_module)
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="Connection API response")
            dto_validation_input = dict(response_snapshot)
            dto_validation_input["raw"] = normalize_json_object(
                response_snapshot,
                context="Connection typed response state",
            )
            generated.ConnectionReadDTO.model_validate(dto_validation_input)
            data = normalize_json_object(response_snapshot, context="Connection typed response state")
        else:
            read_dto = raw
            data = read_dto.raw or read_dto.model_dump(exclude_none=True)
        connection_type = str(data.get("type") or data.get("db_type") or connection_type_fallback or "")
        key = _optional_str(data.get("key"))
        domain_location = resolve_entry_location_from_api_fields(
            dir_path=_optional_str(data.get("dir_path")),
            key=key,
            collection_id=_optional_str(data.get("collection_id")),
            workbook_id=_optional_str(data.get("workbook_id")),
            fallback=location,
        )
        return Connection(
            id=_optional_str(data.get("id")) or id_fallback,
            type=connection_type,
            name=_optional_str(data.get("name")) or name_from_key(key) or name,
            installation=installation,
            description=str(data.get("description") or ""),
            location=domain_location,
            raw=data,
            response_snapshot=response_snapshot,
            _operations=operations,
        )
