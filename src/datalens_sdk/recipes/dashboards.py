"""Cross-entity dashboard recipes (epic D4.6).

Recipes are HTTP-touching helpers over the client's typed port accessors
(:class:`DashboardRecipeClient`) — pure-domain introspection stays on the
read model. The first recipe, :func:`validate_dashboard_refs`, collects every
broken reference of a dashboard without raising: the server accepts unknown
chart/dataset/field ids silently (a selector with a bogus datasetFieldId
renders as an error state and never filters — probe P016).
"""

from __future__ import annotations

import difflib
from typing import Protocol, runtime_checkable

from datalens_sdk.converter.dashboard_control import _tab_used_fields
from datalens_sdk.domain.dashboard import ControlMemberView, Dashboard
from datalens_sdk.domain.dashboard_types import ValidationIssue, ValidationIssueKind
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.ports import ChartOperations, DashboardOperations, DatasetOperations
from datalens_sdk.domain.ql_chart import QLChart
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import ForbiddenError, NotFoundError

__all__ = ["DashboardRecipeClient", "ValidationIssue", "validate_dashboard_refs"]


@runtime_checkable
class DashboardRecipeClient(Protocol):
    """The client seam recipes depend on: typed operation ports only."""

    @property
    def dashboard_ops(self) -> DashboardOperations: ...

    @property
    def chart_ops(self) -> ChartOperations: ...

    @property
    def dataset_ops(self) -> DatasetOperations: ...


_MISSING = "missing"
_FORBIDDEN = "forbidden"


class _EntityCache:
    """Memoized fetches classifying NotFound/Forbidden; other errors propagate."""

    def __init__(self, client: DashboardRecipeClient) -> None:
        self._client = client
        self._charts: dict[str, object] = {}
        self._datasets: dict[str, object] = {}

    def chart(self, chart_id: str) -> object:
        if chart_id not in self._charts:
            try:
                self._charts[chart_id] = self._client.chart_ops.get_chart(chart_id)
            except NotFoundError:
                self._charts[chart_id] = _MISSING
            except ForbiddenError:
                self._charts[chart_id] = _FORBIDDEN
        return self._charts[chart_id]

    def dataset(self, dataset_id: str) -> object:
        if dataset_id not in self._datasets:
            try:
                self._datasets[dataset_id] = self._client.dataset_ops.get_dataset(dataset_id)
            except NotFoundError:
                self._datasets[dataset_id] = _MISSING
            except ForbiddenError:
                self._datasets[dataset_id] = _FORBIDDEN
        return self._datasets[dataset_id]


def _entity_issue(
    entity: object,
    *,
    kind_missing: ValidationIssueKind,
    tab_id: str | None,
    item_id: str | None,
    message_missing: str,
    message_forbidden: str,
) -> ValidationIssue | None:
    if entity is _MISSING:
        return ValidationIssue(kind=kind_missing, tab_id=tab_id, item_id=item_id, message=message_missing)
    if entity is _FORBIDDEN:
        return ValidationIssue(kind="access_denied", tab_id=tab_id, item_id=item_id, message=message_forbidden)
    return None


def _chart_dataset_ids(chart: object) -> tuple[str, ...]:
    """Dataset ids statically derivable from a chart.

    Wizard V1 charts expose ids from ``data.sources.datasetsIds`` through
    :attr:`WizardChart.dataset_ids`. Editor charts source data from code and
    QL charts have no datasets.
    """
    if isinstance(chart, WizardChart):
        return chart.dataset_ids
    return ()


def _parameter_titles(dataset: object) -> tuple[str, ...]:
    if not isinstance(dataset, Dataset):
        return ()
    return tuple(title for field in dataset.parameters if (title := field.title))


