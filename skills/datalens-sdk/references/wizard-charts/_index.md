# Wizard charts: routing and full operation matrix

Read this file first for any wizard-chart task. Pick the chart type from the
routing table, then read exactly the one `chart-*.md` file it points to, plus
[common operations](common-operations.md) for lifecycle and shared methods.

## Chart-type routing

All 17 factories live on `client.create.wizard_chart.<factory>()`. Route by
what the user asks for, not by DataLens UI names. Before selecting one, confirm
its name is present in
`client.capabilities["chart_factories"]["wizard"]`; that generated list is
authoritative for the configured client.

| User wants | Read | Factory |
| --- | --- | --- |
| line chart, time series, trend | [chart-line.md](chart-line.md) | `line` |
| area chart | [chart-area.md](chart-area.md) | `area` |
| normalized / 100% stacked area | [chart-area-100p.md](chart-area-100p.md) | `area_100p` |
| column chart, vertical bars | [chart-column.md](chart-column.md) | `column` |
| normalized / 100% stacked column | [chart-column-100p.md](chart-column-100p.md) | `column_100p` |
| horizontal bar chart, ranking | [chart-bar.md](chart-bar.md) | `bar` |
| normalized / 100% stacked horizontal bar | [chart-bar-100p.md](chart-bar-100p.md) | `bar_100p` |
| two visualizations on one x-axis, dual-axis mix (e.g. columns + line) | [chart-combined-chart.md](chart-combined-chart.md) | `combined_chart` |
| pie chart | [chart-pie.md](chart-pie.md) | `pie` |
| donut / ring chart | [chart-donut.md](chart-donut.md) | `donut` |
| plain table, list of rows | [chart-flat-table.md](chart-flat-table.md) | `flat_table` |
| pivot / cross table, matrix | [chart-pivot-table.md](chart-pivot-table.md) | `pivot_table` |
| KPI, single number, metric tile, indicator | [chart-indicator.md](chart-indicator.md) | `indicator` |
| scatter, bubble chart, correlation | [chart-scatter.md](chart-scatter.md) | `scatter` |
| treemap, share-of-total tiles | [chart-treemap.md](chart-treemap.md) | `treemap` |
| funnel, conversion steps | [chart-funnel.md](chart-funnel.md) | `funnel` |
| map: points, polygons, routes, geo density | [chart-geolayer.md](chart-geolayer.md) | `geolayer` |

Naming traps:

- The KPI factory is `indicator()`, but a fetched indicator reports
  `chart.visualization_id == "metric"`. Never call
  `client.create.wizard_chart.metric()` — it does not exist.
- 100% factories use underscores (`area_100p`), while the persisted
  visualization ids do not (`area100p`, `bar100p`, `column100p`).

### Requests that are not a factory

| User wants | It is not a factory — do this instead |
| --- | --- |
| heatmap (value matrix, e.g. weekday × hour) | `pivot_table()` with `column_background()` on the measure — [chart-pivot-table.md](chart-pivot-table.md) |
| heatmap (geographic density on a map) | `geolayer()` with `add_layer("heatmap", geopoint=...)` — [chart-geolayer.md](chart-geolayer.md); do not confuse the two heatmaps |
| stacked column/bar/area (regular, not 100%) | the base chart plus `color_by_dimension()` as the stack split — e.g. [chart-column.md](chart-column.md) |
| dual y-axis line chart | `line` with `y2()` — [chart-line.md](chart-line.md); mix chart kinds only via `combined_chart` |
| gauge, radar, sankey, waterfall, boxplot | no wizard visualization exists; check [../editor-charts/_index.md](../editor-charts/_index.md) before promising anything |

## Full fluent-operation matrix

`C` = create builder, `U` = `WizardChartUpdate`, `CU` = both, `—` =
unsupported. `Field` means `DatasetField | str`. `StructuralTarget` means
`DatasetField | exact GUID str`; titles do not resolve for those arguments.
Every cell describes only the installed package's typed public API.

