# Public Editor charts

This index applies only to the Yandex Cloud and Enterprise clients provided by
the public `datalens-sdk` package. Read it first, then open exactly one renderer
reference. Confirm the factory in
`client.capabilities["chart_factories"]["editor"]` before using it.

## Route the task

| Task | Read |
|---|---|
| Inspect, rename, relate, or delete an Editor chart | [common-operations.md](common-operations.md) |
| Create an Editor chart | the selected renderer reference below |
| Update or publish an Editor chart | fetch it, select the renderer by `chart.wire_type`, then read that renderer reference |
| The chart persists but does not render | the renderer reference and [troubleshooting.md](troubleshooting.md) |

Use the renderer requested by the user or already identified by
`chart.wire_type`. Do not silently translate a payload between renderers. A
successful `.build()` or `.execute()` proves persistence, not JavaScript
execution; re-fetch the intended branch and verify the stored tabs.

## Public runtime documentation

These pages define JavaScript formats and runtime behavior. They do not add a
factory or tab method to the installed SDK.

| Contract | Official documentation |
|---|---|
| Tab execution and exports | [Editor tabs](https://yandex.cloud/ru/docs/datalens/charts/editor/tabs) |
| `Editor.*` methods and `Editor.wrapFn` | [Available Editor methods](https://yandex.cloud/ru/docs/datalens/charts/editor/methods) |
| Advanced chart | [Advanced chart](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/advanced) |
| Gravity UI Charts | [Gravity UI Charts](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/gravity-ui) |
| Selector | [Controls](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/controls) |
| Markdown | [Markdown](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/markdown) |
| Table | [Table](https://yandex.cloud/ru/docs/datalens/charts/editor/widgets/table) |

Tab code runs on the server. Functions wrapped with `Editor.wrapFn` run in a
restricted client-side sandbox. Wrapped functions cannot close over surrounding
variables; pass the smallest serializable values they need through `args`.

## Renderer routing and supported tab methods

The same tab row applies to create and update for that `wire_type`. Every tab
method below accepts `str`.

| Factory | `chart.wire_type` | Use for | Supported tab methods | Reference |
|---|---|---|---|---|
| `advanced_chart` | `advanced-chart_node` | custom HTML or wrapped rendering | `controls`, `meta`, `params`, `prepare`, `sources` | [advanced-chart.md](advanced-chart.md) |
| `gravity_charts` | `d3_node` | general Gravity Charts configuration | `config`, `controls`, `meta`, `params`, `prepare`, `sources` | [gravity-charts.md](gravity-charts.md) |
| `markdown` | `markdown_node` | Markdown text and tables | `controls`, `meta`, `params`, `prepare`, `sources` | [markdown.md](markdown.md) |
| `selector` | `control_node` | parameter controls | `controls`, `meta`, `params`, `sources` | [selector.md](selector.md) |
| `table` | `table_node` | explicit table output | `config`, `controls`, `meta`, `params`, `prepare`, `sources` | [table.md](table.md) |

The recipes leave `meta` unset because no non-empty public payload is verified;
the converter supplies the required empty value. Do not call tab methods
outside the selected row. Editor `secrets` is read-only server state and has no
create or update method.

## Shared operations

Create factories use keyword-only `name` and `location`, and support
`.description(text: str)` followed by `.build()`. Fetch with
`client.get.editor_chart(by_id=..., workbook_id=..., branch="saved" | "published",
rev_id=...)`. Update through `chart.update`, optionally set
`.description(text: str)` and `.mode("save" | "publish")`, then call
`.execute()`. The renderer cannot be changed by an update.
