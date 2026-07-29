from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from uuid import uuid4

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter._dataset_policy import with_supported_rls2_state
from datalens_sdk.converter._navigation import name_from_key
from datalens_sdk.converter._utils import _optional_str, _read_response_id
from datalens_sdk.converter.raw.dataset import (
    RawDatasetCreateEnvelope,
    RawDatasetReplaceData,
    RawDatasetReplaceEnvelope,
    dataset_content_from_snapshot,
)
from datalens_sdk.domain.dataset import Dataset, Source, SourcesProxy
from datalens_sdk.domain.dataset_types import (
    DatasetCreateRelationPayload,
    DatasetUpdateAction,
    DataType,
    RawSchemaColumnPayload,
    RLS2ConfigEntryPayload,
)
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    dir_path_from_location,
    resolve_entry_location_from_api_fields,
    workbook_id_from_location,
)
from datalens_sdk.domain.ports import DatasetOperations
from datalens_sdk.domain.specs.dataset import DatasetCreateSpec, DatasetUpdateSpec
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.serialization.artifacts import DatasetSnapshotView
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object


class DatasetSourceDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class DatasetContentDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class DatasetCreateDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class DatasetReadDTOProtocol(Protocol):
    raw: dict[str, object]

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, object]: ...


class DatasetSourceDTOClass(Protocol):
    def __call__(
        self,
        *,
        id: str,
        title: str,
        source_type: str,
        connection_id: str | None,
        connection_type: str,
        parameters: Mapping[str, object],
        raw_schema: tuple[RawSchemaColumnPayload, ...],
    ) -> DatasetSourceDTOProtocol: ...


class DatasetContentDTOClass(Protocol):
    def __call__(
        self,
        *,
        description: str,
        sources: tuple[DatasetSourceDTOProtocol, ...],
        source_avatars: tuple[object, ...],
        avatar_relations: tuple[object, ...],
        result_schema: tuple[Mapping[str, object], ...] = (),
        obligatory_filters: tuple[Mapping[str, object], ...] = (),
        rls2: Mapping[str, object] | None = None,
    ) -> DatasetContentDTOProtocol: ...


class DatasetCreateDTOClass(Protocol):
    def __call__(
        self,
        *,
        installation: str,
        name: str,
        dir_path: str | None,
        workbook_id: str | None = None,
        collection_id: str | None = None,
        dataset: DatasetContentDTOProtocol,
    ) -> DatasetCreateDTOProtocol: ...


class DatasetReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> DatasetReadDTOProtocol: ...


class DatasetDtoModule(Protocol):
    DatasetSourceDTO: DatasetSourceDTOClass
    DatasetContentDTO: DatasetContentDTOClass
    DatasetCreateDTO: DatasetCreateDTOClass
    DatasetReadDTO: DatasetReadDTOClass


def _dto_module(dto_module: DatasetDtoModule | None) -> DatasetDtoModule:
    return cast(DatasetDtoModule, generated_dto if dto_module is None else dto_module)


def _dict_with_string_keys(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


_DATA_TYPE_VALUES: tuple[DataType, ...] = (
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
)


def _optional_data_type(value: object) -> DataType | None:
    if value in _DATA_TYPE_VALUES:
        return value
    return None


def _list_of_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_dict_with_string_keys(item) for item in value if isinstance(item, Mapping))


def _raw_schema(value: object) -> tuple[RawSchemaColumnPayload, ...]:
    return tuple(
        RawSchemaColumnPayload(
            description=_optional_str(item.get("description")),
            has_auto_aggregation=_optional_bool(item.get("has_auto_aggregation")),
            lock_aggregation=_optional_bool(item.get("lock_aggregation")),
            name=str(item.get("name") or ""),
            native_type=item.get("native_type"),
            nullable=_optional_bool(item.get("nullable")),
            title=str(item.get("title") or ""),
            user_type=_optional_data_type(item.get("user_type")),
        )
        for item in _list_of_mappings(value)
    )


def _dataset_content(raw: Mapping[str, object]) -> dict[str, object]:
    data = _dict_with_string_keys(raw.get("dataset"))
    return with_supported_rls2_state(data)


def _read_response_state(raw: Mapping[str, object]) -> dict[str, object]:
    out = dict(raw)
    if isinstance(out.get("dataset"), Mapping):
        out["dataset"] = _dataset_content(out)
    return out


_DATASET_ID_KEYS: tuple[str, ...] = ("id", "entryId", "entry_id", "datasetId", "dataset_id")


