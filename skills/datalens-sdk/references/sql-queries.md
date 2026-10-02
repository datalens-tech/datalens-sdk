# Saved SQL queries (Yandex Cloud)

This reference is for DataLens **saved SQL-query entities**. It does not route
ordinary SQL/YQL analysis or a QL chart built from SQL. The typed SqlQueries
API is available on `DataLensClientYC` only. Enterprise and YaTeam clients do
not expose these YC-only actions: looking one up raises ordinary
`AttributeError`. Do not use raw HTTP or private/generated imports to emulate
them. Follow [setup](setup.md) and the
bundled preflight before writing or running SDK code.

## Find a saved query

There is no SqlQueries list RPC. Discover entries through navigation and
compare the full name exactly on the client. Use a known workbook id to
disambiguate duplicate exact names, then fetch the query:

```python
name = "Daily revenue"
workbook_id = None  # Set to a known workbook id if exact names are duplicated
entries = list(client.navigation.get_entries(scope="sql_query", name=name, ignore_workbook_entries=False))
if workbook_id is not None:
    entries = [entry for entry in entries if entry.workbook_id == workbook_id]
matches = [entry for entry in entries if entry.name == name]
if len(matches) != 1:
    raise LookupError("Choose by exact full name with workbook or by id")
query = client.get.sql_query(by_id=matches[0].id)
```

The server's `name=` filter only narrows candidates. A name such as
`Revenue/2026` may contain a literal slash, so compare the full name. A
suffix-only candidate may be a different literal name, even in the same
workbook. Identify a path-qualified candidate by id; a workbook id alone
cannot establish that its suffix is the requested query name.

For a known id, call `client.get.sql_query(by_id=query_id)` directly. Optional `rev_id`,
`include_favorite`, and `include_permissions` are keyword-only. `None` omits an
option from the request; explicit `False` is sent. A get resolves the entry
name through navigation when the query response omits it, but `query.name`
can still be `None` if no matching navigation entry exists. See
[navigation](navigation.md) for pager and name-matching details.

## Create in a workbook

The destination must be `EntryLocation.workbook(workbook_id)`. `connection()`
accepts a connection id or a bound `Connection`; both `connection()` and
`query()` are required before the terminal `.build()` call.

```python
from datalens_sdk import EntryLocation, SqlQueryParameter

saved = (
    client.create.sql_query(
        name="Daily revenue",
        location=EntryLocation.workbook("workbook-1"),
    )
    .connection("connection-1")
    .query("select * from revenue where day = {{day}}")
    .parameters([SqlQueryParameter.date("day")])
    .description("Revenue by day")
    .build()
)
saved = client.get.sql_query(by_id=saved.id)
```

Re-fetch after persistence to check the stored query, connection, parameters,
and description. A successful write alone does not prove that the SQL will
run. See [connections](connections.md) for finding or creating a connection
and [core concepts](core-concepts.md) for builder and persistence rules.

### Saved parameter definitions

Use the typed factories below. The second argument is an optional default;
omitting it leaves `defaultValue` absent. `SqlQueryInterval(start, end)` is
used for both interval types and maps to the wire `from`/`to` fields.

```python
from datalens_sdk import SqlQueryInterval, SqlQueryParameter

parameters = [
    SqlQueryParameter.string("region", "West"),
    SqlQueryParameter.number("minimum", 100),
    SqlQueryParameter.boolean("include_returns", False),
    SqlQueryParameter.date("day", "2026-09-30"),
    SqlQueryParameter.datetime("updated_at", "2026-09-30T12:00:00"),
    SqlQueryParameter.date_interval("days", SqlQueryInterval("2026-09-01", "2026-09-30")),
    SqlQueryParameter.datetime_interval("times", SqlQueryInterval("2026-09-29T00:00:00", "2026-09-30T00:00:00")),
]
```

The types are `string`, `number`, `boolean`, `date`, `datetime`,
`date-interval`, and `datetime-interval`. Defaults must match their type; a
boolean is not a numeric default. Supplying `.parameters([])` writes an
explicitly empty list.

## Update the bound query

Fetch first and update only the requested fields. The builder starts with the
current required connection and SQL text and sends them again on `.execute()`.
It preserves optional description and parameters unless replaced.
`.parameters(values)` replaces the complete list; `.clear_parameters()` sends
an empty list, and `.description("")` clears the description.

```python
from datalens_sdk import SqlQueryParameter

query = client.get.sql_query(by_id="query-1")
updated = (
    query.update.query("select * from revenue where day >= {{day}}")
    .parameters([SqlQueryParameter.date("day")])
    .description("")
    .execute()
)
updated = client.get.sql_query(by_id=updated.id)
```

Use `query.update.clear_parameters().execute()` when parameters must be
removed. `.connection(connection_or_id)` changes the connection; a bound
connection from another installation is rejected. There is no SqlQueries
rename or move operation.

## Run only with result-handling authorization

`query.run()` returns data. Before calling it or reading its result, obtain
the user's explicit execution and result-handling authorization. If the task
only asks to prepare or save code, the saved script may contain `.run()`, but
do not launch it. For an intended run, an explicit request covering both
execution and result handling is sufficient. If execution authorization is
missing or ambiguous, ask whether to run. If result handling is missing or
ambiguous, ask whether to show results in chat, save them to a file, keep them
as a variable in a saved script, or analyze them in code. Wait for each
needed answer before running. A result destination chosen by the agent does
not authorize execution. Never inspect rows or status as an implicit smoke
test. This is [hard rule 12](../SKILL.md#hard-rules).

After that authorization, pass run-time overrides by saved parameter name.
Values may be scalars, sequences of scalars, or intervals. This independent
example assumes `query-1` already defines `region`, `minimum`, `ids`, and
`days`; it is not the one-parameter query in the create example:

```python
from datalens_sdk import SqlQueryInterval

query = client.get.sql_query(by_id="query-1")
result = query.run(
    params={
        "region": "West",
        "minimum": 100,
        "ids": [1, 2, 3],
        "days": SqlQueryInterval("2026-09-01", "2026-09-30"),
    }
)
```

`run(params=None)` omits `params`, while `run(params={})` sends an empty
mapping. The call returns one `SqlQueryRun` immediately. Its `status` is
`success`, `error`, `pending`, or `partial_success`. Its ordered `results`
contain `SqlQueryStatementSuccess` (columns, rows, optional affected-row
count) or `SqlQueryStatementError` (code, message, optional database message).
Statement errors and run-level error statuses are result data, not SDK
exceptions. Transport, API, and malformed-response failures raise SDK errors;
report an API error's request id per [troubleshooting](troubleshooting.md).
There is no run-polling endpoint for `pending` and no automatic retry for a
run. Handle only the result values the user authorized.

## Delete

Before deleting, identify the saved query by name and id and obtain explicit
confirmation. Deletion is irreversible for this entry and has no automatic
retry. After confirmation:

```python
query = client.get.sql_query(by_id="query-1")
query.delete()
```

The API has no saved-query rename or move operation. For general destructive
actions and conflict handling, follow [core concepts](core-concepts.md).
