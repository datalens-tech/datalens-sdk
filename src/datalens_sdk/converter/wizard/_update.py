from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import TYPE_CHECKING, cast

from datalens_sdk._runtime.viz_specs import get_viz_spec, validate_placeholder_id
from datalens_sdk._runtime.wizard_field_references import WizardFieldReferences
from datalens_sdk._runtime.wizard_visualization_transitions import validate_visualization_transition
from datalens_sdk.converter.wizard._autofix import _apply_smart_labels_position
from datalens_sdk.converter.wizard._colors import (
    _apply_colors_config,
    _apply_shape_encoding,
    _has_color_split,
)
from datalens_sdk.converter.wizard._common import FieldRef, _dict_with_string_keys, _placeholders_list
from datalens_sdk.converter.wizard._decorations import (
    _apply_item_mutations,
    _apply_measure_formats,
    _apply_pending_filters,
    _apply_sort_direction_items,
    _enrich_chart_local_fields,
    _merge_local_fields_into_snapshot,
    build_hierarchy_object,
)
from datalens_sdk.converter.wizard._layers import _hierarchies_map, _local_fields_map
from datalens_sdk.converter.wizard._normalizer import _Normalizer
from datalens_sdk.converter.wizard._placeholders import _enrich_placeholder, _sync_axis_mode_map
from datalens_sdk.domain.chart_types import MeasureFormat
from datalens_sdk.domain.wizard_chart import resolve_field_snapshot
from datalens_sdk.errors import DatalensConfigurationError, DatalensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.wizard_chart import WizardChartUpdate

# Wire keys written by data_fields_edits where an empty list from the caller
# means "clear this key" rather than "leave existing value unchanged".
_CLEARABLE_DATA_FIELDS: frozenset[str] = frozenset({"labels", "colors", "sort", "filters", "segments", "tooltips"})

# A transition rebuilds the visualization from the target specification.  The
# remaining keys are visualization-specific root-level state and therefore
# cannot safely survive without a target-specific migration rule.
_TRANSITION_DISCARDED_DATA_KEYS: frozenset[str] = frozenset(
    {
        "colors",
        "colorsConfig",
        "extraSettings",
        "geopointsConfig",
        "labels",
        "segments",
        "shapes",
        "shapesConfig",
        "tooltips",
    }
)


def _hierarchies_for_update(
    data: Mapping[str, object],
    update: WizardChartUpdate,
) -> dict[str, dict[str, object]]:
    combined: list[Mapping[str, object]] = []
    existing = data.get("hierarchies")
    if isinstance(existing, list):
        combined.extend(h for h in existing if isinstance(h, Mapping))
    combined.extend(update.new_hierarchies)
    return _hierarchies_map(combined)


def _validate_transition_capacity(*, visualization_id: str, placeholder_id: str, items: list[object]) -> None:
    spec = get_viz_spec(visualization_id)
    placeholder_specs = spec.get("placeholders")
    placeholder_spec = placeholder_specs.get(placeholder_id) if isinstance(placeholder_specs, dict) else None
    capacity = placeholder_spec.get("capacity") if isinstance(placeholder_spec, dict) else None
    if isinstance(capacity, int) and capacity >= 0 and len(items) > capacity:
        raise DatalensValidationError(
            "change_visualization_to: transition to "
            f"{visualization_id!r} cannot retain {len(items)} fields in placeholder {placeholder_id!r}; "
            f"its capacity is {capacity}."
        )