| Operation | Arguments | area | area_100p | bar | bar_100p | column | column_100p | combined_chart | donut | flat_table | funnel | geolayer | line | indicator | pie | pivot_table | scatter | treemap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `<factory>()` | `*, name: str, location: EntryLocation` | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C |
| `dataset()` | `dataset: Dataset` | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C |
| `add_dataset()` | `dataset: Dataset` | — | — | — | — | — | — | — | — | — | — | C | — | — | — | — | — | — |
| `x()` | `fields: Sequence[Field]` | CU | CU | CU | CU | CU | CU | CU | CU | — | CU | — | CU | — | CU | — | CU | CU |
| `y()` | `fields: Sequence[Field]` | CU | CU | CU | CU | CU | CU | — | CU | — | CU | — | CU | CU | CU | CU | CU | CU |
| `y2()` | `fields: Sequence[Field]` | — | — | — | — | — | — | — | — | — | — | — | CU | — | — | — | — | — |
| `columns()` | `fields: Sequence[Field]` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `rows()` | `fields: Sequence[Field]` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | CU | — | — |
| `measures()` | `fields: Sequence[Field]` | — | — | — | — | — | — | — | U | — | U | — | — | U | U | U | — | U |
| `points()` | `fields: Sequence[Field]` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | CU | — |
| `size()` | `fields: Sequence[Field]` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | CU | — |
| `add_layer()` | `combined_chart`: `layer_type: CombinedLayerType, *, y: Field \| None = None, y2: Field \| None = None, name: str \| None = None`<br>`geolayer`: `layer_type: GeoLayerType, *, geopoint: Field \| None = None, polygon: Field \| None = None, polyline: Field \| None = None, size: Field \| None = None, color: Field \| None = None, tooltips: Sequence[Field] = (), labels: Sequence[Field] = (), alpha: int = 80, name: str \| None = None, dataset: Dataset \| None = None` | — | — | — | — | — | — | C | — | — | — | C | — | — | — | — | — | — |
| `map_type()` | `*, mode: MapType` | — | — | — | — | — | — | — | — | — | — | C | — | — | — | — | — | — |
| `map_center()` | `*, lat: float, lon: float, zoom: int \| None = None` | — | — | — | — | — | — | — | — | — | — | C | — | — | — | — | — | — |
| `add_aggregated_measure()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str \| None = None, guid: str \| None = None` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `add_local_field()` | `*, title: str, formula: str, guid: str \| None = None, cast: str = 'float', measure: bool = False, aggregation: str \| None = None, formatting: MeasureFormat \| None = None` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `add_hierarchy()` | `title: str, fields: Sequence[Field], *, guid: str \| None = None` | CU | CU | CU | CU | CU | CU | — | — | CU | — | — | CU | — | — | CU | CU | — |
| `add_filter()` | `field: Field, *, operation: FilterOperation, values: Sequence[str] = ()` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | — | CU | CU | CU | CU | CU | CU |
| `add_date_filter()` | `field: Field, *, start: str, end: str, inclusive_end: bool = True` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | — | CU | CU | CU | CU | CU | CU |
| `add_relative_date_filter()` | `field: Field, *, start_offset: str, end_offset: str` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | — | CU | CU | CU | CU | CU | CU |
| `add_sort()` | `field: Field, *, direction: Literal['asc', 'desc'] = 'asc'` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | — | CU | — | CU | CU | CU | — |
| `sort()` | `fields: Sequence[Field]` | C | C | C | C | C | C | C | C | C | C | — | C | — | C | C | C | — |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `description()` | `text: str` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `tooltips()` | `fields: Sequence[Field]` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `labels()` | `fields: Sequence[Field]` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | — | CU | CU | CU | CU |
| `labels_position()` | `*, mode: Literal['inside', 'outside', 'auto']` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `label_mode()` | `*, mode: Literal['absolute', 'percent']` | — | CU | — | CU | — | CU | — | CU | — | CU | — | — | — | CU | — | — | — |
| `tooltip_percentage_base()` | `*, mode: Literal['auto', 'first', 'previous']` | — | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | — | — |
| `shape()` | `*, value: FunnelShape` | — | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | — | — |
| `navigator()` | `*, mode: Literal['show', 'hide']` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | — | — |
| `axis_visibility()` | `ph_id: Literal['x', 'y']` (`'y2'` also on line), `*, mode: Literal['show', 'hide']` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | CU | — |
| `axis_title()` | `ph_id: Literal['x', 'y']` (`'y2'` also on line), `*, mode: Literal['off', 'manual', 'auto'], text: str = ''` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | CU | — |
| `axis_scale()` | `ph_id: Literal['x', 'y']` (`'y2'` also on line), `*, scale: Literal['linear', 'logarithmic'] = 'linear', mode: Literal['auto', 'manual'] = 'auto', min: str \| None = None, max: str \| None = None` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | CU | — |
| `grid()` | `ph_id: Literal['x', 'y']` (`'y2'` also on line), `*, enabled: bool, step: int \| None = None` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | CU | — |
| `hide_labels()` | `ph_id: Literal['x', 'y']` (`'y2'` also on line), `*, enabled: bool` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | CU | — |
| `nulls_mode()` | `ph_id: Literal['x', 'y']` (`'y2'` also on line), `*, mode: Literal['ignore', 'connect', 'as-0']` | CU | CU | CU | CU | CU | CU | — | — | — | — | — | CU | — | — | — | CU | — |
| `segments()` | `fields: Sequence[Field]` | CU | CU | — | — | CU | CU | — | — | — | — | — | CU | — | — | — | — | — |
| `palette()` | `*, id: PaletteId` | CU | CU | CU | CU | CU | CU | — | CU | CU | CU | — | CU | — | CU | CU | CU | CU |
| `color_by_dimension()` | `field: Field` | CU | CU | CU | CU | CU | CU | — | CU | — | CU | — | CU | — | CU | — | CU | CU |
| `color_by_measure()` | `field: Field, *, mode: Literal['2-point', '3-point'] \| None = None, palette: GradientPaletteId \| None = None, reversed: bool \| None = None` | — | — | CU | — | CU | — | — | — | CU | — | — | — | — | — | CU | CU | CU |
| `color_by_measure_name()` | `*, colors_map: Mapping[Field, str] \| None = None` | — | — | CU | — | CU | — | — | — | — | — | — | CU | — | — | — | — | — |
| `shape_by_dimension()` | `field: Field, *, shapes_map: Mapping[str, ShapeStyle] \| None = None` | — | — | — | — | — | — | — | — | — | — | — | CU | — | — | — | CU | — |
| `shape_by_measure_name()` | `*, shapes_map: Mapping[Field, ShapeStyle] \| None = None` | — | — | — | — | — | — | — | — | — | — | — | CU | — | — | — | — | — |
| `point_size_range()` | `*, min_radius: float = 4.5, max_radius: float = 9.0` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | CU | — |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent', 'currency'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'bln'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU | CU |
| `font_size()` | `*, size: Literal['xs', 's', 'm', 'l']` | — | — | — | — | — | — | — | — | — | — | — | — | CU | — | — | — | — |
| `font_color()` | `*, color: str` | — | — | — | — | — | — | — | — | — | — | — | — | CU | — | — | — | — |
| `measure_title_mode()` | `*, mode: Literal['by-field', 'manual', 'hide']` | — | — | — | — | — | — | — | — | — | — | — | — | CU | — | — | — | — |
| `column_background()` | `field: Field, *, mode: Literal['2-point', '3-point'] = '3-point', palette: GradientPaletteId = 'red-orange-green', thresholds: tuple[float, ...] \| None = None, reversed: bool = False` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `column_bars()` | `field: Field, *, enabled: bool = True, color_type: Literal['one-color', 'two-color', 'gradient'] = 'one-color', color: str \| None = None, palette: DiscretePaletteId \| None = None, color_index: int \| None = None, color_positive: str \| None = None, color_negative: str \| None = None, positive_color_index: int \| None = None, negative_color_index: int \| None = None, gradient_palette: GradientPaletteId \| None = None, gradient_type: Literal['2-point', '3-point'] = '2-point', reversed: bool = False, show_labels: bool = True, show_in_totals: bool = False, align: Literal['default', 'left', 'right'] = 'default'` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `column_title()` | `field: Field, *, title: str` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `freeze_columns()` | `*, count: int = 1` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `pagination()` | `*, enabled: bool, limit: int = 100` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `table_size()` | `*, size: Literal['s', 'm', 'l']` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | CU | — | — |
| `totals()` | `*, enabled: bool` | — | — | — | — | — | — | — | — | CU | — | — | — | — | — | — | — | — |
| `subtotals()` | `field: Field, *, enabled: bool` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | CU | — | — |
| `replace_formula()` | `field: StructuralTarget, *, formula: str` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `replace_field()` | `old: StructuralTarget, new: Field` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `delete_field()` | `field: StructuralTarget` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `delete_filter()` | `field: StructuralTarget` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `replace_dataset()` | `*, old: str, new: str` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `change_visualization_to()` | `*, visualization_id: str` | — | — | U | — | U | — | — | — | — | — | — | U | — | — | — | — | — |
| `build()` | none | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C | C |
| `mode()` | `value: EntryUpdateMode` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |
| `execute()` | `none` | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U | U |

