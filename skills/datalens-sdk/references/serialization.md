# Serialization: export, import, clone

Read this when you need to export an entity to files, import one from an artifact, clone an entity in memory, or copy entities across workbooks and folders — everything that goes through `to_file()` and `client.raw`.

## The snapshot is the unit of exchange

Every fetched entity carries `response_snapshot` — an owned snapshot of the JSON object the server returned. `to_file()` writes it to disk; `client.raw` consumes it (in memory or from disk). Editor RPCs no longer expose `entry.data.secrets`; as a defensive compatibility measure, the SDK still removes that block if a legacy snapshot or unexpected response contains it. Two consequences:

- **Only a `client.get.*` result is complete enough.** Snapshots are validated on capture: a chart snapshot must contain full `data`, an id, and a wire type; a dataset snapshot must contain the full `dataset` content. Objects returned by `create` builders fail this validation (the create response omits content) with a message telling you to fetch via `client.get.<resource>(...)` first.
- **The snapshot is opaque and transport-oriented.** Do not build one by hand; fetch, optionally patch (see the cross-workbook recipe), and feed it back. Revisions, counters, service metadata, and representation details may change after a create or update, so snapshots are not stable byte-for-byte equality targets.

## Exporting: `entity.to_file(path)`

Verified signatures (all return `pathlib.Path` — the artifact directory):

```python
connection.to_file(path)
dataset.to_file(path)
wizard_chart.to_file(path)  # same for ql_chart
editor_chart.to_file(path, split_tabs=False)
dashboard.to_file(path, with_dependencies=False)
```

`path` is the **parent** directory and must already exist (create it yourself; a missing parent raises `DataLensValidationError`). The artifact itself is a directory named `<name> [<id>]` (both components sanitized for portability) containing one main JSON file:

| Entity | Main file |
|---|---|
| connection | `connection.json` |
| dataset | `dataset.json` |
| chart (any family) | `chart.json` |
| dashboard | `dashboard.json` |

Export **never overwrites**: if the artifact directory already exists, `to_file` raises `DataLensValidationError` ("Artifact path already exists"). Re-exporting the same entity requires removing the old artifact or using a fresh parent. The write is atomic — you never observe a half-written artifact.

### Editor charts: `split_tabs=True`

`editor_chart.to_file(path, split_tabs=True)` additionally writes a `Tabs/` directory with one file per editor tab (`.js`, documentation tabs as `.md`) — **for human review only**. Only `chart.json` is importable; edits under `Tabs/` are ignored by `from_file`. `split_tabs=True` on a non-editor chart raises `DataLensValidationError`.

### Dashboards: `with_dependencies=True`

`dashboard.to_file(path, with_dependencies=True)` walks the server-side relations of the dashboard (its widget charts, plus the datasets of the dashboard and of each chart) and writes a bundle:

```
My Dash [abc123]/
  dashboard.json
  charts/
    Sales trend [ch1id]/chart.json
    ...
  datasets/
    Sales [ds1id]/dataset.json
    ...
```

Facts to keep straight about bundles:

- **Connections are never included.** Not in dashboard bundles, not anywhere — there is no bundle that carries a connection.
- **No cross-resource revision consistency.** Each dependency is fetched by its own `get` call at its current default revision; if someone saves a chart mid-export, the bundle mixes revisions.
- The dashboard object must be client-bound (fetched via `client.get.dashboard`) — dependency discovery makes API calls.

## Importing: `client.raw`

`client.raw` has two sub-namespaces, each with six resource factories: `connection`, `dataset`, `dashboard`, `wizard_chart`, `editor_chart`, `ql_chart`.

| Call shape | Returns | Terminal call |
|---|---|---|
| `client.raw.create.<resource>(response_snapshot=..., name=..., location=...)` | create builder | `.build()` → new entity |
| `client.raw.create.<resource>.from_file(path, name=..., location=...)` | create builder | `.build()` |
| `client.raw.replace.<resource>(target=..., response_snapshot=...)` | replace builder | `.execute()` → updated entity |
| `client.raw.replace.<resource>.from_file(path, target=...)` | replace builder | `.execute()` |

So each factory is *callable* (in-memory snapshot) and also has a `.from_file(...)` method (artifact on disk); both return the same builder, and — as everywhere in the SDK — nothing persists until the terminal call. Resource-specific extras:

- **connection** create and replace accept `overrides=` — a mapping merged over the snapshot-derived payload. Identity, location, connector, and server-owned keys are rejected in overrides.
- **dashboard** replace terminates with `.execute(publish=..., lock_token=None)` — `publish` is a required keyword, same as dashboard updates.
- **chart** replace supports `.mode("save" | "publish")` before `.execute()` (default `"save"`).

For `from_file`, `path` is the **artifact directory** (`My Dash [abc123]/`), not the JSON file inside it. Chart artifacts are category-checked: loading a wizard artifact through `client.raw.create.ql_chart.from_file` raises `DataLensValidationError`.

Builders validate at construction time, before any HTTP: snapshot completeness, entry name rules, and installation — you cannot replace a `yacloud` entity through an `enterprise` client, replace a connection with a snapshot of a different connector type, or replace a chart with a snapshot of a different category/wire type.

### In-memory clone

```python
src = client.get.dataset(by_id=source_id)  # complete snapshot
clone = client.raw.create.dataset(
    response_snapshot=src.response_snapshot,
    name=f"{src.name} clone",
    location=EntryLocation.workbook(target_workbook_id),
).build()
```

### File-based import

