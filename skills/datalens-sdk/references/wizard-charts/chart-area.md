# Area Wizard chart

Factory: `client.create.wizard_chart.area(name=..., location=...)`
`chart.visualization_id`: `area`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x()` | `x` | category/date axis | yes | 1 |
| `y()` | `y` | measures | no | no SDK limit specified |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.area()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `x()` | `fields: Sequence[Field]` | CU |
| `y()` | `fields: Sequence[Field]` | CU |
| `add_aggregated_measure()` | `field: WizardAggregatedMeasure` | CU |
| `add_local_field()` | `field: WizardLocalField` | CU |
| `add_hierarchy()` | `hierarchy: WizardHierarchy` | CU |
| `add_filter()` | `field: Field, *, operation: FilterOperation, values: Sequence[str] = ()` | CU |
| `add_date_filter()` | `field: Field, *, start: str, end: str, inclusive_end: bool = True` | CU |
| `add_relative_date_filter()` | `field: Field, *, start_offset: str, end_offset: str` | CU |
| `add_sort()` | `field: Field, *, direction: Literal['asc', 'desc'] = 'asc'` | CU |
| `sort()` | `fields: Sequence[Field]` | C |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU |
| `description()` | `text: str` | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU |
| `tooltip()` | `*, mode: Literal['show', 'hide']` | CU |
| `labels()` | `fields: Sequence[Field]` | CU |
| `label_mode()` | `*, mode: Literal['absolute']` | CU |
| `navigator()` | `*, mode: Literal['show', 'hide']` | CU |
| `axis_visibility()` | `slot_name: Literal['x', 'y'], *, mode: Literal['show', 'hide']` | CU |
| `axis_title()` | `slot_name: Literal['x', 'y'], *, mode: Literal['off', 'manual', 'auto'], text: str = ''` | CU |
| `axis_scale()` | `slot_name: Literal['y'], *, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str \| None = None, max: str \| None = None` | CU |
| `grid()` | `slot_name: Literal['x', 'y'], *, enabled: bool, step: int \| None = None` | CU |
| `hide_labels()` | `slot_name: Literal['x', 'y'], *, enabled: bool` | CU |
| `nulls_mode()` | `slot_name: Literal['y'], *, mode: Literal['ignore', 'connect', 'as-0', 'use-previous']` | CU |
| `segments()` | `fields: Sequence[Field]` | CU |
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_dimension()` | `field: Field` | CU |
| `color_by_measure_name()` | `*, colors_map: Mapping[Field, str] \| None = None` | CU |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'b', 't'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `replace_formula()` | `field: Field, *, formula: str` | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U |
| `replace_field()` | `old: Field, new: Field` | U |
| `delete_field()` | `field: Field` | U |
| `delete_filter()` | `field: Field` | U |
| `replace_dataset()` | `*, old: str, new: str` | U |
| `build()` | none | C |
| `mode()` | `value: EntryUpdateMode` | U |
| `execute()` | none | U |

## Create with two measures

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

date = dataset.fields.by_name("Date")
revenue = dataset.fields.by_name("Revenue")
cost = dataset.fields.by_name("Cost")

chart = (
    client.create.wizard_chart.area(
        name="Area",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([revenue, cost])
    .color_by_measure_name(colors_map={revenue: "#3366CC", cost: "#DC3912"})
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
revenue_field = chart.fields.by_guid(revenue.guid)
cost_field = chart.fields.by_guid(cost.guid)
chart = (
    chart.update.color_by_measure_name(colors_map={revenue_field: "#DC3912", cost_field: "#3366CC"})
    .mode("publish")
    .execute()
)
```

## Constraints and gotchas

- Place one field on `x` and one or more measures of compatible units on `y`. The SDK does not impose a numeric limit on the number of Y measures.
- With at least two Y measures, the SDK adds the Measure Names color binding when no explicit color binding is set. Use `color_by_dimension()` for a dimension binding or `color_by_measure_name()` to set colors per measure.
- Use `#RRGGBB`, `#RRGGBBAA`, or non-negative palette indexes as strings in `colors_map`. Measures without an explicit color get an index in Y order.
- Use field objects or their GUIDs as color map keys. Display names set with `fakeTitle` do not change those keys.
- When the Y measures change, the SDK keeps existing colors for retained measures, assigns palette indexes to new measures, and removes the Measure Names binding if fewer than two measures remain. An explicit dimension binding is preserved.
- Sorting is supported despite older examples that treated area charts as unsortable.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