def _apply_visualization_transition(data: dict[str, object], update: WizardChartUpdate) -> None:
    source_visualization_id = update.chart.visualization_id
    target_visualization_id = update.visualization_id
    if target_visualization_id is None or target_visualization_id == source_visualization_id:
        return
    if source_visualization_id is None:
        raise DatalensConfigurationError(
            "change_visualization_to: active visualization is missing; fetch a chart with data.visualization.id first."
        )
    transition = validate_visualization_transition(
        method="change_visualization_to",
        source_visualization_id=source_visualization_id,
        target_visualization_id=target_visualization_id,
    )
    source_viz = data.get("visualization")
    if not isinstance(source_viz, dict):
        raise DatalensConfigurationError("change_visualization_to: chart data has no visualization object to migrate.")
    source_placeholders = {
        placeholder_id: placeholder
        for placeholder in _placeholders_list(source_viz)
        if isinstance(placeholder.get("id"), str)
        for placeholder_id in [cast(str, placeholder["id"])]
    }
    target_spec = get_viz_spec(target_visualization_id)
    target_meta = target_spec.get("viz")
    target_placeholder_specs = target_spec.get("placeholders")
    if not isinstance(target_meta, dict) or not isinstance(target_placeholder_specs, dict):
        raise DatalensConfigurationError(
            f"change_visualization_to: target visualization {target_visualization_id!r} has no complete specification."
        )

    retained_items: dict[str, list[object]] = {}
    for source_placeholder_id, target_placeholder_id in transition["placeholder_mapping"]:
        source_placeholder = source_placeholders.get(source_placeholder_id)
        source_items = source_placeholder.get("items") if isinstance(source_placeholder, dict) else []
        items = copy.deepcopy(source_items) if isinstance(source_items, list) else []
        _validate_transition_capacity(
            visualization_id=target_visualization_id,
            placeholder_id=target_placeholder_id,
            items=items,
        )
        retained_items[target_placeholder_id] = items

    migrated_visualization = copy.deepcopy(target_meta)
    migrated_visualization["id"] = target_visualization_id
    migrated_placeholders: list[dict[str, object]] = []
    for placeholder_id, placeholder_spec in target_placeholder_specs.items():
        if not isinstance(placeholder_id, str) or not isinstance(placeholder_spec, dict):
            continue
        placeholder = copy.deepcopy(placeholder_spec)
        placeholder["id"] = placeholder_id
        placeholder["items"] = retained_items.get(placeholder_id, [])
        migrated_placeholders.append(placeholder)
    migrated_visualization["placeholders"] = migrated_placeholders
    data["visualization"] = migrated_visualization
    _sync_axis_mode_map(data)
    for key in _TRANSITION_DISCARDED_DATA_KEYS:
        data.pop(key, None)


def _apply_placeholder_edits(data: dict[str, object], update: WizardChartUpdate) -> None:
    edits = update.placeholder_edits
    if not edits:
        return
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    visualization_id = update.visualization_id or ""
    fields = list(update.chart.fields)
    normalizer = _Normalizer(
        dataset=None,
        local_fields=_local_fields_from_data(data),
        fields=fields,
        hierarchies=_hierarchies_for_update(data, update),
    )
    dataset_ids = data.get("datasetsIds")
    fallback_dataset_id: str | None = None
    if isinstance(dataset_ids, list) and dataset_ids:
        first = dataset_ids[0]
        if isinstance(first, str):
            fallback_dataset_id = first
    existing = {p.get("id"): p for p in _placeholders_list(viz) if isinstance(p.get("id"), str)}
    for builder_pid, items in edits.items():
        actual_id = (
            builder_pid
            if visualization_id == "combined-chart" and builder_pid == "x"
            else validate_placeholder_id(
                method=builder_pid,
                visualization_id=visualization_id,
                placeholder_id=builder_pid,
            )
        )
        normalized = normalizer.normalize(items)
        if fallback_dataset_id:
            for item in normalized:
                # Hierarchy objects must stay exactly 7 keys; injecting
                # datasetId would break the invariant (E1-8KEY).
                if item.get("data_type") == "hierarchy":
                    continue
                if not item.get("datasetId"):
                    item["datasetId"] = fallback_dataset_id
        if visualization_id == "combined-chart" and actual_id == "x":
            layers = viz.get("layers")
            if not isinstance(layers, list):
                raise DatalensConfigurationError("combined-chart x update requires visualization.layers.")
            for layer in layers:
                if not isinstance(layer, dict):
                    continue
                layer_x = next(
                    (placeholder for placeholder in _placeholders_list(layer) if placeholder.get("id") == "x"),
                    None,
                )
                if layer_x is None:
                    raise DatalensConfigurationError("combined-chart layer is missing its x placeholder.")
                layer_x["items"] = copy.deepcopy(normalized)
            continue
        target = existing.get(actual_id)
        if target is not None:
            target["items"] = normalized
        else:
            placeholders = _placeholders_list(viz)
            new_ph = _enrich_placeholder(visualization_id, builder_pid, normalized)
            placeholders.append(new_ph)
            viz["placeholders"] = placeholders
            existing[actual_id] = new_ph


