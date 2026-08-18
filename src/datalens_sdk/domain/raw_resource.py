from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeVar, get_args

from typing_extensions import Self

from datalens_sdk.domain.chart_types import ChartCategory
from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.ports import ChartOperations, ConnectionOperations, DatasetOperations
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.artifacts import (
    ChartSnapshotView,
    DatasetSnapshotView,
)
from datalens_sdk.serialization.connection import ConnectionOverridesView, ConnectionSnapshotView
from datalens_sdk.serialization.json_types import JsonValue

if TYPE_CHECKING:
    from datalens_sdk.domain.connection import Connection
    from datalens_sdk.domain.dataset import Dataset
    from datalens_sdk.domain.editor_chart import EditorChart
    from datalens_sdk.domain.ql_chart import QLChart
    from datalens_sdk.domain.wizard_chart import WizardChart


def _validate_target_installation(
    *,
    resource: str,
    target_installation: str,
    client_installation: str,
) -> None:
    if target_installation and target_installation != client_installation:
        raise DataLensValidationError(
            f"Cannot replace a {target_installation!r} {resource} through a {client_installation!r} client"
        )


_OperationsT = TypeVar("_OperationsT")


def _require_operations(operations: _OperationsT | None) -> _OperationsT:
    if operations is None:
        raise DataLensConfigurationError("Object is not bound to client operations. Use a client namespace.")
    return operations


class RawConnectionCreate:
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        installation: str,
        overrides: Mapping[str, JsonValue] | None,
        operations: ConnectionOperations | None,
    ) -> None:
        resolved_location = resolve_entry_location(location=location, installation=installation)
        validate_entry_name(name=name, location=resolved_location)
        source = ConnectionSnapshotView.capture(response_snapshot)
        self._spec = RawCreateSpec(
            response_snapshot=source,
            name=name,
            location=resolved_location,
        )
        self._overrides = None if overrides is None else ConnectionOverridesView.capture(overrides)
        self._operations = operations

    def build(self) -> Connection:
        return _require_operations(self._operations).create_connection_from_raw(
            self._spec,
            overrides=self._overrides,
        )


class RawConnectionReplace:
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        target: Connection,
        installation: str,
        overrides: Mapping[str, JsonValue] | None,
        operations: ConnectionOperations | None,
    ) -> None:
        _validate_target_installation(
            resource="connection",
            target_installation=target.installation,
            client_installation=installation,
        )
        if not target.id:
            raise DataLensValidationError("Cannot replace a connection without an id")
        if not target.type:
            raise DataLensValidationError("Cannot replace a connection without a connector type")
        source = ConnectionSnapshotView.capture(response_snapshot)
        if source.connector != target.type:
            raise DataLensValidationError(
                f"Connection connector type mismatch: source is {source.connector!r}, target is {target.type!r}"
            )
        self._spec = RawReplaceSpec(
            response_snapshot=source,
            target_id=target.id,
            target_name=target.name,
            target_location=target.location,
        )
        self._target_connector_type = target.type
        self._overrides = None if overrides is None else ConnectionOverridesView.capture(overrides)
        self._operations = operations

    def execute(self) -> Connection:
        return _require_operations(self._operations).replace_connection_from_raw(
            self._spec,
            target_connector_type=self._target_connector_type,
            overrides=self._overrides,
        )


class RawDatasetCreate:
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        installation: str,
        operations: DatasetOperations | None,
    ) -> None:
        resolved_location = resolve_entry_location(location=location, installation=installation)
        validate_entry_name(name=name, location=resolved_location)
        self._spec = RawCreateSpec(
            response_snapshot=DatasetSnapshotView.capture(response_snapshot),
            name=name,
            location=resolved_location,
        )
        self._operations = operations

    def build(self) -> Dataset:
        return _require_operations(self._operations).create_dataset_from_raw(self._spec)


class RawDatasetReplace:
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        target: Dataset,
        installation: str,
        operations: DatasetOperations | None,
    ) -> None:
        _validate_target_installation(
            resource="dataset",
            target_installation=target.installation,
            client_installation=installation,
        )
        if not target.id:
            raise DataLensValidationError("Cannot replace a dataset without an id")
        self._spec = RawReplaceSpec(
            response_snapshot=DatasetSnapshotView.capture(response_snapshot),
            target_id=target.id,
            target_name=target.name,
            target_location=target.location,
        )
        self._operations = operations

    def execute(self) -> Dataset:
        return _require_operations(self._operations).replace_dataset_from_raw(self._spec)


class _RawChartCreate:
    def __init__(
        self,
        *,
        raw: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        category: ChartCategory,
        operations: ChartOperations | None,
    ) -> None:
        installation = operations.installation if operations is not None else ""
        resolved_location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context=f"{category.capitalize()} chart creation",
        )
        validate_entry_name(name=name, location=resolved_location)
        source = ChartSnapshotView.capture(raw, expected_category=category)
        self._spec = RawCreateSpec(
            response_snapshot=source,
            name=name,
            location=resolved_location,
        )
        self._operations = operations


