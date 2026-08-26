from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datalens_sdk._runtime.builder_base import BaseConnectionCreate
    from datalens_sdk._runtime.chart_builder_base import (
        _BaseEditorNodeCreate,
        _BaseQLChartCreate,
        _BaseWizardChartCreate,
    )
    from datalens_sdk.domain.chart import Chart
    from datalens_sdk.domain.collection import Collection, CollectionCreate, CollectionUpdate
    from datalens_sdk.domain.connection import Connection, ConnectionUpdate
    from datalens_sdk.domain.dashboard import Dashboard
    from datalens_sdk.domain.dashboard_create import DashboardCreate
    from datalens_sdk.domain.dashboard_update import DashboardUpdate
    from datalens_sdk.domain.dataset import Dataset, DatasetCreate, Source
    from datalens_sdk.domain.dataset_types import RawSchemaColumnPayload
    from datalens_sdk.domain.dataset_update import DatasetUpdate
    from datalens_sdk.domain.editor_chart import EditorChart, EditorChartUpdate
    from datalens_sdk.domain.entry_location import EntryLocation
    from datalens_sdk.domain.entry_types import EntryBranch, EntryUpdateMode
    from datalens_sdk.domain.folder import Folder, FolderCreate, FolderUpdate
    from datalens_sdk.domain.license import License, LicenseLimits, LicenseListOptions
    from datalens_sdk.domain.navigation import (
        CollectionListOptions,
        DirectoryListOptions,
        DirectoryPager,
        EntryRelation,
        EntrySummary,
        GetEntriesOptions,
        Pager,
        RelationOptions,
        StructureSummary,
        WorkbookListOptions,
    )
    from datalens_sdk.domain.ql_chart import QLChart, QLChartUpdate
    from datalens_sdk.domain.specs.raw_resource import (
        RawCreateSpec,
        RawReplaceSpec,
    )
    from datalens_sdk.domain.wizard_chart import WizardChart, WizardChartUpdate
    from datalens_sdk.domain.workbook import Workbook, WorkbookCreate, WorkbookUpdate
    from datalens_sdk.serialization.artifacts import ArtifactPath
    from datalens_sdk.serialization.json_types import JsonObject


@runtime_checkable
class NavigationOperations(Protocol):
    def get_entries(self, options: GetEntriesOptions) -> Pager[EntrySummary]: ...

    def list_folder_entries(
        self,
        path: str,
        options: DirectoryListOptions,
    ) -> DirectoryPager[EntrySummary]: ...

    def move_folder_entry(
        self,
        *,
        entry_id: str,
        location: EntryLocation,
        name: str | None = None,
    ) -> None: ...

    def list_collection_entries(
        self,
        collection_id: str,
        options: CollectionListOptions,
    ) -> Pager[StructureSummary]: ...

    def list_workbook_entries(
        self,
        workbook_id: str,
        options: WorkbookListOptions,
    ) -> Pager[EntrySummary]: ...

    def get_entry_relations(
        self,
        entry_id: str,
        options: RelationOptions,
    ) -> Pager[EntryRelation]: ...


@runtime_checkable
class ConnectionOperations(Protocol):
    def create_connection(self, builder: BaseConnectionCreate) -> Connection: ...

    def create_connection_from_raw(
        self,
        spec: RawCreateSpec,
        *,
        overrides: JsonObject | None,
    ) -> Connection: ...

    def get_connection(
        self,
        connection_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Connection: ...

    def update_connection(self, builder: ConnectionUpdate) -> Connection: ...

    def replace_connection_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_connector_type: str,
        overrides: JsonObject | None,
    ) -> Connection: ...

    def delete_connection(self, connection_id: str) -> None: ...

    def rename_connection(self, connection: Connection, name: str) -> Connection: ...

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]: ...


@runtime_checkable
class DatasetOperations(Protocol):
    def create_dataset(self, builder: DatasetCreate) -> Dataset: ...

    def create_dataset_from_raw(self, spec: RawCreateSpec) -> Dataset: ...

    def get_dataset(
        self,
        dataset_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Dataset: ...

    def update_dataset(self, builder: DatasetUpdate) -> Dataset: ...

    def replace_dataset_from_raw(self, spec: RawReplaceSpec) -> Dataset: ...

    def delete_dataset(self, dataset_id: str) -> None: ...

    def rename_dataset(self, dataset: Dataset, name: str) -> Dataset: ...

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]: ...

    def validate_source(
        self,
        source: Source,
        *,
        strict: bool = False,
    ) -> tuple[tuple[RawSchemaColumnPayload, ...], bool]: ...


