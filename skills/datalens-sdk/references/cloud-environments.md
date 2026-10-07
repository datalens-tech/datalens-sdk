# Cloud environments (Yandex Cloud)

Use this reference for the Yandex Cloud environments used by managed Trino
and Spark resources. These actions are exposed by `DataLensClientYC`; other
installations do not expose them. Configure the client through
[setup](setup.md).

## Create, get, and list

Create is an action-first builder. `name`, `cloud_id`, and `subnet_id` are
required; `description`, `security_group_ids`, and storage `max_size` are
optional. Call `.build()` to create the resource and get a
`LakehouseOperation` snapshot.

```python
builder = client.create.cloud_environment(
    name="analytics",
    cloud_id="cloud-id",
    subnet_id="subnet-id",
)
builder.description("Managed analytics environment")
builder.security_group_ids(["security-group-id"])
builder.storage(max_size="53687091200")
operation = builder.build()
```

`client.get.cloud_environment(by_id=..., include_permissions=None)` fetches a
`CloudEnvironment`. `client.list.cloud_environments(...)` returns a lazy
`Pager[CloudEnvironment]` and accepts `filters=()`,
`include_permissions=None`, `page_size=100`, and `page_token=None`. Constructing
the pager makes no request. Iterate only after the user has authorized how
returned environment data will be handled. See [core concepts](core-concepts.md)
for page and continuation-token behavior.

## Read model and lifecycle

`CloudEnvironment` exposes `id`, `name`, `status`, `status_details`,
`description`, `cloud_id`, `tenant_id`, `subnet_id`, `security_group_ids`,
optional `storage`, `permissions`, `created_at`, `created_by_id`, `updated_at`,
`updated_by_id`, `installation`, and `raw`. Storage settings expose `max_size`
as a string. Use the bound model for lifecycle actions:

```python
environment = client.get.cloud_environment(by_id="environment-id")
fresh = environment.refresh()
operation = fresh.update().description("Updated").execute()
operation = fresh.delete()
```

`refresh()` returns a new snapshot. `.update()` requires at least one configured
field; `.name(...)`, `.description(...)`, `.security_group_ids(...)`, and
`.storage(max_size=...)` build the patch, and `.execute()` returns a
`LakehouseOperation`. Pass an empty string to clear the description and an
empty list to clear security groups. Deletion also returns an operation; it
does not wait for remote completion. For operation handling, read
[lakehouse operations](lakehouse-operations.md).

Cloud environment IDs are required when creating managed Trino clusters and
Spark clusters. See [Trino clusters](trino-clusters.md) and
[Spark clusters](spark-clusters.md).
