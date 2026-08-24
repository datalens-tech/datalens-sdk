from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, TypeAdapter

from datalens_sdk.converter.dashboard_contract import DashboardGeneratedContract


class _FloatLayoutDTO(BaseModel):
    model_config = ConfigDict(strict=True)

    i: str
    x: float
    y: float
    w: float
    h: float


class _FloatTabDTO(BaseModel):
    model_config = ConfigDict(strict=True)

    layout: list[_FloatLayoutDTO]


def _contract() -> DashboardGeneratedContract:
    mapping = cast("TypeAdapter[object]", TypeAdapter(dict[str, object]))
    return DashboardGeneratedContract(
        tab=TypeAdapter(_FloatTabDTO),
        item=mapping,
        layout=TypeAdapter(_FloatLayoutDTO),
        connection=mapping,
        aliases=mapping,
    )


def test_integral_float_layout_fragments_return_to_integer_grid() -> None:
    contract = _contract()
    entry = {"i": "item", "x": 0, "y": 6, "w": 12, "h": 6}

    serialized_entry = contract.serialize_layout(entry)
    serialized_tab = contract.serialize_tab({"layout": [entry]})

    assert serialized_entry == entry
    assert serialized_tab["layout"] == [entry]
    assert all(isinstance(serialized_entry[key], int) for key in ("x", "y", "w", "h"))
