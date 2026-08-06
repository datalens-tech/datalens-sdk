# Core concepts

Read this when the object model is unclear: client namespaces, the entity lifecycle, locations, field references, retries, pagination, or the update sentinels.

## One client, four namespaces

Every configured client exposes the same namespace model:

| Namespace                                | Role                             | Terminal call              |
|------------------------------------------|----------------------------------|----------------------------|
| `client.get.*`                           | fetch one entity by id           | returns the object         |
| `client.create.*`                        | fluent builders for new entities | `.build()`                 |
| `obj.update` / `.rename()` / `.delete()` | mutate a fetched object          | `.execute()` (update only) |
| `client.navigation` / `client.raw`       | listing / snapshot import-export | —                          |

### `client.get.*` — by id only

Getters take keyword-only arguments and require an id. There is **no key- or name-based lookup** here — to find an entity by name, list with `client.navigation.get_entries(name=...)` and then `get` by the id you found.

```python
conn = client.get.connection(by_id="...", workbook_id=None, rev_id=None)
ds = client.get.dataset(by_id="...", workbook_id=None, rev_id=None)
wch = client.get.wizard_chart(by_id="...")  # also: editor_chart, ql_chart
ch = client.get.chart(by_id="...")  # returns WizardChart | EditorChart | QLChart
dash = client.get.dashboard(by_id="...")
col = client.get.collection(by_id="...")
wb = client.get.workbook(by_id="...")
fold = client.get.folder(by_path="Users/someone/dir")  # the one path-based getter
```

Chart and dashboard getters additionally accept `branch=` (`"saved"` or `"published"`) and `rev_id=`. Passing **both** `rev_id=` and `branch=` emits a `UserWarning` and silently drops `branch` — an explicit `rev_id` already pins the revision. Do not pass both.

### `client.create.*` — fluent builders, terminal `.build()`

Builders accumulate state and persist nothing until `.build()`. A chain without `.build()` "succeeds" and creates nothing.

```python
conn = client.create.connection.clickhouse(name="prod-ch", location=wb).host("ch.example.net").port(8443).build()
src = client.create.source(using=conn).ch_table(alias="sales", db_name="samples", table_name="sales").build()
ds = client.create.dataset(name="Sales", location=wb).sources([src]).build()
ds = client.get.dataset(by_id=ds.id)
chart = (
    client.create.wizard_chart.line(name="Trend", location=wb)
    .dataset(ds)
    .x([ds.fields.by_name("Date")])
    .y([ds.fields.by_name("Sales")])
    .build()
)
dashboard = client.create.dashboard(name="Overview", location=wb).add_tab(...).build()
col = client.create.collection(name="Team", parent=None).build()
wb2 = client.create.workbook(name="Q3", collection=col).build()
fold = client.create.folder(
    name="probes",
    location=EntryLocation.path("Users/me"),
).build()
```

Connection types (`client.create.connection.<type>`), dataset source types (`client.create.source(using=conn).<type>`), and editor chart node types are generated per installation; `client.capabilities` lists what your client actually has (see below). Chart families each have their own factory: `client.create.wizard_chart.<viz>`, `client.create.ql_chart.<viz>`, `client.create.editor_chart.<node>` — routing and per-type placeholders live in the chart references.

### Updating, renaming, deleting a fetched object

`update` is a **property** that returns a fresh builder; the terminal call is `.execute()`, which returns the updated object:

```python
ds = client.get.dataset(by_id=dataset_id)
ds = ds.update.add_calculation(
    name="Margin",
    formula="SUM([Profit]) / SUM([Sales])",
    kind="MEASURE",
).execute()

cht = cht.update.palette(id="datalens-neo-20").execute()

dash = dash.update.settings(hide_tabs=True).execute(publish=True)  # dashboards require publish=
```

Every entity also has direct `rename(name)` (returns the renamed object) and `delete()` methods. `Dashboard.delete()` additionally accepts `lock_token=`. Dashboard updates are **last-write-wins** — the server has no optimistic locking, so call `dash.refresh()` right before `.update` and keep the builder short-lived, or concurrent edits are silently overwritten.

### `client.navigation.get_entries()` — a lazy, re-iterable `Pager`

