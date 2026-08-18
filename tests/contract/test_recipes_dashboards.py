"""validate_dashboard_refs recipe (epic D4.6, stage 19).

The recipe walks the tolerant read model and classifies broken references
without raising; entity fetches go through the typed port accessors, so the
tests drive it with small fake ops objects (and pin that the real client
satisfies the recipe Protocol).
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import APIErrorContext, ForbiddenError, NotFoundError
from datalens_sdk.recipes import DashboardRecipeClient, ValidationIssue, validate_dashboard_refs

# -- fakes --------------------------------------------------------------------------


class _FakeChartOps:
    def __init__(self, charts: dict[str, object]) -> None:
        self._charts = charts

    def get_chart(self, chart_id: str, workbook_id: str | None = None) -> object:
        entity = self._charts.get(chart_id)
        if entity is None:
            raise NotFoundError(APIErrorContext(status_code=404, code=None, message="not found"))
        if entity == "forbidden":
            raise ForbiddenError(APIErrorContext(status_code=403, code=None, message="forbidden"))
        return entity


class _FakeDatasetOps:
    def __init__(self, datasets: dict[str, object]) -> None:
        self._datasets = datasets

    def get_dataset(self, dataset_id: str, workbook_id: str | None = None) -> object:
        entity = self._datasets.get(dataset_id)
        if entity is None:
            raise NotFoundError(APIErrorContext(status_code=404, code=None, message="not found"))
        if entity == "forbidden":
            raise ForbiddenError(APIErrorContext(status_code=403, code=None, message="forbidden"))
        return entity


class _FakeClient:
    def __init__(self, *, charts: dict[str, object] | None = None, datasets: dict[str, object] | None = None) -> None:
        self.chart_ops = _FakeChartOps(charts or {})
        self.dataset_ops = _FakeDatasetOps(datasets or {})
        self.dashboard_ops = object()


def _dataset(dataset_id: str, *, fields: tuple[tuple[str, str], ...] = (), params: tuple[str, ...] = ()) -> Dataset:
    schema = [{"guid": guid, "title": title, "data_type": "string", "type": "DIMENSION"} for guid, title in fields]
    schema.extend(
        {"guid": f"param_{name}", "title": name, "data_type": "string", "calc_mode": "parameter"} for name in params
    )
    return Dataset(id=dataset_id, installation="yacloud", result_schema=tuple(schema))


def _wizard_chart(chart_id: str, *, dataset_ids: tuple[str, ...] = ()) -> WizardChart:
    return WizardChart(
        id=chart_id,
        installation="yacloud",
        data={
            "sources": {"datasetsIds": list(dataset_ids)},
            "visualization": {"type": "line", "x": {"items": []}},
        },
    )


def _dashboard(tabs: list[dict[str, object]]) -> Dashboard:
    data: dict[str, object] = {"tabs": tabs}
    return Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "dash-1", "data": data})


def _control(member_id: str, source: dict[str, object], *, source_type: str) -> dict[str, object]:
    return {
        "id": f"g_{member_id}",
        "type": "group_control",
        "namespace": "default",
        "data": {
            "group": [
                {
                    "id": member_id,
                    "title": member_id,
                    "sourceType": source_type,
                    "source": source,
                    "defaults": {},
                }
            ],
            "autoHeight": False,
            "buttonApply": False,
            "buttonReset": False,
            "updateControlsOnChange": True,
            "showGroupName": False,
        },
    }


def _tab(items: list[dict[str, object]], *, aliases: list[list[str]] | None = None) -> dict[str, object]:
    return {
        "id": "tab_1",
        "title": "T",
        "items": items,
        "layout": [],
        "connections": [],
        "aliases": {"default": aliases or []},
    }


def _kinds(issues: tuple[ValidationIssue, ...]) -> list[str]:
    return [issue.kind for issue in issues]


def _validate(client: object, dashboard: Dashboard) -> tuple[ValidationIssue, ...]:
    # the fakes satisfy the recipe structurally but not the full port Protocols
    return validate_dashboard_refs(cast("DashboardRecipeClient", client), dashboard)


# -- checks -------------------------------------------------------------------------


def test_clean_dashboard_yields_no_issues() -> None:
    dashboard = _dashboard(
        [
            _tab(
                [
                    {
                        "id": "w1",
                        "type": "widget",
                        "data": {"tabs": [{"id": "wt1", "chartId": "ch-ok", "params": {}}]},
                    },
                    _control(
                        "m1",
                        {"datasetId": "ds-ok", "datasetFieldId": "guid_a", "elementType": "select"},
                        source_type="dataset",
                    ),
                ]
            )
        ]
    )
    client = _FakeClient(
        charts={"ch-ok": _wizard_chart("ch-ok", dataset_ids=("ds-ok",))},
        datasets={"ds-ok": _dataset("ds-ok", fields=(("guid_a", "Category"),))},
    )
    assert _validate(client, dashboard) == ()


def test_missing_and_forbidden_charts_are_distinguished() -> None:
    dashboard = _dashboard(
        [
            _tab(
                [
                    {"id": "w1", "type": "widget", "data": {"tabs": [{"id": "wt1", "chartId": "ch-gone"}]}},
                    {"id": "w2", "type": "widget", "data": {"tabs": [{"id": "wt2", "chartId": "ch-secret"}]}},
                ]
            )
        ]
    )
    client = _FakeClient(charts={"ch-secret": "forbidden"})
    issues = _validate(client, dashboard)
    assert _kinds(issues) == ["missing_chart", "access_denied"]
    assert issues[0].item_id == "w1"
    assert issues[1].item_id == "w2"


def test_missing_dataset_field_suggests_titles() -> None:
    dashboard = _dashboard(
        [
            _tab(
                [
                    _control(
                        "m1",
                        {"datasetId": "ds-1", "datasetFieldId": "catgory", "elementType": "select"},
                        source_type="dataset",
                    )
                ]
            )
        ]
    )
    client = _FakeClient(datasets={"ds-1": _dataset("ds-1", fields=(("guid_a", "category"),))})
    issues = _validate(client, dashboard)
    assert _kinds(issues) == ["missing_dataset_field"]
    assert issues[0].suggestions == ("category",)


def test_manual_selector_binding_over_reachable_datasets() -> None:
    dashboard = _dashboard(
        [
            _tab(
                [
                    {
                        "id": "w1",
                        "type": "widget",
                        "data": {"tabs": [{"id": "wt1", "chartId": "ch-1", "params": {}}]},
                    },
                    _control("m1", {"fieldName": "region", "elementType": "input"}, source_type="manual"),
                    _control("m2", {"fieldName": "reggion", "elementType": "input"}, source_type="manual"),
                ]
            )
        ]
    )
    client = _FakeClient(
        charts={"ch-1": _wizard_chart("ch-1", dataset_ids=("ds-1",))},
        datasets={"ds-1": _dataset("ds-1", params=("region",))},
    )
    issues = _validate(client, dashboard)
    assert _kinds(issues) == ["unbound_manual_selector"]
    assert issues[0].item_id == "m2"
    assert issues[0].suggestions == ("region",)


def test_dangling_alias_detection_covers_preexisting_ones() -> None:
    dashboard = _dashboard(
        [
            _tab(
                [_control("m1", {"fieldName": "field_a", "elementType": "input"}, source_type="manual")],
                aliases=[["field_a", "field_gone"]],
            )
        ]
    )
    issues = _validate(_FakeClient(), dashboard)
    assert _kinds(issues) == ["dangling_alias", "unbound_manual_selector"]
    assert "field_gone" in issues[0].message


def test_cross_dataset_alias_field_is_not_flagged() -> None:
    # live P021 shape: the alias pairs a selector field with a field of the
    # widget's dataset — never a parameter key in the document, still live
    dashboard = _dashboard(
        [
            _tab(
                [
                    {
                        "id": "w1",
                        "type": "widget",
                        "data": {"tabs": [{"id": "wt1", "chartId": "ch-1", "params": {}}]},
                    },
                    _control(
                        "m1",
                        {"datasetId": "ds-2", "datasetFieldId": "uat_guid", "elementType": "select"},
                        source_type="dataset",
                    ),
                ],
                aliases=[["uat_guid", "category_g71a"]],
            )
        ]
    )
    client = _FakeClient(
        charts={"ch-1": _wizard_chart("ch-1", dataset_ids=("ds-1",))},
        datasets={
            "ds-1": _dataset("ds-1", fields=(("category_g71a", "category"),)),
            "ds-2": _dataset("ds-2", fields=(("uat_guid", "category (uat)"),)),
        },
    )
    assert _validate(client, dashboard) == ()


def test_dangling_detection_is_skipped_when_tab_fields_are_not_enumerable() -> None:
    # an editor chart's fields cannot be listed: the recipe cannot tell a
    # dangling alias field from a live one and stays silent
    class _Editorish:
        pass

    dashboard = _dashboard(
        [
            _tab(
                [{"id": "w1", "type": "widget", "data": {"tabs": [{"id": "wt1", "chartId": "ch-ed", "params": {}}]}}],
                aliases=[["mystery_a", "mystery_b"]],
            )
        ]
    )
    client = _FakeClient(charts={"ch-ed": _Editorish()})
    assert _validate(client, dashboard) == ()


def test_issues_are_deterministically_ordered() -> None:
    dashboard = _dashboard(
        [
            _tab(
                [
                    {"id": "w2", "type": "widget", "data": {"tabs": [{"id": "wt2", "chartId": "ch-b"}]}},
                    {"id": "w1", "type": "widget", "data": {"tabs": [{"id": "wt1", "chartId": "ch-a"}]}},
                ]
            )
        ]
    )
    first = _validate(_FakeClient(), dashboard)
    second = _validate(_FakeClient(), dashboard)
    assert first == second
    assert [issue.item_id for issue in first] == ["w1", "w2"]


def test_wizard_chart_dataset_refs_are_validated() -> None:
    # a wizard chart pointing at a deleted dataset is a broken ref of the
    # widget even when no selector references that dataset
    dashboard = _dashboard(
        [_tab([{"id": "w1", "type": "widget", "data": {"tabs": [{"id": "wt1", "chartId": "ch-1"}]}}])]
    )
    client = _FakeClient(charts={"ch-1": _wizard_chart("ch-1", dataset_ids=("ds-gone",))})
    issues = _validate(client, dashboard)
    assert _kinds(issues) == ["missing_dataset"]
    assert issues[0].item_id == "w1"
    assert "ds-gone" in issues[0].message


def test_wizard_chart_forbidden_dataset_is_access_denied() -> None:
    dashboard = _dashboard(
        [_tab([{"id": "w1", "type": "widget", "data": {"tabs": [{"id": "wt1", "chartId": "ch-1"}]}}])]
    )
    client = _FakeClient(
        charts={"ch-1": _wizard_chart("ch-1", dataset_ids=("ds-secret",))},
        datasets={"ds-secret": "forbidden"},
    )
    issues = _validate(client, dashboard)
    assert _kinds(issues) == ["access_denied"]


def test_recipe_api_is_exported_from_the_package_root() -> None:
    assert dl.validate_dashboard_refs is validate_dashboard_refs
    assert dl.ValidationIssue is ValidationIssue
    assert dl.DashboardRecipeClient is DashboardRecipeClient


def test_real_client_satisfies_the_recipe_protocol() -> None:
    client = dl.DataLensClientYC(
        auth=None,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    assert isinstance(client, DashboardRecipeClient)


def test_unexpected_errors_propagate() -> None:
    class _Boom:
        def get_chart(self, chart_id: str, workbook_id: str | None = None) -> object:
            raise RuntimeError("network down")

    class _Client:
        chart_ops = _Boom()
        dataset_ops = _FakeDatasetOps({})
        dashboard_ops = object()

    dashboard = _dashboard(
        [_tab([{"id": "w1", "type": "widget", "data": {"tabs": [{"id": "wt1", "chartId": "ch-x"}]}}])]
    )
    with pytest.raises(RuntimeError, match="network down"):
        _validate(_Client(), dashboard)
