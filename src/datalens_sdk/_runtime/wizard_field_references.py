from __future__ import annotations

from collections.abc import Iterator, Mapping
import copy
from dataclasses import dataclass
from typing import Literal, TypeAlias

from datalens_sdk.errors import DataLensValidationError

FieldCarrier = Literal["slot", "filter", "sort", "hierarchy", "field_definition"]
PathPart: TypeAlias = str | int
ReplacementContainer: TypeAlias = dict[str, object] | list[object]

# These keys define the mounted field snapshot owned by SDK replacement
# semantics. They are intentionally a policy subset, not a copy of every
# field property exposed by the generated Wizard schema.
_MOUNTED_FIELD_OWNED_KEYS = frozenset(
    {
        "aggregation",
        "aggregation_locked",
        "autoaggregated",
        "avatar_id",
        "calc_mode",
        "cast",
        "data_type",
        "datasetId",
        "default_value",
        "fakeTitle",
        "format",
        "formula",
        "guid",
        "local",
        "originalDateCast",
        "originalFormula",
        "originalSource",
        "originalTitle",
        "quickFormula",
        "source",
        "title",
        "type",
    }
)
_FILTER_FIELD_OWNED_KEYS = frozenset({"guid", "datasetId", "fakeTitle"})
_SORT_FIELD_OWNED_KEYS = frozenset({"guid", "datasetId", "fakeTitle", "format"})
_HIERARCHY_FIELD_OWNED_KEYS = frozenset({"guid", "datasetId"})

# Replacement ownership is an SDK mutation policy, not a projection of every
# property exposed by generated field schemas. New open-snapshot properties
# therefore remain preserved until an operation deliberately takes ownership.
_FIELD_SNAPSHOT_OWNED_KEYS_BY_CARRIER: Mapping[FieldCarrier, frozenset[str]] = {
    "slot": _MOUNTED_FIELD_OWNED_KEYS,
    "filter": _FILTER_FIELD_OWNED_KEYS,
    "sort": _SORT_FIELD_OWNED_KEYS,
    "hierarchy": _HIERARCHY_FIELD_OWNED_KEYS,
    "field_definition": _MOUNTED_FIELD_OWNED_KEYS,
}

# Only disagreements that make a GUID-based lookup ambiguous are conflicts;
# other open decorations stay carrier-local and server-owned.
_ACTIVE_SNAPSHOT_CONFLICT_KEYS = frozenset({"datasetId", "fakeTitle", "format", "formatting"})
_GUID_VALUE_KEYS = frozenset({"colorFieldGuid", "fieldGuid"})
_GUID_MAP_KEYS = frozenset({"axisModeMap", "mountedColors", "mountedShapes"})


def _guid(value: Mapping[str, object]) -> str | None:
    guid = value.get("guid")
    return guid if isinstance(guid, str) and guid else None


def _replacement_snapshot(
    current: Mapping[str, object],
    replacement: Mapping[str, object],
    *,
    carrier: FieldCarrier,
) -> dict[str, object]:
    owned_keys = _FIELD_SNAPSHOT_OWNED_KEYS_BY_CARRIER[carrier]
    result = {key: copy.deepcopy(value) for key, value in current.items() if key not in owned_keys}
    result.update({key: copy.deepcopy(value) for key, value in replacement.items() if key in owned_keys})
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
        normalized = _replacement_snapshot(self.snapshot, replacement, carrier=self.carrier)
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
    key: str
    guid_is_key: bool = False

    @property
    def guid(self) -> str | None:
        value = self.key if self.guid_is_key else self.config.get(self.key)
        return value if isinstance(value, str) and value else None

    def replace(self, guid: str) -> None:
        if self.guid_is_key:
            value = self.config.pop(self.key)
            self.config[guid] = value
            self.key = guid
        else:
            self.config[self.key] = guid

    def clear(self) -> None:
        self.config.pop(self.key, None)


@dataclass(slots=True)
class LinkFieldLocation:
    path: tuple[PathPart, ...]
    fields: dict[str, object]
    key: str
    entry: dict[str, object]
    dataset: dict[str, object]
    field: dict[str, object]

    @property
    def guid(self) -> str:
        return str(self.field["guid"])

    @property
    def dataset_id(self) -> str:
        return str(self.dataset["id"])

    def replace_field(self, replacement: Mapping[str, object]) -> None:
        guid = replacement.get("guid")
        title = replacement.get("title")
        if not isinstance(guid, str) or not guid or not isinstance(title, str):
            raise AssertionError("Wizard linked-field replacement was not preflighted")
        self.field["guid"] = guid
        self.field["title"] = title


