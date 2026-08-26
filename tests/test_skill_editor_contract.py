from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from typing import cast, get_type_hints

from datalens_sdk._generated.builders.charts import (
    EnterpriseEditorChartCreateFactory,
    YacloudEditorChartCreateFactory,
)

ROOT = Path(__file__).parents[1]
SKILLS_DIR = ROOT / "skills"
SKILL_DIR = SKILLS_DIR / "datalens-sdk"
EDITOR_DIR = SKILL_DIR / "references" / "editor-charts"
EDITOR_INDEX = EDITOR_DIR / "_index.md"
ENV_SPECIFIC = SKILLS_DIR / "env-specific.yaml"
LINK_PATTERN = re.compile(r"\[[^]]*\]\(([^)]+)\)")
PYTHON_BLOCK_PATTERN = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
METHOD_PATTERN = re.compile(r"`([a-z_]+)\(([^)]+)\)`")
EXPECTED_LEAVES = {
    "advanced_chart": "advanced-chart.md",
    "gravity_charts": "gravity-charts.md",
    "markdown": "markdown.md",
    "selector": "selector.md",
    "table": "table.md",
}


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _generated_nodes(installation: str) -> dict[str, dict[str, object]]:
    manifest = _object(json.loads((ROOT / "src" / "datalens_sdk" / "_generated" / "installations.json").read_text()))
    installations = _object(manifest["installations"])
    charts = _object(_object(installations[installation])["charts"])
    nodes = _object(charts["editor_nodes"])
    return {_string(_object(node)["factory_method"]): _object(node) for node in nodes.values()}


def _documented_routes() -> dict[str, tuple[str, frozenset[str], str]]:
    section = EDITOR_INDEX.read_text().split("## Renderer routing and supported tab methods", 1)[1]
    section = section.split("## Shared operations", 1)[0]
    routes: dict[str, tuple[str, frozenset[str], str]] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        factory = cells[0].strip("`")
        wire_type = cells[1].strip("`")
        tabs = frozenset(re.findall(r"`([^`]+)`", cells[3]))
        link = LINK_PATTERN.search(cells[4])
        assert link is not None
        routes[factory] = (wire_type, tabs, link.group(1))
    return routes


def _leaf_contract(path: Path) -> tuple[str, str, dict[str, str]]:
    text = path.read_text()
    factory_match = re.search(r"Factory: `client\.create\.editor_chart\.([a-z_]+)`", text)
    wire_match = re.search(r"`chart\.wire_type`: `([^`]+)`", text)
    methods_match = re.search(r"Supported create/update tab methods: (.*?)\.\n", text, re.DOTALL)
    assert factory_match is not None, path
    assert wire_match is not None, path
    assert methods_match is not None, path
    methods = dict(METHOD_PATTERN.findall(methods_match.group(1)))
    return factory_match.group(1), wire_match.group(1), methods


def test_public_editor_routes_match_both_generated_installations() -> None:
    routes = _documented_routes()
    enterprise = _generated_nodes("enterprise")
    yacloud = _generated_nodes("yacloud")

    assert enterprise == yacloud
    assert routes.keys() == enterprise.keys() == EXPECTED_LEAVES.keys()
    for factory, (wire_type, tabs, leaf) in routes.items():
        node = enterprise[factory]
        assert wire_type == node["wire_type"]
        assert tabs == frozenset(_object(node["data_fields"]))
        assert leaf == EXPECTED_LEAVES[factory]


def test_public_leaf_contracts_match_generated_builder_methods_and_types() -> None:
    nodes = _generated_nodes("yacloud")
    factory_classes = (YacloudEditorChartCreateFactory, EnterpriseEditorChartCreateFactory)

    for factory, filename in EXPECTED_LEAVES.items():
        documented_factory, wire_type, methods = _leaf_contract(EDITOR_DIR / filename)
        fields = _object(nodes[factory]["data_fields"])
        assert documented_factory == factory
        assert wire_type == nodes[factory]["wire_type"]
        assert methods == dict.fromkeys(fields, "str")

        for factory_class in factory_classes:
            builder_type = get_type_hints(getattr(factory_class, factory))["return"]
            builder_tabs = {
                name for name, value in vars(builder_type).items() if not name.startswith("_") and callable(value)
            }
            assert builder_tabs == fields.keys()
            for field in fields:
                assert get_type_hints(getattr(builder_type, field))["value"] is str


def test_public_create_and_per_wire_update_schemas_are_identical() -> None:
    manifest = _object(json.loads((ROOT / "src" / "datalens_sdk" / "_generated" / "installations.json").read_text()))
    for installation in ("enterprise", "yacloud"):
        charts = _object(_object(_object(manifest["installations"])[installation])["charts"])
        create_nodes = _object(charts["editor_nodes"])
        update_nodes = _object(charts["editor_update_nodes"])
        assert create_nodes.keys() == update_nodes.keys()
        for wire_type, create_node_value in create_nodes.items():
            create_node = _object(create_node_value)
            update_node = _object(update_nodes[wire_type])
            assert create_node["wire_type"] == update_node["wire_type"]
            assert create_node["data_fields"] == update_node["data_fields"]


def test_every_public_editor_reference_is_environment_specific_once() -> None:
    patterns = [line.removeprefix("  - ") for line in ENV_SPECIFIC.read_text().splitlines() if line.startswith("  - ")]
    resolved = [
        path.relative_to(SKILLS_DIR).as_posix()
        for pattern in patterns
        for path in sorted(SKILLS_DIR.glob(pattern))
        if path.is_file()
    ]
    editor_files = {path.relative_to(SKILLS_DIR).as_posix() for path in EDITOR_DIR.glob("*.md")}

    assert len(resolved) == len(set(resolved))
    assert editor_files
    assert all(resolved.count(path) == 1 for path in editor_files)


def test_public_editor_references_do_not_cross_installations() -> None:
    for path in EDITOR_DIR.glob("*.md"):
        text = path.read_text()
        assert "docs.yandex-team.ru" not in text, path
        assert "installation overlay" not in text.lower(), path
        for target in LINK_PATTERN.findall(text):
            if target.startswith(("http://", "https://")):
                assert target.startswith("https://yandex.cloud/"), f"{path}: {target}"


def test_public_editor_python_snippets_compile_and_local_links_resolve() -> None:
    for path in EDITOR_DIR.glob("*.md"):
        for index, source in enumerate(PYTHON_BLOCK_PATTERN.findall(path.read_text()), start=1):
            ast.parse(source, filename=f"{path}#python-{index}")
        for target in LINK_PATTERN.findall(path.read_text()):
            if target.startswith(("http://", "https://", "#")):
                continue
            assert (path.parent / target.split("#", 1)[0]).is_file(), f"{path}: {target}"
