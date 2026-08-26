# Public Gravity Charts

This reference applies only to public Yandex Cloud and Enterprise clients from
`datalens-sdk`.

Factory: `client.create.editor_chart.gravity_charts`.
`chart.wire_type`: `d3_node`.
Supported create/update tab methods: `config(str)`, `controls(str)`,
`meta(str)`, `params(str)`, `prepare(str)`, `sources(str)`.

`prepare` exports the complete Gravity Charts configuration:

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
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
    xAxis: {type: 'category', categories: ['Apples', 'Oranges', 'Grapes']},
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
        .controls(CONTROLS)
        .config(CONFIG)
        .prepare(PREPARE)
        .description("Gravity Charts Editor chart")
        .build()
    )
```

Leave `meta` unset. Re-fetch the intended branch and verify the stored tab
strings before checking rendering in DataLens.

## Related references

- [_index.md](_index.md) — public renderer routing and supported tab methods
- [common-operations.md](common-operations.md) — lifecycle operations
- [troubleshooting.md](troubleshooting.md) — persistence and render failures
- [Gravity UI Charts documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/gravity-ui)
