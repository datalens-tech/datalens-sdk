# Public Table

This reference applies only to public Yandex Cloud and Enterprise clients from
`datalens-sdk`.

Factory: `client.create.editor_chart.table`.
`chart.wire_type`: `table_node`.
Supported create/update tab methods: `config(str)`, `controls(str)`,
`meta(str)`, `params(str)`, `prepare(str)`, `sources(str)`.

`prepare` exports `{head, rows, footer}`:

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
        client.create.editor_chart.table(name="SDK Table", location=location)
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .config(CONFIG)
        .prepare(PREPARE)
        .description("Table Editor chart")
        .build()
    )
```

Leave `meta` unset. Re-fetch the intended branch and verify the stored tab
strings before checking rendering in DataLens.

## Related references

- [_index.md](_index.md) — public renderer routing and supported tab methods
- [common-operations.md](common-operations.md) — lifecycle operations
- [troubleshooting.md](troubleshooting.md) — persistence and render failures
- [Table documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/table)
