from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeAlias
from uuid import uuid4

from typing_extensions import TypedDict

FieldKind: TypeAlias = Literal["DIMENSION", "MEASURE"]
CalcMode: TypeAlias = Literal["direct", "formula", "parameter"]
Aggregation: TypeAlias = Literal["none", "sum", "avg", "min", "max", "count", "countunique"]
DataType: TypeAlias = Literal[
    "string",
    "integer",
    "float",
    "date",
    "datetime",
    "boolean",
    "geopoint",
    "geopolygon",
    "uuid",
    "markup",
    "datetimetz",
    "unsupported",
    "array_str",
    "array_int",
    "array_float",
    "tree_str",
    "genericdatetime",
]
ParameterDataType: TypeAlias = Literal["string", "integer", "float", "date", "datetime", "boolean"]
ParameterValue: TypeAlias = str | int | float | bool | None
FilterValue: TypeAlias = str | int | float | bool | None
FilterValues: TypeAlias = Sequence[FilterValue]
JoinType: TypeAlias = Literal["inner", "left", "right", "full"]
JoinOperator: TypeAlias = Literal["gt", "lt", "gte", "lte", "eq", "ne"]
WhereOperation: TypeAlias = Literal[
    "ISNULL",
    "ISNOTNULL",
    "GT",
    "LT",
    "GTE",
    "LTE",
    "EQ",
    "NE",
    "STARTSWITH",
    "ISTARTSWITH",
    "ENDSWITH",
    "IENDSWITH",
    "CONTAINS",
    "ICONTAINS",
    "NOTCONTAINS",
    "NOTICONTAINS",
    "LENEQ",
    "LENNE",
    "LENGT",
    "LENGTE",
    "LENLT",
    "LENLTE",
    "IN",
    "NIN",
    "BETWEEN",
]
NumberFormat: TypeAlias = Literal["number", "percent"]
NumberFormatUnit: TypeAlias = Literal["auto", "k", "m", "b", "t"]
RLSSubjectType: TypeAlias = Literal["user", "group", "all", "userid"]
RLSPatternType: TypeAlias = Literal["value", "all", "userid"]
ManagedBy: TypeAlias = Literal["user", "feature", "compiler_runtime"]
CacheInvalidationMode: TypeAlias = Literal["sql", "formula", "off"]
SettingName: TypeAlias = Literal[
    "load_preview_by_default",
    "template_enabled",
    "data_export_forbidden",
]


@dataclass(frozen=True, slots=True)
class CacheInvalidationFormula:
    formula: str = ""
    guid_formula: str = ""


@dataclass(frozen=True, slots=True)
class CacheInvalidationField:
    guid: str = ""
    title: str = "INVALIDATION CACHE SERVICE FIELD"
    type: FieldKind | None = None
    aggregation: Aggregation = "none"
    cast: DataType = "string"
    data_type: DataType = "string"
    calc_spec: CacheInvalidationFormula | None = None
    description: str = ""
    hidden: bool = False
    ui_settings: str = ""
    initial_data_type: DataType | None = None
    has_auto_aggregation: bool | None = None
    lock_aggregation: bool | None = None
    managed_by: ManagedBy | None = None
    valid: bool | None = None


@dataclass(frozen=True, slots=True)
class CacheInvalidationFilterCondition:
    column: str
    operation: WhereOperation
    values: tuple[FilterValue, ...] = ()


@dataclass(frozen=True, slots=True)
class CacheInvalidationFilter:
    field_guid: str
    default_filters: tuple[CacheInvalidationFilterCondition, ...]
    id: str = field(default_factory=lambda: str(uuid4()))
    managed_by: ManagedBy | None = "user"
    valid: bool = True


@dataclass(frozen=True, slots=True)
class CacheInvalidationSource:
    mode: CacheInvalidationMode = "off"
    sql: str | None = None
    field: CacheInvalidationField | None = None
    filters: tuple[CacheInvalidationFilter, ...] = ()


class RLSSubjectPayload(TypedDict, total=False):
    subject_id: str
    subject_type: RLSSubjectType
    subject_name: str


class RLS2ConfigEntryPayload(TypedDict, total=False):
    subject: RLSSubjectPayload
    allowed_value: str
    field_guid: str
    pattern_type: RLSPatternType


class FieldPayload(TypedDict, total=False):
    guid: str
    title: str
    source: str
    avatar_id: str
    calc_mode: CalcMode
    type: FieldKind
    hidden: bool
    aggregation: Aggregation
    cast: DataType | ParameterDataType
    description: str
    formula: str
    default_value: ParameterValue
    ui_settings: str


