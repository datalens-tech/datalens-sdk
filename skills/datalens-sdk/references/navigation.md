# Navigation

Read this when you need to find, list, move, or rename entities, or manage the containers they live in: collections, workbooks, and folders.

## The container model

Two organizational schemes coexist, per installation:

- **Collections and workbooks** — a collection tree holds workbooks; a workbook holds entries (connections, datasets, charts, dashboards).
- **Folders** — a path-based directory tree (`Users/someone/reports`) that holds entries directly. Only installations with a directory tree have usable folders; check `client.capabilities["namespaces"]` before relying on them, and see [core-concepts.md](core-concepts.md) for `NotSupportedError` gating.

`Collection`, `Workbook`, and `Folder` objects are all `EntryLocation`s — pass them directly as `location=` / `collection=` / `parent=` to any create builder or `move()`, no id plumbing.

## Global listing: `client.navigation.get_entries()`

Returns a `Pager[EntrySummary]` over every entry visible to you, with server-side filters:

```python
pager = client.navigation.get_entries(
    ids=[...],  # exact ids
    created_by=[...],  # author filter
    name="Sales",  # name filter (narrows; do exact match client-side)
    scope="dataset",  # one EntryScope (single value; see the complete list below)
    type=None,  # entry subtype, e.g. "d3_wizard_node"
    exclude_locked=True,
    ignore_shared_entries=None,
    ignore_workbook_entries=None,  # skip entries that live inside workbooks
    include_data=None,  # populate .data
    include_links=None,  # populate .links
    include_permissions_info=None,  # populate .permissions
    order_by="name",  # "name" | "created_at"
    order_direction="asc",  # "asc" | "desc"
    page_size=100,  # default 100
)
for entry in pager:  # EntrySummary
    print(entry.id, entry.scope, entry.name, entry.workbook_id)
```

`EntrySummary` carries `.id`, `.scope`, `.type`, `.name`, `.key` (path, on folder installations), `.workbook_id`, `.collection_id`, `.created_by`/`.created_at`, `.updated_by`/`.updated_at`, `.saved_id`/`.published_id`, `.hidden`, `.is_favorite`, `.is_locked`, plus `.data`/`.links`/`.permissions` (populated only when the matching `include_*` flag is on) and `.raw`. Some listing endpoints return a path-qualified `.name` such as `Folder/Sales`; derive the display leaf with `entry.name.rsplit("/", 1)[-1]` when matching by the user-visible name.

`EntryScope` accepts `"dash"`, `"report"`, `"widget"`, `"dataset"`,
`"folder"`, `"connection"`, `"compute"`, `"artifact"`, and `"sql_query"`.
Write-side scope filters are closed to this set: an unsupported value raises
`DataLensValidationError` before a pager is created or HTTP is sent. Read-side
`.scope` remains a string so newer backend values can still be inspected.

### Pager semantics — lazy and re-iterable

A `Pager` holds a loader, not results:

- Nothing is fetched until you iterate.
- Each iteration **replays the query from page 1** with fresh HTTP calls — cheap to pass around, but not a cache; materialize with `list(pager)` if you iterate twice over live data.
- `pager.pages()` yields `Page` objects (`.items`, `.next_page_token`) when you need page granularity:

```python
for page in pager.pages():
    print(len(page.items), page.next_page_token)
```

## Listing inside a container

Each container object lists its own contents; same lazy-pager semantics:

| Call | Returns | Items |
|---|---|---|
| `folder.list_entries(...)` | `DirectoryPager[EntrySummary]` | entries in the directory |
| `collection.list_entries(...)` | `Pager[StructureSummary]` | mixed `CollectionSummary` \| `WorkbookSummary` \| `EntrySummary` |
| `workbook.list_entries(...)` | `Pager[EntrySummary]` | entries in the workbook |

