# Public Gravity UI Charts

Use this leaf only with public Yandex Cloud and Enterprise clients.

Factory: `client.create.editor_chart.gravity_charts`.
`chart.wire_type`: `d3_node`.
Supported create/update tab methods: `config(str)`, `controls(str)`,
`meta(str)`, `params(str)`, `prepare(str)`, `sources(str)`.

## Minimal payload

```python
from datalens_sdk import EntryLocation

EMPTY = "module.exports = {};\n"
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


def build_minimal(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.gravity_charts(name="Gravity", location=location)
        .sources(EMPTY)
        .params(EMPTY)
        .controls(EMPTY)
        .config(EMPTY)
        .prepare(PREPARE)
        .description("Gravity Charts Editor chart")
        .build()
    )
```

This dependency-free smoke test omits `meta`. For real option shapes use
[Prepare](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/gravity-ui#prepare)
and [Config](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/gravity-ui#config).
For linked data follow [Meta](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#meta),
[Sources](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources), and
[`Editor.getLoadedData()`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#get-loaded-data).

Every setter replaces a complete tab. Re-fetching proves persistence, not
rendering. See [_index.md](_index.md) and
[common-operations.md](common-operations.md).
