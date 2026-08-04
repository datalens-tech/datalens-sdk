# QL scatter chart

Choose `scatter` to compare two numeric variables and optionally encode point
identity, size, and grouping.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.scatter(...)` |
| Canonical ID | `scatter` |
| Typical wire type | `d3_ql_node` |
| Placements | `x` required (capacity 1); `y` required (capacity 1); `points` optional (capacity 1); `size` optional (capacity 1) |
| Decorations | `colors`, `shapes`, `tooltips` |

Both axes must be populated before `.build()`. Use `points()` for identity or a
categorical split and `size()` for a numeric magnitude.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_scatter(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT
      toInt64(120) AS latency_ms,
      toInt64(42) AS requests,
      toInt64(7) AS errors,
      'api' AS service
    """
    return (
        client.create.ql_chart.scatter(
            name="Latency and traffic",
            location=location,
        )
        .connection(connection)
        .query(query)
        .x([QLColumn("latency_ms", cast="integer")])
        .y([QLColumn("requests", cast="integer")])
        .points([QLColumn("service")])
        .size([QLColumn("errors", cast="integer")])
        .colors([QLColumn("service")])
        .shapes([QLColumn("service")])
        .build()
    )
```

`labels()` is unsupported. Every listed method is valid on create and update
and replaces its complete target. See [the exact matrix in the index](_index.md).
