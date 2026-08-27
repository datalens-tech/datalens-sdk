from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import overload
from uuid import uuid4

from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.data import (
    DatasetData,
    DatasetDataFilter,
    DatasetDataParameter,
    DatasetDataQuery,
    DatasetDataSort,
)
from datalens_sdk.domain.dataset_types import (
    Aggregation,
    CacheInvalidationSource,
    CalcMode,
    DatasetCreateRelationPayload,
    DataType,
    FieldKind,
    FilterValues,
    JoinCondition,
    JoinType,
    NumberFormat,
    NumberFormatUnit,
    ParameterDataType,
    ParameterValue,
    RawSchemaColumnPayload,
    RLSPatternType,
    RLSSubjectType,
    SettingName,
    WhereOperation,
)
from datalens_sdk.domain.dataset_update import DatasetUpdate
from datalens_sdk.domain.entry_location import (
    EntryLocation,
    collection_id_from_location,
    dir_path_from_location,
    key_from_location,
    resolve_entry_location,
    validate_entry_name,
    workbook_id_from_location,
)
from datalens_sdk.domain.fields import DatasetField, FieldLike, FieldRef, FieldsProxy
from datalens_sdk.domain.navigation import EntryRelation, EntryScope, LinkDirection, Pager, RelationOptions
from datalens_sdk.domain.ports import DatasetOperations
from datalens_sdk.domain.specs.dataset import DatasetCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError, NotSupportedError
from datalens_sdk.serialization.artifacts import ArtifactPath, write_dataset_artifact
from datalens_sdk.serialization.json_types import JsonValue

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(slots=True)
class Source:
    id: str
    source_type: str
    title: str
    connection_id: str | None
    connection_type: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    raw_schema: tuple[RawSchemaColumnPayload, ...] = ()
    valid: bool = True

    @property
    def fields(self) -> FieldsProxy:
        return FieldsProxy(self.raw_schema)


class SourcesProxy(Sequence[Source]):
    def __init__(self, sources: Sequence[Source]) -> None:
        self._sources = tuple(sources)

    def by_alias(self, alias: str) -> Source:
        for source in self._sources:
            if source.title == alias or source.id == alias:
                return source
        raise ValueError(f"Source with alias {alias!r} not found")

    def __iter__(self) -> Iterator[Source]:
        return iter(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    @overload
    def __getitem__(self, index: int) -> Source: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Source]: ...

    def __getitem__(self, index: int | slice) -> Source | Sequence[Source]:
        return self._sources[index]


SourceRef = Source | str


def _source_ref_id(source: SourceRef) -> str:
    if isinstance(source, Source):
        return source.id
    return source


class SourceBuilder:
    def __init__(
        self,
        *,
        installation: str,
        connection: Connection,
        source_types: Mapping[str, Mapping[str, object]],
        operations: DatasetOperations | None = None,
    ) -> None:
        self._installation = installation
        self._connection = connection
        self._source_types = source_types
        self._operations = operations

    def raw(self, *, alias: str, source_type: str, parameters: Mapping[str, object] | None = None) -> Source:
        if self._connection.installation and self._connection.installation != self._installation:
            raise NotSupportedError(
                f"Cannot use a {self._connection.installation!r} connection in a {self._installation!r} dataset"
            )
        meta = self._source_types.get(source_type)
        if meta is None:
            raise NotSupportedError(
                f"Dataset source type {source_type!r} is not available on installation {self._installation!r}"
            )
        expected_connection_type = meta.get("connection_type")
        if expected_connection_type and self._connection.type != expected_connection_type:
            raise NotSupportedError(
                f"Dataset source {source_type!r} requires {expected_connection_type!r}, got {self._connection.type!r}"
            )
        if not self._connection.id:
            raise DataLensValidationError("Dataset source requires a connection with an id")
        return Source(
            id=str(uuid4()),
            source_type=source_type,
            title=alias,
            connection_id=self._connection.id,
            connection_type=self._connection.type,
            parameters=dict(parameters or {}),
        )


