from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import ValidationError

from datalens_sdk.api.entries import EntriesService
from datalens_sdk.converter.dashboard import DashboardConverter, DashboardDtoModule
from datalens_sdk.converter.dashboard_state import (
    MAX_STATE_DATA_SYMBOLS,
    DashboardStateConverter,
    DashboardStateDtoModule,
)
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_create import DashboardCreate
from datalens_sdk.domain.dashboard_update import DashboardUpdate
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.entry_state import DashboardStateData, DashboardStateRecord
from datalens_sdk.domain.entry_types import EntryBranch
from datalens_sdk.domain.navigation import EntryRelation, Pager, RelationOptions
from datalens_sdk.domain.ports import (
    ChartOperations,
    DashboardOperations,
    DatasetOperations,
    NavigationOperations,
    ScreenshotOperations,
)
from datalens_sdk.domain.revisions import EntryRevision, EntryRevisionsOptions
from datalens_sdk.domain.screenshot import EntityScreenshot, ScreenshotRequest
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
)
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy
from datalens_sdk.recipes.dashboard_export import DashboardBundleExporter
from datalens_sdk.serialization.artifacts import ArtifactPath


class DashboardAPI:
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

    def get(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/getDashboard", payload, retry_policy=TRANSIENT_RETRY_POLICY)

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/createDashboard", payload)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateDashboard", payload)

    def delete(self, payload: dict[str, object]) -> None:
        self._post("/rpc/deleteDashboard", payload)


