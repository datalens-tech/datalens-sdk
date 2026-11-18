# Dashboard states

Read this when the task involves a dashboard link with `state=<hash>`: which
selector values and chart clicks it holds, which widgets they reach, or a new
link with other values. The SDK wraps `/rpc/getEntryState` and
`/rpc/createEntryState`. Both are available in the Enterprise and Yandex Cloud
contracts. The state JSON is read and written through models generated from the
`DashboardState` schema of the API specification.

## Read a state

```python
dashboard = client.get.dashboard(by_id="<dashboard-id>")
state = dashboard.get_state("<hash>", tab="<tab id from ?tab=>")
for selection in state.selections:
    print(
        selection.kind,
        selection.item_id,
        selection.applied,
        [(_.param, _.operation, _.values) for _ in selection.values],
    )
```

`get_state(hash, tab=None, strict=False)` returns an immutable
`DashboardState`. It holds `hash`, `dashboard_id`, `tab_id`, `rev_id`,
`version`, `created_at`, `selections`, `issues`, the typed `data`
(`DashboardStateData`), and the stored JSON in `raw`. A hash unknown for this
dashboard raises `DashboardStateNotFoundError`, a subclass of `NotFoundError`.

A state applies to **one dashboard tab**. Without `tab`, the SDK picks the
first tab that holds every item of the state, as the UI opens a link without
`?tab=`. A state of global selectors fits every tab, so pass `tab=` (the
link's `?tab=` value: a tab id, title, or `DashboardTabView`) to check it
against the tab you mean. When no tab fits, it raises
`DataLensValidationError`.

A state is not bound to a revision. The SDK checks it against the revision
loaded into `dashboard`, and `state.rev_id` is that revision.

## Stored format (version 2)

```json
{
  "6n": {"params": {"E7Z": {"date_interval": "__interval_2026-11-10T00:00:00.000Z_2026-11-16T23:59:59.999Z"}}},
  "LEN": {"params": {}, "state": {"tabId": "dM3"}},
  "Lj": {"params": {"_ap_171030c0-21bc-11ef-909c-4f6e9f670c50": ["Prod"]}},
  "__meta__": {"version": 2, "queue": [
    {"id": "6n", "groupItemId": "E7Z"},
    {"id": "LEN", "tabId": "dM3"},
    {"id": "Lj", "tabId": "0x"}
  ]}
}
```

- Only sources in `__meta__.queue` contribute parameters, in queue order; later
  sources win on the same parameter. `selections` follow the queue; entries of
  `data` outside the queue are kept in `data` and `raw` but are not sources.
- `groupItemId` is a selector of a group; its params are nested under
  `params[groupItemId]`.
- `state.tabId` of a widget is its active chart tab; without it the tab marked
  `isDefault`, else the first tab, is active. The queue `tabId` names the chart
  tab the params came from: such a source applies only while that tab is
  active (`selection.applied`). Neither is the dashboard tab, which goes to the
  URL as `?tab=`.
- A state without `__meta__` is version 1: every widget keeps only its own
  stored params, and an issue `legacy_state_version` is reported.

Each `StateSelection` has `item_id`, `group_item_id`, `widget_tab_id`, `kind`
(`"selector"`, `"group_selector"`, `"chart"`, `"unknown"`), the matching view in
`item` (`ControlView`, `ControlMemberView`, or `DashboardItemView`), decoded
`values`, the stored `params`, and `applied`.

## Value prefixes

Each `StateValue` has `param`, `operation` (a `ParamOperation`), decoded
`values`, `multiple` (a list on the wire), `inherits_operation` (no prefix: the
selector's operation applies), the stored wire `raw`, `is_action_param`, and
`field_guid`. Decoding and encoding the wire forms below is done by the SDK; the
domain objects hold only typed values.

| Wire form | Meaning |
|---|---|
| `_ap_<guid>` (key) | chart click (action parameter) on dataset field `<guid>`; other widgets receive it as `<guid>` |
| `__<op>_<value>` | explicit operation, lower case: `__ne_x`, `__gte_10`, `__isnull_` |
| `__interval_<start>_<end>` | date range, decoded to `DateInterval`; operation BETWEEN |
| `__relative_-7d[_sd]` | relative date, decoded to `RelativeDate(offset, cast, unit)`; `_sd`/`_ed` round to the start/end of a day |
| no prefix | the selector's operation, else IN (BETWEEN for an interval) |

The UI writes every value of a selector that has an operation with that
operation's prefix. An unknown prefix such as `__relative_` alone decodes as IN.

`ParamOperation` has 24 values: the 12 of `FilterOperation` plus `NIN`,
`ICONTAINS`, `NOTCONTAINS`, `NOTICONTAINS`, `ISTARTSWITH`, `ENDSWITH`,
`IENDSWITH`, `LENEQ`, `LENGT`, `LENGTE`, `LENLT`, and `LENLTE`.

## Orphans and `strict`

The UI silently ignores ids that no longer exist. The SDK keeps such sources
in `selections` with `item=None` (`is_orphan`, `applied=False`) and records a
`ValidationIssue`:

| Issue kind | Cause |
|---|---|
| `unknown_state_item` | the item is not on the tab |
| `unknown_group_item` | the selector group has no such selector |
| `unknown_widget_tab` | the chart widget or tabs selector has no such tab |
| `unknown_state_param` | the parameter is not in the selector `defaults` or the chart tab `params` (`_ap_` keys are not checked); it is not applied |
| `legacy_state_version` | version 1 state |

All issues are reported with one `UserWarning`. `strict=True` raises
`DataLensValidationError` instead.

## Create a state

```python
from datalens_sdk import DateInterval, RelativeDate

state = (
    dashboard.new_state("Overview")
    .select("Period", DateInterval(RelativeDate("-7d", cast="s", unit="d"), RelativeDate("+0d")))
    .select("department_param", "User")
    .select(item="LEN", widget_tab="dM3")
    .create()
)
link = state.url()
```

`DashboardStateBuilder.select(target=None, values=None, *, field=None, item=None, widget_tab=None, operation=None)`:

- `target` is an item or selector id, then a selector title, then a parameter
  name; or a `ControlView`, `ControlMemberView`, or `DashboardItemView`.
  Several matches raise `DataLensValidationError` with the candidates.
- `field=` finds the selector bound to that dataset field.
- `item=` with `field=` selects a chart value as `_ap_<guid>`. `widget_tab`
  picks the chart tab and makes it active (`state.tabId`, omitted for the
  default tab); without it the active tab is kept. `item=` without `field=`
  takes a mapping of chart parameters or only switches the chart tab.
- Values are strings, sequences of strings, `DateInterval`,
  `RelativeDateInterval`, or `RelativeDate`; a mapping sets several parameters
  of one source. A range selector takes exactly one interval. A selector with
  its own operation prefixes the values with it; `operation=` writes another
  one (`__in_` included).
- A repeated `select` of the same source moves it to the end of the queue.

`clear(target)` removes a source and keeps the widget's active tab,
`add(selection)` appends a read `StateSelection` or a raw
`{"id", "groupItemId", "tabId", "params"}` mapping, `prune()` drops orphans
and returns them, and `to_data()` returns the typed state.

`create()` raises `DataLensValidationError` on any orphan, item from another
tab that is not global, undeclared parameter, or payload above 50 000
characters (UTF-16 length of the JSON, as US counts it). Then it calls
`createEntryState` and returns a `DashboardState` with the hash and
`created_at=None`. The hash is deterministic: equal data returns the same hash,
so a retried create is safe.

Shortcuts:

- `dashboard.create_state(tab, selections)` takes `StateSelection` objects or
  raw mappings and runs the same validation.
- `state.edit()` starts a builder with a copy of the queue and the widget
  states on the same tab; its `create()` stores a new state and leaves the old
  one unchanged.

## `params_for` and `effects`

`state.params_for(item)` returns the parameters an item ends up with, ready for
`get_chart_data(params=...)`, following DashKit:

1. the params of the item's active chart tab (only for that chart);
2. dashboard `globalParams`;
3. selector defaults of the namespace; on a shared name the first selector in
   the dashboard wins;
4. the applied queue sources in order, limited to the parameters their
   selector or chart tab declares, plus action params.

Parameters travel within one `namespace` to every item, whatever its parameter
names. A connection `{"from": R, "to": S, "kind": "ignore"}` stops R receiving
anything from S; both ends are the active endpoints: a chart's active tab id,
a selector id, or one selector of a group. `aliases[namespace]` copies a value
to every name of its group, and a foreign `_ap_<guid>` arrives as `<guid>`. A
selector of a global group takes part only on the tabs of its `impactType`.
Address a group by one of its selectors.

`state.effects(*, resolve_charts=False, items=None)` returns `StateEffect`
objects: `selection`, `receiver` (an item view, or the `ControlMemberView` of a
selector in a group), `params`, `certainty`, `matched_by`. `items=` limits the
receivers; a version 1 state has none.

| `certainty` | Meaning |
|---|---|
| `received` | the receiver gets the parameters; default, no HTTP |
| `exact` | a selector `defaults` key, a Wizard dataset field guid or title, or a QL parameter `name` uses them |
| `declared` | a QL interval bound (`name_from`, `name_to`) or an Editor chart tab `params` key |
| `unknown` | an Editor chart tab declares no params (the public API exposes no `usedParams`), or the chart was not found |

With `resolve_charts=True`, receivers that do not use the parameters are
dropped and `matched_by` is `"guid"` or `"title"` for Wizard charts. It sends
one `getEntries` for the chart kinds, one request per distinct chart, and one
per distinct dataset of the Wizard charts.

## Links and `ui_base_url`

`state.url(base=None)` returns `{base}/{dashboard_id}?tab={tab_id}&state={hash}`.
`base` defaults to the client's `ui_base_url`: `https://datalens.ru` for
`DataLensClientYC`; Enterprise clients must pass
`DataLensClientEnterprise(..., ui_base_url="https://<datalens-ui>")` or
`url(base=...)`, else `DataLensConfigurationError`. A state without a hash
raises `DataLensValidationError`.

## Screenshots and chart data

`dashboard.screenshot(state=state)` renders the dashboard with the state; the
tab comes from the state, and a different explicit `tab` or a state of another
dashboard raises `DataLensValidationError`. A string hash is still accepted as
before; see [screenshots](screenshots.md#saved-dashboard-state).

To read a chart as the state shows it, pass the receiver's parameters, after
the result-handling permission from [chart data](chart-data.md):

```python
widget = dashboard.tabs[0].items[0]
result = client.data.get_chart_data(chart_id="<chart-id>", params=state.params_for(widget))
```

## Related references

- [dashboards.md](dashboards.md) — selectors, connections, aliases, read model
- [parameters.md](parameters.md) — parameter flow and action parameters
- [screenshots.md](screenshots.md) — rendering a dashboard with a state
- [chart-data.md](chart-data.md) — reading chart tables with runtime params
