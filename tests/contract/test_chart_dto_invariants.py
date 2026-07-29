from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pydantic import ValidationError
import pytest

from datalens_sdk._generated.builders.charts import (
    EnterpriseEditorChartCreateFactory,
    YacloudEditorChartCreateFactory,
)
from datalens_sdk._generated.dto import (
    INSTALLATION_EDITOR_NODE_TYPES,
    WizardChartCreateDTO,
    WizardChartReadDTO,
)
from datalens_sdk.domain.ports import ChartOperations

_SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
_EDITOR_FACTORY_METHOD_BY_WIRE_TYPE = {
    "advanced-chart_node": "advanced_chart",
    "control_node": "selector",
    "d3_node": "gravity_charts",
    "markdown_node": "markdown",
    "table_node": "table",
}


def _load_editor_discriminator(spec_path: Path) -> frozenset[str]:
    data = json.loads(spec_path.read_text())
    schemas = data["components"]["schemas"]
    if "CreateEditorChartArgs" not in schemas:
        return frozenset()
    entry = schemas["CreateEditorChartArgs"]["properties"]["entry"]
    mapping = entry["allOf"][0]["discriminator"]["mapping"]
    return frozenset(mapping.keys())


def test_yacloud_editor_node_types_match_discriminator() -> None:
    yacloud_spec = _SPEC_DIR / "yacloud.json"
    discriminator_types = _load_editor_discriminator(yacloud_spec)
    generated_types = INSTALLATION_EDITOR_NODE_TYPES["yacloud"]
    assert generated_types == discriminator_types, (
        f"yacloud generated editor node types {sorted(generated_types)} "
        f"do not match spec discriminator types {sorted(discriminator_types)}"
    )


def test_wizard_chart_read_dto_captures_raw() -> None:
    raw_data = {
        "entryId": "abc123",
        "template": "datalens",
        "data": {"key": "value"},
        "extra_future_field": "should_be_ignored",
    }
    dto = WizardChartReadDTO.model_validate(raw_data)
    assert dto.entry_id == "abc123"
    assert dto.template == "datalens"
    assert dto.raw == raw_data
    assert "extra_future_field" in dto.raw


def test_wizard_chart_read_dto_extra_ignore() -> None:
    dto = WizardChartReadDTO.model_validate({"unknown_field": "x", "entryId": "id1"})
    assert dto.entry_id == "id1"
    assert "unknown_field" in dto.raw


def test_wizard_chart_create_dto_requires_template_and_data() -> None:
    with pytest.raises(ValidationError):
        WizardChartCreateDTO.model_validate({"data": {}})

    with pytest.raises(ValidationError):
        WizardChartCreateDTO.model_validate({"template": "datalens"})

    dto = WizardChartCreateDTO.model_validate({"template": "datalens", "data": {"viz": "line"}})
    assert dto.template == "datalens"
    assert dto.data == {"viz": "line"}


def test_enterprise_editor_node_types_match_discriminator() -> None:
    enterprise_spec = _SPEC_DIR / "enterprise.json"
    discriminator_types = _load_editor_discriminator(enterprise_spec)
    generated_types = INSTALLATION_EDITOR_NODE_TYPES["enterprise"]
    assert generated_types == discriminator_types, (
        f"enterprise generated editor node types {sorted(generated_types)} "
        f"do not match enterprise spec discriminator types {sorted(discriminator_types)}"
    )


def test_public_editor_factory_methods_match_public_types() -> None:
    for installation, factory_cls in (
        ("yacloud", YacloudEditorChartCreateFactory),
        ("enterprise", EnterpriseEditorChartCreateFactory),
    ):
        factory = factory_cls(cast(ChartOperations, None))
        public_types = INSTALLATION_EDITOR_NODE_TYPES[installation]
        factory_method_names = {
            name for name in dir(factory) if not name.startswith("_") and callable(getattr(factory, name))
        }
        type_to_method = {_EDITOR_FACTORY_METHOD_BY_WIRE_TYPE[wire_type] for wire_type in public_types}
        missing = type_to_method - factory_method_names
        assert not missing, f"{factory_cls.__name__} missing methods for types: {sorted(missing)}"
        extra = factory_method_names - type_to_method
        assert not extra, (
            f"{factory_cls.__name__} exposes methods for types not in "
            f"INSTALLATION_EDITOR_NODE_TYPES[{installation!r}]: {sorted(extra)}"
        )
