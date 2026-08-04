# QL line chart

Choose `line` for an ordered trend and optionally a secondary value axis.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.line(...)` |
| Canonical ID | `line` |
| Typical wire type | `d3_ql_node` |
| Placements | `x` required (capacity 1); `y`, `y2` optional |
| Decorations | `colors`, `labels`, `shapes`, `tooltips` |

Use a datetime alias on `x`, value aliases on `y`/`y2`, and a categorical
alias for colors or shapes. Although only `x` is SDK-required, populate `y`
for a meaningful trend. Every listed method is valid on create and update.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_line(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT
      toDateTime('2026-07-01T00:00:00') AS ts,
      toInt64(42) AS events,
      toInt64(7) AS errors,
      'api' AS source
    """
    return (
        client.create.ql_chart.line(name="Event trend", location=location)
        .connection(connection)
        .query(query)
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .y2([QLColumn("errors", cast="integer")])
        .colors([QLColumn("source")])
        .tooltips([QLColumn("errors", cast="integer")])
        .build()
    )
```

`colors`, `labels`, `shapes`, and `tooltips` replace top-level data sections,
not placeholders. See [the exact matrix in the index](_index.md) and
[common operations](common-operations.md).