```python
wb = client.get.workbook(by_id=workbook_id)
for entry in wb.list_entries(scope=["widget", "dataset"], name="Sales", order_by="name"):
    print(entry.id, entry.scope, entry.name)
# workbook filters: created_by=, name=, include_permissions_info=, order_by=,
#                   order_direction=, page_size=, scope= (EntryScope or sequence)

col = client.get.collection(by_id=collection_id)
from datalens_sdk import CollectionSummary, WorkbookSummary

for item in col.list_entries(mode="all"):  # "all" | "collections" | "workbooks" | "entries"
    kind = (
        "collection"
        if isinstance(item, CollectionSummary)
        else "workbook"
        if isinstance(item, WorkbookSummary)
        else "entry"
    )
    print(kind, item.id, item.name)
# collection filters: filter_string=, only_my=, include_permissions_info=,
#                     order_by= ("name" | "created_at" | "updated_at"), order_direction=, page_size=
```

`Folder.list_entries()` is the one that returns a `DirectoryPager`: its `.pages()` yields `DirectoryPage` objects that add `.breadcrumbs` — the chain of `DirectoryBreadcrumb` (`.id`, `.name`, `.path`) from the root down to this directory:

```python
folder = client.get.folder(by_path="Users/someone/reports")
for page in folder.list_entries(scope=("dataset", "widget"), order_by="name").pages():
    print(" > ".join(crumb.name for crumb in page.breadcrumbs))
    for entry in page.items:
        print(" ", entry.id, entry.name)
```

Folder filters are `created_by=`, `name=`, `include_permissions_info=`,
`order_by=`, `order_direction=`, `page_size=`, and `scope=` (one `EntryScope`
or a sequence of them). For both folder and workbook listings, an empty scope
sequence omits the filter.

## Finding or recovering an entity safely

Names are not unique identities. Entity getters are id-only
(`client.get.folder(by_path=...)` is the single path-based exception), so a
find-by-name or post-create recovery is list, verify, then get by id. Keep the
id returned by a successful `.build()` or `.execute()` whenever possible. If
later local code fails, re-fetch that id instead of searching or repeating the
write.

When the id was lost or the write outcome is uncertain, start from the known
destination container. Both container models are first-class:

```python
def display_name(entry):
    return entry.name.rsplit("/", 1)[-1] if entry.name is not None else None


if workbook_id is not None:
    container = client.get.workbook(by_id=workbook_id)
elif folder_path is not None:
    container = client.get.folder(by_path=folder_path)
else:
    raise LookupError("A workbook id or folder path is required to recover the entry safely")

summaries = [
    entry
    for entry in container.list_entries(name="Sales", scope="widget")
    if display_name(entry) == "Sales" and entry.type == "d3_wizard_node"
]
```

`workbook.list_entries()` and `folder.list_entries()` accept `name`, `scope`,
and `created_by`, but not `type`; check `EntrySummary.type` on the returned
candidates. The current SDK creates line charts as `d3_wizard_node`; when
recovering a known legacy chart, use its exact expected legacy type rather than
accepting every widget. Global `client.navigation.get_entries()` accepts
`type`, but has no `workbook_id`, folder, or `dataset_id` filters. Use it only when the
container is unknown, then verify `EntrySummary.workbook_id` or the full
folder path in `EntrySummary.key` on every candidate.

Apply every reliable discriminator already known from the attempted create or
the surrounding task. For a Wizard line chart backed by a known dataset:

```python
verified = []
for summary in summaries:
    chart = client.get.wizard_chart(by_id=summary.id)
    if chart.visualization_id != "line":
        continue
    if set(chart.dataset_ids) != {dataset_id}:
        continue
    verified.append(chart)

if len(verified) != 1:
    candidate_ids = [summary.id for summary in summaries]
    raise LookupError(
        f"Expected one fully verified chart, found {len(verified)}: {candidate_ids}; "
        "require the exact id before mutating another object"
    )
chart = verified[0]
```

For another chart family or entity type, use its typed getter and stable
properties. When the object does not expose direct dataset ids, compare the
complete expected set with
`{rel.id for rel in obj.get_relations(link_direction="from", scope="dataset")}`.
If only part of the dependency set is known, membership can narrow candidates
but cannot by itself prove identity. `created_by` and timestamps can narrow or
support the search, but they do not override a remaining ambiguity.

