from __future__ import annotations

import inspect
from pathlib import Path
import re
from typing import Any, cast

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk.domain.entry_location import EntryLocation

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"
WIZARD_REFERENCES = SKILL_DIR / "references" / "wizard-charts"
CREATE_INFRASTRUCTURE_METHODS = frozenset({"build", "dataset", "execute", "to_spec", "viz_id", "wire_type"})


def _table(text: str, heading: str) -> tuple[list[str], list[list[str]]]:
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    rows = [
        [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))] for line in lines
    ]
    return rows[0], rows[2:]


def _actual_create_builders() -> dict[str, Any]:
    factory = WizardChartCreateFactory(cast(Any, None))
    location = EntryLocation.path("/SkillChecks")
    factory_names = [name for name in dir(factory) if not name.startswith("_") and callable(getattr(factory, name))]
    return {
        factory_name: getattr(factory, factory_name)(name="Contract check", location=location)
        for factory_name in factory_names
    }


def _actual_create_methods() -> dict[str, set[str]]:
    return {
        factory_name: {
            name
            for name in dir(builder)
            if not name.startswith("_")
            and callable(getattr(builder, name))
            and name not in CREATE_INFRASTRUCTURE_METHODS
        }
        for factory_name, builder in _actual_create_builders().items()
    }


def _documented_index_create_methods() -> dict[str, set[str]]:
    text = (WIZARD_REFERENCES / "_index.md").read_text()
    header, rows = _table(text, "Full fluent-operation matrix")
    result: dict[str, set[str]] = {factory_name: set() for factory_name in header[2:]}
    for row in rows:
        operation = row[0].strip("`").split("(", 1)[0]
        if operation == "<factory>" or operation in CREATE_INFRASTRUCTURE_METHODS:
            continue
        for factory_name, support in zip(header[2:], row[2:], strict=True):
            if support in {"C", "CU"}:
                result[factory_name].add(operation)
    return result


def _documented_page_create_methods(factory_name: str) -> set[str]:
    path = WIZARD_REFERENCES / f"chart-{factory_name.replace('_', '-')}.md"
    _, rows = _table(path.read_text(), "Fluent operations")
    result: set[str] = set()
    for operation_cell, _, support in rows:
        operation = operation_cell.strip("`").split("(", 1)[0]
        if operation.startswith("client.create.") or operation in CREATE_INFRASTRUCTURE_METHODS:
            continue
        if support in {"C", "CU"}:
            result.add(operation)
    return result


def _documented_page_create_parameters(factory_name: str) -> dict[str, list[str]]:
    path = WIZARD_REFERENCES / f"chart-{factory_name.replace('_', '-')}.md"
    _, rows = _table(path.read_text(), "Fluent operations")
    result: dict[str, list[str]] = {}
    for operation_cell, arguments, support in rows:
        operation = operation_cell.strip("`").split("(", 1)[0]
        if operation.startswith("client.create.") or support not in {"C", "CU"}:
            continue
        arguments = arguments.replace("`", "").strip()
        result[operation] = (
            []
            if arguments == "none"
            else [
                match.group(1)
                for match in re.finditer(
                    r"(?:^|, )\*{0,2}([a-z_][a-z0-9_]*)(?=\s*(?::|=|,|$))",
                    arguments,
                )
            ]
        )
    return result


def _documented_page_create_signatures(factory_name: str) -> dict[str, str]:
    path = WIZARD_REFERENCES / f"chart-{factory_name.replace('_', '-')}.md"
    _, rows = _table(path.read_text(), "Fluent operations")
    result: dict[str, str] = {}
    for operation_cell, arguments, support in rows:
        operation = operation_cell.strip("`").split("(", 1)[0]
        if operation.startswith("client.create.") or support not in {"C", "CU"}:
            continue
        arguments = arguments.replace("`", "").strip()
        result[operation] = "" if arguments == "none" else arguments
    return result


def _public_signature(method: Any) -> str:
    result: list[str] = []
    inserted_keyword_separator = False
    for parameter in inspect.signature(method).parameters.values():
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY and not inserted_keyword_separator:
            result.append("*")
            inserted_keyword_separator = True
        prefix = ""
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            prefix = "*"
            inserted_keyword_separator = True
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            prefix = "**"
        rendered = f"{prefix}{parameter.name}"
        if parameter.annotation is not inspect.Parameter.empty:
            annotation = str(parameter.annotation).replace("WizardFieldRef", "Field")
            rendered += f": {annotation}"
        if parameter.default is not inspect.Parameter.empty:
            rendered += f" = {parameter.default!r}"
        result.append(rendered)
    return ", ".join(result)


def _canonical_signature(signature: str) -> str:
    return re.sub(
        r"Literal\[([^\]]+)\]",
        lambda match: f"Literal[{', '.join(sorted(match.group(1).split(', ')))}]",
        signature,
    )


def _surface_diff(
    actual: dict[str, set[str]],
    documented: dict[str, set[str]],
) -> dict[str, dict[str, list[str]]]:
    return {
        factory_name: {
            "undocumented": sorted(actual[factory_name] - documented[factory_name]),
            "not_generated": sorted(documented[factory_name] - actual[factory_name]),
        }
        for factory_name in actual
        if actual[factory_name] != documented[factory_name]
    }


def test_wizard_index_create_surface_matches_generated_builders() -> None:
    actual = _actual_create_methods()
    documented = _documented_index_create_methods()
    assert set(documented) == set(actual)
    assert _surface_diff(actual, documented) == {}


def test_wizard_chart_pages_create_surface_matches_generated_builders() -> None:
    actual = _actual_create_methods()
    documented = {factory_name: _documented_page_create_methods(factory_name) for factory_name in actual}
    assert _surface_diff(actual, documented) == {}


def test_wizard_chart_pages_parameter_names_match_generated_builders() -> None:
    mismatches: dict[str, dict[str, dict[str, list[str]]]] = {}
    for factory_name, builder in _actual_create_builders().items():
        documented = _documented_page_create_parameters(factory_name)
        for method_name, documented_parameters in documented.items():
            if method_name in CREATE_INFRASTRUCTURE_METHODS:
                continue
            actual_parameters = list(inspect.signature(getattr(builder, method_name)).parameters)
            if documented_parameters != actual_parameters:
                mismatches.setdefault(factory_name, {})[method_name] = {
                    "documented": documented_parameters,
                    "generated": actual_parameters,
                }
    assert mismatches == {}


def test_wizard_chart_pages_signatures_match_generated_builders() -> None:
    mismatches: dict[str, dict[str, dict[str, str]]] = {}
    for factory_name, builder in _actual_create_builders().items():
        documented = _documented_page_create_signatures(factory_name)
        for method_name, documented_signature in documented.items():
            if method_name in CREATE_INFRASTRUCTURE_METHODS:
                continue
            actual_signature = _public_signature(getattr(builder, method_name))
            if _canonical_signature(documented_signature) != _canonical_signature(actual_signature):
                mismatches.setdefault(factory_name, {})[method_name] = {
                    "documented": documented_signature,
                    "generated": actual_signature,
                }
    assert mismatches == {}


def test_wizard_references_do_not_use_removed_ph_id_parameter_name() -> None:
    references_with_ph_id = [path.name for path in WIZARD_REFERENCES.glob("*.md") if "ph_id" in path.read_text()]
    assert references_with_ph_id == []
