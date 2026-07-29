"""RMW engine contract (_apply_update): verbatim no-op over every fixture,
deep-copy isolation, settings/globalParams/description patch semantics (D3.1).

The verbatim invariant is the load-bearing guarantee of the update epic: a
full-document save must never destroy unknown item types (neuro_widget),
enableActionParams or any future fields the read DTO ignores.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.converter.dashboard_apply import _apply_update
from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_types import REMOVE_PARAM, DateInterval
from datalens_sdk.errors import DatalensValidationError


def _tabs(data: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", data["tabs"])


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value)


_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"
_FIXTURE_PATHS = sorted(_FIXTURES_DIR.glob("*.json"))


def _load_entry(path: Path) -> dict[str, object]:
    entry: object = json.loads(path.read_text())
    assert isinstance(entry, dict)
    return cast(dict[str, object], entry)


def _dashboard_from(entry: dict[str, object]) -> Dashboard:
    return Dashboard(
        id=cast(str, entry["entryId"]),
        installation="yacloud",
        data=cast(dict[str, object], entry["data"]),
        raw=entry,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


@pytest.mark.parametrize("path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_empty_update_applies_to_verbatim_data(path: Path) -> None:
    entry = _load_entry(path)
    spec = _dashboard_from(entry).update.to_spec()
    applied = _apply_update(spec)
    assert _canonical(applied) == _canonical(entry["data"])
    # named load-bearing keys survive untouched
    data = cast(dict[str, object], entry["data"])
    assert applied["salt"] == data["salt"]
    assert applied["schemeVersion"] == data["schemeVersion"]
    assert applied["counter"] == data["counter"]


def test_applied_result_is_isolated_from_snapshot() -> None:
    entry = _load_entry(_FIXTURES_DIR / "simple.json")
    update = _dashboard_from(entry).update
    spec = update.to_spec()
    applied = _apply_update(spec)
    cast(list[object], applied["tabs"]).clear()
    # neither the spec snapshot nor a fresh application see the mutation
    assert cast(list[object], spec.data["tabs"])
    assert cast(list[object], _apply_update(spec)["tabs"])


def test_settings_patch_preserves_unknown_keys_and_sets_values() -> None:
    entry = _load_entry(_FIXTURES_DIR / "simple.json")
    data = cast(dict[str, object], entry["data"])
    settings = cast(dict[str, object], data["settings"])
    settings["someFutureFlag"] = "keep-me"
    update = _dashboard_from(entry).update.settings(hide_tabs=True, max_concurrent_requests=3)
    applied_settings = cast(dict[str, object], _apply_update(update.to_spec())["settings"])
    assert applied_settings["hideTabs"] is True
    assert applied_settings["maxConcurrentRequests"] == 3
    assert applied_settings["someFutureFlag"] == "keep-me"


def test_settings_clear_resets_to_canon() -> None:
    entry = _load_entry(_FIXTURES_DIR / "simple.json")
    data = cast(dict[str, object], entry["data"])
    settings = cast(dict[str, object], data["settings"])
    settings["autoupdateInterval"] = 120
    settings["loadPriority"] = "charts"
    settings["hideTabs"] = True
    update = _dashboard_from(entry).update.settings(autoupdate_interval=None, load_priority=None, hide_tabs=None)
    applied_settings = cast(dict[str, object], _apply_update(update.to_spec())["settings"])
    assert applied_settings["autoupdateInterval"] is None  # canonical null
    assert "loadPriority" not in applied_settings  # no canonical value -> removed
    assert applied_settings["hideTabs"] is False  # canonical default


def test_global_params_merge_and_remove() -> None:
    entry = _load_entry(_FIXTURES_DIR / "simple.json")
    data = cast(dict[str, object], entry["data"])
    settings = cast(dict[str, object], data["settings"])
    settings["globalParams"] = {"keep": ["1"], "stale": ["x"], "override": ["old"]}
    update = _dashboard_from(entry).update.global_params(
        {"override": "new", "added": ["a", "b"], "stale": REMOVE_PARAM}
    )
    applied = cast(dict[str, object], _apply_update(update.to_spec())["settings"])
    assert applied["globalParams"] == {"keep": ["1"], "override": ["new"], "added": ["a", "b"]}


def _leaf_paths(value: object, prefix: str = "$") -> dict[str, object]:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            out.update(_leaf_paths(item, f"{prefix}.{key}"))
        return out or {prefix: {}}
    if isinstance(value, list):
        out = {}
        for index, item in enumerate(value):
            out.update(_leaf_paths(item, f"{prefix}[{index}]"))
        return out or {prefix: []}
    return {prefix: value}


@pytest.mark.parametrize("path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_single_point_edit_changes_only_the_addressed_path(path: Path) -> None:
    entry = _load_entry(path)
    data = cast(dict[str, object], entry["data"])
    tabs = cast("list[dict[str, object]]", data["tabs"])
    first_tab_id = cast(str, tabs[0]["id"])

    update = _dashboard_from(entry).update.hide_tab(first_tab_id)
    applied = _apply_update(update.to_spec())

    before = _leaf_paths(data)
    after = _leaf_paths(applied)
    changed_keys = {key for key in before.keys() | after.keys() if before.get(key, ...) != after.get(key, ...)}
    assert changed_keys == {"$.tabs[0].hidden"}
    assert after["$.tabs[0].hidden"] is True


def test_description_tri_state() -> None:
    entry = _load_entry(_FIXTURES_DIR / "simple.json")
    data = cast(dict[str, object], entry["data"])
    data["accessDescription"] = "old access"
    data["supportDescription"] = "old support"
    data["description"] = "old description"

    # not called -> verbatim
    untouched = _apply_update(_dashboard_from(entry).update.to_spec())
    assert untouched["accessDescription"] == "old access"

    # "" -> cleared via key removal (live-verified true clearing form, P0.1)
    cleared = _apply_update(
        _dashboard_from(entry).update.access_description("").support_description("").description("").to_spec()
    )
    assert "accessDescription" not in cleared
    assert "supportDescription" not in cleared
    assert "description" not in cleared

    # value -> set
    updated = _apply_update(_dashboard_from(entry).update.access_description("new access").to_spec())
    assert updated["accessDescription"] == "new access"
    assert updated["supportDescription"] == "old support"


# -- dangling-alias auto-cleanup on removals (epic D4, stage 17) --------------------


def _alias_stand() -> Dashboard:
    """Two manual selectors + a widget; aliases pair their fields."""
    tabs = [
        {
            "id": "tab_1",
            "title": "T",
            "items": [
                {
                    "id": "c_a",
                    "type": "control",
                    "namespace": "default",
                    "defaults": {"field_a": ""},
                    "data": {
                        "title": "A",
                        "sourceType": "manual",
                        "source": {"elementType": "input", "fieldName": "field_a"},
                    },
                },
                {
                    "id": "c_b",
                    "type": "control",
                    "namespace": "default",
                    "defaults": {"field_b": ""},
                    "data": {
                        "title": "B",
                        "sourceType": "manual",
                        "source": {"elementType": "input", "fieldName": "field_b"},
                    },
                },
                {
                    "id": "w_1",
                    "type": "widget",
                    "namespace": "default",
                    "data": {
                        "hideTitle": False,
                        "tabs": [
                            {
                                "id": "wt_1",
                                "title": "W",
                                "chartId": "ch-1",
                                "isDefault": True,
                                "params": {"field_a": []},
                            },
                        ],
                    },
                },
            ],
            "layout": [
                {"i": "c_a", "x": 0, "y": 0, "w": 12, "h": 2},
                {"i": "c_b", "x": 12, "y": 0, "w": 12, "h": 2},
                {"i": "w_1", "x": 0, "y": 2, "w": 36, "h": 10},
            ],
            "connections": [],
            "aliases": {"default": [["field_a", "field_b"], ["field_b", "field_x", "field_a"]]},
        }
    ]
    data: dict[str, object] = {"counter": 1, "salt": "s", "schemeVersion": 8, "settings": {}, "tabs": tabs}
    return Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "dash-1", "data": data})


def test_remove_item_drops_aliases_of_the_sole_user() -> None:
    update = _alias_stand().update
    update.remove_item("c_b")  # field_b loses its only user
    data = _apply_update(update.to_spec())
    default = _as_dict(_tabs(data)[0]["aliases"])["default"]
    # [a, b] loses b and shrinks below 2 -> removed; [b, x, a] loses b but
    # keeps x (never a parameter here — the removal did not touch it) and a
    assert default == [["field_x", "field_a"]]


def test_remove_item_keeps_alias_fields_the_removal_did_not_touch() -> None:
    update = _alias_stand().update
    update.remove_item("c_a")  # field_a is STILL used by widget params
    data = _apply_update(update.to_spec())
    default = _as_dict(_tabs(data)[0]["aliases"])["default"]
    # no field lost its last user: field_a survives through the widget,
    # field_x was never a parameter on this tab -> aliases stay verbatim
    assert default == [["field_a", "field_b"], ["field_b", "field_x", "field_a"]]


def test_three_field_alias_group_loses_one_and_survives() -> None:
    update = _alias_stand().update
    update.set_chart_params(item_id="w_1", params={"field_x": "v"})
    data = _apply_update(update.to_spec())
    # no removal happened yet; now remove nothing — aliases untouched by pure param op
    default = _as_dict(_tabs(data)[0]["aliases"])["default"]
    assert default == [["field_a", "field_b"], ["field_b", "field_x", "field_a"]]

    update2 = Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "d", "data": data}).update
    update2.remove_item("c_b")
    result = _apply_update(update2.to_spec())
    default2 = _as_dict(_tabs(result)[0]["aliases"])["default"]
    # field_b gone; [b, x, a] keeps x (widget param) and a -> survives as a pair
    assert default2 == [["field_x", "field_a"]]


def _second_tab_with_dangling_alias() -> dict[str, object]:
    return {
        "id": "tab_2",
        "title": "Other",
        "items": [
            {
                "id": "c_z",
                "type": "control",
                "namespace": "default",
                "defaults": {"field_z": ""},
                "data": {
                    "title": "Z",
                    "sourceType": "manual",
                    "source": {"elementType": "input", "fieldName": "field_z"},
                },
            }
        ],
        "layout": [{"i": "c_z", "x": 0, "y": 0, "w": 12, "h": 2}],
        "connections": [],
        "aliases": {"default": [["field_z", "field_gone"]]},
    }


def test_alias_cleanup_is_scoped_to_tabs_the_removal_touched() -> None:
    dashboard = _alias_stand()
    tabs = _tabs(cast("dict[str, object]", dashboard.data))
    tabs.append(_second_tab_with_dangling_alias())

    update = dashboard.update
    update.remove_item("c_b")  # touches tab_1 only
    data = _apply_update(update.to_spec())
    # tab_2's PRE-EXISTING dangling alias stays byte-verbatim (raw-RMW):
    # detecting it is the validate_dashboard_refs recipe's job
    assert _canonical(_tabs(data)[1]) == _canonical(_second_tab_with_dangling_alias())


def test_remove_selector_alias_cleanup_is_scoped_too() -> None:
    dashboard = _alias_stand()
    tabs = _tabs(cast("dict[str, object]", dashboard.data))
    tabs.append(_second_tab_with_dangling_alias())
    # turn c_b into a singleton group so remove_selector exercises the member path
    group_item: dict[str, object] = {
        "id": "g_1",
        "type": "group_control",
        "namespace": "default",
        "data": {
            "group": [
                {
                    "id": "m_b",
                    "title": "B2",
                    "namespace": "default",
                    "sourceType": "manual",
                    "placementMode": "auto",
                    "width": "",
                    "source": {"elementType": "input", "fieldName": "field_m"},
                    "defaults": {"field_m": ""},
                },
                {
                    "id": "m_c",
                    "title": "C2",
                    "namespace": "default",
                    "sourceType": "manual",
                    "placementMode": "auto",
                    "width": "",
                    "source": {"elementType": "input", "fieldName": "field_c"},
                    "defaults": {"field_c": ""},
                },
            ],
            "autoHeight": False,
            "buttonApply": False,
            "buttonReset": False,
            "updateControlsOnChange": True,
            "showGroupName": False,
        },
    }
    first_tab = _tabs(cast("dict[str, object]", dashboard.data))[0]
    cast("list[object]", first_tab["items"]).append(group_item)
    cast("list[object]", first_tab["layout"]).append({"i": "g_1", "x": 0, "y": 12, "w": 24, "h": 2})

    update = dashboard.update
    update.remove_selector(item_id="m_c")
    data = _apply_update(update.to_spec())
    assert _canonical(_tabs(data)[1]) == _canonical(_second_tab_with_dangling_alias())


def test_cross_dataset_alias_survives_unrelated_removals() -> None:
    # the live P021 shape: the alias pairs a selector field with a field of
    # the widget's OTHER dataset; the latter is never a parameter key in the
    # document, so it must survive removals that do not touch the selector
    dashboard = _alias_stand()
    first_tab = _tabs(cast("dict[str, object]", dashboard.data))[0]
    aliases = _as_dict(first_tab["aliases"])
    aliases["default"] = [["field_a", "other_ds_guid"]]

    update = dashboard.update
    update.remove_item("c_b")  # unrelated to the alias
    data = _apply_update(update.to_spec())
    assert _as_dict(_tabs(data)[0]["aliases"])["default"] == [["field_a", "other_ds_guid"]]

    # removing the selector side kills the alias: the last parameter user is gone
    update2 = Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "d", "data": data}).update
    update2.set_chart_params(item_id="w_1", params={}, merge=False)  # field_a leaves widget params first
    update2.remove_item("c_a")
    result = _apply_update(update2.to_spec())
    assert _as_dict(_tabs(result)[0]["aliases"])["default"] == []


# -- update_selector encoding parity with create (review fixes) ---------------------


def _group_manual_dashboard() -> Dashboard:
    return _dashboard_from(_load_entry(_FIXTURES_DIR / "group_control_manual.json"))


def _find_member(data: dict[str, object], member_id: str) -> dict[str, object]:
    for tab in _tabs(data):
        for item in cast("list[dict[str, object]]", tab.get("items", [])):
            for member in cast("list[dict[str, object]]", _as_dict(item.get("data", {})).get("group", []) or []):
                if member.get("id") == member_id:
                    return member
    raise AssertionError(f"member {member_id!r} not found")


def test_update_selector_operation_only_reencodes_the_defaults_prefix() -> None:
    update = _group_manual_dashboard().update
    update.update_selector(item_id="om", operation="NIN")
    data = _apply_update(update.to_spec())
    member = _find_member(data, "om")
    assert _as_dict(member["source"])["operation"] == "NIN"
    # the __<op>_ prefix follows the declared operation instead of going stale
    assert member["defaults"] == {"field_0004": ["__nin_Value 5"]}


def test_update_selector_select_scalar_default_becomes_lists() -> None:
    update = _group_manual_dashboard().update
    update.update_selector(item_id="om", default_value="Title 6")
    data = _apply_update(update.to_spec())
    member = _find_member(data, "om")
    assert _as_dict(member["source"])["defaultValue"] == ["Title 6"]
    assert member["defaults"] == {"field_0004": ["__eq_Title 6"]}  # operation EQ from the source


def test_update_selector_rejects_element_incompatible_defaults_on_apply() -> None:
    bool_update = _group_manual_dashboard().update
    bool_update.update_selector(item_id="no", default_value=True)  # "no" is an input element
    with pytest.raises(DatalensValidationError, match="checkbox"):
        _apply_update(bool_update.to_spec())

    interval_update = _group_manual_dashboard().update
    interval_update.update_selector(item_id="no", default_value=DateInterval("2024-01-01", "2024-02-01"))
    with pytest.raises(DatalensValidationError, match="element='date'"):
        _apply_update(interval_update.to_spec())


def test_remove_member_shrinking_shared_group_to_one_moves_impact_into_member() -> None:
    dashboard = _alias_stand()
    shared_group: dict[str, object] = {
        "id": "g_sh",
        "type": "group_control",
        "namespace": "default",
        "data": {
            "group": [
                {
                    "id": "m_1",
                    "title": "M1",
                    "namespace": "default",
                    "sourceType": "manual",
                    "placementMode": "auto",
                    "width": "",
                    "source": {"elementType": "input", "fieldName": "p_1"},
                    "defaults": {"p_1": ""},
                },
                {
                    "id": "m_2",
                    "title": "M2",
                    "namespace": "default",
                    "sourceType": "manual",
                    "placementMode": "auto",
                    "width": "",
                    "source": {"elementType": "input", "fieldName": "p_2"},
                    "defaults": {"p_2": ""},
                },
            ],
            "autoHeight": False,
            "buttonApply": False,
            "buttonReset": False,
            "updateControlsOnChange": True,
            "showGroupName": False,
            "impactType": "allTabs",
        },
    }
    first_tab = _tabs(cast("dict[str, object]", dashboard.data))[0]
    cast("list[object]", first_tab["items"]).append(shared_group)
    cast("list[object]", first_tab["layout"]).append({"i": "g_sh", "x": 0, "y": 14, "w": 24, "h": 2})

    update = dashboard.update
    update.remove_selector(item_id="m_2")
    data = _apply_update(update.to_spec())
    item = next(it for it in cast("list[dict[str, object]]", _tabs(data)[0]["items"]) if it.get("id") == "g_sh")
    item_data = _as_dict(item["data"])
    group = cast("list[dict[str, object]]", item_data["group"])
    assert len(group) == 1
    # single-member quirk: the impact fields moved into data.group[0]
    assert "impactType" not in item_data
    assert group[0]["impactType"] == "allTabs"
