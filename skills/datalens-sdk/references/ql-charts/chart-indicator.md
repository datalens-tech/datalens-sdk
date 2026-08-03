# QL indicator

Choose `indicator` for one headline KPI.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.indicator(...)` |
| Canonical ID | `metric` |
| Typical wire type | `metric2_ql_node` |
| Placements | `measures` required (capacity 1); `colors` optional |
| Decorations | `tooltips`; `colors` is a placeholder |

Return one aggregate row and place one numeric alias in `measures()`. The
factory deliberately follows the DataLens UI name `indicator`; `.metric()` is
not public.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_indicator(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT toInt64(42) AS total_events
    """
    return (
        client.create.ql_chart.indicator(
            name="Total events",
            location=location,
        )
        .connection(connection)
        .query(query)
        .measures([QLColumn("total_events", cast="integer")])
        .tooltips([QLColumn("total_events", cast="integer")])
        .build()
    )
```

`labels()` and `shapes()` are unsupported. `colors()` is valid but targets the
visualization's `colors` placeholder rather than top-level `data.colors`.
Reads return canonical ID `metric`. See [the exact matrix in the index](_index.md).
