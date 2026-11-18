from __future__ import annotations

import datetime
from typing import get_args

import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dashboard_control import encode_selector_default
from datalens_sdk.domain.dashboard_types import DateInterval, RelativeDate, RelativeDateInterval
from datalens_sdk.domain.param_values import (
    ParamOperation,
    StateValue,
    decode_param_value,
    encode_param_value,
)

OPERATIONS: tuple[ParamOperation, ...] = get_args(ParamOperation)


def test_param_operation_is_a_flat_tuple_of_24_strings() -> None:
    assert len(OPERATIONS) == 24
    assert len(set(OPERATIONS)) == 24
    assert all(isinstance(operation, str) for operation in OPERATIONS)
    assert {"IN", "NIN", "BETWEEN", "ISNULL", "LENLTE", "IENDSWITH"} <= set(OPERATIONS)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_operation_round_trips(operation: ParamOperation) -> None:
    values = () if operation in ("ISNULL", "ISNOTNULL") else ("Moscow", "Paris")

    raw = encode_param_value(values, operation, multiselect=True, is_range=False)
    decoded = decode_param_value("city", raw)

    assert decoded.operation == operation
    assert decoded.values == values
    assert decoded.raw == tuple(raw)


@pytest.mark.parametrize(
    ("operation", "expected"),
    [("IN", ["a"]), (None, ["a"]), ("EQ", ["__eq_a"]), ("ISNULL", ["__isnull_"]), ("NIN", ["__nin_a"])],
)
def test_prefix_is_written_only_for_non_default_operations(
    operation: ParamOperation | None, expected: list[str]
) -> None:
    values = () if operation == "ISNULL" else ("a",)

    assert encode_param_value(values, operation, multiselect=True, is_range=False) == expected


def test_single_value_source_gets_a_string() -> None:
    assert encode_param_value("a", "GT", multiselect=False, is_range=False) == "__gt_a"


def test_absolute_interval_round_trips() -> None:
    raw = "__interval_2026-01-01T00:00:00.000Z_2026-01-31T23:59:59.999Z"

    decoded = decode_param_value("dt", raw)

    assert decoded.operation == "BETWEEN"
    assert decoded.values == (DateInterval("2026-01-01T00:00:00.000Z", "2026-01-31T23:59:59.999Z"),)
    assert encode_param_value(decoded.values, "BETWEEN", multiselect=False, is_range=True) == raw


def test_relative_interval_round_trips() -> None:
    raw = "__interval___relative_-7d_s_day___relative_+0d_e_day"

    decoded = decode_param_value("dt", raw)

    interval = DateInterval(RelativeDate("-7d", cast="s", unit="day"), RelativeDate("+0d", cast="e", unit="day"))
    assert decoded.values == (interval,)
    assert encode_param_value(interval, None, multiselect=False, is_range=True) == raw


def test_mixed_interval_and_between_prefix_decode() -> None:
    decoded = decode_param_value("dt", "__between___interval_2024-01-01___relative_-0d")

    assert decoded.operation == "BETWEEN"
    assert decoded.values == (DateInterval("2024-01-01", RelativeDate("-0d")),)


def test_interval_encoding_accepts_dates_and_legacy_relative_interval() -> None:
    interval = DateInterval(datetime.date(2026, 1, 1), datetime.date(2026, 1, 2), inclusive_end=False)

    assert (
        encode_param_value(interval, None, multiselect=False, is_range=True)
        == "__interval_2026-01-01T00:00:00.000Z_2026-01-02T00:00:00.000Z"
    )
    assert (
        encode_param_value(RelativeDateInterval("-1M", "-0d"), None, multiselect=False, is_range=True)
        == "__interval___relative_-1M___relative_-0d"
    )


def test_single_relative_date_round_trips() -> None:
    decoded = decode_param_value("dt", "__relative_-7d_s_day", "GTE")

    assert decoded.operation == "GTE"
    assert decoded.values == (RelativeDate("-7d", cast="s", unit="day"),)
    assert encode_param_value(decoded.values[0], None, multiselect=False, is_range=False) == "__relative_-7d_s_day"


@pytest.mark.parametrize("raw", ["__isnull", "__isnull_", "__ISNULL_"])
def test_isnull_has_no_values(raw: str) -> None:
    decoded = decode_param_value("city", raw)

    assert decoded.operation == "ISNULL"
    assert decoded.values == ()


