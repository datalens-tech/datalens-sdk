# Markdown

Factory: `client.create.editor_chart.markdown`. `chart.wire_type`:
`markdown_node`.

Tabs: `controls`, `meta`, `params`, `prepare`, `sources`.

`prepare` must export an object containing `markdown`, not a bare string.

```python
from datalens_sdk import EntryLocation

SOURCES = "module.exports = {};\n"
PARAMS = "module.exports = {};\n"
CONTROLS = "module.exports = {};\n"
PREPARE = """\
const markdown = `
# Markdown created with datalens_sdk

Working **bold**, _italics_, and a table:

Type | Status
:--- | :---
Editor | Ready
`;

module.exports = {markdown};
"""


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.markdown(
            name="SDK Markdown",
            location=location,
        )
        .sources(SOURCES)
        .params(PARAMS)
        .controls(CONTROLS)
        .prepare(PREPARE)
        .description("Markdown Editor chart")
        .build()
    )
```

Leave `meta` unset.

## Related references

- [_index.md](_index.md) — routing, exact tab matrix
- [common-operations.md](common-operations.md) — read, update, publish, delete
- [troubleshooting.md](troubleshooting.md) — chart persists but does not render
- [Official Markdown documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/markdown)
