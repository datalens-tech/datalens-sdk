from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, get_args, get_type_hints

import httpx
from typing_extensions import assert_type

from datalens_sdk import (
    CacheInvalidationSource,
    Collection,
    CollectionCreate,
    CollectionSummary,
    CollectionUpdate,
    Dashboard,
    DashboardTabView,
    DataLensClientEnterprise,
    DataLensClientYC,
    Dataset,
    DatasetUpdate,
    DirectoryPager,
    EditorChart,
    EntryLocation,
    EntryRelation,
    EntrySummary,
    FieldsProxy,
    Folder,
    FolderCreate,
    FolderUpdate,
    JsonValue,
    License,
    Pager,
    QLChart,
    QLChartUpdate,
    QLColumn,
    RawConnectionCreate,
    RawConnectionReplace,
    RawDashboardCreate,
    RawDashboardReplace,
    RawEditorChartCreate,
    RawEditorChartReplace,
    RawQLChartCreate,
    RawQLChartReplace,
    RawWizardChartCreate,
    RawWizardChartReplace,
    WizardChart,
    Workbook,
    WorkbookCreate,
    WorkbookSummary,
    WorkbookUpdate,
)
from datalens_sdk._generated.builders.charts import (
    AdvancedChartNodeNodeCreate,
    EnterpriseEditorChartCreateFactory,
    LineWizardChartCreate,
    WizardChartCreateFactory,
    YacloudEditorChartCreateFactory,
)
from datalens_sdk._generated.builders.dataset_sources import (
    EnterpriseSourceCreateFactory,
    YacloudSourceCreateFactory,
)
from datalens_sdk._generated.builders.enterprise import (
    ClickhouseConnectionCreate as EnterpriseClickhouseConnectionCreate,
)
from datalens_sdk._generated.builders.enterprise import (
    ConnectionCreateFactory as EnterpriseConnectionCreateFactory,
)
from datalens_sdk._generated.builders.yacloud import (
    ClickhouseConnectionCreate as YacloudClickhouseConnectionCreate,
)
from datalens_sdk._generated.builders.yacloud import (
    ConnectionCreateFactory as YacloudConnectionCreateFactory,
)
from datalens_sdk._generated.builders.yacloud import PostgresConnectionCreate
from datalens_sdk.client import (
    CreateNamespace,
    DashboardCreateFactory,
    DatasetCreateFactory,
    GetNamespace,
    LicensesNamespace,
    NavigationNamespace,
)
from datalens_sdk.domain import (
    Connection,
    DashboardCreate,
    DashboardTab,
    DashboardUpdate,
    DatasetCreate,
    RawDatasetCreate,
    RawDatasetReplace,
    SourceCreate,
)
from datalens_sdk.domain.dataset_update import FieldRef
from datalens_sdk.raw import (
    RawConnectionCreateFactory,
    RawConnectionReplaceFactory,
    RawCreateNamespace,
    RawDashboardCreateFactory,
    RawDashboardReplaceFactory,
    RawDatasetCreateFactory,
    RawDatasetReplaceFactory,
    RawEditorChartCreateFactory,
    RawEditorChartReplaceFactory,
    RawNamespace,
    RawQLChartCreateFactory,
    RawQLChartReplaceFactory,
    RawReplaceNamespace,
    RawWizardChartCreateFactory,
    RawWizardChartReplaceFactory,
)


def _check_entry_mutation_return_types(
    *,
    collection: Collection,
    workbook: Workbook,
    folder: Folder,
    connection: Connection,
    dataset: Dataset,
    dashboard: Dashboard,
    wizard: WizardChart,
    editor: EditorChart,
    ql: QLChart,
) -> None:
    assert_type(collection.rename("Renamed"), Collection)
    assert_type(workbook.rename("Renamed"), Workbook)
    assert_type(folder.rename("Renamed"), Folder)
    assert_type(collection.move(EntryLocation.collection("parent")), Collection)
    assert_type(workbook.move(None), Workbook)
    assert_type(folder.move(EntryLocation.path("/Destination")), Folder)
    assert_type(connection.rename("Renamed"), Connection)
    assert_type(dataset.rename("Renamed"), Dataset)
    assert_type(dashboard.rename("Renamed"), Dashboard)
    assert_type(wizard.rename("Renamed"), WizardChart)
    assert_type(editor.rename("Renamed"), EditorChart)
    assert_type(ql.rename("Renamed"), QLChart)
    assert_type(
        ql.update.x([QLColumn("x")])
        .y(["y"])
        .y2(["y2"])
        .dimensions(["dimension"])
        .measures(["measure"])
        .points(["point"])
        .size(["size"])
        .flat_table_columns(["column"])
        .colors(["color"])
        .labels(["label"])
        .shapes(["shape"])
        .tooltips(["tooltip"])
        .description("Description"),
        QLChartUpdate,
    )