class RawSchemaColumnPayload(TypedDict, total=False):
    description: str | None
    has_auto_aggregation: bool | None
    lock_aggregation: bool | None
    name: str
    native_type: object | None
    nullable: bool | None
    title: str
    user_type: DataType | None


class UpdateDescriptionAction(TypedDict):
    action: Literal["update_description"]
    description: str


class AddFieldAction(TypedDict):
    action: Literal["add_field"]
    field: FieldPayload


class UpdateFieldAction(TypedDict):
    action: Literal["update_field"]
    field: FieldPayload


class DeleteFieldPayload(TypedDict):
    guid: str


class _CloneFieldRequired(TypedDict):
    from_guid: str
    title: str


class CloneFieldPayload(_CloneFieldRequired, total=False):
    guid: str


class DeleteFieldAction(TypedDict):
    action: Literal["delete_field"]
    field: DeleteFieldPayload


class CloneFieldAction(TypedDict):
    action: Literal["clone_field"]
    field: CloneFieldPayload


class SourcePayload(TypedDict, total=False):
    id: str
    title: str
    source_type: str
    connection_id: str
    parameters: dict[str, object]
    raw_schema: list[RawSchemaColumnPayload]


class _UpdateSourcePayloadRequired(TypedDict):
    id: str
    title: str
    source_type: str


class UpdateSourcePayload(_UpdateSourcePayloadRequired, total=False):
    connection_id: str | None
    parameters: dict[str, object]
    raw_schema: list[RawSchemaColumnPayload]


class DeleteSourcePayload(TypedDict):
    id: str


class ReplaceConnectionPayload(TypedDict):
    id: str
    new_id: str


class AddSourceAction(TypedDict):
    action: Literal["add_source"]
    source: SourcePayload


class UpdateSourceAction(TypedDict):
    action: Literal["update_source"]
    source: UpdateSourcePayload


class DeleteSourceAction(TypedDict):
    action: Literal["delete_source"]
    source: DeleteSourcePayload


class ReplaceConnectionAction(TypedDict):
    action: Literal["replace_connection"]
    connection: ReplaceConnectionPayload


class WherePayload(TypedDict):
    column: str
    operation: WhereOperation
    values: list[FilterValue]


class SourceAvatarPayload(TypedDict, total=False):
    id: str
    source_id: str
    title: str
    is_root: bool


class DeleteSourceAvatarPayload(TypedDict):
    id: str


class AddSourceAvatarAction(TypedDict):
    action: Literal["add_source_avatar"]
    source_avatar: SourceAvatarPayload


class UpdateSourceAvatarAction(TypedDict):
    action: Literal["update_source_avatar"]
    source_avatar: SourceAvatarPayload


class DeleteSourceAvatarAction(TypedDict):
    action: Literal["delete_source_avatar"]
    source_avatar: DeleteSourceAvatarPayload


class ObligatoryFilterPayload(TypedDict):
    id: str
    field_guid: str
    default_filters: list[WherePayload]


class DeleteObligatoryFilterPayload(TypedDict):
    id: str


class AddObligatoryFilterAction(TypedDict):
    action: Literal["add_obligatory_filter"]
    obligatory_filter: ObligatoryFilterPayload


class UpdateObligatoryFilterAction(TypedDict):
    action: Literal["update_obligatory_filter"]
    obligatory_filter: ObligatoryFilterPayload


class DeleteObligatoryFilterAction(TypedDict):
    action: Literal["delete_obligatory_filter"]
    obligatory_filter: DeleteObligatoryFilterPayload


class ConditionPartPayload(TypedDict):
    calc_mode: Literal["direct"]
    source: str


class JoinConditionPayload(TypedDict):
    left: ConditionPartPayload
    operator: JoinOperator
    right: ConditionPartPayload
    type: Literal["binary"]


class AvatarRelationPayload(TypedDict):
    id: str
    join_type: JoinType
    conditions: list[JoinConditionPayload]
    required: bool
    managed_by: ManagedBy
    left_avatar_id: str | None
    right_avatar_id: str | None


class DeleteAvatarRelationPayload(TypedDict):
    id: str


class AddAvatarRelationAction(TypedDict):
    action: Literal["add_avatar_relation"]
    avatar_relation: AvatarRelationPayload


class UpdateAvatarRelationAction(TypedDict):
    action: Literal["update_avatar_relation"]
    avatar_relation: AvatarRelationPayload


