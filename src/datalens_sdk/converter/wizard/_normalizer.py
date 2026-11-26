from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy

from datalens_sdk._runtime.wizard_field_references import field_snapshot_dataset_id
from datalens_sdk._runtime.wizard_structure import WizardFieldStructure
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
        field_dataset_ids: Mapping[str, str] | None = None,
        dataset_ids: Sequence[str] = (),
        dataset_replacement: tuple[str, str] | None = None,
        field_structure: WizardFieldStructure,
    ) -> None:
        self._local_fields = local_fields
        self._hierarchies = dict(hierarchies) if hierarchies else {}
        if fields is not None:
            self._fields = list(fields)
        else:
            self._fields = list(dataset.fields) if dataset is not None else []
        self._dataset_name = _dataset_name(dataset)
        self._dataset_replacement = dataset_replacement
        self._dataset_ids = frozenset(self._replace_dataset_id(dataset_id) for dataset_id in dataset_ids if dataset_id)
        self._field_dataset_ids = {
            field.guid: field.dataset_id for field in self._fields if field.guid and field.dataset_id
        }
        if field_dataset_ids is not None:
            self._field_dataset_ids.update(field_dataset_ids)
        self._field_structure = field_structure
        self._direct_field_properties = frozenset(field_structure["direct_properties"])

    @property
    def direct_field_properties(self) -> frozenset[str]:
        return self._direct_field_properties

    def for_dataset(self, dataset: Dataset) -> _Normalizer:
        return _Normalizer(
            dataset=dataset,
            local_fields=self._local_fields,
            hierarchies=self._hierarchies,
            field_structure=self._field_structure,
        )

    def for_hierarchy_fields(self) -> _Normalizer:
        "Return a copy of this normalizer that skips hierarchy lookups."
        clone = copy.copy(self)
        clone._hierarchies = {}
        return clone

    def _replace_dataset_id(self, dataset_id: str) -> str:
        if self._dataset_replacement is not None and dataset_id == self._dataset_replacement[0]:
            return self._dataset_replacement[1]
        return dataset_id

    def dataset_id_for(self, snapshot: Mapping[str, object], *, fallback: str | None) -> str | None:
        dataset_id = field_snapshot_dataset_id(snapshot)
        if dataset_id is not None:
            return dataset_id
        guid = snapshot.get("guid")
        if not isinstance(guid, str):
            return None
        known_id = self._field_dataset_ids.get(guid)
        if known_id is not None:
            return self._replace_dataset_id(known_id)
        local_field = self._local_fields.get(guid)
        if local_field is not None and local_field.get("guid") == guid:
            local_id = field_snapshot_dataset_id(local_field)
            if local_id is not None:
                return self._replace_dataset_id(local_id)
        if len(self._dataset_ids) > 1:
            raise DataLensValidationError(
                f"Cannot determine datasetId for Wizard field guid {guid!r} with multiple datasets "
                f"{sorted(self._dataset_ids)!r}. Pass a DatasetField with a known dataset."
            )
        return next(iter(self._dataset_ids), fallback)

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
            dataset_id = field_snapshot_dataset_id(snapshot)
            if dataset_id is not None:
                snapshot["datasetId"] = self._replace_dataset_id(dataset_id)
            out.append(snapshot)
        return out
