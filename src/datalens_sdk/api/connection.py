from __future__ import annotations

from pydantic import ValidationError

from datalens_sdk._runtime.builder_base import BaseConnectionCreate
from datalens_sdk.api.entries import EntriesService
from datalens_sdk.converter.connection import ConnectionConverter, ConnectionDtoModule
from datalens_sdk.domain.connection import Connection, ConnectionUpdate
from datalens_sdk.domain.entry_location import workbook_id_from_location
from datalens_sdk.domain.navigation import EntryRelation, Pager, RelationOptions
from datalens_sdk.domain.ports import ConnectionOperations, NavigationOperations
from datalens_sdk.domain.specs.connection import ConnectionUpdateSpec
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import (
    translate_dto_validation_error,
)
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy
from datalens_sdk.serialization.json_types import JsonObject


class ConnectionAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def _post(
        self,
        path: str,
        body: dict[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> dict[str, object]:
        return self._client.post_json_object(path, body, retry_policy=retry_policy)

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/createConnection", payload)

    def get(
        self,
        connection_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {"connectionId": connection_id}
        if workbook_id is not None:
            body["workbookId"] = workbook_id
        if rev_id is not None:
            body["rev_id"] = rev_id
        return self._post("/rpc/getConnection", body, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateConnection", payload)

    def delete(self, connection_id: str) -> None:
        self._post("/rpc/deleteConnection", {"connectionId": connection_id})


class ConnectionService(ConnectionOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: ConnectionAPI,
        entries_service: EntriesService,
        navigation_operations: NavigationOperations,
        dto_module: ConnectionDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._entries_service = entries_service
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    def create_connection(self, builder: BaseConnectionCreate) -> Connection:
        spec = builder.to_spec()
        try:
            dto = ConnectionConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createConnection", reason=str(exc)) from exc
        response = self._api.create(dto.to_payload())
        # API returns only the new id from createConnection; fetch the full entry only in that case.
        if len(response) == 1:
            connection_id = response.get("id")
            if isinstance(connection_id, str) and connection_id:
                return self.get_connection(connection_id, workbook_id=workbook_id_from_location(spec.location))
        return ConnectionConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            dto_module=self._dto_module,
        )

    def create_connection_from_raw(
        self,
        spec: RawCreateSpec,
        *,
        overrides: JsonObject | None,
    ) -> Connection:
        payload = ConnectionConverter.from_raw_create(
            spec,
            overrides=overrides,
            installation=self._installation,
            dto_module=self._dto_module,
        ).to_payload()
        response = self._api.create(payload)
        return ConnectionConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            connection_type_fallback=str(payload["type"]),
            dto_module=self._dto_module,
        )

    def get_connection(
        self,
        connection_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Connection:
        response = self._api.get(connection_id, workbook_id=workbook_id, rev_id=rev_id)
        return ConnectionConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            dto_module=self._dto_module,
        )

    def update_connection(self, builder: ConnectionUpdate) -> Connection:
        spec: ConnectionUpdateSpec = builder.to_spec()
        response = self._api.update(ConnectionConverter.from_domain_update(spec))
        changed_name = spec.changes.get("name")
        return ConnectionConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.connection_location,
            name=changed_name if isinstance(changed_name, str) else spec.connection_name,
            id_fallback=spec.connection_id,
            dto_module=self._dto_module,
        )

    def replace_connection_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_connector_type: str,
        overrides: JsonObject | None,
    ) -> Connection:
        payload = ConnectionConverter.from_raw_replace(
            spec,
            target_connector_type=target_connector_type,
            overrides=overrides,
            installation=self._installation,
            dto_module=self._dto_module,
        ).to_payload()
        response = self._api.update(payload)
        return ConnectionConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.target_location,
            name=spec.target_name,
            id_fallback=spec.target_id,
            connection_type_fallback=target_connector_type,
            dto_module=self._dto_module,
        )

    def delete_connection(self, connection_id: str) -> None:
        self._api.delete(connection_id)

    def rename_connection(self, connection: Connection, name: str) -> Connection:
        if not connection.id:
            raise ValueError("Cannot rename a connection without an id")
        self._entries_service.rename_entry(entry_id=connection.id, name=name)
        return self.get_connection(connection.id, workbook_id=connection.workbook_id)

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]:
        return self._navigation_operations.get_entry_relations(entry_id, options)