```python
restored = client.raw.create.dashboard.from_file(
    "artifacts/My Dash [abc123]",  # the artifact directory
    name="My Dash restored",
    location=EntryLocation.path("Users/me/restored"),
).build()
```

### Connection snapshots have no secrets

The API never returns connection credentials, so an exported or in-memory connection snapshot lacks the password/token. A cloned connection is created without them — supply credentials through `overrides=` with values read from the environment (hard rule 3: never a literal in code, never echoed), or tell the user to re-enter them in the UI:

```python
clone = client.raw.create.connection(
    response_snapshot=src.response_snapshot,
    name=f"{src.name} clone",
    location=EntryLocation.workbook(wb_id),
    overrides={"password": os.environ["CH_PASSWORD"]},
).build()
```

## The export/import asymmetry

Export is richer than import. State this plainly to users before they rely on bundles as backups:

- **Dependency bundles are export-only.** `from_file` reads only the main JSON; `charts/`, `datasets/`, and `Tabs/` are ignored. Importing a dashboard bundle creates the dashboard — it does not create, restore, or touch its charts and datasets.
- **No id remapping.** An imported dashboard still references the *original* chart ids; an imported chart still references the *original* dataset id; an imported dataset still references the *original* connection id. If those entities exist and are accessible, the clone works against them (shared dependencies); if not, the server accepts the import **silently** and the entity renders broken.
- **Connections are never included** in any bundle, and their snapshots carry no secrets.
- **No cross-resource revision consistency** in a bundle — each file is an independent fetch.

After importing a dashboard, verify it (hard rule 4). `datalens_sdk.recipes` has one serialization-relevant helper for exactly this:

```python
from datalens_sdk.recipes import validate_dashboard_refs

issues = validate_dashboard_refs(client, client.get.dashboard(by_id=new_dash.id))
# tuple[ValidationIssue, ...] — never raises; empty tuple means no broken refs.
# Catches: missing/forbidden charts and datasets, selectors bound to
# nonexistent dataset fields, unbound manual selectors, dangling aliases.
```

## `raw.replace` is destructive — hard rule 6

`raw.replace` sends the snapshot's content to the target id. It does **not** fetch the target's current state, does **not** merge, and does **not** check for conflicts — pure last-write-wins. Everything on the target that is not in the snapshot is gone after `.execute()`; concurrent edits are silently overwritten. The target keeps its own id, name, and location — only the content is replaced.

Per the skill's hard rules, before constructing any `raw.replace` builder:

1. Get **explicit user approval**, naming the exact entity (id + name) that will be overwritten.
2. Double-check the target id — replace onto the wrong id is unrecoverable through the SDK.
3. Export the target first (`target.to_file(backup_dir)`) so a rollback artifact exists.

```python
target = client.get.dashboard(by_id=target_id)  # confirm this is the right one
target.to_file("backups")  # rollback artifact
client.raw.replace.dashboard.from_file(
    "artifacts/My Dash [abc123]",
    target=target,
).execute(publish=False)
```

## Recipe: clone across workbooks

Bottom-up, in dependency order, patching ids as you go — because `raw.create` never remaps them for you. Shown for a dataset + wizard chart pair; extend the same pattern per entity:

Inventory the target workbook before creating anything. Check collisions only for the names and scopes this clone will create, adopt an exact existing match on `ConflictError`, and preserve every unrelated target entry. A target workbook is not required to be empty, and an exact total-entry-count assertion is not a valid clone check.

```python
import json

src_ds = client.get.dataset(by_id=dataset_id)
src_ch = client.get.wizard_chart(by_id=chart_id)
target = EntryLocation.workbook(target_workbook_id)

# 1. Clone the dataset (still points at the original connection —
#    fine when the connection is shared/accessible from the target).
new_ds = client.raw.create.dataset(
    response_snapshot=src_ds.response_snapshot,
    name=src_ds.name,
    location=target,
).build()

# 2. Patch the chart snapshot: swap every occurrence of the old dataset id
#    for the new one (ids are opaque strings — textual replace is safe).
patched = json.loads(json.dumps(src_ch.response_snapshot).replace(src_ds.id, new_ds.id))

# 3. Clone the chart against the cloned dataset.
new_ch = client.raw.create.wizard_chart(
    response_snapshot=patched,
    name=src_ch.name,
    location=target,
).build()

# 4. Verify (hard rule 4): re-fetch and confirm the business reference moved.
check = client.get.wizard_chart(by_id=new_ch.id)
assert src_ds.id not in json.dumps(check.response_snapshot)
```

For a dashboard on top, repeat step 2–3 with the dashboard snapshot, replacing each old chart id with its clone's id, then run `validate_dashboard_refs` on the result. If you skip the patching, the clones keep pointing at the originals — acceptable when you *want* shared dependencies, broken when the originals are deleted or inaccessible from the target.

Verify clones through stable business invariants: the requested names/scopes exist exactly once, the old-to-new id map is complete, cloned charts and dashboards reference the remapped ids, expected shared connections remain shared, and both dashboard validators are clean. Do not compare complete `response_snapshot` values, revision ids, counters, or service-owned metadata with the source.

Name collisions on import behave like any create: same name in the same location raises `ConflictError` — adopt the existing entry, do not mint `name-2` copies (hard rule 7). Inspect `e.context.status_code` for diagnostics rather than assuming it is always 409.

## Related references

- [core-concepts.md](core-concepts.md) — `client.raw` in the namespace map, locations, lifecycle
- [navigation.md](navigation.md) — finding source entities and target workbooks/folders
- [troubleshooting.md](troubleshooting.md) — `DataLensValidationError`, conflict adoption, any API error
