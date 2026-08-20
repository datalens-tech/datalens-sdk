# Geolayer Wizard chart

Factory: `client.create.wizard_chart.geolayer(name=..., location=...)`
`chart.visualization_id`: `geolayer`

`Field` below means `DatasetField`, `WizardLocalField`, `WizardAggregatedMeasure`, `WizardHierarchy`, or an exact string reference. Prefer identity objects: save Dataset fields from the dataset schema and reuse GUID-bearing Wizard handles. After fetching a chart, resolve direct snapshots by exact GUID with `chart.fields.by_guid(...)`, never by title.

## Layer slots

| Layer type | Required public argument | Geometry field group | Supported optional field inputs |
| --- | --- | --- | --- |
| `geopoint` | `geopoint=` | `geopoint` | `size`, `color`, `filters`, `tooltips`, `labels` |
| `geopoint-with-cluster` | `geopoint=` | `geopoint` | `size`, `color`, `filters`, `tooltips`, `labels` |
| `heatmap` | `geopoint=` | `heatmap` | `color`, `filters` |
| `geopolygon` | `polygon=` | `geopolygon` | `color`, `filters`, `tooltips` |
| `polyline` | `polyline=` | `polyline` | `grouping`, `color`, `filters`, `sort_by` |

Geolayers have no chart-level `x`/`y` fields. Geometry and decoration fields belong to individual layers.
The method has one shared signature for all layer types. Use only the optional
field inputs supported by the selected layer type. `color_mode`,
`color_palette`, and `color_reversed` configure a gradient for a supplied
`MEASURE` `color` field. Omit all three for categorical `DIMENSION` color.
`sort_direction` controls `sort_by` and defaults to ascending.
`alpha`, `name`, and `dataset` apply to every layer type.
Non-empty field inputs outside the selected layer's row are rejected.

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.geolayer()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `add_dataset()` | `dataset: Dataset` | C |
| `add_layer()` | `layer_type: GeoLayerType, *, geopoint: Field \| None = None, polygon: Field \| None = None, polyline: Field \| None = None, grouping: Field \| None = None, size: Field \| None = None, color: Field \| None = None, color_mode: Literal['2-point', '3-point'] \| None = None, color_palette: GradientPaletteId \| None = None, color_reversed: bool \| None = None, filters: Sequence[GeoLayerFilter] = (), tooltips: Sequence[Field] = (), labels: Sequence[Field] = (), sort_by: Field \| None = None, sort_direction: Literal['asc', 'desc'] = 'asc', alpha: int = 80, name: str \| None = None, dataset: Dataset \| None = None` | C |
| `map_center()` | `*, lat: float, lon: float, zoom: int \| None = None` | C |
| `add_aggregated_measure()` | `field: WizardAggregatedMeasure` | CU |
| `add_local_field()` | `field: WizardLocalField` | CU |
| `add_filter()` | `field: Field, *, operation: FilterOperation, values: Sequence[str] = ()` | CU |
| `add_date_filter()` | `field: Field, *, start: str, end: str, inclusive_end: bool = True` | CU |
| `add_relative_date_filter()` | `field: Field, *, start_offset: str, end_offset: str` | CU |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU |
| `description()` | `text: str` | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU |
| `labels()` | `fields: Sequence[Field]` | CU |
| `labels_position()` | `*, mode: Literal['inside', 'outside', 'auto']` | CU |
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

## Confirmed single-dataset create

The same `geolayer()` factory builds point, cluster, and density layers. Bind
the geometry through `geopoint=` for all three public calls. The example uses
both chart-level filters and a filter scoped only to the heatmap layer.

```python
from datalens_sdk import EntryLocation, GeoLayerFilter

point = dataset.fields.by_name("Coordinates")
trips = dataset.fields.by_name("Trips")
tariff = dataset.fields.by_name("Tariff Class")
geo_zone = dataset.fields.by_name("Geo Zone")
order_date = dataset.fields.by_name("Order Date")

chart = (
    client.create.wizard_chart.geolayer(
        name="Points, clusters, and density",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .add_filter(tariff, operation="IN", values=["Comfort+"])
    .add_filter(geo_zone, operation="IN", values=["luanda"])
    .add_relative_date_filter(order_date, start_offset="-1d", end_offset="-0d")
    .add_layer(
        "geopoint",
        geopoint=point,
        size=trips,
        color=trips,
        color_mode="3-point",
        color_palette="orange-gray-blue",
        color_reversed=False,
        tooltips=[trips],
        labels=[trips],
        name="Points",
    )
    .add_layer(
        "heatmap",
        geopoint=point,
        color=trips,
        color_mode="3-point",
        color_palette="red-orange-green",
        color_reversed=False,
        filters=[
            GeoLayerFilter(
                field=tariff,
                operation="IN",
                values=["Comfort+"],
            ),
        ],
        name="Density",
    )
    .add_layer("geopoint-with-cluster", geopoint=point, name="Clusters")
    .map_center(lat=55.75, lon=37.62, zoom=10)
    .build()
)
```

