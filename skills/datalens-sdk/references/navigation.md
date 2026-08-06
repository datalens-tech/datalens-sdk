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
    scope="dataset",  # "dataset" | "widget" (charts) | "dash" | "connection" | "folder"
    type=None,  # entry subtype, e.g. "graph_wizard_node"
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
#                   order_direction=, page_size=, scope= (str or sequence)

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
for page in folder.list_entries(order_by="name").pages():
    print(" > ".join(crumb.name for crumb in page.breadcrumbs))
    for entry in page.items:
        print(" ", entry.id, entry.name)
```

## Finding an entity by name

Entity getters are id-only (`client.get.folder(by_path=...)` is the single path-based exception), so find-by-name is always list-then-get. The server `name=` filter narrows the listing; compare exactly on the client, then `get` by the id you found:

```python
def display_name(entry):
    return entry.name.rsplit("/", 1)[-1] if entry.name is not None else None


matches = [
    entry for entry in client.navigation.get_entries(scope="dataset", name="Sales") if display_name(entry) == "Sales"
]
if not matches:
    raise LookupError("dataset 'Sales' not found")
if len(matches) > 1:
    raise LookupError(f"{len(matches)} datasets named 'Sales'; disambiguate by workbook_id or id")
ds = client.get.dataset(by_id=matches[0].id)
```

Scope the search when you can: inside a known workbook use `wb.list_entries(name=..., scope="dataset")` instead of the global listing. The server-side `name=` filter only narrows candidates; always compare the derived display leaf exactly. This is also the adopt-on-409 lookup (hard rule 7).

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

Only containers move; entries do not:

| Object | `.move()` | Destination kind |
|---|---|---|
| `Collection` | `move(location, *, name=None)` | a collection (`Collection` object or `EntryLocation.collection(id)`), or `None` for the root |
| `Workbook` | `move(location, *, name=None)` | a collection, or `None` for the root |
| `Folder` | `move(location, *, name=None)` | a path (`Folder` object or `EntryLocation.path(dir)`) |
| `Connection`, `Dataset`, charts, `Dashboard` | — no `move()`; `rename(name)` only | — |

`name=` makes the move-and-rename atomic — one API call, no window where the object sits at the destination under the old name:

```python
wb = wb.move(target_collection, name="Q3 archived")  # move + rename in one call
fld = fld.move(EntryLocation.path("Users/me/archive"))  # keep the name
```

Every `move()` returns the updated object — rebind the variable, and verify via `parent_id` / `collection_id` / `key`. Wrong destination kind (e.g. a workbook passed to `Folder.move`) raises `DatalensValidationError`; a destination from another installation raises `NotSupportedError`. To "move" an entry between workbooks or folders, use the export/clone workflow in [serialization.md](serialization.md) instead — and remember the copy gets a new id.

For a path-located create or move, `name` must not contain `/` — the directory goes in the location, the leaf name in `name=`.

## Related references

- [core-concepts.md](core-concepts.md) — `EntryLocation`, `client.capabilities`, `NotSupportedError`, pagination and retry behavior
- [serialization.md](serialization.md) — export, import, and clone when entries must cross workbook or folder boundaries
- [troubleshooting.md](troubleshooting.md) — 404 on lookups, 409 on creates, permission errors while listing
