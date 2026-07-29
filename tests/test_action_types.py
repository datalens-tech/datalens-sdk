import json
from pathlib import Path
from typing import cast, get_args, get_type_hints

from datalens_sdk.domain.dataset_types import (
    AddSourceAction,
    AddSourceAvatarAction,
    CloneFieldAction,
    DatasetUpdateAction,
    DeleteAvatarRelationAction,
    DeleteFieldAction,
    DeleteObligatoryFilterAction,
    DeleteSourceAction,
    DeleteSourceAvatarAction,
    ReplaceConnectionAction,
    SettingName,
    UpdateAvatarRelationAction,
    UpdateCacheInvalidationSourceAction,
    UpdateObligatoryFilterAction,
    UpdateSettingAction,
    UpdateSourceAction,
    UpdateSourceAvatarAction,
)


def _openapi_actions(path: Path) -> set[str]:
    spec = cast(dict[str, object], json.loads(path.read_text()))
    components = cast(dict[str, object], spec["components"])
    schemas = cast(dict[str, object], components["schemas"])
    action = cast(dict[str, object], schemas["Action"])
    discriminator = cast(dict[str, object], action["discriminator"])
    mapping = cast(dict[str, object], discriminator["mapping"])
    return set(mapping)


def _sdk_actions() -> set[str]:
    members = get_args(DatasetUpdateAction)
    discriminators: set[str] = set()
    for member in members:
        action_hint = get_type_hints(member)["action"]
        args = get_args(action_hint)
        assert len(args) == 1
        discriminators.add(args[0])
    assert len(discriminators) == len(members)
    return discriminators


def test_action_union_matches_all_openapi_specs() -> None:
    public_root = Path(__file__).resolve().parents[1]
    spec_actions = [
        _openapi_actions(public_root / "spec" / "enterprise.json"),
        _openapi_actions(public_root / "spec" / "yacloud.json"),
    ]

    sdk_actions = _sdk_actions()
    assert all(actions == sdk_actions for actions in spec_actions)


def test_setting_signature_matches_all_openapi_specs() -> None:
    public_root = Path(__file__).resolve().parents[1]
    expected_names = set(get_args(SettingName))

    for path in (
        public_root / "spec" / "enterprise.json",
        public_root / "spec" / "yacloud.json",
    ):
        spec = cast(dict[str, object], json.loads(path.read_text()))
        components = cast(dict[str, object], spec["components"])
        schemas = cast(dict[str, object], components["schemas"])
        setting = cast(dict[str, object], schemas["Setting"])
        properties = cast(dict[str, object], setting["properties"])
        name_schema = cast(dict[str, object], properties["name"])
        value_schema = cast(dict[str, object], properties["value"])

        assert set(cast(list[str], name_schema["enum"])) == expected_names
        assert value_schema["type"] == "boolean"


def test_delete_field_action_shape() -> None:
    action: DeleteFieldAction = {
        "action": "delete_field",
        "field": {"guid": "field-1"},
    }
    assert action["action"] == "delete_field"
    assert action["field"]["guid"] == "field-1"


def test_clone_field_action_shape() -> None:
    action: CloneFieldAction = {
        "action": "clone_field",
        "field": {"from_guid": "field-1", "title": "Cloned Field"},
    }
    assert action["action"] == "clone_field"
    assert action["field"]["from_guid"] == "field-1"
    assert action["field"]["title"] == "Cloned Field"


def test_clone_field_action_with_new_guid() -> None:
    action: CloneFieldAction = {
        "action": "clone_field",
        "field": {"from_guid": "field-1", "guid": "field-2", "title": "Clone"},
    }
    assert action["field"]["from_guid"] == "field-1"
    assert action["field"]["guid"] == "field-2"
    assert action["field"]["title"] == "Clone"


def test_add_source_action_shape() -> None:
    action: AddSourceAction = {
        "action": "add_source",
        "source": {
            "id": "source-1",
            "title": "Test Source",
            "source_type": "TABLE",
            "connection_id": "conn-1",
            "parameters": {"table_name": "users"},
        },
    }
    assert action["action"] == "add_source"
    assert action["source"]["id"] == "source-1"
    assert action["source"]["title"] == "Test Source"
    assert action["source"]["connection_id"] == "conn-1"


def test_update_source_action_shape() -> None:
    action: UpdateSourceAction = {
        "action": "update_source",
        "source": {
            "id": "source-1",
            "title": "Updated Source",
            "source_type": "TABLE",
            "connection_id": "conn-1",
            "parameters": {"table_name": "users"},
            "raw_schema": [{"name": "id", "title": "ID", "user_type": "integer"}],
        },
    }
    assert action["action"] == "update_source"
    assert action["source"]["id"] == "source-1"
    assert action["source"]["title"] == "Updated Source"


def test_delete_source_action_shape() -> None:
    action: DeleteSourceAction = {
        "action": "delete_source",
        "source": {"id": "source-1"},
    }
    assert action["action"] == "delete_source"
    assert action["source"]["id"] == "source-1"


def test_add_source_avatar_action_shape() -> None:
    action: AddSourceAvatarAction = {
        "action": "add_source_avatar",
        "source_avatar": {
            "id": "avatar-1",
            "source_id": "source-1",
            "title": "Avatar Title",
            "is_root": True,
        },
    }
    assert action["action"] == "add_source_avatar"
    assert action["source_avatar"]["id"] == "avatar-1"
    assert action["source_avatar"]["source_id"] == "source-1"
    assert action["source_avatar"]["is_root"] is True


