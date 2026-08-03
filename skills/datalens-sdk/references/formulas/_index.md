# DataLens Formulas

The official DataLens documentation is the source of truth for formula syntax,
function signatures, examples, and source-specific availability. This
reference only adds the public SDK ownership and persistence workflow.

QL chart queries are SQL, and Editor chart tabs contain JavaScript or JSON.
Neither uses the DataLens formula language described here.

## Official Documentation

Start with:

- [Formula syntax](https://yandex.cloud/ru/docs/datalens/concepts/calculations/formula-syntax)
- [All functions](https://yandex.cloud/ru/docs/datalens/function-ref/all)
- [Function availability by data source](https://yandex.cloud/ru/docs/datalens/function-ref/availability)

Load only the category needed for the task:

| Category | Official reference |
|---|---|
| Aggregation | [Aggregate functions](https://yandex.cloud/ru/docs/datalens/function-ref/aggregation-functions) |
| Conditions | [Logical functions](https://yandex.cloud/ru/docs/datalens/function-ref/logical-functions) |
| Arithmetic | [Numeric functions](https://yandex.cloud/ru/docs/datalens/function-ref/numeric-functions) |
| Database-specific expressions | [Native functions](https://yandex.cloud/ru/docs/datalens/function-ref/native-functions) |
| Windows and ranking | [Window functions](https://yandex.cloud/ru/docs/datalens/function-ref/window-functions) |
| Operators | [Operator functions](https://yandex.cloud/ru/docs/datalens/function-ref/operator-functions) |
| Text | [String functions](https://yandex.cloud/ru/docs/datalens/function-ref/string-functions) |
| Dates and time | [Date functions](https://yandex.cloud/ru/docs/datalens/function-ref/date-functions) |
| Time-series comparisons | [Time-series functions](https://yandex.cloud/ru/docs/datalens/function-ref/time-series-functions) |
| Arrays | [Array functions](https://yandex.cloud/ru/docs/datalens/function-ref/array-functions) |
| Type conversion | [Type-conversion functions](https://yandex.cloud/ru/docs/datalens/function-ref/type-conversion-functions) |
| Parameters | [Parameters](https://yandex.cloud/ru/docs/datalens/concepts/parameters) |
| Rich text and links | [Markup functions](https://yandex.cloud/ru/docs/datalens/function-ref/markup-functions) |
| Hashing | [Hash functions](https://yandex.cloud/ru/docs/datalens/function-ref/hash-functions) |

For advanced worked examples, use the official tutorials:

- [Aggregations and grouping](https://yandex.cloud/ru/docs/datalens/concepts/aggregation-tutorial)
- [LOD expressions and filter control](https://yandex.cloud/ru/docs/datalens/concepts/lod-aggregation)
- [Window functions](https://yandex.cloud/ru/docs/datalens/concepts/window-function-tutorial)
- [Time-series functions](https://yandex.cloud/ru/docs/datalens/concepts/time-series-functions)

Cloud documentation can be newer than the selected Enterprise installation.
The SDK version pins the mutation API, not server-side formula semantics.
Check the availability table for the actual connection type and deployment.
If documentation cannot be accessed, provide a qualified template and state
that the exact syntax and availability remain unverified.

## SDK Workflow

1. Inspect the real Dataset or Wizard chart and its backing Dataset.
2. Resolve the exact owner, fields, parameter names, types, aggregations, and
   chart grouping. Do not invent titles, GUIDs, casts, or aggregations.
3. Choose the owner:
   - Dataset calculation for reuse across charts;
   - Wizard local field for one chart;
   - cache-invalidation formula only for cache freshness.
4. Use the official syntax and function reference, then check availability for
   the actual source.
5. Apply one narrow public SDK mutation and finish with `.execute()`.
6. Re-fetch the owner and verify the stored field and formula text.
7. Validate or render separately. Persistence does not prove semantic validity.

If no live artifact or identifier is available, state assumptions and do not
claim server validation.

See [SDK formula surfaces](sdk-surfaces.md) for the exact ownership signals,
read surfaces, propagation rules, and excluded lookalikes.

## Diagnosis Boundary

- Unknown field or parameter: inspect the live owner; do not guess spelling.
- Inconsistent aggregation: inspect the expression levels and chart grouping,
  then use the official aggregation and window documentation.
- Unsupported function: check the official availability matrix for the
  connection type and deployment.
- Persisted formula that fails to render: report persistence as successful but
  semantic validation as failed or incomplete.
- Missing public setter: stop at the public SDK boundary; do not switch to raw
  HTTP, private imports, or a hand-built payload.
