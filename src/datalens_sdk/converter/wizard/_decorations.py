from __future__ import annotations

from collections.abc import Mapping, Sequence
import uuid

from datalens_sdk._runtime.viz_specs import get_placeholder_id
from datalens_sdk.converter.wizard._common import FieldRef, _item_matches_ref, _items_list, _placeholders_list
from datalens_sdk.converter.wizard._normalizer import _Normalizer
from datalens_sdk.domain.chart_types import MeasureFormat
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.errors import DataLensConfigurationError


def _visualization_items(visualization: dict[str, object]) -> list[dict[str, object]]:
    items = [item for placeholder in _placeholders_list(visualization) for item in _items_list(placeholder)]
    layers = visualization.get("layers")
    if not isinstance(layers, list):
        return items
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        items.extend(item for placeholder in _placeholders_list(layer) for item in _items_list(placeholder))
    return items


def _apply_data_fields(
    data: dict[str, object],
    data_fields: dict[str, list[FieldRef]],
    normalizer: _Normalizer,
) -> None:
    for wire_key, fields in data_fields.items():
        if fields:
            data[wire_key] = normalizer.normalize(fields)


def _apply_extra_settings(data: dict[str, object], extra_settings: dict[str, object]) -> None:
    if not extra_settings:
        return
    existing = data.get("extraSettings")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(extra_settings)
    data["extraSettings"] = merged


def _apply_ph_settings(
    data: dict[str, object],
    ph_settings: dict[str, dict[str, object]],
    spec_key: str,
) -> None:
    if not ph_settings:
        return
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    existing: dict[str, dict[str, object]] = {
        p.get("id"): p  # type: ignore[misc]
        for p in _placeholders_list(viz)
        if isinstance(p.get("id"), str)
    }
    for builder_pid, settings in ph_settings.items():
        actual_id = get_placeholder_id(spec_key, builder_pid)
        target = existing.get(actual_id)
        if target is None:
            continue
        ph_settings_dict = target.get("settings")
        if not isinstance(ph_settings_dict, dict):
            ph_settings_dict = {}
            target["settings"] = ph_settings_dict
        ph_settings_dict.update(settings)


def _apply_item_mutations(
    data: dict[str, object],
    mutations: list[tuple[FieldRef, str, object]],
) -> None:
    if not mutations:
        return
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    all_items = _visualization_items(viz)

    for ref, setting_key, value in mutations:
        matched = False
        for item in all_items:
            if not _item_matches_ref(item, ref):
                continue
            matched = True
            if setting_key == "_title_override":
                item["fakeTitle"] = value
            elif setting_key == "backgroundSettings" and isinstance(value, dict):
                background_settings = dict(value)
                background_settings["colorFieldGuid"] = item.get("guid")
                item[setting_key] = background_settings
            else:
                item[setting_key] = value
        if not matched:
            raise DataLensConfigurationError(
                f"Field {ref!r} not found in any placeholder. Call .columns()/.measures()/.rows() before this method."
            )


def _apply_measure_formats(
    data: dict[str, object],
    pending_measure_formats: list[tuple[FieldRef, MeasureFormat]],
) -> None:
    if not pending_measure_formats:
        return
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return
    all_items = _visualization_items(viz)

    for ref, fmt in pending_measure_formats:
        wire_fmt = _measure_format_to_wire(fmt)
        matched = False
        for item in all_items:
            if not _item_matches_ref(item, ref):
                continue
            matched = True
            existing_fmt = item.get("formatting")
            if isinstance(existing_fmt, dict):
                existing_fmt.update(wire_fmt)
            else:
                item["formatting"] = dict(wire_fmt)
        if not matched:
            raise DataLensConfigurationError(
                f"Field {ref!r} not found in any placeholder. Call .columns()/.measures()/.rows() before this method."
            )

    labels = data.get("labels")
    if isinstance(labels, list):
        for ref, fmt in pending_measure_formats:
            wire_fmt = _measure_format_to_wire(fmt)
            for label_item in labels:
                if not isinstance(label_item, dict):
                    continue
                if not _item_matches_ref(label_item, ref):
                    continue
                existing_fmt = label_item.get("formatting")
                if isinstance(existing_fmt, dict):
                    existing_fmt.update(wire_fmt)
                else:
                    label_item["formatting"] = dict(wire_fmt)

    updates = data.get("updates")
    if isinstance(updates, list):
        for ref, fmt in pending_measure_formats:
            wire_fmt = _measure_format_to_wire(fmt)
            for upd in updates:
                if not isinstance(upd, dict):
                    continue
                field = upd.get("field")
                if not isinstance(field, dict):
                    continue
                if not _item_matches_ref(field, ref):
                    continue
                existing_fmt = field.get("formatting")
                if isinstance(existing_fmt, dict):
                    existing_fmt.update(wire_fmt)
                else:
                    field["formatting"] = dict(wire_fmt)