Continue to an update, dashboard attachment, or conflict adoption only when
exactly one candidate matches the container, exact display-name leaf, scope,
stable entry type when available, typed object kind, and every known dependency. Zero matches means
the object was not recovered; multiple matches require the user to provide the
exact id. Never choose the first, newest, or merely visible result.

## Relations: what an entry depends on

Every entry object (`Connection`, `Dataset`, `Dashboard`, and all chart types) exposes `get_relations()` — the linked entries, e.g. the dataset and connection behind a chart, or the charts built on a dataset. Containers (`Folder`, `Collection`, `Workbook`) do **not** have it.

```python
ds = client.get.dataset(by_id=dataset_id)
for rel in ds.get_relations():  # Pager[EntryRelation]
    print(rel.id, rel.scope, rel.type, rel.key, rel.workbook_id)
# filters: link_direction= ("from" | "to" — which side of the dependency edge;
#          omit for all related entries), scope=, include_permissions_info=, page_size=100
```

Check relations before deleting anything shared — a dataset with dependent charts will break them.

## Collections, workbooks, folders: CRUD

```python
from datalens_sdk import EntryLocation

# create — builders, terminal .build()
col = client.create.collection(name="Team", parent=parent_col).description("...").build()
wb = client.create.workbook(name="Q3", collection=col).description("...").build()
fld = client.create.folder(name="reports", location=EntryLocation.path("Users/me")).build()
# parent= / collection= accept a Collection object, EntryLocation.collection(id), or None (root);
# folder location= accepts a Folder object or EntryLocation.path(dir_path)

# get
col = client.get.collection(by_id=col.id)
wb = client.get.workbook(by_id=wb.id)
fld = client.get.folder(by_path=fld.key)  # the one path-based getter; .key is the full path

# rename / update — rename() returns the renamed object; update needs .execute()
col = col.rename("Team 2026")
col = col.update.description("...").execute()  # workbook: same; folder update: .name() only

# delete — children first; hard rule 6 for anything you did not create this session
fld.delete()
wb.delete()
col.delete()
```

Key attributes: `Collection.parent_id`, `Workbook.collection_id`, `Folder.key` (full path) — use them to verify a create or move landed where you expected.

## Moving, and atomic move-and-rename

Containers and path-located entries expose typed move operations:

| Object | `.move()` | Destination kind |
|---|---|---|
| `Collection` | `move(location, *, name=None)` | a collection (`Collection` object or `EntryLocation.collection(id)`), or `None` for the root |
| `Workbook` | `move(location, *, name=None)` | a collection, or `None` for the root |
| `Folder` | `move(location, *, name=None)` | a path (`Folder` object or `EntryLocation.path(dir)`) |
| `Connection`, `Dataset`, charts, `Dashboard` | `move(location, *, name=None)` | a path (`Folder` object or `EntryLocation.path(dir)`) |

`name=` makes the move-and-rename atomic — one API call, no window where the object sits at the destination under the old name:

```python
wb = wb.move(target_collection, name="Q3 archived")  # move + rename in one call
fld = fld.move(EntryLocation.path("Users/me/archive"))  # keep the name
```

Every `move()` returns the updated object — rebind the variable, and verify via `parent_id` / `collection_id` / `key`. Ordinary entries keep their id and may be renamed atomically while moving between paths. Moving an ordinary entry into or out of a workbook is unsupported and raises `NotSupportedError`; use the export/clone workflow when crossing that boundary, and remember the copy gets a new id. Other wrong destination kinds raise `DataLensValidationError`, and a destination from another installation raises `NotSupportedError`.

For a path-located create or move, `name` must not contain `/` — the directory goes in the location, the leaf name in `name=`.

## Related references

- [core-concepts.md](core-concepts.md) — `EntryLocation`, `client.capabilities`, `NotSupportedError`, pagination and retry behavior
- [serialization.md](serialization.md) — export, import, and clone when entries must cross workbook or folder boundaries
- [troubleshooting.md](troubleshooting.md) — 404 on lookups, conflicts on creates, permission errors while listing
