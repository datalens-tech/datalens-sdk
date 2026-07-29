"""Create, update, and read a collection and workbook.

DataLensClientYC uses the active yc CLI profile for authentication.

Required environment variables:
  DL_PARENT_COLLECTION_ID
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os

from datalens_sdk import DataLensClientYC, EntryLocation


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this example")
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
    parent_collection = EntryLocation.collection(required_env("DL_PARENT_COLLECTION_ID"))

    with DataLensClientYC() as client:
        collection = (
            client.create.collection(name=f"SDK example collection {suffix}", parent=parent_collection)
            .description("Created by the DataLens SDK example")
            .build()
        )

        workbook = (
            client.create.workbook(name=f"SDK example workbook {suffix}", collection=collection)
            .description("Created by the DataLens SDK example")
            .build()
        )

        collection = collection.rename(f"SDK example collection renamed {suffix}")
        collection = collection.update.description("Updated by the DataLens SDK example").execute()
        workbook = workbook.rename(f"SDK example workbook renamed {suffix}")
        workbook = workbook.update.description("Updated by the DataLens SDK example").execute()

        collection = client.get.collection(by_id=require_id(collection.id, resource="collection"))
        workbook = client.get.workbook(by_id=require_id(workbook.id, resource="workbook"))
        print(f"Collection: id={collection.id!r}, name={collection.name!r}")
        print(f"Workbook: id={workbook.id!r}, name={workbook.name!r}")


if __name__ == "__main__":
    main()