class RawWizardChartCreate(_RawChartCreate):
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None,
    ) -> None:
        super().__init__(
            raw=response_snapshot,
            name=name,
            location=location,
            category="wizard",
            operations=operations,
        )

    def build(self) -> WizardChart:
        return _require_operations(self._operations).create_wizard_chart_from_raw(self._spec)


class RawEditorChartCreate(_RawChartCreate):
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None,
    ) -> None:
        super().__init__(
            raw=response_snapshot,
            name=name,
            location=location,
            category="editor",
            operations=operations,
        )

    def build(self) -> EditorChart:
        return _require_operations(self._operations).create_editor_chart_from_raw(self._spec)


class RawQLChartCreate(_RawChartCreate):
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        operations: ChartOperations | None,
    ) -> None:
        super().__init__(
            raw=response_snapshot,
            name=name,
            location=location,
            category="ql",
            operations=operations,
        )

    def build(self) -> QLChart:
        return _require_operations(self._operations).create_ql_chart_from_raw(self._spec)


class _RawChartReplace:
    def __init__(
        self,
        *,
        source: ChartSnapshotView,
        target_id: str,
        target_name: str | None,
        target_location: EntryLocation | None,
        target_revision_id: str | None,
        target_category: ChartCategory,
        target_wire_type: str,
        operations: ChartOperations | None,
    ) -> None:
        if not target_id:
            raise DataLensValidationError(f"Cannot replace a {target_category} chart without an id")
        if not target_wire_type:
            raise DataLensValidationError(f"Cannot replace a {target_category} chart without a wire type")
        self._spec = RawReplaceSpec(
            response_snapshot=source,
            target_id=target_id,
            target_name=target_name,
            target_location=target_location,
            target_revision_id=target_revision_id,
        )
        self._target_wire_type = target_wire_type
        self._mode: EntryUpdateMode = "save"
        self._operations = operations

    def mode(self, value: EntryUpdateMode) -> Self:
        if value not in get_args(EntryUpdateMode):
            raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
        self._mode = value
        return self


class RawWizardChartReplace(_RawChartReplace):
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        target: WizardChart,
        installation: str,
        operations: ChartOperations | None,
    ) -> None:
        _init_raw_chart_replace(
            self,
            response_snapshot=response_snapshot,
            target=target,
            installation=installation,
            category="wizard",
            operations=operations,
        )

    def execute(self) -> WizardChart:
        return _require_operations(self._operations).replace_wizard_chart_from_raw(
            self._spec,
            target_wire_type=self._target_wire_type,
            mode=self._mode,
        )


class RawEditorChartReplace(_RawChartReplace):
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        target: EditorChart,
        installation: str,
        operations: ChartOperations | None,
    ) -> None:
        _init_raw_chart_replace(
            self,
            response_snapshot=response_snapshot,
            target=target,
            installation=installation,
            category="editor",
            operations=operations,
        )

    def execute(self) -> EditorChart:
        return _require_operations(self._operations).replace_editor_chart_from_raw(
            self._spec,
            target_wire_type=self._target_wire_type,
            mode=self._mode,
        )


class RawQLChartReplace(_RawChartReplace):
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        target: QLChart,
        installation: str,
        operations: ChartOperations | None,
    ) -> None:
        _init_raw_chart_replace(
            self,
            response_snapshot=response_snapshot,
            target=target,
            installation=installation,
            category="ql",
            operations=operations,
        )

    def execute(self) -> QLChart:
        return _require_operations(self._operations).replace_ql_chart_from_raw(
            self._spec,
            target_wire_type=self._target_wire_type,
            mode=self._mode,
        )


def _init_raw_chart_replace(
    builder: _RawChartReplace,
    *,
    response_snapshot: Mapping[str, JsonValue],
    target: WizardChart | EditorChart | QLChart,
    installation: str,
    category: ChartCategory,
    operations: ChartOperations | None,
) -> None:
    _validate_target_installation(
        resource=f"{category} chart",
        target_installation=target.installation,
        client_installation=installation,
    )
    if target.category != category:
        raise DataLensValidationError(f"Chart category mismatch: expected {category!r}, target is {target.category!r}")
    source = ChartSnapshotView.capture(response_snapshot, expected_category=category)
    if target.wire_type and source.wire_type != target.wire_type:
        raise DataLensValidationError(
            f"{category.capitalize()} chart wire type mismatch: "
            f"source is {source.wire_type!r}, target is {target.wire_type!r}"
        )
    target_revision_id = target.raw.get("revId")
    _RawChartReplace.__init__(
        builder,
        source=source,
        target_id=target.id or "",
        target_name=target.name,
        target_location=target.location,
        target_revision_id=target_revision_id if isinstance(target_revision_id, str) else None,
        target_category=target.category,
        target_wire_type=target.wire_type or "",
        operations=operations,
    )
