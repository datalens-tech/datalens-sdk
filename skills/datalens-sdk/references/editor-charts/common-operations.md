# Editor Chart Common Operations

The lifecycle shared by public Editor renderers on Yandex Cloud and Enterprise.
Examples use clients and domain types from `datalens-sdk`. For client
construction, see [../setup.md](../setup.md). Check
[the public Editor index](_index.md) before creating. Treat every tab value as
the complete replacement source for that tab.

## Create

Every factory starts with the same entry arguments and ends with `.build()`:

```python
from datalens_sdk import EntryLocation


def build_chart(client, *, location: EntryLocation):
    return (
        client.create.editor_chart.markdown(
            name="SDK Markdown",
            location=location,
        )
        .sources("module.exports = {};\n")
        .params("module.exports = {};\n")
        .controls("module.exports = {};\n")
        .prepare("module.exports = {markdown: '# Hello from Editor'};\n")
        .description("Created with datalens_sdk")
        .build()
    )
```

Pass either `EntryLocation.path("/Charts")` or
`EntryLocation.workbook("workbook-id")`, according to the destination used
by the configured client.

Use the renderer-specific references for complete working tab
content. DTO requiredness does not define a renderer-safe default: a missing
required tab may be serialized as an empty string, so set every tab that
needs non-empty or format-specific content explicitly.

Dashboard widget/global params and manual selectors address Editor parameters
by the keys exported from the `params` tab. See
[../parameters.md](../parameters.md) for scope, precedence, and the static
validation boundary.

## Read

```python
def read_chart_versions(client, *, chart_id: str, workbook_id: str | None):
    saved = client.get.editor_chart(
        by_id=chart_id,
        workbook_id=workbook_id,
        branch="saved",
    )
    published = client.get.editor_chart(
        by_id=chart_id,
        workbook_id=workbook_id,
        branch="published",
    )
    revision = client.get.editor_chart(
        by_id=chart_id,
        workbook_id=workbook_id,
        rev_id="revision-id",
    )
    generic = client.get.chart(by_id=chart_id, workbook_id=workbook_id)
    return saved, published, revision, generic
```

Omit `workbook_id` when the chart is path-based. Prefer
`client.get.editor_chart` when the category is known. `branch` accepts
`"saved"` or `"published"`. When both `rev_id` and `branch` are passed,
`rev_id` takes precedence and the client emits a `UserWarning`.

Useful public state:

- `chart.id`, `chart.name`, `chart.location`, and `chart.description`;
- `chart.category == "editor"`;
- `chart.wire_type`, which identifies the renderer; map it to the factory in
  [the public Editor index](_index.md). Editor charts do not expose a
  Wizard/QL-style `visualization_id`;
- `chart.data`, a `Mapping[str, object]` whose tab values are usually source
  strings; nullable, redacted, or omitted tabs may be `None` or absent;
- `chart.update`, which starts a fluent update.

## Update and Publish

Fetch the saved branch before editing. Each setter replaces the complete
tab:

```python
def update_prepare(client, *, chart_id: str, workbook_id: str | None, prepare_source: str):
    saved = client.get.editor_chart(
        by_id=chart_id,
        workbook_id=workbook_id,
        branch="saved",
    )
    return saved.update.prepare(prepare_source).description("Updated with datalens_sdk").mode("publish").execute()
```

Update defaults to `.mode("save")`. Use `.mode("publish")` only when the
result must be published. Use only the tab methods listed for the current
renderer in [the public Editor index](_index.md). A successful `.execute()`
confirms persistence, not JavaScript execution. Re-fetch the desired branch
after `.execute()` before checking persisted tab content. Untouched tabs remain
preserved; do not resend or reconstruct them. A setter replaces only the
complete source of the tab it targets.

Editor secrets are managed outside the Editor RPC surface. The SDK exposes no
create, read, or update field for them; use the DataLens UI for secret bindings.
For compatibility with legacy snapshots and unexpected backend drift, the SDK
still discards an unknown `data.secrets` block before domain or raw state.

## Rename

```python
def rename_chart(client, *, chart_id: str, workbook_id: str | None, new_name: str):
    chart = client.get.editor_chart(by_id=chart_id, workbook_id=workbook_id)
    return chart.rename(new_name)
```

## Relations

```python
def dashboard_relations(chart):
    return chart.get_relations(
        include_permissions_info=True,
        link_direction="to",
        page_size=100,
        scope="dash",
    )
```

`get_relations()` is lazy. Iterate it or call `.pages()` only when the user has
requested or permitted handling the returned relation data. Its optional
arguments are `include_permissions_info`, `link_direction` (`"from"` or
`"to"`), `page_size` (default `100`), and `scope` (`"dash"`, `"report"`,
`"widget"`, `"dataset"`, `"folder"`, or `"connection"`).

## Delete

Deletion is immediate. Obtain explicit confirmation for the exact chart before
running a delete call. After that confirmation:

```python
def delete_confirmed_chart(client, *, chart_id: str, workbook_id: str | None):
    chart = client.get.editor_chart(by_id=chart_id, workbook_id=workbook_id)
    chart.delete()
```

## Related references

- [_index.md](_index.md) — public renderer routing and tab methods
- [troubleshooting.md](troubleshooting.md) — a chart persists but does not render
- [../core-concepts.md](../core-concepts.md) — namespaces, terminal calls, retries
- [../serialization.md](../serialization.md) — export/clone via `to_file` and `client.raw`
