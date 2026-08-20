from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from datalens_sdk._runtime.wizard_field_references import WizardFieldReferences
from datalens_sdk._runtime.wizard_semantics import (
    get_wizard_visualization_semantics,
    validate_slot_name,
    validate_visualization_transition,
)
from datalens_sdk.converter.wizard._assemble import (
    _UPDATE_FIELD_KEYS,
    _apply_color_encoding,
    _apply_implicit_measure_names,
    _apply_item_mutations,
    _apply_label_mode,
    _apply_labels_position,
    _apply_measure_formats,
    _apply_palette_to_visualization,
    _apply_shape_encoding,
    _chart_settings_structure,
    _default_slot_settings,
    _iter_visualization_slots,
    _json_object,
    _layer_slot,
    _layer_slot_settings_structure,
    _normalize_fields,
    _project_field,
    _selected_layer,
    _slot_settings_structure,
    _sync_axis_modes,
    _validate_structural_settings,
    _without_field_decorations,
)
from datalens_sdk.converter.wizard._normalizer import _hierarchies_map, _local_fields_map, _Normalizer
from datalens_sdk.converter.wizard._types import WizardJsonObject, WizardVisualizationStructure
from datalens_sdk.domain.wizard_chart import resolve_field_snapshot
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError
from datalens_sdk.serialization.json_types import JsonValue

if TYPE_CHECKING:
    from datalens_sdk.domain.wizard_chart import WizardChartUpdate


def _sources(data: WizardJsonObject) -> WizardJsonObject:
    value = data.get("sources")
    if not isinstance(value, dict):
        raise DataLensConfigurationError("Wizard V1 config requires a sources object.")
    return value


def _visualization(data: WizardJsonObject) -> WizardJsonObject:
    value = data.get("visualization")
    if not isinstance(value, dict):
        raise DataLensConfigurationError("Wizard V1 config requires a visualization object.")
    return value


def _known_visualization(data: WizardJsonObject, *, mutation_requested: bool) -> WizardJsonObject:
    visualization = _visualization(data)
    visualization_type = visualization.get("type")
    semantics = get_wizard_visualization_semantics(visualization_type) if isinstance(visualization_type, str) else None
    if mutation_requested and semantics is None:
        raise DataLensConfigurationError(
            f"Typed Wizard V1 updates require a known visualization; got {visualization_type!r}."
        )
    return visualization


def _slots_for_edit(visualization: WizardJsonObject, slot_name: str) -> list[WizardJsonObject]:
    visualization_type = visualization.get("type")
    if visualization_type not in {"combined-chart", "geolayer"}:
        return [_slot(visualization, slot_name)]
    layers = visualization.get("layers")
    if visualization_type == "combined-chart" and slot_name == "x":
        if not isinstance(layers, list) or not layers:
            raise DataLensConfigurationError("Wizard combined-chart visualization requires layers.")
        return [_layer_slot(layer, slot_name) for layer in layers if isinstance(layer, dict)]
    return [_layer_slot(_selected_layer(visualization), slot_name)]


def _dataset_ids(data: WizardJsonObject) -> list[JsonValue]:
    value = _sources(data).get("datasetsIds")
    if not isinstance(value, list):
        raise DataLensConfigurationError("Wizard V1 config requires sources.datasetsIds.")
    return value


def _primary_dataset_id(data: WizardJsonObject) -> str | None:
    return next((item for item in _dataset_ids(data) if isinstance(item, str)), None)


def _local_fields_from_data(data: WizardJsonObject) -> dict[str, dict[str, object]]:
    updates = _sources(data).get("updates")
    if not isinstance(updates, list):
        return {}
    fields: list[Mapping[str, object]] = []
    for operation in updates:
        if not isinstance(operation, Mapping) or operation.get("action") not in {
            "add",
            "add_field",
            "update",
            "update_field",
        }:
            continue
        field = operation.get("field")
        if isinstance(field, Mapping):
            fields.append(field)
    return _local_fields_map(fields)


