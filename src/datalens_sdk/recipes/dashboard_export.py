from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from itertools import chain
import os
from pathlib import Path
from typing import NoReturn

from datalens_sdk._runtime.chart_constants import classify_chart_wire_type
from datalens_sdk.domain.chart import Chart
from datalens_sdk.domain.chart_types import ChartCategory
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.navigation import EntryRelation, EntryScope, RelationOptions
from datalens_sdk.domain.ports import ChartOperations, DatasetOperations, NavigationOperations
from datalens_sdk.errors import DatalensValidationError, translate_invalid_response_error
from datalens_sdk.serialization.artifacts import (
    DASHBOARD_FILENAME,
    ArtifactPath,
    ChartSnapshotView,
    artifact_directory_path,
    require_complete_dashboard_snapshot,
    require_complete_dataset_snapshot,
)
from datalens_sdk.serialization.json_io import write_artifact_directory


@dataclass(frozen=True, slots=True)
class DependencyRef:
    id: str
    type: str
    workbook_id: str | None


def _invalid_relations(reason: str) -> NoReturn:
    raise translate_invalid_response_error(operation="getEntriesRelations", reason=reason)


def _coalesce_dependency_refs(
    relations: Iterable[EntryRelation],
    *,
    scope: EntryScope,
    allow_blank_type: bool = False,
) -> tuple[DependencyRef, ...]:
    scoped = tuple(relation for relation in tuple(relations) if relation.scope == scope)
    if any(not relation.id.strip() for relation in scoped):
        _invalid_relations(f"{scope!r} relation has a blank id")
    blank_type_ids = sorted({relation.id for relation in scoped if not relation.type.strip()})
    if blank_type_ids and not allow_blank_type:
        _invalid_relations(f"relations for {blank_type_ids!r} have a blank type")
    blank_workbook_ids = sorted(
        {relation.id for relation in scoped if relation.workbook_id is not None and not relation.workbook_id.strip()}
    )
    if blank_workbook_ids:
        _invalid_relations(f"relations for {blank_workbook_ids!r} have a blank workbookId")

    grouped: dict[str, list[EntryRelation]] = {}
    for relation in scoped:
        grouped.setdefault(relation.id, []).append(relation)

    refs: list[DependencyRef] = []
    for relation_id in sorted(grouped):
        group = grouped[relation_id]
        wire_types = {relation.type for relation in group}
        if len(wire_types) != 1:
            _invalid_relations(f"relations for {relation_id!r} have conflicting types: {sorted(wire_types)!r}")
        workbook_ids = {relation.workbook_id for relation in group if relation.workbook_id is not None}
        if len(workbook_ids) > 1:
            _invalid_relations(f"relations for {relation_id!r} have conflicting workbookIds: {sorted(workbook_ids)!r}")
        refs.append(
            DependencyRef(
                id=relation_id,
                type=next(iter(wire_types)),
                workbook_id=next(iter(workbook_ids), None),
            )
        )
    return tuple(refs)


