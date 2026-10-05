# Spark applications (Yandex Cloud)

Use this reference for applications submitted to an existing managed DataLens
Spark cluster: Spark, PySpark, and Spark Connect applications, their snapshots,
and log fragments. Cluster provisioning and resource presets belong to the managed
[Spark-cluster workflow](spark-clusters.md); REST-catalog discovery belongs to
[REST catalogs](rest-catalogs.md). Generic Apache Spark programming and
ordinary database connections are outside this SDK workflow.

Only `DataLensClientYC` exposes `client.create.spark_application`,
`client.get.spark_application`, `client.list.spark_applications`, and
`client.list.spark_application_log`. Enterprise and YaTeam clients have no
SparkApplications actions; an absent action raises ordinary `AttributeError`.
Stop there. Do not substitute raw HTTP, generated DTOs, or a private package.
Start with the
bundled preflight and [Yandex Cloud setup](setup.md).

## Identity and references

`cluster=` accepts a managed `SparkCluster` model or its non-empty managed
`cluster_id` string. The model gives the SDK an installation and cloud
environment to check; its DataLens entity `id` is not the managed cluster ID.
For `client.list.spark_application_log`, `application=` accepts a
`SparkApplication` snapshot or its non-empty `id`. An application model must
belong to the selected managed cluster and client installation. A raw
application ID cannot prove either fact.

Creation may attach `RestCatalog` models or catalog ID strings through
`.catalogs([...])`. A catalog model provides installation and cloud-environment
checks when `cluster` is a model. A raw cluster ID has no cloud-environment
provenance, so the SDK cannot prove whether it matches a catalog model; the
service decides that combination. Keep IDs supplied or verified by the user;
do not invent environment discovery or derive an application ID from operation
metadata.
See [core concepts](core-concepts.md) for model and pager conventions.

## Authorize reads and result handling first

Before calling get, list, log, `SparkApplication.refresh()`,
`LakehouseOperation.refresh()` or `.wait()`, requesting a pager page, or
inspecting any returned application, log fragment, operation, or error, ask how
the result should be handled: shown in chat, saved to a file, kept as a variable
in a saved script, or analyzed in code. Wait for the answer and use only that
form. A request to prepare or save a script permits future calls in its text;
it does not authorize running the script, fetching a test page, polling an
operation, or reading returned data now. A result destination alone does not
authorize execution; obtain execution authorization separately.

The following examples assume a configured Yandex Cloud client and both
result-handling and execution authorization. The lists below stand for the
approved script-variable destination; adapt them to the actual approved form.

## Get, list, and refresh applications

Get one known application with `by_id=`. `SparkApplication.refresh()` fetches a
new bound snapshot, leaving the held snapshot unchanged.
`client.list.spark_applications` returns a lazy, repeatable
`Pager[SparkApplication]`; constructing it makes no request, while
iteration does. Its default `page_size=100` is sent explicitly. `filters` is a
sequence of API filter expressions such as `name="daily-etl"`.

```python
from datalens_sdk import DataLensClientYC

client = DataLensClientYC()
application = client.get.spark_application(cluster="managed-cluster-id", by_id="known-application-id")
new_snapshot = application.refresh()

applications = []
continuation_token = None
pager = client.list.spark_applications(cluster="managed-cluster-id", filters=('name="daily-etl"',), page_size=100)
for page in pager.pages():
    applications.extend(page.items)
    continuation_token = page.next_page_token
```

Save a non-empty continuation token in the approved destination, then resume
with `page_token=continuation_token`. An empty final token stops traversal;
clear any saved token then. A new iteration starts from the original options.
Use the snapshot's typed `status` to inspect the application state. There is no
`SparkApplication.wait()` and no SDK rule that infers terminal application
state from a status string.

## Read log fragments without changing their shape

`client.list.spark_application_log` returns a lazy `SparkApplicationLogPager`.
Iterating `.pages()` yields `SparkApplicationLogPage(content, next_page_token)`;
iterating the pager directly yields unchanged content strings. Fragments may be empty and
are not lines or structured records. Keep their boundaries; do not split,
parse, or automatically concatenate them. Omitting `page_size` omits that wire
field; an explicit value (including `0`) is the maximum fragment length, not
a line count.

After result-handling and execution authorization, request fragments and
retain their continuation tokens in the approved destination:

```python
from datalens_sdk import DataLensClientYC

client = DataLensClientYC()
fragments = []
continuation_token = None
log_pages = client.list.spark_application_log(cluster="managed-cluster-id", application="known-application-id")
for page in log_pages.pages():
    fragments.append(page.content)
    continuation_token = page.next_page_token
```

Resume with `page_token=continuation_token` when it is non-empty; clear a
saved token after the final empty token. For a chosen maximum fragment length,
pass `page_size=4096`. Constructing the pager does not read a log, and a
second traversal starts again from its original options. A repeated non-empty
continuation token raises an SDK error before another request with that token.

## Confirm immediately before submitting an application

Submission can incur compute cost. Before each `.build()` call, show the
selected managed cluster, application name, and workload to the user and obtain a
fresh, explicit confirmation. For a saved script, use a fail-closed prompt
immediately before the call. Blank, negative, or noninteractive execution
must stop. Preparing the script is not confirmation to create an application.

Choose exactly one variant per builder. `spark` requires
`main_jar_file_uri`; `pyspark` requires `main_python_file_uri`;
`spark_connect` accepts an empty payload. Optional `args`, dependency URI
sequences, package lists, and `properties` belong to the selected variant.
`None` omits an optional field; an empty list or mapping sends an explicit
empty value. `catalogs(values: Sequence[RestCatalog | str])` replaces the
complete outer catalog list;
omission and `.catalogs([])` differ. Repeating or combining selectors fails.
Each selector returns the same `SparkApplicationCreate` builder (`Self`). Their
keyword-only signatures are:

