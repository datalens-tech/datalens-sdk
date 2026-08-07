from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDITOR_REFERENCE_DIR = ROOT / "skills" / "datalens-sdk" / "references" / "editor-charts"
EDITOR_INDEX = EDITOR_REFERENCE_DIR / "_index.md"
TABLE_REFERENCE = EDITOR_REFERENCE_DIR / "table.md"


def _documented_python(path: Path, marker: str) -> str:
    match = re.search(
        rf"<!-- {marker}:start -->\n```python\n(?P<source>.*?)```\n<!-- {marker}:end -->",
        path.read_text(),
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group("source")


def _execute_documented_python(path: Path, marker: str) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(_documented_python(path, marker), namespace)
    return namespace


def _decode_json_parse_expression(expression: str) -> object:
    prefix = "JSON.parse("
    assert expression.startswith(prefix)
    assert expression.endswith(")")
    document = json.loads(expression[len(prefix) : -1])
    assert isinstance(document, str)
    return json.loads(document)


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        (EDITOR_INDEX, "editor-safe-json-example"),
        (TABLE_REFERENCE, "editor-table-example"),
    ],
)
def test_documented_json_helpers_preserve_untrusted_values_as_data(path: Path, marker: str) -> None:
    namespace = _execute_documented_python(path, marker)
    helper = cast(Callable[[object], str], namespace["javascript_json_parse"])
    value = {
        "__proto__": {"polluted": True},
        "title": 'Отчёт "Продажи"\nC:\\new\\path',
        "rows": [
            {"name": "Customer's choice", "value": 1},
            {"name": '"}; globalThis.compromised = true; //', "value": 2},
        ],
    }

    expression = helper(value)

    assert expression.startswith('JSON.parse("')
    assert _decode_json_parse_expression(expression) == value


def test_documented_json_helper_rejects_non_finite_numbers() -> None:
    namespace = _execute_documented_python(EDITOR_INDEX, "editor-safe-json-example")
    helper = cast(Callable[[object], str], namespace["javascript_json_parse"])

    with pytest.raises(ValueError, match="Out of range float values"):
        helper(float("nan"))


def test_documented_table_example_has_valid_export_shape() -> None:
    namespace = _execute_documented_python(TABLE_REFERENCE, "editor-table-example")
    prepare = cast(str, namespace["PREPARE"])

    assert "module.exports = {head, rows, footer: []};" in prepare
    for name in ("head", "rows"):
        match = re.search(rf"^const {name} = (?P<expression>JSON\.parse\(.+\));$", prepare, flags=re.MULTILINE)
        assert match is not None
        assert _decode_json_parse_expression(match.group("expression")) == namespace[name.upper()]
