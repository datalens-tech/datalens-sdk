# QL pie chart

Choose `pie` for part-to-whole comparison with a small number of categories.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.pie(...)` |
| Canonical ID | `pie` |
| Typical wire type | `d3_ql_node` |
| Placements | `dimensions` optional (capacity 1); `colors` optional (capacity 1); `measures` required (capacity 1) |
| Decorations | `labels`, `tooltips`; `colors` is a placeholder |

Use one category alias in `dimensions()` or `colors()` and one numeric alias
in `measures()`. Keep category cardinality low enough to remain readable.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_pie(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT 'api' AS source, toInt64(42) AS events
    """
    return (
        client.create.ql_chart.pie(name="Event share", location=location)
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
