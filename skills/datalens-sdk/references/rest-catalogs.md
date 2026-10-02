# REST catalogs (Yandex Cloud)

This reference is for DataLens REST catalogs on Yandex Cloud. Enterprise and
YaTeam do not expose `client.list.rest_catalogs`; accessing that missing
action raises ordinary `AttributeError` at the public list namespace. Stop there.
Do not replace the missing action with raw HTTP, `/rpc` calls, generated DTOs,
or private-package imports. For client configuration, use [setup](setup.md).

## Current surface: list only

The catalog namespace currently provides only the action-first
`client.list.rest_catalogs(...)` read. It has no catalog get, create, update,
delete, or bound lifecycle method. Catalog attachment and detachment belong to
the Trino cluster, not to the catalog.

## Get permission before reading results

Before calling `rest_catalogs`, iterating its `Pager`, requesting a page, or
inspecting catalog data, check that the user explicitly authorized how the
result will be handled. If unclear, ask whether to show it in chat, save it to
a file, leave it in a saved script as a variable, or analyze it in code. Wait
for the answer and use only the approved form. A request to prepare or save a
script permits writing the code below, but **not running it**, fetching a page,
inspecting a catalog, or attaching one. No smoke-test exception applies.

The examples below assume a configured Yandex Cloud `client` from
[setup](setup.md), and are to be executed only after that authorization.

## Tenant-wide or cloud-environment-scoped listing

Omit `cloud_environment_id` for the current tenant's catalogs. Supply a
non-empty cloud-environment ID to narrow the listing; the SDK does not discover
one for you.

```python
tenant_catalogs = client.list.rest_catalogs()
environment_catalogs = client.list.rest_catalogs(cloud_environment_id="cloud-environment-id")
```

Both values are lazy `Pager[RestCatalog]` objects; constructing a pager makes
no HTTP request.

## Filters, permissions, and order

`filters` accepts a sequence of backend-supported filter strings, not one
scalar string. The SDK forwards filter expressions without interpreting their
syntax. `include_permissions=None` omits the option, while `False` and `True`
are sent explicitly. Sort using the public snake-case fields `"name"`,
`"created_at"`, or `"updated_at"`; `order` is `"asc"` (default) or `"desc"`.
The default `page_size` is 100.

```python
from datalens_sdk import DataLensClientYC


def filtered_catalogs(client: DataLensClientYC, expressions: tuple[str, ...]):
    return client.list.rest_catalogs(
        filters=expressions,
        include_permissions=False,
        sort_by="created_at",
        order="desc",
        page_size=50,
    )
```

Invalid public sort/order choices and an explicitly empty environment ID fail
with `DataLensValidationError` before transport. The generated request contract
validates page-size constraints when the lazy pager first loads a page.

## Lazy pages and resumption

Only iterate after result-handling authorization. `pager.pages()` yields
`Page[RestCatalog]` objects with `.items` and `.next_page_token`. Save a
non-empty continuation token in the approved destination to resume later;
pass it as `page_token`. An empty final token remains visible on the final
page but does not request another page. Repeated non-empty tokens are rejected
before they can loop.

```python
pager = client.list.rest_catalogs(page_size=50, page_token="saved-continuation-token")
for page in pager.pages():
    for catalog in page.items:
        print(catalog.id, catalog.name)  # Only if showing results was authorized.
    continuation_token = page.next_page_token
```

The printed form is only for a request that explicitly permits showing the
results. For a saved file, script variable, or code analysis, handle the page
only in that approved form. Save each page's updated `continuation_token` to
the approved checkpoint destination; clear any previously saved token when
the final page returns `""` or `None`. A second iteration starts a fresh
listing; the pager is not a cache. See [core concepts](core-concepts.md) for
shared pager behavior.

## Catalog snapshots

Each item is a frozen, slotted `RestCatalog` with `.id`, `.installation`,
`.organization_id`, `.tenant_id`, `.cloud_environment_id`, `.name`,
`.description`, `.created_by_id`, `.bucket.settings`, optional `.bucket.details`,
`.labels`, `.permissions`, `.created_at`, `.updated_at`, and `.raw`. The bucket
size values are strings. Omitted labels become an empty mapping; omitted
permissions remain `None`, distinct from an explicitly empty permission map.
Optional details and timestamps remain `None` when absent. `.raw` preserves
the original catalog item, including unknown nested fields, for forward
compatibility; it is not a substitute for the typed fields.