def test_update_source_avatar_action_shape() -> None:
    action: UpdateSourceAvatarAction = {
        "action": "update_source_avatar",
        "source_avatar": {"id": "avatar-1", "title": "Updated Avatar"},
    }
    assert action["action"] == "update_source_avatar"
    assert action["source_avatar"]["id"] == "avatar-1"
    assert action["source_avatar"]["title"] == "Updated Avatar"


def test_delete_source_avatar_action_shape() -> None:
    action: DeleteSourceAvatarAction = {
        "action": "delete_source_avatar",
        "source_avatar": {"id": "avatar-1"},
    }
    assert action["action"] == "delete_source_avatar"
    assert action["source_avatar"]["id"] == "avatar-1"


def test_update_avatar_relation_action_shape() -> None:
    action: UpdateAvatarRelationAction = {
        "action": "update_avatar_relation",
        "avatar_relation": {
            "id": "relation-1",
            "join_type": "inner",
            "conditions": [
                {
                    "left": {"calc_mode": "direct", "source": "field-1"},
                    "operator": "eq",
                    "right": {"calc_mode": "direct", "source": "field-2"},
                    "type": "binary",
                }
            ],
            "required": False,
            "managed_by": "user",
            "left_avatar_id": "avatar-1",
            "right_avatar_id": "avatar-2",
        },
    }
    assert action["action"] == "update_avatar_relation"
    assert action["avatar_relation"]["id"] == "relation-1"
    assert action["avatar_relation"]["join_type"] == "inner"


def test_delete_avatar_relation_action_shape() -> None:
    action: DeleteAvatarRelationAction = {
        "action": "delete_avatar_relation",
        "avatar_relation": {"id": "relation-1"},
    }
    assert action["action"] == "delete_avatar_relation"
    assert action["avatar_relation"]["id"] == "relation-1"


def test_replace_connection_action_shape() -> None:
    action: ReplaceConnectionAction = {
        "action": "replace_connection",
        "connection": {
            "id": "conn-1",
            "new_id": "conn-2",
        },
    }
    assert action["action"] == "replace_connection"
    assert action["connection"]["id"] == "conn-1"
    assert action["connection"]["new_id"] == "conn-2"


def test_update_obligatory_filter_action_shape() -> None:
    action: UpdateObligatoryFilterAction = {
        "action": "update_obligatory_filter",
        "obligatory_filter": {
            "id": "filter-1",
            "field_guid": "field-1",
            "default_filters": [{"column": "field-1", "operation": "EQ", "values": ["test"]}],
        },
    }
    assert action["action"] == "update_obligatory_filter"
    assert action["obligatory_filter"]["id"] == "filter-1"
    assert action["obligatory_filter"]["field_guid"] == "field-1"


def test_delete_obligatory_filter_action_shape() -> None:
    action: DeleteObligatoryFilterAction = {
        "action": "delete_obligatory_filter",
        "obligatory_filter": {"id": "filter-1"},
    }
    assert action["action"] == "delete_obligatory_filter"
    assert action["obligatory_filter"]["id"] == "filter-1"


def test_update_setting_action_shape_bool() -> None:
    action: UpdateSettingAction = {
        "action": "update_setting",
        "setting": {
            "name": "load_preview_by_default",
            "value": True,
        },
    }
    assert action["action"] == "update_setting"
    assert action["setting"]["name"] == "load_preview_by_default"
    assert action["setting"]["value"] is True


def test_update_setting_action_shape_data_export() -> None:
    action: UpdateSettingAction = {
        "action": "update_setting",
        "setting": {
            "name": "data_export_forbidden",
            "value": False,
        },
    }
    assert action["action"] == "update_setting"
    assert action["setting"]["name"] == "data_export_forbidden"
    assert action["setting"]["value"] is False


def test_update_cache_invalidation_source_action_shape() -> None:
    action: UpdateCacheInvalidationSourceAction = {
        "action": "update_cache_invalidation_source",
        "cache_invalidation_source": {
            "mode": "sql",
            "sql": "SELECT MAX(updated_at) FROM orders",
            "filters": [],
        },
    }
    assert action["action"] == "update_cache_invalidation_source"
    assert action["cache_invalidation_source"]["mode"] == "sql"


def test_existing_actions_still_conform_to_union() -> None:
    update_description: DatasetUpdateAction = {
        "action": "update_description",
        "description": "test",
    }
    assert update_description["action"] == "update_description"

    add_field: DatasetUpdateAction = {
        "action": "add_field",
        "field": {
            "guid": "field-1",
            "title": "Field",
            "source": "col",
            "avatar_id": "avatar-1",
            "calc_mode": "direct",
            "type": "DIMENSION",
        },
    }
    assert add_field["action"] == "add_field"

    update_field: DatasetUpdateAction = {
        "action": "update_field",
        "field": {"guid": "field-1", "title": "Updated"},
    }
    assert update_field["action"] == "update_field"

    add_obligatory_filter: DatasetUpdateAction = {
        "action": "add_obligatory_filter",
        "obligatory_filter": {
            "id": "filter-1",
            "field_guid": "field-1",
            "default_filters": [],
        },
    }
    assert add_obligatory_filter["action"] == "add_obligatory_filter"

    add_avatar_relation: DatasetUpdateAction = {
        "action": "add_avatar_relation",
        "avatar_relation": {
            "id": "rel-1",
            "join_type": "inner",
            "conditions": [],
            "required": False,
            "managed_by": "user",
            "left_avatar_id": None,
            "right_avatar_id": None,
        },
    }
    assert add_avatar_relation["action"] == "add_avatar_relation"

    refresh_source: DatasetUpdateAction = {
        "action": "refresh_source",
        "source": {"id": "source-1", "force_update_fields": False},
    }
    assert refresh_source["action"] == "refresh_source"
