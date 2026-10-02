# Managed Spark clusters (Yandex Cloud)

This reference covers DataLens-managed Spark clusters and resource presets,
not generic Apache Spark programming, an ordinary database connection, or
Spark job submission. It is available only through `DataLensClientYC`.
Enterprise and YaTeam do not expose these create/get/list actions; accessing
one raises ordinary `AttributeError`. Stop at the public SDK boundary: do not
substitute raw HTTP, generated DTOs, or a private package. Configure the
client with [setup](setup.md).

## Resource and operation model

A managed Spark cluster lives in a DataLens collection and a caller-supplied
cloud environment. The SDK does not discover or manage cloud environments.
Resource presets configure the driver and executor pools. Each pool needs a
`SparkFixedScalePolicy(size=...)` or
`SparkAutoScalePolicy(min_size=..., max_size=..., initial_size=...)`.
Creating, starting, stopping, or deleting a cluster returns an asynchronous
[Lakehouse operation](lakehouse-operations.md) immediately, without waiting.
There is no cluster update, rename, move, catalog configuration, or SparkJobs
method in this reference.

## Authorize reads and confirm mutations

Before get/list, requesting or iterating a pager page, refreshing a cluster,
polling an operation, or inspecting any returned data, ask how the user wants
results handled: shown in chat, saved to a file, kept as a variable in a
saved script, or analyzed in code. Wait for an answer and use only that form.
Preparing a script does not authorize executing it or making a smoke-test
read. A result destination alone is not execution approval; obtain that
separately.

Creating or starting a cluster can incur cost; stopping disrupts work and
deletion is destructive. Require fresh confirmation naming the actual target
immediately before each `.build()`, `.start()`, `.stop()`, or `.delete()`.
Preparing code is not that confirmation. In a saved script, use a fail-closed
interactive guard; never prefill its answer:

```python
import sys


def require_confirmation(message: str) -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("Interactive confirmation required")
    try:
        answer = input(f"{message} Type yes to confirm (anything else cancels): ")
    except (EOFError, KeyboardInterrupt):
        raise RuntimeError("Spark cluster change canceled") from None
    if answer.strip().lower() != "yes":
        raise RuntimeError("Spark cluster change canceled")
```

All following snippets assume a configured Yandex Cloud `client` from
[setup](setup.md). Execute them only after the relevant result-handling,
execution, and per-mutation confirmations.

## Discover a resource preset

For an exact known ID, use the action-first get method. It requires the
caller-supplied cloud-environment ID and returns `SparkResourcePreset` with
that environment recorded for later local compatibility checks.

```python
preset = client.get.spark_resource_preset(
    by_id="preset-7",
    cloud_environment_id="cloud-environment-id",
)
```

For discovery, `client.list.spark_resource_presets` returns a lazy
`Pager[SparkResourcePreset]`; construction does not request a page. Choose
the requested preset by its exact ID, never an arbitrary first item. An
explicit `page_token` resumes at that token. Save every updated
`Page.next_page_token` to the approved destination, including `""` or `None`
to clear a prior checkpoint. Repeated non-empty tokens fail before replay.

```python
pager = client.list.spark_resource_presets(
    cloud_environment_id="cloud-environment-id",
    page_size=100,
    page_token="saved-continuation-token",
)
for page in pager.pages():
    for item in page.items:
        print(item.id, item.cores, item.memory)  # Only if showing results was authorized.
    continuation_token = page.next_page_token
```

A non-empty raw preset ID also works for pool setters, but cannot carry
installation or cloud-environment checks. Prefer a fetched preset model when
those facts matter.

## Create a cluster

The action-first create method needs a name, collection location, and
caller-supplied cloud-environment ID. Set both driver and executor pools
before `.build()`. Scale sizes are integers; the SDK converts them to the
API's string representation and generated DTOs enforce declared bounds.
Supply every auto-scale size explicitly. If the user gave a range but not
`initial_size`, ask for it; do not infer it from the range or this example.

