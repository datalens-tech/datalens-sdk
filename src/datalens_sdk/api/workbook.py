from __future__ import annotations

from pydantic import ValidationError

from datalens_sdk.converter.workbook import WorkbookConverter, WorkbookDtoModule
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.navigation import EntrySummary, Pager, WorkbookListOptions
from datalens_sdk.domain.ports import NavigationOperations, WorkbookOperations
from datalens_sdk.domain.workbook import Workbook, WorkbookCreate, WorkbookUpdate
from datalens_sdk.errors import translate_dto_validation_error
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy


class WorkbookAPI:
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
        return self._post("/rpc/createWorkbook", payload)

    def get(self, workbook_id: str) -> dict[str, object]:
        return self._post("/rpc/getWorkbook", {"workbookId": workbook_id}, retry_policy=TRANSIENT_RETRY_POLICY)

    def get_entries(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/getWorkbookEntries", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateWorkbook", payload)

    def move(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/moveWorkbook", payload)

    def delete(self, workbook_id: str) -> None:
        self._post("/rpc/deleteWorkbook", {"workbookId": workbook_id})


class WorkbookService(WorkbookOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: WorkbookAPI,
        navigation_operations: NavigationOperations,
        dto_module: WorkbookDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    def _to_domain(self, response: dict[str, object], *, operation: str) -> Workbook:
        try:
            return WorkbookConverter.to_domain(
                response,
                installation=self._installation,
                operations=self,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc

    def create_workbook(self, builder: WorkbookCreate) -> Workbook:
        spec = builder.to_spec()
        try:
            dto = WorkbookConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createWorkbook", reason=str(exc)) from exc
        return self._to_domain(self._api.create(dto.to_payload()), operation="createWorkbook")

    def get_workbook(self, workbook_id: str) -> Workbook:
        return self._to_domain(self._api.get(workbook_id), operation="getWorkbook")

    def update_workbook(self, builder: WorkbookUpdate) -> Workbook:
        spec = builder.to_spec()
        try:
            dto = WorkbookConverter.from_domain_update(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateWorkbook", reason=str(exc)) from exc
        return self._to_domain(self._api.update(dto.to_payload()), operation="updateWorkbook")

    def delete_workbook(self, workbook_id: str) -> None:
        self._api.delete(workbook_id)

    def move_workbook(
        self,
        workbook: Workbook,
        location: EntryLocation | None,
        *,
        name: str | None = None,
    ) -> Workbook:
        try:
            dto = WorkbookConverter.from_domain_move(
                workbook,
                location,
                name=name,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="moveWorkbook", reason=str(exc)) from exc
        return self._to_domain(self._api.move(dto.to_payload()), operation="moveWorkbook")

    def list_workbook_entries(
        self,
        workbook_id: str,
        options: WorkbookListOptions,
    ) -> Pager[EntrySummary]:
        return self._navigation_operations.list_workbook_entries(workbook_id, options)
