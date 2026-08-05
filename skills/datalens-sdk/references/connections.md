# Connections

Read this when creating or editing a connection to a database or API, or binding one of its tables/queries as a dataset source.

## The connection builder pattern

`client.create.connection.<type>(name=..., location=...)` returns a fluent builder with one setter per connector field; `.build()` persists and returns a `Connection`:

```python
conn = client.create.connection.postgres(name="prod-pg", location=wb).host("pg.example.net").port(6432).build()
```

Builder behavior (same for every connector):

- Accessing a setter the connector does not expose raises plain `AttributeError`.
  Passing a value outside a generated enum's allowed values raises
  `NotSupportedError` immediately. Use `fields_help()` and
  `allowed_values(field)` instead of guessing.
- `.build()` raises `DatalensValidationError` listing the missing required fields before any HTTP call.
- Every builder self-describes: `required_fields()`, `optional_fields()`, `missing_required()`, `allowed_values(field)`, and `fields_help()` (a `dict[str, FieldHelp]` with required/default/allowed per field). Use these instead of guessing — connector fields vary a lot.

**Credentials are secrets.** `password`, `token`, `access_token`, and similar builder values must come from the environment (`os.environ[...]`) — never hardcode them in scripts, never print or echo them, and never write them into `.env` yourself (the user does that).

## Factory catalog

The factory surface is generated per installation. Enterprise exposes a subset
of the Yandex Cloud surface; every shared connector has identical builder
fields on both. This table documents the public package, but the configured
client's `client.capabilities["connectors"]` inventory is authoritative. If a
listed factory is absent there, report it as unavailable instead of calling or
reconstructing it.

### Databases

| Factory      | Backend            | Required fields                                                                             | YC  | Enterprise |
|--------------|--------------------|---------------------------------------------------------------------------------------------|-----|------------|
| `clickhouse` | ClickHouse         | `host`, `port`                                                                              | yes | yes        |
| `postgres`   | PostgreSQL         | `host`, `port`                                                                              | yes | yes        |
| `mysql`      | MySQL              | `host`, `port`                                                                              | yes | yes        |
| `mssql`      | MS SQL Server      | `host`, `port`, `username`, `password`                                                      | yes | yes        |
| `oracle`     | Oracle             | `host`, `port`, `username`, `password`, `db_connect_method`                                 | yes | yes        |
| `greenplum`  | Greenplum          | `host`, `port`, `username`, `password`                                                      | yes | yes        |
| `trino`      | Trino              | `host`, `listing_sources`                                                                   | yes | yes        |
| `ydb`        | YDB                | `host`, `port`, `db_name`, `cloud_id`, `folder_id`, `service_account_id`                    | yes | yes        |
| `chyt`       | CHYT over YTsaurus | `host`, `port`, `alias`, `token`                                                            | yes | yes        |
| `promql`     | Prometheus         | `host`, `port`                                                                              | yes | yes        |
| `bigquery`   | Google BigQuery    | `project_id`, `credentials`                                                                 | yes | —          |
| `snowflake`  | Snowflake          | `account_name`, `client_id`, `client_secret`, `db_name`, `schema`, `user_name`, `warehouse` | yes | —          |
| `yq`         | Yandex Query       | `cloud_id`, `folder_id`, `service_account_id`                                               | yes | —          |

### API-based

| Factory          | Backend                    | Required fields                   | YC  | Enterprise |
|------------------|----------------------------|-----------------------------------|-----|------------|
| `json_api`       | Generic JSON-over-HTTP API | `host`, `port`, `allowed_methods` | yes | yes        |
| `metrika_api`    | Yandex Metrica             | `counter_id`, `token`             | yes | yes        |
| `appmetrica_api` | AppMetrica                 | `counter_id`, `token`             | yes | yes        |
| `gsheets`        | Google Sheets              | `url`                             | yes | —          |
| `bitrix24`       | Bitrix24                   | `portal`, `token`                 | yes | —          |
| `moysklad`       | MoySklad                   | `access_token`                    | yes | —          |
| `equeo`          | Equeo                      | `access_token`                    | yes | —          |
| `kontur_market`  | Kontur.Market              | `access_token`                    | yes | —          |
| `extractor1c`    | 1C extractor               | `access_token`                    | yes | —          |

### Cloud-specific (Yandex Cloud only)

`monitoring` (Yandex Monitoring; `cloud_id`, `folder_id`, `service_account_id`), `speechsense` (`project_id`), `smb_heatmaps` (`token`), `ch_billing_analytics`, `ch_ya_music_podcast_stats` (`token`), `usage_analytics_detailed`, `usage_analytics_light`.

Accessing a factory that does not exist on the selected client raises plain
`AttributeError`, so `hasattr(client.create.connection, "bigquery")` is a safe
probe.

## Canonical example: ClickHouse

```python
import os

conn = (
    client.create.connection.clickhouse(name="prod-ch", location=wb)
    .host(os.environ["CH_HOST"])
    .port(8443)
    .db_name("samples")
    .username(os.environ["CH_USER"])
    .password(os.environ["CH_PASSWORD"])  # secret: env only, never echo
    .raw_sql_level("off")  # "off" | "subselect" | "template" | "dashsql"
    .ssl_ca_verify("on")
    .secure("on")
    .build()
)
```