def _measure_format_to_wire(fmt: MeasureFormat) -> dict[str, object]:
    wire: dict[str, object] = {}
    if "format" in fmt:
        wire["format"] = fmt["format"]
    if "precision" in fmt:
        wire["precision"] = fmt["precision"]
    if "unit" in fmt:
        wire["unit"] = fmt["unit"]
    if "prefix" in fmt:
        wire["prefix"] = fmt["prefix"]
    if "postfix" in fmt:
        wire["postfix"] = fmt["postfix"]
    if "show_rank_delimiter" in fmt:
        wire["showRankDelimiter"] = fmt["show_rank_delimiter"]
    return wire


def build_hierarchy_object(
    hier_spec: Mapping[str, object],
    normalizer: _Normalizer,
) -> dict[str, object]:
    """Build the 7-key hierarchy wire object from a hierarchy spec.

    Mirrors the backend shape (ground truth: reference_*.json):
    ``{guid, title, className:"item dimension-item", type:"PSEUDO",
    data_type:"hierarchy", valid:True, fields:[...]}`` where ``fields``
    are full normalized field snapshots (not guid strings).

    Inner ``fields`` are always normalized without hierarchy lookup so that a
    child ref string whose guid/title matches any declared hierarchy (including
    this hierarchy itself) is resolved as a plain field rather than triggering
    another ``build_hierarchy_object`` call.  This prevents both direct
    self-reference (``add_hierarchy("dim", ["dim"])``) and mutual A↔B recursion.
    """
    fields_refs = hier_spec.get("fields", [])
    if not isinstance(fields_refs, list):
        fields_refs = []
    normalized_fields = normalizer.for_hierarchy_fields().normalize(list(fields_refs))
    guid = hier_spec.get("guid")
    return {
        "guid": guid if isinstance(guid, str) and guid else str(uuid.uuid4()),
        "title": hier_spec.get("title", ""),
        "className": "item dimension-item",
        "type": "PSEUDO",
        "data_type": "hierarchy",
        "valid": True,
        "fields": normalized_fields,
    }


def _apply_hierarchies(
    data: dict[str, object],
    hierarchies: list[dict[str, object]],
    normalizer: _Normalizer,
) -> None:
    if not hierarchies:
        return
    existing = data.get("hierarchies")
    result: list[object] = (
        [dict(h) if isinstance(h, dict) else h for h in existing] if isinstance(existing, list) else []
    )
    for hier in hierarchies:
        result.append(build_hierarchy_object(hier, normalizer))
    data["hierarchies"] = result


def _build_filter_item(
    item: dict[str, object],
    *,
    operation: str,
    values: list[str],
    dataset_id: str | None,
) -> dict[str, object]:
    guid = item.get("guid", "")
    title = item.get("title", "")
    field_type = item.get("type", "DIMENSION")
    data_type = item.get("data_type", "string")
    filter_item: dict[str, object] = {
        "guid": guid,
        "title": title,
        "type": field_type,
        "data_type": data_type,
        "filter": {
            "operation": {"code": operation},
            "value": values,
        },
    }
    if dataset_id:
        filter_item["datasetId"] = dataset_id
    return filter_item


def _build_sort_item(
    item: dict[str, object],
    *,
    direction: str,
    dataset_id: str | None,
) -> dict[str, object]:
    sort_item: dict[str, object] = {"guid": item.get("guid", "")}
    resolved_dataset = dataset_id or item.get("datasetId")
    if resolved_dataset:
        sort_item["datasetId"] = resolved_dataset
    sort_item["data_type"] = item.get("data_type", "")
    sort_item["title"] = item.get("title", "")
    sort_item["source"] = item.get("source", "")
    sort_item["type"] = item.get("type", "")
    sort_item["direction"] = direction.upper()
    return sort_item


