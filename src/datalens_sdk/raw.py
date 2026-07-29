from __future__ import annotations

from collections.abc import Mapping

from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.ports import (
    ChartOperations,
    ConnectionOperations,
    DashboardOperations,
    DatasetOperations,
)
from datalens_sdk.domain.ql_chart import QLChart
from datalens_sdk.domain.raw_dashboard import RawDashboardCreate, RawDashboardReplace
from datalens_sdk.domain.raw_resource import (
    RawConnectionCreate,
    RawConnectionReplace,
    RawDatasetCreate,
    RawDatasetReplace,
    RawEditorChartCreate,
    RawEditorChartReplace,
    RawQLChartCreate,
    RawQLChartReplace,
    RawWizardChartCreate,
    RawWizardChartReplace,
)
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.serialization.artifacts import (
    ArtifactPath,
    read_chart_artifact,
    read_connection_artifact,
    read_dashboard_artifact,
    read_dataset_artifact,
)
from datalens_sdk.serialization.json_types import JsonValue


class RawConnectionCreateFactory:
    def __init__(self, *, installation: str, operations: ConnectionOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        overrides: Mapping[str, JsonValue] | None = None,
    ) -> RawConnectionCreate:
        return RawConnectionCreate(
            response_snapshot=response_snapshot,
            name=name,
            location=location,
            installation=self._installation,
            overrides=overrides,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        name: str,
        location: EntryLocation,
        overrides: Mapping[str, JsonValue] | None = None,
    ) -> RawConnectionCreate:
        return self(
            response_snapshot=read_connection_artifact(path),
            name=name,
            location=location,
            overrides=overrides,
        )


class RawConnectionReplaceFactory:
    def __init__(self, *, installation: str, operations: ConnectionOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        target: Connection,
        response_snapshot: Mapping[str, JsonValue],
        overrides: Mapping[str, JsonValue] | None = None,
    ) -> RawConnectionReplace:
        return RawConnectionReplace(
            target=target,
            response_snapshot=response_snapshot,
            installation=self._installation,
            overrides=overrides,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        target: Connection,
        overrides: Mapping[str, JsonValue] | None = None,
    ) -> RawConnectionReplace:
        return self(
            response_snapshot=read_connection_artifact(path),
            target=target,
            overrides=overrides,
        )


class RawDatasetCreateFactory:
    def __init__(self, *, installation: str, operations: DatasetOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
    ) -> RawDatasetCreate:
        return RawDatasetCreate(
            response_snapshot=response_snapshot,
            name=name,
            location=location,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        name: str,
        location: EntryLocation,
    ) -> RawDatasetCreate:
        return self(
            response_snapshot=read_dataset_artifact(path),
            name=name,
            location=location,
        )


class RawDatasetReplaceFactory:
    def __init__(self, *, installation: str, operations: DatasetOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        target: Dataset,
        response_snapshot: Mapping[str, JsonValue],
    ) -> RawDatasetReplace:
        return RawDatasetReplace(
            target=target,
            response_snapshot=response_snapshot,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        target: Dataset,
    ) -> RawDatasetReplace:
        return self(
            response_snapshot=read_dataset_artifact(path),
            target=target,
        )


class RawDashboardCreateFactory:
    def __init__(self, *, installation: str, operations: DashboardOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
    ) -> RawDashboardCreate:
        return RawDashboardCreate(
            response_snapshot=response_snapshot,
            name=name,
            location=location,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        name: str,
        location: EntryLocation,
    ) -> RawDashboardCreate:
        return self(
            response_snapshot=read_dashboard_artifact(path),
            name=name,
            location=location,
        )


class RawDashboardReplaceFactory:
    def __init__(self, *, installation: str, operations: DashboardOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        target: Dashboard,
        response_snapshot: Mapping[str, JsonValue],
    ) -> RawDashboardReplace:
        return RawDashboardReplace(
            target=target,
            response_snapshot=response_snapshot,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        target: Dashboard,
    ) -> RawDashboardReplace:
        return self(
            response_snapshot=read_dashboard_artifact(path),
            target=target,
        )


class RawWizardChartCreateFactory:
    def __init__(self, *, operations: ChartOperations) -> None:
        self._operations = operations

    def __call__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
    ) -> RawWizardChartCreate:
        return RawWizardChartCreate(
            response_snapshot=response_snapshot,
            name=name,
            location=location,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        name: str,
        location: EntryLocation,
    ) -> RawWizardChartCreate:
        return self(
            response_snapshot=read_chart_artifact(path, expected_category="wizard"),
            name=name,
            location=location,
        )


class RawWizardChartReplaceFactory:
    def __init__(self, *, installation: str, operations: ChartOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        target: WizardChart,
        response_snapshot: Mapping[str, JsonValue],
    ) -> RawWizardChartReplace:
        return RawWizardChartReplace(
            target=target,
            response_snapshot=response_snapshot,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        target: WizardChart,
    ) -> RawWizardChartReplace:
        return self(
            response_snapshot=read_chart_artifact(path, expected_category="wizard"),
            target=target,
        )