def validate_dashboard_refs(client: DashboardRecipeClient, dashboard: Dashboard) -> tuple[ValidationIssue, ...]:
    """Collect every broken reference of the dashboard (never raises).

    Checks: widget chart ids and external selector chart ids exist; dataset
    selector ``datasetId``/``datasetFieldId`` exist (all group members,
    globalItems included); wizard-chart dataset references resolve; manual
    selectors bind to a dataset parameter by name (with did-you-mean
    suggestions over reachable datasets); alias fields neither any item
    references as a parameter nor any tab dataset carries (dangling,
    including pre-existing ones — skipped on tabs with editor charts or
    external selectors, whose fields cannot be enumerated). Missing entities
    and access-denied ones are distinguished (``missing_*`` vs
    ``access_denied``); network/server errors propagate.
    """
    cache = _EntityCache(client)
    issues: list[ValidationIssue] = []

    # reachable datasets: selector-bound ones plus wizard-chart ones
    reachable_dataset_ids: list[str] = []

    def _note_dataset(dataset_id: str) -> None:
        if dataset_id not in reachable_dataset_ids:
            reachable_dataset_ids.append(dataset_id)

    def _check_chart(
        tab_id: str | None,
        item_id: str | None,
        chart_id: str,
        *,
        context: str,
        tab_dataset_ids: list[str],
    ) -> bool:
        """Validate the chart reference; ``False`` when the chart's parameter
        surface cannot be enumerated statically (missing/forbidden/editor)."""
        chart = cache.chart(chart_id)
        issue = _entity_issue(
            chart,
            kind_missing="missing_chart",
            tab_id=tab_id,
            item_id=item_id,
            message_missing=f"{context}: chart {chart_id!r} does not exist",
            message_forbidden=f"{context}: no access to chart {chart_id!r}",
        )
        if issue is not None:
            issues.append(issue)
            return False
        if isinstance(chart, WizardChart):
            # datasets the chart references are dashboard references too: a
            # wizard chart pointing at a deleted dataset is a broken ref of
            # THIS widget
            for dataset_id in _chart_dataset_ids(chart):
                _note_dataset(dataset_id)
                tab_dataset_ids.append(dataset_id)
                dataset_issue = _entity_issue(
                    cache.dataset(dataset_id),
                    kind_missing="missing_dataset",
                    tab_id=tab_id,
                    item_id=item_id,
                    message_missing=(
                        f"{context}: chart {chart_id!r} references dataset {dataset_id!r} which does not exist"
                    ),
                    message_forbidden=f"{context}: chart {chart_id!r} references dataset {dataset_id!r} without access",
                )
                if dataset_issue is not None:
                    issues.append(dataset_issue)
            return True
        # QL charts carry no datasets; editor charts (and unknown kinds)
        # source data from code — their fields are not enumerable
        return isinstance(chart, QLChart)

    manual_members: list[tuple[str | None, ControlMemberView]] = []

    for tab in dashboard.tabs:
        tab_dataset_ids: list[str] = []
        tab_sources_unknown = False
        for item in (*tab.items, *tab.global_items):
            if item.item_type == "widget":
                widget_tabs = item.data.get("tabs")
                for widget_tab in widget_tabs if isinstance(widget_tabs, list) else ():
                    if isinstance(widget_tab, dict):
                        chart_id = widget_tab.get("chartId")
                        if isinstance(chart_id, str) and chart_id:
                            enumerable = _check_chart(
                                tab.id,
                                item.id,
                                chart_id,
                                context=f"widget {item.id!r}",
                                tab_dataset_ids=tab_dataset_ids,
                            )
                            tab_sources_unknown = tab_sources_unknown or not enumerable
        for control in tab.controls:
            for member in control.members:
                source = member.source
                if member.source_type == "external":
                    if source.chart_id:
                        _check_chart(
                            tab.id,
                            member.id,
                            source.chart_id,
                            context=f"external selector {member.id!r}",
                            tab_dataset_ids=tab_dataset_ids,
                        )
                    # an external selector emits parameters its editor chart
                    # defines — not statically enumerable
                    tab_sources_unknown = True
                    continue
                if member.source_type == "dataset" and source.dataset_id:
                    _note_dataset(source.dataset_id)
                    tab_dataset_ids.append(source.dataset_id)
                    dataset = cache.dataset(source.dataset_id)
                    issue = _entity_issue(
                        dataset,
                        kind_missing="missing_dataset",
                        tab_id=tab.id,
                        item_id=member.id,
                        message_missing=f"selector {member.id!r}: dataset {source.dataset_id!r} does not exist",
                        message_forbidden=f"selector {member.id!r}: no access to dataset {source.dataset_id!r}",
                    )
                    if issue is not None:
                        issues.append(issue)
                        continue
                    assert isinstance(dataset, Dataset)
                    guids = {field.guid for field in dataset.fields}
                    if source.dataset_field_id and source.dataset_field_id not in guids:
                        titles = [title for field in dataset.fields if (title := field.title)]
                        suggestions = tuple(difflib.get_close_matches(source.dataset_field_id, titles, n=3))
                        issues.append(
                            ValidationIssue(
                                kind="missing_dataset_field",
                                tab_id=tab.id,
                                item_id=member.id,
                                message=(
                                    f"selector {member.id!r}: field {source.dataset_field_id!r} is not in "
                                    f"dataset {source.dataset_id!r}"
                                ),
                                suggestions=suggestions,
                            )
                        )
                    continue
                if member.source_type == "manual" and source.param_name:
                    manual_members.append((tab.id, member))
        # dangling aliases (including pre-existing ones): a field counts as
        # used when an item references it as a parameter OR when it is a
        # field of any dataset reachable from this tab's items — the
        # cross-dataset alias case (live UAT P021). With sources whose fields
        # cannot be enumerated (editor charts, external selectors, unreadable
        # entities) the check is skipped: it could not tell dangling from live.
        default_groups = tab.aliases.get("default")
        if isinstance(default_groups, list) and default_groups and not tab_sources_unknown:
            used_fields = set(_tab_used_fields(dict(tab.raw)))
            for dataset_id in dict.fromkeys(tab_dataset_ids):
                entity = cache.dataset(dataset_id)
                if isinstance(entity, Dataset):
                    used_fields.update(field.guid for field in entity.fields if field.guid)
                else:
                    tab_sources_unknown = True
            if not tab_sources_unknown:
                for group in default_groups:
                    if not isinstance(group, list):
                        continue
                    dangling = [field for field in group if isinstance(field, str) and field not in used_fields]
                    if dangling:
                        issues.append(
                            ValidationIssue(
                                kind="dangling_alias",
                                tab_id=tab.id,
                                item_id=None,
                                message=(
                                    f"alias group {group!r}: fields {dangling!r} are not used by any item "
                                    "or dataset on this tab"
                                ),
                            )
                        )

    # manual binding: the parameter must exist on SOME reachable dataset
    if manual_members:
        parameter_titles: list[str] = []
        for dataset_id in reachable_dataset_ids:
            parameter_titles.extend(_parameter_titles(cache.dataset(dataset_id)))
        known = set(parameter_titles)
        for tab_id, member in manual_members:
            param_name = member.source.param_name
            if param_name in known:
                continue
            suggestions = tuple(difflib.get_close_matches(param_name or "", parameter_titles, n=3))
            issues.append(
                ValidationIssue(
                    kind="unbound_manual_selector",
                    tab_id=tab_id,
                    item_id=member.id,
                    message=(
                        f"manual selector {member.id!r}: parameter {param_name!r} is not declared on any "
                        "dataset reachable from this dashboard"
                    ),
                    suggestions=suggestions,
                )
            )

    issues.sort(key=lambda issue: (issue.tab_id or "", issue.item_id or "", issue.kind, issue.message))
    return tuple(issues)