class SourceCreate:
    def __init__(self, *, source: Source, operations: DatasetOperations | None) -> None:
        self._source = source
        self._operations = operations

    def build(self, *, strict: bool = False) -> Source:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        schema, valid = self._operations.validate_source(self._source, strict=strict)
        return Source(
            id=self._source.id,
            source_type=self._source.source_type,
            title=self._source.title,
            connection_id=self._source.connection_id,
            connection_type=self._source.connection_type,
            parameters=self._source.parameters,
            raw_schema=schema,
            valid=valid,
        )


class DatasetCreate:
    def __init__(
        self,
        *,
        installation: str,
        name: str,
        location: EntryLocation,
        operations: DatasetOperations | None = None,
    ) -> None:
        self._installation = installation
        self._location = resolve_entry_location(
            location=location,
            installation=installation,
        )
        validate_entry_name(name=name, location=self._location)
        self._name = name
        self._operations = operations
        self._description = ""
        self._sources: list[Source] = []
        self._relations: list[DatasetCreateRelationPayload] = []
        self._mutations = DatasetUpdate(
            dataset=Dataset(
                id=None,
                name=name,
                installation=installation,
                location=self._location,
                _operations=operations,
            ),
            operations=operations,
        )

    def description(self, value: str) -> DatasetCreate:
        self._description = value
        return self

    def sources(self, sources: list[Source]) -> DatasetCreate:
        self._sources = list(sources)
        return self

    def add_source(self, source: Source) -> DatasetCreate:
        self._sources.append(source)
        return self

    def add_relation(
        self,
        *,
        type: JoinType,
        conditions: Sequence[JoinCondition],
        left_source: SourceRef,
        right_source: SourceRef,
        drop_duplicates: bool = False,
    ) -> DatasetCreate:
        if not conditions:
            raise DataLensValidationError("'conditions' must not be empty")
        self._relations.append(
            {
                "type": type,
                "conditions": tuple(conditions),
                "drop_duplicates": drop_duplicates,
                "left_avatar_id": _source_ref_id(left_source),
                "right_avatar_id": _source_ref_id(right_source),
            }
        )
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
    ) -> DatasetCreate:
        self._mutations.add_field(
            title=title,
            source=source,
            kind=kind,
            avatar_id=avatar_id,
            calc_mode=calc_mode,
            aggregation=aggregation,
            cast=cast,
            description=description,
            hidden=hidden,
            guid=guid,
        )
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
    ) -> DatasetCreate:
        self._mutations.add_calculation(
            name=name,
            formula=formula,
            kind=kind,
            aggregation=aggregation,
            cast=cast,
            guid=guid,
        )
        return self

    def add_parameter(
        self,
        *,
        name: str,
        type: ParameterDataType,
        default: ParameterValue,
        guid: str | None = None,
    ) -> DatasetCreate:
        self._mutations.add_parameter(name=name, type=type, default=default, guid=guid)
        return self

    def update_field(
        self,
        *,
        field: FieldLike | str,
        title: str | None = None,
        cast: DataType | ParameterDataType | None = None,
        aggregation: Aggregation | None = None,
        description: str | None = None,
        hidden: bool | None = None,
        ui_settings: str | None = None,
    ) -> DatasetCreate:
        self._mutations.update_field(
            field=field,
            title=title,
            cast=cast,
            aggregation=aggregation,
            description=description,
            hidden=hidden,
            ui_settings=ui_settings,
        )
        return self

    def change_field_type(self, *, field: FieldLike | str, to: DataType) -> DatasetCreate:
        self._mutations.change_field_type(field=field, to=to)
        return self

    def change_field_aggregation(self, *, field: FieldLike | str, to: Aggregation) -> DatasetCreate:
        self._mutations.change_field_aggregation(field=field, to=to)
        return self

    def change_field_description(self, *, field: FieldLike | str, to: str) -> DatasetCreate:
        self._mutations.change_field_description(field=field, to=to)
        return self

    def update_field_format(
        self,
        *,
        field: FieldLike | str,
        format_: NumberFormat | None = None,
        precision: int | None = None,
        prefix: str | None = None,
        postfix: str | None = None,
        unit: NumberFormatUnit | None = None,
        show_rank_delimiter: bool | None = None,
    ) -> DatasetCreate:
        self._mutations.update_field_format(
            field=field,
            format_=format_,
            precision=precision,
            prefix=prefix,
            postfix=postfix,
            unit=unit,
            show_rank_delimiter=show_rank_delimiter,
        )
        return self

    def add_default_filter(
        self,
        *,
        field: FieldLike | str,
        operator: WhereOperation,
        values: FilterValues | None = None,
    ) -> DatasetCreate:
        self._mutations.add_default_filter(field=field, operator=operator, values=values)
        return self

    def add_rls(
        self,
        *,
        field: FieldLike | str,
        subject_id: str,
        allowed_value: str | None = None,
        subject_type: RLSSubjectType = "user",
        subject_name: str | None = None,
        pattern_type: RLSPatternType = "value",
    ) -> DatasetCreate:
        self._mutations.add_rls(
            field=field,
            subject_id=subject_id,
            allowed_value=allowed_value,
            subject_type=subject_type,
            subject_name=subject_name,
            pattern_type=pattern_type,
        )
        return self

    def clone_field(
        self,
        *,
        field: FieldLike | str,
        new_title: str,
        new_guid: str | None = None,
    ) -> DatasetCreate:
        self._mutations.clone_field(field=field, new_title=new_title, new_guid=new_guid)
        return self

    def hide_field(self, *, field: FieldLike | str) -> DatasetCreate:
        self._mutations.hide_field(field=field)
        return self

    def show_field(self, *, field: FieldLike | str) -> DatasetCreate:
        self._mutations.show_field(field=field)
        return self

    def update_setting(self, *, name: SettingName, value: bool) -> DatasetCreate:
        self._mutations.update_setting(name=name, value=value)
        return self

    def update_cache_invalidation_source(self, *, source: CacheInvalidationSource) -> DatasetCreate:
        self._mutations.update_cache_invalidation_source(source=source)
        return self

    def to_spec(self) -> DatasetCreateSpec:
        return DatasetCreateSpec(
            installation=self._installation,
            name=self._name,
            location=self._location,
            description=self._description,
            sources=tuple(self._sources),
            relations=tuple(self._relations),
            actions=self._mutations.actions,
            rls2_changes=dict(self._mutations.rls2_changes),
        )

    def build(self) -> Dataset:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.create_dataset(self)


