"""Create a ClickHouse connection, dataset, chart, and dashboard.

DataLensClientYC uses the active yc CLI profile for authentication.

Required environment variables:
  DL_WORKBOOK_ID
  DL_CH_HOST
  DL_CH_DATABASE
  DL_CH_USER
  DL_CH_PASSWORD
  DL_CH_TABLE
  DL_CH_DIMENSION_FIELD
  DL_CH_MEASURE_FIELD    Numeric field to change to a SUM measure.

Optional environment variables:
  DL_CH_PORT            Default: 8443
  DL_CH_SECURE          Default: on
  DL_CH_SSL_CA_VERIFY   Default: on
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os

from datalens_sdk import DashboardTab, DataLensClientYC, EntryLocation


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this example")
    return value


def int_env(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc


def on_off_env(name: str, *, default: str) -> str:
    value = os.environ.get(name, default).strip().lower()
    if value not in {"on", "off"}:
        raise SystemExit(f"{name} must be 'on' or 'off'")
    return value


def require_id(value: str | None, *, resource: str) -> str:
    if not value:
        raise RuntimeError(f"The created {resource} did not contain an id")
    return value


def parse_args() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()


def main() -> None:
    parse_args()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    workbook = EntryLocation.workbook(required_env("DL_WORKBOOK_ID"))
    database = required_env("DL_CH_DATABASE")

    with DataLensClientYC() as client:
        connection = (
            client.create.connection.clickhouse(name=f"SDK example ClickHouse {suffix}", location=workbook)
            .host(required_env("DL_CH_HOST"))
            .port(int_env("DL_CH_PORT", default=8443))
            .db_name(database)
            .username(required_env("DL_CH_USER"))
            .password(required_env("DL_CH_PASSWORD"))
            .raw_sql_level("off")
            .secure(on_off_env("DL_CH_SECURE", default="on"))
            .ssl_ca_verify(on_off_env("DL_CH_SSL_CA_VERIFY", default="on"))
            .build()
        )

        source = (
            client.create.source(using=connection)
            .ch_table(alias="source", db_name=database, table_name=required_env("DL_CH_TABLE"))
            .build(strict=True)
        )
        dataset = (
            client.create.dataset(name=f"SDK example dataset {suffix}", location=workbook).sources([source]).build()
        )

        dataset = client.get.dataset(by_id=require_id(dataset.id, resource="dataset"))
        numeric_field = dataset.fields.by_name(required_env("DL_CH_MEASURE_FIELD"))
        dataset = dataset.update.change_field_aggregation(field=numeric_field, to="sum").execute()

        dimension = dataset.fields.by_name(required_env("DL_CH_DIMENSION_FIELD"))
        measure = dataset.fields.by_name(required_env("DL_CH_MEASURE_FIELD"))
        chart = (
            client.create.wizard_chart.flat_table(name=f"SDK example chart {suffix}", location=workbook)
            .dataset(dataset)
            .columns([dimension, measure])
            .build()
        )

        tab = DashboardTab("Overview").add_chart(chart, item_id="table", size=(36, 12))
        dashboard = (
            client.create.dashboard(name=f"SDK example dashboard {suffix}", location=workbook)
            .add_tab(tab)
            .description("Created by the DataLens SDK example")
            .build()
        )

        print(f"Connection id: {connection.id}")
        print(f"Dataset id: {dataset.id}")
        print(f"Chart id: {chart.id}")
        print(f"Dashboard id: {dashboard.id}")


if __name__ == "__main__":
    main()