```text
spark(*, main_jar_file_uri: str, main_class: str | None = None,
      args: Sequence[str] | None = None,
      archive_uris: Sequence[str] | None = None,
      file_uris: Sequence[str] | None = None,
      jar_file_uris: Sequence[str] | None = None,
      packages: Sequence[str] | None = None,
      repositories: Sequence[str] | None = None,
      exclude_packages: Sequence[str] | None = None,
      properties: Mapping[str, str] | None = None) -> Self
pyspark(*, main_python_file_uri: str,
        args: Sequence[str] | None = None,
        python_file_uris: Sequence[str] | None = None,
        archive_uris: Sequence[str] | None = None,
        file_uris: Sequence[str] | None = None,
        jar_file_uris: Sequence[str] | None = None,
        packages: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        exclude_packages: Sequence[str] | None = None,
        properties: Mapping[str, str] | None = None) -> Self
spark_connect(*, archive_uris: Sequence[str] | None = None,
              file_uris: Sequence[str] | None = None,
              jar_file_uris: Sequence[str] | None = None,
              packages: Sequence[str] | None = None,
              repositories: Sequence[str] | None = None,
              exclude_packages: Sequence[str] | None = None,
              properties: Mapping[str, str] | None = None) -> Self
```

```python
import sys

from datalens_sdk import DataLensClientYC


def require_confirmation(message: str) -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("Interactive Spark application creation confirmation required")
    try:
        answer = input(f"{message} Type yes to confirm (anything else cancels): ")
    except (EOFError, KeyboardInterrupt):
        raise RuntimeError("Spark application creation canceled") from None
    if answer.strip().lower() != "yes":
        raise RuntimeError("Spark application creation canceled")


client = DataLensClientYC()
cluster_id = "managed-cluster-id"  # Replace with the user-selected managed cluster ID.
application_name = "daily-etl"  # Replace with the user-selected application name.
main_python_file_uri = "s3://bucket/main.py"  # Replace with the user-selected workload URI.
catalog_id: str | None = None  # Set only when the user selected an existing catalog ID.
builder = client.create.spark_application(cluster=cluster_id, name=application_name)
builder.pyspark(main_python_file_uri=main_python_file_uri)
if catalog_id is not None:
    builder.catalogs([catalog_id])

catalog_summary = f"catalog {catalog_id!r}" if catalog_id is not None else "no catalog"
require_confirmation(
    f"Submit PySpark application {application_name!r} to managed cluster "
    f"{cluster_id!r} "
    f"using workload {main_python_file_uri!r} and {catalog_summary}? "
    "This may incur compute cost."
)
operation = builder.build()
```

`build()` posts once and returns a bound `LakehouseOperation` snapshot. It
does not wait for the operation or Spark application. Do not infer a new
application ID from opaque operation metadata. Use a known application ID for a
later get, or list applications after read authorization and identify the exact
requested application.

## Confirm immediately before canceling

Cancellation can disrupt a running workload. After the authorized get and
inspection needed to identify the exact application, obtain a separate fresh
confirmation immediately before `SparkApplication.cancel()`. The bound method uses
the snapshot's managed cluster ID and application ID, returns a
`LakehouseOperation`, and does not wait or check the possibly stale status.
There is no standalone `client.cancel.spark_application` action.

```python
import sys

from datalens_sdk import DataLensClientYC


def require_cancel_confirmation(cluster_id: str, application_id: str) -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("Interactive Spark application cancellation confirmation required")
    try:
        answer = input(
            f"Cancel Spark application {application_id!r} on managed cluster "
            f"{cluster_id!r}? "
            "This can disrupt its workload. Type yes to confirm: "
        )
    except (EOFError, KeyboardInterrupt):
        raise RuntimeError("Spark application cancellation declined") from None
    if answer.strip().lower() != "yes":
        raise RuntimeError("Spark application cancellation declined")


client = DataLensClientYC()
application = client.get.spark_application(cluster="managed-cluster-id", by_id="known-application-id")
require_cancel_confirmation(application.cluster_id, application.id)
operation = application.cancel()
```

The example assumes result-handling and execution authorization before its
get call. Saving it for later does not authorize running that get or cancel
now.

## Operation completion is not application completion

Create and cancel operations share [Lakehouse operations](lakehouse-operations.md).
`operation.refresh()` returns a new snapshot; `operation.wait()` waits for
the operation's `done` flag only and does not run automatically. An operation
may be done even though the Spark application has a separate status or the
operation contains an error. Inspect the terminal operation only in the
authorized result form. A later application-status check needs a known
application ID and a separate authorized `client.get.spark_application(...)` or
`application.refresh()` call. Do not infer an application ID from opaque
operation fields or invent an application-level wait.

After separate result-handling and execution authorization, inspect an
operation and a known application ID in the approved form:

```python
from datalens_sdk import DataLensClientYC

client = DataLensClientYC()
operation = client.get.lakehouse_operation(by_id="known-operation-id")
new_operation = operation.refresh()
finished_operation = new_operation.wait(timeout=600.0, poll_interval=2.0)
operation_done = finished_operation.done
operation_error = finished_operation.error
application = client.get.spark_application(cluster="managed-cluster-id", by_id="known-application-id")
application_status = application.status
```

For authentication and client creation, see [setup](setup.md). For shared
pagination and models, see [core concepts](core-concepts.md). For failures,
see [troubleshooting](troubleshooting.md).