```python
from datalens_sdk import EntryLocation, SparkAutoScalePolicy, SparkFixedScalePolicy

preset = client.get.spark_resource_preset(
    by_id="preset-7",
    cloud_environment_id="cloud-environment-id",
)
builder = client.create.spark_cluster(
    name="analytics-spark",
    location=EntryLocation.collection("collection-id"),
    cloud_environment_id="cloud-environment-id",
)
builder.driver(resource_preset=preset, scale_policy=SparkFixedScalePolicy(size=1))
builder.executor(
    resource_preset=preset,
    scale_policy=SparkAutoScalePolicy(min_size=2, max_size=4, initial_size=2),
)
require_confirmation(
    "Create Spark cluster 'analytics-spark' in collection 'collection-id', "
    "cloud environment 'cloud-environment-id', "
    "with preset 'preset-7', one driver, and 2–4 executors (initial 2), incurring cost?"
)
operation = builder.build()
```

The sizes above are illustrative, not implicit defaults. You may set
`.description("...")`, `.labels({...})`, `.spark_version("...")`,
`.dependencies(pip_packages=[...], deb_packages=[...])`, and
`.logging(enabled=False)` before confirmation and `.build()`. Omitting
`.dependencies(...)` omits that object; calling `.dependencies()` includes
an empty object, while an explicit `pip_packages=[]` or `deb_packages=[]`
sends an empty array for that field. Omitting logging differs from explicitly
setting `False`. Optional description, labels, and version are likewise
omitted unless set. `.build()` returns a bound `LakehouseOperation`, not a
completed cluster; it never waits automatically.

## Get, list, and refresh clusters

`client.get.spark_cluster(by_id=...)` uses the public DataLens cluster entry
ID and returns a bound `SparkCluster`. `.refresh()` obtains a new snapshot;
it does not mutate the old object. Use these only after result-handling and
execution authorization.

```python
cluster = client.get.spark_cluster(by_id="spark-entry-id")
new_snapshot = cluster.refresh()
```

`client.list.spark_clusters(...)` returns a lazy, repeatable
`Pager[SparkCluster]`. Its optional `collection` accepts
`EntryLocation.collection(...)` or a non-empty collection ID. `filters` is a
sequence of backend filter strings, not one scalar string; the SDK does not
interpret their syntax. Default page size is 100. Explicit zero and an
initial empty-string token remain distinct from omission. Each traversal
starts from the original token; repeated non-empty tokens fail before
another request.

```python
cluster_pager = client.list.spark_clusters(
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
invent syntax from the SDK. Save or clear the checkpoint in the approved
destination after each page. See [core concepts](core-concepts.md) for
pagination and [navigation](navigation.md) for collection discovery.

After a create operation reaches `done=True` without `.error`, its opaque
response supplies no documented cluster entry ID. With separate
result-handling and execution authorization for reads, list the known
collection and select exactly one cluster with the requested name and cloud
environment:

```python
terminal = operation.wait(timeout=600.0, poll_interval=2.0)
if terminal.error is not None:
    raise RuntimeError("Spark cluster creation did not succeed")

matches = [
    item
    for item in client.list.spark_clusters(collection="collection-id")
    if item.name == "analytics-spark" and item.cloud_environment_id == "cloud-environment-id"
]
if len(matches) != 1:
    raise RuntimeError(f"Expected one newly created Spark cluster; found {len(matches)}")
cluster = matches[0]
```

Stop on zero or multiple matches; do not guess or parse operation
`.metadata`/`.response` for an ID. The bound `cluster` is ready for an
authorized refresh or lifecycle call.

## Bound lifecycle

`refresh()` and `delete()` internally use public entry `id`; `start()` and
`stop()` internally use managed `cluster_id`. Call the bound methods; do not
choose a wire identifier yourself. Every mutation returns a bound
`LakehouseOperation` without automatic polling or mutation retry.

```python
require_confirmation(f"Start Spark cluster {cluster.name!r} (id={cluster.cluster_id!r}) and incur cost?")
operation = cluster.start()
```

```python
require_confirmation(f"Stop Spark cluster {cluster.name!r} (id={cluster.cluster_id!r}) and disrupt work?")
operation = cluster.stop()
```

```python
require_confirmation(f"Delete Spark cluster {cluster.name!r} (entry id={cluster.id!r}) permanently?")
operation = cluster.delete()
```

For explicit operation `refresh()` and `wait(...)`, terminal error data, and
timeout inspection, read [Lakehouse operations](lakehouse-operations.md).
For API failures, consult [troubleshooting](troubleshooting.md) instead of
blindly replaying a mutation.
