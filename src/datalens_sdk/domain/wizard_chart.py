from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import difflib

from datalens_sdk._runtime.wizard_field_references import WizardFieldReferences
from datalens_sdk.domain.chart import Chart
from datalens_sdk.domain.chart_types import ChartCategory
from datalens_sdk.domain.fields import DatasetField, FieldLike, FieldRef, FieldsProxy
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

__all__ = ["FieldRef", "WizardChart", "WizardChartUpdate", "resolve_field_snapshot"]

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


def _field_snapshot(field_obj: FieldLike) -> dict[str, object]:
    if field_obj.raw:
        snapshot: dict[str, object] = dict(field_obj.raw)
    else:
        snapshot = {"guid": field_obj.guid, "title": field_obj.title}
        if field_obj.type is not None:
            snapshot["type"] = field_obj.type
        if field_obj.data_type is not None:
            snapshot["data_type"] = field_obj.data_type
        if field_obj.calc_mode:
            snapshot["calc_mode"] = field_obj.calc_mode
        if field_obj.aggregation is not None:
            snapshot["aggregation"] = field_obj.aggregation
        if field_obj.cast is not None:
            snapshot["cast"] = field_obj.cast
        if field_obj.source is not None:
            snapshot["source"] = field_obj.source
        if field_obj.avatar_id is not None:
            snapshot["avatar_id"] = field_obj.avatar_id
        if field_obj.formula:
            snapshot["formula"] = field_obj.formula
        if field_obj.description:
            snapshot["description"] = field_obj.description
        if field_obj.hidden:
            snapshot["hidden"] = True
        if field_obj.default_value is not None:
            snapshot["default_value"] = field_obj.default_value
        if field_obj.ui_settings is not None:
            snapshot["ui_settings"] = field_obj.ui_settings
        if field_obj.initial_data_type is not None:
            snapshot["initial_data_type"] = field_obj.initial_data_type
    # Provenance robustness: result-schema rows frequently omit ``datasetId`` (the
    # normalizer stamps it on send). Fall back to the field's ``dataset_id`` attribute
    # — populated by ``Dataset.fields`` (``FieldsProxy(..., dataset_id=self.id)``) for
    # fields from a fetched dataset — so the snapshot carries correct multi-dataset
    # provenance. Single-dataset behavior is unchanged (same id). Never raises.
    if not snapshot.get("datasetId") and field_obj.dataset_id:
        snapshot["datasetId"] = field_obj.dataset_id
    return snapshot


