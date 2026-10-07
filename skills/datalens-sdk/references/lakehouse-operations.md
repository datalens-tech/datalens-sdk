# Lakehouse operations (Yandex Cloud)

Trino cluster mutations and REST catalog attach/detach calls return a
`LakehouseOperation` snapshot; they do not wait for completion. Enterprise and
YaTeam do not expose `client.get.lakehouse_operation`. Stay on the public SDK
surface and do not substitute raw HTTP, generated DTOs, or private-package
imports.

Before executing a script that refreshes or inspects an operation, obtain
separate authorization for execution and for how results will be handled.
A request to prepare code is not authorization to run it or inspect its
results. See [setup](setup.md) for client configuration.

After authorization, refresh the returned snapshot or wait for a terminal
snapshot explicitly:

```python
snapshot = operation.refresh()
terminal = snapshot.wait(timeout=600.0, poll_interval=2.0)
```

For a pending operation, `wait()` refreshes until `.done` is true and returns
the latest snapshot without changing the original. If the current snapshot is
already terminal, `wait()` returns that same object without a request. A
finite timeout raises `DataLensOperationTimeoutError`; its `last_operation`
holds the latest snapshot, and the timeout does not cancel the remote
operation. After saving an operation ID, reload it through
`client.get.lakehouse_operation(by_id=...)`, then use the same explicit
refresh/wait flow. A terminal `.error` is returned as data; it is not raised
automatically. Pass `timeout=None` to wait without a local deadline. See
[troubleshooting](troubleshooting.md) for SDK errors.
