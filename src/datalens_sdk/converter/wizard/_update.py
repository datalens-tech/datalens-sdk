from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from datalens_sdk._runtime.wizard_field_references import WizardFieldReferences
from datalens_sdk.converter.wizard._assemble import (
    _CHART_SETTING_KEYS,
    _LINE_SLOTS,
    _UPDATE_FIELD_KEYS,
    _apply_color_encoding,
    _apply_implicit_measure_names,
    _apply_item_mutations,
    _apply_measure_formats,
    _apply_palette_to_visualization,
    _apply_shape_encoding,
    _json_object,
    _normalize_fields,
    _project_field,
    _sync_x_axis_modes,
)
from datalens_sdk.converter.wizard._normalizer import _hierarchies_map, _local_fields_map, _Normalizer
from datalens_sdk.converter.wizard._types import WizardJsonObject
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


def _line_visualization(data: WizardJsonObject, *, mutation_requested: bool) -> WizardJsonObject:
    visualization = _visualization(data)
    visualization_type = visualization.get("type")
    if mutation_requested and visualization_type != "line":
        raise DataLensConfigurationError(
            f"Typed phase-1 updates require Wizard V1 visualization.type == 'line'; got {visualization_type!r}."
        )
    return visualization


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
    )


def _slot(visualization: WizardJsonObject, slot_name: str) -> WizardJsonObject:
    if slot_name not in _LINE_SLOTS:
        raise DataLensConfigurationError(f"Line visualization has no {slot_name!r} slot in Wizard V1.")
    value = visualization.get(slot_name)
    if value is None:
        value = {"items": []}
        visualization[slot_name] = value
    if not isinstance(value, dict):
        raise DataLensConfigurationError(f"Wizard V1 visualization.{slot_name} must be an object.")
    items = value.get("items")
    if not isinstance(items, list):
        raise DataLensConfigurationError(f"Wizard V1 visualization.{slot_name}.items must be an array.")
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
    visualization = _line_visualization(data, mutation_requested=True)
    normalizer = _normalizer(data, update)
    dataset_id = _primary_dataset_id(data)
    for slot_name, refs in update.slot_edits.items():
        target = _slot(visualization, slot_name)
        normalized = normalizer.normalize(refs)
        target["items"] = [_project_field(item, dataset_id=dataset_id) for item in normalized]
        if slot_name == "x":
            _sync_x_axis_modes(target, normalized)  # type: ignore[arg-type]
    if "colors" not in update.slot_edits and update.color_encoding is None:
        _apply_implicit_measure_names(visualization)  # type: ignore[arg-type]


def _apply_chart_settings(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    edits = update.chart_settings_edits
    if not edits:
        return
    unsupported = set(edits) - _CHART_SETTING_KEYS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise DataLensConfigurationError(f"Line chart settings are not supported by Wizard V1: {names}.")
    visualization = _line_visualization(data, mutation_requested=True)
    current = visualization.get("chartSettings")
    settings = current if isinstance(current, dict) else {}
    settings.update(_json_object(edits, context="Wizard chart settings"))
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
    visualization = _line_visualization(data, mutation_requested=True)
    for slot_name, edits in update.slot_settings_edits.items():
        target = _slot(visualization, slot_name)
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
    visualization = _line_visualization(data, mutation_requested=True)
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
        for slot_name in _LINE_SLOTS:
            slot = visualization.get(slot_name)
            items = slot.get("items") if isinstance(slot, dict) else None
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
        visualization = _line_visualization(data, mutation_requested=True)
        sort_slot = _slot(visualization, "sort")
        items = sort_slot["items"]
        if not isinstance(items, list):
            raise AssertionError("Wizard sort slot items were narrowed to a list")
        for ref, direction in update.sort_direction_items:
            item = _normalize_fields(normalizer, [ref], dataset_id=dataset_id)[0]
            item["direction"] = direction.upper()
            items.append(item)


def _apply_encodings_and_decorations(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    visualization = _line_visualization(data, mutation_requested=True)
    normalizer = _normalizer(data, update)
    dataset_id = _primary_dataset_id(data)
    if update.color_encoding is not None:
        _apply_color_encoding(
            visualization,  # type: ignore[arg-type]
            update.color_encoding,
            normalizer=normalizer,
            dataset_id=dataset_id,
            palette=update.colors_palette,
        )
    elif update.colors_palette is not None:
        _apply_palette_to_visualization(
            visualization,  # type: ignore[arg-type]
            update.colors_palette,
            normalizer=normalizer,
        )
    if update.shape_encoding is not None:
        _apply_shape_encoding(
            visualization,  # type: ignore[arg-type]
            update.shape_encoding,
            normalizer=normalizer,
            dataset_id=dataset_id,
        )
    _apply_item_mutations(
        visualization,  # type: ignore[arg-type]
        update.item_mutations,
        normalizer=normalizer,
        dataset_id=dataset_id,
    )
    _apply_measure_formats(
        visualization,  # type: ignore[arg-type]
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


def _apply_update_operations(data: WizardJsonObject, update: WizardChartUpdate) -> None:
    if update.target_visualization_type is not None:
        raise DataLensConfigurationError(
            "change_visualization_to is preserved for the Phase 3 Wizard document-V1 transition implementation; "
            "Phase 1 refuses this update before an RPC."
        )
    mutation_requested = _has_update_mutations(update)
    _sources(data)
    _line_visualization(data, mutation_requested=mutation_requested)
    if not mutation_requested:
        return
    if update.geopoints_config:
        raise DataLensConfigurationError("Line visualization has no geopoints settings in Wizard V1.")

    _apply_local_field_additions(data, update)
    _apply_structural_field_mutations(data, update)
    _apply_slot_edits(data, update)
    _apply_chart_settings(data, update)
    _apply_slot_settings(data, update)
    _apply_dataset_replacement(data, update)
    _apply_filter_deletions(data, update)
    _apply_hierarchies(data, update)
    _apply_filters_and_sort(data, update)
    _apply_encodings_and_decorations(data, update)
    _apply_formula_replacements(data, update)
