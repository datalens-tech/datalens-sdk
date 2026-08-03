# QL charts: routing and exact matrix

A QL chart renders directly from a SQL query against a connection, bypassing
datasets. Pick the visualization here, then read exactly one per-type file
plus [common-operations.md](common-operations.md) for the shared lifecycle
(queries, `QLParam` parameters, `QLColumn` columns, update semantics).

## Contents

- [Choosing a visualization](#choosing-a-visualization)
- [Canonical IDs and placement constraints](#canonical-ids-and-placement-constraints)
- [Method signatures and defaults](#method-signatures-and-defaults)
- [Factory by public fluent method](#factory-by-public-fluent-method)
- [Reading rules](#reading-rules)
- [Related references](#related-references)

## Choosing a visualization

Factories live on `client.create.ql_chart.<factory>(name=..., location=...)`.
The factory spelling and the canonical `visualization_id` returned on read
differ for five types — never guess one from the other. Confirm the selected
factory is present in `client.capabilities["chart_factories"]["ql"]` before
using it; that generated list is authoritative for the configured client.

| Task | Factory | Canonical ID | Read |
|---|---|---|---|
| Trend over an ordered axis, optional second value axis | `line` | `line` | [chart-line.md](chart-line.md) |
| Magnitude over an ordered axis, stacked series | `area` | `area` | [chart-area.md](chart-area.md) |
| Share of total over an ordered axis | `area_100p` | `area100p` | [chart-area-100p.md](chart-area-100p.md) |
| Horizontal ranking, long category labels | `bar` | `bar` | [chart-bar.md](chart-bar.md) |
| Horizontal normalized composition | `bar_100p` | `bar100p` | [chart-bar-100p.md](chart-bar-100p.md) |
| Vertical category comparison | `column` | `column` | [chart-column.md](chart-column.md) |
| Vertical normalized composition | `column_100p` | `column100p` | [chart-column-100p.md](chart-column-100p.md) |
| Part-to-whole, few categories | `pie` | `pie` | [chart-pie.md](chart-pie.md) |
| Part-to-whole as a ring | `donut` | `donut` | [chart-donut.md](chart-donut.md) |
| Two numeric variables, point identity/size | `scatter` | `scatter` | [chart-scatter.md](chart-scatter.md) |
| Hierarchical part-to-whole area | `treemap` | `treemap` | [chart-treemap.md](chart-treemap.md) |
| SQL result aliases as table columns | `flat_table` | `flatTable` | [chart-flat-table.md](chart-flat-table.md) |
| One headline KPI | `indicator` | `metric` | [chart-indicator.md](chart-indicator.md) |

## Canonical IDs and placement constraints

Read wire types in this table are observed server-response conventions, not
public SDK identifiers. Do not construct payloads or branch application logic
on them.

`!` means `build()` requires a non-empty placement. The number is scaffold
capacity; `∞` means the scaffold declares no capacity. **Capacity counts are
advisory**: the current builder enforces required non-emptiness, but does not
enforce capacity counts. Keep within capacity unless reproducing a known
backend-supported payload.

| Factory | Canonical `visualization_id` | Read wire type | Placements (`method: requirement/capacity`) |
|---|---|---|---|
| `area` | `area` | `d3_ql_node` | `x: !/1`, `y: optional/∞` |
| `area_100p` | `area100p` | `d3_ql_node` | `x: !/1`, `y: optional/∞` |
| `bar` | `bar` | `d3_ql_node` | `y: optional/2`, `x: optional/∞` |
| `bar_100p` | `bar100p` | `d3_ql_node` | `y: optional/2`, `x: optional/∞` |
| `column` | `column` | `d3_ql_node` | `x: optional/2`, `y: optional/∞` |
| `column_100p` | `column100p` | `d3_ql_node` | `x: optional/2`, `y: optional/∞` |
| `donut` | `donut` | `d3_ql_node` | `dimensions: optional/1`, `colors: optional/1`, `measures: !/1` |
| `flat_table` | `flatTable` | `table_ql_node` | `flat_table_columns: !/∞` |
| `indicator` | `metric` | `metric2_ql_node` | `measures: !/1`, `colors: optional/∞` |
| `line` | `line` | `d3_ql_node` | `x: !/1`, `y: optional/∞`, `y2: optional/∞` |
| `pie` | `pie` | `d3_ql_node` | `dimensions: optional/1`, `colors: optional/1`, `measures: !/1` |
| `scatter` | `scatter` | `d3_ql_node` | `x: !/1`, `y: !/1`, `points: optional/1`, `size: optional/1` |
| `treemap` | `treemap` | `d3_ql_node` | `dimensions: !/∞`, `measures: !/1` |

## Method signatures and defaults

| Operation | Exact arguments | Default/state semantics |
|---|---|---|
| `<factory>()` | `*, name: str, location: EntryLocation` | No defaults; factory is not callable directly |
| `connection()` | `connection: Connection` | Requires `connection.id`; replaces the connection |
| `query()` | `sql: str` | Create starts as `""`; replaces `data.queryValue` |
| `params()` | `params: Sequence[QLParam]` | Create starts as `()`; replaces all parameters |
| placement/decorations | `columns: Columns` | Strings become `QLColumn(..., cast="string")`; replaces the whole target |
| `description()` | `text: str` | Create omits empty description; update writes the supplied text |
| `visualization()` | `blob: Mapping[str, object]` | Create-only opaque replacement of generated visualization |
| `data()` | `blob: Mapping[str, object]` | Shallow top-level merge; later keys win |
| `build()` | none | Performs create; required-placeholder checks run unless custom visualization was supplied |
| `mode()` | `value: Literal["save", "publish"]` | Update-only; initial update mode is `"save"` |
| `execute()` | none | Performs update and returns `QLChart` |

`Columns` means `Sequence[QLColumn | str]`. `to_spec()` exists on the builders
for SDK plumbing; it is **not a persistence operation** — do not build user
workflows around it. Only `.build()` (create) and `.execute()` (update)
persist anything.

## Factory by public fluent method

`C` means the chart-specific create builder, `U` means `QLChartUpdate`, `CU`
means both, and `—` means unsupported. `P` marks a visualization placeholder;
`D` marks a top-level `data` section.

This matrix describes the typed public `datalens_sdk` surface. It is an
acceptance matrix, not permission to supply SQL aliases that do not exist.

| Operation | area | area_100p | bar | bar_100p | column | column_100p | donut | flat_table | indicator | line | pie | scatter | treemap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `<factory>()` | C | C | C | C | C | C | C | C | C | C | C | C | C |
| `connection()` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `query()` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `params()` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `x()` | CU | CU | CU | CU | CU | CU | — | — | — | CU | — | CU | — |
| `y()` | CU | CU | CU | CU | CU | CU | — | — | — | CU | — | CU | — |
| `y2()` | — | — | — | — | — | — | — | — | — | CU | — | — | — |
| `dimensions()` | — | — | — | — | — | — | CU | — | — | — | CU | — | CU |
| `measures()` | — | — | — | — | — | — | CU | — | CU | — | CU | — | CU |
| `points()` | — | — | — | — | — | — | — | — | — | — | — | CU | — |
| `size()` | — | — | — | — | — | — | — | — | — | — | — | CU | — |
| `flat_table_columns()` | — | — | — | — | — | — | — | CU | — | — | — | — | — |
| `colors()` | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-P | CU-D | CU-P | CU-D | CU-P | CU-D | CU-D |
| `labels()` | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | — | — | CU-D | CU-D | — | — |
| `shapes()` | — | — | — | — | — | — | — | — | — | CU-D | — | CU-D | — |
| `tooltips()` | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D | CU-D |
| `description()` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `visualization()` | C | C | C | C | C | C | C | C | C | C | C | C | C |
| `data()` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `build()` | C | C | C | C | C | C | C | C | C | C | C | C | C |
| `mode()` | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `execute()` | U | U | U | U | U | U | U | U | U | U | U | U | U |

## Reading rules

- Treat the exact canonical ID as the value returned by
  `chart.visualization_id`. Do not expect factory spelling for `area_100p`,
  `bar_100p`, `column_100p`, `flat_table`, or `indicator`.
- `indicator()` is the only public factory spelling for canonical ID `metric`;
  do not invent `.metric()`.
- `flat_table_columns()` targets wire placeholder ID `flat-table-columns`.
- On update, all placement methods exist on `QLChartUpdate`, but applicability
  is checked against the active canonical ID and active placeholders.
- `colors()` is routed to the `colors` placeholder only for canonical IDs
  `pie`, `donut`, and `metric`; it preserves their top-level `data.colors`.
- `tooltips()` is a top-level section for all 13 types.
- No factory supports filters, sorting, axes, palettes, aggregations, local
  fields, dataset binding, or visualization transitions.

## Related references

- [common-operations.md](common-operations.md) — QL lifecycle shared by all
  13 types: create flow, columns, parameters, get/update, rename/delete.
- [../core-concepts.md](../core-concepts.md) — object model, retries,
  pagination, error handling.
- [../connections.md](../connections.md) — creating the connection a QL
  chart queries.
- [../setup.md](../setup.md) — client construction and credentials.
- [../serialization.md](../serialization.md) — export, import, and clone.
