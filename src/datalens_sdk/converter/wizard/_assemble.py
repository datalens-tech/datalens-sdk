from __future__ import annotations

from datalens_sdk._runtime.chart_wire import merge_chart_defaults
from datalens_sdk.converter.wizard._autofix import (
    _apply_auto_fix_pie_dimension_color,
    _apply_bar_auto_defaults,
    _apply_smart_labels_position,
    _auto_fix_multi_measure,
)
from datalens_sdk.converter.wizard._colors import (
    _apply_colors_config,
    _apply_shape_encoding,
    _has_color_split,
)
from datalens_sdk.converter.wizard._decorations import (
    _apply_data_fields,
    _apply_extra_settings,
    _apply_hierarchies,
    _apply_item_mutations,
    _apply_measure_formats,
    _apply_pending_filters,
    _apply_ph_settings,
    _apply_sort_direction_items,
    _build_datasets_partial_fields,
    _enrich_chart_local_fields,
    _inject_dataset_parameters_to_updates,
    _merge_local_fields_into_snapshot,
)
from datalens_sdk.converter.wizard._layers import (
    _apply_geolayer_selected_layer_field,
    _finalize_geolayer_selected_layer_fields,
    _hierarchies_map,
    _local_fields_map,
    _sync_geolayer_selected_layer_fields,
)
from datalens_sdk.converter.wizard._normalizer import _dataset_of, _Normalizer
from datalens_sdk.converter.wizard._placeholders import (
    _build_visualization,
    _fill_missing_placeholders,
    _sync_axis_mode_map,
)
from datalens_sdk.domain.specs.wizard_chart import WizardChartCreateSpec


def _assemble_wizard_data(spec: WizardChartCreateSpec) -> dict[str, object]:
    spec_key = spec.viz_id
    dataset = _dataset_of(spec.dataset)
    local_fields = spec.local_fields
    normalizer = _Normalizer(
        dataset=dataset,
        local_fields=_local_fields_map(local_fields),
        hierarchies=_hierarchies_map(spec.hierarchies),
    )

    dataset_id = dataset.id if dataset is not None else (spec.dataset_ids[0] if spec.dataset_ids else None)

    data: dict[str, object] = {}

    updates: list[dict[str, object]] = []
    for lf in local_fields:
        field_entry = dict(lf)
        if dataset_id is not None and "datasetId" not in field_entry:
            field_entry["datasetId"] = dataset_id
        updates.append({"action": "add_field", "field": field_entry})
    if updates:
        data["updates"] = updates

    data["visualization"] = _build_visualization(spec, spec_key, normalizer)

    sort_input = spec.sort
    sort_direction_items = spec.sort_direction_items
    if sort_direction_items:
        _apply_sort_direction_items(data, list(sort_direction_items), normalizer, dataset_id)
    elif sort_input:
        data["sort"] = normalizer.normalize(list(sort_input))

    labels_input = spec.labels
    if labels_input:
        normalized_labels = normalizer.normalize(list(labels_input))
        if spec_key == "geolayer":
            _apply_geolayer_selected_layer_field(data, "labels", normalized_labels)
        else:
            data["labels"] = normalized_labels

    data_fields = {key: list(value) for key, value in spec.data_fields.items()}
    if spec_key == "geolayer":
        tooltips_input = data_fields.pop("tooltips", None)
        if tooltips_input:
            _apply_geolayer_selected_layer_field(data, "tooltips", normalizer.normalize(tooltips_input))
    _apply_data_fields(data, data_fields, normalizer)
    _apply_extra_settings(data, dict(spec.extra_settings))

    explicit_colors = spec.explicit_colors

    _fill_missing_placeholders(data, spec_key)
    _sync_axis_mode_map(data)
    _apply_ph_settings(data, {key: dict(value) for key, value in spec.ph_settings.items()}, spec_key)
    if not explicit_colors:
        _apply_auto_fix_pie_dimension_color(data)
    _apply_shape_encoding(
        data,
        shape_encoding=spec.shape_encoding,
        visualization_id=spec.viz_id,
        normalizer=normalizer,
    )
    _apply_colors_config(
        data,
        colors_palette=spec.colors_palette,
        color_encoding=spec.color_encoding,
        visualization_id=spec.viz_id,
        normalizer=normalizer,
    )
    _apply_item_mutations(data, list(spec.item_mutations))
    _apply_measure_formats(data, list(spec.pending_measure_formats))
    _apply_hierarchies(data, [dict(h) for h in spec.hierarchies], normalizer)
    _inject_dataset_parameters_to_updates(data, dataset)
    _apply_bar_auto_defaults(data, spec_key)
    _auto_fix_multi_measure(data, explicit_colors)
    _apply_smart_labels_position(data, spec_key, has_colors=_has_color_split(data, explicit_colors))
    _enrich_chart_local_fields(data)

    _apply_pending_filters(data, list(spec.pending_filters), normalizer, dataset_id)

    if spec.geopoints_config:
        existing = data.get("geopointsConfig")
        cfg = dict(existing) if isinstance(existing, dict) else {}
        cfg.update(spec.geopoints_config)
        data["geopointsConfig"] = cfg

    if spec_key == "geolayer":
        _sync_geolayer_selected_layer_fields(data)
    merged = merge_chart_defaults(data)
    if spec_key == "geolayer":
        _finalize_geolayer_selected_layer_fields(merged)

    datasets = [dataset] if dataset is not None else []
    for geo_dataset in spec.geo_datasets:
        if geo_dataset not in datasets:
            datasets.append(geo_dataset)
    snapshot = [fields for chart_dataset in datasets for fields in _build_datasets_partial_fields(chart_dataset)]
    if snapshot or local_fields:
        merged["datasetsPartialFields"] = _merge_local_fields_into_snapshot(snapshot, local_fields)

    dataset_ids = spec.dataset_ids
    if dataset_ids:
        merged["datasetsIds"] = list(dataset_ids)

    return merged
