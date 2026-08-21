# Editor Charts

Routing for hand-written JavaScript (Editor) charts. Read
this index first, then exactly the one renderer file the task needs. The
lifecycle shared by every renderer (create, read, update, publish, rename,
relations, delete) lives in [common-operations.md](common-operations.md).

## Classify the task before loading renderer details

| Task | Read |
|---|---|
| Inspect, rename, relate, or delete an editor chart | [common-operations.md](common-operations.md) only |
| Create a new editor chart | the renderer file chosen below, plus the tab matrix in this index |
| Update tabs or publish | fetch the chart, map `chart.wire_type` to its factory in the routing table, then read that renderer file |
| Chart persists but fails to render | that renderer file plus [troubleshooting.md](troubleshooting.md) |

For create, copy the renderer file's complete
`build_chart(client, location=...)` example and adapt the tab contents. A
successful `.build()` or `.execute()` confirms persistence, not JavaScript
execution — re-fetch the intended branch and verify the stored tabs before
reporting done.

## Available renderers

The public SDK exposes **five** renderer factories on
`client.create.editor_chart`:

`advanced_chart`, `gravity_charts`, `markdown`, `selector`, `table`

Before routing, read
`client.capabilities["chart_factories"]["editor"]` and confirm the requested
renderer is present. That generated list is authoritative for the configured
client; if a renderer is absent, report it as unavailable rather than inventing
a factory. For general charting, `gravity_charts` covers most needs.

## Renderer routing

| Factory | `chart.wire_type` | Use when the requested output is | Reference |
|---|---|---|---|
| `advanced_chart` | `advanced-chart_node` | custom HTML or arbitrary wrapped rendering logic | [advanced-chart.md](advanced-chart.md) |
| `gravity_charts` | `d3_node` | a general chart using Gravity Charts configuration | [gravity-charts.md](gravity-charts.md) |
| `markdown` | `markdown_node` | Markdown-formatted text and tables | [markdown.md](markdown.md) |
| `selector` | `control_node` | an interactive parameter control | [selector.md](selector.md) |
| `table` | `table_node` | explicit table headers, rows, and footer | [table.md](table.md) |

When several general chart renderers could work, follow the renderer named
by the user or the existing chart's `wire_type`. Do not silently translate
one renderer's JavaScript contract into another. Editor charts identify
their renderer through `chart.wire_type`; they do not expose a
Wizard/QL-style `visualization_id`.

## Exact tab matrix

Every listed tab is available on the corresponding create factory.
Every tab setter accepts `str`.

| Factory | `chart.wire_type` | Create tabs |
|---|---|---|
| `advanced_chart` | `advanced-chart_node` | `controls`, `meta`, `params`, `prepare`, `sources` |
| `gravity_charts` | `d3_node` | `config`, `controls`, `meta`, `params`, `prepare`, `sources` |
| `markdown` | `markdown_node` | `controls`, `meta`, `params`, `prepare`, `sources` |
| `selector` | `control_node` | `controls`, `meta`, `params`, `sources` |
| `table` | `table_node` | `config`, `controls`, `meta`, `params`, `prepare`, `sources` |

There is no `shared`, `activities`, or `secrets` tab. Leave
`meta` unset: the setter exists, but its content format is not verified.

Code tabs contain JavaScript with
`module.exports`; the exact export shape is renderer-specific and shown in
each reference. Treat the renderer references as minimum working examples,
not complete documentation for every optional tab.

## Shared builder signatures

All create factories expose:

```text
client.create.editor_chart.<factory>(*, name: str, location: EntryLocation)
.description(text: str)
.build()
```

All Editor updates go through the generic `EditorChartUpdate`:

```text
chart.update.<tab>(value)
.description(text: str)
.mode("save" | "publish")   # default "save"
.execute()
```

`EditorChartUpdate` exposes setters for writable tabs, including some used by
no renderer in the routing table. It intentionally has no `secrets()` setter:
API v3 treats Editor secrets as UI-managed, read-only state.
Use only the tabs in the row for the chart's current renderer.
`EditorChartUpdate.meta()` exists (as does `.meta()` on the create
builders) but should not be called — its content format is not verified. To
change a chart's renderer, create a separate chart; the renderer is fixed at
create time.

## Related references

- [common-operations.md](common-operations.md) — the full editor chart lifecycle
- [troubleshooting.md](troubleshooting.md) — `ERR.CHARTS.INVALID_SOURCE_FORMAT` and render failures
- [../setup.md](../setup.md) — clients, installations, auth
- [../core-concepts.md](../core-concepts.md) — namespaces, builders, terminal calls
- [../serialization.md](../serialization.md) — export/import via `to_file` and `client.raw`
