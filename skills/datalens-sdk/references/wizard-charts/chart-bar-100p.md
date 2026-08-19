# 100% stacked horizontal bar Wizard chart

Factory: `client.create.wizard_chart.bar_100p(name=..., location=...)`
`chart.visualization_id`: `bar100p`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `y()` | `y` | categories | no | 2 |
| `x()` | `x` | single measure | no | 1 |
| semantic color API | `colors` | stack split dimension | no | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.bar_100p()` | `name: str`, `location: EntryLocation` | C |
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
| `label_mode()` | `*, mode: Literal['absolute', 'percent']` | CU |
| `navigator()` | `*, mode: Literal['show', 'hide']` | CU |
| `axis_visibility()` | `ph_id: Literal['x', 'y'], *, mode: Literal['show', 'hide']` | CU |
| `axis_title()` | `ph_id: Literal['x', 'y'], *, mode: Literal['off', 'manual', 'auto'], text: str = ''` | CU |
| `axis_scale()` | `ph_id: Literal['x', 'y'], *, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str \| None = None, max: str \| None = None` | CU |
| `grid()` | `ph_id: Literal['x', 'y'], *, enabled: bool, step: int \| None = None` | CU |
| `hide_labels()` | `ph_id: Literal['x', 'y'], *, enabled: bool` | CU |
| `nulls_mode()` | `ph_id: Literal['x', 'y'], *, mode: Literal['ignore', 'connect', 'as-0']` | CU |
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

category = dataset.fields.by_name("Country")
value = dataset.fields.by_name("Revenue")
segment = dataset.fields.by_name("Segment")

chart = (
    client.create.wizard_chart.bar_100p(
        name="100% stacked horizontal bar",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .y([category])
    .x([value])
    .color_by_dimension(segment)
    .label_mode(mode="percent")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
new_segment = dataset.fields.by_name("Region")
chart = chart.update.color_by_dimension(new_segment).mode("publish").execute()
```

## Constraints and gotchas

- Canonical viz id is `bar100p`; categories go to `y`, the single measure goes to `x`.
- `segments()` is not supported on horizontal 100% bars.
- Only dimension color is supported; the color placeholder has capacity 1.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
