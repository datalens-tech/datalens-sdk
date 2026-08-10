from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Protocol, cast

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter._utils import _optional_str
from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.converter.dashboard_items import (
    _CANONICAL_SETTINGS,
    _concrete_layout,
    _is_shared_group,
    _validate_grid,
    _validate_items_layout_bijection,
    _wire_item,
    _wire_layout_entry,
    _wire_tab,
)
from datalens_sdk.converter.raw.dashboard import (
    RawDashboardCreateEntry,
    RawDashboardCreateEnvelope,
    RawDashboardReplaceEntry,
    RawDashboardReplaceEnvelope,
)
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_layout import find_overlaps, layout_entries
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    key_from_location,
    resolve_entry_location_from_api_fields,
    workbook_id_from_location,
)
from datalens_sdk.domain.entry_types import EntryBranch, EntryUpdateMode
from datalens_sdk.domain.ports import DashboardOperations
from datalens_sdk.domain.specs.dashboard import (
    DashboardCreateSpec,
    DashboardUpdateSpec,
    ExternalControlItem,
    GroupControlItem,
    TabSpec,
    WidgetItem,
)
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import DataLensValidationError, translate_invalid_response_error
from datalens_sdk.serialization.artifacts import DashboardSnapshotView
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object

_SCHEME_VERSION = 8
_SALT = "0.13371337"
_ITEM_NAMESPACE_VALUE = "default"

# Required-nullable settings serialize as explicit nulls; the rest of the canon
# is the strict server default set (partial data is rejected with 400 — P006).


class DashboardArgsDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class DashboardReadDTOProtocol(Protocol):
    entry_id: str | None
    key: str | None
    name: str | None
    data: dict[str, object] | None
    rev_id: str | None
    saved_id: str | None
    published_id: str | None
    workbook_id: str | None
    raw: dict[str, object]


class DashboardReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> DashboardReadDTOProtocol: ...


class DashboardGetArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        dashboard_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
        branch: EntryBranch | None = None,
        include_favorite: bool | None = None,
        include_links: bool | None = None,
        include_permissions: bool | None = None,
    ) -> DashboardArgsDTOProtocol: ...


class DashboardDeleteArgsDTOClass(Protocol):
    def __call__(
        self,
        *,
        dashboard_id: str,
        lock_token: str | None = None,
    ) -> DashboardArgsDTOProtocol: ...


class DashboardCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        data: Mapping[str, object],
        meta: Mapping[str, object] | None,
        key: str | None = None,
        name: str | None = None,
        workbook_id: str | None = None,
        annotation: Mapping[str, object] | None = None,
    ) -> DashboardArgsDTOProtocol: ...


class DashboardUpdateDTOClass(Protocol):
    def __call__(
        self,
        *,
        entry_id: str,
        data: Mapping[str, object],
        meta: Mapping[str, object] | None,
        mode: EntryUpdateMode,
        rev_id: str | None = None,
        lock_token: str | None = None,
        annotation: Mapping[str, object] | None = None,
    ) -> DashboardArgsDTOProtocol: ...


class DashboardDtoModule(Protocol):
    DashboardReadDTO: DashboardReadDTOClass
    DashboardGetArgsDTO: DashboardGetArgsDTOClass
    DashboardDeleteArgsDTO: DashboardDeleteArgsDTOClass
    DashboardCreateDTO: DashboardCreateDTOClass
    DashboardUpdateDTO: DashboardUpdateDTOClass


def _dto_module(dto_module: DashboardDtoModule | None) -> DashboardDtoModule:
    return cast(DashboardDtoModule, generated_dto if dto_module is None else dto_module)


