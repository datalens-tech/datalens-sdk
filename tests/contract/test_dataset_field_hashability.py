from __future__ import annotations

from datalens_sdk.domain.fields import DatasetField, field_from_mapping


def test_dataset_field_is_hashable() -> None:
    # frozen dataclass with a Mapping field is normally unhashable; compare=False
    # on `raw` restores hashability so DatasetField can be used as a dict key.
    df = DatasetField(guid="g1", title="t1", name="t1", calc_mode="direct")
    # Must not raise.
    assert hash(df) is not None


def test_dataset_field_usable_as_dict_key() -> None:
    df = field_from_mapping(
        {"guid": "g1", "title": "t1", "name": "t1", "calc_mode": "direct", "data_type": "string"},
        dataset_id="ds1",
    )
    overrides: dict[DatasetField, str] = {df: "#4DA2F1"}
    assert overrides[df] == "#4DA2F1"


def test_fields_built_from_same_mapping_with_different_raw_are_equal_and_hash_equal() -> None:
    # Regression: two DatasetField objects built from the same identity-bearing
    # mapping but with different `raw` blobs (e.g. one carries an extra unknown
    # key) must compare equal and hash equally — equality is by identity fields,
    # not by the raw blob.
    base_mapping = {"guid": "g1", "title": "t1", "name": "t1", "calc_mode": "direct"}

    mapping_with_extra: dict[str, object] = dict(base_mapping)
    mapping_with_extra["__unknown_future_wire_key__"] = {"nested": [1, 2, 3]}

    a = field_from_mapping(base_mapping, dataset_id="ds1")
    b = field_from_mapping(mapping_with_extra, dataset_id="ds1")

    # raw blobs differ (b carries the extra unknown key)
    assert a.raw != b.raw

    # but the fields themselves are equal and hash equally
    assert a == b
    assert hash(a) == hash(b)

    # and they collapse to the same entry in a dict keyed by DatasetField
    keyed: dict[DatasetField, str] = {a: "x"}
    keyed[b] = "y"
    assert keyed[a] == "y"
    assert len(keyed) == 1


def test_dataset_field_with_list_default_value_is_hashable() -> None:
    # D6: backend can send default_value as a list; field must stay hashable so
    # color_by_measure_name(colors_map={field: ...}) does not raise.
    df = field_from_mapping(
        {
            "guid": "g1",
            "title": "t1",
            "name": "t1",
            "calc_mode": "direct",
            "default_value": [1, 2, 3],
        }
    )
    assert hash(df) is not None
    overrides: dict[DatasetField, str] = {df: "#4DA2F1"}
    assert overrides[df] == "#4DA2F1"
    # original shape stays available via raw
    assert df.raw["default_value"] == [1, 2, 3]


def test_dataset_field_with_dict_default_value_is_hashable() -> None:
    # D6: date-interval default_value arrives as {"from": ..., "to": ...}; the
    # auto-__hash__ on DatasetField must not blow up on a dict.
    df = field_from_mapping(
        {
            "guid": "g1",
            "title": "t1",
            "name": "t1",
            "calc_mode": "direct",
            "default_value": {"from": "2025-01-01", "to": "2025-12-31"},
        }
    )
    assert hash(df) is not None
    overrides: dict[DatasetField, str] = {df: "#4DA2F1"}
    assert overrides[df] == "#4DA2F1"
    assert df.raw["default_value"] == {"from": "2025-01-01", "to": "2025-12-31"}


def test_dataset_field_with_dict_default_value_is_deterministic_across_key_orders() -> None:
    # D6: the dict→sorted-tuple coercion is deterministic — two fields built
    # from mappings that only differ in dict iteration order hash equally and
    # collapse to one dict entry.
    a = field_from_mapping(
        {
            "guid": "g1",
            "title": "t1",
            "name": "t1",
            "calc_mode": "direct",
            "default_value": {"from": "2025-01-01", "to": "2025-12-31"},
        }
    )
    b = field_from_mapping(
        {
            "guid": "g1",
            "title": "t1",
            "name": "t1",
            "calc_mode": "direct",
            "default_value": {"to": "2025-12-31", "from": "2025-01-01"},
        }
    )
    assert a == b
    assert hash(a) == hash(b)
    keyed: dict[DatasetField, str] = {a: "x"}
    keyed[b] = "y"
    assert len(keyed) == 1
    assert keyed[a] == "y"
