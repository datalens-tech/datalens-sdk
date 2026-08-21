from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module, resources
from importlib.metadata import PackageNotFoundError, version
import json
from typing import TYPE_CHECKING, ClassVar, Generic, Protocol, TypedDict, TypeVar, cast
import warnings

import httpx

from datalens_sdk.api.chart import ChartAPI, ChartService
from datalens_sdk.api.collection import CollectionAPI, CollectionService
from datalens_sdk.api.connection import ConnectionAPI, ConnectionService
from datalens_sdk.api.dashboard import DashboardAPI, DashboardService
from datalens_sdk.api.dataset import DatasetAPI, DatasetService
from datalens_sdk.api.entries import EntriesAPI, EntriesDtoModule, EntriesService
from datalens_sdk.api.folder import FolderAPI, FolderService
from datalens_sdk.api.license import LicenseAPI, LicenseService
from datalens_sdk.api.navigation import NavigationService
from datalens_sdk.api.workbook import WorkbookAPI, WorkbookService
from datalens_sdk.auth import (
    AuthProviderProtocol,
    EnterpriseServiceAccountCredentialsAuthProvider,
    NoAuthProvider,
    YCIAMAuthProvider,
    _AuthProviderHTTPXAuth,
)
from datalens_sdk.converter.collection import CollectionDtoModule
from datalens_sdk.converter.connection import ConnectionDtoModule
from datalens_sdk.converter.dashboard import DashboardDtoModule
from datalens_sdk.converter.dataset import DatasetDtoModule
from datalens_sdk.converter.editor_chart import EditorChartDtoModule, editor_wire_types
from datalens_sdk.converter.folder import FolderDtoModule
from datalens_sdk.converter.license import LicenseDtoModule
from datalens_sdk.converter.wizard_chart import WizardChartDtoModule
from datalens_sdk.converter.workbook import WorkbookDtoModule
from datalens_sdk.domain.collection import Collection, CollectionCreate
from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_create import DashboardCreate
from datalens_sdk.domain.dataset import Dataset, DatasetCreate, SourceBuilder
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.entry_types import EntryBranch
from datalens_sdk.domain.folder import Folder, FolderCreate
from datalens_sdk.domain.license import (
    License,
    LicenseLimits,
    LicenseListOptions,
    LicenseSortField,
    LicenseStatus,
)
from datalens_sdk.domain.navigation import (
    EntryOrderField,
    EntrySummary,
    GetEntriesOptions,
    Pager,
    SortDirection,
)
from datalens_sdk.domain.ports import (
    ChartOperations,
    CollectionOperations,
    ConnectionOperations,
    DashboardOperations,
    DatasetOperations,
    FolderOperations,
    LicenseOperations,
    NavigationOperations,
    WorkbookOperations,
)
from datalens_sdk.domain.ql_chart import QLChart
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.domain.workbook import Workbook, WorkbookCreate
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError, NotSupportedError
from datalens_sdk.http import (
    DataLensHTTPClient,
    HTTPClientProtocol,
    HTTPEventHooks,
)
from datalens_sdk.raw import RawNamespace
from datalens_sdk.recipes.dashboard_export import DashboardBundleExporter

if TYPE_CHECKING:
    from datalens_sdk._generated.builders.charts import (
        EnterpriseEditorChartCreateFactory,
        QLChartCreateFactory,
        WizardChartCreateFactory,
        YacloudEditorChartCreateFactory,
    )
    from datalens_sdk._generated.builders.dataset_sources import (
        EnterpriseSourceCreateFactory,
        YacloudSourceCreateFactory,
    )
    from datalens_sdk._generated.builders.enterprise import (
        ConnectionCreateFactory as EnterpriseConnectionCreateFactory,
    )
    from datalens_sdk._generated.builders.yacloud import (
        ConnectionCreateFactory as YacloudConnectionCreateFactory,
    )


ConnectionFactoryT_co = TypeVar("ConnectionFactoryT_co", covariant=True)
SourceFactoryT_co = TypeVar("SourceFactoryT_co", bound=SourceBuilder, covariant=True)
EditorChartFactoryT_co = TypeVar("EditorChartFactoryT_co", covariant=True)
_DEFAULT_AUTH_PROVIDER = cast(AuthProviderProtocol, object())


def _distribution_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