class DashboardService(DashboardOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: DashboardAPI,
        entries_service: EntriesService,
        navigation_operations: NavigationOperations,
        bundle_exporter: DashboardBundleExporter,
        screenshot_operations: ScreenshotOperations,
        chart_operations: ChartOperations,
        dataset_operations: DatasetOperations,
        ui_base_url: str | None = None,
        dto_module: DashboardDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._entries_service = entries_service
        self._navigation_operations = navigation_operations
        self._screenshot_operations = screenshot_operations
        self._chart_operations = chart_operations
        self._dataset_operations = dataset_operations
        self._ui_base_url = ui_base_url
        self._bundle_exporter = bundle_exporter
        self._dto_module = dto_module

    @property
    def installation(self) -> str:
        return self._installation

    @property
    def chart_operations(self) -> ChartOperations:
        return self._chart_operations

    @property
    def dataset_operations(self) -> DatasetOperations:
        return self._dataset_operations

    @property
    def ui_base_url(self) -> str | None:
        return self._ui_base_url

    def _to_domain(
        self,
        response: dict[str, object],
        *,
        operation: str,
        location: EntryLocation | None = None,
        name: str | None = None,
    ) -> Dashboard:
        try:
            return DashboardConverter.to_domain(
                response,
                installation=self._installation,
                operations=self,
                location=location,
                name=name,
                operation=operation,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc

    def create_dashboard(self, builder: DashboardCreate) -> Dashboard:
        spec = builder.to_spec()
        try:
            dto = DashboardConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createDashboard", reason=str(exc)) from exc
        response = self._api.create(dto.to_payload())
        # A workbook entry's key is nullable on the wire: without the builder's
        # name/location fallback the returned Dashboard would carry name=None.
        return self._to_domain(
            response,
            operation="createDashboard",
            location=spec.location,
            name=spec.name,
        )

    def create_dashboard_from_raw(self, spec: RawCreateSpec) -> Dashboard:
        try:
            payload = DashboardConverter.from_raw_create(spec).to_payload()
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createDashboard", reason=str(exc)) from exc
        response = self._api.create(payload)
        return self._to_domain(
            response,
            operation="createDashboard",
            location=spec.location,
            name=spec.name,
        )

    def update_dashboard(
        self,
        builder: DashboardUpdate,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard:
        spec = builder.to_spec()
        try:
            dto = DashboardConverter.from_domain_update(
                spec,
                publish=publish,
                lock_token=lock_token,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateDashboard", reason=str(exc)) from exc
        response = self._api.update(dto.to_payload())
        # location/name come from the spec snapshot: a keyless workbook
        # dashboard would otherwise return with name=None (same fallback as create).
        return self._to_domain(
            response,
            operation="updateDashboard",
            location=spec.location,
            name=spec.name,
        )

    def replace_dashboard_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard:
        try:
            payload = DashboardConverter.from_raw_replace(
                spec,
                publish=publish,
                lock_token=lock_token,
            ).to_payload()
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateDashboard", reason=str(exc)) from exc
        response = self._api.update(payload)
        return self._to_domain(
            response,
            operation="updateDashboard",
            location=spec.target_location,
            name=spec.target_name,
        )

    def publish_dashboard(
        self,
        dashboard: Dashboard,
        rev_id: str,
        lock_token: str | None = None,
    ) -> Dashboard:
        if not dashboard.id:
            raise DataLensValidationError("Cannot publish a dashboard without an id")
        raw_meta = dashboard.raw.get("meta")
        raw_annotation = dashboard.raw.get("annotation")
        try:
            dto = DashboardConverter.from_domain_publish_revision(
                dashboard.id,
                data=dashboard.data,
                meta=cast("dict[str, object]", raw_meta) if isinstance(raw_meta, dict) else None,
                annotation=cast("dict[str, object]", raw_annotation) if isinstance(raw_annotation, dict) else None,
                rev_id=rev_id,
                lock_token=lock_token,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateDashboard", reason=str(exc)) from exc
        response = self._api.update(dto.to_payload())
        return self._to_domain(
            response,
            operation="updateDashboard",
            location=dashboard.location,
            name=dashboard.name,
        )

    def get_dashboard(
        self,
        dashboard_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> Dashboard:
        try:
            args = DashboardConverter.from_domain_get(
                dashboard_id,
                workbook_id=workbook_id,
                branch=branch,
                rev_id=rev_id,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getDashboard", reason=str(exc)) from exc
        response = self._api.get(args.to_payload())
        return self._to_domain(response, operation="getDashboard")

    def delete_dashboard(self, dashboard_id: str, lock_token: str | None = None) -> None:
        try:
            args = DashboardConverter.from_domain_delete(
                dashboard_id,
                lock_token=lock_token,
                dto_module=self._dto_module,
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="deleteDashboard", reason=str(exc)) from exc
        self._api.delete(args.to_payload())

    def rename_dashboard(self, dashboard: Dashboard, name: str) -> Dashboard:
        if not dashboard.id:
            raise ValueError("Cannot rename a dashboard without an id")
        self._entries_service.rename_entry(entry_id=dashboard.id, name=name)
        return self.get_dashboard(dashboard.id, workbook_id=dashboard.workbook_id)

    def move_dashboard(
        self,
        dashboard: Dashboard,
        location: EntryLocation,
        *,
        name: str | None = None,
    ) -> Dashboard:
        if not dashboard.id:
            raise DataLensValidationError("Cannot move a dashboard without an id")
        self._navigation_operations.move_folder_entry(entry_id=dashboard.id, location=location, name=name)
        return self.get_dashboard(dashboard.id)

    def get_entry_revisions(self, entry_id: str, options: EntryRevisionsOptions) -> Pager[EntryRevision]:
        return self._entries_service.get_entry_revisions(entry_id, options)

    def get_dashboard_state(self, entry_id: str, hash: str) -> DashboardStateRecord:
        record = self._entries_service.get_entry_state(entry_id, hash)
        raw = record.data or {}
        try:
            data = DashboardStateConverter.to_domain(raw, dto_module=self._state_dto_module())
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="getEntryState", reason=str(exc)) from exc
        return DashboardStateRecord(hash=record.hash, data=data, raw=raw, created_at=record.created_at)

    def create_dashboard_state(self, entry_id: str, data: DashboardStateData) -> DashboardStateRecord:
        try:
            payload = DashboardStateConverter.to_payload(data, dto_module=self._state_dto_module())
        except ValidationError as exc:
            raise DataLensValidationError(str(exc)) from exc
        size = DashboardStateConverter.symbols(payload)
        if size > MAX_STATE_DATA_SYMBOLS:
            raise DataLensValidationError(
                f"Cannot create the dashboard state: state data has {size} characters, "
                f"the limit is {MAX_STATE_DATA_SYMBOLS}"
            )
        hash_value = self._entries_service.create_entry_state(entry_id, payload)
        return DashboardStateRecord(hash=hash_value, data=data, raw=payload)

    def _state_dto_module(self) -> DashboardStateDtoModule | None:
        return cast(DashboardStateDtoModule | None, self._dto_module)

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]:
        return self._navigation_operations.get_entry_relations(entry_id, options)

    def get_screenshot(self, request: ScreenshotRequest) -> EntityScreenshot:
        return self._screenshot_operations.get_screenshot(request)

    def get_screenshot_url(self, request: ScreenshotRequest) -> str:
        return self._screenshot_operations.get_screenshot_url(request)

    def export_dashboard_with_dependencies(
        self,
        dashboard: Dashboard,
        path: ArtifactPath,
    ) -> Path:
        return self._bundle_exporter.export(dashboard, path)
