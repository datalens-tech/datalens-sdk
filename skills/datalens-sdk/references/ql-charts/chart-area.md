# QL area chart

Choose `area` for magnitude over an ordered axis, often split into colored
series.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.area(...)` |
| Canonical ID | `area` |
| Typical wire type | `d3_ql_node` |
| Placements | `x` required (capacity 1); `y` optional |
| Decorations | `colors`, `labels`, `tooltips` |

Populate `y` even though only `x` is enforced by the current builder. Use
`area_100p` instead when the desired value is each series' share of the whole.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_area(
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
        client.create.ql_chart.area(name="Event volume", location=location)
        .connection(connection)
        .query(query)
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("source")])
        .labels([QLColumn("events", cast="integer")])
        .build()
    )
```

All listed methods are valid on create and update and replace their complete
target lists. See [the exact matrix in the index](_index.md).