def _apply_dataset_replacement(data: dict[str, object], update: WizardChartUpdate) -> None:
    replacement = update.dataset_replacement
    if replacement is None:
        return
    old_id, new_id = replacement
    dataset_ids = data.get("datasetsIds")
    if not isinstance(dataset_ids, list) or old_id not in dataset_ids:
        raise DatalensValidationError(
            f"replace_dataset(old={old_id!r}, new={new_id!r}) cannot proceed: the chart datasets are {dataset_ids!r}."
        )
    data["datasetsIds"] = [new_id if item == old_id else item for item in dataset_ids]
    references = WizardFieldReferences(data)
    references.replace_dataset(old_id, new_id)
    references.assert_dataset_absent(old_id)


def _apply_filter_deletions(data: dict[str, object], update: WizardChartUpdate) -> None:
    deleted = update.deleted_filter_guids
    if not deleted:
        return
    filters = data.get("filters")
    if not isinstance(filters, list):
        return
    data["filters"] = [f for f in filters if not (isinstance(f, dict) and _filter_field_guid(f) in deleted)]


def _filter_field_guid(filter_item: Mapping[str, object]) -> str | None:
    for key in ("guid",):
        value = filter_item.get(key)
        if isinstance(value, str) and value:
            return value
    field = filter_item.get("field")
    if isinstance(field, Mapping):
        guid = field.get("guid")
        if isinstance(guid, str) and guid:
            return guid
    return None


def _merge_settings(existing: Mapping[str, object], edits: Mapping[str, object]) -> dict[str, object]:
    merged = dict(existing)
    for key, value in edits.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_settings(current, value)
        else:
            merged[key] = value
    return merged


def _apply_extra_settings_edits(data: dict[str, object], update: WizardChartUpdate) -> None:
    edits = update.extra_settings_edits
    if not edits:
        return
    existing = data.get("extraSettings")
    existing_settings = existing if isinstance(existing, Mapping) else {}
    data["extraSettings"] = _merge_settings(existing_settings, edits)


def _apply_ph_settings_edits(data: dict[str, object], update: WizardChartUpdate) -> None:
    edits = update.ph_settings_edits
    if not edits:
        return
    visualization_id = update.visualization_id or ""
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    existing: dict[str, dict[str, object]] = {
        p.get("id"): p  # type: ignore[misc]
        for p in _placeholders_list(viz)
        if isinstance(p.get("id"), str)
    }
    for builder_pid, settings in edits.items():
        actual_id = validate_placeholder_id(
            method="placeholder settings",
            visualization_id=visualization_id,
            placeholder_id=builder_pid,
        )
        target = existing.get(actual_id)
        if target is None:
            raise DatalensConfigurationError(
                f"placeholder settings: placeholder {actual_id!r} is declared for active visualization "
                f"{visualization_id!r} but is absent from the chart payload."
            )
        ph_settings_dict = target.get("settings")
        if not isinstance(ph_settings_dict, dict):
            ph_settings_dict = {}
            target["settings"] = ph_settings_dict
        ph_settings_dict.update(settings)


def _apply_data_fields_edits(data: dict[str, object], update: WizardChartUpdate) -> None:
    edits = update.data_fields_edits
    if not edits:
        return
    fields = list(update.chart.fields)
    normalizer = _Normalizer(dataset=None, local_fields=_local_fields_from_data(data), fields=fields)
    dataset_ids = data.get("datasetsIds")
    fallback_dataset_id: str | None = None
    if isinstance(dataset_ids, list) and dataset_ids:
        first = dataset_ids[0]
        if isinstance(first, str):
            fallback_dataset_id = first
    for wire_key, field_refs in edits.items():
        normalized = normalizer.normalize(field_refs)
        if fallback_dataset_id:
            for item in normalized:
                # Hierarchy objects must stay exactly 7 keys; skip injection
                # (E1-8KEY mirrors the same guard in _apply_placeholder_edits).
                if item.get("data_type") == "hierarchy":
                    continue
                if not item.get("datasetId"):
                    item["datasetId"] = fallback_dataset_id
        if normalized:
            data[wire_key] = normalized
        elif wire_key in _CLEARABLE_DATA_FIELDS:
            # Empty list from the caller means "clear this field" (e.g. labels([])).
            # Writing [] lets _apply_smart_labels_position short-circuit on the
            # falsy value rather than mutating extraSettings as a side-effect
            # against the user's explicit clear intent (E3-LABELS-NOOP).
            data[wire_key] = []


