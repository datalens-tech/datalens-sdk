"""Adopt-on-conflict in either a workbook or a folder.

Creates are not idempotent: re-running a create for a name that already
exists in the same container raises ``ConflictError``. Depending on the API
path, its context can contain status 409 or a legacy status 400 with
``ERR.US.DB.UNIQUE_VIOLATION``. This script searches the original workbook or
folder, requires exactly one exact match, and continues with it instead of
minting a ``name-2`` copy.

Skill hard rules demonstrated:
  * Rule 7 (names are filters, not identities): recovery is container-scoped
    and fails closed on zero or multiple exact matches.
  * Rule 4 (validate, don't just create): the returned dashboard is checked
    for an id and validated before the script reports success.
  * Rule 9 (report request_id on API failures).

Required environment variables:
  DATALENS_INSTALLATION   'yc' or 'enterprise'
  DATALENS_BASE_URL       enterprise only: API endpoint
  DATALENS_OAUTH_TOKEN    enterprise, optional: OAuth token (read by OAuthAuthProvider)
  DATALENS_ORG_ID         yc, optional: org id for static IAM auth
  DATALENS_IAM_TOKEN      yc, optional: IAM token for static auth (else the yc CLI is used)
"""

from __future__ import annotations

import argparse
import os
import sys

from datalens_sdk import (
    ConflictError,
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
        org_id = os.environ.get("DATALENS_ORG_ID")
        token = os.environ.get("DATALENS_IAM_TOKEN")
        if org_id and token:
            return DataLensClientYC(auth=StaticYCIAMAuthProvider(org_id=org_id, token=token))
        return DataLensClientYC()  # default auth: the `yc` CLI
    if installation == "enterprise":
        base_url = os.environ["DATALENS_BASE_URL"]
        if os.environ.get("DATALENS_OAUTH_TOKEN"):
            return DataLensClientEnterprise(base_url=base_url, auth=OAuthAuthProvider())
        return DataLensClientEnterprise(base_url=base_url)  # default: no auth headers
    raise SystemExit("Set DATALENS_INSTALLATION to 'yc' or 'enterprise'")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="Dashboard name (rerun with the same name to see adoption)")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--workbook-id", help="Workbook the dashboard lives in")
    destination.add_argument("--folder-path", help="Folder path the dashboard lives in")
    return parser.parse_args()


def create_or_adopt_dashboard(
    client,
    *,
    name: str,
    workbook_id: str | None,
    folder_path: str | None,
):
    """Create the dashboard; on conflict adopt one exact match in its container."""
    if workbook_id is not None:
        location = EntryLocation.workbook(workbook_id)
        container = client.get.workbook(by_id=workbook_id)
        container_label = f"workbook {workbook_id!r}"
    elif folder_path is not None:
        location = EntryLocation.path(folder_path)
        container = client.get.folder(by_path=folder_path)
        container_label = f"folder {folder_path!r}"
    else:
        raise ValueError("Pass a workbook id or folder path")

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
            f"request_id={e.context.request_id}); checking {container_label}"
        )
        summaries = [
            entry
            for entry in container.list_entries(scope="dash", name=name)
            if entry.name is not None and entry.name.rsplit("/", 1)[-1] == name
        ]
        verified = []
        for summary in summaries:
            candidate = client.get.dashboard(by_id=summary.id, workbook_id=workbook_id)
            tabs = candidate.tabs
            has_expected_seed = (
                candidate.name == name
                and len(tabs) == 1
                and tabs[0].title == "Main"
                and any(item.item_type == "title" and item.data.get("text") == "Placeholder" for item in tabs[0].items)
                and not candidate.validate()
            )
            if has_expected_seed:
                verified.append(candidate)

        if len(verified) != 1:
            candidate_ids = [entry.id for entry in summaries]
            raise LookupError(
                f"Expected one fully verified dashboard named {name!r} in {container_label}, "
                f"found {len(verified)}; container candidates: {candidate_ids}"
            ) from e
        print(f"Adopted existing dashboard {verified[0].id!r}")
        return verified[0]


def main() -> None:
    args = parse_args()

    try:
        with make_client() as client:
            dashboard = create_or_adopt_dashboard(
                client,
                name=args.name,
                workbook_id=args.workbook_id,
                folder_path=args.folder_path,
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
