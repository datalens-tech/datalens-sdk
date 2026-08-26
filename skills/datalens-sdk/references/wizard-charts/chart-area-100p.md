# 100% stacked area Wizard chart

Factory: `client.create.wizard_chart.area_100p(name=..., location=...)`
`chart.visualization_id`: `area100p`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x()` | `x` | category/date axis | yes | 1 |
| `y()` | `y` | single measure | no | 1 |
| semantic color API | `colors` | stack split dimension | no | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.area_100p()` | `name: str`, `location: EntryLocation` | C |
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
| `label_mode()` | `*, mode: Literal['absolute', 'percent']` | CU |
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
segment = dataset.fields.by_name("Segment")

chart = (
    client.create.wizard_chart.area_100p(
        name="100% stacked area",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([value])
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

- Canonical viz id is `area100p`, not the factory spelling `area_100p`.
- `x`, `y`, and the color split each have capacity 1; `x` is required.
- `segments()` is supported in addition to semantic dimension color.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
