from __future__ import annotations

from typing import Literal

from datalens_sdk.errors import DataLensValidationError

_SemanticGuidKind = Literal["field", "hierarchy"]


class _SemanticGuidRegistry:
    def __init__(self) -> None:
        self._owners: dict[str, tuple[_SemanticGuidKind, str]] = {}

    def register(
        self,
        guid: object,
        *,
        kind: _SemanticGuidKind,
        owner: str,
        allow_existing_same_kind: bool = False,
    ) -> None:
        if not isinstance(guid, str) or not guid:
            raise DataLensValidationError(f"{owner} requires a non-empty semantic GUID.")
        previous = self._owners.get(guid)
        if previous is not None:
            if allow_existing_same_kind and previous[0] == kind:
                return
            raise DataLensValidationError(
                f"Wizard semantic GUID {guid!r} already exists: it is registered by both {previous[1]} and {owner}. "
                "Use a distinct stable GUID for every dataset parameter, chart-local field, and hierarchy."
            )
        self._owners[guid] = (kind, owner)
