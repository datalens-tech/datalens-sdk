"""Dataset create and update DSL: a two-table join, calculation, and aggregation.

Builds a dataset over two tables of an existing connection. The relation is
declared on the create builder with explicit ``left_source`` and
``right_source`` objects so same-named join columns cannot resolve both sides
to one source. It then applies one chained field update:
``change_field_aggregation`` and ``add_calculation``, persisted by a single
``.execute()``.

Skill hard rules demonstrated:
  * Rule 4 (validate, don't just create): the dataset is re-fetched after
    creation, and the applied relation and calculation are checked on the
    returned object before the script reports success.
  * Rule 5 (edit incrementally): all changes go through get -> update
    builder -> ``.execute()``; nothing is deleted and recreated.
  * Rule 9 (report request_id on API failures).

Required environment variables:
  DATALENS_INSTALLATION   'yc' or 'enterprise'
  DATALENS_BASE_URL       enterprise only: API endpoint
  DATALENS_API_TOKEN      enterprise, optional: OAuth token (read by OAuthAuthProvider)
  DATALENS_YC_ORG_ID      yc, optional: org id for static IAM auth
  DATALENS_YC_IAM_TOKEN   yc, optional: IAM token for static auth (else the yc CLI is used)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
import sys

from datalens_sdk import (
    DatalensAPIError,
    DataLensClientEnterprise,
    DataLensClientYC,
    EntryLocation,
    JoinCondition,
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
    parser.add_argument("--connection-id", required=True, help="Existing ClickHouse connection id")
    parser.add_argument("--workbook-id", required=True, help="Workbook to create the dataset in")
    parser.add_argument("--db-name", required=True, help="Database holding both tables")
    parser.add_argument("--facts-table", required=True, help="Left (facts) table name")
    parser.add_argument("--dim-table", required=True, help="Right (dimension) table name")
    parser.add_argument("--join-column", required=True, help="Source column present on both sides of the join")
    parser.add_argument("--measure-field", required=True, help="Numeric facts field to turn into a SUM measure")
    parser.add_argument(
        "--calc-formula",
        default=None,
        help="Formula for the added calculation; default: SUM([<measure-field>])",
    )
    return parser.parse_args()


def configure_joined_dataset(builder, *, facts, dims, join_column: str):
    """Attach both sources and their unambiguous LEFT relation."""
    return builder.sources([facts, dims]).add_relation(
        type="left",
        conditions=[JoinCondition(left=join_column, right=join_column, operator="eq")],
        left_source=facts,
        right_source=dims,
        drop_duplicates=False,
    )


def main() -> None:
    args = parse_args()

    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    workbook = EntryLocation.workbook(args.workbook_id)
    calc_name = "SDK example calculation"
    formula = args.calc_formula or f"SUM([{args.measure_field}])"

    try:
        with make_client() as client:
            connection = client.get.connection(by_id=args.connection_id)

            factory = client.create.source(using=connection)
            facts = factory.ch_table(alias="facts", db_name=args.db_name, table_name=args.facts_table).build(
                strict=True
            )
            dims = factory.ch_table(alias="dims", db_name=args.db_name, table_name=args.dim_table).build(strict=True)

            dataset = configure_joined_dataset(
                client.create.dataset(name=f"SDK example join {suffix}", location=workbook),
                facts=facts,
                dims=dims,
                join_column=args.join_column,
            ).build()

            # MANDATORY re-get before any field operation: the create response
            # omits field snapshots.
            dataset = client.get.dataset(by_id=dataset.id)

            dataset = (
                dataset.update.change_field_aggregation(field=dataset.fields.by_name(args.measure_field), to="sum")
                .add_calculation(name=calc_name, formula=formula, kind="MEASURE", cast="float")
                .execute()
            )

            # Hard rule 4: verify the applied actions on the returned dataset.
            if not dataset.relations:
                raise SystemExit("Update persisted but no relation is present on the dataset")
            calc = dataset.fields.by_name(calc_name)  # raises with hints on a miss
            measure = dataset.fields.by_name(args.measure_field)
            if measure.aggregation != "sum":
                raise SystemExit(f"Expected aggregation 'sum' on {args.measure_field!r}, got {measure.aggregation!r}")

            print(f"Dataset id: {dataset.id}")
            print(f"Relations: {len(dataset.relations)}")
            print(f"Calculation guid: {calc.guid}")
    except DatalensAPIError as e:
        # Hard rule 9: the request id is what DataLens support needs.
        print(
            f"DataLens API error {e.context.status_code} {e.context.code}: "
            f"{e.context.message} (request_id={e.context.request_id})",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