def _local_fields_from_data(data: Mapping[str, object]) -> dict[str, dict[str, object]]:
    updates = data.get("updates")
    if not isinstance(updates, list):
        return {}
    add_field_dicts: list[Mapping[str, object]] = []
    for operation in updates:
        if not isinstance(operation, Mapping) or operation.get("action") != "add_field":
            continue
        field = operation.get("field")
        if isinstance(field, Mapping):
            add_field_dicts.append(_dict_with_string_keys(field))
    # Index by guid AND title (mirror _local_fields_map) so local fields added on
    # update resolve by title too — e.g. add_local_field(title="X").columns(["X"]).
    return _local_fields_map(add_field_dicts)


def _apply_local_field_additions(
    data: dict[str, object],
    update: WizardChartUpdate,
    dataset_id: str | None,
) -> None:
    """Merge ``update.local_field_additions`` into ``data``.

    Runs first in ``_apply_update_operations`` so newly added local fields are
    visible to every subsequent ref-resolving normalizer (P1-RACE: callers can
    ``.add_local_field(...).add_sort(guid)`` in a single update). Existing
    ``data["updates"]`` entries are preserved via ``setdefault`` (P1-UPDATES);
    guid collisions with existing ``add_field`` operations raise
    ``DatalensValidationError`` (P1-DROP, no silent drop); the
    ``datasetsPartialFields`` snapshot is merged with the new entries prepended.
    """
    additions = update.local_field_additions
    if not additions:
        return
    updates = data.setdefault("updates", [])
    if not isinstance(updates, list):
        return
    existing_add_field_guids: set[object] = set()
    for op in updates:
        if not isinstance(op, dict) or op.get("action") != "add_field":
            continue
        field = op.get("field")
        if isinstance(field, dict):
            existing_add_field_guids.add(field.get("guid"))
    for entry in additions:
        guid = entry.get("guid")
        if guid in existing_add_field_guids:
            raise DatalensValidationError(
                f"add_local_field: a local field with guid {guid!r} already exists in the chart. "
                "Pass a different guid= or remove the existing field first."
            )
        field = dict(entry)
        if dataset_id and not field.get("datasetId"):
            field["datasetId"] = dataset_id
        updates.append({"action": "add_field", "field": field})
        existing_add_field_guids.add(guid)
    existing_snapshot = data.get("datasetsPartialFields")
    snapshot = cast("list[list[dict[str, object]]]", existing_snapshot) if isinstance(existing_snapshot, list) else []
    data["datasetsPartialFields"] = _merge_local_fields_into_snapshot(snapshot, additions)


def _apply_formula_replacements(data: dict[str, object], update: WizardChartUpdate) -> None:
    replacements = update.formula_replacements
    if not replacements:
        return
    updates = data.get("updates")
    if not isinstance(updates, list):
        return
    for operation in updates:
        if not isinstance(operation, dict) or operation.get("action") != "add_field":
            continue
        field = operation.get("field")
        if not isinstance(field, dict):
            continue
        guid = field.get("guid")
        if isinstance(guid, str) and guid in replacements:
            field["formula"] = replacements[guid]


def _has_update_mutations(update: WizardChartUpdate) -> bool:
    return any(
        (
            update.placeholder_edits,
            update.extra_settings_edits,
            update.ph_settings_edits,
            update.data_fields_edits,
            update.field_replacements,
            update.deleted_field_guids,
            update.deleted_filter_guids,
            update.dataset_replacement,
            update.item_mutations,
            update.pending_filters,
            update.sort_direction_items,
            update.colors_palette is not None,
            update.color_encoding is not None,
            update.pending_measure_formats,
            update.geopoints_config,
            update.shape_encoding is not None,
            update.formula_replacements,
            update.description_value is not None,
            update.visualization_id != update.chart.visualization_id,
            update.new_hierarchies,
            update.local_field_additions,
        )
    )


