# Public Editor charts

This index applies only to the Yandex Cloud and Enterprise clients from
`datalens-sdk`. Confirm the requested factory in
`client.capabilities["chart_factories"]["editor"]`.

## Stable mental model

1. Select a factory for a new chart; use `chart.wire_type` for an existing
   chart. An update cannot change the renderer.
2. Editor tab setters accept complete tab sources. A setter replaces that tab;
   preserve every untouched or unknown tab.
3. Tab code runs on the server. Functions wrapped with `Editor.wrapFn` run in a
   restricted browser sandbox and cannot close over surrounding variables.
4. The generated setter matrix below is authoritative for SDK availability.
   Runtime documentation is authoritative for JavaScript formats and behavior;
   documentation cannot add a missing SDK setter.
5. Re-fetching verifies stored tab text only. Without UI or browser evidence,
   report "persisted; rendering not verified".

For a data-backed public Editor chart, `Meta` declares aliases for linked
DataLens objects, `Sources` resolves them with `Editor.getId(...)`, and
`Prepare` reads results through `Editor.getLoadedData()`. Omit `meta` only when
the chart has no linked DataLens objects. Do not copy runtime payload schemas
from this skill; follow the exact documentation sections below.

## Route the task

| Task | Read |
|---|---|
| Create a chart | its leaf in the matrix below |
| Update or publish tabs | [common-operations.md](common-operations.md), then its leaf selected by `chart.wire_type` |
| Read, rename, relate, delete, export, or diagnose | [common-operations.md](common-operations.md) |

## SDK renderer matrix

Every listed tab method accepts `str` and is available on both create and
update for that `wire_type`.

| Factory | `chart.wire_type` | Use for | SDK tab methods | Renderer leaf |
|---|---|---|---|---|
| `advanced_chart` | `advanced-chart_node` | custom HTML or SVG | `controls`, `meta`, `params`, `prepare`, `sources` | [advanced-chart.md](advanced-chart.md) |
| `gravity_charts` | `d3_node` | general charts | `config`, `controls`, `meta`, `params`, `prepare`, `sources` | [gravity-charts.md](gravity-charts.md) |
| `markdown` | `markdown_node` | formatted text | `controls`, `meta`, `params`, `prepare`, `sources` | [markdown.md](markdown.md) |
| `selector` | `control_node` | parameter controls | `controls`, `meta`, `params`, `sources` | [selector.md](selector.md) |
| `table` | `table_node` | explicit tables | `config`, `controls`, `meta`, `params`, `prepare`, `sources` | [table.md](table.md) |

Use the renderer requested by the user or identified by `chart.wire_type`.
Never translate a payload or migrate a chart to another renderer silently;
create a separate chart only with the user's agreement.

The public typed SDK has no `activities` setter. The runtime
[Activities documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#activities)
does not extend this matrix; do not invent `.activities(...)`.

## Runtime documentation router

| Need | Authoritative section |
|---|---|
| Tab order and server/browser execution | [How tabs work](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#how-tabs-works) |
| Linked object aliases | [Meta](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#meta) |
| Defaults and overrides | [Params](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#params) |
| Dataset, SQL, or API Connector data | [Sources](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources) |
| Data transformation | [Prepare](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#prepare) |
| Chart-local controls | [Controls](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#controls) |
| Read loaded data | [`Editor.getLoadedData()`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#get-loaded-data) |
| Read parameters | [`Editor.getParams()`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#get-params) |
| Browser handlers and sandbox | [`Editor.wrapFn`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#wrap) |
| Source size and execution limits | [Editor data sources](https://yandex.cloud/ru/docs/datalens/charts/editor/sources#limits) |

Editor secrets are managed outside the Editor RPC surface and have no typed
create, read, or update field. Use the DataLens UI for secret bindings.