@runtime_checkable
class CollectionOperations(Protocol):
    def create_collection(self, builder: CollectionCreate) -> Collection: ...

    def get_collection(self, collection_id: str) -> Collection: ...

    def update_collection(self, builder: CollectionUpdate) -> Collection: ...

    def delete_collection(self, collection_id: str) -> None: ...

    def move_collection(
        self,
        collection: Collection,
        location: EntryLocation | None,
        *,
        name: str | None = None,
    ) -> Collection: ...

    def list_collection_entries(
        self,
        collection_id: str,
        options: CollectionListOptions,
    ) -> Pager[StructureSummary]: ...


@runtime_checkable
class WorkbookOperations(Protocol):
    def create_workbook(self, builder: WorkbookCreate) -> Workbook: ...

    def get_workbook(self, workbook_id: str) -> Workbook: ...

    def update_workbook(self, builder: WorkbookUpdate) -> Workbook: ...

    def delete_workbook(self, workbook_id: str) -> None: ...

    def move_workbook(
        self,
        workbook: Workbook,
        location: EntryLocation | None,
        *,
        name: str | None = None,
    ) -> Workbook: ...

    def list_workbook_entries(
        self,
        workbook_id: str,
        options: WorkbookListOptions,
    ) -> Pager[EntrySummary]: ...


@runtime_checkable
class FolderOperations(Protocol):
    def create_folder(self, builder: FolderCreate) -> Folder: ...

    def get_folder(self, path: str) -> Folder: ...

    def update_folder(self, builder: FolderUpdate) -> Folder: ...

    def delete_folder(self, folder_id: str) -> None: ...

    def move_folder(self, folder: Folder, location: EntryLocation, *, name: str | None = None) -> Folder: ...

    def list_folder_entries(
        self,
        path: str,
        options: DirectoryListOptions,
    ) -> DirectoryPager[EntrySummary]: ...


@runtime_checkable
class DashboardOperations(Protocol):
    def create_dashboard(self, builder: DashboardCreate) -> Dashboard: ...

    def create_dashboard_from_raw(self, spec: RawCreateSpec) -> Dashboard: ...

    def update_dashboard(
        self,
        builder: DashboardUpdate,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard: ...

    def replace_dashboard_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard: ...

    def publish_dashboard(
        self,
        dashboard: Dashboard,
        rev_id: str,
        lock_token: str | None = None,
    ) -> Dashboard: ...

    def get_dashboard(
        self,
        dashboard_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> Dashboard: ...

    def delete_dashboard(self, dashboard_id: str, lock_token: str | None = None) -> None: ...

    def rename_dashboard(self, dashboard: Dashboard, name: str) -> Dashboard: ...

    def get_entry_relations(
        self,
        entry_id: str,
        options: RelationOptions,
    ) -> Pager[EntryRelation]: ...

    def export_dashboard_with_dependencies(
        self,
        dashboard: Dashboard,
        path: ArtifactPath,
    ) -> Path: ...


@runtime_checkable
class LicenseOperations(Protocol):
    def assign_licenses(self, user_ids: Sequence[str]) -> tuple[License, ...]: ...

    def list_licenses(self, options: LicenseListOptions) -> Pager[License]: ...

    def get_license_limits(self) -> LicenseLimits: ...

    def set_license_limit(self, value: int) -> LicenseLimits: ...


@runtime_checkable
class ChartOperations(Protocol):
    @property
    def installation(self) -> str: ...

    def create_wizard_chart(self, builder: _BaseWizardChartCreate) -> WizardChart: ...

    def create_wizard_chart_from_raw(self, spec: RawCreateSpec) -> WizardChart: ...

    def get_wizard_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> WizardChart: ...

    def update_wizard_chart(self, builder: WizardChartUpdate) -> WizardChart: ...

    def publish_wizard_chart(self, chart: WizardChart, rev_id: str) -> WizardChart: ...

    def replace_wizard_chart_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
    ) -> WizardChart: ...

    def delete_wizard_chart(self, chart_id: str) -> None: ...

    def create_editor_chart(self, builder: _BaseEditorNodeCreate) -> EditorChart: ...

    def create_editor_chart_from_raw(self, spec: RawCreateSpec) -> EditorChart: ...

    def get_editor_chart(
        self,
        entry_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> EditorChart: ...

    def update_editor_chart(self, builder: EditorChartUpdate) -> EditorChart: ...

    def replace_editor_chart_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
    ) -> EditorChart: ...

    def delete_editor_chart(self, entry_id: str) -> None: ...

    def create_ql_chart(self, builder: _BaseQLChartCreate) -> QLChart: ...

    def create_ql_chart_from_raw(self, spec: RawCreateSpec) -> QLChart: ...

    def get_ql_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> QLChart: ...

    def update_ql_chart(self, builder: QLChartUpdate) -> QLChart: ...

    def replace_ql_chart_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
    ) -> QLChart: ...

    def delete_ql_chart(self, chart_id: str) -> None: ...

    def get_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> WizardChart | EditorChart | QLChart: ...

    def rename_chart(self, chart: Chart, name: str) -> Chart: ...

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]: ...
