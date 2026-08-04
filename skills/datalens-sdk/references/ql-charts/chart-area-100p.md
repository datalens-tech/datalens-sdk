# QL 100% area chart

Choose `area_100p` to compare each colored series as a percentage of the total
at every ordered `x` value.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.area_100p(...)` |
| Canonical ID | `area100p` |
| Typical wire type | `d3_ql_node` |
| Placements | `x` required (capacity 1); `y` optional |
| Decorations | `colors`, `labels`, `tooltips` |

Provide a series alias through `colors()`; without a split, 100% normalization
usually carries little information.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_area_100p(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT
      toDateTime('2026-07-01T00:00:00') AS ts,
      toInt64(42) AS events,
      'api' AS source
    """
    return (
        client.create.ql_chart.area_100p(
            name="Event share over time",
            location=location,
        )
        .connection(connection)
        .query(query)
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("source")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

The public factory uses `area_100p`; reads return canonical ID `area100p`.
See [the exact matrix in the index](_index.md).
