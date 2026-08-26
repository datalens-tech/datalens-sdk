# Public Markdown

This reference applies only to public Yandex Cloud and Enterprise clients from
`datalens-sdk`.

Factory: `client.create.editor_chart.markdown`.
`chart.wire_type`: `markdown_node`.
Supported create/update tab methods: `controls(str)`, `meta(str)`,
`params(str)`, `prepare(str)`, `sources(str)`.

`prepare` exports an object containing `markdown`, not a bare string:

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
PREPARE = """\
const markdown = `
# Markdown created with datalens_sdk

Type | Status
:--- | :---
Editor | Ready
`;

module.exports = {markdown};
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.markdown(name="SDK Markdown", location=location)
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .prepare(PREPARE)
        .description("Markdown Editor chart")
        .build()
    )
```

Leave `meta` unset. Re-fetch the intended branch and verify the stored tab
strings before checking rendering in DataLens.

## Related references

- [_index.md](_index.md) — public renderer routing and supported tab methods
- [common-operations.md](common-operations.md) — lifecycle operations
- [troubleshooting.md](troubleshooting.md) — persistence and render failures
- [Markdown documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/markdown)