def _refuse_orphaning_publish(update: WizardChartUpdate) -> None:
    if update.mode_value != "publish" or _has_update_mutations(update):
        return
    raw = update.chart.raw
    published_id = raw.get("publishedId")
    saved_id = raw.get("savedId")
    revision_id = raw.get("revId")
    if not isinstance(published_id, str) or not isinstance(saved_id, str) or not isinstance(revision_id, str):
        return
    if saved_id != published_id and revision_id == published_id:
        raise DatalensConfigurationError(
            "Cannot publish a loaded published revision while a newer saved draft exists without chart changes. "
            "Load the saved draft first or include changes."
        )


def _has_color_update_intentions(update: WizardChartUpdate) -> bool:
    return update.colors_palette is not None or update.color_encoding is not None


def _apply_hierarchies_update(
    data: dict[str, object],
    update: WizardChartUpdate,
    normalizer: _Normalizer,
) -> None:
    new_hierarchies = update.new_hierarchies
    if not new_hierarchies:
        return
    existing = data.get("hierarchies")
    result: list[object] = (
        [dict(h) if isinstance(h, dict) else h for h in existing] if isinstance(existing, list) else []
    )
    guid_to_idx: dict[object, int] = {
        cast("str | None", h.get("guid")): i for i, h in enumerate(result) if isinstance(h, dict)
    }
    new_by_guid: dict[object, dict[str, object]] = {}
    for spec in new_hierarchies:
        obj = build_hierarchy_object(spec, normalizer)
        guid = obj.get("guid")
        new_by_guid[guid] = obj
        if guid in guid_to_idx:
            result[guid_to_idx[guid]] = obj  # replace (dedup by guid)
        else:
            guid_to_idx[guid] = len(result)
            result.append(obj)
    data["hierarchies"] = result
    # Sync existing placeholder mounts by guid (position preserved, object refreshed).
    viz = data.get("visualization")
    if isinstance(viz, dict):
        for ph in _placeholders_list(viz):
            items = ph.get("items")
            if not isinstance(items, list):
                continue
            for i, item in enumerate(items):
                if isinstance(item, dict) and item.get("data_type") == "hierarchy" and item.get("guid") in new_by_guid:
                    items[i] = copy.deepcopy(new_by_guid[item["guid"]])


def _resolve_replacement_snapshot(
    data: Mapping[str, object],
    update: WizardChartUpdate,
    field: FieldRef,
) -> dict[str, object]:
    snapshot = resolve_field_snapshot(
        field,
        fields=list(update.chart.fields),
        local_fields=_local_fields_from_data(data),
    )
    if not snapshot.get("datasetId"):
        dataset_ids = data.get("datasetsIds")
        if isinstance(dataset_ids, list):
            string_ids = [dataset_id for dataset_id in dataset_ids if isinstance(dataset_id, str)]
            if len(string_ids) == 1:
                snapshot["datasetId"] = string_ids[0]
    return snapshot


def _apply_structural_field_mutations(
    data: dict[str, object],
    update: WizardChartUpdate,
) -> tuple[frozenset[str], frozenset[str]]:
    references = WizardFieldReferences(data)
    replacement_targets: set[str] = set()
    refreshed_guids: set[str] = set()
    deleted = update.deleted_field_guids
    for guid in deleted:
        references.delete_field(guid)

    local_fields = _local_fields_from_data(data)
    for old_guid, staged_replacement in update.aggregation_field_replacements.items():
        if old_guid in deleted:
            continue
        replacement_guid = staged_replacement.get("guid")
        if not isinstance(replacement_guid, str):
            raise DatalensValidationError(
                f"change_aggregation staged an invalid replacement guid for field {old_guid!r}."
            )
        replacement = local_fields.get(replacement_guid)
        if replacement is None:
            raise DatalensValidationError(
                f"change_aggregation could not resolve its staged replacement for field {old_guid!r}."
            )
        references.replace_field(old_guid, replacement)
        replacement_targets.add(replacement_guid)

    for old_guid, field in update.field_replacements.items():
        if old_guid in deleted:
            continue
        replacement = _resolve_replacement_snapshot(data, update, field)
        references.replace_field(old_guid, replacement)
        replacement_guid = replacement.get("guid")
        if isinstance(replacement_guid, str):
            replacement_targets.add(replacement_guid)
            if replacement_guid == old_guid:
                refreshed_guids.add(old_guid)
    return frozenset(replacement_targets), frozenset(refreshed_guids)


