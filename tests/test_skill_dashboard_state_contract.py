from __future__ import annotations

import ast
from collections.abc import Callable
import inspect
from pathlib import Path
import re
from typing import get_args

import datalens_sdk as dl
from datalens_sdk.client import DataNamespace
from datalens_sdk.domain.chart_types import FilterOperation

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"
REFERENCE = SKILL_DIR / "references" / "dashboard-state.md"
METHODS: dict[str, Callable[..., object]] = {
    "get_state": dl.Dashboard.get_state,
    "new_state": dl.Dashboard.new_state,
    "create_state": dl.Dashboard.create_state,
    "screenshot": dl.Dashboard.screenshot,
    "select": dl.DashboardStateBuilder.select,
    "clear": dl.DashboardStateBuilder.clear,
    "add": dl.DashboardStateBuilder.add,
    "prune": dl.DashboardStateBuilder.prune,
    "to_raw": dl.DashboardStateBuilder.to_raw,
    "create": dl.DashboardStateBuilder.create,
    "edit": dl.DashboardState.edit,
    "url": dl.DashboardState.url,
    "params_for": dl.DashboardState.params_for,
    "effects": dl.DashboardState.effects,
    "get_chart_data": DataNamespace.get_chart_data,
}


def _examples() -> list[ast.Module]:
    return [ast.parse(block) for block in re.findall(r"```python\n(.*?)```", REFERENCE.read_text(), flags=re.DOTALL)]


def test_skill_routes_dashboard_state_tasks() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text()

    assert skill.count("references/dashboard-state.md") >= 3
    for name in ("dashboards.md", "parameters.md", "screenshots.md"):
        assert "dashboard-state.md" in (SKILL_DIR / "references" / name).read_text()


def test_reference_examples_use_public_names_and_real_signatures() -> None:
    called: set[str] = set()
    for tree in _examples():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module == "datalens_sdk"
                for alias in node.names:
                    assert hasattr(dl, alias.name), alias.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id[0].isupper():
                assert hasattr(dl, node.func.id), node.func.id
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            method = METHODS.get(node.func.attr)
            if method is None:
                continue
            called.add(node.func.attr)
            parameters = inspect.signature(method).parameters
            positional = [
                _ for _ in parameters.values() if _.name != "self" and _.kind is not inspect.Parameter.KEYWORD_ONLY
            ]
            assert len(node.args) <= len(positional), node.func.attr
            for keyword in node.keywords:
                assert keyword.arg in parameters, (node.func.attr, keyword.arg)
    assert {"get_state", "new_state", "select", "create", "url", "params_for"} <= called


def test_reference_covers_the_api_surface() -> None:
    reference = REFERENCE.read_text()
    for method in (dl.Dashboard.get_state, dl.DashboardStateBuilder.select, dl.DashboardState.effects):
        for argument in inspect.signature(method).parameters:
            if argument != "self":
                assert f"{argument}=" in reference or f"`{argument}`" in reference, argument
    extra_operations = set(get_args(dl.ParamOperation)) - set(get_args(FilterOperation))
    assert len(extra_operations) == 12
    for operation in extra_operations:
        assert f"`{operation}`" in reference, operation
    for fragment in (
        "/rpc/getEntryState",
        "/rpc/createEntryState",
        "__meta__.queue",
        "groupItemId",
        "not a dashboard tab",
        "_ap_<guid>",
        "__interval_",
        "__relative_",
        "strict=True",
        "DashboardStateNotFoundError",
        "50 000",
        "ui_base_url",
        "https://datalens.ru",
        "resolve_charts=True",
        "usedParams",
        'kind": "ignore"',
        "aliases[namespace]",
        "get_chart_data(params=",
    ):
        assert fragment in reference, fragment
    for kind in ("unknown_state_item", "unknown_group_item", "unknown_widget_tab", "unknown_state_param"):
        assert kind in reference
    for certainty in ("received", "exact", "declared", "unknown"):
        assert f"`{certainty}`" in reference
    assert "TODO" not in reference
    assert "yandex-team" not in reference