def _hierarchies_for_update(
    data: WizardJsonObject,
    update: WizardChartUpdate,
) -> dict[str, dict[str, object]]:
    combined: list[Mapping[str, object]] = []
    existing = _sources(data).get("hierarchies")
    if isinstance(existing, list):
        combined.extend(item for item in existing if isinstance(item, Mapping))
    combined.extend(update.new_hierarchies)
    return _hierarchies_map(combined)


def _normalizer(data: WizardJsonObject, update: WizardChartUpdate) -> _Normalizer:
    return _Normalizer(
        dataset=None,
        local_fields=_local_fields_from_data(data),
        fields=list(update.chart.fields),
        hierarchies=_hierarchies_for_update(data, update),
        dataset_replacement=update.dataset_replacement,
    )


def _slot(visualization: WizardJsonObject, slot_name: str) -> WizardJsonObject:
    visualization_type = visualization.get("type")
    if not isinstance(visualization_type, str):
        raise DataLensConfigurationError("Wizard V1 visualization requires a string type discriminator.")
    canonical_name = validate_slot_name(
        method="Wizard update",
        visualization_type=visualization_type,
        slot_name=slot_name,
    )
    value = visualization.get(canonical_name)
    if value is None:
        value = {"items": []}
        visualization[canonical_name] = value
    if not isinstance(value, dict):
        raise DataLensConfigurationError(f"Wizard V1 visualization.{canonical_name} must be an object.")
    items = value.get("items")
    if not isinstance(items, list):
        raise DataLensConfigurationError(f"Wizard V1 visualization.{canonical_name}.items must be an array.")
    return value


