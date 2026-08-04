# QL flat table

Choose `flat_table` to show SQL result aliases as ordered table columns.

| Contract | Value |
|---|---|
| Factory | `client.create.ql_chart.flat_table(...)` |
| Canonical ID | `flatTable` |
| Typical wire type | `table_ql_node` |
| Placements | `flat_table_columns` required; no declared capacity |
| Decorations | `colors`, `tooltips` |

Pass the complete column order to `flat_table_columns()`. The wire placeholder
ID is `flat-table-columns`, but the public method is snake case.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn


def create_flat_table(
    client,
    *,
    connection: Connection,
    location: EntryLocation,
):
    query = """
    SELECT
      toDateTime('2026-07-01T00:00:00') AS ts,
      'api' AS source,
      toInt64(42) AS events
    """
    return (
        client.create.ql_chart.flat_table(
            name="Event details",
            location=location,
        )
        .connection(connection)
        .query(query)
        .flat_table_columns(
            [
                QLColumn("ts", cast="genericdatetime"),
                QLColumn("source"),
                QLColumn("events", cast="integer"),
            ]
        )
        .tooltips([QLColumn("source")])
        .build()
    )
```

There are no typed QL pagination, totals, formatting, sorting, or column-width
methods. Reads return canonical ID `flatTable`. See
[the exact matrix in the index](_index.md).
