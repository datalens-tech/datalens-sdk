# Lakehouse operations (Yandex Cloud)

Use this reference for asynchronous operations returned by Yandex Cloud Trino
and Spark cluster mutations, REST catalog attach/detach calls, and Spark
application submissions or cancellations. They return a `LakehouseOperation` snapshot and
do not wait for completion. Enterprise and YaTeam do not expose
`client.get.lakehouse_operation`; the missing action raises ordinary
`AttributeError`. Stop at the public SDK boundary: do not substitute raw HTTP,
generated DTOs, or a private package. Configure a client through [setup](setup.md).

## An operation is a snapshot

`LakehouseOperation` has `.id`, `.done`, optional `.error`, opaque `.metadata`
mapping, and optional opaque `.response` mapping. Only `.done` says whether
the operation is terminal.
A terminal snapshot may contain an error; the SDK returns that error as data,
not as an exception. `refresh()` returns a new bound snapshot and does not
change the original. Cluster and application mutations return an operation
immediately;
they do not wait for completion.

## Authorize result handling before reads or inspection

Before calling `client.get.lakehouse_operation`, `operation.refresh()`, or
`operation.wait()`, or inspecting `.error`, `.metadata`, or `.response`, ask the
user how the results should be handled: shown in chat, saved to a file, kept
as a variable in a saved script, or analyzed in code. Wait for an answer and
use only the approved form. A request to prepare or save a script permits
writing future calls but does not authorize running the script, polling as a
smoke test, or inspecting an operation now. A result destination alone does
not authorize execution; obtain that authorization separately.

The examples below assume a configured Yandex Cloud `client` from
[setup](setup.md) and both result-handling and execution authorization.

## Get, refresh, and wait explicitly

```python
operation = client.get.lakehouse_operation(by_id="operation-id")
new_snapshot = operation.refresh()
terminal_snapshot = new_snapshot.wait(timeout=600.0, poll_interval=2.0)
```

`by_id` is a required keyword-only non-empty string. With time remaining,
`wait()` refreshes immediately, then polls at a fixed interval (defaults: 600
seconds total, 2 seconds between polls). Pass `timeout=None` for no deadline.
It returns the same object without a request when the current snapshot already has
`done=True`. There is no automatic polling, backoff, callback, async variant,
or implicit retry of the mutation that produced the operation. Individual
read-only refresh requests use the SDK's transient retry policy.

## Terminal errors and timeouts

When `.done` is true, handle `.error` according to the approved result
destination. Do not assume an absent `.error` means the service-specific
`.response` has a particular shape: `.metadata` is opaque, and `.response` is
an optional opaque mapping. API, transport, and DTO failures from a refresh
still raise their ordinary SDK errors.

A finite polling deadline raises `DataLensOperationTimeoutError`. Its
`.operation_id`, `.timeout`, and `.last_operation` identify the latest parsed
snapshot, which may be the original when no refresh completed. Inspect them
only after result-handling authorization. A timeout does not mean the remote
operation was canceled.

```python
from datalens_sdk import DataLensOperationTimeoutError

try:
    terminal_snapshot = operation.wait(timeout=600.0, poll_interval=2.0)
except DataLensOperationTimeoutError as exc:
    last_snapshot = exc.last_operation
    operation_id = exc.operation_id
    configured_timeout = exc.timeout
```

For shared pagination and error handling, see [core concepts](core-concepts.md)
and [troubleshooting](troubleshooting.md).