## Confirmed polyline create

Polyline geometry is a sequence of geopoints. `grouping` separates independent
routes, while `sort_by` orders their points; use a numeric or temporal field
whose order is stable within each group.

```python
geometry = dataset.fields.by_name("geopoint")
route = dataset.fields.by_name("route")
speed = dataset.fields.by_name("speed_kmh")
point_number = dataset.fields.by_name("point_num")
precision = dataset.fields.by_name("precision")

chart = (
    client.create.wizard_chart.geolayer(
        name="Routes",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .add_filter(route, operation="IN", values=["Москва"])
    .add_filter(precision, operation="IN", values=["1"])
    .add_layer(
        "polyline",
        polyline=geometry,
        grouping=route,
        color=speed,
        color_mode="3-point",
        color_palette="red-orange-green",
        sort_by=point_number,
        sort_direction="asc",
        name="Routes",
    )
    .build()
)
```

## Multi-dataset create

Assume `client` is configured and `dataset` plus `density_dataset` are fetched.

```python
from datalens_sdk import EntryLocation, GeoLayerFilter

point = dataset.fields.by_name("Coordinates")
value = dataset.fields.by_name("Revenue")
category = dataset.fields.by_name("Location")
density_point = density_dataset.fields.by_name("Coordinates")
density_weight = density_dataset.fields.by_name("Weight")

chart = (
    client.create.wizard_chart.geolayer(
        name="Locations and density",
        location=EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .add_dataset(density_dataset)
    .add_layer(
        "geopoint",
        geopoint=point,
        size=value,
        color=value,
        color_mode="3-point",
        color_palette="orange-gray-blue",
        color_reversed=False,
        filters=[GeoLayerFilter(field=category, operation="ISNOTNULL")],
        tooltips=[category, value],
        labels=[category],
        name="Locations",
    )
    .add_layer(
        "heatmap",
        geopoint=density_point,
        color=density_weight,
        color_mode="2-point",
        color_palette="orange-yellow",
        name="Density",
        dataset=density_dataset,
    )
    .map_center(lat=55.75, lon=37.62, zoom=10)
    .legend(mode="show")
    .build()
)
```

## Update

Create and update responses can be minimal. Re-fetch before any state-dependent follow-up. Pass new or unplaced fields as `DatasetField` objects.

```python
chart = client.get.wizard_chart(by_id=chart.id)
chart = chart.update.chart_title(text="Revenue and density by location").mode("publish").execute()
```

## Constraints and gotchas

- The root chart has no field slots. Each layer owns its own required geometry slot.
- Layer types and required arguments: `geopoint`/`geopoint-with-cluster`/`heatmap` -> `geopoint=`, `geopolygon` -> `polygon=`, `polyline` -> `polyline=`.
- The public argument for heatmap geometry remains `geopoint=`, while the persisted layer slot key is `heatmap`.
- `filters=[GeoLayerFilter(...)]` limits only that layer. Chart-level
  `.add_filter()`, `.add_date_filter()`, and `.add_relative_date_filter()`
  populate a separate chart filter list; do not substitute one scope for the
  other.
- Layer gradient settings require `color=` resolving to a `MEASURE`.
  Sequential palettes `blue`, `orange-yellow`, and `yellow` use
  `color_mode="2-point"`; diverging palettes `orange-gray-blue`,
  `pink-gray-green`, and `red-orange-green` use `color_mode="3-point"`.
  When `color_palette` is supplied without `color_mode`, the SDK infers the
  compatible mode. A `DIMENSION` color is categorical and accepts none of the
  gradient settings.
- Labels are supported only on point and cluster layers. Their only supported
  label mode is `absolute`, which the create builder emits automatically.
- `add_dataset()`, `add_layer()`, and `map_center()` are create-only; layer topology and map settings have no update fluent API.
- There is no targeted layer update. `replace_field(old, new)` is global and
  is safe only when `old` is unique to the intended layer.
- `heatmap` here means geographic density. A matrix heatmap is a
  `pivot_table()` with `column_background()`.
- `grouping`, `sort_by`, and `sort_direction` are polyline-only. The persisted
  sort keeps the full dataset field snapshot and is mirrored into both the
  selected layer and the chart-level field section. Prefer a `DatasetField`
  obtained from `dataset.fields`; polyline rendering uses that snapshot to
  order points inside every group. A non-default `sort_direction` requires
  `sort_by`.
- The SDK can re-fetch saved metadata but cannot render the map to verify its
  visual result.
- Chart-level `add_filter()`, `add_date_filter()`, and `add_relative_date_filter()` are available. Polyline point ordering is configured inside `add_layer()`.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
