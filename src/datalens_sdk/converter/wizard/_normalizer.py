from __future__ import annotations

from collections.abc import Mapping, Sequence

from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.fields import DatasetField, WizardFieldRef, WizardHierarchy
from datalens_sdk.domain.wizard_chart import resolve_field_snapshot
from datalens_sdk.errors import DataLensValidationError


def _local_fields_map(local_fields: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for field in local_fields:
        guid = field.get("guid")
        if isinstance(guid, str) and guid:
            result[guid] = dict(field)
    for field in local_fields:
        title = field.get("title")
        if isinstance(title, str) and title and title not in result:
            result[title] = dict(field)
    return result


def _hierarchies_map(hierarchies: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for hierarchy in hierarchies:
        guid = hierarchy.get("guid")
        if isinstance(guid, str) and guid:
            result[guid] = dict(hierarchy)
    for hierarchy in hierarchies:
        title = hierarchy.get("title")
        if isinstance(title, str) and title and title not in result:
            result[title] = dict(hierarchy)
    return result


def _dataset_of(dataset: Dataset | None) -> Dataset | None:
    return dataset if isinstance(dataset, Dataset) else None


def _dataset_name(dataset: Dataset | None) -> str:
    if dataset is None:
        return ""
    if dataset.name:
        return dataset.name
    if dataset.dir_path and "/" in dataset.dir_path:
        return dataset.dir_path.rsplit("/", 1)[-1]
    return ""


class _Normalizer:
    def __init__(
        self,
        *,
        dataset: Dataset | None,
        local_fields: Mapping[str, Mapping[str, object]],
        hierarchies: Mapping[str, Mapping[str, object]] | None = None,
        fields: Sequence[DatasetField] | None = None,
        dataset_replacement: tuple[str, str] | None = None,
    ) -> None:
        self._dataset = dataset
        self._local_fields = local_fields
        self._hierarchies = dict(hierarchies) if hierarchies else {}
        if fields is not None:
            self._fields = list(fields)
        else:
            self._fields = list(dataset.fields) if dataset is not None else []
        self._dataset_id = dataset.id if dataset is not None else None
        self._dataset_name = _dataset_name(dataset)
        self._dataset_replacement = dataset_replacement

    def for_hierarchy_fields(self) -> _Normalizer:
        "Return a copy of this normalizer that skips hierarchy lookups."
        clone: _Normalizer = object.__new__(_Normalizer)
        clone._dataset = self._dataset
        clone._local_fields = self._local_fields
        clone._hierarchies = {}  # no hierarchy lookup inside hierarchy fields
        clone._fields = self._fields
        clone._dataset_id = self._dataset_id
        clone._dataset_name = self._dataset_name
        clone._dataset_replacement = self._dataset_replacement
        return clone

    def normalize(self, items: Sequence[WizardFieldRef]) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for item in items:
            hierarchy_key = item.guid if isinstance(item, WizardHierarchy) else item
            hier_spec = self._hierarchies.get(hierarchy_key) if isinstance(hierarchy_key, str) else None
            if isinstance(item, WizardHierarchy) and hier_spec is None:
                raise DataLensValidationError(
                    f"Wizard hierarchy {item.title!r} ({item.guid}) is not registered in this chart. "
                    "Call add_hierarchy(hierarchy) before using the handle as a field reference."
                )
            if hier_spec is not None:
                fields = hier_spec.get("fields")
                refs = list(fields) if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)) else []
                normalized_fields = self.for_hierarchy_fields().normalize(refs)
                out.append(
                    {
                        "guid": hier_spec.get("guid"),
                        "title": hier_spec.get("title"),
                        "data_type": "hierarchy",
                        "fields": [
                            {"guid": field.get("guid"), "datasetId": field.get("datasetId")}
                            for field in normalized_fields
                        ],
                    }
                )
                continue
            snapshot = resolve_field_snapshot(
                item,
                fields=self._fields,
                local_fields=self._local_fields,
                bound_dataset_name=self._dataset_name or None,
            )
            snapshot = {k: v for k, v in snapshot.items() if v is not None}
            if self._dataset_replacement is not None and snapshot.get("datasetId") == self._dataset_replacement[0]:
                snapshot["datasetId"] = self._dataset_replacement[1]
            if self._dataset_id and not snapshot.get("datasetId"):
                snapshot["datasetId"] = self._dataset_id
            out.append(snapshot)
        return out