class DatasetConverter:
    @staticmethod
    def from_domain_create(
        spec: DatasetCreateSpec,
        *,
        dto_module: DatasetDtoModule | None = None,
    ) -> DatasetCreateDTOProtocol:
        generated = _dto_module(dto_module)
        source_dtos = tuple(
            generated.DatasetSourceDTO(
                id=source.id,
                title=source.title,
                source_type=source.source_type,
                connection_id=source.connection_id,
                connection_type=source.connection_type,
                parameters=dict(source.parameters),
                raw_schema=source.raw_schema,
            )
            for source in spec.sources
        )
        return generated.DatasetCreateDTO(
            installation=spec.installation,
            name=spec.name,
            dir_path=dir_path_from_location(spec.location),
            workbook_id=workbook_id_from_location(spec.location),
            collection_id=collection_id_from_location(spec.location),
            dataset=generated.DatasetContentDTO(
                description=spec.description,
                sources=source_dtos,
                source_avatars=(),
                avatar_relations=(),
            ),
        )

    @staticmethod
    def empty_dataset_state() -> dict[str, object]:
        return {
            "avatar_relations": [],
            "component_errors": {"items": []},
            "description": "",
            "load_preview_by_default": True,
            "obligatory_filters": [],
            "result_schema": [],
            "result_schema_aux": {"inter_dependencies": {"deps": []}},
            "source_avatars": [],
            "source_features": {},
            "sources": [],
        }

    @staticmethod
    def from_domain_create_validate_step(
        *,
        sources: Sequence[Source],
        relations: Sequence[DatasetCreateRelationPayload],
        relation_sources: Sequence[Source] | None = None,
        existing_state: Mapping[str, object] | None = None,
        refresh_sources: bool = False,
        actions: Sequence[DatasetUpdateAction] = (),
    ) -> dict[str, object]:
        updates: list[dict[str, object]] = []
        for source in sources:
            source_dict: dict[str, object] = {
                "id": source.id,
                "title": source.title,
                "group": [],
                "source_type": source.source_type,
                "connection_id": source.connection_id,
                "parameters": dict(source.parameters),
                "tab_title": "Table",
                "disabled": False,
            }
            needs_refresh = refresh_sources and not source.raw_schema
            if refresh_sources:
                source_dict["raw_schema"] = [dict(column) for column in source.raw_schema]
            updates.extend(
                [
                    {
                        "action": "add_source",
                        "source": source_dict,
                    },
                    {
                        "action": "add_source_avatar",
                        "source_avatar": {
                            "id": source.id,
                            "is_root": True,
                            "title": source.title,
                            "source_id": source.id,
                        },
                    },
                ]
            )
            if needs_refresh:
                updates.append(
                    {
                        "action": "refresh_source",
                        "source": {"id": source.id, "force_update_fields": True},
                    }
                )

        for relation in relations:
            updates.append(
                {
                    "action": "add_avatar_relation",
                    "avatar_relation": {
                        "id": str(uuid4()),
                        "left_avatar_id": relation["left_avatar_id"],
                        "right_avatar_id": relation["right_avatar_id"],
                        "join_type": relation["type"],
                        "conditions": [
                            {
                                "type": "binary",
                                "operator": cond.operator,
                                "left": {"calc_mode": "direct", "source": cond.left},
                                "right": {"calc_mode": "direct", "source": cond.right},
                            }
                            for cond in relation["conditions"]
                        ],
                        "required": relation["drop_duplicates"],
                    },
                }
            )

        updates.extend(dict(action) for action in actions)

        dataset = with_supported_rls2_state(
            dict(existing_state) if existing_state is not None else DatasetConverter.empty_dataset_state()
        )
        return {"datasetId": "", "data": {"dataset": dataset, "updates": updates}}

    @staticmethod
    def build_validate_source_payload(source: Source) -> dict[str, object]:
        return DatasetConverter.from_domain_create_validate_step(
            sources=[source],
            relations=[],
            existing_state=None,
            refresh_sources=True,
        )

    @staticmethod
    def parse_validate_source_response(
        response: Mapping[str, object],
        source_id: str,
    ) -> tuple[tuple[RawSchemaColumnPayload, ...], bool]:
        state = DatasetConverter.state_from_read_response(response)
        raw_sources = state.get("sources")
        if isinstance(raw_sources, list):
            for raw_source in raw_sources:
                src = _dict_with_string_keys(raw_source)
                if str(src.get("id") or "") == source_id:
                    valid = bool(src.get("valid", True))
                    schema = _raw_schema(src.get("raw_schema"))
                    return schema, valid
        return (), False

    @staticmethod
    def to_domain(
        raw: Mapping[str, object] | DatasetReadDTOProtocol,
        *,
        installation: str,
        operations: DatasetOperations | None = None,
        location: EntryLocation | None = None,
        name: str | None = None,
        id_fallback: str | None = None,
        dto_module: DatasetDtoModule | None = None,
    ) -> Dataset:
        response_snapshot: dict[str, JsonValue] = {}
        generated = _dto_module(dto_module)
        if isinstance(raw, Mapping):
            response_snapshot = normalize_json_object(raw, context="Dataset API response")
            dto_validation_input = dict(response_snapshot)
            dto_validation_input["raw"] = response_snapshot
            generated.DatasetReadDTO.model_validate(dto_validation_input)
            data = _read_response_state(
                normalize_json_object(
                    response_snapshot,
                    context="Dataset typed response state",
                )
            )
        else:
            read_dto = raw
            data = _read_response_state(read_dto.raw or read_dto.model_dump(exclude_none=True))
        dataset = _dataset_content(data)
        raw_sources = dataset.get("sources")
        sources: list[Source] = []
        if isinstance(raw_sources, list):
            for raw_source in raw_sources:
                source_data = _dict_with_string_keys(raw_source)
                if not source_data:
                    continue
                source_type = str(source_data.get("source_type") or "")
                parameters = _dict_with_string_keys(source_data.get("parameters"))
                sources.append(
                    Source(
                        id=str(source_data.get("id") or ""),
                        source_type=source_type,
                        title=str(source_data.get("title") or ""),
                        connection_id=_optional_str(source_data.get("connection_id")),
                        connection_type=str(source_data.get("connection_type") or ""),
                        parameters=parameters,
                        raw_schema=_raw_schema(source_data.get("raw_schema")),
                        valid=bool(source_data.get("valid", True)),
                    )
                )
        rls2 = _dict_with_string_keys(dataset.get("rls2"))
        key = _optional_str(data.get("key"))
        domain_location = resolve_entry_location_from_api_fields(
            dir_path=_optional_str(data.get("dir_path")),
            key=key,
            collection_id=_optional_str(data.get("collection_id")),
            workbook_id=_optional_str(data.get("workbook_id")),
            fallback=location,
        )
        return Dataset(
            id=_read_response_id(data, keys=_DATASET_ID_KEYS) or id_fallback,
            name=_optional_str(data.get("name")) or name_from_key(key) or name,
            installation=installation,
            description=str(dataset.get("description") or ""),
            location=domain_location,
            sources=SourcesProxy(sources),
            source_avatars=_list_of_mappings(dataset.get("source_avatars")),
            avatar_relations=_list_of_mappings(dataset.get("avatar_relations")),
            result_schema=_list_of_mappings(dataset.get("result_schema")),
            obligatory_filters=_list_of_mappings(dataset.get("obligatory_filters")),
            rls2=rls2,
            raw=data,
            response_snapshot=response_snapshot,
            is_favorite=_optional_bool(data.get("is_favorite")),
            permissions=_dict_with_string_keys(data.get("permissions")),
            full_permissions=_dict_with_string_keys(data.get("full_permissions")),
            options=_dict_with_string_keys(data.get("options")),
            published_id=_optional_str(data.get("publishedId")),
            rev_id=_optional_str(data.get("revId")),
            saved_id=_optional_str(data.get("savedId")),
            _operations=operations,
        )

    @staticmethod
    def from_raw_create(spec: RawCreateSpec) -> RawDatasetCreateEnvelope:
        source = DatasetSnapshotView.from_raw(spec.response_snapshot)
        return RawDatasetCreateEnvelope(
            name=spec.name,
            dir_path=dir_path_from_location(spec.location),
            workbook_id=workbook_id_from_location(spec.location),
            collection_id=collection_id_from_location(spec.location),
            dataset=dataset_content_from_snapshot(source),
        )

    @staticmethod
    def from_raw_replace(spec: RawReplaceSpec) -> RawDatasetReplaceEnvelope:
        source = DatasetSnapshotView.from_raw(spec.response_snapshot)
        return RawDatasetReplaceEnvelope(
            dataset_id=spec.target_id,
            data=RawDatasetReplaceData(dataset=dataset_content_from_snapshot(source)),
        )

    @staticmethod
    def from_domain_validate(spec: DatasetUpdateSpec) -> dict[str, object]:
        return {
            "datasetId": spec.dataset_id,
            "data": {
                "dataset": _dataset_content(spec.raw),
                "updates": [dict(action) for action in spec.actions],
            },
        }

    @staticmethod
    def state_from_read_response(raw: Mapping[str, object]) -> dict[str, object]:
        return _dataset_content(raw)

    @staticmethod
    def state_for_name_only(spec: DatasetUpdateSpec) -> dict[str, object]:
        state = _dataset_content(spec.raw)
        if spec.name_change is not None:
            state["name"] = spec.name_change
        return state

    @staticmethod
    def apply_rls2_changes(
        state: Mapping[str, object],
        changes: Mapping[str, Sequence[RLS2ConfigEntryPayload] | None],
    ) -> dict[str, object]:
        out = with_supported_rls2_state(state)
        if not changes:
            return out
        existing = _dict_with_string_keys(out.get("rls2"))
        rls2: dict[str, object] = dict(existing)
        for guid, entries in changes.items():
            if entries is None:
                rls2.pop(guid, None)
            else:
                current = rls2.get(guid)
                merged = list(current) if isinstance(current, list) else []
                merged.extend(dict(entry) for entry in entries)
                rls2[guid] = merged
        out["rls2"] = rls2
        return out
