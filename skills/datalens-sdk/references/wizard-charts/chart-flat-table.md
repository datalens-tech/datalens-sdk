# Flat table Wizard chart

Factory: `client.create.wizard_chart.flat_table(name=..., location=...)`
`chart.visualization_id`: `flatTable`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Public setter | Field group | Role | Required | Capacity |
| --- | --- | --- | --- | --- |
| `columns()` | `flat-table-columns` | displayed dimensions/measures | yes | unbounded |

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.flat_table()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `columns()` | `fields: Sequence[Field]` | CU |
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
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent', 'currency'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'bln'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `column_background()` | `field: Field, *, mode: Literal['2-point', '3-point'] = '3-point', palette: GradientPaletteId = 'red-orange-green', thresholds: tuple[float, ...] \| None = None, reversed: bool = False` | CU |
| `column_bars()` | `field: Field, *, enabled: bool = True, color_type: Literal['one-color', 'two-color', 'gradient'] = 'one-color', color: str \| None = None, palette: DiscretePaletteId \| None = None, color_index: int \| None = None, color_positive: str \| None = None, color_negative: str \| None = None, positive_color_index: int \| None = None, negative_color_index: int \| None = None, gradient_palette: GradientPaletteId \| None = None, gradient_type: Literal['2-point', '3-point'] = '2-point', reversed: bool = False, show_labels: bool = True, show_in_totals: bool = False, align: Literal['default', 'left', 'right'] = 'default'` | CU |
| `column_title()` | `field: Field, *, title: str` | CU |
| `freeze_columns()` | `*, count: int = 1` | CU |
| `pagination()` | `*, enabled: bool, limit: int = 100` | CU |
| `table_size()` | `*, size: Literal['s', 'm', 'l']` | CU |
| `totals()` | `*, enabled: bool` | CU |
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

category = dataset.fields.by_name("Country")
value = dataset.fields.by_name("Revenue")
margin = dataset.fields.by_name("Margin")

chart = (
    client.create.wizard_chart.flat_table(
        name="Flat table",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .columns([category, value, margin])
    .column_title(value, title="Revenue, USD")
    .column_background(
        margin,
        mode="2-point",
        palette="blue",
        thresholds=(0.0, 1.0),
    )
    .column_bars(
        value,
        color_type="one-color",
        color="#4DA2F1",
        show_labels=True,
    )
    .measure_format(value, format="currency", precision=0)
    .totals(enabled=True)
    .freeze_columns(count=1)
    .pagination(enabled=True, limit=50)
    .table_size(size="m")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
placed_value = chart.fields.by_name("Revenue")
chart = (
    chart.update.column_bars(
        placed_value,
        color_type="two-color",
        color_positive="#0FA08D",
        color_negative="#FF3D64",
        show_labels=True,
    )
    .pagination(enabled=True, limit=100)
    .mode("publish")
    .execute()
)
```

## Constraints and gotchas

- `columns` is required and accepts any number of displayed fields.
- Call `columns()` before item-level methods such as `column_background()`, `column_bars()`, or `column_title()`.
- `measure_format()` and every item-level table operation must target a field
  already placed by `columns()`.
- `column_bars()` has mutually exclusive one-color, two-color, and gradient
  argument sets; use the complete patterns in [operation recipes](operation-recipes.md).
- `totals()` is flat-table-only. Pivot totals use `subtotals()`.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
