from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import TYPE_CHECKING
from uuid import uuid4

from typing_extensions import Self

from datalens_sdk.domain.dataset_types import (
    Aggregation,
    CacheInvalidationSource,
    CalcMode,
    CloneFieldPayload,
    DatasetUpdateAction,
    DataType,
    FieldKind,
    FieldPayload,
    FilterValues,
    JoinCondition,
    JoinType,
    NumberFormat,
    NumberFormatUnit,
    ParameterDataType,
    ParameterValue,
    RLS2ConfigEntryPayload,
    RLSPatternType,
    RLSSubjectPayload,
    RLSSubjectType,
    SettingName,
    SourceAvatarPayload,
    SourcePayload,
    UpdateSourcePayload,
    WhereOperation,
    cache_invalidation_source_payload,
)
from datalens_sdk.domain.fields import DatasetField, FieldLike
from datalens_sdk.domain.ports import DatasetOperations
from datalens_sdk.domain.specs.dataset import DatasetUpdateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

if TYPE_CHECKING:
    from datalens_sdk.domain.dataset import Dataset, Source


FieldRef = FieldLike | str


def _field_guid(field: FieldRef) -> str:
    if isinstance(field, DatasetField):
        return field.guid
    return field


def _field_title(field: FieldRef) -> str | None:
    if isinstance(field, DatasetField):
        return field.title
    return None


def _unique_matched_guid(field: str, candidates: list[DatasetField]) -> str | None:
    matched_guids = {candidate.guid for candidate in candidates}
    if len(matched_guids) > 1:
        raise DataLensValidationError(f"Field reference {field!r} is ambiguous; pass a DatasetField or field GUID")
    if not matched_guids:
        return None
    return matched_guids.pop()


def _default_filter_field_guid(dataset: Dataset, field: FieldRef) -> str:
    if isinstance(field, DatasetField):
        return field.guid
    for candidates in (
        [candidate for candidate in dataset.fields if candidate.guid == field],
        [candidate for candidate in dataset.fields if field in (candidate.name, candidate.title)],
        [candidate for candidate in dataset.fields if candidate.source == field],
    ):
        guid = _unique_matched_guid(field, candidates)
        if guid is not None:
            return guid
    return field


def _field_avatar_id(dataset: Dataset, field: FieldRef) -> str | None:
    if isinstance(field, DatasetField):
        return field.avatar_id

    for candidate in dataset.fields:
        if field in (candidate.guid, candidate.name, candidate.title, candidate.source):
            return candidate.avatar_id
    return None


def _field_avatar_id_strict(dataset: Dataset, field: FieldRef) -> str | None:
    if isinstance(field, DatasetField):
        return field.avatar_id

    matched: list[str | None] = []
    for candidate in dataset.fields:
        if field in (candidate.guid, candidate.name, candidate.title, candidate.source):
            matched.append(candidate.avatar_id)

    if len(set(matched)) > 1:
        raise DataLensValidationError(
            f"Field reference {field!r} is ambiguous across multiple avatars; "
            "pass a DatasetField with an explicit avatar_id"
        )
    return matched[0] if matched else None