```python
pager = client.navigation.get_entries(scope="dataset", name="Sales", page_size=100)
for entry in pager:  # EntrySummary: .id, .scope, .type, .name, .key, .workbook_id, ...
    print(entry.id, entry.name)
```

`Pager` holds a loader, not results: nothing is fetched until you iterate, and **each iteration replays the query from the first page** (fresh HTTP calls — cheap to pass around, not a cache). `pager.pages()` yields `Page` objects (`.items`, `.next_page_token`) when you need page granularity. Useful filters: `ids=`, `created_by=`, `name=`, `scope=` (`"dataset"`, `"widget"`, `"dash"`, `"connection"`, `"folder"`), `type=`, `order_by=`/`order_direction=`, `exclude_locked=`.

### `client.raw` — snapshot-level create and replace

`client.raw.create.*` and `client.raw.replace.*` (for `connection`, `dataset`, `dashboard`, `wizard_chart`, `editor_chart`, `ql_chart`) work on full response snapshots, either passed as `response_snapshot=` or loaded with `.from_file(path, ...)` from an artifact written by an entity's `to_file()`. `raw.replace` is last-write-wins with no conflict check — hard rule 6 applies. Export, import, and clone workflows: [serialization.md](serialization.md).

### `client.capabilities` and installation gating

`client.capabilities` returns the exact surface generated for this client's
installation, grouped under four keys:

```python
capabilities = client.capabilities
capabilities["connectors"]  # connection factory metadata by factory name
capabilities["dataset_sources"]  # source factory metadata by factory name
capabilities["chart_factories"]  # {"wizard": [...], "ql": [...], "editor": [...]}
capabilities["namespaces"]  # available top-level client namespaces
```

Choose a chart family first, then check its factory name in
`capabilities["chart_factories"][family]`. Treat these local generated
inventories as authoritative; do not infer availability from a reference table
or another installation.

Accessing a namespace the installation does not have raises `NotSupportedError` whose message names where it *is* available:

```python
client.licenses
# NotSupportedError: Namespace 'licenses' is not available on this installation
```

`NotSupportedError` subclasses `AttributeError`, so `hasattr(client, "licenses")` is a safe feature probe. The same error guards cross-installation destinations (e.g. passing a `yacloud` workbook to an `enterprise` client).

## The entity lifecycle chain

Entities form a dependency chain; build left to right and reference by object or id:

```
connection -> source -> dataset -> chart -> dashboard
                        (fields)    (wizard | ql | editor)
```

- A **source** is not a standalone entity: `client.create.source(using=conn)` binds a table/query of a connection, and the built `Source` is fed to a dataset builder via `.add_source(...)`.
- A **dataset** owns fields (dimensions, measures, calculations, parameters).
- A **wizard chart** binds one dataset with `.dataset(ds)` and places fields into placeholders; QL charts skip datasets and query a connection directly; editor charts are hand-written code.
- A **dashboard** references charts by id and adds tabs, selectors, and layout.

## Locations: where an entity lives

Every `create` builder takes a destination. Construct one explicitly:

```python
from datalens_sdk import EntryLocation

EntryLocation.path("Users/me/reports")  # folder tree (path-based installations)
EntryLocation.workbook(workbook_id)  # inside a workbook
EntryLocation.collection(collection_id)  # inside a collection (workbook/collection creation)
```

`Workbook`, `Collection`, and `Folder` objects **are** `EntryLocation`s — pass a fetched or just-created object directly, no id plumbing:

```python
wb = client.create.workbook(name="Q3", collection=col).build()  # col: Collection object
ds = client.create.dataset(name="Sales", location=wb).build()  # wb: Workbook object
```

For a path-located entity, `name` must not contain `/` — the directory goes in the location, the leaf name in `name=`.

## Field references in chart builders

Two conventions, one rule:

1. **Dataset fields → pass `DatasetField` objects.** Fetch the dataset, then `dataset.fields.by_name("Sales")` or `.by_guid(...)`. This is unambiguous and carries the full field snapshot.
2. **Chart-local fields → pass their title strings.** Fields born inside the same builder chain — `add_local_field(title=..., formula=...)`, `add_hierarchy(title, fields)`, `add_aggregated_measure(field, aggregation=..., name=...)` — have no `DatasetField` object yet; refer to them by the exact title you gave them.

