# QL chart common operations

## Contents

- [Canonical create flow](#canonical-create-flow)
- [Connection, SQL aliases, columns, and parameters](#connection-sql-aliases-columns-and-parameters)
- [Locations and names](#locations-and-names)
- [Get and inspect](#get-and-inspect)
- [Update and replacement semantics](#update-and-replacement-semantics)
- [Branches, revisions, and re-fetching](#branches-revisions-and-re-fetching)
- [Rename, relations, export, and delete](#rename-relations-export-and-delete)
- [Opaque escape hatches](#opaque-escape-hatches)
- [Related references](#related-references)

## Canonical create flow

Accept a configured client and an existing `Connection`. Keep client
construction and credentials outside reusable chart-building code; see
[../setup.md](../setup.md) for setup.

```python
from datalens_sdk import Connection, EntryLocation, QLColumn, QLParam


def create_line_chart(
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
    WHERE 'api' IN ({{source}})
    """
    created = (
        client.create.ql_chart.line(name="SQL event trend", location=location)
        .connection(connection)
        .query(query)
        .params([QLParam.string("source", default="api")])
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("source", cast="string")])
        .build()
    )
    if created.id is None:
        raise RuntimeError("QL create response did not contain an ID")
    return client.get.ql_chart(by_id=created.id, branch="saved")
```

The factory method selects the visualization scaffold. `.build()` validates
only scaffold placeholders marked required, sends the create request, and
returns a `QLChart`. It does not execute the SQL or prove that the chart
renders. Supply a connection, a non-empty query, and semantically sufficient
placements even when the SDK does not require them.

## Connection, SQL aliases, columns, and parameters

Fetch a connection by ID when one is not already available (creating one from
scratch: [../connections.md](../connections.md)):

```python
connection = client.get.connection(by_id="connection-id")
```

`.connection()` accepts a `datalens_sdk.Connection`, not an ID string or raw
mapping, and rejects a connection without `id`. On read,
`chart.connection` is a wire-shaped mapping, not a reusable `Connection`;
fetch the domain connection again before assigning it in an update.

Each placement/decorative value is a SQL output alias:

```python
QLColumn("category")  # cast defaults to "string"
QLColumn("amount", cast="integer")
QLColumn("created_at", cast="genericdatetime")
```

Only `"string"`, `"integer"`, and `"genericdatetime"` are accepted casts.
Every QL item is encoded with a synthetic QL dataset identity and a
dimension-shaped wire item, including values placed in measure sections. Do
not substitute `DatasetField`, aggregation builders, formulas, or Wizard field
objects. The SDK does not parse SQL or verify that aliases exist, are unique,
or have compatible runtime types.

Define parameters with typed immutable values:

```python
params = [
    QLParam.number("limit", default="100"),
    QLParam.string("status", default="active"),
    QLParam.date_interval(
        "interval",
        default={"from": "__relative_-30d", "to": "__relative_-0d"},
    ),
]
```

The SQL text refers to a parameter by `{{name}}`; `.params()` serializes the
parameter list but does not bind or validate SQL placeholders. Number defaults
are strings. A date-interval default must be a mapping, but the SDK does not
validate its keys. Duplicate names and missing SQL references are not rejected.
On read, `chart.params` is a list of mappings, not `QLParam` objects.

When a QL parameter is supplied from a dashboard widget override, global
parameter, or manual selector, the receiving key is the same `QLParam` name
used in `{{name}}`. See [../parameters.md](../parameters.md) for scope,
precedence, and the dashboard validator boundary.

## Locations and names

Use one destination container:

```python
path_location = EntryLocation.path("/Team/Charts")
workbook_location = EntryLocation.workbook("workbook-id")
```

QL create accepts only path and workbook locations. For a path, the request key
is `<dir>/<name>` and `name` cannot contain `/`. For a workbook, `name` and
`workbookId` are sent separately. `EntryLocation.collection(...)`,
invented destination keywords, and a path embedded in `name` are invalid.

## Get and inspect

Use the family-specific getter when the chart is known to be QL:

```python
chart = client.get.ql_chart(by_id="chart-id")
saved = client.get.ql_chart(by_id="chart-id", branch="saved")
published = client.get.ql_chart(by_id="chart-id", branch="published")
revision = client.get.ql_chart(by_id="chart-id", rev_id="revision-id")
workbook_chart = client.get.ql_chart(
    by_id="chart-id",
    workbook_id="workbook-id",
    branch="saved",
)
```

`client.get.chart(by_id=...)` is a generic dispatcher and returns a
`WizardChart | EditorChart | QLChart`; it performs entry classification before
calling the family endpoint. Do not invent key- or path-based lookup, or a callable
getter.

Useful QL state:

```python
chart.id
chart.name
chart.category  # "ql"
chart.visualization_id  # canonical ID such as "flatTable" or "metric"
chart.query_value
chart.connection  # Mapping[str, object] | None
chart.params  # list[Mapping[str, object]]
chart.fields  # flattened placeholder items
chart.description
chart.key
chart.dir_path
chart.workbook_id
chart.collection_id
chart.wire_type
chart.data  # complete structured QL data mapping
chart.raw  # complete read response mapping
```

`chart.fields` is a read-only `FieldsProxy` flattened from visualization
placeholders; `.by_name(...)` and `.by_guid(...)` can inspect its
`DatasetField`-shaped views. Do not pass those views back to QL placement
methods; construct `QLColumn` values.

## Update and replacement semantics

Start from a freshly fetched chart because update serializes a copy of that
chart's entire current `data`:

```python
from datalens_sdk import QLColumn, QLParam


chart = client.get.ql_chart(by_id="chart-id", branch="saved")
updated = (
    chart.update.query("SELECT toDateTime(now()) AS ts, toInt64({{limit}}) AS events")
    .params([QLParam.number("limit", default="84")])
    .x([QLColumn("ts", cast="genericdatetime")])
    .y([QLColumn("events", cast="integer")])
    .description("Updated SQL event trend")
    .mode("save")
    .execute()
)
```

Typed edits preserve untouched top-level data and untouched placeholders, but
each called method replaces its entire target:

- `.query(...)` replaces `data.queryValue`.
- `.connection(...)` replaces `data.connection`.
- `.params(...)` replaces the complete `data.params` list; `[]` clears it.
- A placement method replaces that placeholder's complete `items`; `[]`
  clears it.
- A decoration method replaces the complete section or special colors
  placeholder; `[]` clears it.
- `.description(...)` updates the description while preserving other
  annotation keys.

`QLChartUpdate` exposes every placement/decorative method for typing
convenience. It fails closed when a method is not applicable to the active
visualization or the expected placeholder is absent. There is no typed method
to change visualization. Create a separate chart for a different type.

## Branches, revisions, and re-fetching

`branch` accepts only `"saved"` or `"published"`. `rev_id` pins an exact
revision; if both are passed, the client warns and ignores `branch`.
`workbook_id` is an optional getter context, not a creation destination.

An update starts in mode `"save"`:

```python
chart.update.query("SELECT 1").execute()  # save
chart.update.query("SELECT 2").mode("save").execute()  # explicit save
chart.update.query("SELECT 3").mode("publish").execute()  # publish
```

Saving can leave the published branch unchanged. Publishing sends the full
state copied from the fetched chart plus edits, so fetch the intended source
branch before building the update.

Create and update return converters over the mutation response; they do not
automatically perform a second get. Re-fetch before inspecting authoritative
state or chaining another state-dependent update:

```python
if updated.id is None:
    raise RuntimeError("QL update response did not contain an ID")
fresh = client.get.ql_chart(by_id=updated.id, branch="saved")
```

## Rename, relations, export, and delete

Rename validates the name, mutates the entry, re-fetches through the QL getter,
and returns a new `QLChart`:

```python
renamed = chart.rename("New chart name")
```

List relations lazily:

```python
relations = chart.get_relations(
    include_permissions_info=True,
    link_direction="to",
    page_size=100,
    scope="dash",
)
for relation in relations:
    print(relation.id, relation.type)
```

`link_direction` is `"from" | "to"`; `scope` is one of `"dash"`, `"report"`,
`"widget"`, `"dataset"`, `"folder"`, or `"connection"`. All relation arguments
are optional and `page_size` defaults to `100`.

Exporting a QL chart to a file (`chart.to_file(...)`), importing, and cloning
via `client.raw` work the same way as for other entries — see
[../serialization.md](../serialization.md).

Delete has no return value and requires a bound chart with an ID:

```python
chart.delete()
```

## Opaque escape hatches

Prefer typed methods. Use these only when the user supplies a known payload or
the current public typed surface cannot express an established backend field:

- Create `.visualization(mapping)` completely replaces the generated
  visualization and skips required-placeholder validation.
- Create/update `.data(mapping)` shallow-merges top-level `data` keys.
- On create, opaque data is merged after the stable scaffold and can override
  scaffold keys.
- On update, typed edits are applied first and opaque data is merged last, so
  colliding `.data(...)` keys win.
- Neither method deep-merges nested mappings or validates backend semantics.

Do not derive opaque payloads from Wizard specs. QL visualization scaffolds,
placeholder IDs, and capabilities are separate. `to_spec()` on the builders is
SDK plumbing, not a persistence operation — only `.build()` and `.execute()`
persist anything.

## Related references

- [_index.md](_index.md) — visualization routing and the exact
  factory/method matrix.
- [../core-concepts.md](../core-concepts.md) — object model, lifecycle,
  errors, retries, pagination.
- [../connections.md](../connections.md) — creating and editing the
  connection a QL chart queries.
- [../setup.md](../setup.md) — client construction, auth, environment.
- [../serialization.md](../serialization.md) — export, import, clone.
