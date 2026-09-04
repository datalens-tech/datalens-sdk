# Public Selector

Factory: `client.create.editor_chart.selector`.
`chart.wire_type`: `control_node`.
Supported create/update tab methods: `controls(str)`, `meta(str)`,
`params(str)`, `sources(str)`. There is no `prepare` setter.

## Minimal payload

```python
from datalens_sdk import EntryLocation

EMPTY = "module.exports = {};\n"
PARAMS = "module.exports = {region: ['North']};\n"
CONTROLS = """\
module.exports = {controls: [{
    type: 'select',
    param: 'region',
    label: 'Region',
    content: ['North', 'West', 'South', 'East'].map(
        (value) => ({title: value, value})
    ),
    multiselect: false,
    searchable: false,
    width: '100%',
}]};
"""


def build_minimal(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.selector(name="Selector", location=location)
        .sources(EMPTY)
        .params(PARAMS)
        .controls(CONTROLS)
        .description("Selector Editor chart")
        .build()
    )
```

Literal values need no linked object, so this smoke test omits `meta`. Route
control variants to [Controls](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/controls#controls)
and [common fields](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/controls#common-fields).
For dataset-backed controls follow the index's Meta → Sources flow.

Every setter replaces a complete tab. Re-fetching proves persistence, not
rendering. See [_index.md](_index.md) and
[common-operations.md](common-operations.md).
