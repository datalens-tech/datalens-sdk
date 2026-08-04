# Geolayer Wizard chart

Factory: `client.create.wizard_chart.geolayer(name=..., location=...)`
`chart.visualization_id`: `geolayer`

`Field` below means a `DatasetField` or an exact string reference. Prefer `DatasetField`; strings on create require a bound `.dataset(dataset)`, while updates can resolve strings only from fields already placed in the fetched chart.

## Placeholders

| Layer type | Required public argument | Geometry field group | Optional layer inputs |
| --- | --- | --- | --- |
| `geopoint` | `geopoint=` | `geopoint` | `size`, `color`, `tooltips`, `labels` |
| `heatmap` | `geopoint=` | `geopoint` | `color`, `tooltips`, `labels` |
| `geopolygon` | `polygon=` | `geopolygon` | `color`, `tooltips`, `labels` |
| `polyline` | `polyline=` | `polyline` | `color`, `tooltips`, `labels` |

Geolayers have no chart-level `x`/`y` fields. Geometry and decoration fields belong to individual layers.
The method has one shared signature for all layer types. `size` affects
geopoint layers; the common decoration inputs are accepted for every layer,
although their visible effect depends on the selected layer type.

## Fluent operations

`C` = create, `U` = update, `CU` = both.

| Operation | Arguments | Surface |
| --- | --- | --- |
| `client.create.wizard_chart.geolayer()` | `name: str`, `location: EntryLocation` | C |
| `dataset()` | `dataset: Dataset` | C |
| `add_dataset()` | `dataset: Dataset` | C |
| `add_layer()` | `layer_type: GeoLayerType, *, geopoint: Field \| None = None, polygon: Field \| None = None, polyline: Field \| None = None, size: Field \| None = None, color: Field \| None = None, tooltips: Sequence[Field] = (), labels: Sequence[Field] = (), alpha: int = 80, name: str \| None = None, dataset: Dataset \| None = None` | C |
| `map_type()` | `*, mode: MapType` | C |
| `map_center()` | `*, lat: float, lon: float, zoom: int \| None = None` | C |
| `add_aggregated_measure()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str \| None = None, guid: str \| None = None` | CU |
| `add_local_field()` | `*, title: str, formula: str, guid: str \| None = None, cast: str = 'float', measure: bool = False, aggregation: str \| None = None, formatting: MeasureFormat \| None = None` | CU |
| `chart_title()` | `*, text: str = '', mode: Literal['show', 'hide'] = 'show'` | CU |
| `description()` | `text: str` | CU |
| `legend()` | `*, mode: Literal['show', 'hide']` | CU |
| `tooltip_sum()` | `*, enabled: bool` | CU |
| `tooltips()` | `fields: Sequence[Field]` | CU |
| `labels()` | `fields: Sequence[Field]` | CU |
| `labels_position()` | `*, mode: Literal['inside', 'outside', 'auto']` | CU |
| `measure_format()` | `field: Field, *, format: Literal['number', 'percent', 'currency'] \| None = None, precision: int \| None = None, unit: Literal['auto', 'k', 'm', 'bln'] \| None = None, prefix: str \| None = None, postfix: str \| None = None, show_rank_delimiter: bool \| None = None` | CU |
| `replace_formula()` | `field: Field, *, formula: str` | U |
| `change_aggregation()` | `field: DatasetField, *, aggregation: Literal['sum', 'avg', 'min', 'max', 'count', 'countunique'], name: str, guid: str \| None = None` | U |
| `replace_field()` | `old: Field, new: Field` | U |
| `delete_field()` | `field: Field` | U |
| `delete_filter()` | `field: Field` | U |
| `replace_dataset()` | `*, old: str, new: str` | U |
| `build()` | none | C |
| `mode()` | `value: EntryUpdateMode` | U |
| `execute()` | none | U |

## Multi-dataset create

Assume `client` is configured and `dataset` plus `density_dataset` are fetched.

```python
from datalens_sdk import EntryLocation

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
        tooltips=[category, value],
        labels=[category],
        name="Locations",
    )
    .add_layer(
        "heatmap",
        geopoint=density_point,
        color=density_weight,
        tooltips=[density_weight],
        name="Density",
        dataset=density_dataset,
    )
    .map_type(mode="light")
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

- The root chart has no placeholders. Each layer owns its own required geometry placeholder.
- Layer types and required arguments: `geopoint`/`heatmap` -> `geopoint=`, `geopolygon` -> `polygon=`, `polyline` -> `polyline=`.
- `add_dataset()`, `add_layer()`, `map_type()`, and `map_center()` are create-only; layer topology and map settings have no update fluent API.
- There is no targeted layer update. `replace_field(old, new)` is global and
  is safe only when `old` is unique to the intended layer.
- `heatmap` here means geographic density. A matrix heatmap is a
  `pivot_table()` with `column_background()`.
- The SDK can re-fetch saved metadata but cannot render the map to verify its
  visual result.
- Root filter/sort helpers are intentionally absent; use the layer inputs exposed by `add_layer()`.
- No visualization transition is supported from this visualization.

## Related references

- [Common chart operations](common-operations.md)
- [Chart-type routing and full operation matrix](_index.md)
