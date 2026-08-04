# Gravity Charts

Factory: `client.create.editor_chart.gravity_charts`. `chart.wire_type`:
`d3_node`.

Tabs: `config`, `controls`, `meta`, `params`, `prepare`, `sources`.

`prepare` exports the complete Gravity Charts configuration.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {};\n"
CONFIG = "module.exports = {};\n"
PREPARE = """\
module.exports = {
    chart: {margin: {left: 10, right: 10, top: 10, bottom: 10}},
    series: {
        data: [{
            type: 'bar-x',
            name: 'Fruits',
            data: [{x: 0, y: 3}, {x: 1, y: 1}, {x: 2, y: 2}],
        }],
    },
    title: {text: 'Gravity Charts created with datalens_sdk'},
    xAxis: {
        type: 'category',
        categories: ['Apples', 'Oranges', 'Grapes'],
    },
    yAxis: [{title: {text: 'Value'}}],
};
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.gravity_charts(
            name="SDK Gravity Charts",
            location=location,
        )
        .sources(SOURCES)
        .params(PARAMS)
        .config(CONFIG)
        .prepare(PREPARE)
        .description("Gravity Charts Editor chart")
        .build()
    )
```

Leave `meta` unset.

## Related references

- [_index.md](_index.md) — routing, exact tab matrix
- [common-operations.md](common-operations.md) — read, update, publish, delete
- [troubleshooting.md](troubleshooting.md) — chart persists but does not render