def _apply_local_field_additions(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    additions = update.local_field_additions
    if not additions:
        return
    sources = _sources(data)
    updates = sources.setdefault("updates", [])
    if not isinstance(updates, list):
        raise DataLensConfigurationError("Wizard V1 sources.updates must be an array.")
    existing_guids: set[str] = set()
    for operation in updates:
        field = operation.get("field") if isinstance(operation, Mapping) else None
        existing_guid = field.get("guid") if isinstance(field, Mapping) else None
        if isinstance(existing_guid, str):
            existing_guids.add(existing_guid)
    dataset_id = _primary_dataset_id(data)
    for addition in additions:
        addition_guid = addition.get("guid")
        if addition_guid in existing_guids:
            raise DataLensValidationError(f"add_local_field: field guid {addition_guid!r} already exists in the chart.")
        field = _json_object(
            {key: value for key, value in addition.items() if key in _UPDATE_FIELD_KEYS},
            context="Wizard local field",
        )
        if dataset_id is not None and "datasetId" not in field:
            field["datasetId"] = dataset_id
        updates.append(_json_object({"action": "add_field", "field": field}, context="Wizard field update"))
        if isinstance(addition_guid, str):
            existing_guids.add(addition_guid)


def _apply_slot_edits(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if not update.slot_edits:
        return
    visualization = _known_visualization(data, mutation_requested=True)
    normalizer = _normalizer(data, update)
    dataset_id = _primary_dataset_id(data)
    for slot_name, refs in update.slot_edits.items():
        normalized = normalizer.normalize(refs)
        for target in _slots_for_edit(visualization, slot_name):
            target["items"] = [_project_field(item, dataset_id=dataset_id) for item in normalized]
            settings = target.get("settings")
            if isinstance(settings, Mapping) and "axisModeMap" in settings:
                _sync_axis_modes(target, normalized)
    if visualization.get("type") not in {"combined-chart", "geolayer"} and (
        "colors" not in update.slot_edits and update.color_encoding is None
    ):
        _apply_implicit_measure_names(visualization)


def _apply_chart_settings(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    edits = update.chart_settings_edits
    if not edits:
        return
    visualization = _known_visualization(data, mutation_requested=True)
    current = visualization.get("chartSettings")
    settings = current if isinstance(current, dict) else {}
    _merge_settings(settings, edits)
    visualization["chartSettings"] = settings


def _merge_settings(current: WizardJsonObject, edits: Mapping[str, object]) -> None:
    for key, value in _json_object(edits, context="Wizard slot settings").items():
        existing = current.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _merge_settings(existing, value)
        else:
            current[key] = value


def _apply_slot_settings(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if not update.slot_settings_edits:
        return
    visualization = _known_visualization(data, mutation_requested=True)
    for slot_name, edits in update.slot_settings_edits.items():
        for target in _slots_for_edit(visualization, slot_name):
            current = target.get("settings")
            settings = current if isinstance(current, dict) else {}
            _merge_settings(settings, edits)
            target["settings"] = settings


def _apply_dataset_replacement(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    replacement = update.dataset_replacement
    if replacement is None:
        return
    old_id, new_id = replacement
    dataset_ids = _dataset_ids(data)
    if old_id not in dataset_ids:
        raise DataLensValidationError(
            f"replace_dataset(old={old_id!r}, new={new_id!r}) cannot proceed: the chart datasets are {dataset_ids!r}."
        )
    replaced_ids: list[JsonValue] = [new_id if item == old_id else item for item in dataset_ids]
    _sources(data)["datasetsIds"] = replaced_ids
    references = WizardFieldReferences(data)
    references.replace_dataset(old_id, new_id)
    references.assert_dataset_absent(old_id)


def _apply_filter_deletions(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if not update.deleted_filter_guids:
        return
    sources = _sources(data)
    filters = sources.get("filters")
    if not isinstance(filters, list):
        return
    sources["filters"] = [
        item for item in filters if not (isinstance(item, Mapping) and item.get("guid") in update.deleted_filter_guids)
    ]


def _resolve_replacement(
    data: WizardJsonObject,
    update: WizardChartUpdate,
    field: object,
) -> WizardJsonObject:
    snapshot = resolve_field_snapshot(
        field,  # type: ignore[arg-type]
        fields=list(update.chart.fields),
        local_fields=_local_fields_from_data(data),
    )
    return _project_field(snapshot, dataset_id=_primary_dataset_id(data))


def _apply_structural_field_mutations(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    references = WizardFieldReferences(data)
    deleted = update.deleted_field_guids
    for guid in deleted:
        references.delete_field(guid)

    local_fields = _local_fields_from_data(data)
    for old_guid, staged in update.aggregation_field_replacements.items():
        if old_guid in deleted:
            continue
        replacement_guid = staged.get("guid")
        replacement = local_fields.get(replacement_guid) if isinstance(replacement_guid, str) else None
        if replacement is None:
            raise DataLensValidationError(
                f"change_aggregation could not resolve its staged replacement for field {old_guid!r}."
            )
        references.replace_field(
            old_guid,
            _project_field(replacement, dataset_id=_primary_dataset_id(data)),
        )

    for old_guid, field in update.field_replacements.items():
        if old_guid not in deleted:
            references.replace_field(old_guid, _resolve_replacement(data, update, field))


def _apply_hierarchies(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if not update.new_hierarchies:
        return
    sources = _sources(data)
    current = sources.get("hierarchies")
    hierarchies = list(current) if isinstance(current, list) else []
    positions = {
        item.get("guid"): index
        for index, item in enumerate(hierarchies)
        if isinstance(item, Mapping) and isinstance(item.get("guid"), str)
    }
    normalizer = _normalizer(data, update).for_hierarchy_fields()
    dataset_id = _primary_dataset_id(data)
    visualization = _known_visualization(data, mutation_requested=True)
    for spec in update.new_hierarchies:
        refs = spec.get("fields")
        fields = _normalize_fields(
            normalizer,
            list(refs) if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)) else [],
            dataset_id=dataset_id,
        )
        source_hierarchy = _json_object(
            {
                "guid": spec.get("guid"),
                "title": spec.get("title"),
                "fields": [{"guid": item.get("guid"), "datasetId": item.get("datasetId")} for item in fields],
            },
            context="Wizard hierarchy",
        )
        guid = source_hierarchy.get("guid")
        if guid in positions:
            hierarchies[positions[guid]] = source_hierarchy
        else:
            positions[guid] = len(hierarchies)
            hierarchies.append(source_hierarchy)

        mounted = _json_object(
            {**source_hierarchy, "data_type": "hierarchy"},
            context="Wizard hierarchy field",
        )
        for slot in _iter_visualization_slots(visualization):
            items = slot.get("items")
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if isinstance(item, Mapping) and item.get("guid") == guid and item.get("data_type") == "hierarchy":
                    items[index] = mounted.copy()
    sources["hierarchies"] = hierarchies


def _apply_filters_and_sort(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    normalizer = _normalizer(data, update)
    dataset_id = _primary_dataset_id(data)
    if update.pending_filters:
        sources = _sources(data)
        filters = sources.setdefault("filters", [])
        if not isinstance(filters, list):
            raise DataLensConfigurationError("Wizard V1 sources.filters must be an array.")
        for ref, operation, values in update.pending_filters:
            item = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0]
            filter_value: WizardJsonObject = {"operation": {"code": operation}}
            if values:
                filter_value["value"] = list(values)
            filter_item: WizardJsonObject = {
                "guid": item["guid"],
                "datasetId": item["datasetId"],
                "filter": filter_value,
            }
            if "fakeTitle" in item:
                filter_item["fakeTitle"] = item["fakeTitle"]
            filters.append(filter_item)
    if update.sort_direction_items:
        visualization = _known_visualization(data, mutation_requested=True)
        sort_slot = _slots_for_edit(visualization, "sort")[0]
        items = sort_slot["items"]
        if not isinstance(items, list):
            raise AssertionError("Wizard sort slot items were narrowed to a list")
        for ref, direction in update.sort_direction_items:
            item = _without_field_decorations(_normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0])
            item["direction"] = direction.upper()
            items.append(item)


def _apply_encodings_and_decorations(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    visualization = _known_visualization(data, mutation_requested=True)
    normalizer = _normalizer(data, update)
    dataset_id = _primary_dataset_id(data)
    if visualization.get("type") in {"combined-chart", "geolayer"} and any(
        (update.color_encoding is not None, update.colors_palette is not None, update.shape_encoding is not None)
    ):
        raise DataLensConfigurationError("Layered Wizard V1 encodings must be configured by add_layer().")
    if update.color_encoding is not None:
        _apply_color_encoding(
            visualization,
            update.color_encoding,
            normalizer=normalizer,
            dataset_id=dataset_id,
            palette=update.colors_palette,
        )
    elif update.colors_palette is not None:
        _apply_palette_to_visualization(
            visualization,
            update.colors_palette,
            normalizer=normalizer,
        )
    if update.shape_encoding is not None:
        _apply_shape_encoding(
            visualization,
            update.shape_encoding,
            normalizer=normalizer,
            dataset_id=dataset_id,
        )
    _apply_item_mutations(
        visualization,
        update.item_mutations,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )
    _apply_measure_formats(
        visualization,
        update.pending_measure_formats,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )


def _apply_formula_replacements(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if not update.formula_replacements:
        return
    updates = _sources(data).get("updates")
    if not isinstance(updates, list):
        return
    for operation in updates:
        if not isinstance(operation, Mapping):
            continue
        field = operation.get("field")
        if not isinstance(field, dict):
            continue
        guid = field.get("guid")
        if isinstance(guid, str) and guid in update.formula_replacements:
            field["formula"] = update.formula_replacements[guid]


def _apply_visualization_transition(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    target_type = update.target_visualization_type
    if target_type is None:
        return
    source = _visualization(data)
    source_type = source.get("type")
    if not isinstance(source_type, str):
        raise DataLensConfigurationError("change_visualization_to requires a string source visualization type.")
    transition = validate_visualization_transition(
        method="change_visualization_to",
        source_visualization_type=source_type,
        target_visualization_type=target_type,
    )
    target_semantics = get_wizard_visualization_semantics(target_type)
    if target_semantics is None or target_type in {"combined-chart", "geolayer"}:
        raise DataLensConfigurationError(
            f"change_visualization_to target {target_type!r} is not supported by phase 3A."
        )
    target: WizardJsonObject = {"type": target_type}
    for slot_name in target_semantics["slots"]:
        slot: WizardJsonObject = {"items": []}
        settings = _default_slot_settings(target_type, slot_name)
        if settings is not None:
            slot["settings"] = settings
        target[slot_name] = slot
    for source_slot_name, target_slot_name in transition["slot_mapping"]:
        source_slot = source.get(source_slot_name)
        source_items = source_slot.get("items") if isinstance(source_slot, Mapping) else None
        target_slot = target.get(target_slot_name)
        if isinstance(source_items, list) and isinstance(target_slot, dict):
            capacity = target_semantics.get("slot_capacities", {}).get(target_slot_name)
            if capacity is not None and len(source_items) > capacity:
                raise DataLensValidationError(
                    f"change_visualization_to transition to {target_type!r} cannot retain {len(source_items)} "
                    f"items in slot {target_slot_name!r}: capacity is {capacity}."
                )
            target_slot["items"] = list(source_items)
            target_settings = target_slot.get("settings")
            if isinstance(target_settings, Mapping) and "axisModeMap" in target_settings:
                _sync_axis_modes(target_slot, [item for item in source_items if isinstance(item, Mapping)])
    data["visualization"] = target


def _apply_scatter_size(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if not update.geopoints_config:
        return
    visualization = _known_visualization(data, mutation_requested=True)
    if visualization.get("type") != "scatter":
        raise DataLensConfigurationError("point_size_range() is supported only by Wizard V1 scatter visualization.")
    size = _slot(visualization, "size")
    current = size.get("settings")
    settings = current if isinstance(current, dict) else {}
    settings.update(_json_object(update.geopoints_config, context="Wizard scatter size settings"))
    size["settings"] = settings


def _validate_update_structure(
    data: WizardJsonObject,
    update: WizardChartUpdate,
    structure: WizardVisualizationStructure | None,
) -> None:
    if not structure:
        return
    visualization = _known_visualization(data, mutation_requested=True)
    visualization_type = visualization.get("type")
    if not isinstance(visualization_type, str) or visualization_type not in structure:
        raise DataLensConfigurationError(f"Wizard V1 generated structure has no visualization {visualization_type!r}.")
    raw = structure[visualization_type]
    slots = raw.get("slots")
    if not isinstance(slots, Mapping):
        raise DataLensConfigurationError(
            f"Wizard V1 generated structure for visualization {visualization_type!r} has no slots registry."
        )
    layered = visualization_type in {"combined-chart", "geolayer"}
    selected = _selected_layer(visualization) if layered else None
    selected_layer_type = selected.get("type") if selected is not None else None
    raw_layers = raw.get("layers")
    layer_structures = raw_layers if isinstance(raw_layers, Mapping) else {}
    for slot_name in set(update.slot_edits) | set(update.slot_settings_edits):
        canonical_name = (
            slot_name
            if layered
            else validate_slot_name(
                method="Wizard update",
                visualization_type=visualization_type,
                slot_name=slot_name,
            )
        )
        if layered:
            target_layer_types: list[str] = []
            if visualization_type == "combined-chart" and canonical_name == "x":
                layers = visualization.get("layers")
                if isinstance(layers, list):
                    target_layer_types = [
                        layer_type
                        for layer in layers
                        if isinstance(layer, Mapping) and isinstance((layer_type := layer.get("type")), str)
                    ]
            elif isinstance(selected_layer_type, str):
                target_layer_types = [selected_layer_type]
            layer_slots = []
            for layer_type in target_layer_types:
                layer = layer_structures.get(layer_type)
                raw_slots = layer.get("slots") if isinstance(layer, Mapping) else None
                layer_slots.append(raw_slots if isinstance(raw_slots, Mapping) else {})
            if not target_layer_types or any(canonical_name not in slots for slots in layer_slots):
                raise DataLensConfigurationError(
                    f"Wizard V1 visualization {visualization_type!r} has no generated layer slot {canonical_name!r}."
                )
        elif canonical_name not in slots:
            raise DataLensConfigurationError(
                f"Wizard V1 visualization {visualization_type!r} has no generated slot {canonical_name!r}."
            )
    _validate_structural_settings(
        update.chart_settings_edits,
        _chart_settings_structure(visualization_type, structure),
        context=f"Wizard V1 visualization {visualization_type!r}",
    )
    for slot_name, edits in update.slot_settings_edits.items():
        canonical_name = (
            slot_name
            if layered
            else validate_slot_name(
                method="Wizard update",
                visualization_type=visualization_type,
                slot_name=slot_name,
            )
        )
        if layered:
            target_layer_types = []
            if visualization_type == "combined-chart" and canonical_name == "x":
                layers = visualization.get("layers")
                if isinstance(layers, list):
                    target_layer_types = [
                        layer_type
                        for layer in layers
                        if isinstance(layer, Mapping) and isinstance((layer_type := layer.get("type")), str)
                    ]
            elif isinstance(selected_layer_type, str):
                target_layer_types = [selected_layer_type]
            for layer_type in target_layer_types:
                _validate_structural_settings(
                    edits,
                    _layer_slot_settings_structure(
                        visualization_type,
                        layer_type,
                        canonical_name,
                        structure,
                    ),
                    context=(
                        f"Wizard V1 visualization {visualization_type!r} layer {layer_type!r} slot {canonical_name!r}"
                    ),
                )
        else:
            _validate_structural_settings(
                edits,
                _slot_settings_structure(visualization_type, canonical_name, structure),
                context=f"Wizard V1 visualization {visualization_type!r} slot {canonical_name!r}",
            )


def _has_update_mutations(update: WizardChartUpdate) -> bool:
    return any(
        (
            update.slot_edits,
            update.chart_settings_edits,
            update.slot_settings_edits,
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
            update.shape_encoding is not None,
            update.formula_replacements,
            update.new_hierarchies,
            update.local_field_additions,
            update.geopoints_config,
            update.label_mode_value is not None,
            update.labels_position_value is not None,
            update.target_visualization_type is not None,
        )
    )


def _refuse_orphaning_publish(update: WizardChartUpdate) -> None:
    if update.mode_value != "publish" or _has_update_mutations(update):
        return
    raw = update.chart.raw
    published_id = raw.get("publishedId")
    saved_id = raw.get("savedId")
    revision_id = raw.get("revId")
    if (
        all(isinstance(value, str) for value in (published_id, saved_id, revision_id))
        and saved_id != published_id
        and revision_id == published_id
    ):
        raise DataLensConfigurationError(
            "Cannot publish a loaded published revision while a newer saved draft exists without chart changes. "
            "Load the saved draft first or include changes."
        )


def _apply_update_operations(
    data: WizardJsonObject,
    update: WizardChartUpdate,
    *,
    visualization_structure: WizardVisualizationStructure | None = None,
) -> None:
    mutation_requested = _has_update_mutations(update)
    _sources(data)
    _known_visualization(data, mutation_requested=mutation_requested)
    if not mutation_requested:
        return

    _apply_visualization_transition(data, update)
    _validate_update_structure(data, update, visualization_structure)
    _apply_local_field_additions(data, update)
    _apply_structural_field_mutations(data, update)
    _apply_slot_edits(data, update)
    _apply_chart_settings(data, update)
    _apply_slot_settings(data, update)
    visualization = _known_visualization(data, mutation_requested=True)
    decoration_target = (
        _selected_layer(visualization) if visualization.get("type") in {"combined-chart", "geolayer"} else visualization
    )
    _apply_label_mode(decoration_target, update.label_mode_value)
    _apply_labels_position(decoration_target, update.labels_position_value)
    _apply_dataset_replacement(data, update)
    _apply_filter_deletions(data, update)
    _apply_hierarchies(data, update)
    _apply_filters_and_sort(data, update)
    _apply_encodings_and_decorations(data, update)
    _apply_scatter_size(data, update)
    _apply_formula_replacements(data, update)

    references = WizardFieldReferences(data)
    stale_guids = (
        set(update.deleted_field_guids) | set(update.field_replacements) | set(update.aggregation_field_replacements)
    )
    for guid in stale_guids:
        references.assert_guid_absent(guid)
    if update.dataset_replacement is not None:
        references.assert_dataset_absent(update.dataset_replacement[0])
