"""DashboardUpdate builder contract: snapshot isolation, shadow index,
tab resolution, tri-state scalar setters, repeatable to_spec (D3.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from datalens_sdk.domain.dashboard import Dashboard
from datalens_sdk.domain.dashboard_types import REMOVE_PARAM, UNSET
from datalens_sdk.domain.dashboard_update import DashboardUpdate
from datalens_sdk.domain.specs.dashboard import GlobalParamsOp
from datalens_sdk.errors import DataLensValidationError

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dashboards"
_FIXTURE_PATHS = sorted(_FIXTURES_DIR.glob("*.json"))


def _load_entry(path: Path) -> dict[str, object]:
    entry: object = json.loads(path.read_text())
    assert isinstance(entry, dict)
    return cast(dict[str, object], entry)


def _dashboard_from(entry: dict[str, object]) -> Dashboard:
    data = entry["data"]
    assert isinstance(data, dict)
    return Dashboard(
        id=cast(str, entry["entryId"]),
        installation="yacloud",
        data=cast(dict[str, object], data),
        raw=entry,
    )


def _dashboard(stem: str = "simple") -> Dashboard:
    return _dashboard_from(_load_entry(_FIXTURES_DIR / f"{stem}.json"))


def _synthetic(tabs: list[dict[str, object]]) -> Dashboard:
    data: dict[str, object] = {"counter": 1, "salt": "s", "settings": {}, "tabs": tabs}
    return Dashboard(id="dash-1", installation="yacloud", data=data, raw={"entryId": "dash-1", "data": data})


def test_dashboard_update_property_returns_fresh_builder() -> None:
    dashboard = _dashboard()
    first = dashboard.update
    second = dashboard.update
    assert isinstance(first, DashboardUpdate)
    assert first is not second


def test_dashboard_update_without_id_raises() -> None:
    dashboard = Dashboard(id=None, installation="yacloud")
    with pytest.raises(DataLensValidationError, match="without an id"):
        _ = dashboard.update


def test_update_snapshot_is_isolated_from_source_mutation() -> None:
    tabs: list[dict[str, object]] = [{"id": "tab_1", "title": "One", "items": [], "layout": []}]
    dashboard = _synthetic(tabs)
    update = dashboard.update
    tabs[0]["title"] = "MUTATED"
    spec = update.to_spec()
    tabs_snapshot = cast(list[dict[str, object]], spec.data["tabs"])
    assert tabs_snapshot[0]["title"] == "One"


def test_update_snapshot_captures_meta_and_annotation_verbatim() -> None:
    # this fixture carries a live annotation object; `simple` has an explicit null
    entry = _load_entry(_FIXTURES_DIR / "global_items_shared_selectors.json")
    spec = _dashboard_from(entry).update.to_spec()
    assert spec.meta == entry.get("meta")
    assert spec.annotation == entry.get("annotation")
    assert spec.annotation is not None

    null_annotation = _load_entry(_FIXTURES_DIR / "simple.json")
    assert null_annotation["annotation"] is None
    assert _dashboard_from(null_annotation).update.to_spec().annotation is None


def test_meta_and_annotation_snapshots_are_deep_copies() -> None:
    entry: dict[str, object] = {
        "entryId": "dash-1",
        "meta": {"nested": {"flag": True}},
        "annotation": {"description": "orig", "extra": {"keep": 1}},
        "data": {"tabs": []},
    }
    dashboard = _dashboard_from(entry)
    update = dashboard.update
    # nested mutation of the SOURCE after the builder was created
    cast("dict[str, object]", cast("dict[str, object]", entry["meta"])["nested"])["flag"] = False
    cast("dict[str, object]", cast("dict[str, object]", entry["annotation"])["extra"])["keep"] = 999
    spec = update.to_spec()
    assert spec.meta == {"nested": {"flag": True}}
    assert spec.annotation == {"description": "orig", "extra": {"keep": 1}}
    # and the spec itself is an independent snapshot too
    cast("dict[str, object]", cast("dict[str, object]", spec.meta)["nested"])["flag"] = "mutated"
    cast("list[object]", spec.data["tabs"]).append({"id": "hacked"})
    fresh = update.to_spec()
    assert fresh.meta == {"nested": {"flag": True}}
    assert fresh.data == {"tabs": []}


def test_to_spec_is_repeatable_and_unaffected_by_later_calls() -> None:
    update = _dashboard().update
    first = update.to_spec()
    second = update.to_spec()
    assert first == second
    update.description("changed later")
    assert first.description is None


# Tab-reference resolution (id-then-title, ambiguous/unknown fail-loud) is
# covered through the public tab operations in test_dashboard_update ops tests
# (D3.2); the resolver itself is private.


def test_description_setters_require_strings() -> None:
    update = _dashboard().update
    with pytest.raises(DataLensValidationError, match="description must be a string"):
        update.description(cast(str, None))
    with pytest.raises(DataLensValidationError, match="access_description"):
        update.access_description(cast(str, 42))
    with pytest.raises(DataLensValidationError, match="support_description"):
        update.support_description(cast(str, 42))


def test_settings_tri_state_recorded_in_spec() -> None:
    update = _dashboard().update.settings(hide_tabs=True, autoupdate_interval=None)
    spec = update.to_spec()
    assert spec.settings.hide_tabs is True
    assert spec.settings.autoupdate_interval is None
    assert spec.settings_cleared == frozenset({"autoupdate_interval"})
    # untouched fields are neither set nor cleared
    assert spec.settings.silent_loading is None
    assert "silent_loading" not in spec.settings_cleared


def test_settings_set_after_clear_wins() -> None:
    update = _dashboard().update.settings(hide_tabs=None).settings(hide_tabs=False)
    spec = update.to_spec()
    assert spec.settings.hide_tabs is False
    assert "hide_tabs" not in spec.settings_cleared


def test_settings_validation_mirrors_create() -> None:
    update = _dashboard().update
    with pytest.raises(DataLensValidationError, match="hide_tabs must be a bool"):
        update.settings(hide_tabs=cast(bool, "yes"))
    with pytest.raises(DataLensValidationError, match="autoupdate_interval must be >= 30"):
        update.settings(autoupdate_interval=5)
    with pytest.raises(DataLensValidationError, match="max_concurrent_requests must be >= 1"):
        update.settings(max_concurrent_requests=0)
    with pytest.raises(DataLensValidationError, match="Unknown load_priority"):
        update.settings(load_priority="everything")  # type: ignore[arg-type]
    assert update.to_spec().settings_cleared == frozenset()


def test_global_params_records_op_and_snapshots_input() -> None:
    update = _dashboard().update
    params: dict[str, object] = {"region": "north", "cities": ["a", "b"], "stale": REMOVE_PARAM}
    update.global_params(params)
    params["region"] = "MUTATED"
    (op,) = update.ops
    assert isinstance(op, GlobalParamsOp)
    assert op.changes["region"] == ("north",)
    assert op.changes["cities"] == ("a", "b")
    assert op.changes["stale"] is REMOVE_PARAM


def test_global_params_rejects_bad_keys_and_values() -> None:
    update = _dashboard().update
    with pytest.raises(DataLensValidationError, match="non-empty strings"):
        update.global_params({"": "x"})
    with pytest.raises(DataLensValidationError, match="string or a sequence of strings"):
        update.global_params({"n": 5})
    assert update.ops == ()


def test_unset_sentinel_reprs() -> None:
    assert repr(UNSET) == "UNSET"
    assert repr(REMOVE_PARAM) == "REMOVE_PARAM"