def _assert_structural_field_invariants(
    data: dict[str, object],
    update: WizardChartUpdate,
    *,
    replacement_targets: frozenset[str],
    refreshed_guids: frozenset[str],
) -> None:
    stale_guids = (
        (update.deleted_field_guids - replacement_targets)
        | (update.field_replacements.keys() - refreshed_guids)
        | update.aggregation_field_replacements.keys()
    )
    references = WizardFieldReferences(data)
    for guid in sorted(stale_guids):
        references.assert_guid_absent(guid)


def _apply_update_operations(data: dict[str, object], update: WizardChartUpdate) -> None:
    dataset_ids = data.get("datasetsIds")
    initial_dataset_id = (
        dataset_ids[0] if isinstance(dataset_ids, list) and dataset_ids and isinstance(dataset_ids[0], str) else None
    )
    # Local-field additions run first so every subsequent ref-resolving
    # normalizer (placeholders/data_fields/main) sees them via
    # _local_fields_from_data(data) (P1-RACE).
    _apply_local_field_additions(data, update, initial_dataset_id)
    _apply_visualization_transition(data, update)
    replacement_targets, refreshed_guids = _apply_structural_field_mutations(data, update)
    _apply_placeholder_edits(data, update)
    _apply_extra_settings_edits(data, update)
    _apply_ph_settings_edits(data, update)
    _apply_data_fields_edits(data, update)
    _apply_dataset_replacement(data, update)
    _apply_filter_deletions(data, update)

    # Re-read dataset_id after _apply_dataset_replacement so that any
    # subsequent operations (filter/sort additions) use the new id, not the
    # stale pre-replacement value (P1-STALE).
    post_replacement_ids = data.get("datasetsIds")
    dataset_id = (
        post_replacement_ids[0]
        if isinstance(post_replacement_ids, list) and post_replacement_ids and isinstance(post_replacement_ids[0], str)
        else None
    )

    fields = list(update.chart.fields)
    normalizer = _Normalizer(
        dataset=None,
        local_fields=_local_fields_from_data(data),
        fields=fields,
        hierarchies=_hierarchies_for_update(data, update),
    )
    _apply_hierarchies_update(data, update, normalizer)
    _apply_shape_encoding(
        data,
        shape_encoding=update.shape_encoding,
        visualization_id=update.visualization_id or "",
        normalizer=normalizer,
    )
    if _has_color_update_intentions(update):
        _apply_colors_config(
            data,
            colors_palette=update.colors_palette,
            color_encoding=update.color_encoding,
            visualization_id=update.visualization_id,
            normalizer=normalizer,
        )
    _apply_item_mutations(data, list(update.item_mutations))
    _apply_measure_formats(data, cast(list[tuple[FieldRef, MeasureFormat]], update.pending_measure_formats))
    _apply_pending_filters(data, list(update.pending_filters), normalizer, dataset_id)
    _apply_sort_direction_items(data, list(update.sort_direction_items), normalizer, dataset_id)
    if update.geopoints_config:
        existing_geopoints = data.get("geopointsConfig")
        geopoints_config = dict(existing_geopoints) if isinstance(existing_geopoints, dict) else {}
        geopoints_config.update(update.geopoints_config)
        data["geopointsConfig"] = geopoints_config
    if "labels" in update.data_fields_edits:
        viz_id = update.visualization_id or update.chart.visualization_id or ""
        _apply_smart_labels_position(data, viz_id, has_colors=_has_color_split(data, update.explicit_colors))
    _apply_formula_replacements(data, update)
    _enrich_chart_local_fields(data)
    if update.dataset_replacement is not None:
        old_dataset_id, new_dataset_id = update.dataset_replacement
        references = WizardFieldReferences(data)
        references.replace_dataset(old_dataset_id, new_dataset_id)
        references.assert_dataset_absent(old_dataset_id)
    _assert_structural_field_invariants(
        data,
        update,
        replacement_targets=replacement_targets,
        refreshed_guids=refreshed_guids,
    )