class WizardFieldReferences:
    """Traverse field references in one open Wizard V1 config snapshot."""

    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    def snapshot_locations(self, *, include_definitions: bool = False) -> list[FieldSnapshotLocation]:
        return list(self._iter_snapshot_locations(include_definitions=include_definitions))

    def guid_locations(self) -> list[FieldGuidLocation]:
        return list(self._iter_guid_locations())

    def link_field_locations(self) -> list[LinkFieldLocation]:
        return list(self._iter_link_field_locations())

    def active_snapshots(self) -> list[dict[str, object]]:
        return [location.snapshot for location in self.snapshot_locations()]

    def unique_active_snapshots(self) -> list[dict[str, object]]:
        definitions = {
            location.guid: location.snapshot
            for location in self.snapshot_locations(include_definitions=True)
            if location.carrier == "field_definition" and location.guid is not None
        }
        unique: list[dict[str, object]] = []
        by_guid: dict[str, dict[str, object]] = {}
        for snapshot in self.active_snapshots():
            guid = _guid(snapshot)
            if guid is None:
                unique.append(snapshot)
                continue
            definition = definitions.get(guid)
            if definition is not None:
                snapshot = {**definition, **snapshot}
            existing = by_guid.get(guid)
            if existing is None:
                by_guid[guid] = snapshot
                unique.append(snapshot)
                continue
            conflicts = {
                key
                for key in _ACTIVE_SNAPSHOT_CONFLICT_KEYS
                if key in existing
                and key in snapshot
                and existing[key] not in (None, "")
                and snapshot[key] not in (None, "")
                and existing[key] != snapshot[key]
            }
            if conflicts:
                raise DataLensValidationError(
                    f"Wizard chart contains conflicting snapshots for field guid {guid!r}: "
                    f"{sorted(conflicts)} differ between active carriers."
                )
        return unique

    def validate_field_replacement(self, old_guid: str, replacement: Mapping[str, object]) -> None:
        links = [location for location in self.link_field_locations() if location.guid == old_guid]
        if not links:
            return
        replacement_guid = _guid(replacement)
        replacement_title = replacement.get("title")
        replacement_dataset_id = replacement.get("datasetId")
        if replacement_guid is None or not isinstance(replacement_title, str):
            raise DataLensValidationError(
                f"Replacing linked field {old_guid!r} requires a replacement with non-empty guid and string title."
            )
        if not isinstance(replacement_dataset_id, str) or not replacement_dataset_id:
            raise DataLensValidationError(
                f"Replacing linked field {old_guid!r} requires a replacement with a non-empty datasetId."
            )
        for location in links:
            if replacement_dataset_id == location.dataset_id:
                continue
            if replacement_dataset_id in location.fields and replacement_dataset_id != location.key:
                raise DataLensValidationError(
                    "Wizard linked-field replacement would collide with existing sources.links field-map key "
                    f"{replacement_dataset_id!r} at {location.path!r}."
                )
            raise DataLensValidationError(
                "Wizard linked-field replacement across datasets requires an explicit link mapping and "
                f"dataset realName; cannot replace {old_guid!r} at {location.path!r}."
            )

    def validate_field_deletion(self, guid: str) -> None:
        links = [location.path for location in self.link_field_locations() if location.guid == guid]
        if links:
            raise DataLensValidationError(
                f"Deleting linked field {guid!r} requires an explicit replacement for sources.links at {links!r}."
            )

    def validate_dataset_replacement(self, old_id: str, new_id: str) -> None:
        links = [
            location
            for location in self.link_field_locations()
            if location.key == old_id or location.dataset_id == old_id
        ]
        for location in links:
            if new_id in location.fields and new_id != location.key:
                raise DataLensValidationError(
                    "Wizard dataset replacement would collide with existing sources.links field-map key "
                    f"{new_id!r} at {location.path!r}."
                )
        if links:
            paths = [location.path for location in links]
            raise DataLensValidationError(
                "Wizard dataset replacement for sources.links requires an explicit link mapping and new dataset "
                f"realName; cannot replace {old_id!r} with {new_id!r} at {paths!r}."
            )

    def replace_field(
        self,
        old_guid: str,
        replacement: Mapping[str, object],
        *,
        link_replacement: Mapping[str, object] | None = None,
    ) -> None:
        replacement_guid = _guid(replacement)
        if replacement_guid is None:
            raise DataLensValidationError("Replacement field snapshot must contain a non-empty guid.")
        if replacement_guid == old_guid:
            raise DataLensValidationError(f"Replacement field guid must differ from {old_guid!r}.")
        snapshots = [location for location in self.snapshot_locations() if location.guid == old_guid]
        pointers = [location for location in self.guid_locations() if location.guid == old_guid]
        links = [location for location in self.link_field_locations() if location.guid == old_guid]
        effective_link_replacement = link_replacement if link_replacement is not None else replacement
        self.validate_field_replacement(old_guid, effective_link_replacement)
        if not snapshots and not pointers and not links:
            raise DataLensValidationError(f"Field guid {old_guid!r} is not referenced by this Wizard chart.")
        for location in snapshots:
            location.replace(replacement)
        for pointer_location in pointers:
            pointer_location.replace(replacement_guid)
        for link_location in links:
            link_location.replace_field(effective_link_replacement)
        self.assert_guid_absent(old_guid)

    def delete_field(self, guid: str) -> None:
        snapshots = [location for location in self.snapshot_locations() if location.guid == guid]
        pointers = [location for location in self.guid_locations() if location.guid == guid]
        links = [location for location in self.link_field_locations() if location.guid == guid]
        self.validate_field_deletion(guid)
        if not snapshots and not pointers and not links:
            raise DataLensValidationError(f"Field guid {guid!r} is not referenced by this Wizard chart.")
        removals: dict[int, tuple[list[object], set[int]]] = {}
        for location in snapshots:
            container_id = id(location._removal_container)
            if container_id not in removals:
                removals[container_id] = (location._removal_container, set())
            removals[container_id][1].add(location._removal_index)
        for container, indices in removals.values():
            for index in sorted(indices, reverse=True):
                del container[index]
        for pointer_location in pointers:
            pointer_location.clear()
        self.assert_guid_absent(guid)

    def replace_dataset(self, old_id: str, new_id: str) -> None:
        self.validate_dataset_replacement(old_id, new_id)
        for location in self.snapshot_locations(include_definitions=True):
            if location.snapshot.get("datasetId") == old_id:
                location.snapshot["datasetId"] = new_id

    def assert_guid_absent(self, guid: str) -> None:
        stale = [location.path for location in self.snapshot_locations() if location.guid == guid]
        stale.extend(location.path for location in self.guid_locations() if location.guid == guid)
        stale.extend(
            (*location.path, "field", "guid") for location in self.link_field_locations() if location.guid == guid
        )
        if stale:
            raise DataLensValidationError(f"Wizard field mutation left stale guid {guid!r} at {stale!r}.")

    def assert_dataset_absent(self, dataset_id: str) -> None:
        stale = [
            location.path
            for location in self.snapshot_locations(include_definitions=True)
            if location.snapshot.get("datasetId") == dataset_id
        ]
        stale.extend(
            (*location.path, "dataset", "id")
            for location in self.link_field_locations()
            if location.dataset_id == dataset_id or location.key == dataset_id
        )
        if stale:
            raise DataLensValidationError(
                f"Wizard dataset replacement left stale datasetId {dataset_id!r} at {stale!r}."
            )

    def _iter_snapshot_locations(self, *, include_definitions: bool) -> Iterator[FieldSnapshotLocation]:
        visualization = self._data.get("visualization")
        if isinstance(visualization, dict):
            for slot_name, slot in visualization.items():
                if not isinstance(slot, dict):
                    continue
                items = slot.get("items")
                if not isinstance(items, list):
                    continue
                carrier: FieldCarrier = "sort" if slot_name == "sort" else "slot"
                yield from self._iter_list(items, carrier=carrier, path=("visualization", slot_name, "items"))
            layers = visualization.get("layers")
            if isinstance(layers, list):
                for layer_index, layer in enumerate(layers):
                    if not isinstance(layer, dict):
                        continue
                    settings = layer.get("layerSettings")
                    raw_layer_id = settings.get("id") if isinstance(settings, Mapping) else None
                    layer_id = raw_layer_id if isinstance(raw_layer_id, str) else None
                    for slot_name, slot in layer.items():
                        if not isinstance(slot, dict):
                            continue
                        items = slot.get("items")
                        if not isinstance(items, list):
                            continue
                        carrier = "sort" if slot_name == "sort" else "slot"
                        yield from self._iter_list(
                            items,
                            carrier=carrier,
                            layer_id=layer_id,
                            path=("visualization", "layers", layer_index, slot_name, "items"),
                        )

        sources = self._data.get("sources")
        if not isinstance(sources, dict):
            return
        filters = sources.get("filters")
        if isinstance(filters, list):
            yield from self._iter_list(filters, carrier="filter", path=("sources", "filters"))
        hierarchies = sources.get("hierarchies")
        if isinstance(hierarchies, list):
            for hierarchy_index, hierarchy in enumerate(hierarchies):
                if not isinstance(hierarchy, dict):
                    continue
                fields = hierarchy.get("fields")
                if isinstance(fields, list):
                    yield from self._iter_list(
                        fields,
                        carrier="hierarchy",
                        path=("sources", "hierarchies", hierarchy_index, "fields"),
                    )
        if include_definitions:
            updates = sources.get("updates")
            if isinstance(updates, list):
                for update_index, operation in enumerate(updates):
                    if not isinstance(operation, dict):
                        continue
                    field = operation.get("field")
                    if not isinstance(field, dict):
                        continue
                    yield FieldSnapshotLocation(
                        carrier="field_definition",
                        layer_id=None,
                        path=("sources", "updates", update_index, "field"),
                        reference_kind="snapshot",
                        snapshot=field,
                        _replacement_container=operation,
                        _replacement_key="field",
                        _removal_container=updates,
                        _removal_index=update_index,
                    )

    @staticmethod
    def _iter_list(
        items: list[object],
        *,
        carrier: FieldCarrier,
        layer_id: str | None = None,
        path: tuple[PathPart, ...],
    ) -> Iterator[FieldSnapshotLocation]:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            yield FieldSnapshotLocation(
                carrier=carrier,
                layer_id=layer_id,
                path=(*path, index),
                reference_kind="snapshot",
                snapshot=item,
                _replacement_container=items,
                _replacement_key=index,
                _removal_container=items,
                _removal_index=index,
            )

    def _iter_guid_locations(self) -> Iterator[FieldGuidLocation]:
        visualization = self._data.get("visualization")
        if not isinstance(visualization, dict):
            return
        yield from self._iter_guid_nodes(visualization, path=("visualization",), layer_id=None)

    def _iter_link_field_locations(self) -> Iterator[LinkFieldLocation]:
        sources = self._data.get("sources")
        if not isinstance(sources, Mapping):
            return
        links = sources.get("links")
        if links is None:
            return
        if not isinstance(links, list):
            raise DataLensValidationError("Wizard sources.links must be an array before structural mutation.")
        for link_index, link in enumerate(links):
            if not isinstance(link, dict):
                raise DataLensValidationError(f"Wizard sources.links[{link_index}] must be an object.")
            fields = link.get("fields")
            if not isinstance(fields, dict):
                raise DataLensValidationError(f"Wizard sources.links[{link_index}].fields must be an object.")
            for key, entry in fields.items():
                path = ("sources", "links", link_index, "fields", key)
                if not isinstance(key, str) or not key or not isinstance(entry, dict):
                    raise DataLensValidationError(f"Wizard linked-field entry at {path!r} is invalid.")
                dataset = entry.get("dataset")
                field = entry.get("field")
                if not isinstance(dataset, dict) or not isinstance(field, dict):
                    raise DataLensValidationError(f"Wizard linked-field entry at {path!r} requires dataset and field.")
                dataset_id = dataset.get("id")
                real_name = dataset.get("realName")
                guid = field.get("guid")
                title = field.get("title")
                if (
                    not isinstance(dataset_id, str)
                    or not dataset_id
                    or not isinstance(real_name, str)
                    or not isinstance(guid, str)
                    or not guid
                    or not isinstance(title, str)
                ):
                    raise DataLensValidationError(f"Wizard linked-field identity at {path!r} is invalid.")
                if key != dataset_id:
                    raise DataLensValidationError(
                        f"Wizard linked-field map key {key!r} must match dataset.id {dataset_id!r} at {path!r}."
                    )
                yield LinkFieldLocation(
                    path=path,
                    fields=fields,
                    key=key,
                    entry=entry,
                    dataset=dataset,
                    field=field,
                )

    def _iter_guid_nodes(
        self,
        node: dict[str, object],
        *,
        path: tuple[PathPart, ...],
        layer_id: str | None,
    ) -> Iterator[FieldGuidLocation]:
        for key, value in list(node.items()):
            if key in _GUID_VALUE_KEYS and isinstance(value, str):
                yield FieldGuidLocation(
                    carrier="config_pointer",
                    layer_id=layer_id,
                    path=(*path, key),
                    reference_kind="guid",
                    config=node,
                    key=key,
                )
            elif key in _GUID_MAP_KEYS and isinstance(value, dict):
                for guid in list(value):
                    yield FieldGuidLocation(
                        carrier="config_pointer",
                        layer_id=layer_id,
                        path=(*path, key, guid),
                        reference_kind="guid",
                        config=value,
                        key=guid,
                        guid_is_key=True,
                    )
            elif isinstance(value, dict):
                yield from self._iter_guid_nodes(value, path=(*path, key), layer_id=layer_id)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        nested_layer_id = layer_id
                        if key == "layers":
                            settings = item.get("layerSettings")
                            raw_layer_id = settings.get("id") if isinstance(settings, Mapping) else None
                            nested_layer_id = raw_layer_id if isinstance(raw_layer_id, str) else None
                        yield from self._iter_guid_nodes(
                            item,
                            path=(*path, key, index),
                            layer_id=nested_layer_id,
                        )
