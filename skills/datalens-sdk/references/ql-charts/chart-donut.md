# QL donut chart

Choose `donut` for the same part-to-whole task as pie when a ring presentation
is preferred.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.donut(...)` |
| Canonical ID | `donut` |
| Typical wire type | `d3_ql_node` |
| Placements | `dimensions` optional (capacity 1); `colors` optional (capacity 1); `measures` required (capacity 1) |
| Decorations | `labels`, `tooltips`; `colors` is a placeholder |

Use one category alias and one numeric measure. The SDK scaffold capacity is
one for each placement even though older live payloads may contain more items.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_donut(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT 'api' AS source, toInt64(42) AS events
    """
    return (
        client.create.ql_chart.donut(name="Event share ring", location=location)
        .connection(connection)
        .query(query)
        .dimensions([QLColumn("source")])
        .colors([QLColumn("source")])
        .measures([QLColumn("events", cast="integer")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

Here `colors()` replaces the visualization's `colors` placeholder; it does
not write top-level `data.colors`. See [the exact matrix in the index](_index.md).