class DatasetUpdate:
    def __init__(self, *, dataset: Dataset, operations: DatasetOperations | None = None) -> None:
        self._dataset = dataset
        self._operations = operations
        self._actions: list[DatasetUpdateAction] = []
        self._name_change: str | None = None
        self._rls2_changes: dict[str, list[RLS2ConfigEntryPayload] | None] = {}

    @property
    def actions(self) -> tuple[DatasetUpdateAction, ...]:
        return tuple(self._actions)

    @property
    def name_change(self) -> str | None:
        return self._name_change

    @property
    def rls2_changes(self) -> dict[str, list[RLS2ConfigEntryPayload] | None]:
        return self._rls2_changes

    def name(self, value: str) -> Self:
        self._name_change = value
        return self

    def description(self, value: str) -> Self:
        self._actions.append({"action": "update_description", "description": value})
        return self

    def add_field(
        self,
        *,
        title: str,
        source: str,
        kind: FieldKind,
        avatar_id: str | None = None,
        calc_mode: CalcMode = "direct",
        aggregation: Aggregation | None = None,
        cast: DataType | None = None,
        description: str | None = None,
        hidden: bool = False,
        guid: str | None = None,
    ) -> Self:
        payload: FieldPayload = {
            "guid": guid or str(uuid4()),
            "title": title,
            "source": source,
            "calc_mode": calc_mode,
            "type": kind,
            "hidden": hidden,
        }
        if avatar_id is not None:
            payload["avatar_id"] = avatar_id
        if aggregation is not None:
            payload["aggregation"] = aggregation
        if cast is not None:
            payload["cast"] = cast
        if description is not None:
            payload["description"] = description
        self._actions.append({"action": "add_field", "field": payload})
        return self

    def add_calculation(
        self,
        *,
        name: str,
        formula: str,
        kind: FieldKind,
        aggregation: Aggregation | None = "none",
        cast: DataType | None = None,
        guid: str | None = None,
    ) -> Self:
        payload: FieldPayload = {
            "guid": guid or str(uuid4()),
            "title": name,
            "formula": formula,
            "calc_mode": "formula",
            "type": kind,
        }
        if aggregation is not None:
            payload["aggregation"] = aggregation
        if cast is not None:
            payload["cast"] = cast
        self._actions.append({"action": "add_field", "field": payload})
        return self

    def add_parameter(
        self,
        *,
        name: str,
        type: ParameterDataType,
        default: ParameterValue,
        guid: str | None = None,
    ) -> Self:
        self._actions.append(
            {
                "action": "add_field",
                "field": {
                    "guid": guid or str(uuid4()),
                    "title": name,
                    "calc_mode": "parameter",
                    "cast": type,
                    "default_value": default,
                },
            }
        )
        return self

    def update_field(
        self,
        *,
        field: FieldRef,
        title: str | None = None,
        cast: DataType | ParameterDataType | None = None,
        aggregation: Aggregation | None = None,
        description: str | None = None,
        hidden: bool | None = None,
        ui_settings: str | None = None,
    ) -> Self:
        payload: FieldPayload = {"guid": _field_guid(field)}
        current_title = title or _field_title(field)
        if current_title is not None:
            payload["title"] = current_title
        if cast is not None:
            payload["cast"] = cast
        if aggregation is not None:
            payload["aggregation"] = aggregation
        if description is not None:
            payload["description"] = description
        if hidden is not None:
            payload["hidden"] = hidden
        if ui_settings is not None:
            payload["ui_settings"] = ui_settings
        self._actions.append({"action": "update_field", "field": payload})
        return self

    def change_field_type(self, *, field: FieldRef, to: DataType) -> Self:
        return self.update_field(field=field, cast=to)

    def change_field_aggregation(self, *, field: FieldRef, to: Aggregation) -> Self:
        kind: FieldKind = "DIMENSION" if to == "none" else "MEASURE"
        return self.update_field(field=field, aggregation=to, title=_field_title(field), hidden=None)._set_last_type(
            kind
        )

    def _set_last_type(self, kind: FieldKind) -> Self:
        action = self._actions[-1]
        match action["action"]:
            case "add_field" | "update_field":
                action["field"]["type"] = kind
            case _:
                pass
        return self

    def change_field_description(self, *, field: FieldRef, to: str) -> Self:
        return self.update_field(field=field, description=to)

    def update_field_format(
        self,
        *,
        field: FieldRef,
        format_: NumberFormat | None = None,
        precision: int | None = None,
        prefix: str | None = None,
        postfix: str | None = None,
        unit: NumberFormatUnit | None = None,
        show_rank_delimiter: bool | None = None,
    ) -> Self:
        if all(v is None for v in (format_, precision, prefix, postfix, unit, show_rank_delimiter)):
            raise DataLensValidationError("At least one formatting parameter must be provided")
        number_formatting: dict[str, str | int | bool] = {}
        if format_ is not None:
            number_formatting["format"] = format_
        if precision is not None:
            number_formatting["precision"] = precision
        if prefix is not None:
            number_formatting["prefix"] = prefix
        if postfix is not None:
            number_formatting["postfix"] = postfix
        if unit is not None:
            number_formatting["unit"] = unit
        if show_rank_delimiter is not None:
            number_formatting["showRankDelimiter"] = show_rank_delimiter
        return self.update_field(field=field, ui_settings=json.dumps({"numberFormatting": number_formatting}))

    def add_default_filter(
        self,
        *,
        field: FieldRef,
        operator: WhereOperation,
        values: FilterValues | None = None,
    ) -> Self:
        guid = _default_filter_field_guid(self._dataset, field)
        self._actions.append(
            {
                "action": "add_obligatory_filter",
                "obligatory_filter": {
                    "id": str(uuid4()),
                    "field_guid": guid,
                    "default_filters": [{"column": guid, "operation": operator, "values": list(values or ())}],
                },
            }
        )
        return self

    def add_relation(
        self,
        *,
        type: JoinType,
        conditions: Sequence[JoinCondition],
        drop_duplicates: bool = False,
    ) -> Self:
        if not conditions:
            raise DataLensValidationError("'conditions' must not be empty")
        left_avatar_id = _field_avatar_id(self._dataset, conditions[0].left)
        right_avatar_id = _field_avatar_id(self._dataset, conditions[0].right)
        self._actions.append(
            {
                "action": "add_avatar_relation",
                "avatar_relation": {
                    "id": str(uuid4()),
                    "join_type": type,
                    "conditions": [
                        {
                            "left": {"calc_mode": "direct", "source": cond.left},
                            "operator": cond.operator,
                            "right": {"calc_mode": "direct", "source": cond.right},
                            "type": "binary",
                        }
                        for cond in conditions
                    ],
                    "required": drop_duplicates,
                    "managed_by": "user",
                    "left_avatar_id": left_avatar_id,
                    "right_avatar_id": right_avatar_id,
                },
            }
        )
        return self

    def refresh_source(self, source_id: str, *, force_update_fields: bool = False) -> Self:
        self._actions.append(
            {
                "action": "refresh_source",
                "source": {"id": source_id, "force_update_fields": force_update_fields},
            }
        )
        return self

    def add_rls(
        self,
        *,
        field: FieldRef,
        subject_id: str,
        allowed_value: str | None = None,
        subject_type: RLSSubjectType = "user",
        subject_name: str | None = None,
        pattern_type: RLSPatternType = "value",
    ) -> Self:
        guid = _field_guid(field)
        subject: RLSSubjectPayload = {"subject_id": subject_id, "subject_type": subject_type}
        if subject_name is not None:
            subject["subject_name"] = subject_name
        entry: RLS2ConfigEntryPayload = {"subject": subject, "field_guid": guid, "pattern_type": pattern_type}
        if allowed_value is not None:
            entry["allowed_value"] = allowed_value
        entries = self._rls2_changes.get(guid)
        if entries is None:
            entries = []
            self._rls2_changes[guid] = entries
        entries.append(entry)
        return self

    def update_rls(
        self,
        *,
        field: FieldRef,
        subject_id: str,
        allowed_value: str | None = None,
        subject_type: RLSSubjectType = "user",
        subject_name: str | None = None,
        pattern_type: RLSPatternType = "value",
    ) -> Self:
        return self.add_rls(
            field=field,
            subject_id=subject_id,
            allowed_value=allowed_value,
            subject_type=subject_type,
            subject_name=subject_name,
            pattern_type=pattern_type,
        )

    def delete_rls(self, *, field: FieldRef) -> Self:
        self._rls2_changes[_field_guid(field)] = None
        return self

    def delete_field(self, *, field: FieldRef) -> Self:
        self._actions.append({"action": "delete_field", "field": {"guid": _field_guid(field)}})
        return self

    def clone_field(
        self,
        *,
        field: FieldRef,
        new_title: str,
        new_guid: str | None = None,
    ) -> Self:
        payload: CloneFieldPayload = {"from_guid": _field_guid(field), "title": new_title}
        if new_guid is not None:
            payload["guid"] = new_guid
        self._actions.append({"action": "clone_field", "field": payload})
        return self

    def hide_field(self, *, field: FieldRef) -> Self:
        return self.update_field(field=field, hidden=True)

    def show_field(self, *, field: FieldRef) -> Self:
        return self.update_field(field=field, hidden=False)

    def update_calculation(
        self,
        *,
        field: FieldRef,
        formula: str | None = None,
        kind: FieldKind | None = None,
        cast: DataType | None = None,
        aggregation: Aggregation | None = None,
    ) -> Self:
        payload: FieldPayload = {"guid": _field_guid(field)}
        if formula is not None:
            payload["formula"] = formula
        if cast is not None:
            payload["cast"] = cast
        if aggregation is not None:
            payload["aggregation"] = aggregation
        self._actions.append({"action": "update_field", "field": payload})
        if kind is not None:
            self._set_last_type(kind)
        return self

    def update_parameter(
        self,
        *,
        field: FieldRef,
        type: ParameterDataType | None = None,
        default: ParameterValue | None = None,
    ) -> Self:
        payload: FieldPayload = {"guid": _field_guid(field)}
        if type is not None:
            payload["cast"] = type
        if default is not None:
            payload["default_value"] = default
        self._actions.append({"action": "update_field", "field": payload})
        return self

    def _find_filter_by_id(self, filter_id: str) -> Mapping[str, object]:
        for entry in self._dataset.obligatory_filters:
            if str(entry.get("id") or "") == filter_id:
                return entry
        raise DataLensValidationError(f"Obligatory filter {filter_id!r} not found in dataset")

    def update_default_filter(
        self,
        *,
        filter_id: str,
        operator: WhereOperation,
        values: FilterValues | None = None,
    ) -> Self:
        existing = self._find_filter_by_id(filter_id)
        field_guid = str(existing.get("field_guid") or "")
        self._actions.append(
            {
                "action": "update_obligatory_filter",
                "obligatory_filter": {
                    "id": filter_id,
                    "field_guid": field_guid,
                    "default_filters": [{"column": field_guid, "operation": operator, "values": list(values or ())}],
                },
            }
        )
        return self

    def delete_default_filter(self, *, filter_id: str) -> Self:
        self._actions.append({"action": "delete_obligatory_filter", "obligatory_filter": {"id": filter_id}})
        return self

    def _find_relation_by_id(self, relation_id: str) -> Mapping[str, object]:
        for rel in self._dataset.avatar_relations:
            if str(rel.get("id") or "") == relation_id:
                return rel
        raise DataLensValidationError(f"Avatar relation {relation_id!r} not found in dataset")

    def update_relation(
        self,
        *,
        relation_id: str,
        type: JoinType | None = None,
        conditions: Sequence[JoinCondition] | None = None,
        drop_duplicates: bool | None = None,
    ) -> Self:
        existing = self._find_relation_by_id(relation_id)
        join_type = type or str(existing.get("join_type") or "inner")
        required = drop_duplicates if drop_duplicates is not None else bool(existing.get("required", False))
        managed_by_raw = str(existing.get("managed_by") or "user")

        if conditions is not None:
            left_avatar_id = _field_avatar_id_strict(self._dataset, conditions[0].left)
            right_avatar_id = _field_avatar_id_strict(self._dataset, conditions[0].right)
            resolved_conditions: list[dict[str, object]] = [
                {
                    "left": {"calc_mode": "direct", "source": cond.left},
                    "operator": cond.operator,
                    "right": {"calc_mode": "direct", "source": cond.right},
                    "type": "binary",
                }
                for cond in conditions
            ]
        else:
            left_avatar_id_raw = existing.get("left_avatar_id")
            right_avatar_id_raw = existing.get("right_avatar_id")
            left_avatar_id = left_avatar_id_raw if isinstance(left_avatar_id_raw, str) else None
            right_avatar_id = right_avatar_id_raw if isinstance(right_avatar_id_raw, str) else None
            raw_conditions = existing.get("conditions")
            resolved_conditions = list(raw_conditions) if isinstance(raw_conditions, list) else []

        self._actions.append(
            {  # type: ignore[arg-type,misc]
                "action": "update_avatar_relation",
                "avatar_relation": {
                    "id": relation_id,
                    "join_type": join_type,
                    "conditions": resolved_conditions,
                    "required": required,
                    "managed_by": managed_by_raw,
                    "left_avatar_id": left_avatar_id,
                    "right_avatar_id": right_avatar_id,
                },
            }
        )
        return self

    def delete_relation(self, *, relation_id: str) -> Self:
        self._actions.append({"action": "delete_avatar_relation", "avatar_relation": {"id": relation_id}})
        return self

    def add_source(self, *, source: Source) -> Self:
        payload: SourcePayload = {
            "id": source.id,
            "title": source.title,
            "source_type": source.source_type,
            "connection_id": source.connection_id or "",
            "parameters": dict(source.parameters),
        }
        self._actions.append({"action": "add_source", "source": payload})
        return self

    def update_source(
        self,
        *,
        source_id: str,
        title: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> Self:
        source = self._dataset.sources.by_alias(source_id)
        payload: UpdateSourcePayload = {
            "id": source_id,
            "title": source.title if title is None else title,
            "source_type": source.source_type,
            "connection_id": source.connection_id,
            "parameters": dict(source.parameters if parameters is None else parameters),
            "raw_schema": list(source.raw_schema),
        }
        self._actions.append({"action": "update_source", "source": payload})
        return self

    def delete_source(self, *, source_id: str) -> Self:
        self._actions.append({"action": "delete_source", "source": {"id": source_id}})
        return self

    def update_source_avatar(self, *, avatar_id: str, title: str | None = None) -> Self:
        payload: SourceAvatarPayload = {"id": avatar_id}
        if title is not None:
            payload["title"] = title
        self._actions.append({"action": "update_source_avatar", "source_avatar": payload})
        return self

    def delete_source_avatar(self, *, avatar_id: str) -> Self:
        self._actions.append({"action": "delete_source_avatar", "source_avatar": {"id": avatar_id}})
        return self

    def replace_connection(self, *, old_connection_id: str, new_connection_id: str) -> Self:
        self._actions.append(
            {
                "action": "replace_connection",
                "connection": {
                    "id": old_connection_id,
                    "new_id": new_connection_id,
                },
            }
        )
        return self

    def update_setting(self, *, name: SettingName, value: bool) -> Self:
        self._actions.append({"action": "update_setting", "setting": {"name": name, "value": value}})
        return self

    def update_cache_invalidation_source(self, *, source: CacheInvalidationSource) -> Self:
        self._actions.append(
            {
                "action": "update_cache_invalidation_source",
                "cache_invalidation_source": cache_invalidation_source_payload(source),
            }
        )
        return self

    def to_spec(self) -> DatasetUpdateSpec:
        return DatasetUpdateSpec(
            dataset_id=self._dataset.id or "",
            name=self._dataset.name,
            location=self._dataset.location,
            raw=self._dataset.raw,
            actions=tuple(self._actions),
            name_change=self._name_change,
            rls2_changes=dict(self._rls2_changes),
        )

    def execute(self) -> Dataset:
        if self._operations is None:
            raise DataLensConfigurationError("Object is not bound to client operations. Use a client namespace.")
        if not self._dataset.id:
            raise DataLensValidationError("Cannot update a dataset without an id")
        return self._operations.update_dataset(self)
