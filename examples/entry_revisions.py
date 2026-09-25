"""Print a DataLens dataset's revision history and optionally read one revision.

Example:
  python examples/entry_revisions.py dataset-id --page-size 100
  python examples/entry_revisions.py dataset-id --rev-id revision-id --read-revision revision-id

DataLensClientYC uses the active yc CLI profile for authentication.
Running this example prints revision metadata and, when requested, the selected
revision's dataset name and description.
"""

from __future__ import annotations

import argparse

from datalens_sdk import DataLensClientYC


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset_id", help="Dataset whose revision history to read")
    parser.add_argument("--page-size", type=int, default=200, help="Revisions per page (1-200; default: 200)")
    parser.add_argument("--page-token", help="Opaque continuation token from an earlier page")
    parser.add_argument("--rev-id", action="append", dest="rev_ids", help="Filter by revision id; may be repeated")
    parser.add_argument("--read-revision", help="Also read this revision using the ordinary dataset getter")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with DataLensClientYC() as client:
        dataset = client.get.dataset(by_id=args.dataset_id)
        revisions = dataset.get_revisions(
            page_size=args.page_size,
            page_token=args.page_token,
            rev_ids=args.rev_ids,
        )
        # The pager is lazy: HTTP starts when pages() is iterated.
        for page in revisions.pages():
            for revision in page.items:
                print(
                    f"rev_id={revision.rev_id!r} updated_at={revision.updated_at!r} "
                    f"updated_by={revision.updated_by!r} "
                    f"is_saved={revision.is_saved} is_published={revision.is_published}"
                )
            print(f"next_page_token={page.next_page_token!r}")

        if args.read_revision is not None:
            historical = client.get.dataset(by_id=args.dataset_id, rev_id=args.read_revision)
            print(f"historical_rev_id={historical.rev_id!r}")
            print(f"historical_name={historical.name!r}")
            print(f"historical_description={historical.description!r}")


if __name__ == "__main__":
    main()