def _check_raw_chart_return_types(
    *,
    client: DataLensClientYC,
    wizard: WizardChart,
    editor: EditorChart,
    ql: QLChart,
) -> None:
    wizard_create = client.raw.create.wizard_chart(
        response_snapshot={"entryId": "source", "type": "d3_wizard_node", "data": {}},
        name="Wizard",
        location=EntryLocation.path("/raw"),
    )
    editor_create = client.raw.create.editor_chart(
        response_snapshot={"entry": {"entryId": "source", "type": "advanced-chart_node", "data": {}}},
        name="Editor",
        location=EntryLocation.path("/raw"),
    )
    ql_create = client.raw.create.ql_chart(
        response_snapshot={"entryId": "source", "type": "d3_ql_node", "data": {}},
        name="QL",
        location=EntryLocation.path("/raw"),
    )
    assert_type(wizard_create, RawWizardChartCreate)
    assert_type(editor_create, RawEditorChartCreate)
    assert_type(ql_create, RawQLChartCreate)
    assert_type(wizard_create.build(), WizardChart)
    assert_type(editor_create.build(), EditorChart)
    assert_type(ql_create.build(), QLChart)

    wizard_replace = client.raw.replace.wizard_chart(
        target=wizard,
        response_snapshot={"entryId": "source", "type": "d3_wizard_node", "data": {}},
    )
    editor_replace = client.raw.replace.editor_chart(
        target=editor,
        response_snapshot={"entry": {"entryId": "source", "type": "advanced-chart_node", "data": {}}},
    )
    ql_replace = client.raw.replace.ql_chart(
        target=ql,
        response_snapshot={"entryId": "source", "type": "d3_ql_node", "data": {}},
    )
    assert_type(wizard_replace, RawWizardChartReplace)
    assert_type(editor_replace, RawEditorChartReplace)
    assert_type(ql_replace, RawQLChartReplace)
    assert_type(wizard_replace.mode("publish").execute(), WizardChart)
    assert_type(editor_replace.mode("publish").execute(), EditorChart)
    assert_type(ql_replace.mode("publish").execute(), QLChart)

    artifact = Path("/raw/chart-artifact")
    assert_type(client.raw.replace.wizard_chart.from_file(artifact, target=wizard), RawWizardChartReplace)
    assert_type(client.raw.replace.editor_chart.from_file(artifact, target=editor), RawEditorChartReplace)
    assert_type(client.raw.replace.ql_chart.from_file(artifact, target=ql), RawQLChartReplace)
    assert_type(editor.to_file(artifact, split_tabs=True), Path)


