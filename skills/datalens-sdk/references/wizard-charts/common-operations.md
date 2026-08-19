# Wizard Chart Common Operations

Use this catalog for the installed public `datalens_sdk`. It describes the
Wizard chart lifecycle and every public fluent method exposed by its typed
create builders or `WizardChartUpdate`.

## Contents

- [Public API map and notation](#public-api-map-and-notation)
- [Lifecycle](#lifecycle)
- [Field references](#field-references)
- [Fluent operation catalog](#fluent-operation-catalog)
- [Argument domains and constraints](#argument-domains-and-constraints)
- [Minimal examples](#minimal-examples)
- [Related references](#related-references)

## Public API Map and Notation

Import common public types from the package root:

```python
from datalens_sdk import (
    Dataset,
    DatasetField,
    EntryLocation,
    EntryRelation,
    Pager,
    WizardChart,
    WizardChartUpdate,
)
from datalens_sdk.domain.chart_types import (
    CombinedLayerType,
    DiscretePaletteId,
    FilterOperation,
    FunnelShape,
    GeoLayerType,
    GradientPaletteId,
    MapType,
    MeasureFormat,
    PaletteId,
    ShapeStyle,
)
```

The signatures below use `FieldRef` as shorthand for `DatasetField | str`.
Examples assume `client` is already configured. For client construction and
authentication, see [../setup.md](../setup.md).

Use the client namespaces and terminal methods as one lifecycle:

```text
client.create.wizard_chart.<factory>(...) -> typed create builder -> .build()
                                                                  |
client.get.wizard_chart(by_id=...) -------------------------------+-> WizardChart
                                                                       |
                                                                       +-> .update
                                                                           -> WizardChartUpdate
                                                                           -> .execute()
```

`C` means a method exists on at least one typed create builder. `U` means it
exists on `WizardChartUpdate`. A `C/U` mark does not mean every visualization
supports the operation; use [the full matrix](_index.md) and the selected
chart-type file. Create builders expose only applicable methods. Update rejects
an operation that does not apply to the chart's current visualization.

## Lifecycle

### Create

All 17 factories have the same entry signature:

```text
client.create.wizard_chart.<factory>(
    *,
    name: str,
    location: EntryLocation,
) -> <TypedWizardChartCreate>
```

Factories are `area`, `area_100p`, `bar`, `bar_100p`, `column`,
`column_100p`, `combined_chart`, `donut`, `flat_table`, `funnel`, `geolayer`,
`line`, `indicator`, `pie`, `pivot_table`, `scatter`, and `treemap`.

Use `EntryLocation.path(dir_path)` or `EntryLocation.workbook(workbook_id)`.
Wizard creation rejects collection locations. `name` must be non-empty; for a
path location it must not contain `/`.

Every create builder inherits:

| Method | Side | Meaning |
|---|---|---|
| `.dataset(dataset: Dataset)` | C | Bind the primary dataset and make its fields available to the builder. |
| `.build() -> WizardChart` | C | Validate, create the chart, and return it. |

The `Required` markers in the chart tables describe the server contract.
Unlike QL builders, Wizard `.build()` does not validate that required
placeholders are populated client-side. Re-fetch and validate the persisted
chart instead of treating a successful build as proof of completeness.

`geolayer` additionally has `.add_dataset(dataset)` for multiple layer
datasets. Its inherited `.dataset(dataset)` remains the primary binding.

### Get

Use the typed getter when the chart is known to be Wizard:

```text
client.get.wizard_chart(
    *,
    by_id: str | None = None,
    workbook_id: str | None = None,
    branch: Literal["saved", "published"] | None = None,
    rev_id: str | None = None,
) -> WizardChart
```

Use the generic getter only when the chart category is unknown:

```text
client.get.chart(
    *,
    by_id: str | None = None,
    workbook_id: str | None = None,
    branch: Literal["saved", "published"] | None = None,
    rev_id: str | None = None,
) -> WizardChart | EditorChart | QLChart
```

The Python signature defaults `by_id` to `None` because it is shared with
generated getter infrastructure, but the public call contract requires a chart
ID and rejects `None`. There is no key-based lookup argument. Pass `workbook_id` when
the installation requires workbook context. When both `rev_id` and `branch`
are provided, `rev_id` wins and the client emits `UserWarning`.

### Inspect and Entry Operations

`WizardChart` inherits the following public state from `Chart`:

| Surface | Type / behavior |
|---|---|
| `.id` | `str | None`; entry ID used by get/update/delete. |
| `.name` | `str | None`. |
| `.description` | `str | None`. |
| `.location` | `EntryLocation | None`. |
| `.key` | Derived/reported navigation key, if available. |
| `.dir_path` | Path location, if applicable. |
| `.workbook_id` | Workbook location ID, if applicable. |
| `.collection_id` | Collection metadata, if reported. |
| `.category` | Always `"wizard"`. |
| `.visualization_id` | Current Wizard visualization ID, or `None`. |
| `.fields` | `FieldsProxy` containing fields currently referenced by the chart. |
| `.dataset_ids` | Tuple of datasets currently referenced by the chart. |
| `.update` | A new `WizardChartUpdate` bound to this chart. |

Entry methods:

```text
chart.rename(name: str) -> WizardChart
chart.get_relations(
    *,
    include_permissions_info: bool | None = None,
    link_direction: Literal["from", "to"] | None = None,
    page_size: int = 100,
    scope: Literal["dash", "report", "widget", "dataset", "folder", "connection"] | None = None,
) -> Pager[EntryRelation]
chart.delete() -> None
```

`rename` and `delete` require a bound chart with an ID. `get_relations` is lazy:
iterate the returned pager or call `.pages()`. Deletion is destructive; obtain
explicit user approval first.

### Update

Start from `chart.update`, chain methods, then call:

```text
.mode(value: Literal["save", "publish"])  # default is "save"
.execute() -> WizardChart
```

No update is persisted before `.execute()`. Create and update responses can be
minimal, so re-fetch by ID before reading `.fields` or `.dataset_ids`, or before
starting another update that depends on the persisted chart state.

## Field References

Create-side field arguments use `FieldLike | str`, where current `FieldLike` is
`DatasetField`. Update-side arguments use `FieldRef`, currently
`DatasetField | str`.

Prefer `DatasetField`:

```python
dataset = client.get.dataset(by_id="dataset-id")
date = dataset.fields.by_name("Order Date")
sales = dataset.fields.by_guid("sales-guid")
```

For placeholder, decoration, filter, sort, hierarchy, and replacement-new
arguments, string resolution is deterministic:

1. Resolve a chart-local field or hierarchy by exact GUID/title where supported.
2. Resolve an exact dataset-field GUID.
3. Resolve an exact dataset-field title or name.
4. Reject ambiguous title/name matches and unresolved strings.

On create, call `.dataset(dataset)` before relying on dataset field strings. On
update, strings can resolve only against fields already active in the loaded
chart and chart-local fields. To place an unreferenced dataset field, fetch the
dataset using `chart.dataset_ids[0]` and pass its `DatasetField`.

Structural target arguments are stricter. For `replace_field(old, ...)`,
`delete_field(field)`, `delete_filter(field)`, and
`replace_formula(field, ...)`, a string means an exact field GUID, not a title.
Prefer the matching object from `chart.fields`; otherwise pass its exact GUID.
`replace_formula()` applies only to a chart-local `add_field` formula. An
unknown or title-like target can fail or leave the formula unchanged.

Placeholder setters replace that placeholder's complete field list; pass `[]`
to clear an optional placeholder. `chart.fields` lists active fields but does
not expose their placeholder membership. When updating an existing chart,
obtain the intended complete field list from the user or known chart design;
do not guess which active fields belong to `x`, `y`, `y2`, or another group.
`sort(fields)` replaces the create-side sort list, while
`add_sort(field, direction=...)` appends one directional sort.

## Fluent Operation Catalog

### Placeholders and Layers

| Signature | Side | Notes |
|---|---|---|
| `.x(fields: Sequence[FieldRef])` | C/U | Set `x`; meaning and capacity are chart-specific. |
| `.y(fields: Sequence[FieldRef])` | C/U | Set `y`; aliases `measures` for indicator, pie, donut, funnel, treemap, and pivot table. |
| `.y2(fields: Sequence[FieldRef])` | C/U | Line create; update only when the active viz accepts `y2`. |
| `.columns(fields: Sequence[FieldRef])` | C/U | Flat/pivot create; update applicability is viz-checked. |
| `.rows(fields: Sequence[FieldRef])` | C/U | Pivot create; update applicability is viz-checked. |
| `.measures(fields: Sequence[FieldRef])` | U | Update alias for indicator, pie, donut, funnel, treemap, and pivot table; their create builders expose `.y(...)`. |
| `.points(fields: Sequence[FieldRef])` | C/U | Scatter point identity. |
| `.size(fields: Sequence[FieldRef])` | C/U | Scatter size; capacity is chart-specific. |
| `.add_layer(layer_type: CombinedLayerType, *, y=None, y2=None, name=None)` | C | Combined only; require at least one of `y`/`y2`. |
| `.add_dataset(dataset: Dataset)` | C | Geolayer only; register an additional layer dataset. |
| `.add_layer(layer_type: GeoLayerType, *, ...)` | C | Geolayer only; see the [full signature and layer capabilities](chart-geolayer.md#fluent-operations). |

### Fields, Filters, Sorting, and Metadata

| Signature | Side | Notes |
|---|---|---|
| `.description(text: str)` | C/U | Set entry description. |
| `.add_local_field(*, title, formula, guid=None, cast="float", measure=False, aggregation=None, formatting=None)` | C/U | Add a chart-local formula field. |
| `.add_aggregated_measure(field: DatasetField, *, aggregation, name=None, guid=None)` | C/U | Add a local aggregated measure from a dataset dimension; existing measures are rejected. |
| `.change_aggregation(field: DatasetField, *, aggregation, name, guid=None)` | U | Replace a placed dimension or manually aggregated measure; `name` is required. |
| `.add_hierarchy(title, fields, *, guid=None)` | C/U | Add a chart hierarchy; omit `guid` to create one automatically. |
| `.replace_formula(field, *, formula: str)` | U | Replace a chart-local `add_field` formula; target by `DatasetField` or exact GUID, never by title. |
| `.add_filter(field, *, operation: FilterOperation, values=())` | C/U | Append a filter. Null checks normally use empty `values`. |
| `.add_date_filter(field, *, start, end, inclusive_end=True)` | C/U | Append `BETWEEN`; normalize ISO date/datetime values. |
| `.add_relative_date_filter(field, *, start_offset, end_offset)` | C/U | Append relative `BETWEEN`; offsets follow DataLens forms such as `-30d`, `-1M`, `+0d`. |
| `.sort(fields: Sequence[FieldRef])` | C | Replace the create-side sort field list; no directions. |
| `.add_sort(field, *, direction="asc")` | C/U | Append one directional sort; direction is `"asc"` or `"desc"`. |
| `.labels(fields: Sequence[FieldRef])` | C/U | Replace labels fields. |
| `.segments(fields: Sequence[FieldRef])` | C/U | Replace split/segment fields where supported. |
| `.tooltips(fields: Sequence[FieldRef])` | C/U | Replace tooltip fields. |
| `.measure_format(field, *, format=None, precision=None, unit=None, prefix=None, postfix=None, show_rank_delimiter=None)` | C/U | Patch only supplied formatting keys; the field must already be placed in a visualization placeholder. |

`aggregation` for aggregated-measure operations is one of `"sum"`, `"avg"`,
`"min"`, `"max"`, `"count"`, or `"countunique"`.

### Titles, Labels, Legend, and Axes

| Signature | Side | Notes |
|---|---|---|
| `.chart_title(*, text="", mode="show")` | C/U | Mode is `"show"` or `"hide"`. |
| `.legend(*, mode: Literal["show", "hide"])` | C/U | Set legend visibility. |
| `.tooltip_sum(*, enabled: bool)` | C/U | Toggle tooltip totals. |
| `.labels_position(*, mode)` | C/U | `"inside"`, `"outside"`, or `"auto"`. |
| `.label_mode(*, mode)` | C/U | `"absolute"` or `"percent"` on supported charts. |
| `.tooltip_percentage_base(*, mode)` | C/U | Funnel only: `"auto"`, `"first"`, or `"previous"`. |
| `.axis_visibility(ph_id, *, mode)` | C/U | Axis ID is chart-specific; mode is `"show"`/`"hide"`. |
| `.hide_labels(ph_id, *, enabled: bool)` | C/U | Toggle labels on one supported axis. |
| `.nulls_mode(ph_id, *, mode)` | C/U | `"ignore"`, `"connect"`, or `"as-0"`. |
| `.axis_title(ph_id, *, mode, text="")` | C/U | Mode is `"off"`, `"manual"`, or `"auto"`; `text` is used for manual mode. |
| `.axis_scale(ph_id, *, scale="linear", mode="auto", min=None, max=None)` | C/U | Scale is `"linear"`/`"logarithmic"`; manual mode requires a bound. |
| `.grid(ph_id, *, enabled: bool, step=None)` | C/U | Supplying `step` switches grid step to manual. |
| `.navigator(*, mode)` | C/U | `"show"` or `"hide"` on supported Cartesian charts. |

### Color and Shape Encodings

| Signature | Side | Notes |
|---|---|---|
| `.palette(*, id: PaletteId)` | C/U | Style an existing Color binding: discrete palettes require dimension/Measure Names color; gradient palettes require measure color. |
| `.color_by_dimension(field)` | C/U | Bind color to a `DIMENSION`. |
| `.color_by_measure(field, *, mode=None, palette=None, reversed=None)` | C/U | Bind color to a `MEASURE`; use a compatible mode and gradient palette from the table below. |
| `.color_by_measure_name(*, colors_map=None)` | C/U | Color at least two placed measures; map keys must name placed measures. |
| `.shape_by_dimension(field, *, shapes_map=None)` | C/U | Bind shape to a `DIMENSION` and optionally map its values to `ShapeStyle`. |
| `.shape_by_measure_name(*, shapes_map=None)` | C/U | Shape at least two placed measures; map keys must name placed measures. |
| `.shape(*, value: FunnelShape)` | C/U | Funnel shape: `"auto"`, `"rectangle"`, or `"trapezoid"`. |
| `.point_size_range(*, min_radius=4.5, max_radius=9.0)` | C/U | Scatter marker radius range. |

Calling another explicit color or shape binding in the same chain replaces the
previous binding of that encoding.

`color_by_measure_name(colors_map=...)` accepts `#RRGGBB`, `#RRGGBBAA`, or a
non-negative palette-index string such as `"2"` for each override value.

`color_by_measure()` accepts only these gradient combinations:

| Mode | Palettes |
|---|---|
| `"2-point"` | `"blue"`, `"orange-yellow"`, `"yellow"` |
| `"3-point"` | `"orange-gray-blue"`, `"pink-gray-green"`, `"red-orange-green"` |

### Table Operations

| Signature | Side | Notes |
|---|---|---|
| `.pagination(*, enabled: bool, limit=100)` | C/U | Store `limit` when enabled. |
| `.table_size(*, size)` | C/U | `"s"`, `"m"`, or `"l"`. |
| `.freeze_columns(*, count=1)` | C/U | Set pinned column count. |
| `.totals(*, enabled: bool)` | C/U | Flat table only. |
| `.column_title(field, *, title: str)` | C/U | Target a field already placed in a table placeholder. |
| `.column_background(field, *, mode="3-point", palette="red-orange-green", thresholds=None, reversed=False)` | C/U | Gradient cell background; thresholds count must match mode. |
| `.column_bars(field, *, enabled=True, color_type="one-color", color=None, palette=None, color_index=None, color_positive=None, color_negative=None, positive_color_index=None, negative_color_index=None, gradient_palette=None, gradient_type="2-point", reversed=False, show_labels=True, show_in_totals=False, align="default")` | C/U | Configure in-cell bars; obey color-mode constraints below. |
| `.subtotals(field, *, enabled: bool)` | C/U | Pivot table only; target a placed field. |

### Indicator and Map Operations

| Signature | Side | Notes |
|---|---|---|
| `.font_size(*, size)` | C/U | Indicator only: `"xs"`, `"s"`, `"m"`, or `"l"`. |
| `.font_color(*, color: str)` | C/U | Indicator only; require `#RRGGBB`. |
| `.measure_title_mode(*, mode)` | C/U | Indicator only: `"by-field"`, `"manual"`, or `"hide"`. |
| `.map_type(*, mode: MapType)` | C | Geolayer only: `"light"`, `"dark"`, or `"satellite"`. |
| `.map_center(*, lat: float, lon: float, zoom: int | None=None)` | C | Geolayer only; selects manual center. |

### Update-Only Structural Mutations

| Signature | Side | Meaning / constraint |
|---|---|---|
| `.mode(value: Literal["save", "publish"])` | U | Select update mode; default is `"save"`. |
| `.change_visualization_to(*, visualization_id: str)` | U | Only verified transitions: `line↔column` and `line↔bar`; bar swaps axes. |
| `.replace_field(old, new)` | U | Replace every chart use of `old`; target `old` by object or exact GUID. |
| `.delete_field(field)` | U | Remove every chart use of a field targeted by object or exact GUID. |
| `.replace_dataset(*, old: str, new: str)` | U | Rebind references from one dataset ID to another. |
| `.delete_filter(field)` | U | Remove filters targeted by a field object or exact field GUID. |
| `.execute() -> WizardChart` | U | Validate, persist, and return the updated chart. |

`change_visualization_to` rejects unknown, identical, and unsupported
transitions. It preserves only the fields mapped by the supported transition;
review the result before publishing.

## Argument Domains and Constraints

### Shared Literals

- `FilterOperation`: `"IN"`, `"EQ"`, `"NE"`, `"GT"`, `"GTE"`, `"LT"`,
  `"LTE"`, `"BETWEEN"`, `"ISNULL"`, `"ISNOTNULL"`, `"STARTSWITH"`,
  `"CONTAINS"`.
- `MeasureFormat.format`: `"number"`, `"percent"`.
- `MeasureFormat.unit`: `"auto"`, `"k"`, `"m"`, `"b"`, `"t"`.
- `CombinedLayerType`: `"column"`, `"line"`, `"area"`.
- `GeoLayerType`: `"geopoint"`, `"geopoint-with-cluster"`, `"geopolygon"`, `"heatmap"`, `"polyline"`.
- `ShapeStyle`: `"Solid"`, `"Dash"`, `"Dot"`, `"ShortDash"`, `"ShortDot"`,
  `"ShortDashDot"`, `"ShortDashDotDot"`, `"LongDash"`, `"DashDot"`,
  `"LongDashDot"`, `"LongDashDotDot"`.
- Discrete palettes: `"datalens-classic-20"`, `"classic20"`,
  `"datalens-neo-20"`, `"defaultScheme"`, `"neutral20"`, `"taxi-paired"`,
  `"taxi-pastel"`, `"taxi9"`, `"yandex-cloud"`.
- Gradient palettes: `"blue"`, `"orange-gray-blue"`, `"orange-yellow"`,
  `"pink-gray-green"`, `"red-orange-green"`, `"yellow"`.

### Validation Rules

- `axis_scale(mode="manual")` requires at least one of `min` or `max`.
- `add_aggregated_measure` requires a dimension `DatasetField` whose
  `calc_mode` is `"direct"` or `"formula"` and whose source/formula metadata is
  present. It rejects fields that are already measures.
- `change_aggregation` requires the exact `DatasetField` to be active in the
  loaded chart. It accepts a placed dimension or manually aggregated measure
  and rejects automatically aggregated measures.
- `measure_format` requires its field to be placed first. In one create/update
  chain, call the applicable placeholder setter before `measure_format`.
- `color_by_dimension` and `shape_by_dimension` require dimension fields;
  `color_by_measure` requires a measure. Treemap dimension color additionally
  requires the same field in its `dimensions` section.
- `color_by_measure` requires a mode-compatible gradient palette: sequential
  `blue`, `orange-yellow`, and `yellow` support only `"2-point"`; diverging
  `orange-gray-blue`, `pink-gray-green`, and `red-orange-green` support only
  `"3-point"`.
- `color_by_measure_name` and `shape_by_measure_name` require at least two
  measures across the chart's supported measure placeholders. Override-map
  keys must resolve to measures already placed there.
- On `column` and `bar`, multi-measure coloring inserts the pseudo
  `Measure Names` item into the category placeholder (`x` for column, `y` for
  bar). It counts toward that placeholder's capacity of 2, so use at most one
  ordinary category field with multiple measures.
- `palette` requires an existing Color field. Use a discrete palette with a
  dimension or Measure Names, and a gradient palette with a measure.
- `column_background` requires exactly two thresholds for `"2-point"` and
  exactly three for `"3-point"` when thresholds are supplied.
- `column_bars(color_type="gradient")` requires `gradient_palette`.
  Sequential palettes (`blue`, `orange-yellow`, `yellow`) support only
  `"2-point"`; diverging palettes (`orange-gray-blue`, `pink-gray-green`,
  `red-orange-green`) support only `"3-point"`.
- `column_bars` color arguments are mutually exclusive by `color_type`:
  use `color`/`palette`/`color_index` for `"one-color"`;
  `color_positive`/`color_negative` and their indexes for `"two-color"`;
  `gradient_palette` for `"gradient"`.
- Table item mutations must target a field already placed in a placeholder.
- Combined `.add_layer()` requires at least one of `y` or `y2`.
- For geolayer field types, layer capabilities, filter scopes, gradients,
  polyline ordering, and lifecycle constraints, use the
  [canonical geolayer contract](chart-geolayer.md).
- `font_color` accepts a full six-digit hex color such as `#0FA08D`.

## Minimal Examples

### Create

```python
import datalens_sdk as dl

dataset = client.get.dataset(by_id="dataset-id")
date = dataset.fields.by_name("Order Date")
sales = dataset.fields.by_name("Sales")

chart = (
    client.create.wizard_chart.line(
        name="Sales over time",
        location=dl.EntryLocation.path("/Users/me"),
    )
    .dataset(dataset)
    .x([date])
    .y([sales])
    .axis_title("y", mode="manual", text="Sales")
    .build()
)
```

### Get and Inspect

```python
chart = client.get.wizard_chart(
    by_id="chart-id",
    workbook_id="workbook-id",
    branch="saved",
)
print(chart.id, chart.visualization_id, chart.dataset_ids)
print([field.title for field in chart.fields])
```

### Update

```python
dataset = client.get.dataset(by_id=chart.dataset_ids[0])
profit = dataset.fields.by_name("Profit")

updated = chart.update.y([profit]).description("Now shows profit").mode("publish").execute()

# Re-fetch before state-dependent inspection or another update.
chart = client.get.wizard_chart(by_id=updated.id)
```

### Rename, Relations, Delete

```python
chart = chart.rename("Published profit")
dependencies = list(chart.get_relations(link_direction="to"))

# Destructive: call only after explicit user approval.
chart.delete()
```

## Related References

- [Chart-type routing and full operation matrix](_index.md)
- [Operation recipes](operation-recipes.md) — cross-cutting how-tos with
  complete code
- [../serialization.md](../serialization.md) — export, import, clone, and
  copy of charts across workbooks
- [../core-concepts.md](../core-concepts.md) — object model, retries,
  pagination
- [../setup.md](../setup.md) — client construction, auth, environment
