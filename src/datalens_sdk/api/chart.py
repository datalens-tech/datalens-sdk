from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import ValidationError

from datalens_sdk._runtime.chart_builder_base import (
    _BaseEditorNodeCreate,
    _BaseQLChartCreate,
    _BaseWizardChartCreate,
)
from datalens_sdk._runtime.chart_constants import is_ql_wire_type
from datalens_sdk.api.entries import EntriesService
from datalens_sdk.converter.editor_chart import (
    EditorChartConverter,
    EditorChartDtoModule,
    editor_wire_types,
)
from datalens_sdk.converter.ql_chart import QLChartConverter, QLChartDtoModule
from datalens_sdk.converter.wizard_chart import WizardChartConverter, WizardChartDtoModule
from datalens_sdk.domain.chart import Chart
from datalens_sdk.domain.editor_chart import EditorChart, EditorChartUpdate
from datalens_sdk.domain.entry_types import EntryBranch, EntryUpdateMode
from datalens_sdk.domain.navigation import (
    EntryRelation,
    GetEntriesOptions,
    Pager,
    RelationOptions,
)
from datalens_sdk.domain.ports import ChartOperations, NavigationOperations
from datalens_sdk.domain.ql_chart import QLChart, QLChartUpdate
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.domain.wizard_chart import WizardChart, WizardChartUpdate
from datalens_sdk.errors import (
    NotSupportedError,
    translate_dto_validation_error,
)
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy
from datalens_sdk.serialization.artifacts import ChartSnapshotView


