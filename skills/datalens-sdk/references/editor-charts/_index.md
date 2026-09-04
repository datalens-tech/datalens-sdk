# Public Editor charts

Confirm the requested factory in
`client.capabilities["chart_factories"]["editor"]`.

## Stable mental model

1. Select a factory for a new chart; use `chart.wire_type` for an existing
   chart. An update cannot change the renderer.
2. Editor tab setters accept complete tab sources. A setter replaces that tab;
   preserve every untouched or unknown tab.
3. Tab code runs on the server. Functions wrapped with `Editor.wrapFn` run in a
   restricted browser sandbox and cannot close over surrounding variables.
4. Runtime documentation is authoritative for whether a tab is supported by
   the selected renderer and for its JavaScript format and behavior. The
   generated setter matrix below is authoritative for what the installed typed
   SDK can currently write. A documented tab missing from this matrix is not
   implemented in the SDK yet; report that limitation instead of inventing a
   setter or a raw request.
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

The public runtime
[Activities documentation](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#activities)
currently supports Activities for Selector, Table, and Gravity UI Charts. The
generated public create and update contracts do not expose that tab yet. The
shared `EditorChartUpdate` object has an `activities(...)` method because the
domain model is also used by other installations, but public generated DTOs
reject the field; treat that method as unavailable for public clients. Typed
public Activities support will be added in a future SDK version. Until then,
do not call the method or work around the limitation with a raw request. If an
existing chart already contains Activities, leave it unchanged; if the typed
SDK cannot preserve it during another update, stop and report the limitation.

## Runtime documentation router

| Need | Authoritative section |
|---|---|
| Tab order and server/browser execution | [Editor tabs](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs) |
| Linked object aliases | [Meta](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#meta) |
| Defaults and overrides | [Params](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#params) |
| Dataset, SQL, or API Connector data | [Sources](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#sources) |
| Data transformation | [Prepare](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#prepare) |
| Chart-local controls | [Controls](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#controls) |
| Activities for Selector, Table, and Gravity UI Charts | [Activities](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs#activities) |
| Read loaded data | [`Editor.getLoadedData()`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#get-loaded-data) |
| Read parameters | [`Editor.getParams()`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#get-params) |
| Browser handlers and sandbox | [`Editor.wrapFn`](https://yandex.cloud/ru/docs/datalens/charts/editor/methods#wrap) |
| Source size and execution limits | [Editor data sources](https://yandex.cloud/ru/docs/datalens/charts/editor/sources#limits) |

Public Editor charts have no typed create, read, or update `secrets` field.
Manage secret bindings in the DataLens UI.
