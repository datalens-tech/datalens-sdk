"""Serialization roundtrip: export a dataset to files, import it into another workbook.

Fetches a dataset (only ``client.get.*`` results carry a complete
``response_snapshot``), writes it with ``dataset.to_file(parent)`` — which
creates a ``<name> [<id>]`` artifact directory — and clones it into a target
workbook via ``client.raw.create.dataset.from_file(...).build()``. Note the
import asymmetry: no id remapping happens, so the clone keeps referencing the
original connection id.

Skill hard rules demonstrated:
  * Rule 4 (validate, don't just create): the clone is re-fetched by its new
    id and its field count is compared against the source before the script
    reports success.
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
import os
from pathlib import Path
import sys

from datalens_sdk import (
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
    parser.add_argument("--dataset-id", required=True, help="Dataset to export and clone")
    parser.add_argument("--target-workbook-id", required=True, help="Workbook to import the clone into")
    parser.add_argument(
        "--export-dir",
        default="artifacts",
        help="Parent directory for the exported artifact (default: ./artifacts)",
    )
    parser.add_argument("--new-name", default=None, help="Name for the clone (default: '<source name> clone')")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    export_parent = Path(args.export_dir)
    export_parent.mkdir(parents=True, exist_ok=True)  # to_file requires an existing parent

    try:
        with make_client() as client:
            # Only a get result carries a snapshot complete enough to export.
            source = client.get.dataset(by_id=args.dataset_id)

            # to_file never overwrites: an existing '<name> [<id>]' directory
            # under the parent raises DataLensValidationError.
            artifact = source.to_file(export_parent)
            print(f"Exported artifact: {artifact}")

            clone = client.raw.create.dataset.from_file(
                artifact,  # the artifact directory, not the JSON inside it
                name=args.new_name or f"{source.name} clone",
                location=EntryLocation.workbook(args.target_workbook_id),
            ).build()

            # Hard rule 4: re-fetch the clone and check what matters.
            check = client.get.dataset(by_id=clone.id)
            if len(check.fields) != len(source.fields):
                raise SystemExit(f"Clone persisted but has {len(check.fields)} fields, source has {len(source.fields)}")

            print(f"Source dataset id: {source.id}")
            print(f"Clone dataset id: {clone.id}")
            print("Note: raw import does not remap ids — the clone still references the original connection id.")
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
