# QL column chart

Choose `column` for vertical category comparison or discrete values over time.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.column(...)` |
| Canonical ID | `column` |
| Typical wire type | `d3_ql_node` |
| Placements | `x` optional (capacity 2); `y` optional |
| Decorations | `colors`, `labels`, `tooltips` |

The SDK marks neither axis required, but a useful chart normally needs a
category/time alias on `x` and a value alias on `y`.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_column(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT 'api' AS service, toInt64(42) AS events, 'prod' AS environment
    """
    return (
        client.create.ql_chart.column(name="Events by service", location=location)
        .connection(connection)
        .query(query)
        .x([QLColumn("service")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("environment")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

Use `bar` for horizontal ranking and `column_100p` for normalized composition.
See [the exact matrix in the index](_index.md).