def _check_raw_namespace_return_types(
    *,
    client: DataLensClientYC,
    connection: Connection,
    dataset: Dataset,
    dashboard: Dashboard,
    wizard: WizardChart,
    editor: EditorChart,
    ql: QLChart,
) -> None:
    connection_snapshot: dict[str, JsonValue] = {"id": "source", "type": "postgres", "name": "Source"}
    dataset_snapshot: dict[str, JsonValue] = {"id": "source", "dataset": {}}
    dashboard_snapshot: dict[str, JsonValue] = {"entry": {"entryId": "source", "data": {}}}
    wizard_snapshot: dict[str, JsonValue] = {"entryId": "source", "type": "d3_wizard_node", "data": {}}
    editor_snapshot: dict[str, JsonValue] = {"entry": {"entryId": "source", "type": "advanced-chart_node", "data": {}}}
    ql_snapshot: dict[str, JsonValue] = {"entryId": "source", "type": "d3_ql_node", "data": {}}
    artifact = Path("/raw/artifact")

    assert_type(client.raw, RawNamespace)
    assert_type(client.raw.create, RawCreateNamespace)
    assert_type(client.raw.replace, RawReplaceNamespace)
    assert_type(client.raw.create.connection, RawConnectionCreateFactory)
    assert_type(client.raw.replace.connection, RawConnectionReplaceFactory)
    assert_type(client.raw.create.dataset, RawDatasetCreateFactory)
    assert_type(client.raw.replace.dataset, RawDatasetReplaceFactory)
    assert_type(client.raw.create.dashboard, RawDashboardCreateFactory)
    assert_type(client.raw.replace.dashboard, RawDashboardReplaceFactory)
    assert_type(client.raw.create.wizard_chart, RawWizardChartCreateFactory)
    assert_type(client.raw.replace.wizard_chart, RawWizardChartReplaceFactory)
    assert_type(client.raw.create.editor_chart, RawEditorChartCreateFactory)
    assert_type(client.raw.replace.editor_chart, RawEditorChartReplaceFactory)
    assert_type(client.raw.create.ql_chart, RawQLChartCreateFactory)
    assert_type(client.raw.replace.ql_chart, RawQLChartReplaceFactory)
    assert_type(
        client.raw.create.connection(
            response_snapshot=connection_snapshot,
            name="Connection",
            location=EntryLocation.path("/raw"),
            overrides={"password": "secret"},
        ),
        RawConnectionCreate,
    )
    assert_type(
        client.raw.create.connection.from_file(
            artifact,
            name="Connection",
            location=EntryLocation.path("/raw"),
            overrides={"password": "secret"},
        ),
        RawConnectionCreate,
    )
    assert_type(
        client.raw.replace.connection(
            target=connection,
            response_snapshot=connection_snapshot,
            overrides={"password": "secret"},
        ),
        RawConnectionReplace,
    )
    assert_type(
        client.raw.replace.connection.from_file(
            artifact,
            target=connection,
            overrides={"password": "secret"},
        ),
        RawConnectionReplace,
    )
    assert_type(
        client.raw.create.dataset(
            response_snapshot=dataset_snapshot,
            name="Dataset",
            location=EntryLocation.path("/raw"),
        ),
        RawDatasetCreate,
    )
    assert_type(
        client.raw.create.dataset.from_file(
            artifact,
            name="Dataset",
            location=EntryLocation.path("/raw"),
        ),
        RawDatasetCreate,
    )
    assert_type(
        client.raw.replace.dataset(
            target=dataset,
            response_snapshot=dataset_snapshot,
        ),
        RawDatasetReplace,
    )
    assert_type(client.raw.replace.dataset.from_file(artifact, target=dataset), RawDatasetReplace)
    assert_type(
        client.raw.create.dashboard(
            response_snapshot=dashboard_snapshot,
            name="Dashboard",
            location=EntryLocation.path("/raw"),
        ),
        RawDashboardCreate,
    )
    assert_type(
        client.raw.create.dashboard.from_file(
            artifact,
            name="Dashboard",
            location=EntryLocation.path("/raw"),
        ),
        RawDashboardCreate,
    )
    assert_type(
        client.raw.replace.dashboard(
            target=dashboard,
            response_snapshot=dashboard_snapshot,
        ),
        RawDashboardReplace,
    )
    assert_type(client.raw.replace.dashboard.from_file(artifact, target=dashboard), RawDashboardReplace)
    assert_type(
        client.raw.create.wizard_chart(
            response_snapshot=wizard_snapshot,
            name="Wizard",
            location=EntryLocation.path("/raw"),
        ),
        RawWizardChartCreate,
    )
    assert_type(
        client.raw.create.wizard_chart.from_file(
            artifact,
            name="Wizard",
            location=EntryLocation.path("/raw"),
        ),
        RawWizardChartCreate,
    )
    assert_type(
        client.raw.replace.wizard_chart(
            target=wizard,
            response_snapshot=wizard_snapshot,
        ).mode("publish"),
        RawWizardChartReplace,
    )
    assert_type(
        client.raw.replace.wizard_chart.from_file(artifact, target=wizard).mode("publish"),
        RawWizardChartReplace,
    )
    assert_type(
        client.raw.create.editor_chart(
            response_snapshot=editor_snapshot,
            name="Editor",
            location=EntryLocation.path("/raw"),
        ),
        RawEditorChartCreate,
    )
    assert_type(
        client.raw.create.editor_chart.from_file(
            artifact,
            name="Editor",
            location=EntryLocation.path("/raw"),
        ),
        RawEditorChartCreate,
    )
    assert_type(
        client.raw.replace.editor_chart(
            target=editor,
            response_snapshot=editor_snapshot,
        ).mode("publish"),
        RawEditorChartReplace,
    )
    assert_type(
        client.raw.replace.editor_chart.from_file(
            artifact,
            target=editor,
        ).mode("publish"),
        RawEditorChartReplace,
    )
    assert_type(
        client.raw.create.ql_chart(
            response_snapshot=ql_snapshot,
            name="QL",
            location=EntryLocation.path("/raw"),
        ),
        RawQLChartCreate,
    )
    assert_type(
        client.raw.create.ql_chart.from_file(
            artifact,
            name="QL",
            location=EntryLocation.path("/raw"),
        ),
        RawQLChartCreate,
    )
    assert_type(
        client.raw.replace.ql_chart(
            target=ql,
            response_snapshot=ql_snapshot,
        ).mode("publish"),
        RawQLChartReplace,
    )
    assert_type(
        client.raw.replace.ql_chart.from_file(artifact, target=ql).mode("publish"),
        RawQLChartReplace,
    )
    assert_type(
        client.raw.create.connection(
            response_snapshot=connection_snapshot,
            name="Connection",
            location=EntryLocation.path("/raw"),
        ).build(),
        Connection,
    )
    assert_type(
        client.raw.replace.connection(target=connection, response_snapshot=connection_snapshot).execute(),
        Connection,
    )
    assert_type(
        client.raw.create.dataset(
            response_snapshot=dataset_snapshot,
            name="Dataset",
            location=EntryLocation.path("/raw"),
        ).build(),
        Dataset,
    )
    assert_type(
        client.raw.replace.dataset(target=dataset, response_snapshot=dataset_snapshot).execute(),
        Dataset,
    )
    assert_type(
        client.raw.create.dashboard(
            response_snapshot=dashboard_snapshot,
            name="Dashboard",
            location=EntryLocation.path("/raw"),
        ).build(),
        Dashboard,
    )
    assert_type(
        client.raw.replace.dashboard(target=dashboard, response_snapshot=dashboard_snapshot).execute(publish=False),
        Dashboard,
    )
    assert_type(
        client.raw.create.wizard_chart(
            response_snapshot=wizard_snapshot,
            name="Wizard",
            location=EntryLocation.path("/raw"),
        ).build(),
        WizardChart,
    )
    assert_type(
        client.raw.replace.wizard_chart(target=wizard, response_snapshot=wizard_snapshot).execute(),
        WizardChart,
    )
    assert_type(
        client.raw.create.editor_chart(
            response_snapshot=editor_snapshot,
            name="Editor",
            location=EntryLocation.path("/raw"),
        ).build(),
        EditorChart,
    )
    assert_type(
        client.raw.replace.editor_chart(target=editor, response_snapshot=editor_snapshot).execute(),
        EditorChart,
    )
    assert_type(
        client.raw.create.ql_chart(
            response_snapshot=ql_snapshot,
            name="QL",
            location=EntryLocation.path("/raw"),
        ).build(),
        QLChart,
    )
    assert_type(
        client.raw.replace.ql_chart(target=ql, response_snapshot=ql_snapshot).execute(),
        QLChart,
    )


