from __future__ import annotations

from collections.abc import Iterator, Mapping
from itertools import chain
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.navigation import EntryRelation, Page, Pager, RelationOptions
from datalens_sdk.domain.ql_chart import QLChart
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import (
    DatalensConfigurationError,
    DatalensValidationError,
    InvalidResponseError,
    NotSupportedError,
)
from datalens_sdk.recipes.dashboard_export import (
    DashboardBundleExporter,
    DependencyRef,
    _coalesce_dependency_refs,
)
from datalens_sdk.serialization.json_types import JsonValue


def _dashboard_snapshot() -> dict[str, JsonValue]:
    return {
        "entry": {
            "entryId": "dashboard-1",
            "key": "/Dash",
            "data": {
                "tabs": [
                    {
                        "items": [
                            {
                                "type": "widget",
                                "data": {
                                    "tabs": [{"chartId": "json-only-chart"}],
                                    "datasetsIds": ["json-only-dataset"],
                                },
                            }
                        ]
                    }
                ]
            },
            "meta": None,
        }
    }


def _wizard_snapshot(chart_id: str) -> dict[str, JsonValue]:
    return {
        "entryId": chart_id,
        "type": "d3_wizard_node",
        "key": f"/{chart_id}",
        "data": {"datasetsIds": ["json-only-dataset"]},
    }


def _editor_snapshot(chart_id: str) -> dict[str, JsonValue]:
    return {
        "entry": {
            "entryId": chart_id,
            "type": "advanced-chart_node",
            "data": {"sources": [{"datasetId": "json-only-dataset"}]},
        }
    }


def _ql_snapshot(chart_id: str) -> dict[str, JsonValue]:
    return {
        "entryId": chart_id,
        "type": "d3_ql_node",
        "key": f"/{chart_id}",
        "data": {"queryValue": "select 1"},
    }


def _dataset_snapshot(dataset_id: str) -> dict[str, JsonValue]:
    return {
        "id": dataset_id,
        "dataset": {"description": dataset_id},
    }


def _relation(
    relation_id: str,
    *,
    scope: str,
    wire_type: str,
    workbook_id: str | None = None,
) -> EntryRelation:
    return EntryRelation(
        id=relation_id,
        scope=cast("object", scope),  # type: ignore[arg-type]
        type=wire_type,
        workbook_id=workbook_id,
    )


def _pager(*pages: tuple[EntryRelation, ...]) -> Pager[EntryRelation]:
    def load() -> Iterator[Page[EntryRelation]]:
        for index, entries in enumerate(pages):
            yield Page(
                items=entries,
                next_page_token=str(index + 1) if index + 1 < len(pages) else None,
            )

    return Pager(load)


class FakeNavigationOperations:
    def __init__(
        self,
        pages: Mapping[tuple[str, str], tuple[tuple[EntryRelation, ...], ...]],
    ) -> None:
        self._pages = pages
        self.calls: list[tuple[str, RelationOptions]] = []

    def get_entry_relations(
        self,
        entry_id: str,
        options: RelationOptions,
    ) -> Pager[EntryRelation]:
        self.calls.append((entry_id, options))
        return _pager(*self._pages.get((entry_id, cast(str, options.scope)), ((),)))


ChartResource = WizardChart | EditorChart | QLChart


class FakeChartOperations:
    def __init__(self, charts: Mapping[str, ChartResource]) -> None:
        self._charts = charts
        self.get_calls: list[tuple[str, str, str | None]] = []

    def get_wizard_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: str | None = None,
        rev_id: str | None = None,
    ) -> ChartResource:
        assert branch is None
        assert rev_id is None
        self.get_calls.append(("wizard", chart_id, workbook_id))
        return self._charts[chart_id]

    def get_editor_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: str | None = None,
        rev_id: str | None = None,
    ) -> ChartResource:
        assert branch is None
        assert rev_id is None
        self.get_calls.append(("editor", chart_id, workbook_id))
        return self._charts[chart_id]

    def get_ql_chart(
        self,
        chart_id: str,
        workbook_id: str | None = None,
        branch: str | None = None,
        rev_id: str | None = None,
    ) -> ChartResource:
        assert branch is None
        assert rev_id is None
        self.get_calls.append(("ql", chart_id, workbook_id))
        return self._charts[chart_id]


