# Managed Trino clusters (Yandex Cloud)

This reference covers DataLens-managed Trino clusters and resource presets,
not an ordinary Trino database connection or a saved SQL query. It is
available only through `DataLensClientYC`. Enterprise and YaTeam do not have
the Trino create/get/list actions: accessing one raises ordinary
`AttributeError`. Stop there; do not use raw HTTP, generated DTOs, or a
private SDK package as a fallback. Configure the client with [setup](setup.md).

## Resource and operation model

A Trino cluster is placed in a DataLens collection and a caller-supplied cloud
environment. The SDK does not discover or manage cloud environments. A
resource preset configures the worker pool; an existing [REST catalog](rest-catalogs.md)
can be included at creation or attached to the cluster later. Create and
bound mutations return an asynchronous
[Lakehouse operation](lakehouse-operations.md) immediately, without waiting.
There is no cluster update, rename, or move action.

## Authorize reads and confirm mutations

Before calling get/list, requesting or iterating a pager page, refreshing a
cluster, polling an operation, or inspecting returned data, ask how the user
wants results handled: in chat, a file, a variable in a saved script, or code
analysis. Wait for an answer and use only that form. A request to prepare a
script does not authorize executing it or making a smoke-test read. A result
destination alone is not permission to execute. Obtain execution approval
separately.

Creating or starting a cluster can incur cost; stopping disrupts work;
deletion is destructive. Attaching or detaching a catalog changes cluster
membership, and detaching **does not delete the catalog resource**. Ask for
fresh confirmation naming the actual target immediately before each terminal
mutation, including `.build()`, `.start()`, `.stop()`, `.delete()`,
`.attach_catalog()`, and `.detach_catalog()`. Preparing code is not that
confirmation. For a saved script, use a fail-closed interactive guard such as
this one; do not prefill the answer:

```python
import sys


def require_confirmation(message: str) -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("Interactive confirmation required")
    try:
        answer = input(f"{message} Type yes to confirm (anything else cancels): ")
    except (EOFError, KeyboardInterrupt):
        raise RuntimeError("Trino cluster change canceled") from None
    if answer.strip().lower() != "yes":
        raise RuntimeError("Trino cluster change canceled")
```

All examples below assume a configured Yandex Cloud `client` from
[setup](setup.md). Execute them only after the separate result-handling,
execution, and per-mutation confirmations that apply.

## Discover a resource preset

For a known preset ID, use the action-first get method. It requires both
keyword-only arguments and returns `TrinoResourcePreset`; the SDK carries the
requested cloud environment into that model for later provenance checking.

```python
preset = client.get.trino_resource_preset(
    by_id="preset-id",
    cloud_environment_id="cloud-environment-id",
)
```

For discovery, `client.list.trino_resource_presets` returns a lazy
`Pager[TrinoResourcePreset]`. Constructing it does not request a page. An
explicit `page_token` resumes from that token; `pages()` exposes every
`Page.next_page_token`. Save each updated token in the approved destination,
and clear an earlier checkpoint when the final token is `""` or `None`.
Repeated non-empty tokens fail before replay. Do not inspect the presets until
the user has chosen how results will be handled.

```python
pager = client.list.trino_resource_presets(
    cloud_environment_id="cloud-environment-id",
    page_size=100,
    page_token="saved-continuation-token",
)
for page in pager.pages():
    for item in page.items:
        print(item.id, item.cores, item.memory)  # Only if showing results was authorized.
    continuation_token = page.next_page_token
```

Choose the requested preset by its exact ID; do not select an arbitrary first
item. A non-empty raw preset ID also works when no model is available, but
cannot carry installation or cloud-environment checks.

## Create a cluster

The action-first create method needs a name, collection location, and
caller-supplied cloud-environment ID. `.worker(...)` is required before
`.build()`. Public `min_count` and `max_count` are integers; the SDK turns them
into the API's string representation and the generated request validates
their individual ranges. It does not invent an ordering constraint between
the two counts. Ask the user for both counts if they were not supplied; the
numbers in the example are illustrative, not defaults to silently apply.

```python
from datalens_sdk import EntryLocation

builder = client.create.trino_cluster(
    name="analytics-trino",
    location=EntryLocation.collection("collection-id"),
    cloud_environment_id="cloud-environment-id",
)
builder.worker(resource_preset=preset, min_count=1, max_count=8)
builder.description("Interactive analytics cluster").labels({"team": "analytics"})
builder.trino_version("476")
require_confirmation(
    f"Create Trino cluster 'analytics-trino' in collection 'collection-id' "
    f"with resource preset {preset.id!r}, min_count=1, max_count=8?"
)
operation = builder.build()
```

If initial catalogs are needed, call `builder.catalogs([catalog])` before the
confirmation and `.build()`. It accepts `RestCatalog` objects or non-empty ID
strings. Omitting `.catalogs(...)` omits the field; `.catalogs([])` sends an
explicit empty list. Preset and catalog models are checked for installation
and cloud-environment compatibility; raw IDs cannot carry those checks.
When catalogs are included, name the selected catalog IDs, preset ID, and
worker counts in the fresh confirmation immediately before `.build()`:

