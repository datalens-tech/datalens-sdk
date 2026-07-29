"""Behavioral tests for selector value types and write-specs (epic D4, stage 2).

Covers the typed date-interval helpers (the wire ``__interval_``/``__relative_``
strings are a converter concern — these classes only validate and normalize),
the server-verified operation vocabulary (probe P016), and the frozen selector
spec dataclasses.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import get_args

import pytest

from datalens_sdk import DateInterval, RelativeDateInterval
from datalens_sdk.domain.dashboard_types import ImpactType, SelectorOperation
from datalens_sdk.domain.dashboard_update_support import _SPEC_ITEM_TYPES
from datalens_sdk.domain.specs.dashboard import (
    DatasetSelectorSource,
    ExternalControlItem,
    GroupControlItem,
    ManualSelectorSource,
    SelectorMemberSpec,
)
from datalens_sdk.errors import DatalensValidationError

# -- DateInterval -----------------------------------------------------------------


def test_date_interval_accepts_iso_dates() -> None:
    interval = DateInterval("2024-01-01", "2024-12-31")
    assert (interval.start, interval.end) == ("2024-01-01", "2024-12-31")


def test_date_interval_accepts_iso_datetime_with_time() -> None:
    interval = DateInterval("2018-01-01T00:00:00.000Z", "2021-12-31T23:59:59.999Z")
    assert interval.start == "2018-01-01T00:00:00.000Z"


def test_date_interval_normalizes_date_objects_to_iso() -> None:
    interval = DateInterval(datetime.date(2024, 3, 1), datetime.datetime(2024, 3, 31, 23, 59, 59))
    assert interval.start == "2024-03-01"
    assert interval.end == "2024-03-31T23:59:59"


def test_date_interval_supports_hybrid_absolute_relative() -> None:
    interval = DateInterval("2024-01-01", "-0d")
    assert interval.end == "-0d"


@pytest.mark.parametrize("bad", ["", "yesterday", "2024-1-1", "-3X", "--1d"])
def test_date_interval_rejects_garbage_edges(bad: str) -> None:
    with pytest.raises(DatalensValidationError):
        DateInterval(bad, "2024-01-01")


def test_date_interval_normalizes_unsigned_offsets_to_signed() -> None:
    # the wire form is always signed; "7d" is accepted as "+7d"
    assert DateInterval("7d", "2024-01-01").start == "+7d"


# -- RelativeDateInterval ---------------------------------------------------------


def test_relative_interval_defaults_to_last_month() -> None:
    interval = RelativeDateInterval()
    assert (interval.start, interval.end) == ("-1M", "-0d")


@pytest.mark.parametrize("offset", ["-7d", "+0d", "-2w", "-1M", "-3Q", "+10y"])
def test_relative_interval_accepts_signed_offsets(offset: str) -> None:
    assert RelativeDateInterval(offset, "+0d").start == offset


@pytest.mark.parametrize("bad", ["2024-01-01", "-1x", "", "-d"])
def test_relative_interval_rejects_non_offsets(bad: str) -> None:
    with pytest.raises(DatalensValidationError):
        RelativeDateInterval(bad, "-0d")


def test_relative_interval_normalizes_unsigned_offsets_to_signed() -> None:
    assert RelativeDateInterval("1d", "0d") == RelativeDateInterval("+1d", "+0d")


def test_intervals_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DateInterval("2024-01-01", "2024-01-02").start = "2024-01-03"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        RelativeDateInterval().end = "-1d"  # type: ignore[misc]


# -- operation and impact vocabularies (probe P016) --------------------------------


def test_selector_operation_matches_server_list() -> None:
    codes = set(get_args(SelectorOperation))
    assert "NE" in codes
    assert "NEQ" not in codes
    assert len(codes) == 25


def test_impact_type_uses_selected_tabs_wire_value() -> None:
    # The server enum is allTabs|currentTab|selectedTabs|asGroup (createDashboard
    # 400 body); "onlyOnTabs" is not a valid wire token and is rejected.
    values = set(get_args(ImpactType))
    assert "selectedTabs" in values
    assert "onlyOnTabs" not in values


def test_selector_member_defaults_to_as_group_influence() -> None:
    assert _member().affects == "as_group"


# -- selector specs ---------------------------------------------------------------


def _member(**overrides: object) -> SelectorMemberSpec:
    defaults: dict[str, object] = {
        "id": "el_1",
        "title": "Категория",
        "source": DatasetSelectorSource(dataset_id="ds-1", field_guid="category_g71a", field_type="string"),
    }
    defaults.update(overrides)
    return SelectorMemberSpec(**defaults)  # type: ignore[arg-type]


def test_selector_specs_are_frozen() -> None:
    member = _member()
    with pytest.raises(dataclasses.FrozenInstanceError):
        member.title = "x"  # type: ignore[misc]
    group = GroupControlItem(id="g1", members=(member,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        group.auto_height = True  # type: ignore[misc]


def test_group_control_defaults_match_the_card_canon() -> None:
    group = GroupControlItem(id="g1", members=(_member(),))
    assert group.apply_button is False
    assert group.reset_button is False
    assert group.update_on_change is True
    assert group.show_group_name is False
    assert group.show_on_tabs == "current"


def test_selector_source_shapes() -> None:
    dataset = DatasetSelectorSource(dataset_id="ds-1", field_guid="g", field_type="date")
    manual = ManualSelectorSource(param_name="region", options=(("East", "East"),))
    # external selectors are their own standalone item spec: group members
    # only discriminate dataset|manual (server schema, P017)
    external = ExternalControlItem(id="c1", title="Ext", chart_id="ch-1")
    assert dataset.dataset_field_type == "DIMENSION"
    assert manual.element == "select"
    assert external.chart_id == "ch-1"


def test_group_control_registered_as_wire_item_type() -> None:
    assert _SPEC_ITEM_TYPES[GroupControlItem] == "group_control"
    assert _SPEC_ITEM_TYPES[ExternalControlItem] == "control"
