from __future__ import annotations

from collections.abc import Mapping, Sequence

from datalens_sdk.converter.wizard._common import FieldRef
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.fields import FieldLike
from datalens_sdk.domain.wizard_chart import resolve_field_snapshot


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
        fields: Sequence[FieldLike] | None = None,
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
        self._dim_counter = 0
        self._meas_counter = 0

    def for_hierarchy_fields(self) -> _Normalizer:
        "Return a copy of this normalizer that skips hierarchy lookups."
        clone: _Normalizer = object.__new__(_Normalizer)
        clone._dataset = self._dataset
        clone._local_fields = self._local_fields
        clone._hierarchies = {}  # no hierarchy lookup inside hierarchy fields
        clone._fields = self._fields
        clone._dataset_id = self._dataset_id
        clone._dataset_name = self._dataset_name
        clone._dim_counter = 0  # fresh counters; hierarchy scope is independent
        clone._meas_counter = 0
        return clone

    def normalize(self, items: Sequence[FieldRef]) -> list[dict[str, object]]:
        # Lazy import to avoid a module-load cycle: _decorations imports
        # _Normalizer at module level (via _colors → _normalizer → _decorations
        # → _normalizer). The dependency is only needed at call time.
        from datalens_sdk.converter.wizard._decorations import (  # noqa: PLC0415
            build_hierarchy_object,
        )

        out: list[dict[str, object]] = []
        for item in items:
            hier_spec = self._hierarchies.get(item) if isinstance(item, str) else None
            if hier_spec is not None:
                # Hierarchy placement: emit the 7-key hierarchy object as-is.
                # Field post-processing (datasetId/datasetName/id at the top
                # level) must be skipped so the object stays exactly 7 keys.
                # The hierarchy's inner fields are normalized with a field-only
                # normalizer (no hierarchy lookup) to prevent infinite recursion
                # when a child ref string matches the hierarchy's own guid/title.
                out.append(build_hierarchy_object(hier_spec, self.for_hierarchy_fields()))
                continue
            snapshot = resolve_field_snapshot(
                item,
                fields=self._fields,
                local_fields=self._local_fields,
                bound_dataset_name=self._dataset_name or None,
            )
            snapshot = {k: v for k, v in snapshot.items() if v is not None}
            if self._dataset_id and not snapshot.get("datasetId"):
                snapshot["datasetId"] = self._dataset_id
            if self._dataset_name and not snapshot.get("datasetName"):
                snapshot["datasetName"] = self._dataset_name
            if not snapshot.get("id"):
                field_type = snapshot.get("type", "DIMENSION")
                if field_type == "MEASURE":
                    snapshot["id"] = f"measure-{self._meas_counter}"
                    self._meas_counter += 1
                else:
                    snapshot["id"] = f"dimension-{self._dim_counter}"
                    self._dim_counter += 1
            out.append(snapshot)
        return out
