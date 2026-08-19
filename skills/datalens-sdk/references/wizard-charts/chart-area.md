# Area Wizard chart

Factory: `client.create.wizard_chart.area(name=..., location=...)`
`chart.visualization_id`: `area`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x()` | `x` | category/date axis | yes | 1 |
| `y()` | `y` | single measure | no | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.area()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `x()` | `fields: Sequence[Field]` | CU |
| `y()` | `fields: Sequence[Field]` | CU |
| `add_aggregated_measure()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str \| None = None, guid: str \| None = None` | CU |
| `add_local_field()` | `*, title: str, formula: str, guid: str \| None = None, cast: str = 'float', measure: bool = False, aggregation: str \| None = None, formatting: MeasureFormat \| None = None` | CU |
| `add_hierarchy()` | `title: str, fields: Sequence[Field], *, guid: str \| None = None` | CU |
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
| `navigator()` | `*, mode: Literal['show', 'hide']` | CU |
| `axis_visibility()` | `ph_id: Literal['x', 'y'], *, mode: Literal['show', 'hide']` | CU |
| `axis_title()` | `ph_id: Literal['x', 'y'], *, mode: Literal['off', 'manual', 'auto'], text: str = ''` | CU |
| `axis_scale()` | `ph_id: Literal['x', 'y'], *, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str \| None = None, max: str \| None = None` | CU |
| `grid()` | `ph_id: Literal['x', 'y'], *, enabled: bool, step: int \| None = None` | CU |
| `hide_labels()` | `ph_id: Literal['x', 'y'], *, enabled: bool` | CU |
| `nulls_mode()` | `ph_id: Literal['x', 'y'], *, mode: Literal['ignore', 'connect', 'as-0']` | CU |
| `segments()` | `fields: Sequence[Field]` | CU |
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_dimension()` | `field: Field` | CU |
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

## Minimal create

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

date = dataset.fields.by_name("Date")
value = dataset.fields.by_name("Revenue")

chart = (
    client.create.wizard_chart.area(
        name="Area",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([value])
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
chart = chart.update.nulls_mode("y", mode="as-0").mode("publish").execute()
```

## Constraints and gotchas

- `x` is required and accepts one field; `y` accepts one measure.
- Only dimension color is supported; measure and measure-name color encodings are not.
- Sorting is supported despite older examples that treated area charts as unsortable.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
