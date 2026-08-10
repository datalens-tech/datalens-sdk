from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from datalens_sdk.domain.dashboard_types import KNOWN_DASHBOARD_ITEM_TYPES, ValidationIssue
from datalens_sdk.domain.dashboard_update import DashboardUpdate
from datalens_sdk.domain.dashboard_validate import validate_dashboard
from datalens_sdk.domain.entry_location import EntryLocation, key_from_location, validate_entry_name
from datalens_sdk.domain.navigation import EntryRelation, EntryScope, LinkDirection, Pager, RelationOptions
from datalens_sdk.domain.ports import DashboardOperations
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.artifacts import ArtifactPath, write_dashboard_artifact
from datalens_sdk.serialization.json_types import JsonValue

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _mappings(value: object) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(entry) for entry in _sequence(value) if isinstance(entry, Mapping))


@dataclass(frozen=True, slots=True)
class DashboardItemView:
    """Tolerant read-view over a single dashboard tab item.

    Every item type — including ``neuro_widget`` and types unknown to this SDK
    version — is served by this view; ``raw`` always keeps the original wire
    dict verbatim.
    """

    raw: Mapping[str, object]

    @property
    def id(self) -> str | None:
        return _optional_str(self.raw.get("id"))

    @property
    def item_type(self) -> str | None:
        return _optional_str(self.raw.get("type"))

    @property
    def namespace(self) -> str | None:
        return _optional_str(self.raw.get("namespace"))

    @property
    def data(self) -> Mapping[str, object]:
        return _mapping(self.raw.get("data"))

    @property
    def defaults(self) -> Mapping[str, object]:
        return _mapping(self.raw.get("defaults"))

    @property
    def order_id(self) -> float | None:
        return _optional_number(self.raw.get("orderId"))

    @property
    def default_order_id(self) -> float | None:
        return _optional_number(self.raw.get("defaultOrderId"))

    @property
    def is_known_type(self) -> bool:
        return self.item_type in KNOWN_DASHBOARD_ITEM_TYPES

    @property
    def action_params_enabled(self) -> bool:
        # Read view only; the field is writable on create/update per current API.
        return any(
            tab.get("enableActionParams") is True
            for tab in _sequence(self.data.get("tabs"))
            if isinstance(tab, Mapping)
        )


@dataclass(frozen=True, slots=True)
class ControlSourceView:
    """Tolerant read-view over a selector ``source`` dict."""

    raw: Mapping[str, object]

    @property
    def element_type(self) -> str | None:
        return _optional_str(self.raw.get("elementType"))

    @property
    def dataset_id(self) -> str | None:
        return _optional_str(self.raw.get("datasetId"))

    @property
    def dataset_field_id(self) -> str | None:
        return _optional_str(self.raw.get("datasetFieldId"))

    @property
    def field_type(self) -> str | None:
        return _optional_str(self.raw.get("fieldType"))

    @property
    def param_name(self) -> str | None:
        return _optional_str(self.raw.get("fieldName"))

    @property
    def chart_id(self) -> str | None:
        return _optional_str(self.raw.get("chartId"))

    @property
    def operation(self) -> str | None:
        return _optional_str(self.raw.get("operation"))

    @property
    def multiselect(self) -> bool:
        return self.raw.get("multiselectable") is True

    @property
    def is_range(self) -> bool:
        return self.raw.get("isRange") is True

    @property
    def required(self) -> bool:
        return self.raw.get("required") is True

    @property
    def default_value(self) -> object:
        """The raw wire ``defaultValue`` (unprefixed form), if present."""
        return self.raw.get("defaultValue")

    @property
    def acceptable_values(self) -> tuple[Mapping[str, object], ...]:
        return _mappings(self.raw.get("acceptableValues"))


@dataclass(frozen=True, slots=True)
class ControlMemberView:
    """One selector member normalized out of any control wire format."""

    raw: Mapping[str, object]
    id: str | None
    title: str | None
    source_type: str | None
    source: ControlSourceView
    defaults: Mapping[str, object]

    @property
    def impact_type(self) -> str | None:
        return _optional_str(self.raw.get("impactType"))

    @property
    def impact_tabs_ids(self) -> tuple[str, ...] | None:
        value = self.raw.get("impactTabsIds")
        if value is None:
            return None
        return tuple(entry for entry in _sequence(value) if isinstance(entry, str))

    @property
    def placement_mode(self) -> str | None:
        return _optional_str(self.raw.get("placementMode"))

    @property
    def width(self) -> str | None:
        return _optional_str(self.raw.get("width"))


