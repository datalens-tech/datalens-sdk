# Public Advanced chart

This reference applies only to public Yandex Cloud and Enterprise clients from
`datalens-sdk`.

Factory: `client.create.editor_chart.advanced_chart`.
`chart.wire_type`: `advanced-chart_node`.
Supported create/update tab methods: `controls(str)`, `meta(str)`,
`params(str)`, `prepare(str)`, `sources(str)`.

`prepare` exports an object whose `render` member is an `Editor.wrapFn(...)`
result. Return HTML or SVG through `Editor.generateHtml(...)`; a raw string is
escaped. The built-in `options` argument comes first, followed by `args`.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
PARAMS = "module.exports = {backgroundColor: ['var(--g-color-base-info-light)']};\n"
PREPARE = """\
const params = Editor.getParams();
const background = params.backgroundColor?.[0] ?? 'var(--g-color-base-info-light)';

module.exports = {
    render: Editor.wrapFn({
        fn: function(options, config) {
            return Editor.generateHtml(
                `<div style="padding:24px;background:${config.background};font-size:24px">`
                    + 'Advanced chart created with datalens_sdk'
                    + '</div>',
            );
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

Leave `meta` unset. Re-fetch the intended branch and verify the stored
`sources`, `params`, `controls`, and `prepare` strings.

## Related references

- [_index.md](_index.md) — public renderer routing and supported tab methods
- [common-operations.md](common-operations.md) — lifecycle operations
- [troubleshooting.md](troubleshooting.md) — persistence and render failures
- [Advanced chart documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced)
