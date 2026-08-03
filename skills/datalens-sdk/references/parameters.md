# Parameters across datasets, charts, and dashboards

Read this for any task where a selector, URL, chart click, or dashboard
setting must supply a named value to a Dataset, Wizard, QL, or Editor chart.
The same parameter key can appear on several SDK surfaces, but those surfaces
have different scopes and precedence.

## Flow and precedence

Parameter definitions and defaults start on the receiving entity. Dashboard
surfaces then override them from narrower to broader runtime scope:

```text
Dataset/Wizard, QL, or Editor definition/default
  -> widget params
  -> dashboard global params
  -> selector values
  -> URL params
  -> URL state
```

Later non-empty values override earlier values. Action parameters are a
runtime filter source rather than another stored default: a chart click emits
values, and the dashboard connection graph decides which widgets receive
them.

| Surface | SDK entry point | Scope and key |
|---|---|---|
| Dataset parameter | `DatasetCreate.add_parameter` / `ds.update.add_parameter` | Definition available to Wizard charts based on that Dataset; key is the exact parameter `name` |
| QL parameter | `QLParam.*(...)` passed to `.params(...)` | Definition for one QL chart; SQL reads it as `{{name}}` |
| Editor parameter | JavaScript exported from the Editor `params` tab | Definition for one Editor chart or selector; key is the exported object key |
| Widget parameter | `add_chart(..., params=...)` or `DashboardChartTab(..., params=...)` | Persistent override for one dashboard widget tab; keys are receiver parameter names, not widget or selector titles |
| Dashboard parameter | `dash.update.global_params(...)` | Persistent dashboard-wide override; keys are receiver parameter names or Dataset field ids |
| Manual selector | `add_selector(param_name=...)` | Interactive value emitted under `param_name` to linked receivers |
| Action parameter | `enable_action_params=True` | Allows a supporting chart tab to emit click/filter values; connections determine receivers |

Use exact, case-sensitive keys. For a Wizard chart that receives a Dataset
parameter, a widget/global/manual-selector key is the Dataset parameter
**name**, not its display title. For Dataset-field filtering, use the field
guid where DataLens requires a field id. For QL use the `QLParam` name; for
Editor use the key exported by the `params` tab.

## Choose the right dashboard surface

- Use **widget params** to place the same chart several times with different
  fixed values.
- Use **global params** for a stored initial value that should reach the whole
  dashboard. The typed create builder has no `global_params` method: build the
  dashboard, then set them through its update builder.
- Use a **manual selector** when the viewer must choose the value.
- Use **action params** for cross-chart filtering driven by a chart click.
  Only enable them on a chart family that emits action parameters at runtime;
  the SDK can persist the flag but cannot prove renderer support.

```python
# One chart instance only: fixed override for the receiving parameter.
tab.add_chart(chart, item_id="prod_chart", params={"env": "prod"})

# Dashboard-wide stored value: update-only, deep-merged by key.
dashboard = dashboard.update.global_params({"env": "prod"}).execute(publish=True)
```

`global_params` and `set_chart_params` normalize each scalar or sequence to a
list of strings. On update:

```python
from datalens_sdk import REMOVE_PARAM

dashboard = dashboard.update.global_params(
    {
        "env": "prod",  # merge/replace this key
        "obsolete": REMOVE_PARAM,  # delete this key
    }
).execute(publish=True)
```

`set_chart_params(item_id=..., params=..., merge=True)` merges keys by
default; `merge=False` replaces the complete mapping. On a multi-tab chart
widget it applies to **every internal chart tab**; there is no per-chart-tab
target. It also updates defaults on a standalone `control`, but rejects a
`group_control`: update a grouped selector by its member id instead.

## Manual selector to every tab

For one shared selector, do not create a named one-member group with both
display and influence overrides. A standalone selector is already a
single-member group: `show_on_tabs="all"` displays it everywhere and its
default `affects="as_group"` makes its influence follow that display scope.

```python
from datalens_sdk import DashboardTab

overview = DashboardTab("Overview", tab_id="overview").add_selector(
    item_id="env",
    param_name="env",
    element="select",
    options=[
        ("prod", "Production"),
        {"value": "test", "title": "Testing"},
    ],
    default_value="prod",
    show_on_tabs="all",
)
```

The receiving parameter must exist before the dashboard uses it:

- Dataset/Wizard: `add_parameter(name="env", ...)`.
- QL: `QLParam.string("env", ...)` and `{{env}}` in the query.
- Editor: an `env` key in the `params` tab export.

For parameter selectors, leave `operation=None`; the selector changes a
parameter value rather than applying a field comparison. Keep the connection
to each intended receiver and add ignore edges for widgets that must not
receive it.

For several selectors in one visual block, put `affects=` on each member and
`show_on_tabs=` on the wrapper:

```python
tab = (
    DashboardTab("Overview", tab_id="overview")
    .add_selector(
        group="filters",
        item_id="env",
        param_name="env",
        options=["prod", "test"],
        default_value="prod",
        affects="all_tabs",
    )
    .add_selector(
        group="filters",
        item_id="region",
        param_name="region",
        options=["EU", "US"],
        default_value="EU",
        affects=("overview", "details"),
    )
    .add_group_selector(
        group="filters",
        item_id="filters",
        show_on_tabs="all",
    )
)
```

## Chart clicks and action parameters

`enable_action_params=True` is the SDK form of enabling cross-chart filtering
for that chart tab. Clicking a supported chart element emits dimension/filter
values. The normal dashboard connection mesh broadcasts them; ignore edges
remove receivers from that mesh. The flag does not define Dataset, QL, or
Editor parameters and does not replace `params=`.

For `DashboardChartTab`, the flag is per internal chart tab:

```python
from datalens_sdk import DashboardChartTab

DashboardChartTab(
    chart=chart,
    title="Filter source",
    enable_action_params=True,
)
```

## Validation boundary

`validate_dashboard_refs(client, dashboard)` can prove that a manual selector
name exists on a reachable Dataset. It does not statically parse QL parameter
lists or Editor JavaScript. For a manual selector that intentionally targets
QL or Editor, inspect the receiver's parameter definition yourself; an
`unbound_manual_selector` issue means only that no reachable Dataset declares
that name.

After any parameter change, re-fetch and inspect the stored surface, then
render or query the receiving chart. Persistence alone does not prove that the
parameter key, value type, connection, or renderer behavior is correct.

## Official product references

- [Parameters](https://yandex.cloud/ru/docs/datalens/concepts/parameters) —
  Dataset/chart definitions and manual-selector usage
- [Dashboard parameters](https://yandex.cloud/ru/docs/datalens/dashboard/dashboard_parameters) —
  dashboard/widget scope, precedence, URL parameters, and reserved keys
- [Cross-chart filtering](https://yandex.cloud/ru/docs/datalens/dashboard/chart-chart-filtration) —
  click-driven filtering and runtime state
- [Selectors](https://yandex.cloud/ru/docs/datalens/dashboard/selector) —
  selector behavior and cross-tab display

## Related skill references

- [datasets.md](datasets.md) — creating Dataset parameters
- [dashboards.md](dashboards.md) — selectors, connections, read model, updates
- [ql-charts/common-operations.md](ql-charts/common-operations.md) — `QLParam` and `{{name}}`
- [editor-charts/common-operations.md](editor-charts/common-operations.md) — Editor `params` tabs
