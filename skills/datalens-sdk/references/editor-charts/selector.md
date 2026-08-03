# Selector

Factory: `client.create.editor_chart.selector`. `chart.wire_type`:
`control_node`.

Tabs: `controls`, `meta`, `params`, `sources`. There is no `prepare` tab on
this renderer.

`controls` must export an array of control definitions. The selected values
live in the object exported by `params`.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {region: ['North']};\n"
CONTROLS = """\
module.exports = [{
    type: 'select',
    param: 'region',
    label: 'Region',
    content: ['North', 'West', 'South', 'East'].map(
        (value) => ({title: value, value})
    ),
    multiselect: false,
    searchable: false,
    width: '100%',
}];
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.selector(
            name="SDK Selector",
            location=location,
        )
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .description("Selector Editor chart")
        .build()
    )
```

Leave `meta` unset.

## Related references

- [_index.md](_index.md) — routing, exact tab matrix
- [common-operations.md](common-operations.md) — read, update, publish, delete
- [troubleshooting.md](troubleshooting.md) — chart persists but does not render