class FakeDatasetOperations:
    def __init__(self, datasets: Mapping[str, Dataset]) -> None:
        self._datasets = datasets
        self.get_calls: list[tuple[str, str | None]] = []

    def get_dataset(
        self,
        dataset_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Dataset:
        assert rev_id is None
        self.get_calls.append((dataset_id, workbook_id))
        return self._datasets[dataset_id]


def _resources() -> tuple[dict[str, ChartResource], dict[str, Dataset]]:
    return (
        {
            "chart-a": WizardChart(
                id="chart-a",
                name="Chart A",
                wire_type="d3_wizard_node",
                response_snapshot=_wizard_snapshot("chart-a"),
            ),
            "chart-b": EditorChart(
                id="chart-b",
                name="Chart B",
                wire_type="advanced-chart_node",
                response_snapshot=_editor_snapshot("chart-b"),
            ),
            "chart-c": QLChart(
                id="chart-c",
                name="Chart C",
                wire_type="d3_ql_node",
                response_snapshot=_ql_snapshot("chart-c"),
            ),
        },
        {
            dataset_id: Dataset(
                id=dataset_id,
                name=f"Dataset {dataset_id.removeprefix('dataset-').upper()}",
                response_snapshot=_dataset_snapshot(dataset_id),
            )
            for dataset_id in ("dataset-a", "dataset-b", "dataset-c")
        },
    )


def _exporter(
    pages: Mapping[tuple[str, str], tuple[tuple[EntryRelation, ...], ...]],
    *,
    charts: Mapping[str, ChartResource] | None = None,
    datasets: Mapping[str, Dataset] | None = None,
) -> tuple[DashboardBundleExporter, FakeNavigationOperations, FakeChartOperations, FakeDatasetOperations]:
    default_charts, default_datasets = _resources()
    navigation = FakeNavigationOperations(pages)
    chart_operations = FakeChartOperations(default_charts if charts is None else charts)
    dataset_operations = FakeDatasetOperations(default_datasets if datasets is None else datasets)
    return (
        DashboardBundleExporter(
            navigation_operations=cast("object", navigation),  # type: ignore[arg-type]
            chart_operations=cast("object", chart_operations),  # type: ignore[arg-type]
            dataset_operations=cast("object", dataset_operations),  # type: ignore[arg-type]
            editor_wire_types=frozenset({"advanced-chart_node"}),
        ),
        navigation,
        chart_operations,
        dataset_operations,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_dependency_ref_coalescer_is_order_independent_and_filters_scope(reverse: bool) -> None:
    first = (
        _relation("dataset-b", scope="dataset", wire_type="dataset", workbook_id=None),
        _relation("ignored", scope="widget", wire_type="dataset"),
    )
    second = (
        _relation("dataset-a", scope="dataset", wire_type="dataset"),
        _relation("dataset-b", scope="dataset", wire_type="dataset", workbook_id="wb-1"),
    )
    pagers: tuple[Pager[EntryRelation], ...] = (_pager(first), _pager(second))
    if reverse:
        pagers = tuple(reversed(pagers))

    refs = _coalesce_dependency_refs(chain.from_iterable(pagers), scope="dataset")

    assert refs == (
        DependencyRef(id="dataset-a", type="dataset", workbook_id=None),
        DependencyRef(id="dataset-b", type="dataset", workbook_id="wb-1"),
    )


def test_dependency_ref_coalescer_accepts_live_dataset_relations_with_blank_type() -> None:
    refs = _coalesce_dependency_refs(
        (
            _relation("dataset-a", scope="dataset", wire_type="", workbook_id=None),
            _relation("dataset-a", scope="dataset", wire_type="", workbook_id="wb-1"),
        ),
        scope="dataset",
        allow_blank_type=True,
    )

    assert refs == (DependencyRef(id="dataset-a", type="", workbook_id="wb-1"),)


@pytest.mark.parametrize(
    ("relations", "message"),
    [
        (
            (
                _relation("chart", scope="widget", wire_type="first"),
                _relation("chart", scope="widget", wire_type="second"),
            ),
            "conflicting types",
        ),
        (
            (
                _relation("chart", scope="widget", wire_type="type", workbook_id="wb-1"),
                _relation("chart", scope="widget", wire_type="type", workbook_id="wb-2"),
            ),
            "conflicting workbookIds",
        ),
        ((_relation("", scope="widget", wire_type="type"),), "blank id"),
        ((_relation("chart", scope="widget", wire_type=" "),), "blank type"),
        ((_relation("chart", scope="widget", wire_type="type", workbook_id=" "),), "blank workbookId"),
    ],
)
def test_dependency_ref_coalescer_rejects_inconsistent_server_relations(
    relations: tuple[EntryRelation, ...],
    message: str,
) -> None:
    with pytest.raises(InvalidResponseError, match=message):
        _coalesce_dependency_refs(relations, scope="widget")


def test_dependency_export_coalesces_all_relations_and_uses_specialized_getters(tmp_path: Path) -> None:
    exporter, navigation, charts, datasets = _exporter(
        {
            ("dashboard-1", "widget"): (
                (_relation("chart-b", scope="widget", wire_type="advanced-chart_node", workbook_id="wb-b"),),
                (
                    _relation("chart-c", scope="widget", wire_type="d3_ql_node"),
                    _relation("chart-a", scope="widget", wire_type="metric_wizard_node"),
                    _relation(
                        "chart-a",
                        scope="widget",
                        wire_type="metric_wizard_node",
                        workbook_id="wb-a",
                    ),
                ),
            ),
            ("dashboard-1", "dataset"): (
                (
                    _relation("dataset-b", scope="dataset", wire_type="dataset", workbook_id="wb-b"),
                    _relation("wrong-direct-scope", scope="widget", wire_type="dataset"),
                ),
            ),
            ("chart-a", "dataset"): (
                (_relation("dataset-a", scope="dataset", wire_type="dataset"),),
                (_relation("dataset-b", scope="dataset", wire_type="dataset"),),
            ),
            ("chart-b", "dataset"): (
                (
                    _relation("dataset-c", scope="dataset", wire_type="dataset", workbook_id="wb-c"),
                    _relation("wrong-chart-scope", scope="widget", wire_type="dataset"),
                ),
            ),
            ("chart-c", "dataset"): ((),),
        }
    )
    dashboard = Dashboard(
        id="dashboard-1",
        name="Dash",
        response_snapshot=_dashboard_snapshot(),
    )
    original_names = (dashboard.name, *(chart.name for chart in charts._charts.values()))

    artifact = exporter.export(dashboard, tmp_path)

    assert artifact == tmp_path / "Dash [dashboard-1]"
    assert charts.get_calls == [
        ("wizard", "chart-a", "wb-a"),
        ("editor", "chart-b", "wb-b"),
        ("ql", "chart-c", None),
    ]
    assert datasets.get_calls == [
        ("dataset-a", None),
        ("dataset-b", "wb-b"),
        ("dataset-c", "wb-c"),
    ]
    assert navigation.calls == [
        ("dashboard-1", RelationOptions(link_direction="from", scope="widget")),
        ("dashboard-1", RelationOptions(link_direction="from", scope="dataset")),
        ("chart-a", RelationOptions(link_direction="from", scope="dataset")),
        ("chart-b", RelationOptions(link_direction="from", scope="dataset")),
        ("chart-c", RelationOptions(link_direction="from", scope="dataset")),
    ]
    assert sorted(path.relative_to(artifact).as_posix() for path in artifact.rglob("*.json")) == [
        "charts/Chart A [chart-a]/chart.json",
        "charts/Chart B [chart-b]/chart.json",
        "charts/Chart C [chart-c]/chart.json",
        "dashboard.json",
        "datasets/Dataset A [dataset-a]/dataset.json",
        "datasets/Dataset B [dataset-b]/dataset.json",
        "datasets/Dataset C [dataset-c]/dataset.json",
    ]
    assert (dashboard.name, *(chart.name for chart in charts._charts.values())) == original_names
    assert not (artifact / "charts" / "Chart B [chart-b]" / "Tabs").exists()


def test_dependency_export_does_not_discover_ids_from_resource_json(tmp_path: Path) -> None:
    exporter, navigation, charts, datasets = _exporter(
        {
            ("dashboard-1", "widget"): ((),),
            ("dashboard-1", "dataset"): ((),),
        }
    )
    dashboard = Dashboard(
        id="dashboard-1",
        name="Dash",
        response_snapshot=_dashboard_snapshot(),
    )

    exporter.export(dashboard, tmp_path)

    assert charts.get_calls == []
    assert datasets.get_calls == []
    assert [call[0] for call in navigation.calls] == ["dashboard-1", "dashboard-1"]


def test_unknown_chart_type_fails_before_chart_relations_or_resource_getters(tmp_path: Path) -> None:
    exporter, navigation, charts, datasets = _exporter(
        {
            ("dashboard-1", "widget"): ((_relation("chart-a", scope="widget", wire_type="mystery_node"),),),
        }
    )
    dashboard = Dashboard(id="dashboard-1", name="Dash", response_snapshot=_dashboard_snapshot())

    with pytest.raises(NotSupportedError, match="mystery_node"):
        exporter.export(dashboard, tmp_path)

    assert navigation.calls == [
        ("dashboard-1", RelationOptions(link_direction="from", scope="widget")),
    ]
    assert charts.get_calls == []
    assert datasets.get_calls == []
    assert not (tmp_path / "Dash [dashboard-1]").exists()


@pytest.mark.parametrize(
    ("chart", "message"),
    [
        (
            WizardChart(
                id="wrong-id",
                wire_type="d3_wizard_node",
                response_snapshot=_wizard_snapshot("wrong-id"),
            ),
            "returned chart id",
        ),
        (
            EditorChart(
                id="chart-a",
                wire_type="advanced-chart_node",
                response_snapshot=_editor_snapshot("chart-a"),
            ),
            "returned chart category",
        ),
        (
            WizardChart(
                id="chart-a",
                wire_type="d3_wizard_node",
                response_snapshot={"entryId": "chart-a", "type": "d3_wizard_node"},
            ),
            "complete 'data' content",
        ),
    ],
)
def test_invalid_chart_dependency_is_translated_to_resource_invalid_response(
    tmp_path: Path,
    chart: ChartResource,
    message: str,
) -> None:
    exporter, _, _, _ = _exporter(
        {
            ("dashboard-1", "widget"): ((_relation("chart-a", scope="widget", wire_type="d3_wizard_node"),),),
            ("dashboard-1", "dataset"): ((),),
            ("chart-a", "dataset"): ((),),
        },
        charts={"chart-a": chart},
    )
    dashboard = Dashboard(id="dashboard-1", name="Dash", response_snapshot=_dashboard_snapshot())

    with pytest.raises(InvalidResponseError, match=rf"getWizardChart.*{message}"):
        exporter.export(dashboard, tmp_path)

    assert not (tmp_path / "Dash [dashboard-1]").exists()
    assert list(tmp_path.glob(".*.staging-*")) == []


@pytest.mark.parametrize(
    ("dataset", "message"),
    [
        (Dataset(id="wrong-id", response_snapshot=_dataset_snapshot("wrong-id")), "returned dataset id"),
        (Dataset(id="dataset-a", response_snapshot={"id": "dataset-a"}), "complete 'dataset' content"),
    ],
)
def test_invalid_dataset_dependency_is_translated_to_resource_invalid_response(
    tmp_path: Path,
    dataset: Dataset,
    message: str,
) -> None:
    exporter, _, _, _ = _exporter(
        {
            ("dashboard-1", "widget"): ((),),
            ("dashboard-1", "dataset"): ((_relation("dataset-a", scope="dataset", wire_type="dataset"),),),
        },
        datasets={"dataset-a": dataset},
    )
    dashboard = Dashboard(id="dashboard-1", name="Dash", response_snapshot=_dashboard_snapshot())

    with pytest.raises(InvalidResponseError, match=rf"getDataset.*{message}"):
        exporter.export(dashboard, tmp_path)

    assert not (tmp_path / "Dash [dashboard-1]").exists()


def test_incomplete_dashboard_snapshot_is_invalid_response_before_relations(tmp_path: Path) -> None:
    exporter, navigation, _, _ = _exporter({})
    dashboard = Dashboard(
        id="dashboard-1",
        name="Dash",
        response_snapshot={"entry": {"entryId": "dashboard-1"}},
    )

    with pytest.raises(InvalidResponseError, match=r"getDashboard.*complete 'data' content"):
        exporter.export(dashboard, tmp_path)

    assert navigation.calls == []


def test_populate_failure_removes_staging_and_never_exposes_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter, _, _, _ = _exporter(
        {
            ("dashboard-1", "widget"): ((_relation("chart-a", scope="widget", wire_type="d3_wizard_node"),),),
            ("dashboard-1", "dataset"): ((),),
            ("chart-a", "dataset"): ((),),
        }
    )
    dashboard = Dashboard(id="dashboard-1", name="Dash", response_snapshot=_dashboard_snapshot())

    def fail_to_write(self: WizardChart, path: object) -> Path:
        del self, path
        raise RuntimeError("disk failed")

    monkeypatch.setattr(WizardChart, "to_file", fail_to_write)

    with pytest.raises(RuntimeError, match="disk failed"):
        exporter.export(dashboard, tmp_path)

    assert not (tmp_path / "Dash [dashboard-1]").exists()
    assert list(tmp_path.glob(".*.staging-*")) == []


@pytest.mark.parametrize("dangling_symlink", [False, True])
def test_existing_target_is_rejected_before_relations_and_is_untouched(
    tmp_path: Path,
    dangling_symlink: bool,
) -> None:
    exporter, navigation, _, _ = _exporter({})
    target = tmp_path / "Dash [dashboard-1]"
    if dangling_symlink:
        try:
            target.symlink_to(tmp_path / "missing", target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"Directory symlinks are not available: {exc}")
    else:
        target.mkdir()
        (target / "marker").write_text("foreign", encoding="utf-8")
    dashboard = Dashboard(id="dashboard-1", name="Dash", response_snapshot=_dashboard_snapshot())

    with pytest.raises(DatalensValidationError, match="already exists"):
        exporter.export(dashboard, tmp_path)

    assert navigation.calls == []
    if dangling_symlink:
        assert target.is_symlink()
    else:
        assert (target / "marker").read_text(encoding="utf-8") == "foreign"


def test_unbound_dashboard_allows_single_export_and_rejects_dependency_export(tmp_path: Path) -> None:
    dashboard = Dashboard(
        id="dashboard-1",
        name="Dash",
        response_snapshot=_dashboard_snapshot(),
    )

    artifact = dashboard.to_file(tmp_path)
    assert artifact.is_dir()

    other_parent = tmp_path / "other"
    other_parent.mkdir()
    with pytest.raises(DatalensConfigurationError):
        dashboard.to_file(other_parent, with_dependencies=True)
