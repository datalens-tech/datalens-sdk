# Treemap Wizard chart

Factory: `client.create.wizard_chart.treemap(name=..., location=...)`
`chart.visualization_id`: `treemap`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x()` | `dimensions` | hierarchy levels | yes | unbounded |
| `y()` | `measures` | tile size | yes | 1 |
| semantic color API | `colors` | tile color | no | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.treemap()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `x()` | `fields: Sequence[Field]` | CU |
| `y()` | `fields: Sequence[Field]` | CU |
| `measures()` | `fields: Sequence[Field]` | U |
| `add_aggregated_measure()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str \| None = None, guid: str \| None = None` | CU |
| `add_local_field()` | `*, title: str, formula: str, guid: str \| None = None, cast: str = 'float', measure: bool = False, aggregation: str \| None = None, formatting: MeasureFormat \| None = None` | CU |
| `add_filter()` | `field: Field, *, operation: FilterOperation, values: Sequence[str] = ()` | CU |
| `add_date_filter()` | `field: Field, *, start: str, end: str, inclusive_end: bool = True` | CU |
| `add_relative_date_filter()` | `field: Field, *, start_offset: str, end_offset: str` | CU |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU |
| `description()` | `text: str` | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU |
| `tooltips()` | `fields: Sequence[Field]` | CU |
| `labels()` | `fields: Sequence[Field]` | CU |
| `labels_position()` | `*, mode: Literal['inside', 'outside', 'auto']` | CU |
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_dimension()` | `field: Field` | CU |
| `color_by_measure()` | `field: Field, *, mode: Literal['2-point', '3-point'] \| None = None, palette: GradientPaletteId \| None = None, reversed: bool \| None = None` | CU |
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

## Canonical create

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

category = dataset.fields.by_name("Category")
subcategory = dataset.fields.by_name("Subcategory")
value = dataset.fields.by_name("Revenue")
color_value = dataset.fields.by_name("Profit")

chart = (
    client.create.wizard_chart.treemap(
        name="Treemap",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([category, subcategory])
    .y([value])
    .color_by_measure(color_value, mode="3-point", palette="red-orange-green")
    .tooltips([value, color_value])
    .measure_format(value, format="currency", unit="m", precision=1)
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
chart = chart.update.color_by_measure(color_value, mode="2-point", palette="blue").mode("publish").execute()
```

## Constraints and gotchas

- `x` aliases required, unbounded `dimensions`; `y` aliases required `measures` with capacity 1.
- Dimension color is valid only when the same field is already present in `dimensions`; measure color is also supported.
- Sorting, hierarchies, axes, label mode, and measure-name color are not supported.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
