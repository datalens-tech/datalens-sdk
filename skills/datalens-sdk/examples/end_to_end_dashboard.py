"""End-to-end build: ClickHouse connection -> source -> dataset -> chart -> dashboard.

Walks the full entity chain in dependency order and finishes with an offline
dashboard validation instead of trusting a clean ``.build()``.

Skill hard rules demonstrated:
  * Rule 3 (tokens are opaque): all secrets come from the environment; the
    script never prints, logs, or hardcodes them.
  * Rule 4 (validate, don't just create): the dataset is re-fetched with
    ``client.get.dataset`` before field operations, and ``dashboard.validate()``
    must return an empty tuple before the script reports success.
  * Rule 9 (report request_id on API failures): every ``DataLensAPIError``
    is reported with ``e.context.request_id``.

Required environment variables:
  DATALENS_INSTALLATION   'yc' or 'enterprise'
  DATALENS_BASE_URL       enterprise only: API endpoint
  DATALENS_API_TOKEN      enterprise, optional: OAuth token (read by OAuthAuthProvider)
  DATALENS_YC_ORG_ID      yc, optional: org id for static IAM auth
  DATALENS_YC_IAM_TOKEN   yc, optional: IAM token for static auth (else the yc CLI is used)
  CH_USER                 ClickHouse username
  CH_PASSWORD             ClickHouse password (secret: env only, never echoed)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
import sys

from datalens_sdk import (
    DashboardTab,
    DataLensAPIError,
    DataLensClientEnterprise,
    DataLensClientYC,
    EntryLocation,
    OAuthAuthProvider,
    StaticYCIAMAuthProvider,
)


def make_client():
    """Build a DataLens client from the skill's env-var contract."""
    installation = os.environ.get("DATALENS_INSTALLATION", "").strip().lower()
    if installation == "yc":
        org_id = os.environ.get("DATALENS_YC_ORG_ID")
        token = os.environ.get("DATALENS_YC_IAM_TOKEN")
        if org_id and token:
            return DataLensClientYC(auth=StaticYCIAMAuthProvider(org_id=org_id, token=token))
        return DataLensClientYC()  # default auth: the `yc` CLI
    if installation == "enterprise":
        base_url = os.environ["DATALENS_BASE_URL"]
        if os.environ.get("DATALENS_API_TOKEN"):
            return DataLensClientEnterprise(base_url=base_url, auth=OAuthAuthProvider())
        return DataLensClientEnterprise(base_url=base_url)  # default: no auth headers
    raise SystemExit("Set DATALENS_INSTALLATION to 'yc' or 'enterprise'")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workbook-id", required=True, help="Workbook to create everything in")
    parser.add_argument("--ch-host", required=True, help="ClickHouse host")
    parser.add_argument("--ch-port", type=int, default=8443, help="ClickHouse port (default: 8443)")
    parser.add_argument("--db-name", required=True, help="ClickHouse database name")
    parser.add_argument("--table-name", required=True, help="ClickHouse table to bind as the source")
    parser.add_argument("--dimension-field", required=True, help="Field title for the chart X axis and the selector")
    parser.add_argument("--measure-field", required=True, help="Numeric field to turn into a SUM measure")
    return parser.parse_args()


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this example")
    return value


def main() -> None:
    args = parse_args()

    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    workbook = EntryLocation.workbook(args.workbook_id)

    try:
        with make_client() as client:
            connection = (
                client.create.connection.clickhouse(name=f"SDK example ClickHouse {suffix}", location=workbook)
                .host(args.ch_host)
                .port(args.ch_port)
                .db_name(args.db_name)
                .username(required_env("CH_USER"))
                .password(required_env("CH_PASSWORD"))  # secret: env only, never echoed
                .raw_sql_level("off")
                .ssl_ca_verify("on")
                .build()
            )

            source = (
                client.create.source(using=connection)
                .ch_table(alias="facts", db_name=args.db_name, table_name=args.table_name)
                .build(strict=True)  # strict: an empty or invalid schema fails loud, at once
            )
            dataset = (
                client.create.dataset(name=f"SDK example dataset {suffix}", location=workbook).sources([source]).build()
            )

            # MANDATORY re-get: the create response omits field snapshots, so
            # fields.by_name(...) on the create result cannot see the schema.
            dataset = client.get.dataset(by_id=dataset.id)
            dataset = dataset.update.change_field_aggregation(
                field=dataset.fields.by_name(args.measure_field), to="sum"
            ).execute()

            dimension = dataset.fields.by_name(args.dimension_field)
            measure = dataset.fields.by_name(args.measure_field)
            chart = (
                client.create.wizard_chart.column(name=f"SDK example chart {suffix}", location=workbook)
                .dataset(dataset)
                .x([dimension])
                .y([measure])
                .build()
            )

            tab = (
                DashboardTab("Overview")
                .add_selector(item_id="flt_dim", dataset=dataset, field=dimension, multiselect=True)
                .add_chart(chart, item_id="measure_by_dimension_chart", size=(36, 12))
            )
            dashboard = (
                client.create.dashboard(name=f"SDK example dashboard {suffix}", location=workbook)
                .add_tab(tab)
                .description("Created by the datalens-sdk skill example")
                .build()
            )

            # Hard rule 4: a clean .build() confirms persistence, not correctness.
            issues = dashboard.validate()
            if issues:
                for issue in issues:
                    print(f"validation issue: {issue}", file=sys.stderr)
                raise SystemExit("Dashboard persisted but failed validation; see issues above")

            print(f"Connection id: {connection.id}")
            print(f"Dataset id: {dataset.id}")
            print(f"Chart id: {chart.id}")
            print(f"Dashboard id: {dashboard.id}")
    except DataLensAPIError as e:
        # Hard rule 9: the request id is what DataLens support needs.
        print(
            f"DataLens API error {e.context.status_code} {e.context.code}: "
            f"{e.context.message} (request_id={e.context.request_id})",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
