from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from datalens_sdk.errors import DataLensValidationError


@dataclass(frozen=True, slots=True)
class EntryRevision:
    """Revision metadata; saved and published flags are independent server values."""

    rev_id: str
    updated_at: str
    updated_by: str
    is_saved: bool
    is_published: bool


@dataclass(frozen=True, slots=True)
class EntryRevisionsOptions:
    page_size: int = 200
    page_token: str | None = None
    rev_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.page_size, bool) or not isinstance(self.page_size, int) or not 1 <= self.page_size <= 200:
            raise DataLensValidationError("page_size must be an integer between 1 and 200")
        if self.page_token is not None and not isinstance(self.page_token, str):
            raise DataLensValidationError("page_token must be a string or None")
        if self.rev_ids is not None and (
            not isinstance(self.rev_ids, tuple)
            or not 1 <= len(self.rev_ids) <= 1000
            or not all(isinstance(rev_id, str) for rev_id in self.rev_ids)
        ):
            raise DataLensValidationError("rev_ids must contain between 1 and 1000 strings")

    @classmethod
    def create(
        cls,
        *,
        page_size: int = 200,
        page_token: str | None = None,
        rev_ids: Sequence[str] | None = None,
    ) -> EntryRevisionsOptions:
        if rev_ids is not None and (isinstance(rev_ids, (str, bytes)) or not isinstance(rev_ids, Sequence)):
            raise DataLensValidationError("rev_ids must be a sequence of strings, not a single string")
        return cls(
            page_size=page_size,
            page_token=page_token,
            rev_ids=None if rev_ids is None else tuple(rev_ids),
        )