class RawEditorChartCreateFactory:
    def __init__(self, *, operations: ChartOperations) -> None:
        self._operations = operations

    def __call__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
    ) -> RawEditorChartCreate:
        return RawEditorChartCreate(
            response_snapshot=response_snapshot,
            name=name,
            location=location,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        name: str,
        location: EntryLocation,
    ) -> RawEditorChartCreate:
        return self(
            response_snapshot=read_chart_artifact(path, expected_category="editor"),
            name=name,
            location=location,
        )


class RawEditorChartReplaceFactory:
    def __init__(self, *, installation: str, operations: ChartOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        target: EditorChart,
        response_snapshot: Mapping[str, JsonValue],
    ) -> RawEditorChartReplace:
        return RawEditorChartReplace(
            target=target,
            response_snapshot=response_snapshot,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        target: EditorChart,
    ) -> RawEditorChartReplace:
        return self(
            response_snapshot=read_chart_artifact(path, expected_category="editor"),
            target=target,
        )


class RawQLChartCreateFactory:
    def __init__(self, *, operations: ChartOperations) -> None:
        self._operations = operations

    def __call__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
    ) -> RawQLChartCreate:
        return RawQLChartCreate(
            response_snapshot=response_snapshot,
            name=name,
            location=location,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        name: str,
        location: EntryLocation,
    ) -> RawQLChartCreate:
        return self(
            response_snapshot=read_chart_artifact(path, expected_category="ql"),
            name=name,
            location=location,
        )


class RawQLChartReplaceFactory:
    def __init__(self, *, installation: str, operations: ChartOperations) -> None:
        self._installation = installation
        self._operations = operations

    def __call__(
        self,
        *,
        target: QLChart,
        response_snapshot: Mapping[str, JsonValue],
    ) -> RawQLChartReplace:
        return RawQLChartReplace(
            target=target,
            response_snapshot=response_snapshot,
            installation=self._installation,
            operations=self._operations,
        )

    def from_file(
        self,
        path: ArtifactPath,
        *,
        target: QLChart,
    ) -> RawQLChartReplace:
        return self(
            response_snapshot=read_chart_artifact(path, expected_category="ql"),
            target=target,
        )


class RawCreateNamespace:
    connection: RawConnectionCreateFactory
    dataset: RawDatasetCreateFactory
    dashboard: RawDashboardCreateFactory
    wizard_chart: RawWizardChartCreateFactory
    editor_chart: RawEditorChartCreateFactory
    ql_chart: RawQLChartCreateFactory

    def __init__(
        self,
        *,
        installation: str,
        connection_operations: ConnectionOperations,
        dataset_operations: DatasetOperations,
        dashboard_operations: DashboardOperations,
        chart_operations: ChartOperations,
    ) -> None:
        self.connection = RawConnectionCreateFactory(
            installation=installation,
            operations=connection_operations,
        )
        self.dataset = RawDatasetCreateFactory(
            installation=installation,
            operations=dataset_operations,
        )
        self.dashboard = RawDashboardCreateFactory(
            installation=installation,
            operations=dashboard_operations,
        )
        self.wizard_chart = RawWizardChartCreateFactory(operations=chart_operations)
        self.editor_chart = RawEditorChartCreateFactory(operations=chart_operations)
        self.ql_chart = RawQLChartCreateFactory(operations=chart_operations)


class RawReplaceNamespace:
    connection: RawConnectionReplaceFactory
    dataset: RawDatasetReplaceFactory
    dashboard: RawDashboardReplaceFactory
    wizard_chart: RawWizardChartReplaceFactory
    editor_chart: RawEditorChartReplaceFactory
    ql_chart: RawQLChartReplaceFactory

    def __init__(
        self,
        *,
        installation: str,
        connection_operations: ConnectionOperations,
        dataset_operations: DatasetOperations,
        dashboard_operations: DashboardOperations,
        chart_operations: ChartOperations,
    ) -> None:
        self.connection = RawConnectionReplaceFactory(
            installation=installation,
            operations=connection_operations,
        )
        self.dataset = RawDatasetReplaceFactory(
            installation=installation,
            operations=dataset_operations,
        )
        self.dashboard = RawDashboardReplaceFactory(
            installation=installation,
            operations=dashboard_operations,
        )
        self.wizard_chart = RawWizardChartReplaceFactory(
            installation=installation,
            operations=chart_operations,
        )
        self.editor_chart = RawEditorChartReplaceFactory(
            installation=installation,
            operations=chart_operations,
        )
        self.ql_chart = RawQLChartReplaceFactory(
            installation=installation,
            operations=chart_operations,
        )


class RawNamespace:
    create: RawCreateNamespace
    replace: RawReplaceNamespace

    def __init__(
        self,
        *,
        installation: str,
        connection_operations: ConnectionOperations,
        dataset_operations: DatasetOperations,
        dashboard_operations: DashboardOperations,
        chart_operations: ChartOperations,
    ) -> None:
        self.create = RawCreateNamespace(
            installation=installation,
            connection_operations=connection_operations,
            dataset_operations=dataset_operations,
            dashboard_operations=dashboard_operations,
            chart_operations=chart_operations,
        )
        self.replace = RawReplaceNamespace(
            installation=installation,
            connection_operations=connection_operations,
            dataset_operations=dataset_operations,
            dashboard_operations=dashboard_operations,
            chart_operations=chart_operations,
        )
