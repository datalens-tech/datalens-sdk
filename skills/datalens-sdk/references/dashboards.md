# Dashboards

Read this when building or editing a dashboard: tabs, widgets, selectors,
layout, the read model, validation, and the update path. For Dataset/QL/Editor
parameter definitions, widget overrides, global params, selectors, action
params, and precedence, also read [parameters.md](parameters.md).

## The model in one paragraph

A dashboard is a set of **tabs**; each tab holds **items** (charts, text, titles, images, selectors) placed on a **36-column grid** (`datalens_sdk.GRID_COLUMNS == 36`; height is unbounded). Charts are referenced by object or id — the dashboard does not own them. You build each tab standalone with `DashboardTab`, then attach it to a create or update builder with `.add_tab(tab)`. The terminal calls are the usual ones: `client.create.dashboard(...).build()` and `dash.update...execute(publish=...)` — dashboards are the one entity whose `execute()` **requires** the `publish=` keyword.

## `DashboardTab` — build tabs before the dashboard

```python
from datalens_sdk import DashboardTab

tab = DashboardTab("Overview")  # also: tab_id=, hidden=
```

A tab is a reusable template: attaching it to a builder never mutates it, and
mutating it afterwards does not affect builders it was already attached to.
The SDK can assign ids at attach time, but the skill imposes a stricter rule:
**every `add_chart` call must pass an explicit semantic `item_id=`**. Name the
chart's business role (`"revenue_by_region"`, `"orders_trend"`), not its
position or creation order (`"main"`, `"chart_1"`, `"widget"`). Stable
semantic ids are required for updates, connections, layout, inspection, and
safe collaboration with later agents.

All `add_*` methods return `Self` and chain. Content methods:

