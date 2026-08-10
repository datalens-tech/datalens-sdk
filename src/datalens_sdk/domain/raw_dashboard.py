from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from datalens_sdk.domain.entry_location import EntryLocation, resolve_entry_location, validate_entry_name
from datalens_sdk.domain.ports import DashboardOperations
from datalens_sdk.domain.raw_resource import _validate_target_installation
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.artifacts import DashboardSnapshotView
from datalens_sdk.serialization.json_types import JsonValue

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard import Dashboard


class RawDashboardCreate:
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        name: str,
        location: EntryLocation,
        installation: str,
        operations: DashboardOperations | None,
    ) -> None:
        resolved_location = resolve_entry_location(
            location=location,
            installation=installation,
            allowed_kinds={"path", "workbook"},
            context="Dashboard creation",
        )
        validate_entry_name(name=name, location=resolved_location)
        self._spec = RawCreateSpec(
            response_snapshot=DashboardSnapshotView.capture(response_snapshot),
            name=name,
            location=resolved_location,
        )
        self._operations = operations

    def build(self) -> Dashboard:
        if self._operations is None:
            raise DataLensConfigurationError("Object is not bound to client operations. Use a client namespace.")
        return self._operations.create_dashboard_from_raw(self._spec)


class RawDashboardReplace:
    def __init__(
        self,
        *,
        response_snapshot: Mapping[str, JsonValue],
        target: Dashboard,
        installation: str,
        operations: DashboardOperations | None,
    ) -> None:
        _validate_target_installation(
            resource="dashboard",
            target_installation=target.installation,
            client_installation=installation,
        )
        if not target.id:
            raise DataLensValidationError("Cannot replace a dashboard without an id")
        self._spec = RawReplaceSpec(
            response_snapshot=DashboardSnapshotView.capture(response_snapshot),
            target_id=target.id,
            target_name=target.name,
            target_location=target.location,
        )
        self._operations = operations

    def execute(
        self,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> Dashboard:
        if self._operations is None:
            raise DataLensConfigurationError("Object is not bound to client operations. Use a client namespace.")
        return self._operations.replace_dashboard_from_raw(
            self._spec,
            publish=publish,
            lock_token=lock_token,
        )