def _dict_with_string_keys(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _wire_endpoint_map(spec: DashboardCreateSpec) -> dict[str, set[str]]:
    """Per-tab ids the server accepts as connection endpoints AFTER shared
    propagation: selector member ids, standalone control ids, widget chart-tab
    ids. A shared group's members count as endpoints only on its show_on_tabs
    target tabs — the wire drops the group from its home tab otherwise."""
    all_tab_ids = [tab.id for tab in spec.tabs]
    endpoint_map: dict[str, set[str]] = {tab_id: set() for tab_id in all_tab_ids}
    for tab in spec.tabs:
        for item in tab.items:
            if isinstance(item, WidgetItem):
                endpoint_map[tab.id].update(widget_tab.id for widget_tab in item.tabs)
            elif isinstance(item, GroupControlItem):
                member_ids = {member.id for member in item.members}
                if _is_shared_group(item):
                    targets = all_tab_ids if item.show_on_tabs == "all" else item.show_on_tabs
                    for target_id in targets:
                        endpoint_map[target_id].update(member_ids)
                else:
                    endpoint_map[tab.id].update(member_ids)
            elif isinstance(item, ExternalControlItem):
                endpoint_map[tab.id].add(item.id)
    return endpoint_map


def _validate_tab_wiring(tab: TabSpec, *, endpoint_ids: set[str]) -> None:
    for edge in tab.connections:
        for label, endpoint in (("from", edge.from_id), ("to", edge.to_id)):
            if endpoint not in endpoint_ids:
                raise DataLensValidationError(
                    f"Tab {tab.id!r} connection {label} endpoint {endpoint!r} is not a selector "
                    "member or widget chart-tab on this tab (a shared selector is only "
                    "connectable on its show_on_tabs target tabs)"
                )
    seen_groups: set[frozenset[str]] = set()
    for group in tab.aliases:
        if len(group) < 2 or len(set(group)) != len(group):
            raise DataLensValidationError(f"Tab {tab.id!r} alias group must be >=2 unique fields, got {group!r}")
        if not all(isinstance(entry, str) and entry for entry in group):
            raise DataLensValidationError(f"Tab {tab.id!r} alias fields must be non-empty strings, got {group!r}")
        key = frozenset(group)
        if key in seen_groups:
            raise DataLensValidationError(f"Tab {tab.id!r} carries a duplicate alias group {group!r}")
        seen_groups.add(key)


def _validate_show_on_tabs_targets(spec: DashboardCreateSpec) -> None:
    tab_ids = {tab.id for tab in spec.tabs}
    for tab in spec.tabs:
        for item in tab.items:
            if not isinstance(item, GroupControlItem):
                continue
            scopes: list[tuple[str, object]] = [(item.id, item.show_on_tabs)]
            scopes.extend((member.id, member.affects) for member in item.members)
            for owner_id, value in scopes:
                if isinstance(value, tuple):
                    unknown = sorted(set(value) - tab_ids)
                    if unknown:
                        raise DataLensValidationError(f"Selector {owner_id!r} references unknown tab ids {unknown!r}")


def _wire_tabs_with_shared(spec: DashboardCreateSpec) -> list[dict[str, object]]:
    """Emit wire tabs, propagating shared group_controls into globalItems.

    A shared selector keeps ONE identity: an identical item id (and member
    ids) replicated into ``globalItems`` of every target tab plus a layout
    entry per tab — the live globalItems contract. Copies are deep so tabs
    never share mutable wire dicts.
    """
    wire_tabs = [_wire_tab(tab) for tab in spec.tabs]
    by_id = {cast(str, wire["id"]): wire for wire in wire_tabs}
    for tab in spec.tabs:
        layout_by_item = {entry.i: entry for entry in tab.layout}
        for item in tab.items:
            if not _is_shared_group(item):
                continue
            assert isinstance(item, GroupControlItem)
            targets = (
                [wire_tab_entry.id for wire_tab_entry in spec.tabs]
                if item.show_on_tabs == "all"
                else list(cast("tuple[str, ...]", item.show_on_tabs))
            )
            item_wire = _wire_item(tab, item)
            layout_wire = _wire_layout_entry(_concrete_layout(layout_by_item[item.id], tab.id))
            for target_id in targets:
                target = by_id[target_id]
                global_items = cast("list[object]", target.setdefault("globalItems", []))
                global_items.append(json.loads(json.dumps(item_wire)))
                cast("list[object]", target["layout"]).append(dict(layout_wire))
    return wire_tabs


def _validate_no_overlaps(wire_tabs: list[dict[str, object]]) -> None:
    """Reject overlapping items in the EFFECTIVE per-tab layout.

    Runs on the wired tabs (after shared group_controls are propagated into
    ``globalItems``), so it catches a shared selector that overlaps a native
    item only on a target tab — invisible to the pre-wire per-item validators.
    Overlap is compared within pin-groups; the DataLens renderer hides overlaps
    visually, so a screenshot cannot substitute for this check.
    """
    for tab in wire_tabs:
        entries, _ = layout_entries(cast("list[object]", tab.get("layout") or []))
        overlaps = find_overlaps(entries)
        if overlaps:
            first, second = overlaps[0]
            raise DataLensValidationError(f"Tab {tab.get('id')!r}: items {first!r} and {second!r} overlap")


def _merged_settings(spec: DashboardCreateSpec) -> dict[str, object]:
    settings = dict(_CANONICAL_SETTINGS)
    # the canon template is a module constant: nested mutables must not be
    # shared between independent conversions
    settings["globalParams"] = {}
    user_set: dict[str, object | None] = {
        "silentLoading": spec.settings.silent_loading,
        "dependentSelectors": spec.settings.dependent_selectors,
        "expandTOC": spec.settings.expand_toc,
        "hideDashTitle": spec.settings.hide_dash_title,
        "hideTabs": spec.settings.hide_tabs,
        "autoupdateInterval": spec.settings.autoupdate_interval,
        "maxConcurrentRequests": spec.settings.max_concurrent_requests,
        "loadPriority": spec.settings.load_priority,
    }
    for key, value in user_set.items():
        if value is not None:
            settings[key] = value
    return settings


def _validate_unique_ids(spec: DashboardCreateSpec) -> None:
    seen_tabs: set[str] = set()
    seen_items: set[str] = set()
    seen_widget_tabs: set[str] = set()
    for tab in spec.tabs:
        if tab.id in seen_tabs:
            raise DataLensValidationError(f"Duplicate tab id {tab.id!r}")
        seen_tabs.add(tab.id)
        for item in tab.items:
            item_id = item.id
            if item_id in seen_items:
                raise DataLensValidationError(f"Duplicate item id {item_id!r}")
            seen_items.add(item_id)
            if isinstance(item, WidgetItem):
                for chart_tab in item.tabs:
                    if chart_tab.id in seen_widget_tabs:
                        raise DataLensValidationError(f"Duplicate widget tab id {chart_tab.id!r}")
                    seen_widget_tabs.add(chart_tab.id)
            if isinstance(item, GroupControlItem):
                # member ids share the item namespace: they are connection
                # endpoints and update-addressing targets (epic D4 identity)
                for member in item.members:
                    if member.id in seen_items:
                        raise DataLensValidationError(f"Duplicate item id {member.id!r}")
                    seen_items.add(member.id)


class DashboardConverter:
    @staticmethod
    def from_domain_create(
        spec: DashboardCreateSpec,
        *,
        dto_module: DashboardDtoModule | None = None,
    ) -> DashboardArgsDTOProtocol:
        generated = _dto_module(dto_module)
        _validate_unique_ids(spec)
        # show_on_tabs targets must be valid BEFORE the endpoint map keys off them
        _validate_show_on_tabs_targets(spec)
        endpoint_map = _wire_endpoint_map(spec)
        for tab in spec.tabs:
            _validate_grid(tab)
            _validate_items_layout_bijection(tab)
            _validate_tab_wiring(tab, endpoint_ids=endpoint_map[tab.id])

        wire_tabs = _wire_tabs_with_shared(spec)
        _validate_no_overlaps(wire_tabs)
        data: dict[str, object] = {
            "schemeVersion": _SCHEME_VERSION,
            "salt": _SALT,
            "counter": max(1, spec.generated_id_count),
            "settings": _merged_settings(spec),
            "tabs": wire_tabs,
        }
        if spec.description is not None:
            data["description"] = spec.description
        if spec.access_description is not None:
            data["accessDescription"] = spec.access_description
        if spec.support_description is not None:
            data["supportDescription"] = spec.support_description

        key = key_from_location(spec.location, name=spec.name)
        return generated.DashboardCreateDTO(
            data=data,
            meta=spec.meta,
            key=key,
            name=None if key else spec.name,
            workbook_id=workbook_id_from_location(spec.location),
        )

    @staticmethod
    def from_domain_update(
        spec: DashboardUpdateSpec,
        *,
        publish: bool,
        lock_token: str | None = None,
        dto_module: DashboardDtoModule | None = None,
    ) -> DashboardArgsDTOProtocol:
        """One-phase update: publish WITHOUT revId persists entry.data."""
        generated = _dto_module(dto_module)
        data = _apply_update(spec)
        return generated.DashboardUpdateDTO(
            entry_id=spec.dashboard_id,
            data=data,
            meta=spec.meta,
            mode="publish" if publish else "save",
            lock_token=lock_token,
            annotation=spec.annotation,
        )

    @staticmethod
    def from_raw_create(spec: RawCreateSpec) -> RawDashboardCreateEnvelope:
        source = DashboardSnapshotView.from_raw(spec.response_snapshot)
        key = key_from_location(spec.location, name=spec.name)
        return RawDashboardCreateEnvelope(
            entry=RawDashboardCreateEntry(
                data=source.data,
                meta=source.optional_object("meta"),
                key=key,
                name=None if key else spec.name,
                workbook_id=workbook_id_from_location(spec.location),
                annotation=source.optional_object("annotation"),
            )
        )

    @staticmethod
    def from_raw_replace(
        spec: RawReplaceSpec,
        *,
        publish: bool,
        lock_token: str | None = None,
    ) -> RawDashboardReplaceEnvelope:
        source = DashboardSnapshotView.from_raw(spec.response_snapshot)
        return RawDashboardReplaceEnvelope(
            entry=RawDashboardReplaceEntry(
                entry_id=spec.target_id,
                data=source.data,
                meta=source.optional_object("meta"),
                annotation=source.optional_object("annotation"),
            ),
            mode="publish" if publish else "save",
            lock_token=lock_token,
        )

    @staticmethod
    def from_domain_publish_revision(
        dashboard_id: str,
        *,
        data: Mapping[str, object],
        meta: Mapping[str, object] | None,
        annotation: Mapping[str, object] | None,
        rev_id: str,
        lock_token: str | None = None,
        dto_module: DashboardDtoModule | None = None,
    ) -> DashboardArgsDTOProtocol:
        """Publish an EXISTING revision: mode=publish + revId.

        The spec requires entry.data, but the server ignores it for this call
        (no new revision is created; the given revision is published).
        """
        generated = _dto_module(dto_module)
        if not rev_id:
            raise DataLensValidationError("rev_id must be a non-empty string")
        return generated.DashboardUpdateDTO(
            entry_id=dashboard_id,
            data=data,
            meta=meta,
            mode="publish",
            rev_id=rev_id,
            lock_token=lock_token,
            annotation=annotation,
        )

    @staticmethod
    def from_domain_get(
        dashboard_id: str,
        *,
        workbook_id: str | None = None,
        branch: EntryBranch | None = None,
        rev_id: str | None = None,
        include_favorite: bool | None = None,
        include_links: bool | None = None,
        include_permissions: bool | None = None,
        dto_module: DashboardDtoModule | None = None,
    ) -> DashboardArgsDTOProtocol:
        generated = _dto_module(dto_module)
        # An explicit rev_id already pins the revision: branch must not be sent with it.
        # The user-facing warning for the combination is emitted at the GetNamespace boundary.
        effective_branch = None if rev_id is not None else branch
        return generated.DashboardGetArgsDTO(
            dashboard_id=dashboard_id,
            workbook_id=workbook_id,
            rev_id=rev_id,
            branch=effective_branch,
            include_favorite=include_favorite,
            include_links=include_links,
            include_permissions=include_permissions,
        )

    @staticmethod
    def from_domain_delete(
        dashboard_id: str,
        *,
        lock_token: str | None = None,
        dto_module: DashboardDtoModule | None = None,
    ) -> DashboardArgsDTOProtocol:
        generated = _dto_module(dto_module)
        return generated.DashboardDeleteArgsDTO(dashboard_id=dashboard_id, lock_token=lock_token)

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | DashboardReadDTOProtocol,
        *,
        installation: str,
        operations: DashboardOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        operation: str = "getDashboard",
        dto_module: DashboardDtoModule | None = None,
    ) -> Dashboard:
        generated = _dto_module(dto_module)
        response_snapshot: dict[str, JsonValue] = {}
        entry_raw: Mapping[str, object]
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="Dashboard API response")
            entry_value = response_snapshot.get("entry")
            if entry_value is not None:
                if not isinstance(entry_value, dict):
                    raise translate_invalid_response_error(operation=operation, reason="entry is not an object")
                unwrapped = entry_value
            else:
                unwrapped = response_snapshot
            dto_validation_input = dict(unwrapped)
            dto_validation_input["raw"] = normalize_json_object(
                unwrapped,
                context="Dashboard typed response state",
            )
            read_dto = generated.DashboardReadDTO.model_validate(dto_validation_input)
            entry_raw = normalize_json_object(
                unwrapped,
                context="Dashboard typed response state",
            )
        else:
            read_dto = raw
            entry_raw = read_dto.raw or {}
        # GetDashboardV1Result requires entry; DashboardV1 requires entryId and data.
        # Unknown fields and item types stay tolerant, but identity must come from
        # the canonical wire field, checked against the raw payload: the DTO's
        # populate_by_name would also accept a pythonic entry_id, and a generic
        # id fallback would let a malformed 200 masquerade as a loaded dashboard.
        entry_id = read_dto.entry_id if isinstance(entry_raw.get("entryId"), str) else None
        if entry_id is None:
            raise translate_invalid_response_error(operation=operation, reason="entry is missing a dashboard id")
        if read_dto.data is None and not isinstance(entry_raw.get("data"), Mapping):
            raise translate_invalid_response_error(operation=operation, reason="entry is missing dashboard data")
        key = read_dto.key or _optional_str(entry_raw.get("key"))
        domain_location = resolve_entry_location_from_api_fields(
            dir_path=_optional_str(entry_raw.get("dir_path")),
            key=key,
            collection_id=_optional_str(entry_raw.get("collection_id")) or _optional_str(entry_raw.get("collectionId")),
            workbook_id=read_dto.workbook_id,
            fallback=location,
        )
        raw_data = read_dto.data
        if raw_data is None:
            raw_data = _dict_with_string_keys(entry_raw.get("data"))
        return Dashboard(
            id=entry_id,
            name=read_dto.name or _optional_str(entry_raw.get("name")) or name_from_key(key) or name,
            installation=installation,
            location=domain_location,
            data=raw_data,
            raw=entry_raw,
            response_snapshot=response_snapshot,
            rev_id=read_dto.rev_id,
            saved_id=read_dto.saved_id,
            published_id=read_dto.published_id,
            workbook_id=read_dto.workbook_id,
            _operations=operations,
        )
