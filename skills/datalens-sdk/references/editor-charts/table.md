# Table

Factory: `client.create.editor_chart.table`. `chart.wire_type`:
`table_node`.

Tabs: `config`, `controls`, `meta`, `params`, `prepare`, `sources`.

`prepare` exports `{head, rows, footer}`.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
CONFIG = """\
module.exports = {
    title: {text: 'Table created with datalens_sdk'},
    size: 'l',
};
"""
PREPARE = """\
const head = [
    {id: 'name', name: 'Name', type: 'text'},
    {id: 'value', name: 'Value', type: 'number'},
];
const rows = [
    {cells: [{value: 'A'}, {value: 1}]},
    {cells: [{value: 'B'}, {value: 2}]},
];

module.exports = {head, rows, footer: []};
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

Leave `meta` unset.

## Related references

- [_index.md](_index.md) — routing, exact tab matrix
- [common-operations.md](common-operations.md) — read, update, publish, delete
- [troubleshooting.md](troubleshooting.md) — chart persists but does not render
- [Official Table documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/table)
