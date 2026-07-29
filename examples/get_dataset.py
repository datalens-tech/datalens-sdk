"""Load a DataLens dataset and print its basic metadata.

Required environment variables:
  DL_DATASET_ID

DataLensClientYC uses the active yc CLI profile for authentication.
"""

from __future__ import annotations

import argparse
import os

from datalens_sdk import DataLensClientYC


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this example")
    return value


def parse_args() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()


def main() -> None:
    parse_args()
    dataset_id = required_env("DL_DATASET_ID")

    with DataLensClientYC() as client:
        dataset = client.get.dataset(by_id=dataset_id)

    print(f"id={dataset.id!r}")
    print(f"name={dataset.name!r}")
    print(f"description={dataset.description!r}")
    print(f"location={dataset.location!r}")
    print(f"fields={len(dataset.fields)}")


if __name__ == "__main__":
    main()
