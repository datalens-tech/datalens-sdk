# QL treemap

Choose `treemap` for hierarchical or categorical part-to-whole area.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.treemap(...)` |
| Canonical ID | `treemap` |
| Typical wire type | `d3_ql_node` |
| Placements | `dimensions` required (no declared capacity); `measures` required (capacity 1) |
| Decorations | `colors`, `tooltips` |

Place one or more hierarchy aliases in `dimensions()` in outer-to-inner order
and one numeric tile-size alias in `measures()`.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_treemap(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT 'platform' AS team, 'api' AS service, toInt64(42) AS events
    """
    return (
        client.create.ql_chart.treemap(
            name="Service footprint",
            location=location,
        )
        .connection(connection)
        .query(query)
        .dimensions([QLColumn("team"), QLColumn("service")])
        .measures([QLColumn("events", cast="integer")])
        .colors([QLColumn("events", cast="integer")])
        .tooltips([QLColumn("service")])
        .build()
    )
```

`labels()` and `shapes()` are unsupported. `colors()` writes top-level
`data.colors`. See [the exact matrix in the index](_index.md).
