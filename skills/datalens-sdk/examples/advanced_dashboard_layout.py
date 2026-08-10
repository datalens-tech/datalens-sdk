"""Advanced dashboard composition over existing dataset and chart ids.

Creates a two-tab dashboard that demonstrates the layout features which are
easy to get wrong when assembling a larger dashboard:

* stable tab and item ids;
* a selector group displayed on, and affecting, every tab;
* independent pinned and scrolling layout flows;
* an internal chart-tab group;
* post-composition ``Layout.row`` / ``Layout.stack`` placement;
* one deliberate selector-to-widget ignore edge;
* offline layout preview plus structural and remote-reference validation.

The example only creates the dashboard. It reuses existing charts and a
dataset so the layout remains the focus.

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
    DashboardChartTab,
    DashboardTab,
    DataLensAPIError,
    DataLensClientEnterprise,
    DataLensClientYC,
    Dataset,
    EntryLocation,
    Layout,
    OAuthAuthProvider,
    StaticYCIAMAuthProvider,
    validate_dashboard_refs,
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
    parser.add_argument("--workbook-id", required=True, help="Workbook to create the dashboard in")
    parser.add_argument("--dataset-id", required=True, help="Dataset used by the shared selectors")
    parser.add_argument("--date-field", required=True, help="Dataset date field title")
    parser.add_argument("--dimension-field", required=True, help="Dataset dimension field title")
    parser.add_argument("--trend-chart-id", required=True, help="Existing chart for the primary trend")
    parser.add_argument("--breakdown-chart-id", required=True, help="Existing chart for the comparison tab")
    parser.add_argument("--detail-chart-id", required=True, help="Existing chart for the detail tab")
    parser.add_argument("--name", default=None, help="Dashboard name (default: timestamped SDK example name)")
    return parser.parse_args()


def build_tabs(
    *,
    dataset: Dataset,
    date_field_name: str,
    dimension_field_name: str,
    trend_chart_id: str,
    breakdown_chart_id: str,
    detail_chart_id: str,
) -> tuple[DashboardTab, DashboardTab]:
    """Compose both tabs without a client or HTTP calls."""
    date_field = dataset.fields.by_name(date_field_name)
    dimension_field = dataset.fields.by_name(dimension_field_name)

    overview = (
        DashboardTab("Overview", tab_id="overview")
        # Pinned content has its own flow and does not consume y=0 in
        # the scrolling layout below.
        .add_title(
            "Executive overview",
            item_id="overview_header",
            show_in_toc=True,
            pinned="fixed",
        )
        # Register selector members first, then assemble one full-width
        # widget. Display and influence are separate cross-tab axes.
        .add_selector(
            group="global_filters",
            item_id="filter_date",
            dataset=dataset,
            field=date_field,
            element="date",
            is_range=True,
            affects="all_tabs",
        )
        .add_selector(
            group="global_filters",
            item_id="filter_dimension",
            dataset=dataset,
            field=dimension_field,
            multiselect=True,
            affects="all_tabs",
        )
        .add_group_selector(
            group="global_filters",
            item_id="global_filters",
            show_on_tabs="all",
            apply_button=True,
            reset_button=True,
        )
        .add_chart(
            trend_chart_id,
            title="Trend",
            item_id="overview_trend",
        )
        .add_chart_group(
            [
                DashboardChartTab(
                    chart=breakdown_chart_id,
                    title="Breakdown",
                    default=True,
                ),
                DashboardChartTab(
                    chart=detail_chart_id,
                    title="Details",
                ),
            ],
            item_id="overview_comparison",
        )
        .add_text(
            "The comparison widget intentionally ignores the dimension selector.",
            item_id="overview_note",
            background=None,
        )
        # Ignore edges subtract from the default broadcast mesh. Both arguments
        # are logical ids: a widget id receives, a selector member id sends.
        .add_connection(
            from_item="overview_comparison",
            to_item="filter_dimension",
        )
    )
    overview.apply_layout(Layout.row("overview_trend", "overview_comparison", y=2, h=14))
    overview.apply_layout(Layout.stack("overview_note", y=16, h=4))

    details = (
        DashboardTab("Details", tab_id="details")
        .add_title(
            "Operational detail",
            item_id="details_header",
            show_in_toc=True,
            pinned="collapsible",
        )
        .add_chart(
            detail_chart_id,
            title="Detailed view",
            item_id="details_chart",
        )
        .add_text(
            "The selector group is defined once on Overview and displayed on all tabs.",
            item_id="details_note",
            background=None,
        )
    )
    details.apply_layout(Layout.stack("details_chart", "details_note", y=0, h=(18, 4)))
    return overview, details


def main() -> None:
    args = parse_args()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = args.name or f"SDK advanced layout {suffix}"

    try:
        with make_client() as client:
            dataset = client.get.dataset(by_id=args.dataset_id)
            overview, details = build_tabs(
                dataset=dataset,
                date_field_name=args.date_field,
                dimension_field_name=args.dimension_field,
                trend_chart_id=args.trend_chart_id,
                breakdown_chart_id=args.breakdown_chart_id,
                detail_chart_id=args.detail_chart_id,
            )

            # Pure local inspection: all explicitly named items appear here,
            # so layout can be reviewed before the create request.
            for tab_name, tab in (("Overview", overview), ("Details", details)):
                print(f"{tab_name} layout:")
                for item_id, position in tab.preview_layout().items():
                    print(f"  {item_id}: {position}")

            dashboard = (
                client.create.dashboard(
                    name=name,
                    location=EntryLocation.workbook(args.workbook_id),
                )
                .add_tab(overview)
                .add_tab(details)
                .description("Advanced dashboard layout created by datalens-sdk")
                .settings(
                    hide_tabs=False,
                    expand_toc=True,
                    load_priority="selectors",
                    max_concurrent_requests=4,
                )
                .build()
            )

            structural_issues = dashboard.validate()
            reference_issues = validate_dashboard_refs(client, dashboard)
            issues = structural_issues + reference_issues
            if issues:
                for issue in issues:
                    print(f"validation issue: {issue}", file=sys.stderr)
                raise SystemExit("Dashboard persisted but failed validation; see issues above")

            print(f"Dashboard id: {dashboard.id}")
    except DataLensAPIError as e:
        print(
            f"DataLens API error {e.context.status_code} {e.context.code}: "
            f"{e.context.message} (request_id={e.context.request_id})",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