class DeleteAvatarRelationAction(TypedDict):
    action: Literal["delete_avatar_relation"]
    avatar_relation: DeleteAvatarRelationPayload


@dataclass(frozen=True, slots=True)
class JoinCondition:
    left: str
    right: str
    operator: JoinOperator = "eq"


class DatasetCreateRelationPayload(TypedDict):
    type: JoinType
    conditions: tuple[JoinCondition, ...]
    drop_duplicates: bool
    left_avatar_id: str
    right_avatar_id: str


class RefreshSourcePayload(TypedDict):
    id: str
    force_update_fields: bool


class RefreshSourceAction(TypedDict):
    action: Literal["refresh_source"]
    source: RefreshSourcePayload


class UpdateSettingPayload(TypedDict):
    name: SettingName
    value: bool


class UpdateSettingAction(TypedDict):
    action: Literal["update_setting"]
    setting: UpdateSettingPayload


class CacheInvalidationFormulaPayload(TypedDict):
    formula: str
    guid_formula: str


class CacheInvalidationFieldPayload(TypedDict, total=False):
    guid: str
    title: str
    type: FieldKind
    aggregation: Aggregation
    cast: DataType
    data_type: DataType
    calc_spec: CacheInvalidationFormulaPayload
    description: str
    hidden: bool
    ui_settings: str
    initial_data_type: DataType | None
    has_auto_aggregation: bool | None
    lock_aggregation: bool | None
    managed_by: ManagedBy | None
    valid: bool | None


class CacheInvalidationFilterPayload(TypedDict):
    id: str
    field_guid: str
    default_filters: list[WherePayload]
    managed_by: ManagedBy | None
    valid: bool


class CacheInvalidationSourcePayload(TypedDict, total=False):
    mode: CacheInvalidationMode
    sql: str | None
    field: CacheInvalidationFieldPayload
    filters: list[CacheInvalidationFilterPayload]


def cache_invalidation_source_payload(source: CacheInvalidationSource) -> CacheInvalidationSourcePayload:
    payload: CacheInvalidationSourcePayload = {
        "mode": source.mode,
        "filters": [
            CacheInvalidationFilterPayload(
                id=filter_.id,
                field_guid=filter_.field_guid,
                default_filters=[
                    {
                        "column": condition.column,
                        "operation": condition.operation,
                        "values": list(condition.values),
                    }
                    for condition in filter_.default_filters
                ],
                managed_by=filter_.managed_by,
                valid=filter_.valid,
            )
            for filter_ in source.filters
        ],
    }
    if source.sql is not None:
        payload["sql"] = source.sql
    if source.field is not None:
        field: CacheInvalidationFieldPayload = {
            "guid": source.field.guid,
            "title": source.field.title,
            "aggregation": source.field.aggregation,
            "cast": source.field.cast,
            "data_type": source.field.data_type,
            "description": source.field.description,
            "hidden": source.field.hidden,
            "ui_settings": source.field.ui_settings,
            "initial_data_type": source.field.initial_data_type,
            "has_auto_aggregation": source.field.has_auto_aggregation,
            "lock_aggregation": source.field.lock_aggregation,
            "managed_by": source.field.managed_by,
            "valid": source.field.valid,
        }
        if source.field.type is not None:
            field["type"] = source.field.type
        if source.field.calc_spec is not None:
            field["calc_spec"] = {
                "formula": source.field.calc_spec.formula,
                "guid_formula": source.field.calc_spec.guid_formula,
            }
        payload["field"] = field
    return payload


class UpdateCacheInvalidationSourceAction(TypedDict):
    action: Literal["update_cache_invalidation_source"]
    cache_invalidation_source: CacheInvalidationSourcePayload


DatasetUpdateAction: TypeAlias = (
    UpdateDescriptionAction
    | AddFieldAction
    | UpdateFieldAction
    | DeleteFieldAction
    | CloneFieldAction
    | AddSourceAction
    | UpdateSourceAction
    | DeleteSourceAction
    | RefreshSourceAction
    | AddSourceAvatarAction
    | UpdateSourceAvatarAction
    | DeleteSourceAvatarAction
    | AddAvatarRelationAction
    | UpdateAvatarRelationAction
    | DeleteAvatarRelationAction
    | ReplaceConnectionAction
    | AddObligatoryFilterAction
    | UpdateObligatoryFilterAction
    | DeleteObligatoryFilterAction
    | UpdateSettingAction
    | UpdateCacheInvalidationSourceAction
)
