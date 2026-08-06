from __future__ import annotations

from collections.abc import Iterator, Mapping
import copy
from dataclasses import dataclass
from typing import Literal, TypeAlias

from datalens_sdk.errors import DatalensValidationError

FieldCarrier = Literal[
    "placeholder",
    "filter",
    "sort",
    "color",
    "label",
    "segment",
    "shape",
    "tooltip",
    "hierarchy",
    "field_definition",
]
ReferenceKind = Literal["snapshot", "guid"]
PathPart: TypeAlias = str | int
ReplacementContainer: TypeAlias = dict[str, object] | list[object]

_DATA_CARRIERS: tuple[tuple[str, FieldCarrier], ...] = (
    ("filters", "filter"),
    ("sort", "sort"),
    ("colors", "color"),
    ("labels", "label"),
    ("segments", "segment"),
    ("shapes", "shape"),
    ("tooltips", "tooltip"),
)
_CONFIG_KEYS = ("colorsConfig", "shapesConfig")
_FIELD_DEFINITION_KEYS = frozenset(
    {
        "aggregation",
        "aggregation_locked",
        "autoaggregated",
        "avatar_id",
        "calc_mode",
        "cast",
        "className",
        "data_type",
        "datasetId",
        "datasetName",
        "default_value",
        "description",
        "formula",
        "guid",
        "guid_formula",
        "has_auto_aggregation",
        "hidden",
        "initial_data_type",
        "local",
        "lock_aggregation",
        "managed_by",
        "name",
        "source",
        "title",
        "type",
        "ui_settings",
        "valid",
        "value_constraint",
        "virtual",
    }
)
_CONFLICT_KEYS = frozenset(
    {
        "aggregation",
        "calc_mode",
        "cast",
        "data_type",
        "datasetId",
        "formula",
        "source",
        "title",
        "type",
    }
)


def _guid(value: Mapping[str, object]) -> str | None:
    guid = value.get("guid")
    return guid if isinstance(guid, str) and guid else None


def _layer_id(layer: Mapping[str, object]) -> str | None:
    settings = layer.get("layerSettings")
    if isinstance(settings, Mapping):
        value = settings.get("id")
        if isinstance(value, str) and value:
            return value
    value = layer.get("id")
    return value if isinstance(value, str) and value else None


def _replacement_snapshot(
    current: Mapping[str, object],
    replacement: Mapping[str, object],
) -> dict[str, object]:
    result = {key: value for key, value in current.items() if key not in _FIELD_DEFINITION_KEYS}
    result.update(copy.deepcopy(dict(replacement)))
    return result


@dataclass(slots=True)
class FieldSnapshotLocation:
    carrier: FieldCarrier
    layer_id: str | None
    path: tuple[PathPart, ...]
    reference_kind: Literal["snapshot"]
    snapshot: dict[str, object]
    _replacement_container: ReplacementContainer
    _replacement_key: str | int
    _removal_container: list[object]
    _removal_index: int

    @property
    def guid(self) -> str | None:
        return _guid(self.snapshot)

    def replace(self, replacement: Mapping[str, object]) -> None:
        normalized = _replacement_snapshot(self.snapshot, replacement)
        if isinstance(self._replacement_container, list):
            if not isinstance(self._replacement_key, int):
                raise AssertionError("Invalid Wizard field-reference list target")
            self._replacement_container[self._replacement_key] = normalized
        else:
            if not isinstance(self._replacement_key, str):
                raise AssertionError("Invalid Wizard field-reference mapping target")
            self._replacement_container[self._replacement_key] = normalized
        self.snapshot = normalized


@dataclass(slots=True)
class FieldGuidLocation:
    carrier: Literal["config_pointer"]
    layer_id: str | None
    path: tuple[PathPart, ...]
    reference_kind: Literal["guid"]
    config: dict[str, object]

    @property
    def guid(self) -> str | None:
        value = self.config.get("fieldGuid")
        return value if isinstance(value, str) and value else None

    def replace(self, guid: str) -> None:
        self.config["fieldGuid"] = guid

    def clear(self) -> None:
        self.config.clear()


