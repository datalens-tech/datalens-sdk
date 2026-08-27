# Reading dataset data

Read this when the task needs actual rows from an existing dataset. This is a
read-only API: it does not alter the dataset, its fields, or its sources.

## Result-handling permission is mandatory

Never call a data-returning method or inspect its returned values unless the
user explicitly requested or permitted how the result will be handled. A
request to build or save code is not permission to run it or read its result.

If the task does not make the intended handling unambiguous, stop before the
call and ask the user to choose whether the result should be:

- shown in chat;
- saved to a file;
- kept in a saved script where it remains available in a variable; or
- analyzed in code.

Proceed only after the user answers, and use the result solely in the approved
form. Do not print, iterate, summarize, sample, validate, count, or otherwise
inspect the returned rows as an implicit smoke test.

## Basic query

Fetch the dataset first when field names, types, or parameter fields must be
resolved. Pass `DatasetField` objects whenever possible; a string is treated
as an exact field GUID, not as a title or source-column name.

```python
dataset = client.get.dataset(by_id=dataset_id)
date = dataset.fields.by_name("Order Date")
sales = dataset.fields.by_name("Sales")

result = client.data.get_dataset_data(
    dataset_id=dataset.id,
    columns=[date, sales],
)

# Equivalent after fetching the dataset:
result = dataset.get_dataset_data(columns=[date, sales])
```

## Filters, parameters, sorting, and pagination

```python
from datalens_sdk import DatasetDataFilter, DatasetDataParameter, DatasetDataSort

region = dataset.fields.by_name("Region")
threshold = dataset.parameters.by_name("Threshold")

result = client.data.get_dataset_data(
    dataset_id=dataset.id,
    columns=[date, region, sales],
    filters=[DatasetDataFilter(region, "IN", ("East", "West"))],
    params=[DatasetDataParameter(threshold, 100)],
    sort=[DatasetDataSort(date, "asc"), DatasetDataSort(sales, "desc")],
    limit=500,
    offset=500,
)
```

Every field used by `sort` must also be present in `columns`. A positive
`offset` requires a non-empty sort. For stable pagination, sort by a total
order and add a tie-breaking field when values can repeat. Filters, parameters,
and sort rules also accept exact GUID strings, but `DatasetField` objects catch
cross-dataset mistakes before a request is sent.

`DatasetDataFilter.values` and `DatasetDataParameter.value` accept strings,
numbers, and booleans. Use the shared uppercase `WhereOperation` literals,
such as `"EQ"`, `"IN"`, `"BETWEEN"`, `"ISNULL"`, and `"CONTAINS"`. The SDK
converts them to the lowercase values accepted by the API.

## Result and failures

`DatasetData.schema` describes row positions in order. Each row is a tuple of
JSON values in that same order. Do not infer a row value's meaning without its
corresponding schema column.

The request is a read RPC and uses the SDK's transient retry policy. Invalid
arguments fail locally with `DataLensValidationError`; malformed responses
raise `DTOValidationError`; API and transport failures retain their ordinary
typed SDK errors and request ids.
