# Line Wizard chart

Factory: `client.create.wizard_chart.line(name=..., location=...)`
`chart.visualization_id`: `line`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x()` | `x` | category/date axis | yes | 1 |
| `y()` | `y` | primary measures | no | unbounded |
| `y2()` | `y2` | secondary-axis measures | no | unbounded |
| semantic shape API | `shapes` | semantic series shapes | no | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.line()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `x()` | `fields: Sequence[Field]` | CU |
| `y()` | `fields: Sequence[Field]` | CU |
| `y2()` | `fields: Sequence[Field]` | CU |
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
| `axis_visibility()` | `slot_name: Literal['x', 'y', 'y2'], *, mode: Literal['show', 'hide']` | CU |
| `axis_title()` | `slot_name: Literal['x', 'y', 'y2'], *, mode: Literal['off', 'manual', 'auto'], text: str = ''` | CU |
| `axis_scale()` | `slot_name: Literal['y', 'y2'], *, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str \| None = None, max: str \| None = None` | CU |
| `grid()` | `slot_name: Literal['x', 'y', 'y2'], *, enabled: bool, step: int \| None = None` | CU |
| `hide_labels()` | `slot_name: Literal['x', 'y', 'y2'], *, enabled: bool` | CU |
| `nulls_mode()` | `slot_name: Literal['y', 'y2'], *, mode: Literal['ignore', 'connect', 'as-0', 'use-previous']` | CU |
| `segments()` | `fields: Sequence[Field]` | CU |
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_dimension()` | `field: Field` | CU |
| `color_by_measure_name()` | `*, colors_map: Mapping[Field, str] \| None = None` | CU |
| `shape_by_dimension()` | `field: Field, *, shapes_map: Mapping[str, ShapeStyle] \| None = None` | CU |
| `shape_by_measure_name()` | `*, shapes_map: Mapping[Field, ShapeStyle] \| None = None` | CU |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'b', 't'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `replace_formula()` | `field: Field, *, formula: str` | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U |
| `replace_field()` | `old: Field, new: Field` | U |
| `delete_field()` | `field: Field` | U |
| `delete_filter()` | `field: Field` | U |
| `replace_dataset()` | `*, old: str, new: str` | U |
| `change_visualization_to()` | `*, visualization_id: str` | U |
| `build()` | none | C |
| `mode()` | `value: EntryUpdateMode` | U |
| `execute()` | none | U |

## Canonical create

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

date = dataset.fields.by_name("Date")
revenue = dataset.fields.by_name("Revenue")
conversion = dataset.fields.by_name("Conversion")
segment = dataset.fields.by_name("Segment")

chart = (
    client.create.wizard_chart.line(
        name="Revenue and conversion",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([revenue])
    .y2([conversion])
    .color_by_dimension(segment)
    .add_relative_date_filter(date, start_offset="-30d", end_offset="+0d")
    .axis_title("y", mode="manual", text="Revenue")
    .axis_title("y2", mode="manual", text="Conversion")
    .grid("y", enabled=True)
    .nulls_mode("y", mode="connect")
    .navigator(mode="show")
    .measure_format(conversion, format="percent", precision=1)
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
dataset = client.get.dataset(by_id=chart.dataset_ids[0])
profit = dataset.fields.by_name("Profit")
chart = chart.update.y([profit]).chart_title(text="Profit and conversion").mode("publish").execute()
```

## Constraints and gotchas

- `x` is required with capacity 1; `y` and `y2` are unbounded.
- Line uniquely supports both dimension/measure-name color and dimension/measure-name shape encodings.
- `color_by_measure_name()` and `shape_by_measure_name()` require at least two
  placed measures. See [operation recipes](operation-recipes.md).
- Supported transitions: `line -> column`, `line -> bar`.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
