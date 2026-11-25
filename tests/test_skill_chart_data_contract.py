from __future__ import annotations

import ast
import inspect
from pathlib import Path
import re

import datalens_sdk as dl
from datalens_sdk.client import DataNamespace

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"
REFERENCE = SKILL_DIR / "references" / "chart-data.md"


def test_skill_routes_chart_table_tasks_and_keeps_exports_separate() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text()

    assert skill.count("references/chart-data.md") >= 3
    assert "Reading tables from a saved Wizard, QL, or Editor chart" in skill
    assert "client.data.get_chart_data()" in skill
    assert "chart.get_chart_data()" in skill
    for name in ("dataset-data.md", "screenshots.md"):
        assert "[chart data](chart-data.md)" in (SKILL_DIR / "references" / name).read_text()
    assert "(parameters.md#runtime-chart-parameters)" in REFERENCE.read_text()


def test_chart_data_reference_covers_the_actual_api_and_result_contract() -> None:
    reference = REFERENCE.read_text()
    for method in (dl.Chart.get_chart_data, DataNamespace.get_chart_data):
        for argument in inspect.signature(method).parameters:
            if argument != "self":
                assert f"`{argument}`" in reference or f"{argument}=" in reference
    for fragment in (
        "/rpc/getChartData",
        "WizardChartData",
        "QLChartData",
        "EditorChartData",
        "ChartDataTable",
        "RuntimeParams",
        "RuntimeParamValue",
        "ScreenshotParams",
        "ScreenshotParamValue",
        "positional",
        "Column names can repeat",
        "deep copies",
        "unknown Wizard type",
        "params=None",
        "params={}",
        "no automatic pagination",
        "Editor.setRawData()",
        "## Wizard pivot results",
        "`ChartDataAggregation`",
        "`table.aggregation`",
        "zero-based indices",
        "multiple `subtotal` tables",
        "`(0, 2)` is grouped by region and product",
        '`aggregation.type == "detail"`',
        "table as unlabelled",
        "Rolled-up dimensions contain `null`",
        "Retained dimensions may contain genuine",
        "keep the separate tables",
        "100,000 rows",
        "100,000 cells",
        "1,000 tables",
        "100,000 schema columns",
        "800 columns",
        "HTTP 422 is not retried",
        "DataLensValidationError",
        "DTOValidationError",
        "InvalidResponseError",
        "error.context.request_id",
    ):
        assert fragment in reference
    assert "TODO" not in reference
    assert "yandex-team" not in reference


def test_chart_data_reference_requires_result_permission_and_executes_by_id() -> None:
    reference = REFERENCE.read_text()
    for fragment in (
        "## Result-handling permission is mandatory",
        "request to build or save code is not permission to run it",
        "Wait for the answer before calling the method",
        "shown in",
        "saved to a file",
        "saved script",
        "analyzed in code",
        "Both entrypoints execute **by ID**",
        "Loading a historical revision does not pin",
        "does not specify which",
        "saved/published revision is selected",
        "rejects `revId` and `branch`",
        "rejects `tab` and `state`",
        "DataLensValidationError` before HTTP",
        "Do not claim that returned rows belong to the loaded or",
        "Empty names and names beginning with `_` remain accepted",
        "chart.to_file(...)` serializes the chart definition",
        "not its returned data",
    ):
        assert fragment in reference

    for example in re.findall(r"```python\n(.*?)```", reference, flags=re.DOTALL):
        tree = ast.parse(example)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        assert calls
        for call in calls:
            assert isinstance(call.func, ast.Attribute)
            assert call.func.attr == "get_chart_data"