`raw_sql_level` gates subselect sources and QL charts on this connection:
`"off"` allows neither, `"subselect"` allows subselect dataset sources, and
`"dashsql"` also allows QL charts. `secure`, `ssl_ca_verify` and
`data_export_forbidden` use the strings `"on"` / `"off"`. As of now, the
ClickHouse `secure` field has an unconstrained server schema and is generated
as `Mapping[str, object]`; do not guess its payload from the other options; this will change in future releases.

## Binding a source

A source is not a standalone entity — it binds one table or query of a connection for use in a dataset:

```python
src = (
    client.create.source(using=conn)
    .ch_table(alias="sales", db_name="samples", table_name="MS_SalesFacts")
    .build(strict=True)
)
ds = client.create.dataset(name="Sales", location=wb).sources([src]).build()
```

- `alias` becomes the source title — it is how you find the source later (`dataset.sources.by_alias("sales")`) and how join sides read in the UI.
- **Always pass `strict=True`.** `.build()` validates the source against the server; with `strict=True` an empty or invalid schema raises `DatalensValidationError` at once. The default (`strict=False`) only warns and returns a `Source` with `valid=False` and an empty schema, which then fails later and less clearly inside dataset creation.
- The source type must match the connection type (`ch_table` needs a `clickhouse` connection) — mismatch raises `NotSupportedError`.

### Main source types

`client.create.source(using=conn).<type>(...)`; all parameters are keyword-only, `alias` is always required:

| Type                                                                     | Connection                         | Key parameters                                                              |
|--------------------------------------------------------------------------|------------------------------------|-----------------------------------------------------------------------------|
| `ch_table`                                                               | clickhouse                         | `db_name`, `table_name`                                                     |
| `ch_subselect`                                                           | clickhouse                         | `subsql` (needs `raw_sql_level` ≥ `"subselect"`)                            |
| `pg_table`                                                               | postgres                           | `db_name`, `schema_name`, `table_name`                                      |
| `pg_subselect`                                                           | postgres                           | `subsql`                                                                    |
| `mysql_table` / `mysql_subselect`                                        | mysql                              | `db_name`, `table_name` / `subsql`                                          |
| `mssql_table`, `oracle_table`, `gp_table`, `trino_table`                 | mssql / oracle / greenplum / trino | `db_name`, `schema_name`, `table_name` (+ `_subselect` twins with `subsql`) |
| `ydb_table` / `ydb_subselect`                                            | ydb                                | `db_name`, `table_name` / `subsql`                                          |
| `chyt_ytsaurus_table`                                                    | chyt                               | `table_name` (a YT path like `//home/...`)                                  |
| `chyt_ytsaurus_subselect`                                                | chyt                               | `subsql`                                                                    |
| `chyt_ytsaurus_table_list`                                               | chyt                               | `table_names`                                                               |
| `chyt_ytsaurus_table_range`                                              | chyt                               | `directory_path`, `range_from`, `range_to`                                  |
| `bigquery_table`, `snowflake_table`, `yq_table`, `gsheets`, `monitoring` | YC-only connectors                 | per-type; introspect or use `client.capabilities["dataset_sources"]`        |
| `json_api`, `metrika_api`, `appmetrica_api`, `promql`                    | matching API connector             | `alias` (+ `table_name` for the metrika pair)                               |

For a type without a generated helper there is an escape hatch: `client.create.source(using=conn).raw(alias=..., source_type="CH_TABLE", parameters={...})` returns an unvalidated `Source` directly.

## Get, update, rename, delete

```python
conn = client.get.connection(by_id=connection_id)  # id only; no name lookup

conn = (
    conn.update.host("new-host.example.net")  # property -> ConnectionUpdate builder
    .set("password", os.environ["CH_PASSWORD"])  # generic setter for any field
    .description("moved to the new cluster")
    .execute()
)

conn = conn.rename("prod-ch-v2")  # returns the renamed Connection
conn.delete()  # hard rule 6: confirm before deleting
```

`ConnectionUpdate` accepts any field name as a dynamic setter (`.host(...)`, `.port(...)`, `.raw_sql_level(...)`) or via `.set(field, value)`. Unlike the create builder it does **not** validate field names client-side — a typo surfaces as a server error, so copy field names from the create builder's `fields_help()`. Datasets keep referencing the connection by id across updates and renames; to point a dataset at a *different* connection use `dataset.update.replace_connection(...)` ([datasets.md](datasets.md)).

## Related references

- [core-concepts.md](core-concepts.md) — namespaces, locations, `client.capabilities`, error families
- [datasets.md](datasets.md) — feeding sources into datasets, joins, `replace_connection`
- [wizard-charts/_index.md](wizard-charts/_index.md) — charts on top of the datasets you build
- [troubleshooting.md](troubleshooting.md) — any `DatalensAPIError`, before retrying anything