The public root exports include `RestCatalog`, `RestCatalogBucket`,
`RestCatalogBucketSettings`, and `RestCatalogBucketDetails`.
`catalog.bucket.settings` exposes
`storage_class`, `max_size`, `alias`, and optional `description`;
`catalog.bucket.details` exposes optional `max_size`, `used_size`, and
`updated_at`. Settings sizes and detail sizes are strings; timestamps are
`LakehouseTimestamp` values.

```python
settings = catalog.bucket.settings
print(settings.storage_class, settings.max_size, settings.alias)
details = catalog.bucket.details
if details is not None:
    print(details.used_size, details.updated_at)
```

## Use a catalog as a Trino reference

The `RestCatalog` item can be passed directly where Trino catalog membership
accepts `RestCatalog | str`. Prefer the model: the SDK can check its
installation and cloud environment against the cluster. A non-empty raw ID is
accepted when no model is available, but cannot carry those checks. Do not
convert the model to a generated or private type.

After result-handling authorization, select exactly one catalog by name and
fetch only the requested cluster through the public SDK. Stop if the name
matches no catalogs or more than one; never attach an arbitrary first result:

```python
matching_catalogs = [
    item for item in client.list.rest_catalogs(cloud_environment_id="cloud-environment-id") if item.name == "analytics"
]
if len(matching_catalogs) != 1:
    raise ValueError("Expected exactly one REST catalog named 'analytics'")
catalog = matching_catalogs[0]
cluster = client.get.trino_cluster(by_id="trino-42")
```

Define this guard before running any example that changes cluster membership:

```python
import sys


def require_confirmation(message: str) -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("Interactive catalog membership confirmation required")
    try:
        answer = input(f"{message} Type yes to confirm (anything else cancels): ")
    except (EOFError, KeyboardInterrupt):
        raise RuntimeError("Catalog membership change canceled") from None
    if answer.strip().lower() != "yes":
        raise RuntimeError("Catalog membership change canceled")
```

To set initial membership while creating a Trino cluster, call
`.catalogs(...)` on the create builder before `.build()`:

```python
from datalens_sdk import EntryLocation

builder = client.create.trino_cluster(
    name="analytics-trino",
    location=EntryLocation.collection("collection-id"),
    cloud_environment_id="cloud-environment-id",
)
builder.worker(resource_preset="preset-id", min_count=1, max_count=8)
builder.catalogs([catalog])
require_confirmation(
    f"Create Trino cluster 'analytics-trino' in collection 'collection-id' "
    f"with REST catalog {catalog.name!r} (id={catalog.id!r})?"
)
operation = builder.build()
```

Omitting `.catalogs(...)` omits `catalogsConfig`; `.catalogs([])` sends an
explicit empty list. Repeated calls replace the previous selection, so the
last call is what `.build()` sends. Models are checked for installation and
cloud-environment compatibility; non-empty string IDs cannot carry those
checks. Use the [confirmation guard below](#confirm-immediately-before-membership-changes)
with a fresh prompt that names the cluster and selected catalogs immediately
before `.build()`.

## Confirm immediately before membership changes

Ask the user to confirm the exact catalog and cluster immediately before each
side-effecting call. A request to list or prepare code is not confirmation.
The `require_confirmation` guard defined above cancels on blank or any answer
other than an explicit `yes`, and fails closed when the script has no
interactive terminal.

Immediately before attachment, name both actual resources in a fresh prompt:

```python
require_confirmation(
    f"Attach REST catalog {catalog.name!r} (id={catalog.id!r}) "
    f"to Trino cluster {cluster.name!r} (id={cluster.cluster_id!r})?"
)
operation = cluster.attach_catalog(catalog)
```

If detachment is requested, obtain a separate fresh confirmation immediately
before it. Detach removes the catalog from this Trino cluster; it **does not
delete the catalog resource**.

```python
require_confirmation(
    f"Detach REST catalog {catalog.name!r} (id={catalog.id!r}) "
    f"from Trino cluster {cluster.name!r} (id={cluster.cluster_id!r})?"
)
operation = cluster.detach_catalog(catalog)
```

Both methods return a `LakehouseOperation` snapshot. Neither call automatically
waits for completion. After separate execution and result-handling
authorization, inspect it with `operation.refresh()` or `operation.wait(...)`;
after persisting an operation ID, reload it with
`client.get.lakehouse_operation(by_id=...)`. See
[Lakehouse operation lifecycle](lakehouse-operations.md) for polling and
terminal-error handling. Do not execute attach, detach, `operation.refresh()`,
or `operation.wait()` for a prepare-only request. Consult
[troubleshooting](troubleshooting.md) if an SDK call fails, and stay on the
public SDK surface if the selected installation lacks these methods.
