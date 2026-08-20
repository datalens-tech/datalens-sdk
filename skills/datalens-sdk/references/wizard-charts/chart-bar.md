# Horizontal bar Wizard chart

Factory: `client.create.wizard_chart.bar(name=..., location=...)`
`chart.visualization_id`: `bar`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `y()` | `y` | categories | no | 2 |
| `x()` | `x` | measures (bar length) | no | unbounded |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.bar()` | `name: str`, `location: EntryLocation` | C |
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
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_dimension()` | `field: Field` | CU |
| `color_by_measure()` | `field: Field, *, mode: Literal['2-point', '3-point'] \| None = None, palette: GradientPaletteId \| None = None, reversed: bool \| None = None` | CU |
| `color_by_measure_name()` | `*, colors_map: Mapping[Field, str] \| None = None` | CU |
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

category = dataset.fields.by_name("Country")
value = dataset.fields.by_name("Revenue")

chart = (
    client.create.wizard_chart.bar(
        name="Horizontal bar",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .y([category])
    .x([value])
    .add_sort(value, direction="desc")
    .labels([value])
    .labels_position(mode="inside")
    .measure_format(value, format="number", precision=0, show_rank_delimiter=True)
    .axis_title("x", mode="manual", text="Revenue")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
chart = chart.update.axis_title("x", mode="manual", text="Revenue").mode("publish").execute()
```

## Constraints and gotchas

- Bar axes are inverted: put categories in `y` and measures in `x`.
- `y` has capacity 2; `x` accepts any number of measures.
- Multiple measures insert `Measure Names` into `y` and consume one of its two
  category slots. Use at most one ordinary `y` category with multi-measure
  coloring.
- Use `add_sort(measure, direction="desc")` for a horizontal ranking.
- `segments()` is not supported. Use color encoding or multiple measures instead.
- Supported transition: `bar -> line`.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
