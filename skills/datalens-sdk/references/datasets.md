# Datasets

Read this when creating a dataset from sources or editing its fields, calculations, parameters, joins, filters, RLS, or settings with the update DSL.

## Create from sources

```python
src = (
    client.create.source(using=conn)
    .ch_table(alias="sales", db_name="samples", table_name="MS_SalesFacts")
    .build(strict=True)
)

ds = client.create.dataset(name="Sales", location=wb).sources([src]).description("Sales facts").build()

ds = client.get.dataset(by_id=ds.id)  # MANDATORY before any field operation
```

**The re-`get` is not optional.** The create response omits field snapshots, so `ds.fields.by_name(...)` on the create result raises "field not found" for every field. Always re-fetch first.

`DatasetCreate` also accepts nearly the whole update DSL below (`add_field`, `add_calculation`, `add_parameter`, `add_default_filter`, `add_rls`, `update_setting`, ...) so a dataset can be born fully configured in one `.build()`. One signature differs: creation-time `add_relation` additionally requires `left_source=` / `right_source=` (a `Source` or its id), because before the first validation there are no field snapshots to infer the join sides from.

## The read model

After the re-`get`:

```python
ds.fields  # FieldsProxy — a sequence of DatasetField
ds.fields.by_name("Sales")  # matches title or name; raises DataLensValidationError
#   with "Did you mean ...?" hints on a miss
ds.fields.by_guid(guid)  # exact guid; raises on a miss

ds.find_field("Sales")  # forgiving twin: guid first, then title/name; returns None on a miss
ds.find_fields(grep="amount", kind="MEASURE", hidden=False)  # filtered list[DatasetField]

ds.parameters  # FieldsProxy of parameter fields only (calc_mode == "parameter")
ds.sources  # SourcesProxy; ds.sources.by_alias("sales") matches title or id
```

`find_field` / `find_fields` live on the **`Dataset`**, not on `FieldsProxy`. `find_fields` filters: `grep=` (case-insensitive regex on title), `calc_mode=` (`"direct"` / `"formula"` / `"parameter"`), `kind=` (`"DIMENSION"` / `"MEASURE"`), `hidden=`, `only_with_description=`.

A `DatasetField` is a frozen dataclass: `guid`, `title`, `name`, `calc_mode`, `data_type`, `type`, `aggregation`, `cast`, `source` (backing column), `avatar_id`, `formula`, `description`, `hidden`, plus the raw payload in `.raw`.

`Source` is a slotted dataclass with public attributes `id`, `source_type`,
`title`, `connection_id`, `connection_type`, `parameters`, `raw_schema`,
`valid`, and `fields`. It has no `.raw` and no instance `__dict__`; read those
typed attributes directly.

Structural snapshots for id lookups are deliberately mapping-shaped:
`ds.relations`, `ds.default_filters`, `ds.source_avatars`, and `ds.rls2`.
In particular, each `source_avatars` item and the result of
`ds.find_source_avatar(title_or_id)` is a `Mapping[str, object]`, not an object
with `.id`/`.title`; use `avatar.get("id")`, `avatar.get("source_id")`, and
`avatar.get("title")`.

## The update DSL

`ds.update` is a property returning a fresh `DatasetUpdate`. Each method appends an action; **chain as many as you like and finish with a single `.execute()`**, which sends one validated update and returns the new `Dataset`:

```python
ds = (
    ds.update.change_field_aggregation(field=ds.fields.by_name("Sales"), to="sum")
    .add_calculation(
        name="Margin",
        formula="SUM([Profit]) / SUM([Sales])",
        kind="MEASURE",
        cast="float",
    )
    .hide_field(field="OrderID")
    .execute()
)
```

Anywhere a method takes `field=` it accepts a `DatasetField` object or a string (guid, title, name, or source column). Prefer the `DatasetField` — in multi-source datasets a bare string that matches fields on several avatars is ambiguous. Formulas reference other fields by `[Title]`.

For expression syntax, calculation levels, functions, diagnostics, and the
choice between reusable Dataset formulas and chart-local Wizard formulas, read
[the formula index](formulas/_index.md). A successful `.execute()` persists
formula text; it does not prove semantic validity at render time.

### Fields, calculations, parameters