class ChartAPI:
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

    def create_wizard(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/createWizardChart", payload)

    def get_wizard(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {"chartId": chart_id}
        if workbook_id is not None:
            body["workbookId"] = workbook_id
        if rev_id is not None:
            body["revId"] = rev_id
        elif branch is not None:
            body["branch"] = branch
        return self._post("/rpc/getWizardChart", body, retry_policy=TRANSIENT_RETRY_POLICY)

    def update_wizard(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateWizardChart", payload)

    def delete_wizard(self, chart_id: str) -> None:
        self._post("/rpc/deleteWizardChart", {"chartId": chart_id})

    def create_editor(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/createEditorChart", payload)

    def get_editor(
        self,
        entry_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {"chartId": entry_id}
        if workbook_id is not None:
            body["workbookId"] = workbook_id
        if rev_id is not None:
            body["revId"] = rev_id
        elif branch is not None:
            body["branch"] = branch
        return self._post("/rpc/getEditorChart", body, retry_policy=TRANSIENT_RETRY_POLICY)

    def update_editor(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateEditorChart", payload)

    def delete_editor(self, entry_id: str) -> None:
        self._post("/rpc/deleteEditorChart", {"chartId": entry_id})

    def create_ql(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/createQLChart", payload)

    def get_ql(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {"chartId": chart_id}
        if workbook_id is not None:
            body["workbookId"] = workbook_id
        if rev_id is not None:
            body["revId"] = rev_id
        elif branch is not None:
            body["branch"] = branch
        return self._post("/rpc/getQLChart", body, retry_policy=TRANSIENT_RETRY_POLICY)

    def update_ql(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateQLChart", payload)

    def delete_ql(self, chart_id: str) -> None:
        self._post("/rpc/deleteQLChart", {"chartId": chart_id})


class ChartService(ChartOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: ChartAPI,
        entries_service: EntriesService,
        navigation_operations: NavigationOperations,
        dto_module: WizardChartDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._entries_service = entries_service
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    @property
    def installation(self) -> str:
        return self._installation

    def create_wizard_chart(self, builder: _BaseWizardChartCreate) -> WizardChart:
        spec = builder.to_spec()
        try:
            dto_obj = WizardChartConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createWizardChart", reason=str(exc)) from exc
        response = self._api.create_wizard(dto_obj.to_payload())
        return WizardChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            visualization_id_fallback=spec.viz_id,
            dto_module=self._dto_module,
        )

    def create_wizard_chart_from_raw(self, spec: RawCreateSpec) -> WizardChart:
        source = ChartSnapshotView.from_raw(spec.response_snapshot, expected_category="wizard")
        payload = WizardChartConverter.from_raw_create(spec, source=source).to_payload()
        response = self._api.create_wizard(payload)
        return WizardChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            wire_type_fallback=source.wire_type,
            dto_module=self._dto_module,
        )

    def get_wizard_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> WizardChart:
        response = self._api.get_wizard(chart_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)
        return WizardChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            id_fallback=chart_id,
            dto_module=self._dto_module,
        )

    def update_wizard_chart(self, builder: WizardChartUpdate) -> WizardChart:
        chart_id = builder.chart.id
        if not chart_id:
            raise ValueError("Cannot update chart without an id")
        try:
            dto_obj = WizardChartConverter.from_domain_update(builder, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateWizardChart", reason=str(exc)) from exc
        response = self._api.update_wizard(dto_obj.to_payload())
        return WizardChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=builder.chart.location,
            name=builder.chart.name,
            id_fallback=chart_id,
            dto_module=self._dto_module,
        )

    def replace_wizard_chart_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
    ) -> WizardChart:
        source = ChartSnapshotView.from_raw(spec.response_snapshot, expected_category="wizard")
        payload = WizardChartConverter.from_raw_replace(
            spec,
            target_wire_type=target_wire_type,
            mode=mode,
            source=source,
        ).to_payload()
        response = self._api.update_wizard(payload)
        return WizardChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.target_location,
            name=spec.target_name,
            id_fallback=spec.target_id,
            wire_type_fallback=target_wire_type,
            dto_module=self._dto_module,
        )

    def delete_wizard_chart(self, chart_id: str) -> None:
        self._api.delete_wizard(chart_id)

    def get_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> WizardChart | EditorChart | QLChart:
        entry = next(
            iter(
                self._navigation_operations.get_entries(
                    GetEntriesOptions(ids=(chart_id,), page_size=1),
                )
            ),
            None,
        )
        wire_type = entry.type if entry is not None else None
        if wire_type in editor_wire_types(self._installation, cast(EditorChartDtoModule | None, self._dto_module)):
            return self.get_editor_chart(chart_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)
        if is_ql_wire_type(wire_type):
            return self.get_ql_chart(chart_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)
        return self.get_wizard_chart(chart_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)

    def create_editor_chart(self, builder: _BaseEditorNodeCreate) -> EditorChart:
        spec = builder.to_spec()
        try:
            dto_obj = EditorChartConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createEditorChart", reason=str(exc)) from exc
        response = self._api.create_editor(dto_obj.to_payload())
        return EditorChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            dto_module=self._dto_module,
        )

    def create_editor_chart_from_raw(self, spec: RawCreateSpec) -> EditorChart:
        editor_dto_module = cast(EditorChartDtoModule, self._dto_module)
        source = ChartSnapshotView.from_raw(spec.response_snapshot, expected_category="editor")
        payload = EditorChartConverter.from_raw_create(
            spec,
            installation=self._installation,
            dto_module=editor_dto_module,
            source=source,
        ).to_payload()
        response = self._api.create_editor(payload)
        return EditorChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            wire_type_fallback=source.wire_type,
            dto_module=editor_dto_module,
        )

    def get_editor_chart(
        self,
        entry_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> EditorChart:
        response = self._api.get_editor(entry_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)
        return EditorChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            id_fallback=entry_id,
            dto_module=self._dto_module,
        )

    def update_editor_chart(self, builder: EditorChartUpdate) -> EditorChart:
        entry_id = builder.chart.id
        if not entry_id:
            raise ValueError("Cannot update editor chart without an id")
        try:
            dto_obj = EditorChartConverter.from_domain_update(builder, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateEditorChart", reason=str(exc)) from exc
        response = self._api.update_editor(dto_obj.to_payload())
        return EditorChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=builder.chart.location,
            name=builder.chart.name,
            id_fallback=entry_id,
            dto_module=self._dto_module,
        )

    def replace_editor_chart_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
    ) -> EditorChart:
        editor_dto_module = cast(EditorChartDtoModule, self._dto_module)
        source = ChartSnapshotView.from_raw(spec.response_snapshot, expected_category="editor")
        payload = EditorChartConverter.from_raw_replace(
            spec,
            target_wire_type=target_wire_type,
            mode=mode,
            installation=self._installation,
            dto_module=editor_dto_module,
            source=source,
        ).to_payload()
        response = self._api.update_editor(payload)
        return EditorChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.target_location,
            name=spec.target_name,
            id_fallback=spec.target_id,
            wire_type_fallback=target_wire_type,
            dto_module=editor_dto_module,
        )

    def delete_editor_chart(self, entry_id: str) -> None:
        self._api.delete_editor(entry_id)

    def create_ql_chart(self, builder: _BaseQLChartCreate) -> QLChart:
        spec = builder.to_spec()
        try:
            dto_obj = QLChartConverter.from_domain_create(spec, dto_module=cast(QLChartDtoModule, self._dto_module))
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createQLChart", reason=str(exc)) from exc
        response = self._api.create_ql(dto_obj.to_payload())
        return QLChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            dto_module=cast(QLChartDtoModule, self._dto_module),
        )

    def create_ql_chart_from_raw(self, spec: RawCreateSpec) -> QLChart:
        source = ChartSnapshotView.from_raw(spec.response_snapshot, expected_category="ql")
        payload = QLChartConverter.from_raw_create(spec, source=source).to_payload()
        response = self._api.create_ql(payload)
        return QLChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            wire_type_fallback=source.wire_type,
            dto_module=cast(QLChartDtoModule, self._dto_module),
        )

    def get_ql_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
    ) -> QLChart:
        response = self._api.get_ql(chart_id, workbook_id=workbook_id, branch=branch, rev_id=rev_id)
        return QLChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            id_fallback=chart_id,
            dto_module=cast(QLChartDtoModule, self._dto_module),
        )

    def update_ql_chart(self, builder: QLChartUpdate) -> QLChart:
        chart_id = builder.chart.id
        if not chart_id:
            raise ValueError("Cannot update QL chart without an id")
        try:
            dto_obj = QLChartConverter.from_domain_update(builder, dto_module=cast(QLChartDtoModule, self._dto_module))
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="updateQLChart", reason=str(exc)) from exc
        response = self._api.update_ql(dto_obj.to_payload())
        return QLChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=builder.chart.location,
            name=builder.chart.name,
            id_fallback=chart_id,
            dto_module=cast(QLChartDtoModule, self._dto_module),
        )

    def replace_ql_chart_from_raw(
        self,
        spec: RawReplaceSpec,
        *,
        target_wire_type: str,
        mode: EntryUpdateMode,
    ) -> QLChart:
        source = ChartSnapshotView.from_raw(spec.response_snapshot, expected_category="ql")
        payload = QLChartConverter.from_raw_replace(
            spec,
            target_wire_type=target_wire_type,
            mode=mode,
            source=source,
        ).to_payload()
        response = self._api.update_ql(payload)
        return QLChartConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.target_location,
            name=spec.target_name,
            id_fallback=spec.target_id,
            wire_type_fallback=target_wire_type,
            dto_module=cast(QLChartDtoModule, self._dto_module),
        )

    def delete_ql_chart(self, chart_id: str) -> None:
        self._api.delete_ql(chart_id)

    def rename_chart(self, chart: Chart, name: str) -> Chart:
        if not chart.id:
            raise ValueError("Cannot rename a chart without an id")
        get_chart: Callable[[str, str | None], Chart]
        if isinstance(chart, EditorChart):
            get_chart = self.get_editor_chart
        elif isinstance(chart, QLChart):
            get_chart = self.get_ql_chart
        elif isinstance(chart, WizardChart):
            get_chart = self.get_wizard_chart
        else:
            raise NotSupportedError(f"Cannot rename unsupported chart type {type(chart).__name__!r}")
        self._entries_service.rename_entry(entry_id=chart.id, name=name)
        return get_chart(chart.id, chart.workbook_id)

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]:
        return self._navigation_operations.get_entry_relations(entry_id, options)
