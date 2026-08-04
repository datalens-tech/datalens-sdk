# QL 100% bar chart

Choose `bar_100p` for normalized composition in horizontal stacks.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.bar_100p(...)` |
| Canonical ID | `bar100p` |
| Typical wire type | `d3_ql_node` |
| Placements | `y` optional (capacity 2); `x` optional |
| Decorations | `colors`, `labels`, `tooltips` |

Put categories on `y`, values on `x`, and stack segments in `colors()`.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_bar_100p(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT 'api' AS service, toInt64(42) AS events, 'success' AS outcome
    """
    return (
        client.create.ql_chart.bar_100p(
            name="Outcome share by service",
            location=location,
        )
        .connection(connection)
        .query(query)
        .y([QLColumn("service")])
        .x([QLColumn("events", cast="integer")])
        .colors([QLColumn("outcome")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

The public factory uses `bar_100p`; reads return canonical ID `bar100p`.
See [the exact matrix in the index](_index.md).