class WizardFieldReferences:
    """Authoritative traversal and mutation of Wizard wire field references."""

    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def snapshot_locations(self, *, include_definitions: bool = False) -> list[FieldSnapshotLocation]:
        return list(self._iter_snapshot_locations(include_definitions=include_definitions))

    def guid_locations(self) -> list[FieldGuidLocation]:
        return list(self._iter_guid_locations())

    def active_snapshots(self) -> list[dict[str, object]]:
        return [location.snapshot for location in self.snapshot_locations()]

    def unique_active_snapshots(self) -> list[dict[str, object]]:
        unique: list[dict[str, object]] = []
        by_guid: dict[str, dict[str, object]] = {}
        for snapshot in self.active_snapshots():
            guid = _guid(snapshot)
            if guid is None:
                unique.append(snapshot)
                continue
            existing = by_guid.get(guid)
            if existing is None:
                by_guid[guid] = snapshot
                unique.append(snapshot)
                continue
            conflicts = {
                key
                for key in _CONFLICT_KEYS
                if key in existing
                and key in snapshot
                and existing[key] not in (None, "")
                and snapshot[key] not in (None, "")
                and existing[key] != snapshot[key]
            }
            if conflicts:
                raise DatalensValidationError(
                    f"Wizard chart contains conflicting snapshots for field guid {guid!r}: "
                    f"{sorted(conflicts)} differ between active carriers."
                )
        return unique

    def replace_field(self, old_guid: str, replacement: Mapping[str, object]) -> None:
        replacement_guid = _guid(replacement)
        if replacement_guid is None:
            raise DatalensValidationError("Replacement field snapshot must contain a non-empty guid.")
        snapshots = [location for location in self.snapshot_locations() if location.guid == old_guid]
        pointers = [location for location in self.guid_locations() if location.guid == old_guid]
        if not snapshots and not pointers:
            raise DatalensValidationError(f"Field guid {old_guid!r} is not referenced by this Wizard chart.")
        for snapshot_location in snapshots:
            snapshot_location.replace(replacement)
        if replacement_guid == old_guid:
            return
        for pointer_location in pointers:
            pointer_location.replace(replacement_guid)
        self.assert_guid_absent(old_guid)

    def delete_field(self, guid: str) -> None:
        snapshots = [location for location in self.snapshot_locations() if location.guid == guid]
        pointers = [location for location in self.guid_locations() if location.guid == guid]
        if not snapshots and not pointers:
            raise DatalensValidationError(f"Field guid {guid!r} is not referenced by this Wizard chart.")
        removals: dict[int, tuple[list[object], set[int]]] = {}
        for location in snapshots:
            key = id(location._removal_container)
            if key not in removals:
                removals[key] = (location._removal_container, set())
            removals[key][1].add(location._removal_index)
        for container, indices in removals.values():
            for index in sorted(indices, reverse=True):
                del container[index]
        for pointer_location in pointers:
            pointer_location.clear()
        self.assert_guid_absent(guid)

    def replace_dataset(self, old_id: str, new_id: str) -> None:
        for location in self.snapshot_locations(include_definitions=True):
            if location.snapshot.get("datasetId") == old_id:
                location.snapshot["datasetId"] = new_id

    def assert_guid_absent(self, guid: str) -> None:
        stale_snapshots = [location.path for location in self.snapshot_locations() if location.guid == guid]
        stale_pointers = [location.path for location in self.guid_locations() if location.guid == guid]
        if stale_snapshots or stale_pointers:
            raise DatalensValidationError(
                f"Wizard field mutation left stale guid {guid!r} at {stale_snapshots + stale_pointers!r}."
            )

    def assert_dataset_absent(self, dataset_id: str) -> None:
        stale = [
            location.path
            for location in self.snapshot_locations(include_definitions=True)
            if location.snapshot.get("datasetId") == dataset_id
        ]
        if stale:
            raise DatalensValidationError(
                f"Wizard dataset replacement left stale datasetId {dataset_id!r} at {stale!r}."
            )

    def _iter_snapshot_locations(self, *, include_definitions: bool) -> Iterator[FieldSnapshotLocation]:
        visualization = self._data.get("visualization")
        if isinstance(visualization, dict):
            yield from self._iter_visualization_snapshots(
                visualization,
                layer_id=None,
                path=("visualization",),
            )
        yield from self._iter_carrier_snapshots(self._data, layer_id=None, path=())
        yield from self._iter_hierarchy_snapshots()
        if include_definitions:
            yield from self._iter_definition_snapshots()

    def _iter_visualization_snapshots(
        self,
        visualization: dict[str, object],
        *,
        layer_id: str | None,
        path: tuple[PathPart, ...],
    ) -> Iterator[FieldSnapshotLocation]:
        placeholders = visualization.get("placeholders")
        if isinstance(placeholders, list):
            for placeholder_index, placeholder in enumerate(placeholders):
                if not isinstance(placeholder, dict):
                    continue
                items = placeholder.get("items")
                if isinstance(items, list):
                    yield from self._iter_item_snapshots(
                        items,
                        carrier="placeholder",
                        layer_id=layer_id,
                        path=(*path, "placeholders", placeholder_index, "items"),
                    )
        common = visualization.get("commonPlaceholders")
        if isinstance(common, dict):
            yield from self._iter_carrier_snapshots(
                common,
                layer_id=layer_id,
                path=(*path, "commonPlaceholders"),
            )
        layers = visualization.get("layers")
        if isinstance(layers, list):
            for layer_index, layer in enumerate(layers):
                if isinstance(layer, dict):
                    yield from self._iter_visualization_snapshots(
                        layer,
                        layer_id=_layer_id(layer),
                        path=(*path, "layers", layer_index),
                    )

    def _iter_carrier_snapshots(
        self,
        owner: Mapping[str, object],
        *,
        layer_id: str | None,
        path: tuple[PathPart, ...],
    ) -> Iterator[FieldSnapshotLocation]:
        for key, carrier in _DATA_CARRIERS:
            items = owner.get(key)
            if isinstance(items, list):
                yield from self._iter_item_snapshots(
                    items,
                    carrier=carrier,
                    layer_id=layer_id,
                    path=(*path, key),
                )

    def _iter_item_snapshots(
        self,
        items: list[object],
        *,
        carrier: FieldCarrier,
        layer_id: str | None,
        path: tuple[PathPart, ...],
    ) -> Iterator[FieldSnapshotLocation]:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            snapshot = item
            replacement_container: ReplacementContainer = items
            replacement_key: str | int = index
            nested_field = item.get("field")
            if _guid(snapshot) is None and isinstance(nested_field, dict) and _guid(nested_field) is not None:
                snapshot = nested_field
                replacement_container = item
                replacement_key = "field"
            if _guid(snapshot) is not None:
                yield FieldSnapshotLocation(
                    carrier=carrier,
                    layer_id=layer_id,
                    path=(*path, index),
                    reference_kind="snapshot",
                    snapshot=snapshot,
                    _replacement_container=replacement_container,
                    _replacement_key=replacement_key,
                    _removal_container=items,
                    _removal_index=index,
                )
            nested_fields = snapshot.get("fields")
            if isinstance(nested_fields, list):
                yield from self._iter_item_snapshots(
                    nested_fields,
                    carrier=carrier,
                    layer_id=layer_id,
                    path=(*path, index, "fields"),
                )

    def _iter_hierarchy_snapshots(self) -> Iterator[FieldSnapshotLocation]:
        hierarchies = self._data.get("hierarchies")
        if not isinstance(hierarchies, list):
            return
        for hierarchy_index, hierarchy in enumerate(hierarchies):
            if not isinstance(hierarchy, dict):
                continue
            fields = hierarchy.get("fields")
            if isinstance(fields, list):
                yield from self._iter_item_snapshots(
                    fields,
                    carrier="hierarchy",
                    layer_id=None,
                    path=("hierarchies", hierarchy_index, "fields"),
                )

    def _iter_definition_snapshots(self) -> Iterator[FieldSnapshotLocation]:
        partial_fields = self._data.get("datasetsPartialFields")
        if isinstance(partial_fields, list):
            for group_index, group in enumerate(partial_fields):
                if isinstance(group, list):
                    yield from self._iter_item_snapshots(
                        group,
                        carrier="field_definition",
                        layer_id=None,
                        path=("datasetsPartialFields", group_index),
                    )
        updates = self._data.get("updates")
        if isinstance(updates, list):
            for update_index, operation in enumerate(updates):
                if not isinstance(operation, dict):
                    continue
                field = operation.get("field")
                if not isinstance(field, dict) or _guid(field) is None:
                    continue
                yield FieldSnapshotLocation(
                    carrier="field_definition",
                    layer_id=None,
                    path=("updates", update_index, "field"),
                    reference_kind="snapshot",
                    snapshot=field,
                    _replacement_container=operation,
                    _replacement_key="field",
                    _removal_container=updates,
                    _removal_index=update_index,
                )

    def _iter_guid_locations(self) -> Iterator[FieldGuidLocation]:
        yield from self._iter_owner_guid_locations(self._data, layer_id=None, path=())
        visualization = self._data.get("visualization")
        if isinstance(visualization, dict):
            yield from self._iter_visualization_guid_locations(
                visualization,
                layer_id=None,
                path=("visualization",),
            )

    def _iter_visualization_guid_locations(
        self,
        visualization: dict[str, object],
        *,
        layer_id: str | None,
        path: tuple[PathPart, ...],
    ) -> Iterator[FieldGuidLocation]:
        common = visualization.get("commonPlaceholders")
        if isinstance(common, dict):
            yield from self._iter_owner_guid_locations(
                common,
                layer_id=layer_id,
                path=(*path, "commonPlaceholders"),
            )
        layers = visualization.get("layers")
        if isinstance(layers, list):
            for layer_index, layer in enumerate(layers):
                if isinstance(layer, dict):
                    yield from self._iter_visualization_guid_locations(
                        layer,
                        layer_id=_layer_id(layer),
                        path=(*path, "layers", layer_index),
                    )

    def _iter_owner_guid_locations(
        self,
        owner: Mapping[str, object],
        *,
        layer_id: str | None,
        path: tuple[PathPart, ...],
    ) -> Iterator[FieldGuidLocation]:
        for key in _CONFIG_KEYS:
            config = owner.get(key)
            if isinstance(config, dict) and isinstance(config.get("fieldGuid"), str):
                yield FieldGuidLocation(
                    carrier="config_pointer",
                    layer_id=layer_id,
                    path=(*path, key, "fieldGuid"),
                    reference_kind="guid",
                    config=config,
                )
