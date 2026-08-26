# Public Selector

This reference applies only to public Yandex Cloud and Enterprise clients from
`datalens-sdk`.

Factory: `client.create.editor_chart.selector`.
`chart.wire_type`: `control_node`.
Supported create/update tab methods: `controls(str)`, `meta(str)`,
`params(str)`, `sources(str)`. There is no `prepare` method for this renderer.

`sources` exports the data-source definitions used by controls; an empty object
is valid when the selector uses literal values. `params` exports the initial
parameter values. `controls` exports an object whose `controls` member is an
array of control definitions.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {region: ['North']};\n"
CONTROLS = """\
module.exports = {
    controls: [{
        type: 'select',
        param: 'region',
        label: 'Region',
        content: ['North', 'West', 'South', 'East'].map(
            (value) => ({title: value, value})
        ),
        multiselect: false,
        searchable: false,
        width: '100%',
    }],
};
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.selector(name="SDK Selector", location=location)
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .description("Selector Editor chart")
        .build()
    )
```

Leave `meta` unset. Re-fetch the intended branch and verify `sources`, `params`,
and `controls`.

## Related references

- [_index.md](_index.md) — public renderer routing and supported tab methods
- [common-operations.md](common-operations.md) — lifecycle operations
- [troubleshooting.md](troubleshooting.md) — persistence and render failures
- [Controls documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/controls)
