# Pivot table Wizard chart

Factory: `client.create.wizard_chart.pivot_table(name=..., location=...)`
`chart.visualization_id`: `pivotTable`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `columns()` | `pivot-table-columns` | column dimensions | no | unbounded |
| `rows()` | `rows` | row dimensions | no | unbounded |
| `y()` | `measures` | cell measures | no | unbounded |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.pivot_table()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `y()` | `fields: Sequence[Field]` | CU |
| `columns()` | `fields: Sequence[Field]` | CU |
| `rows()` | `fields: Sequence[Field]` | CU |
| `measures()` | `fields: Sequence[Field]` | U |
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
| `palette()` | `*, id: PaletteId` | CU |
| `color_by_measure()` | `field: Field, *, mode: Literal['2-point', '3-point'] \| None = None, palette: GradientPaletteId \| None = None, reversed: bool \| None = None` | CU |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'b', 't'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `column_background()` | `field: Field, *, mode: Literal['2-point', '3-point'] = '3-point', palette: GradientPaletteId = 'red-orange-green', thresholds: tuple[float, ...] \| None = None, reversed: bool = False` | CU |
| `column_bars()` | `field: Field, *, enabled: bool = True, color_type: Literal['one-color', 'two-color', 'gradient'] = 'one-color', color: str \| None = None, palette: DiscretePaletteId \| None = None, color_index: int \| None = None, color_positive: str \| None = None, color_negative: str \| None = None, positive_color_index: int \| None = None, negative_color_index: int \| None = None, gradient_palette: GradientPaletteId \| None = None, gradient_type: Literal['2-point', '3-point'] = '2-point', reversed: bool = False, show_labels: bool = True, show_in_totals: bool = False, align: Literal['default', 'left', 'right'] = 'default'` | CU |
| `column_title()` | `field: Field, *, title: str` | CU |
| `freeze_columns()` | `*, count: int = 1` | CU |
| `pagination()` | `*, enabled: bool, limit: int = 100` | CU |
| `table_size()` | `*, size: Literal['s', 'm', 'l']` | CU |
| `subtotals()` | `field: Field, *, enabled: bool` | CU |
| `replace_formula()` | `field: Field, *, formula: str` | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U |
| `replace_field()` | `old: Field, new: Field` | U |
| `delete_field()` | `field: Field` | U |
| `delete_filter()` | `field: Field` | U |
| `replace_dataset()` | `*, old: str, new: str` | U |
| `build()` | none | C |
| `mode()` | `value: EntryUpdateMode` | U |
| `execute()` | none | U |

## Pivot heatmap create

Assume `client` is a configured SDK client and `dataset` is fetched.

```python
from datalens_sdk import EntryLocation

row = dataset.fields.by_name("Country")
column = dataset.fields.by_name("Segment")
value = dataset.fields.by_name("Revenue")

chart = (
    client.create.wizard_chart.pivot_table(
        name="Revenue heatmap",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .rows([row])
    .columns([column])
    .y([value])
    .column_background(
        value,
        mode="3-point",
        palette="red-orange-green",
        thresholds=(0.0, 500_000.0, 1_000_000.0),
    )
    .subtotals(row, enabled=True)
    .freeze_columns(count=1)
    .pagination(enabled=True, limit=100)
    .table_size(size="s")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
placed_value = chart.fields.by_name("Revenue")
chart = (
    chart.update.column_background(
        placed_value,
        mode="3-point",
        palette="red-orange-green",
        thresholds=(0.0, 750_000.0, 1_500_000.0),
        reversed=True,
    )
    .mode("publish")
    .execute()
)
```

## Constraints and gotchas

- `columns` and `y` address the column and measure field groups; their capacities are unbounded.
- Heatmap is a pivot-table recipe: place row/column dimensions and a measure, then apply `column_background()`; there is no `heatmap()` factory.
- This is a table heatmap. Geographic density uses a geolayer
  `add_layer("heatmap", geopoint=...)`.
- `totals()` is not supported. Use `subtotals()` on a row/column dimension.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