def resolve_field_snapshot(
    ref: FieldLike | str | Mapping[str, object],
    *,
    fields: Sequence[FieldLike],
    local_fields: Mapping[str, Mapping[str, object]] | None = None,
    bound_dataset_name: str | None = None,
) -> dict[str, object]:
    local_fields = local_fields or {}
    if isinstance(ref, DatasetField):
        return _field_snapshot(ref)
    if isinstance(ref, Mapping):
        return {key: value for key, value in ref.items() if isinstance(key, str)}
    if not isinstance(ref, str):
        raise DataLensValidationError(f"Field reference must be a field, mapping or string, got {type(ref).__name__}")

    if ref in local_fields:
        return {key: value for key, value in local_fields[ref].items() if isinstance(key, str)}

    guid_matches = [field for field in fields if field.guid == ref]
    if guid_matches:
        return _field_snapshot(guid_matches[0])
    name_matches = [field for field in fields if field.title == ref or field.name == ref]
    matching_guids = {field.guid for field in name_matches}
    if len(matching_guids) > 1:
        raise DataLensValidationError(
            f"Field reference {ref!r} is ambiguous: it matches field guids {sorted(matching_guids)}. "
            "Pass a DatasetField or an exact guid."
        )
    if name_matches:
        return _field_snapshot(name_matches[0])

    titles = [f.title for f in fields if f.title]
    suggestions = difflib.get_close_matches(ref, titles, n=3)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    if not fields:
        # No schema to resolve against — either a create without ``.dataset(...)``, or an
        # update on a chart with no placed fields. ``.dataset(...)`` exists only on the
        # create builder, so advise the DatasetField path that works for both.
        raise DataLensValidationError(
            f"Field reference {ref!r} could not be resolved: no dataset schema is available "
            "(either .dataset(...) was not called on the create builder, or this is an update "
            "on a chart with no placed fields). Fetch the dataset and pass a DatasetField:\n"
            "    dataset = client.get.dataset(by_id=...)\n"
            f"    field   = dataset.fields.by_name({ref!r})\n"
            "On create, also call .dataset(dataset) to bind metadata."
        )
    if bound_dataset_name:
        # Bound-dataset miss (create path with ``.dataset(...)``): the field is missing
        # from the bound dataset schema.
        raise DataLensValidationError(f"Field {ref!r} was not found in dataset {bound_dataset_name!r}.{hint}")
    # Update-path miss: only placed fields are known (the chart was loaded, not created
    # in this session, so no dataset schema is bound to the update). Point the user at
    # the dataset_ids + ``fields.by_name`` pattern so they can place the field.
    known = ", ".join(titles) if titles else "(no placed field titles)"
    raise DataLensValidationError(
        f"Field {ref!r} is not placed in this chart and no dataset schema is bound "
        "(the chart was loaded, not created in this session, so only fields already placed "
        "in the visualization are known). To reference a field that is not yet placed, "
        "fetch the dataset schema and pass a DatasetField:\n"
        "    dataset = client.get.dataset(by_id=chart.dataset_ids[0])\n"
        f"    field   = dataset.fields.by_name({ref!r})\n"
        "    chart.update.<placeholder>([field]).execute()\n"
        f"Known field titles already placed in this chart: {known}.{hint}"
    )


@dataclass(slots=True)
class WizardChart(Chart):
    @property
    def category(self) -> ChartCategory:
        return "wizard"

    @property
    def visualization_id(self) -> str | None:
        """The Wizard V1 visualization discriminator (``data.visualization.type``)."""
        visualization = self.data.get("visualization")
        if not isinstance(visualization, Mapping):
            return None
        value = visualization.get("type")
        return value if isinstance(value, str) else None

    @property
    def fields(self) -> FieldsProxy:
        return FieldsProxy(WizardFieldReferences(self.data).unique_active_snapshots())

    @property
    def dataset_ids(self) -> tuple[str, ...]:
        """The dataset ids backing this chart (``data.sources.datasetsIds``).

        Empty tuple when the key is absent or holds no string ids. Used by the
        update path to point users at the right dataset when a field reference
        cannot be resolved against placed fields alone.
        """
        sources = self.data.get("sources")
        if not isinstance(sources, Mapping):
            return ()
        value = sources.get("datasetsIds")
        if not isinstance(value, list):
            return ()
        return tuple(item for item in value if isinstance(item, str))

    @property
    def rev_id(self) -> str | None:
        value = self.raw.get("revId")
        return value if isinstance(value, str) else None

    @property
    def update(self) -> WizardChartUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a chart without an id")
        return WizardChartUpdate(chart=self, operations=self._operations)

    def publish_revision(self, *, rev_id: str | None = None) -> WizardChart:
        """Publish an existing revision without creating a new one.

        ``rev_id=None`` publishes the revision this object was loaded as. To
        persist changes and publish them in one call, use
        ``chart.update.mode("publish").execute()`` instead.
        """
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot publish a chart without an id")
        effective_rev_id = rev_id if rev_id is not None else self.rev_id
        if not effective_rev_id:
            raise DataLensValidationError("Cannot publish: no rev_id given and the chart carries none")
        return self._operations.publish_wizard_chart(self, effective_rev_id)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a chart without an id")
        self._operations.delete_wizard_chart(self.id)


# Re-export to preserve the historical public path
# ``from datalens_sdk.domain.wizard_chart import WizardChartUpdate`` (converter, tests).
# Imported at the bottom of the module so that ``wizard_chart_update`` can resolve
# ``WizardChart`` during its own import without an import cycle.
from datalens_sdk.domain.wizard_chart_update import WizardChartUpdate  # noqa: E402
