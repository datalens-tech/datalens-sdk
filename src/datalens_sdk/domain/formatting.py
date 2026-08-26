from __future__ import annotations

from typing import Literal

from typing_extensions import TypedDict

__all__ = ["MeasureFormat"]


class MeasureFormat(TypedDict, total=False):
    format: Literal["number", "percent"]
    precision: int
    unit: Literal["auto", "k", "m", "b", "t"]
    prefix: str
    postfix: str
    show_rank_delimiter: bool
