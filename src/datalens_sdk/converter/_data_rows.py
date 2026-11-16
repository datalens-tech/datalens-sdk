from collections.abc import Sequence

from datalens_sdk.serialization.json_types import JsonValue, normalize_json_value


def normalize_data_rows(rows: Sequence[Sequence[object]], *, context: str) -> tuple[tuple[JsonValue, ...], ...]:
    """Copy JSON cells while retaining row order and each row's original width."""
    return tuple(
        tuple(
            normalize_json_value(cell, context=f"{context} row {row_index} column {column_index}")
            for column_index, cell in enumerate(row)
        )
        for row_index, row in enumerate(rows)
    )
