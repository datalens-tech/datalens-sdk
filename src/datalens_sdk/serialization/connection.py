from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from datalens_sdk.errors import DataLensValidationError
from datalens_sdk.serialization.json_types import JsonValue, normalize_json_object

CONNECTION_SERVER_OWNED_FIELDS = frozenset(
    {
        "collection_id",
        "connectionId",
        "connection_id",
        "createdAt",
        "created_at",
        "db_type",
        "dir_path",
        "entryId",
        "entry_id",
        "favorite",
        "fullPermissions",
        "full_permissions",
        "id",
        "isFavorite",
        "is_favorite",
        "key",
        "meta",
        "name",
        "operation",
        "options",
        "permissions",
        "replacement_types",
        "revId",
        "rev_id",
        "revisionId",
        "revision_id",
        "scope",
        "type",
        "updatedAt",
        "updated_at",
        "workbook_id",
    }
)
_CONNECTION_ID_KEYS = ("id", "entryId", "entry_id", "connectionId", "connection_id")


@dataclass(frozen=True, slots=True)
class ConnectionSnapshotView(Mapping[str, JsonValue]):
    snapshot: dict[str, JsonValue] = field(repr=False)
    connector: str

    @classmethod
    def from_raw(cls, raw: Mapping[str, JsonValue]) -> ConnectionSnapshotView:
        if isinstance(raw, cls):
            return raw

        return cls.capture(raw)

    @classmethod
    def capture(cls, raw: Mapping[str, JsonValue]) -> ConnectionSnapshotView:
        snapshot = normalize_json_object(raw, context="Connection response snapshot")
        return cls._from_normalized(snapshot)

    @classmethod
    def _from_normalized(cls, snapshot: dict[str, JsonValue]) -> ConnectionSnapshotView:
        connector = snapshot.get("type") or snapshot.get("db_type")
        if not isinstance(connector, str) or not connector:
            raise DataLensValidationError(
                "Connection response snapshot has no connector type; fetch it with client.get.connection(...) first"
            )
        if not any(isinstance(snapshot.get(key), str) and snapshot[key] for key in _CONNECTION_ID_KEYS):
            raise DataLensValidationError(
                "Connection response snapshot has no source id; fetch it with client.get.connection(...) first"
            )
        if not any(isinstance(snapshot.get(key), str) and snapshot[key] for key in ("name", "key")):
            raise DataLensValidationError(
                "Connection response snapshot has no resource name or key; "
                "fetch it with client.get.connection(...) first"
            )
        return cls(snapshot=snapshot, connector=connector)

    def __getitem__(self, key: str) -> JsonValue:
        return self.snapshot[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.snapshot)

    def __len__(self) -> int:
        return len(self.snapshot)


@dataclass(frozen=True, slots=True)
class ConnectionOverridesView(Mapping[str, JsonValue]):
    data: dict[str, JsonValue] = field(repr=False)

    @classmethod
    def from_raw(cls, raw: Mapping[str, JsonValue]) -> ConnectionOverridesView:
        if isinstance(raw, cls):
            return raw

        return cls.capture(raw)

    @classmethod
    def capture(cls, raw: Mapping[str, JsonValue]) -> ConnectionOverridesView:
        normalized = normalize_json_object(raw, context="Connection raw overrides")
        forbidden = sorted(set(normalized) & CONNECTION_SERVER_OWNED_FIELDS)
        if forbidden:
            raise DataLensValidationError(
                "Connection raw overrides cannot set identity, location, connector, or server-owned fields: "
                f"{forbidden}"
            )
        return cls(data=normalized)

    def __getitem__(self, key: str) -> JsonValue:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)