```python
catalogs = [catalog]
builder.catalogs(catalogs)
require_confirmation(
    f"Create Trino cluster 'analytics-trino' in collection 'collection-id' "
    f"with resource preset {preset.id!r}, min_count=1, max_count=8, "
    f"catalog IDs={[item.id for item in catalogs]!r}?"
)
operation = builder.build()
```

Adapt the confirmation to the values selected for this create request rather
than copying the illustrative IDs or counts unchanged.
Likewise, omitting description/labels/version differs from setting an empty
string or empty mapping. `.build()` returns a bound `LakehouseOperation`, not
a completed cluster; it never waits automatically.

## Get, list, and refresh clusters

`client.get.trino_cluster(by_id=...)` uses the DataLens cluster entry ID and
returns a bound `TrinoCluster`. `.refresh()` obtains a new snapshot and leaves
the old object unchanged. Use these only after result-handling and execution
authorization.

```python
cluster = client.get.trino_cluster(by_id="trino-entry-id")
new_snapshot = cluster.refresh()
```

`client.list.trino_clusters(...)` is lazy and returns a repeatable
`Pager[TrinoCluster]`. Its optional `catalog` accepts a `RestCatalog` or
non-empty ID; `collection` accepts `EntryLocation.collection(...)` or a
non-empty collection ID. `filters` is a sequence of backend filter strings,
not one scalar string; the SDK does not interpret their syntax. The default
page size is 100, and explicit zero and an initial empty-string token remain
distinct from omission. Each new traversal begins at the original token;
repeated non-empty tokens fail before another request.

```python
cluster_pager = client.list.trino_clusters(
    catalog="catalog-id",
    collection="collection-id",
    filters=(),
    page_size=50,
    page_token="saved-continuation-token",
)
for page in cluster_pager.pages():
    for item in page.items:
        print(item.id, item.name, item.status)  # Only if showing results was authorized.
    continuation_token = page.next_page_token
```

Only use filter expressions known to be supported by the backend; do not
invent syntax from the SDK. Persist or clear the checkpoint in the approved
destination after each page. See [core concepts](core-concepts.md) for shared
pager behavior and [navigation](navigation.md) for collection discovery.

After a create operation reaches `done=True` without `.error`, the operation
does not supply a documented cluster entry ID. With separate result-handling
and execution authorization for the reads, list the known collection and
select exactly one cluster with the requested name and cloud environment:

```python
terminal = operation.wait(timeout=600.0, poll_interval=2.0)
if terminal.error is not None:
    raise RuntimeError("Trino cluster creation did not succeed")

matches = [
    item
    for item in client.list.trino_clusters(collection="collection-id")
    if item.name == "analytics-trino" and item.cloud_environment_id == "cloud-environment-id"
]
if len(matches) != 1:
    raise RuntimeError(f"Expected one newly created Trino cluster; found {len(matches)}")
cluster = matches[0]
```

If none or multiple match, stop; do not guess or parse opaque operation
`.metadata`/`.response` for an ID. The returned bound `cluster` is ready for
`refresh()` or lifecycle methods, with their separate authorization and
confirmation requirements.

## Bound lifecycle and catalog membership

`refresh()` and `delete()` internally use the public entry `id`;
`start()`, `stop()`, `attach_catalog()`, and `detach_catalog()` internally use
the managed `cluster_id`. Call the bound methods; do not choose a wire
identifier yourself. Every mutation returns a bound `LakehouseOperation`
without automatic polling or mutation retry.

```python
require_confirmation(f"Start Trino cluster {cluster.name!r} (id={cluster.cluster_id!r}) and incur cost?")
operation = cluster.start()
```

```python
require_confirmation(f"Stop Trino cluster {cluster.name!r} (id={cluster.cluster_id!r}) and disrupt work?")
operation = cluster.stop()
```

```python
require_confirmation(f"Delete Trino cluster {cluster.name!r} (entry id={cluster.id!r}) permanently?")
operation = cluster.delete()
```

Catalog membership also uses bound methods. Select an existing catalog as in
[REST catalogs](rest-catalogs.md); a model lets the SDK check installation and
cloud environment against the cluster. Ask again immediately before each
attachment or detachment. Detaching does not delete the REST catalog.

```python
require_confirmation(
    f"Attach REST catalog {catalog.name!r} (id={catalog.id!r}) "
    f"to Trino cluster {cluster.name!r} (id={cluster.cluster_id!r})?"
)
operation = cluster.attach_catalog(catalog)
```

```python
require_confirmation(
    f"Detach REST catalog {catalog.name!r} (id={catalog.id!r}) "
    f"from Trino cluster {cluster.name!r} (id={cluster.cluster_id!r})?"
)
operation = cluster.detach_catalog(catalog)
```

For explicit operation `refresh()` and `wait(...)`, terminal error data, and
timeout inspection, read [Lakehouse operations](lakehouse-operations.md).
For API failures, consult [troubleshooting](troubleshooting.md) instead of
blindly replaying a mutation.
