from __future__ import annotations

from pydantic import ValidationError

from datalens_sdk.converter.collection import CollectionConverter, CollectionDtoModule
from datalens_sdk.domain.collection import Collection, CollectionCreate, CollectionUpdate
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import CollectionListOptions, Pager, StructureSummary
from datalens_sdk.domain.ports import CollectionOperations, NavigationOperations
from datalens_sdk.errors import translate_dto_validation_error
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy


class CollectionAPI:
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
        return self._post("/rpc/createCollection", payload)

    def get(self, collection_id: str) -> dict[str, object]:
        return self._post("/rpc/getCollection", {"collectionId": collection_id}, retry_policy=TRANSIENT_RETRY_POLICY)

    def get_content(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/getCollectionContent", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateCollection", payload)

    def move(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/moveCollection", payload)

    def delete(self, collection_id: str) -> None:
        self._post("/rpc/deleteCollection", {"collectionId": collection_id})


class CollectionService(CollectionOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: CollectionAPI,
        navigation_operations: NavigationOperations,
        dto_module: CollectionDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    def _to_domain(self, response: dict[str, object], *, operation: str) -> Collection:
        try:
            return CollectionConverter.to_domain(
                response,
                installation=self._installation,
                operations=self,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc

    def create_collection(self, builder: CollectionCreate) -> Collection:
        spec = builder.to_spec()
        try:
            dto = CollectionConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createCollection", reason=str(exc)) from exc
        return self._to_domain(self._api.create(dto.to_payload()), operation="createCollection")

    def get_collection(self, collection_id: str) -> Collection:
        return self._to_domain(self._api.get(collection_id), operation="getCollection")

    def update_collection(self, builder: CollectionUpdate) -> Collection:
        spec = builder.to_spec()
        try:
            dto = CollectionConverter.from_domain_update(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateCollection", reason=str(exc)) from exc
        return self._to_domain(self._api.update(dto.to_payload()), operation="updateCollection")

    def delete_collection(self, collection_id: str) -> None:
        self._api.delete(collection_id)

    def move_collection(
        self,
        collection: Collection,
        location: EntryLocation | None,
        *,
        name: str | None = None,
    ) -> Collection:
        try:
            dto = CollectionConverter.from_domain_move(
                collection,
                location,
                name=name,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="moveCollection", reason=str(exc)) from exc
        return self._to_domain(self._api.move(dto.to_payload()), operation="moveCollection")

    def list_collection_entries(
        self,
        collection_id: str,
        options: CollectionListOptions,
    ) -> Pager[StructureSummary]:
        return self._navigation_operations.list_collection_entries(collection_id, options)