def _transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={}))


def _dataset_transport() -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "ds-1", "dataset": {"description": "", "sources": [], "result_schema": []}},
        )
    )


def _object_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rpc/getCollection":
            return httpx.Response(200, json={"collectionId": "collection-1", "title": "Analytics"})
        if request.url.path == "/rpc/getWorkbook":
            return httpx.Response(200, json={"workbookId": "workbook-1", "title": "Sales"})
        if request.url.path in ("/rpc/getDashboard", "/rpc/updateDashboard"):
            return httpx.Response(
                200,
                json={
                    "entry": {
                        "entryId": "dash-1",
                        "key": "/Users/me/Dash",
                        "revId": "rev-1",
                        "data": {"tabs": [{"id": "tab_1", "title": "One", "items": [], "layout": []}]},
                    }
                },
            )
        if request.url.path == "/rpc/listDirectory":
            return httpx.Response(
                200,
                json={
                    "entries": [
                        {
                            "entryId": "folder-1",
                            "key": "/Users/me/Archive",
                            "scope": "folder",
                            "type": "",
                        }
                    ],
                    "breadCrumbs": [],
                    "hasNextPage": False,
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_yacloud_client_namespaces_are_visible_to_static_tools() -> None:
    client = DataLensClientYC(auth=None, transport=_dataset_transport())

    assert_type(
        client.create,
        CreateNamespace[YacloudConnectionCreateFactory, YacloudSourceCreateFactory, YacloudEditorChartCreateFactory],
    )
    assert_type(client.create.connection, YacloudConnectionCreateFactory)
    assert_type(
        client.raw.create.connection(
            response_snapshot={"id": "source", "type": "postgres", "name": "Source"},
            name="Raw connection",
            location=EntryLocation.path("/raw"),
            overrides={"password": "secret"},
        ),
        RawConnectionCreate,
    )
    assert_type(client.create.editor_chart, YacloudEditorChartCreateFactory)
    assert_type(client.create.dashboard, DashboardCreateFactory)
    assert_type(
        client.raw.create.dashboard(
            response_snapshot={"entry": {"entryId": "source", "data": {}}},
            name="Raw dashboard",
            location=EntryLocation.path("/raw"),
        ),
        RawDashboardCreate,
    )
    assert_type(client.create.dataset, DatasetCreateFactory)
    assert_type(client.get, GetNamespace)
    assert_type(client.navigation, NavigationNamespace)
    assert_type(client.navigation.get_entries(), Pager[EntrySummary])
    assert_type(client.licenses, LicensesNamespace)
    assert_type(client.licenses.list(), Pager[License])
    dataset = client.get.dataset(by_id="ds-1")
    assert_type(dataset, Dataset)
    assert_type(dataset.fields, FieldsProxy)
    assert_type(dataset.parameters, FieldsProxy)
    assert_type(dataset.find_source_avatar("source-1"), Mapping[str, object] | None)
    assert_type(dataset.update, DatasetUpdate)
    assert_type(
        client.raw.create.dataset(
            response_snapshot={"id": "source", "dataset": {}},
            name="Raw dataset",
            location=EntryLocation.path("/raw"),
        ),
        RawDatasetCreate,
    )
    assert_type(
        client.raw.replace.dataset(
            target=dataset,
            response_snapshot={"id": "source", "dataset": {}},
        ),
        RawDatasetReplace,
    )
    assert_type(dataset.get_relations(), Pager[EntryRelation])
    dashboard = Dashboard(id="dashboard-1", data={})
    assert_type(
        client.raw.replace.dashboard(
            target=dashboard,
            response_snapshot={"entry": {"entryId": "source", "data": {}}},
        ),
        RawDashboardReplace,
    )
    if TYPE_CHECKING:
        assert_type(dashboard.to_file(Path("/raw"), with_dependencies=True), Path)

    connection = client.domain_connection(id="conn-1", type="postgres")
    assert_type(connection, Connection)
    assert_type(
        client.raw.replace.connection(
            target=connection,
            response_snapshot={"id": "source", "type": "postgres", "name": "Source"},
            overrides={"password": "secret"},
        ),
        RawConnectionReplace,
    )
    assert_type(connection.get_relations(), Pager[EntryRelation])
    assert_type(client.create.source(using=connection), YacloudSourceCreateFactory)
    assert_type(
        client.create.connection.postgres(name="PG", location=EntryLocation.path("/sdk")),
        PostgresConnectionCreate,
    )
    builder = client.create.connection.postgres(name="PG", location=EntryLocation.path("/sdk"))
    assert_type(builder.host("db.local"), PostgresConnectionCreate)
    assert_type(builder.port(5432), PostgresConnectionCreate)
    assert_type(builder.raw_sql_level("off"), PostgresConnectionCreate)
    clickhouse_builder = client.create.connection.clickhouse(name="CH", location=EntryLocation.path("/sdk"))
    assert_type(clickhouse_builder.secure("on"), YacloudClickhouseConnectionCreate)
    assert_type(
        client.create.dataset(name="DS", location=EntryLocation.path("/sdk")),
        DatasetCreate,
    )
    assert_type(
        client.create.source(using=connection).pg_table(alias="orders", table_name="orders"),
        SourceCreate,
    )


def test_enterprise_client_namespaces_are_visible_to_static_tools() -> None:
    client = DataLensClientEnterprise(
        auth=None,
        base_url="https://enterprise.example.test",
        transport=_transport(),
    )
    connection = client.domain_connection(id="conn-1", type="postgres")

    assert_type(
        client.create,
        CreateNamespace[
            EnterpriseConnectionCreateFactory,
            EnterpriseSourceCreateFactory,
            EnterpriseEditorChartCreateFactory,
        ],
    )
    assert_type(client.create.connection, EnterpriseConnectionCreateFactory)
    assert_type(
        client.raw.create.connection(
            response_snapshot={"id": "source", "type": "postgres", "name": "Source"},
            name="Raw connection",
            location=EntryLocation.path("/raw"),
        ),
        RawConnectionCreate,
    )
    assert_type(client.create.editor_chart, EnterpriseEditorChartCreateFactory)
    assert_type(client.create.source(using=connection), EnterpriseSourceCreateFactory)
    clickhouse_builder = client.create.connection.clickhouse(name="CH", location=EntryLocation.path("/sdk"))
    assert_type(clickhouse_builder.secure("on"), EnterpriseClickhouseConnectionCreate)


def test_object_crud_and_typed_destinations_are_visible_to_static_tools() -> None:
    client = DataLensClientYC(auth=None, transport=_object_transport())

    assert_type(client.create.collection(name="Analytics"), CollectionCreate)
    collection = client.get.collection(by_id="collection-1")
    assert_type(collection, Collection)
    assert_type(collection.update, CollectionUpdate)
    assert_type(collection.list_entries(), Pager[CollectionSummary | WorkbookSummary | EntrySummary])

    assert_type(client.create.workbook(name="Sales", collection=collection), WorkbookCreate)
    workbook = client.get.workbook(by_id="workbook-1")
    assert_type(workbook, Workbook)
    assert_type(workbook.update, WorkbookUpdate)
    assert_type(workbook.list_entries(), Pager[EntrySummary])

    assert_type(
        client.create.folder(name="Archive", location=EntryLocation.path("/Users/me")),
        FolderCreate,
    )
    folder = client.get.folder(by_path="/Users/me/Archive")
    assert_type(folder, Folder)
    assert_type(folder.update, FolderUpdate)
    assert_type(folder.list_entries(), DirectoryPager[EntrySummary])

    dashboard = client.get.dashboard(by_id="dash-1", branch="published")
    assert_type(dashboard, Dashboard)
    assert_type(dashboard.refresh(), Dashboard)
    assert_type(dashboard.refresh(branch="saved"), Dashboard)
    assert_type(dashboard.tabs, tuple[DashboardTabView, ...])
    assert_type(dashboard.get_relations(), Pager[EntryRelation])
    assert_type(dashboard.update, DashboardUpdate)
    assert_type(dashboard.update.hide_tab("tab_1"), DashboardUpdate)
    if TYPE_CHECKING:
        assert_type(
            dashboard.update.add_selector_to_group(
                group_item_id="filters",
                item_id="city",
                dataset=Dataset(id="ds-1"),
                field="City",
                element="select",
            ),
            DashboardUpdate,
        )
    assert_type(dashboard.update.execute(publish=True), Dashboard)
    assert_type(dashboard.publish_revision(rev_id="rev-1"), Dashboard)
    assert_type(
        client.create.dashboard(name="Dash", location=EntryLocation.path("/Users/me")),
        DashboardCreate,
    )
    tab = DashboardTab("Overview").add_text("hello", at=(0, 0, 12, 6))
    assert_type(tab, DashboardTab)
    assert_type(
        client.create.dashboard(name="Dash", location=EntryLocation.path("/Users/me")).add_tab(tab),
        DashboardCreate,
    )

    assert_type(client.create.dataset(location=workbook, name="Dataset"), DatasetCreate)
    assert_type(client.create.connection.postgres(location=workbook, name="PostgreSQL"), PostgresConnectionCreate)
    assert_type(client.create.wizard_chart.line(location=workbook, name="Chart"), LineWizardChartCreate)
    assert_type(
        client.create.editor_chart.advanced_chart(location=workbook, name="Editor chart"),
        AdvancedChartNodeNodeCreate,
    )


def test_dataset_update_public_signatures_avoid_broad_user_argument_types() -> None:
    field_ref_hint = get_type_hints(DatasetUpdate.change_field_type)["field"]
    assert field_ref_hint == FieldRef
    assert Mapping[str, object] not in getattr(field_ref_hint, "__args__", ())

    add_calc_hints = get_type_hints(DatasetUpdate.add_calculation)
    assert add_calc_hints["kind"] is not str
    assert add_calc_hints["aggregation"] != (str | None)
    assert add_calc_hints["cast"] != (str | None)

    parameter_hints = get_type_hints(DatasetUpdate.add_parameter)
    assert parameter_hints["type"] is not str
    assert parameter_hints["default"] is not object

    filter_hints = get_type_hints(DatasetUpdate.add_default_filter)
    assert filter_hints["operator"] is not str
    assert "object" not in repr(filter_hints["values"])

    relation_hints = get_type_hints(DatasetUpdate.add_relation)
    assert relation_hints["type"] is not str
    assert "conditions" in relation_hints
    assert "Sequence" in repr(relation_hints["conditions"])

    create_relation_hints = get_type_hints(DatasetCreate.add_relation)
    assert create_relation_hints["type"] is not str
    assert "conditions" in create_relation_hints
    assert "Sequence" in repr(create_relation_hints["conditions"])
    for source_hint in (create_relation_hints["left_source"], create_relation_hints["right_source"]):
        assert "Source" in repr(source_hint)
        assert "Any" not in repr(source_hint)
        assert "dict" not in repr(source_hint)

    cache_hints = get_type_hints(DatasetUpdate.update_cache_invalidation_source)
    assert cache_hints["source"] is CacheInvalidationSource

    setting_hints = get_type_hints(DatasetUpdate.update_setting)
    assert setting_hints["value"] is bool
    assert set(get_args(setting_hints["name"])) == {
        "load_preview_by_default",
        "template_enabled",
        "data_export_forbidden",
    }


def test_clickhouse_secure_public_signatures_are_literal_enums() -> None:
    for builder_type in (YacloudClickhouseConnectionCreate, EnterpriseClickhouseConnectionCreate):
        assert get_args(get_type_hints(builder_type.secure)["value"]) == ("on", "off")


def test_dataset_create_exposes_creation_safe_mutations() -> None:
    client = DataLensClientYC(auth=None, transport=_dataset_transport())
    builder = client.create.dataset(name="Dataset", location=EntryLocation.path("/Users/me"))

    assert_type(
        builder.add_calculation(name="Revenue", formula="SUM([revenue])", kind="MEASURE"),
        DatasetCreate,
    )
    assert_type(builder.hide_field(field="internal_id"), DatasetCreate)
    assert_type(builder.add_default_filter(field="country", operator="EQ", values=["US"]), DatasetCreate)
    assert_type(
        builder.update_cache_invalidation_source(source=CacheInvalidationSource(mode="sql", sql="SELECT 1")),
        DatasetCreate,
    )


def test_create_placement_signatures_use_one_entry_location_type() -> None:
    collection_hints = get_type_hints(CreateNamespace.collection)
    workbook_hints = get_type_hints(CreateNamespace.workbook)
    dashboard_hints = get_type_hints(DashboardCreateFactory.__call__)
    dataset_hints = get_type_hints(DatasetCreateFactory.__call__)
    connection_hints = get_type_hints(YacloudConnectionCreateFactory.postgres)
    wizard_chart_hints = get_type_hints(WizardChartCreateFactory.line)
    editor_chart_hints = get_type_hints(YacloudEditorChartCreateFactory.advanced_chart)

    assert collection_hints["parent"] == EntryLocation | None
    assert workbook_hints["collection"] == EntryLocation | None
    assert dashboard_hints["location"] == EntryLocation
    assert dashboard_hints["name"] is str
    assert dataset_hints["location"] == EntryLocation
    assert dataset_hints["name"] is str
    assert connection_hints["location"] == EntryLocation
    assert connection_hints["name"] is str
    assert wizard_chart_hints["location"] == EntryLocation
    assert wizard_chart_hints["name"] is str
    assert editor_chart_hints["location"] == EntryLocation
    assert editor_chart_hints["name"] is str
