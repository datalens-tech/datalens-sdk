# Reading chart data

Read this when the task needs tables from a saved Wizard, QL, or Editor chart.
The experimental read RPC `/rpc/getChartData` is available in the Enterprise
and Yandex Cloud contracts. It uses the chart's stored configuration and does
not modify the chart. Availability on a server follows its API contract.

## Result-handling permission is mandatory

Returned tables contain the user's data.

Never call a data-returning method or inspect its returned values unless the
user explicitly requested or permitted how the result will be handled. A
request to build or save code is not permission to run it or read its result.

If the intended handling is unclear, ask whether the result should be shown in
chat, saved to a file, kept in a saved script where it remains available in a
variable, or analyzed in code. Wait for the answer before calling the method.
Use the result only in the approved form. Do not print, iterate, summarize,
sample, validate, count, or otherwise inspect rows as an implicit smoke test.
The examples below leave the result in a variable; they do not authorize
execution or any other handling.

## Two entrypoints, one operation

```python
result = client.data.get_chart_data(
    chart_id="<saved-chart-id>",
    params={"region": ["East", "West"], "year": "2026"},
)

# The same operation on an already loaded, client-bound chart:
result = chart.get_chart_data(params={"region": ["East", "West"], "year": "2026"})
```

`chart_id` is a non-empty saved chart ID. Both methods take keyword-only
arguments and return `ChartData`, a union of `WizardChartData`, `QLChartData`,
and `EditorChartData`. The bound method is inherited by all three chart
families; an unbound chart or a chart without an ID fails before HTTP.
There is no preliminary metadata fetch for the namespace call.

Both entrypoints execute **by ID**. A loaded chart's `rev_id`, branch pointers,
and local content are not sent. Loading a historical revision does not pin the
subsequent data query to that revision. The API does not specify which
saved/published revision is selected. There is no `rev_id` or `branch`
argument. The SDK rejects `revId` and `branch` in `params` before HTTP because
revision selection is unsupported. The SDK cannot select a draft or historical
revision for export. Do not claim that returned rows belong to the loaded or
requested revision. This differs from [screenshots](screenshots.md), whose SDK
request includes the loaded revision for rendering. `dataset.get_dataset_data()`
also executes by ID; see [dataset data](dataset-data.md).

`chart.to_file(...)` serializes the chart definition, not its returned data.
This operation returns tables in memory. It does not provide CSV/XLSX, pandas,
file export, or a dashboard-wide data export.

To read a chart with the filters of a dashboard state link, see
[dashboard state](dashboard-state.md#screenshots-and-chart-data).

## Runtime parameters

`RuntimeParams` maps string names to `RuntimeParamValue`: a string or a
sequence of strings. `params=None` omits the field; `params={}` sends an empty
object. Scalar strings remain strings, sequences become JSON arrays, and
empty strings, empty sequences, Unicode, and value order are preserved. The
request snapshots the caller's mapping and sequences. Format numeric and date
values as strings yourself; numbers, booleans, `None`, bytes, nested mappings,
and sequences containing non-string items fail locally.

Only caller parameters are sent under `params`. The SDK does not add page,
theme, dashboard state, or revision parameters. It rejects `revId` and `branch`
for unsupported revision selection, and rejects `tab` and `state` because
dashboard tabs and saved selector states are not chart-data parameters. All
four names fail with `DataLensValidationError` before HTTP; remove them from
`params`. Empty names and names beginning with `_` remain accepted, unlike
screenshots. The SDK does not check names against QL or Editor defaults:
chart code may read a key absent from its declared defaults. A valid parameter
shape does not prove that the chart reads the key or that a value changes its
output.

Chart data and screenshots share value types, copying, and serialization.
`ScreenshotParams` and `ScreenshotParamValue` remain compatible aliases;
screenshot-specific validation and `queryParams` payloads are unchanged.
Choose keys using the shared [runtime chart parameter guidance](parameters.md#runtime-chart-parameters):
Wizard field GUIDs or dataset parameter names, QL parameters read by SQL, and
Editor keys read by chart code. It covers defaults, unused keys, the QL
scalar/tuple caveat, and how these params differ from `DatasetDataFilter`.
The `region` and `year` names in the examples assume that the chart reads
those exact keys; they are not universal filter names.

There are no separate `columns`, `filters`, `sort`, `limit`, or `offset`
arguments. The dataset default `limit=500` does not apply. Pagination can be
expressed through server-specific parameters, but its keys and termination
rules are not specified here. The SDK provides no automatic pagination and
makes no guarantee that one response contains every row.

## Ordered tables and typed columns

`ChartData.chart_type` distinguishes `"wizard"`, `"ql"`, and `"editor"`.
Each result contains an ordered tuple of `ChartDataTable` objects in `results`.
Every table has its own `schema` and positional `rows`; multiple tables are
kept separate, including those with different schemas. Empty results and empty
tables are valid.

| Result | Table column type | Column fields |
|---|---|---|
| `WizardChartData` | `WizardChartDataColumn` | `name`, string `type`, optional `guid` |
| `QLChartData` | `QLChartDataColumn` | `name`, string `type` |
| `EditorChartData` | `EditorChartDataColumn` | `name` |

Narrow on `chart_type` before using family-specific column fields. The type
of the loaded chart is not a guarantee of the server's response variant.
Column names can repeat, so do not convert rows to dictionaries keyed by name.
Tables, schemas, and rows use tuples; nested JSON arrays and objects inside
cells are independent deep copies and remain mutable.

The SDK preserves JSON values without conversion: QL numeric strings remain
strings, unknown Wizard type names remain strings, and missing GUIDs/types
are not invented. It does not pad or truncate rows to schema width. Large
Wizard integers can lose precision on the server; the SDK cannot recover it.
Table indices are not query or block IDs.

## Server limits and failures

Pivot tables are unsupported. Editor sources must provide raw data through
`Editor.setRawData()`; a visible chart alone does not establish that raw data
is available. Do not infer an Editor failure from an empty result alone.
Editor `module` resources contain reusable JavaScript and never have chart
data. Where an installation exposes Modules, exclude them from data export;
adding `Editor.setRawData()` does not turn a Module into a visual chart.

The operation specifies these aggregate response limits: 100,000 rows,
100,000 cells, 1,000 tables, and 100,000 schema columns, with at most 800 columns
per table. All limits apply simultaneously across the response: if every row
has two cells, the cell limit allows at most 50,000 rows in total. Exceeding a
limit returns HTTP 422. The API does not promise a partial response. The SDK
neither truncates results nor bypasses the limits.

The [Yandex Cloud limits page](https://yandex.cloud/ru/docs/datalens/concepts/limits#datalens-chart-data-limits)
also documents limits for displaying each chart type and API rates of 60
requests per minute per user and 200 per minute per DataLens instance. Those
are Yandex Cloud service limits; the per-type display limits are not a
universal `getChartData` response contract for Enterprise and Yandex Cloud.
Account for repeated attempts under the retry policy when planning call rates.

Invalid chart arguments raise `DataLensValidationError` before HTTP.
Malformed responses raise `DTOValidationError` or `InvalidResponseError`.
API and transport failures use the existing SDK exceptions. HTTP/API errors
retain their code, details, and `error.context.request_id`; include that ID
when reporting a failed call. Do not invent specific error codes for pivot,
missing Editor raw data, export restrictions, or permissions.

Chart data uses the ordinary transient read retry policy, which can execute
the read more than once. HTTP 422 is not retried. This is independent of the
screenshot render timeout and rate-limit loop.
