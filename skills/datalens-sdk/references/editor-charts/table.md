# Public Table

Use this leaf only with public Yandex Cloud and Enterprise clients.

Factory: `client.create.editor_chart.table`.
`chart.wire_type`: `table_node`.
Supported create/update tab methods: `config(str)`, `controls(str)`,
`meta(str)`, `params(str)`, `prepare(str)`, `sources(str)`.

## Minimal payload

```python
from datalens_sdk import EntryLocation

EMPTY = "module.exports = {};\n"
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


def build_minimal(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.table(name="Table", location=location)
        .sources(EMPTY)
        .params(EMPTY)
        .controls(EMPTY)
        .config(CONFIG)
        .prepare(PREPARE)
        .description("Table Editor chart")
        .build()
    )
```

This dependency-free smoke test omits `meta`. Route column and row variants to
[Prepare](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/table#prepare)
and display options to [Config](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/table#config).
For linked data follow [Meta](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#meta)
and [Sources](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources).

Every setter replaces a complete tab. Re-fetching proves persistence, not
rendering. See [_index.md](_index.md) and
[common-operations.md](common-operations.md).