```python
u = ds.update
u.add_field(
    title="Shop", source="ShopName", kind="DIMENSION", cast="string", avatar_id=src_b.id
)  # direct field from a source column;
# avatar_id disambiguates multi-source datasets
u.add_calculation(
    name="AOV", formula="SUM([Sales]) / COUNTD([OrderID])", kind="MEASURE", aggregation="none", cast="float"
)
u.add_parameter(name="Threshold", type="integer", default=100)

u.change_field_type(field="AOV", to="float")
u.change_field_aggregation(field="Sales", to="sum")  # "none" flips the field back to a dimension
u.change_field_description(field="AOV", to="Average order value")
u.update_field(field="AOV", title="Avg order value", hidden=False)  # general-purpose editor
u.update_field_format(
    field="AOV", format_="number", precision=2, unit="auto", prefix="$", show_rank_delimiter=True
)  # note: format_ with underscore
u.update_calculation(field="AOV", formula="AVG([Sales])", kind="MEASURE")
u.update_parameter(field="Threshold", default=200)
u.clone_field(field="AOV", new_title="AOV copy")
u.hide_field(field="AOV copy")
u.show_field(field="AOV copy")
u.delete_field(field="AOV copy")
ds = u.execute()
```

For how a Dataset parameter reaches Wizard widgets through widget params,
dashboard global params, manual selectors, URL state, or action filtering,
read [parameters.md](parameters.md). The exact Dataset parameter `name`, not a
display title, is the receiving key.

