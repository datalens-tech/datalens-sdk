from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from datalens_sdk._generated.builders.charts import (
    EnterpriseEditorChartCreateFactory,
    QLChartCreateFactory,
    WizardChartCreateFactory,
    YacloudEditorChartCreateFactory,
)
from datalens_sdk.codegen import _editor_factory_method_name, _visualization_factory_methods
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.ports import ChartOperations

PUBLIC_EDITOR_FACTORY_METHODS = frozenset(
    {
        "advanced_chart",
        "gravity_charts",
        "markdown",
        "selector",
        "table",
    }
)


def _public_methods(owner: object) -> frozenset[str]:
    return frozenset(name for name in dir(owner) if not name.startswith("_") and callable(getattr(owner, name)))


def test_metric_factories_use_ui_indicator_name_without_changing_builder_semantics() -> None:
    operations = cast(ChartOperations, None)
    location = EntryLocation.path("/Charts")

    wizard_factory = WizardChartCreateFactory(operations)
    wizard_builder = wizard_factory.indicator(name="Indicator", location=location)
    assert wizard_builder.viz_id == "metric"
    assert wizard_builder.wire_type == "metric_wizard_node"
    assert not hasattr(wizard_factory, "metric")

    ql_factory = QLChartCreateFactory(operations)
    ql_builder = ql_factory.indicator(name="Indicator", location=location)
    ql_visualization = cast(Mapping[str, object], ql_builder.to_spec().visualization)
    assert ql_visualization["id"] == "metric"
    assert not hasattr(ql_factory, "metric")


@pytest.mark.parametrize(
    ("factory_cls", "expected_methods"),
    [
        (YacloudEditorChartCreateFactory, PUBLIC_EDITOR_FACTORY_METHODS),
        (EnterpriseEditorChartCreateFactory, PUBLIC_EDITOR_FACTORY_METHODS),
    ],
)
def test_public_editor_factories_use_exact_ui_method_names(
    factory_cls: type[YacloudEditorChartCreateFactory] | type[EnterpriseEditorChartCreateFactory],
    expected_methods: frozenset[str],
) -> None:
    factory = factory_cls(cast(ChartOperations, None))
    assert _public_methods(factory) == expected_methods


@pytest.mark.parametrize(
    ("wire_type", "schema_name", "expected"),
    [
        ("advanced-chart_node", "CreateEditorAdvancedChartNodeEntry", "advanced_chart"),
        ("control_node", "CreateEditorSelectorNodeEntry", "selector"),
        ("d3_node", "CreateEditorGravityChartsNodeEntry", "gravity_charts"),
        ("graph_node", "CreateEditorHighchartsNodeEntry", "highcharts"),
        ("markdown_node", "CreateEditorMarkdownNodeEntry", "markdown"),
        ("markup_node", "CreateEditorMarkupNodeEntry", "markup"),
        ("metric_node", "CreateEditorMetricNodeEntry", "indicator"),
        ("module", "CreateEditorModuleEntry", "module"),
        ("table_node", "CreateEditorTableNodeEntry", "table"),
        ("timeseries_node", "CreateEditorYagrNodeEntry", "yagr"),
        ("ymap_node", "CreateEditorYaMapsNodeEntry", "ya_maps"),
    ],
)
def test_editor_factory_method_name_comes_from_schema_with_ui_overrides(
    wire_type: str,
    schema_name: str,
    expected: str,
) -> None:
    assert _editor_factory_method_name(wire_type, schema_name) == expected


@pytest.mark.parametrize(
    "schema_name",
    [
        "EditorAdvancedChartNodeEntry",
        "CreateEditorNodeEntry",
        "CreateEditorAdvancedChart",
        "CreateEditorAdvanced_ChartNodeEntry",
        "CreateEditorBuildNodeEntry",
    ],
)
def test_editor_factory_method_name_rejects_unstable_or_reserved_schema_names(schema_name: str) -> None:
    with pytest.raises(ValueError, match="Editor factory method"):
        _editor_factory_method_name("custom_node", schema_name)


def test_visualization_factory_method_names_reject_collisions() -> None:
    with pytest.raises(ValueError, match="Wizard factory method collision"):
        _visualization_factory_methods(["flatTable", "flat_table"], family="Wizard")


def test_visualization_factory_method_names_reject_reserved_names() -> None:
    with pytest.raises(ValueError, match="QL factory method"):
        _visualization_factory_methods(["build"], family="QL")
