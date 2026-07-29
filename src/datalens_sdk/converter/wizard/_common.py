from __future__ import annotations

from collections.abc import Mapping, Sequence

from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.domain.fields import FieldRef as FieldRef


def _dict_with_string_keys(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _placeholders_list(viz: Mapping[str, object]) -> list[dict[str, object]]:
    placeholders = viz.get("placeholders")
    if not isinstance(placeholders, list):
        return []
    return [p for p in placeholders if isinstance(p, dict)]


def _items_list(placeholder: Mapping[str, object]) -> list[dict[str, object]]:
    items = placeholder.get("items")
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict)]


def _field_ref_guid(ref: FieldRef) -> str | None:
    if isinstance(ref, DatasetField):
        return ref.guid
    return None


def _item_matches_ref(item: dict[str, object], ref: FieldRef) -> bool:
    item_guid = item.get("guid")
    item_title = item.get("title")
    if isinstance(ref, DatasetField):
        return item_guid == ref.guid or item_title == ref.title
    return item_guid == ref or item_title == ref


def _collect_measures(data: dict[str, object], placeholder_ids: Sequence[str]) -> list[dict[str, object]]:
    viz = data.get("visualization")
    if not isinstance(viz, dict):
        return []
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for ph_id in placeholder_ids:
        for ph in _placeholders_list(viz):
            if ph.get("id") != ph_id:
                continue
            for item in _items_list(ph):
                if item.get("type") != "MEASURE":
                    continue
                guid = item.get("guid")
                if not isinstance(guid, str) or not guid or guid in seen:
                    continue
                seen.add(guid)
                out.append(item)
    return out