@pytest.mark.parametrize(
    ("raw", "default", "operation"),
    [(["a", "b"], None, "IN"), ("a", "EQ", "EQ"), ("__interval_2026-01-01_2026-01-02", None, "BETWEEN")],
)
def test_values_without_prefix_use_default_operation(
    raw: str | list[str], default: ParamOperation | None, operation: str
) -> None:
    assert decode_param_value("p", raw, default).operation == operation


@pytest.mark.parametrize("raw", ["__foo_bar", "__interval_broken", "__relative_-7x", "plain_value"])
def test_unknown_prefixes_stay_plain_strings(raw: str) -> None:
    decoded = decode_param_value("p", raw)

    assert decoded.operation == "IN"
    assert decoded.values == (raw,)


def test_action_params_expose_field_guid() -> None:
    action = decode_param_value("_ap_9f3e1a", ["x"])
    dataset = decode_param_value("9f3e1a", ["x"], dataset_field=True)
    manual = decode_param_value("region", ["x"])

    assert action.is_action_param
    assert action.field_guid == "9f3e1a"
    assert not dataset.is_action_param
    assert dataset.field_guid == "9f3e1a"
    assert manual.field_guid is None


def test_state_value_is_frozen() -> None:
    value = StateValue(param="p", operation="IN", values=("a",), raw="a")

    with pytest.raises(AttributeError):
        value.param = "q"  # type: ignore[misc]


@pytest.mark.parametrize("values", ["2026-01-01", ("a", "b"), ()])
def test_range_requires_one_interval(values: object) -> None:
    with pytest.raises(dl.DataLensValidationError, match="range selector"):
        encode_param_value(values, None, multiselect=False, is_range=True)


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(dl.DataLensValidationError, match="Unknown parameter operation"):
        encode_param_value("a", "NEQ", multiselect=False, is_range=False)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("values", "match"),
    [(("a", "b"), "exactly one value"), ((1,), "State values must be"), (object(), "value or a sequence")],
)
def test_invalid_values_are_rejected(values: object, match: str) -> None:
    with pytest.raises(dl.DataLensValidationError, match=match):
        encode_param_value(values, None, multiselect=False, is_range=False)


def test_valueless_operation_rejects_values() -> None:
    with pytest.raises(dl.DataLensValidationError, match="takes no values"):
        encode_param_value("a", "ISNULL", multiselect=False, is_range=False)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"offset": "7x"}, "offset must look like"),
        ({"offset": "-7d", "cast": "s"}, "set together"),
        ({"offset": "-7d", "cast": "x", "unit": "day"}, "cast must be"),
        ({"offset": "-7d", "cast": "s", "unit": "d-1"}, "unit must be"),
    ],
)
def test_relative_date_validation(kwargs: dict[str, str], match: str) -> None:
    with pytest.raises(dl.DataLensValidationError, match=match):
        RelativeDate(**kwargs)  # type: ignore[arg-type]


def test_relative_date_normalizes_sign_and_supports_time_units() -> None:
    assert RelativeDate("7d").offset == "+7d"
    assert RelativeDate("-30ms").to_wire() == "__relative_-30ms"


def test_selector_defaults_encode_relative_date_edges_and_exclusive_end() -> None:
    interval = DateInterval("2024-01-01", RelativeDate("-0d", cast="e", unit="day"))
    exclusive = DateInterval("2024-01-01", "2024-01-31", inclusive_end=False)

    assert (
        encode_selector_default(interval, field_type="genericdatetime", operation=None)
        == "__interval_2024-01-01T00:00:00.000Z___relative_-0d_e_day"
    )
    assert (
        encode_selector_default(exclusive, field_type="genericdatetime", operation=None)
        == "__interval_2024-01-01T00:00:00.000Z_2024-01-31T00:00:00.000Z"
    )
    assert encode_selector_default(exclusive, field_type="date", operation=None) == "__interval_2024-01-01_2024-01-31"


def test_date_interval_rejects_non_boolean_inclusive_end() -> None:
    with pytest.raises(dl.DataLensValidationError, match="inclusive_end"):
        DateInterval("2024-01-01", "2024-01-02", inclusive_end="yes")  # type: ignore[arg-type]
