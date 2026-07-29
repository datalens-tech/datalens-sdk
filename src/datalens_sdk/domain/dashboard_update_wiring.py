"""Connection/alias adders of the dashboard update builder (epic D4).

Mirrors the tab-entity wiring surface on :class:`DashboardUpdate`: logical
item references are translated into wire endpoints through the shadow index
(the server only accepts selector member ids and widget chart-tab ids —
anything else is HTTP 500, probe P019). Dedup considers edges and alias
groups ALREADY present in the raw snapshot, not only ones added by this
builder; re-adding after an earlier remove op in the same builder is allowed
and clears the removed-shadow entry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast, get_args

from typing_extensions import Self

from datalens_sdk.domain.dashboard_types import (
    DateInterval,
    RelativeDateInterval,
    SelectorDefaultValue,
    SelectorOperation,
)
from datalens_sdk.domain.dashboard_update_support import (
    _iter_mappings,
    _iter_mappings_or_lists,
    _mapping_or_none,
    _string_or_none,
    _TabIndex,
)
from datalens_sdk.domain.specs.dashboard import (
    AddAliasOp,
    AddConnectionOp,
    RemoveSelectorMemberOp,
    UpdateSelectorOp,
)
from datalens_sdk.errors import DatalensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dashboard_update_support import _ItemOccurrence
    from datalens_sdk.domain.specs.dashboard import DashboardUpdateOp


class _WiringAddersMixin:
    """add_connection / disconnect_all / add_alias shared into DashboardUpdate."""

    if TYPE_CHECKING:
        _data: dict[str, object]
        _ops: list[DashboardUpdateOp]
        _tabs: list[_TabIndex]
        _item_occurrences: dict[str, list[_ItemOccurrence]]
        _item_types: dict[str, str | None]
        _item_widget_tab_ids: dict[str, set[str]]
        _item_group_children: dict[str, set[str]]
        _removed_connections: set[tuple[str, str, str]]
        _removed_aliases: set[tuple[str, frozenset[str]]]
        _added_connections: set[tuple[str, str, str]]
        _added_aliases: set[tuple[str, frozenset[str]]]

        def _resolve_tab(self, ref: str) -> str: ...

        def _raw_tabs(self) -> list[Mapping[str, object]]: ...

    def _owning_item_id(self, ref: str) -> str:
        """The item that carries ``ref``: itself, or the widget/group whose
        chart-tab/member id it is."""
        if ref in self._item_occurrences:
            return ref
        for item_id, children in self._item_group_children.items():
            if ref in children:
                return item_id
        for item_id, widget_tabs in self._item_widget_tab_ids.items():
            if ref in widget_tabs:
                return item_id
        raise DatalensValidationError(f"Unknown item id {ref!r}")

    def _wire_endpoint_expansion(self, ref: str) -> tuple[str, ...]:
        """Expand a logical reference into server-accepted wire endpoints."""
        if not isinstance(ref, str) or not ref:
            raise DatalensValidationError(f"connection endpoint must be a non-empty string, got {ref!r}")
        if ref not in self._item_occurrences:
            self._owning_item_id(ref)  # fail-loud on unknown ids
            return (ref,)  # already a member or chart-tab id
        item_type = self._item_types.get(ref)
        if item_type == "group_control":
            children = self._item_group_children.get(ref)
            if not children:
                raise DatalensValidationError(f"group_control {ref!r} has no members to connect")
            return tuple(sorted(children))
        if item_type == "widget":
            widget_tabs = self._item_widget_tab_ids.get(ref)
            if not widget_tabs:
                raise DatalensValidationError(f"widget {ref!r} has no chart tabs to connect")
            return tuple(sorted(widget_tabs))
        if item_type == "control":
            return (ref,)
        raise DatalensValidationError(
            f"Item {ref!r} of type {item_type!r} cannot be a connection endpoint "
            "(text/title/image items cannot filter or be filtered)"
        )

    def _endpoint_tab_ids(self, ref: str) -> set[str]:
        owner = self._owning_item_id(ref)
        return {occurrence.tab_id for occurrence in self._item_occurrences[owner]}

    def _wiring_tab_id(self, refs: tuple[str, ...], tab: str | None) -> str:
        common = set.intersection(*(self._endpoint_tab_ids(ref) for ref in refs))
        if tab is not None:
            tab_id = self._resolve_tab(tab)
            if tab_id not in common:
                raise DatalensValidationError(f"Items {list(refs)!r} do not share tab {tab_id!r}")
            return tab_id
        if not common:
            raise DatalensValidationError(f"Items {list(refs)!r} do not share any tab")
        if len(common) > 1:
            raise DatalensValidationError(f"Items {list(refs)!r} share several tabs {sorted(common)!r}; pass tab=")
        return next(iter(common))

    def _connection_present(self, tab_id: str, from_id: str, to_id: str) -> bool:
        if (tab_id, from_id, to_id) in self._added_connections:
            return True
        if (tab_id, from_id, to_id) in self._removed_connections:
            return False  # removed earlier in this builder: re-adding is legal
        for raw_tab in self._raw_tabs():
            if _string_or_none(raw_tab.get("id")) != tab_id:
                continue
            return any(
                connection.get("from") == from_id and connection.get("to") == to_id
                for connection in _iter_mappings(raw_tab.get("connections"))
            )
        return False

    def _append_wire_edges(self, tab_id: str, pairs: list[tuple[str, str]]) -> None:
        for from_id, to_id in pairs:
            if from_id == to_id or self._connection_present(tab_id, from_id, to_id):
                continue  # idempotent (taxi canon), including against the snapshot
            self._removed_connections.discard((tab_id, from_id, to_id))
            self._added_connections.add((tab_id, from_id, to_id))
            self._ops.append(AddConnectionOp(tab_id=tab_id, from_id=from_id, to_id=to_id))

    def add_connection(self, *, from_item: str, to_item: str, tab: str | None = None, mutual: bool = False) -> Self:
        """Add a directed ignore edge: ``from_item`` stops receiving
        ``to_item``'s parameters. Pass the widget as ``from_item`` to stop
        a selector filtering it, or use ``mutual=True`` /
        :meth:`disconnect_all` for a full break.
        References are logical ids — widgets expand to all their chart tabs,
        groups to all members."""
        if from_item == to_item:
            raise DatalensValidationError("from_item and to_item must differ")
        from_endpoints = self._wire_endpoint_expansion(from_item)
        to_endpoints = self._wire_endpoint_expansion(to_item)
        tab_id = self._wiring_tab_id((from_item, to_item), tab)
        pairs = [(source, target) for source in from_endpoints for target in to_endpoints]
        if mutual:
            pairs.extend((target, source) for source in from_endpoints for target in to_endpoints)
        self._append_wire_edges(tab_id, pairs)
        return self

    def disconnect_all(self, *item_ids: str, tab: str | None = None) -> Self:
        """Fully sever every pair among ``item_ids``: the full mesh of
        directed ignore edges in both directions."""
        if len(item_ids) < 2:
            raise DatalensValidationError("disconnect_all needs at least two item ids")
        if len(set(item_ids)) != len(item_ids):
            raise DatalensValidationError("disconnect_all item ids must be unique")
        expansions = {ref: self._wire_endpoint_expansion(ref) for ref in item_ids}
        tab_id = self._wiring_tab_id(tuple(item_ids), tab)
        pairs: list[tuple[str, str]] = []
        for source_ref in item_ids:
            for target_ref in item_ids:
                if source_ref == target_ref:
                    continue
                pairs.extend((source, target) for source in expansions[source_ref] for target in expansions[target_ref])
        self._append_wire_edges(tab_id, pairs)
        return self

    def _alias_present(self, tab_id: str, group: frozenset[str]) -> bool:
        if (tab_id, group) in self._added_aliases:
            return True
        if (tab_id, group) in self._removed_aliases:
            return False
        for raw_tab in self._raw_tabs():
            if _string_or_none(raw_tab.get("id")) != tab_id:
                continue
            aliases = _mapping_or_none(raw_tab.get("aliases")) or {}
            return any(
                isinstance(entry, list) and {value for value in entry if isinstance(value, str)} == group
                for entry in _iter_mappings_or_lists(aliases.get("default"))
            )
        return False

    def add_alias(self, *fields: str, tab: str | None = None) -> Self:
        """Declare ≥2 dataset field guids equivalent on one tab; groups
        already present on the dashboard (any member order) are skipped."""
        if len(fields) < 2:
            raise DatalensValidationError("add_alias needs at least two field guids")
        if not all(isinstance(entry, str) and entry for entry in fields):
            raise DatalensValidationError(f"alias fields must be non-empty strings, got {fields!r}")
        if len(set(fields)) != len(fields):
            raise DatalensValidationError("alias fields must be unique")
        if tab is not None:
            tab_id = self._resolve_tab(tab)
        elif len(self._tabs) == 1:
            tab_id = self._tabs[0].tab_id
        else:
            raise DatalensValidationError("The dashboard has several tabs; pass tab= for add_alias")
        group = frozenset(fields)
        if self._alias_present(tab_id, group):
            return self
        self._removed_aliases.discard((tab_id, group))
        self._added_aliases.add((tab_id, group))
        self._ops.append(AddAliasOp(tab_id=tab_id, fields=tuple(fields)))
        return self

    # -- selector point-ops (epic D4, stage 16) ----------------------------------

    def _selector_target(self, item_id: str) -> tuple[str, str | None]:
        """Resolve a selector reference into (wrapper item id, member id).

        The canon address is the MEMBER id; a singleton group's wrapper id is
        a convenience shorthand; a multi-member wrapper without a member id
        fails loud. Standalone controls resolve to (item id, None).
        """
        if item_id in self._item_occurrences:
            item_type = self._item_types.get(item_id)
            if item_type == "control":
                return item_id, None
            if item_type == "group_control":
                children = self._item_group_children.get(item_id, set())
                if len(children) == 1:
                    return item_id, next(iter(children))
                raise DatalensValidationError(
                    f"group_control {item_id!r} has {len(children)} members; pass the member id"
                )
            raise DatalensValidationError(f"Item {item_id!r} of type {item_type!r} is not a selector")
        for wrapper_id, children in self._item_group_children.items():
            if item_id in children:
                return wrapper_id, item_id
        raise DatalensValidationError(f"Unknown item id {item_id!r}")

    def update_selector(
        self,
        *,
        item_id: str,
        title: str | None = None,
        default_value: str | Sequence[str] | bool | DateInterval | RelativeDateInterval | None = None,
        operation: SelectorOperation | None = None,
        required: bool | None = None,
        hint: str | None = None,
    ) -> Self:
        """Point-patch one selector's source fields.
        ``item_id`` is the selector member id (or a singleton wrapper /
        standalone control id).
        """
        if title is None and default_value is None and operation is None and required is None and hint is None:
            raise DatalensValidationError("update_selector needs at least one field to change")
        if title is not None and not title:
            raise DatalensValidationError("Selector title must not be an empty string")
        if operation is not None and operation not in get_args(SelectorOperation):
            raise DatalensValidationError(f"Unknown selector operation {operation!r}")
        wrapper_id, member_id = self._selector_target(item_id)
        if self._selector_source_type(wrapper_id, member_id) == "external" and (
            default_value is not None or operation is not None or required is not None
        ):
            raise DatalensValidationError("External selectors only support title/hint patches")
        normalized_default: SelectorDefaultValue | None = None
        if isinstance(default_value, Sequence) and not isinstance(default_value, str):
            values = tuple(default_value)
            if not all(isinstance(entry, str) for entry in values):
                raise DatalensValidationError(f"Select default values must be strings, got {default_value!r}")
            normalized_default = values
        elif default_value is not None:
            normalized_default = default_value
        self._ops.append(
            UpdateSelectorOp(
                item_id=wrapper_id,
                member_id=member_id,
                title=title,
                default_value=normalized_default,
                operation=operation,
                required=required,
                hint=hint,
            )
        )
        return self

    def _selector_source_type(self, wrapper_id: str, member_id: str | None) -> str | None:
        for raw_tab in self._raw_tabs():
            for container in ("items", "globalItems"):
                for item in _iter_mappings(raw_tab.get(container)):
                    if item.get("id") != wrapper_id:
                        continue
                    item_data = _mapping_or_none(item.get("data")) or {}
                    if member_id is None:
                        return _string_or_none(item_data.get("sourceType"))
                    for member in _iter_mappings(item_data.get("group")):
                        if member.get("id") == member_id:
                            return _string_or_none(member.get("sourceType"))
        return None

    def remove_selector(self, *, item_id: str) -> Self:
        """Remove one selector: a member leaves its group (an emptied group
        is removed entirely); a wrapper id removes the whole item."""
        if item_id in self._item_occurrences:
            item_type = self._item_types.get(item_id)
            if item_type not in ("control", "group_control"):
                raise DatalensValidationError(f"Item {item_id!r} of type {item_type!r} is not a selector")
            return cast("Self", cast(object, self).remove_item(item_id))  # type: ignore[attr-defined]
        wrapper_id, member_id = self._selector_target(item_id)
        assert member_id is not None
        children = self._item_group_children.get(wrapper_id, set())
        if children == {member_id}:
            return cast("Self", cast(object, self).remove_item(wrapper_id))  # type: ignore[attr-defined]
        self._ops.append(RemoveSelectorMemberOp(item_id=wrapper_id, member_id=member_id))
        children.discard(member_id)
        for tab_index in self._tabs:
            tab_index.control_child_ids.discard(member_id)
        return self
