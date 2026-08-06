"""Adopt-on-conflict: try to create a dashboard, then adopt an existing entry.

Creates are not idempotent — re-running a create for a name that already
exists in the same location raises ``ConflictError``. Depending on the API
path, its context can contain status 409 or a legacy status 400 with
``ERR.US.DB.UNIQUE_VIOLATION``. This script tries the create, catches the
conflict, finds the existing entry via ``client.navigation.get_entries()``,
and continues with it instead of minting a ``name-2`` copy.

Skill hard rules demonstrated:
  * Rule 7 (no idempotency — adopt on conflict): the whole script is this
    rule as executable code.
  * Rule 4 (validate, don't just create): the returned dashboard is checked
    for an id and validated before the script reports success.
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
import sys

from datalens_sdk import (
    ConflictError,
    DashboardTab,
    DatalensAPIError,
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
    parser.add_argument("--name", required=True, help="Dashboard name (rerun with the same name to see adoption)")
    parser.add_argument("--workbook-id", required=True, help="Workbook the dashboard lives in")
    return parser.parse_args()


def create_or_adopt_dashboard(client, *, name: str, workbook_id: str):
    """Create the dashboard; on a name conflict adopt the existing entry."""
    location = EntryLocation.workbook(workbook_id)
    try:
        created = (
            client.create.dashboard(name=name, location=location)
            .add_tab(DashboardTab("Main").add_title("Placeholder"))
            .build()
        )
        print(f"Created dashboard {created.id!r}")
        return client.get.dashboard(by_id=created.id)
    except ConflictError as e:
        print(
            f"Entry already exists ({e.context.status_code} {e.context.code}, "
            f"request_id={e.context.request_id}); adopting it"
        )
        # Server name= filter narrows; compare exactly on the client.
        for entry in client.navigation.get_entries(scope="dash", name=name):
            display_name = entry.name.rsplit("/", 1)[-1] if entry.name is not None else None
            if display_name == name and entry.workbook_id == workbook_id:
                print(f"Adopted existing dashboard {entry.id!r}")
                return client.get.dashboard(by_id=entry.id)
        raise  # conflict but no match found — report e.context.request_id


def main() -> None:
    args = parse_args()

    try:
        with make_client() as client:
            dashboard = create_or_adopt_dashboard(
                client,
                name=args.name,
                workbook_id=args.workbook_id,
            )

            # Hard rule 4: check the object we ended up with, whichever branch ran.
            if not dashboard.id:
                raise SystemExit("Neither create nor adoption produced a dashboard with an id")
            issues = dashboard.validate()
            if issues:
                for issue in issues:
                    print(f"validation issue: {issue}", file=sys.stderr)
                raise SystemExit("Dashboard exists but failed validation; see issues above")

            print(f"Dashboard id: {dashboard.id}")
            print(f"Dashboard name: {dashboard.name}")
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
