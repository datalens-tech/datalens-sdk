# Wizard Chart Operation Recipes

Use these recipes with the installed public `datalens_sdk`. They complement the
signature catalog in [common operations](common-operations.md) and the
chart-specific applicability tables.

Examples assume `client` is configured. Replace IDs, field titles, formulas,
and locations with values from the user's DataLens installation.

## Contents

- [Resolve fields safely on update](#resolve-fields-safely-on-update)
- [Filter and sort](#filter-and-sort)
- [Create and mutate chart-local fields](#create-and-mutate-chart-local-fields)
- [Configure encodings, axes, and formatting](#configure-encodings-axes-and-formatting)
- [Configure table items](#configure-table-items)
- [Apply structural updates](#apply-structural-updates)
- [Build combined charts and geolayers](#build-combined-charts-and-geolayers)

## Resolve Fields Safely on Update

Re-fetch a chart before updating it. Use `chart.fields` for fields already
referenced by the chart. Fetch its dataset and use a `DatasetField` when adding
a field that is not yet referenced.

```python
chart = client.get.wizard_chart(by_id="chart-id")

placed_revenue = chart.fields.by_name("Revenue")
dataset = client.get.dataset(by_id=chart.dataset_ids[0])
new_profit = dataset.fields.by_name("Profit")

chart = chart.update.y([placed_revenue, new_profit]).mode("save").execute()
```

Placeholder setters replace the complete field list. Include fields that must
remain, and pass `[]` only when intentionally clearing an optional placeholder.
The public typed API lists active fields through `chart.fields` but does not
report which placeholder each field occupies. This example assumes Revenue is
the complete current `y` list; if the current layout is unknown, ask the user
instead of guessing.

`measures()` is update-only. Typed create builders for indicator, pie, donut,
funnel, treemap, and pivot table use `y()` instead.

```python
indicator = client.get.wizard_chart(by_id="indicator-id")
dataset = client.get.dataset(by_id=indicator.dataset_ids[0])
replacement = dataset.fields.by_name("Net Revenue")

indicator = indicator.update.measures([replacement]).mode("publish").execute()
```

## Filter and Sort

Use `add_sort()` when direction matters. Values passed to `add_filter()` are
strings, including numeric comparisons.

```python
import datalens_sdk as dl

dataset = client.get.dataset(by_id="dataset-id")
date = dataset.fields.by_name("Order Date")
region = dataset.fields.by_name("Region")
revenue = dataset.fields.by_name("Revenue")

chart = (
    client.create.wizard_chart.line(
        name="Filtered revenue",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([revenue])
    .add_filter(region, operation="IN", values=["East", "West"])
    .add_relative_date_filter(date, start_offset="-30d", end_offset="+0d")
    .add_sort(date, direction="asc")
    .build()
)
```

Use `add_date_filter()` for an absolute interval. Delete an existing filter by
the field it references before adding its replacement.

```python
chart = client.get.wizard_chart(by_id=chart.id)
date = chart.fields.by_name("Order Date")

chart = (
    chart.update.delete_filter(date)
    .add_date_filter(
        date,
        start="2026-01-01",
        end="2026-01-31",
        inclusive_end=True,
    )
    .mode("publish")
    .execute()
)
```

Create-side `sort()` replaces the entire sort-field list and does not accept
directions. It is unavailable on update.

```python
builder = (
    client.create.wizard_chart.column(
        name="Revenue by date",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([revenue])
    .sort([date])
)
chart = builder.build()
```

## Create and Mutate Chart-Local Fields

A newly added local field, aggregated measure, or hierarchy has no
`DatasetField` yet. Reference it later in the same fluent chain by its title.

```python
import datalens_sdk as dl

dataset = client.get.dataset(by_id="dataset-id")
country = dataset.fields.by_name("Country")
city = dataset.fields.by_name("City")
customer = dataset.fields.by_name("Customer")

revenue_per_order = "Revenue per order"
unique_customers = "Unique customers"
geo_hierarchy = "Country → City"

chart = (
    client.create.wizard_chart.flat_table(
        name="Customer geography",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .add_local_field(
        title=revenue_per_order,
        formula="SUM([Revenue]) / SUM([Orders])",
        cast="float",
        measure=True,
    )
    .add_aggregated_measure(
        customer,
        aggregation="countunique",
        name=unique_customers,
    )
    .add_hierarchy(geo_hierarchy, [country, city])
    .columns([geo_hierarchy, revenue_per_order, unique_customers])
    .build()
)
```

After re-fetching, placed chart-local fields are available through
`chart.fields`. `replace_formula()` preserves the field identity.
`change_aggregation()` creates a replacement local measure and rewrites active
references to it.

```python
chart = client.get.wizard_chart(by_id=chart.id)
ratio = chart.fields.by_name("Revenue per order")
customers = chart.fields.by_name("Unique customers")

chart = (
    chart.update.replace_formula(
        ratio,
        formula="SUM([Net Revenue]) / SUM([Orders])",
    )
    .change_aggregation(
        customers,
        aggregation="count",
        name="Customer rows",
    )
    .mode("publish")
    .execute()
)
```

## Configure Encodings, Axes, and Formatting

Use measure-name encodings when one placeholder contains several measures. Map
measure fields to explicit colors or line shapes.

```python
import datalens_sdk as dl

dataset = client.get.dataset(by_id="dataset-id")
date = dataset.fields.by_name("Order Date")
revenue = dataset.fields.by_name("Revenue")
profit = dataset.fields.by_name("Profit")

chart = (
    client.create.wizard_chart.line(
        name="Revenue and profit",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .y([revenue, profit])
    .color_by_measure_name(
        colors_map={revenue: "#4DA2F1", profit: "#FF3D64"},
    )
    .shape_by_measure_name(
        shapes_map={revenue: "Solid", profit: "Dash"},
    )
    .axis_visibility("y", mode="show")
    .axis_scale("y", scale="linear", mode="manual", min="0")
    .grid("y", enabled=True, step=10_000)
    .hide_labels("x", enabled=False)
    .navigator(mode="show")
    .legend(mode="show")
    .tooltip_sum(enabled=False)
    .tooltips([profit])
    .labels_position(mode="auto")
    .measure_format(
        revenue,
        format="currency",
        precision=0,
        unit="m",
        prefix="$",
        show_rank_delimiter=True,
    )
    .build()
)
```

Use `palette()` after binding color to a dimension when a categorical palette
is desired.

```python
region = dataset.fields.by_name("Region")

chart = (
    client.create.wizard_chart.column(
        name="Revenue by region",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([region])
    .y([revenue])
    .color_by_dimension(region)
    .palette(id="datalens-classic-20")
    .build()
)
```

## Configure Table Items

Place a field in `columns()` or pivot `y()` before applying item-level table
settings to it. Each `column_bars()` call configures one placed field.

```python
import datalens_sdk as dl

dataset = client.get.dataset(by_id="dataset-id")
country = dataset.fields.by_name("Country")
revenue = dataset.fields.by_name("Revenue")
profit = dataset.fields.by_name("Profit")
margin = dataset.fields.by_name("Margin")
growth = dataset.fields.by_name("Growth")

chart = (
    client.create.wizard_chart.flat_table(
        name="Country performance",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .columns([country, revenue, profit, margin, growth])
    .column_title(revenue, title="Revenue, USD")
    .column_background(
        growth,
        mode="3-point",
        palette="red-orange-green",
        thresholds=(-0.1, 0.0, 0.2),
    )
    .column_bars(
        revenue,
        color_type="one-color",
        color="#4DA2F1",
    )
    .column_bars(
        profit,
        color_type="two-color",
        color_positive="#3DA67A",
        color_negative="#FF3D64",
    )
    .column_bars(
        margin,
        color_type="gradient",
        gradient_palette="red-orange-green",
        gradient_type="3-point",
        reversed=False,
    )
    .freeze_columns(count=1)
    .pagination(enabled=True, limit=50)
    .table_size(size="m")
    .build()
)
```

Do not mix arguments from different `color_type` modes:

- `"one-color"` uses `color`, `palette`, or `color_index`;
- `"two-color"` uses positive and negative color arguments;
- `"gradient"` requires `gradient_palette`, with a compatible
  `gradient_type`.

## Apply Structural Updates

Structural operations use the loaded chart as their source of truth.
`replace_field()` and `delete_field()` update every active reference to the
target field, not only one placeholder.

```python
chart = client.get.wizard_chart(by_id="chart-id")
dataset = client.get.dataset(by_id=chart.dataset_ids[0])

old_date = chart.fields.by_name("Order Date")
new_date = dataset.fields.by_name("Order Month")
obsolete_profit = chart.fields.by_name("Outdated Profit")

chart = chart.update.replace_field(old_date, new_date).delete_field(obsolete_profit).mode("save").execute()
```

Visualization changes are limited to `line ↔ column` and `line ↔ bar`.
The SDK maps retained placeholders, including the axis swap between line and
bar. Re-fetch and inspect the result before publishing.

```python
chart = client.get.wizard_chart(by_id="line-chart-id")
chart = chart.update.change_visualization_to(visualization_id="bar").mode("save").execute()
chart = client.get.wizard_chart(by_id=chart.id)
```

`replace_dataset()` rewrites dataset IDs in existing chart references. It does
not translate field GUIDs. Verify that the target dataset contains every
source-dataset field GUID used by the chart. Intersect with the source dataset
schema so chart-local field GUIDs are not mistaken for dataset fields.

```python
chart = client.get.wizard_chart(by_id="chart-id")
old_dataset_id = chart.dataset_ids[0]
new_dataset_id = "compatible-dataset-id"

target_dataset = client.get.dataset(by_id=new_dataset_id)
source_dataset = client.get.dataset(by_id=old_dataset_id)
target_guids = {field.guid for field in target_dataset.fields}
source_guids = {field.guid for field in source_dataset.fields}
required_guids = {field.guid for field in chart.fields if field.guid in source_guids}
missing_guids = required_guids - target_guids
if missing_guids:
    raise ValueError(
        f"Target dataset lacks chart field GUIDs: {sorted(missing_guids)}",
    )

chart = chart.update.replace_dataset(old=old_dataset_id, new=new_dataset_id).mode("publish").execute()
```

## Build Combined Charts and Geolayers

Combined layers are defined only during creation. An update can change the
shared `x` field and chart-wide settings, but it cannot add, remove, or
reconfigure layers.

```python
import datalens_sdk as dl

dataset = client.get.dataset(by_id="dataset-id")
date = dataset.fields.by_name("Order Date")
revenue = dataset.fields.by_name("Revenue")
conversion = dataset.fields.by_name("Conversion")

chart = (
    client.create.wizard_chart.combined_chart(
        name="Revenue and conversion",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .x([date])
    .add_layer("column", y=revenue, name="Revenue")
    .add_layer("line", y2=conversion, name="Conversion")
    .build()
)
```

Geolayer datasets, layers, map type, and map center are also create-only. Layer
geometry arguments depend on the layer type.

```python
point = dataset.fields.by_name("Coordinates")
polygon = dataset.fields.by_name("Boundary")
route = dataset.fields.by_name("Route")
weight = dataset.fields.by_name("Revenue")

chart = (
    client.create.wizard_chart.geolayer(
        name="Geographic layers",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(dataset)
    .add_layer("geopoint", geopoint=point, size=weight)
    .add_layer("heatmap", geopoint=point, color=weight)
    .add_layer("geopolygon", polygon=polygon, color=weight)
    .add_layer("polyline", polyline=route, color=weight)
    .map_type(mode="light")
    .map_center(lat=55.75, lon=37.62, zoom=8)
    .build()
)
```

Use `add_dataset()` for fields owned by another dataset. Passing the same
dataset to `add_layer(dataset=...)` binds that layer's field resolution to it.

```python
primary = client.get.dataset(by_id="primary-dataset-id")
secondary = client.get.dataset(by_id="secondary-dataset-id")
secondary_point = secondary.fields.by_name("Coordinates")

chart = (
    client.create.wizard_chart.geolayer(
        name="Multiple geo datasets",
        location=dl.EntryLocation.path("/Charts"),
    )
    .dataset(primary)
    .add_dataset(secondary)
    .add_layer(
        "geopoint",
        geopoint=secondary_point,
        dataset=secondary,
        name="Secondary points",
    )
    .build()
)
```

Do not confuse a geographic heatmap layer with a table heatmap:

- geographic density: `geolayer().add_layer("heatmap", geopoint=...)`;
- value matrix: `pivot_table()` plus `column_background(...)`.
