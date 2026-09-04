# Public Markdown

Factory: `client.create.editor_chart.markdown`.
`chart.wire_type`: `markdown_node`.
Supported create/update tab methods: `controls(str)`, `meta(str)`,
`params(str)`, `prepare(str)`, `sources(str)`.

## Minimal payload

```python
from datalens_sdk import EntryLocation

EMPTY = "module.exports = {};\n"
PREPARE = """\
const markdown = `
# Markdown created with datalens_sdk

Type | Status
:--- | :---
Editor | Ready
`;

module.exports = {markdown};
"""


def build_minimal(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.markdown(name="Markdown", location=location)
        .sources(EMPTY)
        .params(EMPTY)
        .controls(EMPTY)
        .prepare(PREPARE)
        .description("Markdown Editor chart")
        .build()
    )
```

`prepare` exports an object containing `markdown`, not a bare string. This
dependency-free smoke test omits `meta`. See the authoritative
[Prepare contract](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/markdown#prepare);
for linked data follow the index's Meta → Sources flow.

Every setter replaces a complete tab. Re-fetching proves persistence, not
rendering. See [_index.md](_index.md) and
[common-operations.md](common-operations.md).