## Exact visualization transitions

`change_visualization_to()` retains only the mapped field groups, drops incompatible chart state, and validates target capacities before sending the update.

| Source | Allowed target | Retained placeholder mapping |
| --- | --- | --- |
| `line` | `column` | `x -> x`, `y -> y` |
| `column` | `line` | `x -> x`, `y -> y` |
| `line` | `bar` | `x -> y`, `y -> x` |
| `bar` | `line` | `y -> x`, `x -> y` |

Every other source/target pair, unknown target, and same-visualization transition is unsupported. `combined-chart`, `geolayer`, tables, circular charts, funnel, indicator, scatter, treemap, and all 100% variants have no supported transition.

## Reading notes

- `dataset()` is create-only. On update, pass a `DatasetField` for any new or unplaced field.
- `sort(fields)` is create-only by design; update uses append-style `add_sort(field, direction=...)`.
- `add_layer()` and geolayer map/layer topology operations are create-only.
- `measures()` is an update-only field-group spelling for indicator, pie, donut, funnel, treemap, and pivot. Their create builders expose `y()`.
- Structural target strings are exact GUIDs. Prefer `DatasetField` objects from
  `chart.fields`, especially for `replace_formula()`.
- `build()` performs create. Update uses `mode('save'|'publish').execute()`; update defaults to `save`.

## Related references

- [Common chart operations](common-operations.md)
- [Operation recipes](operation-recipes.md)
- [Area](chart-area.md)
- [100% stacked area](chart-area-100p.md)
- [Horizontal bar](chart-bar.md)
- [100% stacked horizontal bar](chart-bar-100p.md)
- [Column](chart-column.md)
- [100% stacked column](chart-column-100p.md)
- [Combined chart](chart-combined-chart.md)
- [Donut](chart-donut.md)
- [Flat table](chart-flat-table.md)
- [Funnel](chart-funnel.md)
- [Geolayer](chart-geolayer.md)
- [Line](chart-line.md)
- [Indicator](chart-indicator.md)
- [Pie](chart-pie.md)
- [Pivot table](chart-pivot-table.md)
- [Scatter](chart-scatter.md)
- [Treemap](chart-treemap.md)
