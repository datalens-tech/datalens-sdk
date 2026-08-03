# Advanced Chart

Factory: `client.create.editor_chart.advanced_chart`. `chart.wire_type`:
`advanced-chart_node`.

Tabs: `controls`, `meta`, `params`, `prepare`, `sources`.

`prepare` must export an object whose `render` member is an
`Editor.wrapFn(...)` result.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
PARAMS = "module.exports = {backgroundColor: 'var(--g-color-base-info-light)'};\n"
PREPARE = """\
const params = Editor.getParams();
const background =
    params.backgroundColor?.[0] ?? 'var(--g-color-base-info-light)';

module.exports = {
    render: Editor.wrapFn({
        fn: function(config) {
            return `<div style="padding:24px;background:${config.background};font-size:24px">`
                + 'Advanced chart created with datalens_sdk'
                + '</div>';
        },
        args: [{background}],
    }),
};
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.advanced_chart(
            name="SDK Advanced chart",
            location=location,
        )
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .prepare(PREPARE)
        .description("Advanced Editor chart")
        .build()
    )
```

Leave `meta` unset.

## Related references

- [_index.md](_index.md) — routing, exact tab matrix
- [common-operations.md](common-operations.md) — read, update, publish, delete
- [troubleshooting.md](troubleshooting.md) — chart persists but does not render
