from __future__ import annotations

from typing import Any, cast

import pytest

from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._generated.dto import WIZARD_VISUALIZATION_STRUCTURE
from datalens_sdk._runtime.viz_specs import (
    factory_method_name,
)
from datalens_sdk._runtime.wizard_semantics import WIZARD_VISUALIZATION_SEMANTICS, resolve_slot_name
from datalens_sdk.converter.wizard_chart import WizardChartConverter
from datalens_sdk.domain.entry_location import EntryLocation

_NON_LAYERED_VIZ_IDS = frozenset(
    visualization_type
    for visualization_type, structure in WIZARD_VISUALIZATION_STRUCTURE.items()
    if not structure["layers"]
)

_ALIAS_TO_BUILDER: dict[str, dict[str, str]] = {
    "metric": {"measures": "y"},
    "donut": {"dimensions": "x", "measures": "y"},
    "funnel": {"dimensions": "x", "measures": "y"},
    "pie": {"dimensions": "x", "measures": "y"},
    "flatTable": {"flat-table-columns": "columns"},
    "pivotTable": {"pivot-table-columns": "columns", "rows": "rows"},
    "treemap": {"dimensions": "x", "measures": "y"},
}


@pytest.mark.parametrize("viz_id", sorted(_NON_LAYERED_VIZ_IDS))
def test_from_domain_create_emits_all_named_slots_from_semantics(viz_id: str) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method_name(viz_id))(name="T", location=EntryLocation.path("/F"))
    dto = WizardChartConverter.from_domain_create(builder.to_spec())
    produced_viz = cast(dict[str, Any], dto.to_payload()["data"])["visualization"]
    structure = WIZARD_VISUALIZATION_STRUCTURE[viz_id]
    assert produced_viz["type"] == viz_id
    assert set(produced_viz) == {"type", *structure["slots"]}
    assert all(produced_viz[slot_name]["items"] == [] for slot_name in structure["slots"])


@pytest.mark.parametrize("viz_id", sorted(_NON_LAYERED_VIZ_IDS))
def test_from_domain_create_named_slot_ids_exactly_match_semantics(viz_id: str) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method_name(viz_id))(name="T", location=EntryLocation.path("/F"))
    dto = WizardChartConverter.from_domain_create(builder.to_spec())
    produced_viz = cast(dict[str, Any], dto.to_payload()["data"])["visualization"]
    assert set(produced_viz) - {"type", "chartSettings"} == set(WIZARD_VISUALIZATION_STRUCTURE[viz_id]["slots"])


@pytest.mark.parametrize("viz_id", sorted(_NON_LAYERED_VIZ_IDS))
def test_from_domain_create_emits_minimal_wizard_defaults(viz_id: str) -> None:
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = getattr(factory, factory_method_name(viz_id))(name="T", location=EntryLocation.path("/F"))
    dto = WizardChartConverter.from_domain_create(builder.to_spec())
    data = cast(dict[str, Any], dto.to_payload()["data"])
    assert set(data) == {"sources", "visualization"}
    assert data["sources"] == {"datasetsIds": []}
    assert data["visualization"]["type"] == viz_id


def test_builder_names_map_to_canonical_slot_ids() -> None:
    assert resolve_slot_name("pie", "x") == "dimensions"
    assert resolve_slot_name("pie", "y") == "measures"
    assert resolve_slot_name("metric", "y") == "measures"
    assert resolve_slot_name("flatTable", "columns") == "columns"
    assert WIZARD_VISUALIZATION_SEMANTICS["pivotTable"]["slot_aliases"] == {}
    assert resolve_slot_name("pivotTable", "measures") == "measures"
    assert resolve_slot_name("line", "x") == "x"