@dataclass(frozen=True, slots=True)
class ControlView:
    """Read-normalization of the three selector wire formats.

    Serves ``group_control``, standalone ``control``, and tabs-wrapped
    controls as a wrapper plus members.
    """

    item: DashboardItemView

    _GROUP_CONTROL = "group_control"
    _STANDALONE = "standalone_control"
    _TABS = "tabs_control"

    @classmethod
    def from_item(cls, item: DashboardItemView) -> ControlView | None:
        """Wrap a control-ish item; ``None`` for any other item type."""
        return cls(item=item) if item.item_type in ("control", "group_control") else None

    @property
    def id(self) -> str | None:
        """The wrapper item id (NOT a selector identity for group_control)."""
        return self.item.id

    @property
    def wire_format(self) -> str:
        if self.item.item_type == "group_control":
            return self._GROUP_CONTROL
        return self._TABS if "tabs" in self.item.data else self._STANDALONE

    @property
    def members(self) -> tuple[ControlMemberView, ...]:
        data = self.item.data
        if self.wire_format == self._GROUP_CONTROL:
            return tuple(self._member_from_group_entry(entry) for entry in _mappings(data.get("group")))
        if self.wire_format == self._TABS:
            return tuple(self._member_from_tab_entry(entry) for entry in _mappings(data.get("tabs")))
        return (
            ControlMemberView(
                raw=self.item.raw,
                id=self.item.id,
                title=_optional_str(data.get("title")),
                source_type=_optional_str(data.get("sourceType")),
                source=ControlSourceView(raw=_mapping(data.get("source"))),
                defaults=self.item.defaults,
            ),
        )

    def member(self, member_id: str) -> ControlMemberView | None:
        """Resolve a selector by its member id (for standalone controls the
        member id equals the item id)."""
        for entry in self.members:
            if entry.id == member_id:
                return entry
        return None

    @staticmethod
    def _member_from_group_entry(entry: Mapping[str, object]) -> ControlMemberView:
        return ControlMemberView(
            raw=entry,
            id=_optional_str(entry.get("id")),
            title=_optional_str(entry.get("title")),
            source_type=_optional_str(entry.get("sourceType")),
            source=ControlSourceView(raw=_mapping(entry.get("source"))),
            defaults=_mapping(entry.get("defaults")),
        )

    @staticmethod
    def _member_from_tab_entry(entry: Mapping[str, object]) -> ControlMemberView:
        return ControlMemberView(
            raw=entry,
            id=_optional_str(entry.get("id")),
            title=_optional_str(entry.get("title")),
            source_type=_optional_str(entry.get("sourceType")),
            source=ControlSourceView(raw=_mapping(entry.get("source"))),
            defaults=_mapping(entry.get("defaults")),
        )


@dataclass(frozen=True, slots=True)
class DashboardLayoutItemView:
    raw: Mapping[str, object]

    @property
    def item_id(self) -> str | None:
        return _optional_str(self.raw.get("i"))

    @property
    def x(self) -> float | None:
        return _optional_number(self.raw.get("x"))

    @property
    def y(self) -> float | None:
        return _optional_number(self.raw.get("y"))

    @property
    def w(self) -> float | None:
        return _optional_number(self.raw.get("w"))

    @property
    def h(self) -> float | None:
        return _optional_number(self.raw.get("h"))

    @property
    def parent(self) -> str | None:
        return _optional_str(self.raw.get("parent"))


@dataclass(frozen=True, slots=True)
class DashboardTabView:
    raw: Mapping[str, object]

    @property
    def id(self) -> str | None:
        return _optional_str(self.raw.get("id"))

    @property
    def title(self) -> str | None:
        return _optional_str(self.raw.get("title"))

    @property
    def hidden(self) -> bool:
        return self.raw.get("hidden") is True

    @property
    def items(self) -> tuple[DashboardItemView, ...]:
        return tuple(DashboardItemView(raw=entry) for entry in _mappings(self.raw.get("items")))

    @property
    def layout(self) -> tuple[DashboardLayoutItemView, ...]:
        return tuple(DashboardLayoutItemView(raw=entry) for entry in _mappings(self.raw.get("layout")))

    @property
    def connections(self) -> tuple[Mapping[str, object], ...]:
        return _mappings(self.raw.get("connections"))

    @property
    def aliases(self) -> Mapping[str, object]:
        return _mapping(self.raw.get("aliases"))

    @property
    def global_items(self) -> tuple[DashboardItemView, ...]:
        return tuple(DashboardItemView(raw=entry) for entry in _mappings(self.raw.get("globalItems")))

    @property
    def controls(self) -> tuple[ControlView, ...]:
        """Every selector wrapper on this tab (items and globalItems)."""
        views = (ControlView.from_item(item) for item in (*self.items, *self.global_items))
        return tuple(view for view in views if view is not None)

    @property
    def settings(self) -> Mapping[str, object]:
        return _mapping(self.raw.get("settings"))