def _apply_pending_filters(
    data: dict[str, object],
    pending_filters: list[tuple[FieldRef, str, list[str]]],
    normalizer: _Normalizer,
    dataset_id: str | None,
) -> None:
    if not pending_filters:
        return
    existing_filters = data.get("filters")
    filters: list[object] = list(existing_filters) if isinstance(existing_filters, list) else []
    for ref, operation, values in pending_filters:
        normalized = normalizer.normalize([ref])
        if not normalized:
            continue
        item = normalized[0]
        filters.append(_build_filter_item(item, operation=operation, values=values, dataset_id=dataset_id))
    data["filters"] = filters


def _apply_sort_direction_items(
    data: dict[str, object],
    sort_direction_items: list[tuple[FieldRef, str]],
    normalizer: _Normalizer,
    dataset_id: str | None,
) -> None:
    if not sort_direction_items:
        return
    sort_list: list[object] = []
    for ref, direction in sort_direction_items:
        normalized = normalizer.normalize([ref])
        if not normalized:
            continue
        item = normalized[0]
        sort_list.append(_build_sort_item(item, direction=direction, dataset_id=dataset_id))
    data["sort"] = sort_list


def _inject_dataset_parameters_to_updates(data: dict[str, object], dataset: Dataset | None) -> None:
    if dataset is None:
        return
    parameters = list(dataset.parameters)
    if not parameters:
        return
    existing_updates = data.setdefault("updates", [])
    if not isinstance(existing_updates, list):
        return
    existing_guids: set[str] = set()
    for upd in existing_updates:
        if isinstance(upd, dict) and upd.get("action") == "update_field":
            field = upd.get("field")
            if isinstance(field, dict):
                guid = field.get("guid")
                if isinstance(guid, str):
                    existing_guids.add(guid)
    for parameter in parameters:
        guid = parameter.guid
        if not guid or guid in existing_guids:
            continue
        field_copy = dict(parameter.raw) if parameter.raw else {"guid": guid, "title": parameter.title}
        if dataset.id is not None:
            field_copy.setdefault("datasetId", dataset.id)
        existing_updates.append({"action": "update_field", "field": field_copy, "deleteUpdateAfterValidation": False})


def _build_datasets_partial_fields(dataset: Dataset | None) -> list[list[dict[str, object]]]:
    if dataset is None:
        return []
    summaries: list[dict[str, object]] = []
    for f in dataset.fields:
        if not f.guid:
            continue
        summaries.append({"guid": f.guid, "title": f.title, "calc_mode": f.calc_mode or "direct"})
    if not summaries:
        return []
    return [summaries]


def _merge_local_fields_into_snapshot(
    snapshot: list[list[dict[str, object]]],
    local_fields: Sequence[Mapping[str, object]],
) -> list[list[dict[str, object]]]:
    if not local_fields:
        return snapshot
    result = [list(group) for group in snapshot]
    if not result:
        result = [[]]
    existing_guids = {f.get("guid") for f in result[0] if isinstance(f, dict)}
    prepend = [dict(lf) for lf in local_fields if lf.get("guid") not in existing_guids]
    result[0] = prepend + result[0]
    return result


def _enrich_chart_local_fields(data: dict[str, object]) -> None:
    updates = data.get("updates")
    if not isinstance(updates, list):
        return
    meta: dict[str, dict[str, object]] = {}
    for op in updates:
        if not isinstance(op, dict) or op.get("action") != "add_field":
            continue
        field = op.get("field")
        if not isinstance(field, dict):
            continue
        guid = field.get("guid")
        if not isinstance(guid, str) or not guid:
            continue
        entry: dict[str, object] = {}
        for key in ("datasetId", "type", "calc_mode", "data_type", "source", "cast", "aggregation", "avatar_id"):
            if field.get(key) is not None:
                entry[key] = field[key]
        meta[guid] = entry

    if not meta:
        return

    def _enrich_items(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            guid = item.get("guid")
            if not isinstance(guid, str) or guid not in meta:
                continue
            for key, val in meta[guid].items():
                if key not in item:
                    item[key] = val

    viz = data.get("visualization")
    if isinstance(viz, dict):
        for ph in _placeholders_list(viz):
            _enrich_items(ph.get("items"))

    for top_key in ("sort", "filters", "labels", "colors"):
        _enrich_items(data.get(top_key))