```python
ds = client.get.dataset(by_id=dataset_id)
chart = (
    client.create.wizard_chart.column(name="Sales by City", location=wb)
    .dataset(ds)
    .add_local_field(
        title="AOV",
        formula="SUM([Sales]) / COUNTD([Order ID])",
        measure=True,
    )
    .x([ds.fields.by_name("City")])  # dataset field -> DatasetField object
    .y(["AOV"])  # chart-local field -> its title string
    .build()
)
```

Strings *can* also resolve against the bound dataset schema (guid first, then title/name), but a title shared by several fields raises `DatalensValidationError` ("ambiguous"), and on the update path only already-placed fields are known — so `DatasetField` objects are the reliable form for anything that lives in the dataset. Unresolvable strings fail at build/execute time with a message that suggests close matches and the `fields.by_name` pattern.

## Critical behaviors

### No server idempotency — adopt on 409

Re-running a successful create raises `ConflictError` (409, `ENTRY_ALREADY_EXISTS`): same name in the same location. Never work around it by creating `name-2` copies — find the existing entry (via `client.navigation.get_entries(name=..., scope=...)`), `get` it, and continue with it. The full pattern with code: [troubleshooting.md](troubleshooting.md).

### Re-`get` a dataset after creating it

The `createDataset` response omits field snapshots. After `client.create.dataset(...).build()`, re-fetch with `client.get.dataset(by_id=ds.id)` **before any field operation** — `fields.by_name` on the create result will not see the schema.

### `.build()` / `.execute()` confirm persistence, not correctness

A clean terminal call means the server stored the entity — not that it renders, has the right fields, or queries successfully. Verify: re-`get` the entity and inspect the parts that matter (fields, placeholders, dataset ids) before reporting done.

Keep the mutation boundary separate from local verification. Once
`.build()`/`.execute()` returns, a later `AssertionError`, `AttributeError`, or
other verifier bug does not roll the server write back. Re-fetch the object and
rerun only the corrected read-only checks. Re-executing the mutation can create
duplicates, publish extra revisions, or reapply non-idempotent actions.

### Retries: writes are never retried by default

The transport picks a `RetryPolicy` per operation:

- **Writes** (create/update/delete/validate) use the default policy with `max_attempts=1` — one shot, no retry.
- **Reads** (all getters, listings) use an internal 3-attempt policy with exponential backoff, retrying 429/5xx and transport errors automatically.

The retry policy is not a constructor knob. To change write retries you must inject a custom transport via `http_client=` (an object implementing `post_json`/`post_json_object` that overrides `retry_policy` before delegating). `http_client=` is mutually exclusive with `auth=`, `base_url=`, `transport=`, and `event_hooks=` — combining them raises `DatalensConfigurationError`. Think twice: creates are not idempotent, so blind write retries can produce 409s.

### `UNSET` and `REMOVE_PARAM` — tri-state update channels

Dashboard update settings distinguish three intents: `UNSET` (default — leave the setting untouched), `None`/a value (write it), and, inside `settings.globalParams` merges, the `REMOVE_PARAM` sentinel (delete this key):

```python
from datalens_sdk import REMOVE_PARAM, UNSET

dash.update.settings(hide_tabs=True).execute(publish=False)  # others stay UNSET
dash.update.global_params({"region": REMOVE_PARAM}).execute(publish=False)
```

Never substitute `None` for "remove" or "skip" — `None` is a written value; `UNSET` skips; `REMOVE_PARAM` deletes.

## Related references

- [setup.md](setup.md) — environment, auth providers, env-var contract
- [connections.md](connections.md) — connection and source types per installation
- [datasets.md](datasets.md) — the field/action update DSL, joins, parameters, RLS
- [wizard-charts/_index.md](wizard-charts/_index.md), [ql-charts/_index.md](ql-charts/_index.md), [editor-charts/_index.md](editor-charts/_index.md) — chart families
- [dashboards.md](dashboards.md) — tabs, widgets, selectors, layout
- [navigation.md](navigation.md) — finding, listing, and moving entities
- [serialization.md](serialization.md) — export, import, clone via `to_file` and `client.raw`
- [troubleshooting.md](troubleshooting.md) — every error, before retrying anything
