# QL bar chart

Choose `bar` for horizontal ranking, especially when category labels are long.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.bar(...)` |
| Canonical ID | `bar` |
| Typical wire type | `d3_ql_node` |
| Placements | `y` optional (capacity 2); `x` optional |
| Decorations | `colors`, `labels`, `tooltips` |

Bar axes are intentionally reversed from column: put categories on `y` and
values on `x`. The SDK does not require either axis, but meaningful bars
normally need both.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_bar(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT 'api' AS service, toInt64(42) AS events, 'prod' AS environment
    """
    return (
        client.create.ql_chart.bar(name="Service ranking", location=location)
        .connection(connection)
        .query(query)
        .y([QLColumn("service")])
        .x([QLColumn("events", cast="integer")])
        .colors([QLColumn("environment")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

Use `column` for vertical comparison and `bar_100p` for normalized
composition. See [the exact matrix in the index](_index.md).
