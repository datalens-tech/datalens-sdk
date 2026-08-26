# Scatter Wizard chart

Factory: `client.create.wizard_chart.scatter(name=..., location=...)`
`chart.visualization_id`: `scatter`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `x()` | `x` | X measure | yes | 1 |
| `y()` | `y` | Y measure | yes | 1 |
| `points()` | `points` | point identity/category | no | 1 |
| `size()` | `size` | bubble size measure | no | 1 |
| semantic color API | `colors` | point color | no | 1 |
| semantic shape API | `shapes` | point shape | no | 1 |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.scatter()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `x()` | `fields: Sequence[Field]` | CU |
| `y()` | `fields: Sequence[Field]` | CU |
| `points()` | `fields: Sequence[Field]` | CU |
| `size()` | `fields: Sequence[Field]` | CU |
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
| `tooltip()` | `*, mode: Literal['show', 'hide']` | CU |
| `axis_visibility()` | `slot_name: Literal['x', 'y'], *, mode: Literal['show', 'hide']` | CU |
| `axis_title()` | `slot_name: Literal['x', 'y'], *, mode: Literal['off', 'manual', 'auto'], text: str = ''` | CU |
| `axis_scale()` | `slot_name: Literal['x', 'y'], *, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str \| None = None, max: str \| None = None` | CU |
| `grid()` | `slot_name: Literal['x', 'y'], *, enabled: bool, step: int \| None = None` | CU |
| `hide_labels()` | `slot_name: Literal['x', 'y'], *, enabled: bool` | CU |
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_dimension()` | `field: Field` | CU |
| `color_by_measure()` | `field: Field, *, mode: Literal['2-point', '3-point'] \| None = None, palette: GradientPaletteId \| None = None, reversed: bool \| None = None` | CU |
| `shape_by_dimension()` | `field: Field, *, shapes_map: Mapping[str, ShapeStyle] \| None = None` | CU |
| `point_size_range()` | `*, min_radius: float = 4.5, max_radius: float = 9.0` | CU |
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

x_value = dataset.fields.by_name("Revenue")
y_value = dataset.fields.by_name("Orders")
category = dataset.fields.by_name("Country")
size_value = dataset.fields.by_name("Users")

chart = (
    client.create.wizard_chart.scatter(
        name="Scatter",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([x_value])
    .y([y_value])
    .points([category])
    .size([size_value])
    .color_by_dimension(category)
    .shape_by_dimension(category, shapes_map={"US": "Solid", "DE": "Dash"})
    .point_size_range(min_radius=4.0, max_radius=14.0)
    .axis_title("x", mode="manual", text="Revenue")
    .axis_title("y", mode="manual", text="Orders")
    .grid("y", enabled=True)
    .measure_format(x_value, format="number", unit="m", precision=1)
    .legend(mode="show")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
chart = (
    chart.update.point_size_range(min_radius=4.5, max_radius=12.0)
    .shape_by_dimension(category)
    .mode("publish")
    .execute()
)
```

## Constraints and gotchas

- `x` and `y` are required measures with capacity 1; `points`, `size`, colors, and shapes each have capacity 1.
- Dimension and measure color are supported; shape is dimension-only.
- Scatter supports axis helpers but not `navigator()` or `segments()`.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