@dataclass(slots=True)
class Dashboard:
    id: str | None
    name: str | None = None
    installation: str = ""
    location: EntryLocation | None = None
    data: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    response_snapshot: Mapping[str, JsonValue] = field(
        default_factory=dict,
        repr=False,
        compare=False,
        kw_only=True,
    )
    rev_id: str | None = None
    saved_id: str | None = None
    published_id: str | None = None
    workbook_id: str | None = None
    _operations: DashboardOperations | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.name is None:
            self.name = _optional_str(self.raw.get("name"))

    def __getattr__(self, name: str) -> object:
        if name in self.raw:
            return self.raw[name]
        raise AttributeError(name)

    @property
    def key(self) -> str | None:
        return _optional_str(self.raw.get("key")) or key_from_location(self.location, name=self.name)

    @property
    def tabs(self) -> tuple[DashboardTabView, ...]:
        return tuple(DashboardTabView(raw=entry) for entry in _mappings(self.data.get("tabs")))

    @property
    def is_draft(self) -> bool:
        return self.saved_id != self.published_id

    @property
    def update(self) -> DashboardUpdate:
        """Start a raw read-modify-write update over this loaded revision.

        The builder snapshots this object's raw ``data`` verbatim. The server
        has no optimistic locking (last-write-wins): call :meth:`refresh`
        right before ``.update`` and keep the builder short-lived, or
        concurrent edits made after this fetch are silently overwritten.
        """
        if not self.id:
            raise DataLensValidationError("Cannot update a dashboard without an id")
        return DashboardUpdate(dashboard=self, operations=self._operations)

    def to_file(
        self,
        path: ArtifactPath,
        *,
        with_dependencies: bool = False,
    ) -> Path:
        if not with_dependencies:
            return write_dashboard_artifact(
                path,
                self.response_snapshot,
                name=self.name,
                resource_id=self.id,
            )
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.export_dashboard_with_dependencies(self, path)

    def refresh(self) -> Dashboard:
        """Re-read the current default revision of this dashboard.

        The branch/rev_id used to load this object is not remembered: refresh
        never replays it and always returns the API's current revision.
        """
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot refresh a dashboard without an id")
        return self._operations.get_dashboard(self.id, workbook_id=self.workbook_id)

    def validate(self) -> tuple[ValidationIssue, ...]:
        """Collect structural problems without HTTP and without raising.

        Covers duplicate ids, out-of-grid and overlapping items, empty chart
        ids, item/layout coverage, and undersized alias groups; the result is
        empty for a valid (or empty) dashboard. This is the inspection mirror
        of the fail-loud converter validators. For broken cross-entity
        references (missing charts/datasets/fields), use the HTTP recipe
        :func:`~datalens_sdk.recipes.validate_dashboard_refs` instead.
        """
        return validate_dashboard(self.data)

    def publish_revision(self, *, rev_id: str | None = None, lock_token: str | None = None) -> Dashboard:
        """Publish an existing revision without creating a new one.

        ``rev_id=None`` publishes the revision this object was loaded as.
        Server ignores entry.data for this call; to persist changes AND
        publish, use ``.update(...).execute(publish=True)`` instead.
        """
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot publish a dashboard without an id")
        effective_rev_id = rev_id if rev_id is not None else self.rev_id
        if not effective_rev_id:
            raise DataLensValidationError("Cannot publish: no rev_id given and the dashboard carries none")
        return self._operations.publish_dashboard(self, effective_rev_id, lock_token=lock_token)

    def delete(self, lock_token: str | None = None) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a dashboard without an id")
        self._operations.delete_dashboard(self.id, lock_token=lock_token)

    def rename(self, name: str) -> Dashboard:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot rename a dashboard without an id")
        validate_entry_name(name=name, location=self.location)
        return self._operations.rename_dashboard(self, name)

    def get_relations(
        self,
        *,
        include_permissions_info: bool | None = None,
        link_direction: LinkDirection | None = None,
        page_size: int = 100,
        scope: EntryScope | None = None,
    ) -> Pager[EntryRelation]:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot get relations for a dashboard without an id")
        return self._operations.get_entry_relations(
            self.id,
            RelationOptions(
                include_permissions_info=include_permissions_info,
                link_direction=link_direction,
                page_size=page_size,
                scope=scope,
            ),
        )
