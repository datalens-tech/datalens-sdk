"""Wire codec of state parameter values, exercised through :class:`DashboardStateConverter`."""

from __future__ import annotations

import datetime
from typing import get_args

import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_control import encode_selector_default
from datalens_sdk.converter.dashboard_state import DashboardStateConverter
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDate

OPERATIONS: tuple[dl.ParamOperation, ...] = get_args(dl.ParamOperation)


def _decode(wire: str | list[str], param: str = "p") -> dl.StateValue:
    data = DashboardStateConverter.to_domain(
        {"w": {"params": {param: wire}}, "__meta__": {"queue": [{"id": "w"}], "version": 2}}
    )
    params = data.widgets["w"].params
    assert params is not None
    value = params[param]
    assert isinstance(value, dl.StateValue)
    return value


def _encode(value: dl.StateValue) -> object:
    data = dl.DashboardStateData(
        version=2, queue=(dl.StateQueueItem("w"),), widgets={"w": dl.StateWidget(params={value.param: value})}
    )
    payload = DashboardStateConverter.to_payload(data)
    widget = payload["w"]
    assert isinstance(widget, dict)
    return widget["params"][value.param]


def _value(
    *values: object, operation: dl.ParamOperation = "IN", multiple: bool = True, inherits: bool = False
) -> dl.StateValue:
    return dl.StateValue("p", operation, tuple(values), multiple=multiple, inherits_operation=inherits)  # type: ignore[arg-type]


def test_param_operation_is_a_flat_tuple_of_24_strings() -> None:
    assert len(OPERATIONS) == 24
    assert len(set(OPERATIONS)) == 24
    assert {"IN", "NIN", "BETWEEN", "ISNULL", "LENLTE", "IENDSWITH"} <= set(OPERATIONS)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_explicit_operation_round_trips(operation: dl.ParamOperation) -> None:
    values = () if operation in ("ISNULL", "ISNOTNULL") else ("Moscow", "Paris")

    wire = _encode(_value(*values, operation=operation))
    decoded = _decode(wire)  # type: ignore[arg-type]

    assert decoded.operation == operation
    assert decoded.values == values
    assert not decoded.inherits_operation
    assert decoded.raw == tuple(wire)  # type: ignore[arg-type]


def test_value_without_prefix_inherits_the_selector_operation() -> None:
    assert _encode(_value("a", inherits=True)) == ["a"]
    decoded = _decode("a")
    assert (decoded.operation, decoded.inherits_operation, decoded.multiple) == ("IN", True, False)


def test_empty_values_are_not_prefixed() -> None:
    assert _encode(_value("", "EU", operation="NE")) == ["", "__ne_EU"]


def test_absolute_interval_round_trips() -> None:
    raw = "__interval_2026-01-01T00:00:00.000Z_2026-01-31T23:59:59.999Z"

    decoded = _decode(raw)

    assert (decoded.operation, decoded.inherits_operation) == ("BETWEEN", False)
    assert decoded.values == (DateInterval("2026-01-01T00:00:00.000Z", "2026-01-31T23:59:59.999Z"),)
    assert _encode(_value(*decoded.values, operation="BETWEEN", multiple=False, inherits=True)) == raw


def test_relative_interval_uses_the_ui_rounding_format() -> None:
    raw = "__interval___relative_-7d_sd___relative_+0d_ed"
    interval = DateInterval(RelativeDate("-7d", cast="s", unit="d"), RelativeDate("+0d", cast="e", unit="d"))

    assert _decode(raw).values == (interval,)
    assert _encode(_value(interval, operation="BETWEEN", multiple=False, inherits=True)) == raw


def test_between_prefix_wraps_an_interval() -> None:
    decoded = _decode("__between___interval_2024-01-01___relative_-0d")

    assert decoded.operation == "BETWEEN"
    assert decoded.values == (DateInterval("2024-01-01", RelativeDate("-0d")),)


def test_interval_encoding_accepts_dates_and_exclusive_end() -> None:
    interval = DateInterval(datetime.date(2026, 1, 1), datetime.date(2026, 1, 2), inclusive_end=False)

    assert (
        _encode(_value(interval, operation="BETWEEN", multiple=False, inherits=True))
        == "__interval_2026-01-01T00:00:00.000Z_2026-01-02T00:00:00.000Z"
    )


def test_prefixed_relative_date_round_trips() -> None:
    value = _value(RelativeDate("-7d", cast="s", unit="d"), operation="GTE", multiple=False)

    assert _encode(value) == "__gte___relative_-7d_sd"
    assert _decode("__gte___relative_-7d_sd").values == (RelativeDate("-7d", cast="s", unit="d"),)


@pytest.mark.parametrize(
    ("raw", "operation", "inherits"),
    [
        ("__foo_bar", "IN", False),
        ("__isnull", "IN", True),
        ("__ne_", "IN", False),
        ("__relative_-7d_sd", "IN", False),
        ("__interval_broken", "BETWEEN", False),
        ("plain_value", "IN", True),
    ],
)
def test_unrecognized_prefixes_follow_the_ui_fallback(raw: str, operation: str, inherits: bool) -> None:
    decoded = _decode(raw)

    assert (decoded.operation, decoded.inherits_operation) == (operation, inherits)


@pytest.mark.parametrize("raw", ["__isnull_", "__ISNULL_"])
def test_isnull_has_no_values(raw: str) -> None:
    decoded = _decode(raw)

    assert (decoded.operation, decoded.values) == ("ISNULL", ())


def test_stored_raw_is_written_back_unchanged() -> None:
    value = dl.StateValue("p", "IN", (), multiple=True, inherits_operation=True, raw=("__weird_x", "y"))

    assert _encode(value) == ["__weird_x", "y"]


def test_action_params_expose_field_guid() -> None:
    action = _decode(["x"], param="_ap_9f3e1a")

    assert action.is_action_param
    assert action.field_guid == "9f3e1a"
    assert _decode(["x"], param="region").field_guid is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"offset": "7x"}, "offset must look like"),
        ({"offset": "-7d", "cast": "s"}, "set together"),
        ({"offset": "-7d", "cast": "x", "unit": "d"}, "cast must be"),
        ({"offset": "-7d", "cast": "s", "unit": "day"}, "unit must be one of"),
    ],
)
def test_relative_date_validation(kwargs: dict[str, str], match: str) -> None:
    with pytest.raises(dl.DataLensValidationError, match=match):
        RelativeDate(**kwargs)  # type: ignore[arg-type]


def test_relative_date_normalizes_sign() -> None:
    assert RelativeDate("7d").offset == "+7d"


def test_selector_defaults_encode_relative_date_edges_and_exclusive_end() -> None:
    interval = DateInterval("2024-01-01", RelativeDate("-0d", cast="e", unit="d"))
    exclusive = DateInterval("2024-01-01", "2024-01-31", inclusive_end=False)

    assert (
        encode_selector_default(interval, field_type="genericdatetime", operation=None)
        == "__interval_2024-01-01T00:00:00.000Z___relative_-0d_ed"
    )
    assert (
        encode_selector_default(exclusive, field_type="genericdatetime", operation=None)
        == "__interval_2024-01-01T00:00:00.000Z_2024-01-31T00:00:00.000Z"
    )
    assert encode_selector_default(exclusive, field_type="date", operation=None) == "__interval_2024-01-01_2024-01-31"


def test_date_interval_rejects_non_boolean_inclusive_end() -> None:
    with pytest.raises(dl.DataLensValidationError, match="inclusive_end"):
        DateInterval("2024-01-01", "2024-01-02", inclusive_end="yes")  # type: ignore[arg-type]
