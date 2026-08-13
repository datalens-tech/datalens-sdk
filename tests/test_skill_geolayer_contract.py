from __future__ import annotations

import inspect
from pathlib import Path
import re
from typing import Any, cast, get_args

from datalens_sdk import GeoLayerFilter
from datalens_sdk._generated.builders.charts import WizardChartCreateFactory
from datalens_sdk._runtime.viz_specs import get_geo_layer_spec
from datalens_sdk.domain.chart_types import GeoLayerType, GradientPaletteId
from datalens_sdk.domain.entry_location import EntryLocation

SKILL_DIR = Path(__file__).parents[1] / "skills" / "datalens-sdk"


def _table(text: str, heading: str) -> tuple[list[str], list[list[str]]]:
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    rows = [
        [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))] for line in lines
    ]
    return rows[0], rows[2:]


def test_documented_geolayer_surface_matches_the_public_sdk() -> None:
    expected_parameters = (
        "layer_type",
        "geopoint",
        "polygon",
        "polyline",
        "grouping",
        "size",
        "color",
        "color_mode",
        "color_palette",
        "color_reversed",
        "filters",
        "tooltips",
        "labels",
        "sort_by",
        "sort_direction",
        "alpha",
        "name",
        "dataset",
    )
    factory = WizardChartCreateFactory(cast(Any, None))
    builder = factory.geolayer(name="Contract check", location=EntryLocation.path("/SkillChecks"))
    public_signature = inspect.signature(builder.add_layer)
    assert tuple(public_signature.parameters) == expected_parameters
    assert public_signature.parameters["layer_type"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert public_signature.parameters["layer_type"].default is inspect.Parameter.empty
    assert all(
        public_signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in expected_parameters[1:]
    )
    assert {name: public_signature.parameters[name].default for name in expected_parameters[1:]} == {
        "geopoint": None,
        "polygon": None,
        "polyline": None,
        "grouping": None,
        "size": None,
        "color": None,
        "color_mode": None,
        "color_palette": None,
        "color_reversed": None,
        "filters": (),
        "tooltips": (),
        "labels": (),
        "sort_by": None,
        "sort_direction": "asc",
        "alpha": 80,
        "name": None,
        "dataset": None,
    }

    filter_signature = inspect.signature(GeoLayerFilter)
    assert tuple(filter_signature.parameters) == ("field", "operation", "values")
    assert filter_signature.parameters["field"].default is inspect.Parameter.empty
    assert filter_signature.parameters["operation"].default is inspect.Parameter.empty
    assert filter_signature.parameters["values"].default == ()

    geolayer_text = (SKILL_DIR / "references" / "wizard-charts" / "chart-geolayer.md").read_text()
    _, geolayer_rows = _table(geolayer_text, "Fluent operations")
    geolayer_signature = next(row[1] for row in geolayer_rows if row[0] == "`add_layer()`")
    canonical_signature = geolayer_signature.strip("`")
    documented_parameter_order = tuple(re.findall(r"(?:^|, )([a-z_]+)(?:\s*:|\s*=)", canonical_signature))
    assert documented_parameter_order == expected_parameters
    assert "Sequence[GeoLayerFilter]" in canonical_signature

    index_text = (SKILL_DIR / "references" / "wizard-charts" / "_index.md").read_text()
    _, index_rows = _table(index_text, "Full fluent-operation matrix")
    layer_matrix_cell = next(row[1] for row in index_rows if row[0] == "`add_layer()`")
    index_geolayer_summary = layer_matrix_cell.split("<br>`geolayer`: ", 1)[1]
    assert index_geolayer_summary == (
        "`layer_type: GeoLayerType, *, ...` — "
        "[full signature and layer capabilities](chart-geolayer.md#fluent-operations)"
    )

    common_text = (SKILL_DIR / "references" / "wizard-charts" / "common-operations.md").read_text()
    _, common_rows = _table(common_text, "Fluent Operation Catalog")
    common_geolayer_row = next(row for row in common_rows if row[0].startswith("`.add_layer(layer_type: GeoLayerType"))
    assert common_geolayer_row == [
        "`.add_layer(layer_type: GeoLayerType, *, ...)`",
        "C",
        "Geolayer only; see the [full signature and layer capabilities](chart-geolayer.md#fluent-operations).",
    ]
    assert "[canonical geolayer contract](chart-geolayer.md)" in common_text

    public_palettes = set(get_args(GradientPaletteId))
    for palette in public_palettes:
        assert f'`"{palette}"`' in common_text

    _, color_rows = _table(common_text, "Color and Shape Encodings")
    three_point_row = next(row for row in color_rows if row[0] == '`"3-point"`')
    documented_three_point = set(re.findall(r'`"([^"]+)"`', three_point_row[1]))
    assert documented_three_point == {
        "orange-gray-blue",
        "pink-gray-green",
        "red-orange-green",
    }

    placeholders_header, placeholders_rows = _table(geolayer_text, "Placeholders")
    assert placeholders_header == [
        "Layer type",
        "Required public argument",
        "Geometry field group",
        "Supported optional field inputs",
    ]
    documented_capabilities = {
        row[0].strip("`"): {
            "geometry_argument": row[1].strip("`").removesuffix("="),
            "geometry_group": row[2].strip("`"),
            "optional_inputs": set(re.findall(r"`([^`]+)`", row[3])),
        }
        for row in placeholders_rows
    }
    assert set(documented_capabilities) == set(get_args(GeoLayerType))

    for layer_type, documented in documented_capabilities.items():
        layer_spec = get_geo_layer_spec(layer_type)
        viz = cast(dict[str, object], layer_spec["viz"])
        placeholders = cast(dict[str, dict[str, object]], layer_spec["placeholders"])
        placeholder_inputs = cast(dict[str, str], layer_spec["placeholder_inputs"])
        required_groups = [
            placeholder_id
            for placeholder_id, placeholder in placeholders.items()
            if placeholder.get("required") is True
        ]
        assert len(required_groups) == 1
        geometry_group = required_groups[0]

        expected_optional_inputs: set[str] = set()
        if "size" in placeholder_inputs.values():
            expected_optional_inputs.add("size")
        if "grouping" in placeholder_inputs.values():
            expected_optional_inputs.add("grouping")
        for capability, public_input in (
            ("allowColors", "color"),
            ("allowLayerFilters", "filters"),
            ("allowTooltips", "tooltips"),
            ("allowLabels", "labels"),
        ):
            if viz.get(capability) is True:
                expected_optional_inputs.add(public_input)
        if viz.get("allowSort") is True:
            expected_optional_inputs.add("sort_by")

        assert documented == {
            "geometry_argument": placeholder_inputs[geometry_group],
            "geometry_group": geometry_group,
            "optional_inputs": expected_optional_inputs,
        }