| Method                                                | Adds                           | Key arguments                                                                                                                                                                                            |
|-------------------------------------------------------|--------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `add_chart(chart, ...)`                               | one chart widget               | `chart` (object or id str), semantic `item_id=` (**mandatory by this skill**), `title=`, `params=` (receiver parameter **names**, not titles; see [parameters.md](parameters.md)), `description=`, `hint=`, `show_title=`, `auto_height=`, `background=`, `border_radius=`, `enable_action_params=` |
| `add_chart_group(charts, ...)`                        | one widget with internal tabs  | `charts`: sequence of `DashboardChartTab`                                                                                                                                                                |
| `add_text(text, ...)`                                 | markdown text block            | `background=` defaults to `DEFAULT_TEXT_BACKGROUND` (opaque themed `ThemedColor`); pass `background=None` for transparent                                                                                |
| `add_title(text, ...)`                                | heading                        | `size=` is a **title size** `"xs".."xl"` (default `"m"`), not a grid size; `show_in_toc=`, `text_color=`                                                                                                 |
| `add_image(*, src, ...)`                              | image by URL                   | `alt=`, `preserve_aspect_ratio=`                                                                                                                                                                         |
| `add_section_divider(text, ...)`                      | full-width separator           | text label                                                                                                                                                                                               |
| `add_selector(...)`                                   | one selector                   | see [Selectors](#selectors)                                                                                                                                                                              |
| `add_group_selector(*, group, ...)`                   | assembles registered selectors | see [Selectors](#selectors)                                                                                                                                                                              |
| `add_connection(*, from_item, to_item, mutual=False)` | an **ignore** edge             | see [Connections and aliases](#connections-and-aliases)                                                                                                                                                  |
| `add_alias(*fields)`                                  | one alias group                | ≥2 dataset field **guids** declared equivalent                                                                                                                                                           |

`DashboardChartTab` is a dataclass for `add_chart_group` entries:

```python
from datalens_sdk import DashboardChartTab

DashboardChartTab(chart=trips_chart, title="Trips")
DashboardChartTab(chart=gmv_chart, title="GMV", default=True)  # opens first
# also: params=, description=, hint=, auto_height=, enable_action_params=
```

## Layout: auto-flow first, coordinates only when needed

Treat every chart's semantic `item_id` as its **layout primary key**. Assign
it in the same `add_chart` call, before composing layout:

```python
from datalens_sdk import DashboardTab, Layout

tab = (
    DashboardTab("Overview", tab_id="overview")
    .add_chart(orders_chart, item_id="orders_trend")
    .add_chart(revenue_chart, item_id="revenue_by_region")
)
tab.apply_layout(Layout.row("orders_trend", "revenue_by_region", y=0, h=14))
```

This makes `apply_layout` and `preview_layout` usable immediately on the local
`DashboardTab`, before attach/build or any HTTP read. The same ids remain the
handles for later `move_item`, `resize_item`, `swap_items`, `apply_layout`,
`pin_item`, `unpin_item`, `replace_chart`, connections, and removals.
Auto-generated ids force a later agent to build and inspect `dashboard.tabs`
just to discover the chart handles. Semantic ids avoid that discovery pass
and make tab-scoped layout actions explicit. An existing-dashboard write
still starts with `get`/`refresh` for current state and concurrency safety.

Every item-producing method takes `at=` and most take `size=`. Three modes:

1. **Auto-flow (default, `at=None`)** — items flow left-to-right and wrap into rows automatically, each at its type's default size. No coordinate arithmetic.
2. **Auto position, explicit size** — `size=(w, h)`; the flow cursor accounts for it. `size=(36, 10)` makes a full-width row.
3. **Explicit** — `at=Position(x, y, w, h)` or `at=(x, y, w, h)`. Explicit items are **outside the flow**: they do not move the cursor and skip `start_row`/`space`.

Auto-flow does not route around explicit boxes. Mixing `at=` with later
auto-placed items can therefore overlap; inspect `preview_layout()` and run
conversion/`dashboard.validate()` (`ValidationIssue.kind == "overlap"`)
instead of assuming the cursor avoided the explicit item.

Flow control (pure cursor movement — nothing extra reaches the dashboard):

```python
tab.start_row()  # the NEXT auto-placed item starts at x=0 on a new row
tab.space(2)  # new row plus 2 empty grid rows before the next auto item
```

Default sizes per item type — `datalens_sdk.DEFAULT_ITEM_SIZES`:

| Type | Default (w, h) |
|---|---|
| `title` | (36, 2) |
| `text` | (12, 6) |
| `widget` (chart / chart group) | (12, 12) |
| `image` | (12, 12) |
| `control` (external selector) | (2, 2) |
| `group_control` (selectors) | (36, 2) |

### Reposition after adding: `apply_layout` + `Layout`

`Layout` builds `{item_id: Position}` mappings; `tab.apply_layout(mapping)`
patches already-added items by explicit `item_id` (partial patch, unknown ids
fail loud). Never wait for attach-time ids when adding a chart: its semantic
`item_id` must already be available here.

```python
from datalens_sdk import Layout

tab.apply_layout(Layout.row("left", "mid", "right", y=2, h=8))  # equal-width row
tab.apply_layout(Layout.grid("a", "b", "c", "d", cols=2, y=10))  # 2-wide grid
tab.apply_layout(Layout.stack("intro", "detail", y=20))  # full-width stack
```

Signatures: `row(*ids, y=0, h=14)`, `grid(*ids, cols=, y=0, h=14)`,
`stack(*ids, y=0, h=14)`. `row` and `stack` also accept one height per item,
for example `h=(18, 4)`; `grid` uses one height for every cell.

### Pin zones

`pinned=` on non-selector content methods puts the item into one of two sticky
header zones (`PinZone = Literal["fixed", "collapsible"]`; `pinned=True` is
shorthand for `"collapsible"`):

- `"fixed"` — always visible while scrolling.
- `"collapsible"` — the user can fold it.

Each pin zone flows on its **own cursor**: a pinned item never pushes the default flow, and `start_row()`/`space()`/`next_auto_position()`/`content_bottom()` all take `pinned=` to address the right zone.

**Public SDK limitation:** `add_selector`, `add_group_selector`, and update
`pin_item` do not support pinning selector/control items. Do not pass
`pinned=` to selector methods and do not fall back to a private payload.

### Read the layout before creating anything

The cursor is a readable model — inspect placements offline, before any HTTP:

```python
tab.preview_layout()  # {item_id: Position} for every item with an explicit item_id
tab.next_auto_position("widget")  # the slot the NEXT at=None widget would take (pure read)
tab.content_bottom()  # y below all content — where a full-width at= block goes
```

`preview_layout()` reports only items that were given an explicit `item_id=` (unnamed items still occupy space and count for `content_bottom`).

## Selectors

`tab.add_selector(...)` covers three kinds, chosen by which arguments you pass:

```python
# 1. Dataset selector — filters by a dataset field
tab.add_selector(
    item_id="flt_date", dataset=ds, field=ds.fields.by_name("Date"), default_value="2026-01-01", show_on_tabs="all"
)

# 2. Manual selector — emits a named value to linked Dataset/QL/Editor charts
tab.add_selector(item_id="flt_env", param_name="env", element="select", options=["prod", "test"], default_value="prod")

# 3. External selector — a control rendered by an editor/wizard chart
tab.add_selector(item_id="flt_ext", chart=selector_chart)
```

Frequently used keywords: `title=`, `show_title=`, `title_placement=`
(`"left"`/`"top"`), `inner_title=`, `multiselect=`, `is_range=`, `required=`,
`operation=` (comparison such as `"IN"`, `"NE"`, `"GT"`, `"BETWEEN"`; note
`"NE"`, not `"NEQ"`), `element=` (`"select"`, `"date"`, `"input"`,
`"checkbox"`), `default_value=` (str, sequence, bool, `DateInterval`,
`RelativeDateInterval`).

Manual `options=` accepts strings, `(value, title)` pairs, or
`{"value": ..., "title": ...}` mappings. `DateInterval` accepts ISO dates or
relative edges such as `"-7d"`; `RelativeDateInterval` uses offsets with units
`d/w/M/Q/y`, for example `RelativeDateInterval("-30d", "+0d")`.

Cross-tab scope has two separate axes:

| Selector form | Display axis | Influence axis | Constraints |
|---|---|---|---|
| Standalone (no `group=`) | `show_on_tabs=`: `"current"`, `"all"`, or tab-id tuple | leave `affects="as_group"`; influence follows where the standalone selector is displayed | non-default `affects=` raises |
| Member of `group=` | wrapper `add_group_selector(show_on_tabs=...)` | member `add_selector(affects=...)`: `"as_group"`, `"all_tabs"`, or tab-id tuple | member `show_on_tabs=` must stay `"current"` |
| External (`chart=`) | current tab only | chart-defined | cannot be grouped or shared; non-current `show_on_tabs=` raises |

`"as_group"` means the member emits no independent influence scope and
inherits the group's scope. A named group with exactly one member cannot
combine a non-current wrapper `show_on_tabs` with a non-default member
`affects`; use a standalone selector with `show_on_tabs=` or add another
member. `item_id=` names the selector *member* used by selector updates and
connections (except external selectors, where it names the `control` item).

Without `group=` each selector lands as its own single-member group. To render several selectors side by side in one block, register them with a shared `group=` and assemble:

```python
tab.add_selector(
    group="filters",
    item_id="flt_from",
    dataset=...,
    field=...,
)
tab.add_selector(
    group="filters",
    item_id="flt_to",
    dataset=...,
    field=...,
)
tab.add_group_selector(group="filters", item_id="filters", apply_button=True, reset_button=True)
```

`add_group_selector` also takes `update_on_change=`, `show_group_name=`, `show_on_tabs=`, and the usual `at=`/`size=`.

### Shared selectors and `global_items`

A group displayed on other tabs is one logical item replicated into each
target tab's `globalItems` wire collection. On read, those copies appear in
`DashboardTabView.global_items`; `DashboardTabView.controls` already combines
local and global controls.

Shared items have global mutation semantics:

- `add_selector_to_group` appends the member to every occurrence of an
  existing shared group while preserving the wrapper's settings and layout.
- `remove_item` removes every occurrence from every tab, all related
  connections, and selector-dependent alias fields/groups that become empty.
- `replace_chart` and `set_chart_params` likewise patch every occurrence of a
  shared logical item.
- Every target tab gets a layout entry for the shared selector. Overlap checks
  use `items ∪ global_items`, so leave space for it on **every** displayed tab.

Enumerate all occurrences through the read model before removing or replacing
a shared item; never assume an id visible on one tab is local to that tab.

## Connections and aliases

By default every selector broadcasts to every widget on the tab. `add_connection` adds a **directed ignore edge** — it subtracts from the mesh, it never connects anything:

```python
tab.add_connection(from_item="gmv", to_item="flt_date")  # the WIDGET stops receiving the selector
tab.disconnect_all("trips")  # full isolation of one item, both directions
```

`from_item` stops *receiving* `to_item`'s parameters; use `mutual=True` or `disconnect_all` when you want a guaranteed full break.

`add_alias(guid_a, guid_b, ...)` declares dataset field guids equivalent so one selector drives charts on different datasets. Requires ≥2 guids; duplicate groups are deduplicated silently.

## Canonical create example

```python
from datalens_sdk import DashboardChartTab, DashboardTab, Layout

ds = client.get.dataset(by_id=dataset_id)  # fields needed -> re-get, not create result
trips_chart = client.get.wizard_chart(by_id=trips_chart_id)
gmv_chart = client.get.wizard_chart(by_id=gmv_chart_id)

overview = (
    DashboardTab("Overview")
    .add_title("Ride metrics", item_id="hdr", show_in_toc=True, pinned="fixed")
    .add_selector(item_id="flt_date", dataset=ds, field=ds.fields.by_name("Date"), show_on_tabs="all")
    .add_chart(trips_chart, item_id="trips", description="Daily trips")  # 12x12, auto-flow
    .add_chart_group(
        [
            DashboardChartTab(chart=trips_chart, title="Trips"),
            DashboardChartTab(chart=gmv_chart, title="GMV", default=True),
        ],
        item_id="tabs",
    )
    .start_row()
    .space(1)
    .add_chart(gmv_chart, item_id="gmv", size=(36, 10))  # full-width row
)
overview.apply_layout(Layout.row("trips", "tabs", y=4, h=12))  # optional repositioning

dashboard = (
    client.create.dashboard(name="Rides overview", location=wb)
    .add_tab(overview)
    .description("Built by the SDK")
    .settings(hide_tabs=False)
    .build()
)

issues = dashboard.validate()
assert not issues, issues
```

`DashboardCreate` also offers `access_description()`, `support_description()`, and `meta()`.

For a larger executable composition with two tabs, a cross-tab selector
group, pinned content, a chart group, post-composition layout helpers,
an ignore edge, layout preview, and both validation passes, run
[`../examples/advanced_dashboard_layout.py`](../examples/advanced_dashboard_layout.py).

## Dashboard settings

Both create and update builders expose these `settings(...)` keys:

| SDK argument | Meaning |
|---|---|
| `silent_loading` | load only visible charts while scrolling |
| `dependent_selectors` | enable dependent/cascading selector value lists |
| `expand_toc` | show the table of contents |
| `hide_dash_title` | hide the dashboard title |
| `hide_tabs` | hide the tab strip |
| `autoupdate_interval` | global refresh interval in seconds, minimum `30` |
| `max_concurrent_requests` | maximum concurrently loaded widgets, minimum `1` |
| `load_priority` | load `"charts"` or `"selectors"` first |

Create uses `None` for "use the canonical default". Update is tri-state:
omitted (`UNSET`) leaves a key untouched, `None` resets it, and a value sets
it. `dependent_selectors` affects cascading values, not cross-tab
display/influence; use `show_on_tabs` and `affects` for those axes.

## Validate before reporting done

Two collect-all checks; **both return a tuple of `ValidationIssue` and never raise** — an empty tuple means clean. Run them after `.build()`/`.execute()` instead of trusting a clean terminal call (hard rule 4):

```python
from datalens_sdk import recipes

dashboard.validate()
# offline, no HTTP: duplicate ids, out-of-grid and overlapping items, empty chart
# ids, item/layout coverage, undersized alias groups

recipes.validate_dashboard_refs(client, dashboard)
# HTTP: referenced chart ids exist; selector datasetId/datasetFieldId exist;
# wizard-chart dataset references resolve; manual selectors bind a real dataset
# parameter (with did-you-mean suggestions); dangling alias fields.
# Distinguishes missing_* from access_denied; network/server errors DO propagate.
```

Each `ValidationIssue` carries `kind`, `tab_id`, `item_id`, `message`, and `suggestions`. Fix and re-check until both tuples are empty.

For manual selectors targeting QL or Editor parameters, read the validation
boundary in [parameters.md](parameters.md): the HTTP recipe can automatically
prove Dataset parameter declarations only.

## Inspect an existing dashboard before updating

`client.get.dashboard(...)` returns a typed, tolerant read model. Use it to
discover ids from UI-created or third-party dashboards instead of guessing or
searching the full `dashboard.raw` payload:

| Read view | What it exposes |
|---|---|
| `dashboard.tabs` | `DashboardTabView` objects |
| `tab.id`, `tab.title`, `tab.hidden` | stable tab identity and display state |
| `tab.items` / `tab.global_items` | local / shared `DashboardItemView` objects |
| `item.id`, `item.item_type`, `item.data`, `item.defaults` | update handle and tolerant item payload |
| `tab.controls` | normalized local + shared `ControlView` wrappers |
| `control.id`, `control.members`, `control.member(id)` | wrapper and selector-member discovery |
| `member.id`, `member.source`, `member.defaults` | selector update/connection handle and source |
| `tab.layout` | `DashboardLayoutItemView`: `item_id`, `x`, `y`, `w`, `h`, `parent` |
| `tab.connections`, `tab.aliases`, `tab.settings` | current tab wiring and settings |

```python
from collections.abc import Mapping

dashboard = client.get.dashboard(by_id=dashboard_id, branch="saved")
for tab in dashboard.tabs:
    print("tab", tab.id, tab.title)
    for item in (*tab.items, *tab.global_items):
        print("item", item.id, item.item_type)
        if item.item_type == "widget":
            for chart_tab in item.data.get("tabs", ()):
                if isinstance(chart_tab, Mapping):
                    print("  chart tab", chart_tab.get("id"), chart_tab.get("chartId"))
    for control in tab.controls:
        print("selector wrapper", control.id)
        for member in control.members:
            print("  member", member.id, member.source.param_name, member.source.dataset_field_id)
```

Use the ids deliberately:

- item/wrapper id → `remove_item`, layout operations, `replace_chart`,
  `set_chart_params`;
- selector member id → `update_selector`, `remove_selector`, connections;
- internal chart-tab id from `item.data["tabs"]` → multi-tab connection
  endpoints and `replace_chart(widget_tab_id=...)`.

Connections serialize widget endpoints as internal chart-tab ids, not the
outer widget id. Create-side `add_connection` accepts the logical widget id
and expands it; when inspecting or removing existing wire connections, use
the ids shown by the read model.

## Updating an existing dashboard

`get` → `.update` (a property, fresh builder) → chain operations → `.execute(publish=, lock_token=)`:

```python
dash = client.get.dashboard(by_id=dashboard_id, branch="saved")
dash = dash.refresh(branch="saved")  # re-pull the draft right before editing

dash = (
    dash.update.add_chart(new_chart, tab="Overview", item_id="conversion_chart", size=(12, 12))
    .add_selector(tab="Overview", item_id="flt_city", dataset=ds, field=ds.fields.by_name("City"), multiselect=True)
    .resize_item("gmv", h=14)
    .remove_item("note")
    .execute(publish=True)  # publish= is REQUIRED and keyword-only
)

issues = dash.validate()
assert not issues, issues
```

`publish=True` persists **and** publishes in one call; `publish=False` saves a draft revision (check `dash.is_draft`; publish later with `dash.publish_revision()`).

Update-only operations beyond the tab-builder set (all `add_*` content methods
exist here too, taking `tab=` — a tab id or title): `add_tab` / `remove_tab` /
`reorder_tabs` / `hide_tab` / `show_tab` / `update_tab`; `remove_item` /
`replace_chart` / `set_chart_params`; `move_item` / `resize_item` /
`swap_items` / `shift_below` / `compact_layout` / `apply_layout`; `pin_item` /
`unpin_item`; `add_selector_to_group` / `update_selector` / `remove_selector`;
`remove_connection` /
`disconnect_all` / `remove_alias`; `settings(...)` (tri-state `UNSET`
semantics — see core-concepts) / `global_params(...)` (supports
`REMOVE_PARAM`) / `description` / `access_description` /
`support_description`.

`update_selector(item_id=...)` point-patches only `title`, `default_value`,
`operation`, `required`, and `hint`. External selectors support only
`title`/`hint`. `set_chart_params` merge/replacement and multi-tab behavior
are covered in [parameters.md](parameters.md).

### Append a selector to an existing group

Use the group's wrapper id from `tab.controls`, choose a new semantic member
id, and call `add_selector_to_group`. It accepts the dataset/manual selector
arguments from `add_selector`, but intentionally does not accept `chart=`:
external selectors cannot be group members. The new member is immediately
available to later connection operations in the same chain.

```python
dash = client.get.dashboard(by_id=dashboard_id, branch="saved")
group = next(control for tab in dash.tabs for control in tab.controls if control.id == "filters")
assert all(member.id != "flt_city" for member in group.members)

dash = (
    dash.refresh(branch="saved")
    .update.add_selector_to_group(
        group_item_id="filters",
        item_id="flt_city",
        dataset=ds,
        field=ds.fields.by_name("City"),
        element="select",
        multiselect=True,
    )
    .resize_item("filters", h=4)
    .add_connection(from_item="conversion_chart", to_item="flt_city")
    .execute(publish=False)
)
```

This is a typed in-place append: it preserves existing members, wrapper
settings, layout, and shared copies. Do not remove/rebuild the group and do
not use raw replacement for this operation.

### Concurrency: last-write-wins, no lock API

- The server has **no optimistic locking**. `execute()` writes your full snapshot; a stale one silently overwrites concurrent edits. Mitigate by calling `dash.refresh(branch="saved")` immediately before editing a draft (or `refresh()` when the default branch is intentional) and keeping the builder short-lived.
- There is **no lock-acquisition API** in the SDK. If someone is editing the entry in the UI, any write raises `LockedError` (423) immediately — do not retry in a loop; report it and wait for the user (`lock_token=` on `execute`/`delete`/`publish_revision` is pass-through only, for tokens obtained elsewhere).

### Rename and delete

```python
dash = dash.rename("Rides overview v2")  # returns the renamed Dashboard
dash.delete()  # hard rule 6: confirm first; accepts lock_token=
```

## Related references

- [Dashboard settings](https://yandex.cloud/ru/docs/datalens/dashboard/settings) —
  product behavior for tabs, loading, mobile display, and pinned zones
- [Selectors](https://yandex.cloud/ru/docs/datalens/dashboard/selector) —
  cross-tab selector behavior and selector groups
- [Widgets](https://yandex.cloud/ru/docs/datalens/dashboard/widget) —
  product-level widget types
- [Connections](https://yandex.cloud/ru/docs/datalens/dashboard/link) —
  selector/widget influence and aliases
- [Dashboard parameters](https://yandex.cloud/ru/docs/datalens/dashboard/dashboard_parameters) —
  product precedence and dashboard/widget parameter scope
- [parameters.md](parameters.md) — SDK parameter flow across Dataset, QL,
  Editor, widgets, dashboard settings, selectors, and action params
- [core-concepts.md](core-concepts.md) — builders and terminal calls, `UNSET`/`REMOVE_PARAM`, locations, the update contract
- [wizard-charts/_index.md](wizard-charts/_index.md) — building the charts a dashboard references
- [serialization.md](serialization.md) — `to_file(with_dependencies=True)`, cloning via `client.raw`
- [troubleshooting.md](troubleshooting.md) — `LockedError`, 409 adoption, every other API error
- [design-guide.md](design-guide.md) — composition: what to put where and how to size it
