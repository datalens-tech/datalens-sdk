from __future__ import annotations

from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.errors import DataLensValidationError


class _PublishUnset:
    __slots__ = ()


PUBLISH_UNSET = _PublishUnset()


def resolve_dashboard_publish(*, mode: EntryUpdateMode | None, publish: bool | _PublishUnset) -> bool:
    if isinstance(publish, _PublishUnset):
        if mode is None:
            raise TypeError("execute() requires .mode('save'|'publish') or the publish keyword argument")
        return mode == "publish"
    if not isinstance(publish, bool):
        raise DataLensValidationError("publish must be a bool")
    if mode is not None and (mode == "publish") != publish:
        raise DataLensValidationError("publish conflicts with the mode selected on the builder")
    return publish