class DashboardBundleExporter:
    def __init__(
        self,
        *,
        navigation_operations: NavigationOperations,
        chart_operations: ChartOperations,
        dataset_operations: DatasetOperations,
        editor_wire_types: AbstractSet[str],
    ) -> None:
        self._navigation_operations = navigation_operations
        self._chart_operations = chart_operations
        self._dataset_operations = dataset_operations
        self._editor_wire_types = frozenset(editor_wire_types)

    def export(self, dashboard: Dashboard, path: ArtifactPath) -> Path:
        if not dashboard.id:
            raise DatalensValidationError("Cannot export dashboard dependencies without a dashboard id")
        try:
            snapshot = require_complete_dashboard_snapshot(dashboard.response_snapshot)
        except DatalensValidationError as exc:
            raise translate_invalid_response_error(operation="getDashboard", reason=str(exc)) from exc
        target = artifact_directory_path(
            path,
            name=dashboard.name,
            resource_id=dashboard.id,
            resource="Dashboard",
        )
        if os.path.lexists(target):
            raise DatalensValidationError(f"Artifact path already exists: {target}")

        chart_refs = self._relations(dashboard.id, scope="widget")
        classified_chart_refs = tuple(
            (
                ref,
                classify_chart_wire_type(
                    ref.type,
                    editor_wire_types=self._editor_wire_types,
                ),
            )
            for ref in chart_refs
        )

        dataset_relations = chain(
            self._navigation_operations.get_entry_relations(
                dashboard.id,
                RelationOptions(link_direction="from", scope="dataset"),
            ),
            *(
                self._navigation_operations.get_entry_relations(
                    chart_ref.id,
                    RelationOptions(link_direction="from", scope="dataset"),
                )
                for chart_ref, _ in classified_chart_refs
            ),
        )
        # YaTeam dataset relations use scope as the discriminator and return
        # type=""; unlike chart refs, dataset type is not used for RPC dispatch.
        dataset_refs = _coalesce_dependency_refs(
            dataset_relations,
            scope="dataset",
            allow_blank_type=True,
        )

        charts = tuple(self._load_chart(chart_ref, category) for chart_ref, category in classified_chart_refs)
        datasets = tuple(self._load_dataset(dataset_ref) for dataset_ref in dataset_refs)

        def populate(staging: Path) -> None:
            charts_path = staging / "charts"
            datasets_path = staging / "datasets"
            charts_path.mkdir(mode=0o700)
            datasets_path.mkdir(mode=0o700)
            for chart in charts:
                chart.to_file(charts_path)
            for dataset in datasets:
                dataset.to_file(datasets_path)

        return write_artifact_directory(
            target,
            filename=DASHBOARD_FILENAME,
            value=snapshot,
            populate=populate,
        )

    def _relations(self, entry_id: str, *, scope: EntryScope) -> tuple[DependencyRef, ...]:
        relations = self._navigation_operations.get_entry_relations(
            entry_id,
            RelationOptions(link_direction="from", scope=scope),
        )
        return _coalesce_dependency_refs(relations, scope=scope)

    def _load_chart(self, ref: DependencyRef, category: ChartCategory) -> Chart:
        chart: Chart
        if category == "wizard":
            operation = "getWizardChart"
            chart = self._chart_operations.get_wizard_chart(ref.id, workbook_id=ref.workbook_id)
        elif category == "editor":
            operation = "getEditorChart"
            chart = self._chart_operations.get_editor_chart(ref.id, workbook_id=ref.workbook_id)
        else:
            operation = "getQLChart"
            chart = self._chart_operations.get_ql_chart(ref.id, workbook_id=ref.workbook_id)
        if chart.id != ref.id:
            raise translate_invalid_response_error(
                operation=operation,
                reason=f"returned chart id {chart.id!r}, expected {ref.id!r}",
            )
        if chart.category != category:
            raise translate_invalid_response_error(
                operation=operation,
                reason=f"returned chart category {chart.category!r}, expected {category!r}",
            )
        try:
            ChartSnapshotView.from_raw(chart.response_snapshot, expected_category=category)
        except DatalensValidationError as exc:
            raise translate_invalid_response_error(operation=operation, reason=str(exc)) from exc
        return chart

    def _load_dataset(self, ref: DependencyRef) -> Dataset:
        dataset = self._dataset_operations.get_dataset(ref.id, workbook_id=ref.workbook_id)
        if dataset.id != ref.id:
            raise translate_invalid_response_error(
                operation="getDataset",
                reason=f"returned dataset id {dataset.id!r}, expected {ref.id!r}",
            )
        try:
            require_complete_dataset_snapshot(dataset.response_snapshot)
        except DatalensValidationError as exc:
            raise translate_invalid_response_error(operation="getDataset", reason=str(exc)) from exc
        return dataset
