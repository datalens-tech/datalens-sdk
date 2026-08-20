# Indicator Wizard chart

Factory: `client.create.wizard_chart.indicator(name=..., location=...)`
`chart.visualization_id`: `metric`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `y()` | `measures` | single KPI measure | yes | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.indicator()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `y()` | `fields: Sequence[Field]` | CU |
| `measures()` | `fields: Sequence[Field]` | U |
| `add_aggregated_measure()` | `field: WizardAggregatedMeasure` | CU |
| `add_local_field()` | `field: WizardLocalField` | CU |
| `add_filter()` | `field: Field, *, operation: FilterOperation, values: Sequence[str] = ()` | CU |
| `add_date_filter()` | `field: Field, *, start: str, end: str, inclusive_end: bool = True` | CU |
| `add_relative_date_filter()` | `field: Field, *, start_offset: str, end_offset: str` | CU |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU |
| `description()` | `text: str` | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU |
| `labels_position()` | `*, mode: Literal['inside', 'outside', 'auto']` | CU |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'b', 't'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `font_size()` | `*, size: Literal['xs', 's', 'm', 'l']` | CU |
| `font_color()` | `*, color: str` | CU |
| `measure_title_mode()` | `*, mode: Literal['by-field', 'manual', 'hide']` | CU |
| `replace_formula()` | `field: Field, *, formula: str` | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U |
| `replace_field()` | `old: Field, new: Field` | U |
| `delete_field()` | `field: Field` | U |
| `delete_filter()` | `field: Field` | U |
| `replace_dataset()` | `*, old: str, new: str` | U |
| `build()` | none | C |
| `mode()` | `value: EntryUpdateMode` | U |
| `execute()` | none | U |

## Canonical create

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

value = dataset.fields.by_name("Revenue")
date = dataset.fields.by_name("Date")

chart = (
    client.create.wizard_chart.indicator(
        name="Indicator",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .y([value])
    .add_relative_date_filter(date, start_offset="-30d", end_offset="+0d")
    .font_size(size="l")
    .font_color(color="#0FA08D")
    .measure_title_mode(mode="by-field")
    .measure_format(value, format="number", unit="m", precision=1)
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
dataset = client.get.dataset(by_id=chart.dataset_ids[0])
profit = dataset.fields.by_name("Profit")
chart = (
    chart.update.measures([profit])
    .measure_format(profit, format="number", unit="m", precision=1)
    .measure_title_mode(mode="hide")
    .mode("publish")
    .execute()
)
```

## Constraints and gotchas

- The public factory is `indicator()`. A fetched indicator reports
  `chart.visualization_id == "metric"`; do not use that value as a factory
  method name.
- `y` sets the required measure field, which has capacity 1.
- A generic `labels()` slot operation, sorting, palettes, color
  encodings, and axes are not supported. `labels_position()` is supported for
  positioning the indicator value. `font_color()` requires `#RRGGBB`.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
