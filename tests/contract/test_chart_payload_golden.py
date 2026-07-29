from __future__ import annotations

import copy
import json
import os
from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._runtime.viz_specs import (
    VIZ_SPECS,
    factory_method_name,
    get_placeholder_id,
    get_viz_spec,
)
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.entry_location import EntryLocation

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "viz_specs")

_GOLDEN_VIZ_IDS = frozenset(VIZ_SPECS) - {"geolayer"}

_ALIAS_TO_BUILDER: dict[str, dict[str, str]] = {
    "metric": {"measures": "y"},
    "donut": {"dimensions": "x", "measures": "y"},
    "funnel": {"dimensions": "x", "measures": "y"},
    "pie": {"dimensions": "x", "measures": "y"},
    "flatTable": {"flat-table-columns": "columns"},
    "pivotTable": {"pivot-table-columns": "columns", "measures": "y", "rows": "rows"},
    "treemap": {"dimensions": "x", "measures": "y"},
}


def _load_fixture(viz_id: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES_DIR, f"{viz_id}.json"), encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


def _dataset_with_fields(guids: list[str]) -> Dataset:
    schema: list[dict[str, object]] = []
    for i, guid in enumerate(guids):
        is_measure = i % 2 == 1
        schema.append(
            {
                "guid": guid,
                "title": f"field_{guid}",
                "type": "MEASURE" if is_measure else "DIMENSION",
                "data_type": "float" if is_measure else "string",
                "calc_mode": "direct",
                "aggregation": "sum" if is_measure else "",
            }
        )
    return Dataset(id="ds1", name="sales", location=EntryLocation.path("/"), result_schema=tuple(schema))


def _strip_items(placeholder: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in placeholder.items() if k != "items"}


@pytest.mark.parametrize("viz_id", sorted(_GOLDEN_VIZ_IDS))
def test_from_domain_create_enriches_placeholders_from_spec(viz_id: str) -> None:
    spec = get_viz_spec(viz_id)
    spec_placeholders = cast(dict[str, Any], spec.get("placeholders", {}))
    spec_viz = cast(dict[str, Any], spec.get("viz", {}))

    alias_map = _ALIAS_TO_BUILDER.get(viz_id, {})
    calls: list[tuple[str, list[str]]] = []
    for guid_counter, actual_id in enumerate(spec_placeholders):
        # Color and Shapes are semantic encodings, not raw placeholder setters.
        # This test checks placeholder metadata and can leave their items empty.
        if actual_id in {"colors", "shapes"}:
            continue
        builder_method = alias_map.get(actual_id, actual_id)
        calls.append((builder_method, [f"g{guid_counter}"]))

    all_guids = [g for _, guids in calls for g in guids]
    dataset = _dataset_with_fields(all_guids)

    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method_name(viz_id))(name="T", location=EntryLocation.path("/F"))
    builder.dataset(dataset)
    for method, guids in calls:
        getattr(builder, method)(guids)

    dto = WizardChartConverter.from_domain_create(builder.to_spec())
    produced_viz = cast(dict[str, Any], dto.to_payload()["data"])["visualization"]
    produced_by_id = {p["id"]: p for p in produced_viz["placeholders"]}

    for actual_id, ph_spec in spec_placeholders.items():
        assert actual_id in produced_by_id, f"{viz_id}: missing placeholder {actual_id}"
        expected = copy.deepcopy(cast(dict[str, Any], ph_spec))
        expected["id"] = actual_id
        assert _strip_items(produced_by_id[actual_id]) == _strip_items(expected), (
            f"{viz_id}: placeholder {actual_id} shape diverges from VIZ_SPECS"
        )

    assert produced_viz["id"] == spec_viz.get("id")
    assert produced_viz["type"] == spec_viz.get("type")


@pytest.mark.parametrize("viz_id", sorted(_GOLDEN_VIZ_IDS))
def test_from_domain_create_placeholder_ids_superset_of_golden(viz_id: str) -> None:
    fixture = _load_fixture(viz_id)
    golden_placeholder_ids = {p["id"] for p in (fixture["visualization"].get("placeholders") or [])}

    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method_name(viz_id))(name="T", location=EntryLocation.path("/F"))
    dto = WizardChartConverter.from_domain_create(builder.to_spec())
    produced_viz = cast(dict[str, Any], dto.to_payload()["data"])["visualization"]
    produced_ids = {p["id"] for p in produced_viz["placeholders"]}

    missing = golden_placeholder_ids - produced_ids
    assert not missing, f"{viz_id}: produced payload missing golden placeholders {sorted(missing)}"
    assert produced_viz["id"] == fixture["visualization"]["id"]


@pytest.mark.parametrize("viz_id", sorted(_GOLDEN_VIZ_IDS))
def test_from_domain_create_emits_minimal_wizard_defaults(viz_id: str) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method_name(viz_id))(name="T", location=EntryLocation.path("/F"))
    dto = WizardChartConverter.from_domain_create(builder.to_spec())
    data = cast(dict[str, Any], dto.to_payload()["data"])
    for key in ("colors", "colorsConfig", "filters", "labels", "sort", "tooltips", "updates", "version"):
        assert key in data, f"{viz_id}: missing default {key}"
    assert data["type"] == "datalens"


def test_alias_maps_builder_names_to_spec_placeholder_ids() -> None:
    assert get_placeholder_id("pie", "x") == "dimensions"
    assert get_placeholder_id("pie", "y") == "measures"
    assert get_placeholder_id("metric", "y") == "measures"
    assert get_placeholder_id("flatTable", "columns") == "flat-table-columns"
    assert get_placeholder_id("pivotTable", "columns") == "pivot-table-columns"
    assert get_placeholder_id("line", "x") == "x"
