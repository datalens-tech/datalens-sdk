# QL 100% column chart

Choose `column_100p` for normalized composition in vertical stacks.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.column_100p(...)` |
| Canonical ID | `column100p` |
| Typical wire type | `d3_ql_node` |
| Placements | `x` optional (capacity 2); `y` optional |
| Decorations | `colors`, `labels`, `tooltips` |

Use a categorical color alias to define stack segments. The builder does not
require axes, but a useful normalized chart normally needs `x`, `y`, and
`colors`.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_column_100p(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT '2026-07' AS month, toInt64(42) AS events, 'api' AS source
    """
    return (
        client.create.ql_chart.column_100p(
            name="Monthly source share",
            location=location,
        )
        .connection(connection)
        .query(query)
        .x([QLColumn("month")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("source")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

The public factory uses `column_100p`; reads return canonical ID `column100p`.
See [the exact matrix in the index](_index.md).
