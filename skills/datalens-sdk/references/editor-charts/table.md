# Table

Factory: `client.create.editor_chart.table`. `chart.wire_type`:
`table_node`.

Tabs: `config`, `controls`, `meta`, `params`, `prepare`, `sources`.

`prepare` exports `{head, rows, footer}`.

## Dynamic values

Use the safe serialization pattern from
[_index.md](./_index.md#safely-embed-dynamic-values) without changing the
renderer-specific export shape.

<!-- editor-table-example:start -->
```python
import json

from datalens_sdk import EntryLocation


def javascript_json_parse(value: object) -> str:
    document = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return f"JSON.parse({json.dumps(document)})"


SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
CONFIG = """\
module.exports = {
    title: {text: 'Table created with datalens_sdk'},
    size: 'l',
};
"""
HEAD = [
    {"id": "name", "name": "Name", "type": "text"},
    {"id": "value", "name": "Value", "type": "number"},
]
ROWS = [
    {"cells": [{"value": "A"}, {"value": 1}]},
    {"cells": [{"value": "B"}, {"value": 2}]},
]
PREPARE = f"""\
const head = {javascript_json_parse(HEAD)};
const rows = {javascript_json_parse(ROWS)};

module.exports = {{head, rows, footer: []}};
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.table(
            name="SDK Table",
            location=location,
        )
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .config(CONFIG)
        .prepare(PREPARE)
        .description("Table Editor chart")
        .build()
    )
```
<!-- editor-table-example:end -->

Leave `meta` unset.

## Related references

- [_index.md#safely-embed-dynamic-values](_index.md#safely-embed-dynamic-values) — safe dynamic values
- [common-operations.md](common-operations.md) — read, update, publish, delete
- [troubleshooting.md](troubleshooting.md) — chart persists but does not render