class SourceFactoryConstructor(Protocol[SourceFactoryT_co]):
    def __call__(self, *, connection: Connection, operations: DatasetOperations | None = None) -> SourceFactoryT_co: ...


class ChartFactoryCapabilities(TypedDict):
    wizard: list[str]
    ql: list[str]
    editor: list[str]


class InstallationInfo(TypedDict):
    connectors: dict[str, object]
    dataset_sources: dict[str, object]
    namespaces: list[str]
    chart_factories: ChartFactoryCapabilities


def _class_name(value: str, suffix: str) -> str:
    return "".join(part.capitalize() for part in value.split("_")) + suffix


def _string_keyed_dict(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} metadata is invalid")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{context} metadata contains a non-string key")
        result[key] = item
    return result


def _string_list(value: object, *, context: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{context} metadata is invalid")
    return list(value)


def _chart_factory_capabilities(value: object, *, context: str) -> ChartFactoryCapabilities:
    raw = _string_keyed_dict(value, context=context)
    expected = {"wizard", "ql", "editor"}
    if set(raw) != expected:
        raise TypeError(f"{context} metadata must contain exactly {sorted(expected)!r}")
    return {
        "wizard": _string_list(raw["wizard"], context=f"{context}.wizard"),
        "ql": _string_list(raw["ql"], context=f"{context}.ql"),
        "editor": _string_list(raw["editor"], context=f"{context}.editor"),
    }


def _load_installations(generated_package: str) -> dict[str, InstallationInfo]:
    text = resources.files(generated_package).joinpath("installations.json").read_text()
    data: object = json.loads(text)
    if not isinstance(data, Mapping):
        raise TypeError("installations metadata is invalid")
    installations = data.get("installations")
    if not isinstance(installations, dict):
        raise TypeError("installations metadata is invalid")
    result: dict[str, InstallationInfo] = {}
    for name, info in installations.items():
        if not isinstance(name, str) or not isinstance(info, Mapping):
            raise TypeError("installations metadata is invalid")
        result[name] = {
            "connectors": _string_keyed_dict(info.get("connectors"), context=f"{name}.connectors"),
            "dataset_sources": _string_keyed_dict(
                info.get("dataset_sources"),
                context=f"{name}.dataset_sources",
            ),
            "namespaces": _string_list(info.get("namespaces"), context=f"{name}.namespaces"),
            "chart_factories": _chart_factory_capabilities(
                info.get("chart_factories"),
                context=f"{name}.chart_factories",
            ),
        }
    return result


class DatasetCreateFactory:
    def __init__(self, *, installation: str, operations: DatasetOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(self, *, name: str, location: EntryLocation) -> DatasetCreate:
        return DatasetCreate(
            installation=self._installation,
            location=location,
            name=name,
            operations=self._operations,
        )


class DashboardCreateFactory:
    def __init__(self, *, installation: str, operations: DashboardOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(self, *, name: str, location: EntryLocation) -> DashboardCreate:
        return DashboardCreate(
            installation=self._installation,
            location=location,
            name=name,
            operations=self._operations,
        )


class CreateNamespace(Generic[ConnectionFactoryT_co, SourceFactoryT_co, EditorChartFactoryT_co]):
    def __init__(
        self,
        *,
        installation: str,
        connection_operations: ConnectionOperations,
        dashboard_operations: DashboardOperations,
        dataset_operations: DatasetOperations,
        chart_operations: ChartOperations,
        collection_operations: CollectionOperations,
        workbook_operations: WorkbookOperations,
        folder_operations: FolderOperations,
        connection_factory: ConnectionFactoryT_co,
        source_factory_cls: SourceFactoryConstructor[SourceFactoryT_co],
        wizard_chart_factory: WizardChartCreateFactory,
        editor_chart_factory: EditorChartFactoryT_co,
        ql_chart_factory: QLChartCreateFactory,
    ) -> None:
        self._installation = installation
        self._collection_operations = collection_operations
        self._dataset_operations = dataset_operations
        self._chart_operations = chart_operations
        self._folder_operations = folder_operations
        self._workbook_operations = workbook_operations
        self._source_factory_cls = source_factory_cls
        self._connection = connection_factory
        self._wizard_chart_factory = wizard_chart_factory
        self._editor_chart_factory = editor_chart_factory
        self._ql_chart_factory = ql_chart_factory
        self._dataset = DatasetCreateFactory(installation=installation, operations=dataset_operations)
        self._dashboard = DashboardCreateFactory(installation=installation, operations=dashboard_operations)

    @property
    def connection(self) -> ConnectionFactoryT_co:
        return self._connection

    @property
    def dashboard(self) -> DashboardCreateFactory:
        return self._dashboard

    @property
    def dataset(self) -> DatasetCreateFactory:
        return self._dataset

    @property
    def wizard_chart(self) -> WizardChartCreateFactory:
        return self._wizard_chart_factory

    @property
    def editor_chart(self) -> EditorChartFactoryT_co:
        return self._editor_chart_factory

    @property
    def ql_chart(self) -> QLChartCreateFactory:
        return self._ql_chart_factory

    def source(self, *, using: Connection) -> SourceFactoryT_co:
        return self._source_factory_cls(connection=using, operations=self._dataset_operations)

    def collection(self, *, name: str, parent: EntryLocation | None = None) -> CollectionCreate:
        return CollectionCreate(
            installation=self._installation,
            name=name,
            parent=parent,
            operations=self._collection_operations,
        )

    def workbook(self, *, name: str, collection: EntryLocation | None = None) -> WorkbookCreate:
        return WorkbookCreate(
            installation=self._installation,
            name=name,
            collection=collection,
            operations=self._workbook_operations,
        )

    def folder(self, *, name: str, location: EntryLocation) -> FolderCreate:
        return FolderCreate(
            installation=self._installation,
            location=location,
            name=name,
            operations=self._folder_operations,
        )


class GetNamespace:
    def __init__(
        self,
        *,
        chart_operations: ChartOperations,
        collection_operations: CollectionOperations,
        connection_operations: ConnectionOperations,
        dashboard_operations: DashboardOperations,
        dataset_operations: DatasetOperations,
        folder_operations: FolderOperations,
        workbook_operations: WorkbookOperations,
    ) -> None:
        self._chart_operations = chart_operations
        self._collection_operations = collection_operations
        self._connection_operations = connection_operations
        self._dashboard_operations = dashboard_operations
        self._dataset_operations = dataset_operations
        self._folder_operations = folder_operations
        self._workbook_operations = workbook_operations

    def connection(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Connection:
        if by_id is None:
            raise ValueError("by_id must be provided")
        return self._connection_operations.get_connection(by_id, workbook_id=workbook_id, rev_id=rev_id)

    def dashboard(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> Dashboard:
        if by_id is None:
            raise ValueError("by_id must be provided")
        if rev_id is not None and branch is not None:
            # stacklevel=2 points at the user callsite; the converter silently drops branch.
            warnings.warn(
                "branch is ignored because an explicit rev_id already pins the revision",
                UserWarning,
                stacklevel=2,
            )
        return self._dashboard_operations.get_dashboard(by_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)

    def dataset(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Dataset:
        if by_id is None:
            raise ValueError("by_id must be provided")
        return self._dataset_operations.get_dataset(by_id, workbook_id=workbook_id, rev_id=rev_id)

    def wizard_chart(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> WizardChart:
        if by_id is None:
            raise ValueError("by_id must be provided")
        if rev_id is not None and branch is not None:
            # stacklevel=2 points at the user callsite; the API layer silently drops branch.
            warnings.warn(
                "branch is ignored because an explicit rev_id already pins the revision",
                UserWarning,
                stacklevel=2,
            )
        return self._chart_operations.get_wizard_chart(by_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)

    def chart(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> WizardChart | EditorChart | QLChart:
        if by_id is None:
            raise ValueError("by_id must be provided")
        if rev_id is not None and branch is not None:
            warnings.warn(
                "branch is ignored because an explicit rev_id already pins the revision",
                UserWarning,
                stacklevel=2,
            )
        return self._chart_operations.get_chart(by_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)

    def editor_chart(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> EditorChart:
        if by_id is None:
            raise ValueError("by_id must be provided")
        if rev_id is not None and branch is not None:
            warnings.warn(
                "branch is ignored because an explicit rev_id already pins the revision",
                UserWarning,
                stacklevel=2,
            )
        return self._chart_operations.get_editor_chart(by_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)

    def ql_chart(
        self,
        *,
        by_id: str | None = None,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> QLChart:
        if by_id is None:
            raise ValueError("by_id must be provided")
        if rev_id is not None and branch is not None:
            warnings.warn(
                "branch is ignored because an explicit rev_id already pins the revision",
                UserWarning,
                stacklevel=2,
            )
        return self._chart_operations.get_ql_chart(by_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)

    def collection(self, *, by_id: str | None = None) -> Collection:
        if by_id is None:
            raise ValueError("by_id must be provided")
        return self._collection_operations.get_collection(by_id)

    def workbook(self, *, by_id: str | None = None) -> Workbook:
        if by_id is None:
            raise ValueError("by_id must be provided")
        return self._workbook_operations.get_workbook(by_id)

    def folder(self, *, by_path: str | None = None) -> Folder:
        if by_path is None:
            raise ValueError("by_path must be provided")
        return self._folder_operations.get_folder(by_path)


class NavigationNamespace:
    def __init__(self, operations: NavigationOperations) -> None:
        self._operations = operations

    def get_entries(
        self,
        *,
        ids: Sequence[str] = (),
        created_by: Sequence[str] = (),
        name: str | None = None,
        exclude_locked: bool | None = None,
        ignore_shared_entries: bool | None = None,
        ignore_workbook_entries: bool | None = None,
        include_data: bool | None = None,
        include_links: bool | None = None,
        include_permissions_info: bool | None = None,
        order_by: EntryOrderField | None = None,
        order_direction: SortDirection = "asc",
        page_size: int = 100,
        scope: str | None = None,
        type: str | None = None,
    ) -> Pager[EntrySummary]:
        return self._operations.get_entries(
            GetEntriesOptions.create(
                ids=ids,
                created_by=created_by,
                name=name,
                exclude_locked=exclude_locked,
                ignore_shared_entries=ignore_shared_entries,
                ignore_workbook_entries=ignore_workbook_entries,
                include_data=include_data,
                include_links=include_links,
                include_permissions_info=include_permissions_info,
                order_by=order_by,
                order_direction=order_direction,
                page_size=page_size,
                scope=scope,
                type=type,
            )
        )


class LicensesNamespace:
    def __init__(self, operations: LicenseOperations) -> None:
        self._operations = operations

    def assign(self, *, user_ids: Sequence[str]) -> tuple[License, ...]:
        ids = tuple(user_ids)
        if not 1 <= len(ids) <= 1000:
            raise DataLensValidationError("user_ids must contain between 1 and 1000 items")
        return self._operations.assign_licenses(ids)

    def list(
        self,
        *,
        user_ids: Sequence[str] = (),
        status: LicenseStatus | None = None,
        sort_by: LicenseSortField | None = None,
        order: SortDirection = "asc",
        page_size: int = 100,
    ) -> Pager[License]:
        return self._operations.list_licenses(
            LicenseListOptions.create(
                user_ids=user_ids,
                status=status,
                sort_by=sort_by,
                order=order,
                page_size=page_size,
            )
        )

    def get_limit(self) -> LicenseLimits:
        return self._operations.get_license_limits()

    def set_limit(self, *, value: int) -> LicenseLimits:
        if not 1 <= value <= 10000:
            raise DataLensValidationError("value must be between 1 and 10000")
        return self._operations.set_license_limit(value)


class DataLensClientBase:
    INSTALLATION = ""
    GENERATED_PACKAGE = "datalens_sdk._generated"
    SDK_DISTRIBUTION = "datalens-sdk"
    DEFAULT_BASE_URL = ""
    KNOWN_NAMESPACE_OWNERS: ClassVar[dict[str, list[str]]] = {}
    get: GetNamespace
    navigation: NavigationNamespace
    raw: RawNamespace

    @classmethod
    def _get_default_auth_provider(cls) -> AuthProviderProtocol:
        return NoAuthProvider()

    def __init__(
        self,
        *,
        auth: AuthProviderProtocol | None = _DEFAULT_AUTH_PROVIDER,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        event_hooks: HTTPEventHooks | None = None,
        http_client: HTTPClientProtocol | None = None,
    ) -> None:
        if not self.INSTALLATION:
            raise TypeError("INSTALLATION must be defined by subclasses")
        self._installations = _load_installations(self.GENERATED_PACKAGE)
        self._installation_info = self._installations[self.INSTALLATION]
        if http_client is not None:
            if auth is not _DEFAULT_AUTH_PROVIDER or any(
                value is not None for value in (base_url, transport, event_hooks)
            ):
                raise DataLensConfigurationError(
                    "http_client cannot be combined with auth, base_url, transport, or event_hooks"
                )
            self._http = http_client
            self._owns_http_client = False
        else:
            resolved_base_url = base_url or self.DEFAULT_BASE_URL
            if not resolved_base_url:
                raise DataLensConfigurationError(f"{type(self).__name__} requires base_url.")
            if auth is _DEFAULT_AUTH_PROVIDER:
                auth_provider = self._get_default_auth_provider()
            elif auth is None:
                auth_provider = NoAuthProvider()
            else:
                auth_provider = auth
            if self.INSTALLATION == "enterprise" and isinstance(
                auth_provider, EnterpriseServiceAccountCredentialsAuthProvider
            ):
                auth_provider.set_base_url(resolved_base_url)
            self._http = DataLensHTTPClient(
                installation=self.INSTALLATION,
                sdk_version=_distribution_version(self.SDK_DISTRIBUTION),
                base_url=resolved_base_url,
                auth=_AuthProviderHTTPXAuth(auth_provider),
                transport=transport,
                event_hooks=event_hooks,
            )
            self._owns_http_client = True
        dto_module = import_module(f"{self.GENERATED_PACKAGE}.dto")
        entries_api = EntriesAPI(self._http)
        entries_service = EntriesService(
            api=entries_api,
            dto_module=cast(EntriesDtoModule, dto_module),
        )
        collection_api = CollectionAPI(self._http)
        workbook_api = WorkbookAPI(self._http)
        self._navigation_service = NavigationService(
            entries_api=entries_api,
            entries_service=entries_service,
            collection_api=collection_api,
            workbook_api=workbook_api,
            dto_module=cast(EntriesDtoModule, dto_module),
        )
        self._collection_service = CollectionService(
            installation=self.INSTALLATION,
            api=collection_api,
            navigation_operations=self._navigation_service,
            dto_module=cast(CollectionDtoModule, dto_module),
        )
        self._connection_service = ConnectionService(
            installation=self.INSTALLATION,
            api=ConnectionAPI(self._http),
            entries_service=entries_service,
            navigation_operations=self._navigation_service,
            dto_module=cast(ConnectionDtoModule, dto_module),
        )
        self._dataset_service = DatasetService(
            installation=self.INSTALLATION,
            api=DatasetAPI(self._http),
            entries_service=entries_service,
            navigation_operations=self._navigation_service,
            dto_module=cast(DatasetDtoModule, dto_module),
        )
        self._chart_service = ChartService(
            installation=self.INSTALLATION,
            api=ChartAPI(self._http),
            entries_service=entries_service,
            navigation_operations=self._navigation_service,
            dto_module=cast(WizardChartDtoModule, dto_module),
        )
        dashboard_bundle_exporter = DashboardBundleExporter(
            navigation_operations=self._navigation_service,
            chart_operations=self._chart_service,
            dataset_operations=self._dataset_service,
            editor_wire_types=editor_wire_types(
                self.INSTALLATION,
                cast(EditorChartDtoModule, dto_module),
            ),
        )
        self._dashboard_service = DashboardService(
            installation=self.INSTALLATION,
            api=DashboardAPI(self._http),
            entries_service=entries_service,
            navigation_operations=self._navigation_service,
            bundle_exporter=dashboard_bundle_exporter,
            dto_module=cast(DashboardDtoModule, dto_module),
        )
        self._folder_service = FolderService(
            installation=self.INSTALLATION,
            api=FolderAPI(self._http),
            entries_service=entries_service,
            navigation_operations=self._navigation_service,
            dto_module=cast(FolderDtoModule, dto_module),
        )
        self._workbook_service = WorkbookService(
            installation=self.INSTALLATION,
            api=workbook_api,
            navigation_operations=self._navigation_service,
            dto_module=cast(WorkbookDtoModule, dto_module),
        )

        connection_module = import_module(f"{self.GENERATED_PACKAGE}.builders.{self.INSTALLATION}")
        source_module = import_module(f"{self.GENERATED_PACKAGE}.builders.dataset_sources")
        charts_module = import_module(f"{self.GENERATED_PACKAGE}.builders.charts")
        connection_factory = cast(object, connection_module.ConnectionCreateFactory(self._connection_service))
        source_factory_cls = cast(
            SourceFactoryConstructor[SourceBuilder],
            getattr(source_module, _class_name(self.INSTALLATION, "SourceCreateFactory")),
        )
        wizard_chart_factory = cast(
            "WizardChartCreateFactory", charts_module.WizardChartCreateFactory(self._chart_service)
        )
        editor_chart_factory = cast(
            object,
            getattr(charts_module, _class_name(self.INSTALLATION, "EditorChartCreateFactory"))(self._chart_service),
        )
        ql_chart_factory = cast("QLChartCreateFactory", charts_module.QLChartCreateFactory(self._chart_service))
        self.create = CreateNamespace(
            installation=self.INSTALLATION,
            collection_operations=self._collection_service,
            connection_operations=self._connection_service,
            dashboard_operations=self._dashboard_service,
            dataset_operations=self._dataset_service,
            chart_operations=self._chart_service,
            folder_operations=self._folder_service,
            workbook_operations=self._workbook_service,
            connection_factory=connection_factory,
            source_factory_cls=source_factory_cls,
            wizard_chart_factory=wizard_chart_factory,
            editor_chart_factory=editor_chart_factory,
            ql_chart_factory=ql_chart_factory,
        )
        self.raw = RawNamespace(
            installation=self.INSTALLATION,
            connection_operations=self._connection_service,
            dataset_operations=self._dataset_service,
            dashboard_operations=self._dashboard_service,
            chart_operations=self._chart_service,
        )
        self.get = GetNamespace(
            chart_operations=self._chart_service,
            collection_operations=self._collection_service,
            connection_operations=self._connection_service,
            dashboard_operations=self._dashboard_service,
            dataset_operations=self._dataset_service,
            folder_operations=self._folder_service,
            workbook_operations=self._workbook_service,
        )
        self.navigation = NavigationNamespace(self._navigation_service)
        if "licenses" in self._installation_info["namespaces"]:
            self._license_service = LicenseService(
                api=LicenseAPI(self._http),
                dto_module=cast(LicenseDtoModule, dto_module),
            )
            self.licenses = LicensesNamespace(self._license_service)

    @property
    def capabilities(self) -> InstallationInfo:
        return self._installation_info

    def close(self) -> None:
        if self._owns_http_client:
            cast(DataLensHTTPClient, self._http).close()

    def __enter__(self) -> DataLensClientBase:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.close()

    # -- typed port accessors (epic D4) ---------------------------------------
    #
    # Public seams for recipes (validate_dashboard_refs, copy, decompile):
    # cross-entity helpers depend on these operation Protocols instead of the
    # concrete client or private service attributes.

    @property
    def dashboard_ops(self) -> DashboardOperations:
        return self._dashboard_service

    @property
    def chart_ops(self) -> ChartOperations:
        return self._chart_service

    @property
    def dataset_ops(self) -> DatasetOperations:
        return self._dataset_service

    def domain_connection(self, *, id: str, type: str, name: str | None = None) -> Connection:
        return Connection(
            id=id,
            type=type,
            name=name,
            installation=self.INSTALLATION,
            raw={"name": name} if name is not None else {},
            _operations=self._connection_service,
        )

    def __getattr__(self, name: str) -> object:
        owners = [
            installation
            for installation, info in sorted(self._installations.items())
            if name in info.get("namespaces", [])
        ]
        owners.extend(owner for owner in self.KNOWN_NAMESPACE_OWNERS.get(name, []) if owner not in owners)
        if owners:
            raise NotSupportedError(
                f"Namespace {name!r} is not available on installation {self.INSTALLATION!r}. Available on: {owners}"
            )
        raise AttributeError(name)


class DataLensClientYC(DataLensClientBase):
    INSTALLATION = "yacloud"
    DEFAULT_BASE_URL = "https://api.datalens.tech"

    @classmethod
    def _get_default_auth_provider(cls) -> AuthProviderProtocol:
        return YCIAMAuthProvider()

    if TYPE_CHECKING:
        create: CreateNamespace[
            YacloudConnectionCreateFactory, YacloudSourceCreateFactory, YacloudEditorChartCreateFactory
        ]
        licenses: LicensesNamespace


class DataLensClientEnterprise(DataLensClientBase):
    INSTALLATION = "enterprise"
    DEFAULT_BASE_URL = ""
    if TYPE_CHECKING:
        create: CreateNamespace[
            EnterpriseConnectionCreateFactory,
            EnterpriseSourceCreateFactory,
            EnterpriseEditorChartCreateFactory,
        ]
