# Combined chart Wizard chart

Factory: `client.create.wizard_chart.combined_chart(name=..., location=...)`
`chart.visualization_id`: `combined-chart`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Public input | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x(fields)` | each layer's `x` | shared category/date axis | layer-dependent | 1 |
| `add_layer(..., y=...)` | layer `y` | primary measure | `y` or `y2` | 1 per layer call |
| `add_layer(..., y2=...)` | layer `y2` | secondary-axis measure | `y` or `y2` | 1 per layer call |

`x()` sets the shared axis. Each `add_layer()` call creates its layer-specific measure field.

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.combined_chart()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `x()` | `fields: Sequence[Field]` | CU |
| `add_layer()` | `layer_type: CombinedLayerType, *, y: Field \| None = None, y2: Field \| None = None, name: str \| None = None` | C |
| `add_aggregated_measure()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str \| None = None, guid: str \| None = None` | CU |
| `add_local_field()` | `*, title: str, formula: str, guid: str \| None = None, cast: str = 'float', measure: bool = False, aggregation: str \| None = None, formatting: MeasureFormat \| None = None` | CU |
| `add_filter()` | `field: Field, *, operation: FilterOperation, values: Sequence[str] = ()` | CU |
| `add_date_filter()` | `field: Field, *, start: str, end: str, inclusive_end: bool = True` | CU |
| `add_relative_date_filter()` | `field: Field, *, start_offset: str, end_offset: str` | CU |
| `add_sort()` | `field: Field, *, direction: Literal['asc', 'desc'] = 'asc'` | CU |
| `sort()` | `fields: Sequence[Field]` | C |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU |
| `description()` | `text: str` | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU |
| `tooltips()` | `fields: Sequence[Field]` | CU |
| `labels()` | `fields: Sequence[Field]` | CU |
| `labels_position()` | `*, mode: Literal['inside', 'outside', 'auto']` | CU |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent', 'currency'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'bln'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `replace_formula()` | `field: Field, *, formula: str` | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U |
| `replace_field()` | `old: Field, new: Field` | U |
| `delete_field()` | `field: Field` | U |
| `delete_filter()` | `field: Field` | U |
| `replace_dataset()` | `*, old: str, new: str` | U |
| `build()` | none | C |
| `mode()` | `value: EntryUpdateMode` | U |
| `execute()` | none | U |

## Minimal create

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

date = dataset.fields.by_name("Date")
value = dataset.fields.by_name("Revenue")
rate = dataset.fields.by_name("Conversion")

chart = (
    client.create.wizard_chart.combined_chart(
        name="Combined chart",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .add_layer("column", y=value, name="Revenue")
    .add_layer("line", y2=rate, name="Conversion")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
new_date = dataset.fields.by_name("Month")

chart = client.get.wizard_chart(by_id=chart.id)
chart = chart.update.x([new_date]).chart_title(text="Revenue and conversion").mode("publish").execute()
```

## Constraints and gotchas

- `x` is copied into every layer and accepts at most one field.
- `add_layer()` is create-only and requires at least one of `y=` or `y2=`. Layer types are `column`, `line`, and `area`.
- Layer topology cannot be changed by `WizardChartUpdate`; update can change shared `x` and chart-wide settings.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