@dataclass(slots=True)
class Dataset:
    id: str | None
    name: str | None = None
    installation: str = ""
    description: str = ""
    location: EntryLocation | None = None
    sources: SourcesProxy = field(default_factory=lambda: SourcesProxy(()))
    source_avatars: tuple[Mapping[str, object], ...] = ()
    avatar_relations: tuple[Mapping[str, object], ...] = ()
    result_schema: tuple[Mapping[str, object], ...] = ()
    obligatory_filters: tuple[Mapping[str, object], ...] = ()
    rls2: Mapping[str, object] = field(default_factory=dict)
    raw: Mapping[str, object] = field(default_factory=dict)
    response_snapshot: Mapping[str, JsonValue] = field(
        default_factory=dict,
        repr=False,
        compare=False,
        kw_only=True,
    )
    is_favorite: bool | None = None
    permissions: Mapping[str, object] = field(default_factory=dict)
    full_permissions: Mapping[str, object] = field(default_factory=dict)
    options: Mapping[str, object] = field(default_factory=dict)
    published_id: str | None = None
    rev_id: str | None = None
    saved_id: str | None = None
    _operations: DatasetOperations | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.name is None:
            self.name = _optional_str(self.raw.get("name"))

    @property
    def key(self) -> str | None:
        return _optional_str(self.raw.get("key")) or key_from_location(self.location, name=self.name)

    @property
    def dir_path(self) -> str | None:
        return dir_path_from_location(self.location) or _optional_str(self.raw.get("dir_path"))

    @property
    def workbook_id(self) -> str | None:
        return workbook_id_from_location(self.location) or _optional_str(self.raw.get("workbook_id"))

    @property
    def collection_id(self) -> str | None:
        return collection_id_from_location(self.location) or _optional_str(self.raw.get("collection_id"))

    @property
    def fields(self) -> FieldsProxy:
        return FieldsProxy(self.result_schema, dataset_id=self.id)

    @property
    def parameters(self) -> FieldsProxy:
        return FieldsProxy(
            tuple(field for field in self.result_schema if field.get("calc_mode") == "parameter"),
            dataset_id=self.id,
        )

    @property
    def relations(self) -> tuple[Mapping[str, object], ...]:
        return self.avatar_relations

    @property
    def default_filters(self) -> tuple[Mapping[str, object], ...]:
        return self.obligatory_filters

    @property
    def update(self) -> DatasetUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update a dataset without an id")
        return DatasetUpdate(dataset=self, operations=self._operations)

    def to_file(self, path: ArtifactPath) -> Path:
        return write_dataset_artifact(
            path,
            self.response_snapshot,
            name=self.name,
            resource_id=self.id,
        )

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete a dataset without an id")
        self._operations.delete_dataset(self.id)

    def rename(self, name: str) -> Dataset:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot rename a dataset without an id")
        validate_entry_name(name=name, location=self.location)
        return self._operations.rename_dataset(self, name)

    def get_relations(
        self,
        *,
        include_permissions_info: bool | None = None,
        link_direction: LinkDirection | None = None,
        page_size: int = 100,
        scope: EntryScope | None = None,
    ) -> Pager[EntryRelation]:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot get relations for a dataset without an id")
        return self._operations.get_entry_relations(
            self.id,
            RelationOptions(
                include_permissions_info=include_permissions_info,
                link_direction=link_direction,
                page_size=page_size,
                scope=scope,
            ),
        )

    def get_dataset_data(
        self,
        *,
        columns: Sequence[FieldRef],
        filters: Sequence[DatasetDataFilter] = (),
        params: Sequence[DatasetDataParameter] = (),
        sort: Sequence[DatasetDataSort] = (),
        limit: int = 500,
        offset: int | None = None,
    ) -> DatasetData:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot get data for a dataset without an id")
        return self._operations.get_dataset_data(
            DatasetDataQuery.create(
                dataset_id=self.id,
                columns=columns,
                filters=filters,
                params=params,
                sort=sort,
                limit=limit,
                offset=offset,
            )
        )

    def enrich_via_refresh(self, *, force_update_fields: bool = True) -> Dataset:
        if not self.sources:
            return self
        update = self.update
        for source in self.sources:
            update.refresh_source(source.id, force_update_fields=force_update_fields)
        return update.execute()

    def get_connection_ids(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for source in self.sources:
            if source.connection_id and source.connection_id not in seen:
                seen.add(source.connection_id)
                out.append(source.connection_id)
        return out

    def find_field(self, name_or_guid: str) -> DatasetField | None:
        fields = list(self.fields)
        for f in fields:
            if f.guid == name_or_guid:
                return f
        for f in fields:
            if f.title == name_or_guid or f.name == name_or_guid:
                return f
        return None

    def find_source_avatar(self, title_or_id: str) -> Mapping[str, object] | None:
        avatars = list(self.source_avatars)
        for avatar in avatars:
            if avatar.get("id") == title_or_id:
                return avatar
        for avatar in avatars:
            if avatar.get("source_id") == title_or_id or avatar.get("title") == title_or_id:
                return avatar
        return None

    def find_fields(
        self,
        *,
        grep: str | None = None,
        calc_mode: str | None = None,
        kind: str | None = None,
        hidden: bool | None = None,
        only_with_description: bool = False,
    ) -> list[DatasetField]:
        pattern = None
        if grep is not None:
            with contextlib.suppress(re.error):
                pattern = re.compile(grep, re.IGNORECASE)

        out: list[DatasetField] = []
        for f in self.fields:
            if pattern is not None and not pattern.search(f.title):
                continue
            if calc_mode is not None and f.calc_mode != calc_mode:
                continue
            if kind is not None and f.type != kind:
                continue
            if hidden is True and not f.hidden:
                continue
            if hidden is False and f.hidden:
                continue
            if only_with_description and not (f.description or "").strip():
                continue
            out.append(f)
        return out