Cache invalidation has a separate formula-bearing surface:
`update_cache_invalidation_source(source=CacheInvalidationSource(...))` on
both Dataset create and update builders. Its
`CacheInvalidationFormula(formula=..., guid_formula=...)` pair controls cache
freshness and does not create a reusable Dataset field. Use it only for cache
invalidation workflows; see
[formula SDK surfaces](formulas/sdk-surfaces.md#direct-authoring).

Value vocabularies (all plain string literals):

| Parameter | Allowed values |
|---|---|
| `kind` (`FieldKind`) | `"DIMENSION"`, `"MEASURE"` |
| `aggregation` (`Aggregation`) | `"none"`, `"sum"`, `"avg"`, `"min"`, `"max"`, `"count"`, `"countunique"` |
| `cast` / `to` (`DataType`) | `"string"`, `"integer"`, `"float"`, `"date"`, `"datetime"`, `"genericdatetime"`, `"boolean"`, `"geopoint"`, `"geopolygon"`, ... |
| parameter `type` (`ParameterDataType`) | `"string"`, `"integer"`, `"float"`, `"date"`, `"datetime"`, `"boolean"` |
| `format_` / `unit` | `"number"` or `"percent"` / `"auto"`, `"k"`, `"m"`, `"b"`, `"t"` |

### Joins (relations)

```python
from datalens_sdk import JoinCondition

ds = ds.update.add_relation(
    type="left",  # "inner" | "left" | "right" | "full"
    conditions=[JoinCondition(left="ShopID", right="ShopID", operator="eq")],
    drop_duplicates=False,
).execute()
```

`JoinCondition(left, right, operator="eq")` takes **source column names** for each side; operators: `"eq"`, `"ne"`, `"gt"`, `"gte"`, `"lt"`, `"lte"`. On the update path the avatars are inferred from the first condition's columns; on the create path pass `left_source=` / `right_source=` explicitly (see the full example below). Edit an existing join with `update_relation(relation_id=..., type=..., conditions=..., drop_duplicates=...)` or remove it with `delete_relation(relation_id=...)` — ids come from `ds.relations`.

### Default filters and RLS

```python
u = ds.update
u.add_default_filter(field="Shop", operator="EQ", values=["Epsilon"])
u.update_default_filter(filter_id=fid, operator="IN", values=["Epsilon", "Delta"])  # fid from ds.default_filters
u.delete_default_filter(filter_id=fid)

u.add_rls(
    field="Shop", subject_id=user_id, allowed_value="Epsilon"
)  # subject_type: "user" | "group" | "all" | "userid"
u.update_rls(field="Shop", subject_id=user_id, allowed_value="Delta")
u.delete_rls(field="Shop")  # drops all RLS entries for the field
ds = u.execute()
```

Filter operators (`WhereOperation`) are uppercase: `"EQ"`, `"NE"`, `"GT"`, `"GTE"`, `"LT"`, `"LTE"`, `"IN"`, `"NIN"`, `"BETWEEN"`, `"CONTAINS"`, `"ICONTAINS"`, `"STARTSWITH"`, `"ISNULL"`, `"ISNOTNULL"`, ...

### Sources, settings, connection

```python
u = ds.update
u.add_source(source=extra_src)  # registers the source; creates no avatar
u.update_source(
    source_id=src.id,
    title="facts-v2",
    parameters={**src.parameters, "db_name": "samples", "table_name": "FactsV2"},
)
u.delete_source(source_id=extra_src.id)
avatar = ds.find_source_avatar(src.id)  # Mapping[str, object] | None
avatar_id = avatar.get("id") if avatar is not None else None
if not isinstance(avatar_id, str):
    raise LookupError(f"Source avatar for {src.id!r} not found")
u.update_source_avatar(avatar_id=avatar_id, title="Shops")
# Alternative destructive action when explicitly requested:
# u.delete_source_avatar(avatar_id=avatar_id)
u.refresh_source(src.id, force_update_fields=False)  # re-sync fields after schema drift (positional id)
u.replace_connection(old_connection_id=old_id, new_connection_id=new_id)
u.update_setting(name="load_preview_by_default", value=False)
# names: "load_preview_by_default" | "template_enabled" | "data_export_forbidden"
u.name("Sales v2")  # rename inside the same update
u.description("Refreshed")
ds = u.execute()
```

`update_source(*, source_id, title=None, parameters=None)` preserves the
current title or parameters only when that argument is omitted. When changing
source parameters, pass the complete desired mapping—normally a copy of
`src.parameters` with narrow overrides—so connector-specific keys are not
lost. Do not look for `src.raw` or patch a dataset snapshot.

To refresh every registered source and force dataset fields to follow the
current source schemas, use the dataset convenience method:

```python
ds = client.get.dataset(by_id=dataset_id)
ds = ds.enrich_via_refresh(force_update_fields=True)
ds = client.get.dataset(by_id=dataset_id)
```

### Typed source-schema migration

Use this sequence for a connection/table migration; keep each mutation narrow
and re-fetch between phases so the next builder uses current server state:

1. Fetch the dataset, its sources, source avatars, fields, and outgoing
   relations. Record source ids, full `Source.parameters`, field GUIDs, and
   every dependent chart before mutating.
2. If the connection changes, call
   `replace_connection(old_connection_id=..., new_connection_id=...).execute()`
   and re-fetch.
3. Resolve the current `Source` from `ds.sources`, merge the desired table or
   query keys into `source.parameters`, and call
   `update_source(source_id=..., title=..., parameters=...).execute()`. Re-fetch.
4. Call `ds.enrich_via_refresh(force_update_fields=True)`, then re-fetch and
   inspect `source.valid`, `source.raw_schema`, `ds.fields`, and source-avatar
   mappings.
5. Apply only confirmed field/formula changes with the typed dataset update
   DSL. Then update each dependent chart with its typed update builder,
   preserving chart and dataset ids.
6. Re-fetch the dataset and every dependent chart and verify connection ids,
   source parameters/schema, field GUIDs/formulas, chart references, and saved
   versus published state where applicable.

Schema similarity is not permission to invent semantics. Do not guess renamed
column mappings, formulas, aggregations, field kinds, or derived values from
spelling or sample names. If old fields lack an exact source match and the
task/data contract does not define their replacements, stop before that
mutation and ask the user for the mapping. Likewise, add newly discovered
columns as direct fields only when their source identity and intended kind are
known; do not synthesize fields such as month/year ids without an explicit
definition.

## Complete example: two-table join

```python
conn = client.get.connection(by_id=connection_id)

factory = client.create.source(using=conn)
facts = factory.ch_table(alias="facts", db_name="samples", table_name="MS_SalesFacts").build(strict=True)
shops = factory.ch_table(alias="shops", db_name="samples", table_name="MS_Shops").build(strict=True)

from datalens_sdk import JoinCondition

ds = (
    client.create.dataset(name="Sales by shop", location=wb)
    .sources([facts, shops])
    .add_relation(
        type="left",
        conditions=[JoinCondition(left="ShopID", right="ShopID")],
        left_source=facts,
        right_source=shops,
    )
    .build()
)

ds = client.get.dataset(by_id=ds.id)  # re-get before field ops
ds = (
    ds.update.change_field_aggregation(field=ds.fields.by_name("Sales"), to="sum")
    .add_calculation(name="Sales per shop", formula="SUM([Sales])", kind="MEASURE", cast="float")
    .execute()
)
```

Verify before reporting done (hard rule 4): the returned `ds` reflects the applied actions — check `ds.relations`, `ds.fields.by_name("Sales per shop")`, aggregations.

## Related references

- [dataset-data.md](dataset-data.md) — reading typed rows from an existing dataset
- [core-concepts.md](core-concepts.md) — namespaces, locations, field-reference rules, retries
- [connections.md](connections.md) — building the connection and sources a dataset consumes
- [wizard-charts/_index.md](wizard-charts/_index.md) — putting dataset fields into charts
- [troubleshooting.md](troubleshooting.md) — any `DataLensAPIError`, before retrying anything
