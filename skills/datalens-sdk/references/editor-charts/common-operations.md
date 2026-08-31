# Public Editor chart operations

Read [the public Editor index](_index.md) first. Runtime payload formats belong
to the linked official documentation; this file covers the SDK lifecycle.

## Create and read

Create through `client.create.editor_chart.<factory>(name=..., location=...)`,
set only tabs supported by the selected matrix row, optionally add
`.description(...)`, and finish with `.build()`. Public clients accept
`EntryLocation.path(...)` or `EntryLocation.workbook(...)`.

Start from that renderer leaf's minimal payload. DTO requiredness does not
define a renderer-safe default: a missing required tab may serialize as an
empty string, so set every tab that needs non-empty or format-specific content
explicitly.

Fetch one intended version at a time:

```python
chart = client.get.editor_chart(
    by_id=chart_id,
    workbook_id=workbook_id,  # omit for a path-based chart
    branch="saved",  # or "published"; alternatively use rev_id=
)
```

Prefer `client.get.editor_chart` when the category is known;
`client.get.chart(...)` returns `WizardChart | EditorChart | QLChart`. If both
`rev_id` and `branch` are passed, `rev_id` wins and the client emits
`UserWarning`.

Useful state is `chart.id`, `name`, `location`, `description`,
`category == "editor"`, `wire_type`, `data`, `response_snapshot`, and
`update`. `chart.data` is a
`Mapping[str, object]` whose values are usually complete stored tab-source
strings; a nullable, redacted, or omitted tab may be `None` or absent. Editor
charts have no Wizard/QL `visualization_id`.

## Update and publish

Fetch the saved branch, confirm `wire_type`, and use only setters from that
renderer's matrix row. Every setter replaces one complete tab. Untouched tabs
remain preserved.

```python
def update_prepare(
    client,
    *,
    chart_id: str,
    workbook_id: str | None,
    prepare_source: str,
    publish: bool = False,
):
    saved = client.get.editor_chart(
        by_id=chart_id,
        workbook_id=workbook_id,
        branch="saved",
    )
    return saved.update.prepare(prepare_source).mode("publish" if publish else "save").execute()
```

Use `prepare` only for a renderer whose matrix row exposes it; the same pattern
applies to every documented tab setter.

Update defaults to `save`; publish only when requested. Re-fetch the selected
branch and compare the intended stored values. Never repeat a successful write
because later verification code failed.

## Rename, relations, and delete

- Rename: `client.get.editor_chart(...).rename(new_name)`.
- Relations: `chart.get_relations(...)` returns a lazy pager; consume it only
  with permission to handle the result. Arguments include
  `include_permissions_info`, `link_direction`, `page_size`, and `scope`.
  `link_direction` is `"from" | "to"`; `scope` is `"dash" | "report" |
  "widget" | "dataset" | "folder" | "connection"`; `page_size` defaults to
  `100`.
- Delete only after explicit confirmation: fetch the exact chart, then call
  `chart.delete()`; deletion is immediate.

## Export, import, and clone

`chart.to_file(path, split_tabs=True)` writes review-friendly tab files, but
only `chart.json` is importable. Typed tab updates remain the safe default.
Creating through `client.raw.create.editor_chart` or preparing
`client.raw.replace.editor_chart` uses full snapshots; read
[../serialization.md](../serialization.md), and obtain explicit approval before
constructing any raw replace builder.

## Persisted but not rendered

`ERR.CHARTS.INVALID_SOURCE_FORMAT` is a deterministic tab-format failure, not
a transient API error: fix the source instead of retrying. Public `Meta` is
JSON text; ordinary code tabs are JavaScript and must export the value expected
by the renderer. An empty string and `module.exports = {};` are not
interchangeable—start from that renderer leaf's minimal payload.

1. Re-fetch the same saved or published branch.
2. Confirm `wire_type` and compare only the intended changed tabs.
3. Check the selected runtime documentation for export shape and sandbox rules.
4. Preserve unknown tabs and diagnose one tab at a time in save mode.
5. Without UI/browser execution evidence, report "persisted; rendering not
   verified".

Runtime errors are visible in the Editor Console. `console.log(...)` in code
wrapped with `Editor.wrapFn` appears in the browser console; see
[Editor debugging](https://yandex.cloud/ru/docs/datalens/charts/editor/debug).

Editor secrets are outside the typed RPC surface and must be managed in the UI.

## Related SDK references

- [Core concepts](../core-concepts.md) — terminal calls, verification, retries,
  and pagination
- [Parameters](../parameters.md) — keys exported from the Editor `params` tab
  and their dashboard, widget, selector, URL, and action scopes
- [Navigation](../navigation.md) — relation objects and dependency direction
- [Serialization](../serialization.md) — complete snapshot import and replace
- [Troubleshooting](../troubleshooting.md) — generic API failures
