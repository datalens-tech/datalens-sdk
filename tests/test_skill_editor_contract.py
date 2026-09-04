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
INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
EXPECTED_FACTORIES = {"advanced_chart", "gravity_charts", "markdown", "selector", "table"}
EXPECTED_LEAVES = {
    "advanced_chart": "advanced-chart.md",
    "gravity_charts": "gravity-charts.md",
    "markdown": "markdown.md",
    "selector": "selector.md",
    "table": "table.md",
}
EXPECTED_LOCAL_FILES = {"_index.md", "common-operations.md", *EXPECTED_LEAVES.values()}


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
    section = EDITOR_INDEX.read_text().split("## SDK renderer matrix", 1)[1]
    section = section.split("## Runtime documentation router", 1)[0]
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


def _leaf_contract(path: Path) -> tuple[set[str], set[str]]:
    preamble = path.read_text().split("## Minimal payload", 1)[0]
    code_tokens = set(INLINE_CODE_PATTERN.findall(preamble))
    methods = {
        token.removesuffix("(str)")
        for token in code_tokens
        if token.endswith("(str)") and token.removesuffix("(str)").isidentifier()
    }
    return code_tokens, methods


def _minimal_payload_calls(path: Path) -> set[str]:
    minimal_payload = path.read_text().split("## Minimal payload", 1)[1].split("\n## ", 1)[0]
    calls: set[str] = set()
    for source in PYTHON_BLOCK_PATTERN.findall(minimal_payload):
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return calls


def test_public_editor_routes_match_both_generated_installations() -> None:
    routes = _documented_routes()
    enterprise = _generated_nodes("enterprise")
    yacloud = _generated_nodes("yacloud")

    assert enterprise == yacloud
    assert routes.keys() == enterprise.keys() == EXPECTED_FACTORIES
    for factory, (wire_type, tabs, target) in routes.items():
        node = enterprise[factory]
        assert wire_type == node["wire_type"]
        assert tabs == frozenset(_object(node["data_fields"]))
        assert target == EXPECTED_LEAVES[factory]
        assert (EDITOR_DIR / target).is_file()


def test_public_renderer_leaves_match_generated_builder_methods_and_types() -> None:
    nodes = _generated_nodes("yacloud")
    factory_classes = (YacloudEditorChartCreateFactory, EnterpriseEditorChartCreateFactory)
    for factory, filename in EXPECTED_LEAVES.items():
        code_tokens, methods = _leaf_contract(EDITOR_DIR / filename)
        fields = _object(nodes[factory]["data_fields"])

        assert f"client.create.editor_chart.{factory}" in code_tokens
        assert nodes[factory]["wire_type"] in code_tokens
        assert methods == set(fields)

        for factory_class in factory_classes:
            builder_type = get_type_hints(getattr(factory_class, factory))["return"]
            builder_tabs = {
                name for name, value in vars(builder_type).items() if not name.startswith("_") and callable(value)
            }
            assert builder_tabs == fields.keys()
            for field in fields:
                assert get_type_hints(getattr(builder_type, field))["value"] is str


def test_public_editor_keeps_one_leaf_per_renderer() -> None:
    assert {path.name for path in EDITOR_DIR.glob("*.md")} == EXPECTED_LOCAL_FILES

    for filename in EXPECTED_LEAVES.values():
        path = EDITOR_DIR / filename
        assert "## Minimal payload" in path.read_text()
        assert {"description", "build"} <= _minimal_payload_calls(path)


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


def test_public_editor_common_operations_separate_destructive_steps() -> None:
    text = (EDITOR_DIR / "common-operations.md").read_text()
    lifecycle = text.split("## Rename, relations, and delete\n", 1)[1]

    assert "Mapping[str, object]" in text
    relation_scopes = ("dash", "report", "widget", "dataset", "folder", "connection")
    assert all(f'"{scope}"' in lifecycle for scope in relation_scopes)
    before_delete = lifecycle[: lifecycle.index("chart.delete(")]
    assert re.search(r"\bconfirm\w*\b", before_delete, re.IGNORECASE)


def test_public_editor_routes_runtime_details_to_section_links() -> None:
    docs_root = "https://yandex.cloud/ru/docs/datalens/charts/editor"
    index_links = set(LINK_PATTERN.findall(EDITOR_INDEX.read_text()))
    advanced_text = (EDITOR_DIR / "advanced-chart.md").read_text()
    advanced_links = set(LINK_PATTERN.findall(advanced_text))

    assert {
        f"{docs_root}/tabs#meta",
        f"{docs_root}/tabs#sources",
        f"{docs_root}/methods#get-loaded-data",
        f"{docs_root}/methods#wrap",
    } <= index_links
    assert {
        f"{docs_root}/widgets/advanced#begin",
        f"{docs_root}/widgets/advanced#outer-libs",
        f"{docs_root}/widgets/advanced#actions",
        f"{docs_root}/widgets/advanced#tooltip",
        f"{docs_root}/widgets/advanced#chart-chart-filtration",
        f"{docs_root}/tabs#special-parameters",
        f"{docs_root}/tabs#relative-date",
        f"{docs_root}/tabs#interval",
        f"{docs_root}/tabs#params-restrictions",
        f"{docs_root}/tabs#sources-dataset",
        f"{docs_root}/tabs#sources-database",
        f"{docs_root}/tabs#sources-api-connector",
        f"{docs_root}/methods",
    } <= advanced_links
    assert {
        "Editor.getId()",
        "Editor.getLoadedData()",
        "Editor.getParams()",
        "Editor.generateHtml()",
        "Editor.wrapFn()",
    } <= set(INLINE_CODE_PATTERN.findall(advanced_text))


def test_public_editor_routing_uses_packaged_environment_manifest() -> None:
    skill_links = set(LINK_PATTERN.findall((SKILL_DIR / "SKILL.md").read_text()))

    assert "../env-specific.yaml" in skill_links
    assert "references/editor-charts/_index.md" in skill_links
