from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EDITOR_INDEX = ROOT / "skills" / "datalens-sdk" / "references" / "editor-charts" / "_index.md"


def _build_editor_source(*, title: str, rows: list[dict[str, object]]) -> str:
    title_literal = json.dumps(title, ensure_ascii=False)
    rows_literal = json.dumps(rows, ensure_ascii=False)
    return f"""\
const title = {title_literal};
const rows = {rows_literal};

module.exports = {{
    title: {{text: title}},
    rows,
}};
"""


def _read_literal(source: str, name: str) -> object:
    match = re.search(rf"^const {name} = (.+);$", source, flags=re.MULTILINE)
    assert match is not None
    return json.loads(match.group(1))


def test_editor_json_literal_pattern_keeps_untrusted_values_as_data() -> None:
    title = 'Отчёт "Продажи"\nC:\\new\\path'
    rows: list[dict[str, object]] = [
        {"name": "Customer's choice", "value": 1},
        {"name": '"}; globalThis.compromised = true; //', "value": 2},
    ]

    source = _build_editor_source(title=title, rows=rows)

    assert _read_literal(source, "title") == title
    assert _read_literal(source, "rows") == rows
    assert "json.dumps(..., ensure_ascii=False)" in EDITOR_INDEX.read_text()
