from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk._generated.builders.charts import QLChartCreateFactory
from datalens_sdk._runtime.chart_constants import is_ql_wire_type
from datalens_sdk._runtime.viz_specs import QL_VIZ_SPECS, factory_method_name, to_snake
from datalens_sdk.converter.ql_chart import QLChartConverter
from datalens_sdk.domain.connection import Connection
from datalens_sdk.domain.entry_location import EntryLocation
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.domain.ql_chart import QLChart, QLColumn, QLParam
from datalens_sdk.domain.specs.ql_chart import QLChartCreateSpec
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_QL_REFERENCE_DIR = Path(__file__).parent / "fixtures" / "reference_charts" / "ql"

# Each live reference chart, its wire entry type (``*_ql_node``), viz_id and
# placeholder ids (the exact QL placeholder set, mirroring QL_VIZ_SPECS).
# Coverage spans all 13 QL visualizations.
_QL_REFERENCE_CHARTS = {
    "3s1btw4bm5kom": {"wire_type": "d3_ql_node", "viz_id": "column", "placeholders": ("x", "y")},
    "4t2b4ovay396n": {"wire_type": "d3_ql_node", "viz_id": "area100p", "placeholders": ("x", "y")},
    "6v4dfzzem2fep": {"wire_type": "d3_ql_node", "viz_id": "pie", "placeholders": ("dimensions", "colors", "measures")},
    "az8z6uyjoz3qt": {"wire_type": "d3_ql_node", "viz_id": "bar", "placeholders": ("y", "x")},
    "b09if04n0iucu": {"wire_type": "d3_ql_node", "viz_id": "bar100p", "placeholders": ("y", "x")},
    "d2bkncoeml94w": {
        "wire_type": "d3_ql_node",
        "viz_id": "donut",
        "placeholders": ("dimensions", "colors", "measures"),
    },
    "fez420cyep644": {"wire_type": "d3_ql_node", "viz_id": "area", "placeholders": ("x", "y")},
    "h6eyoxeihu8c0": {"wire_type": "metric2_ql_node", "viz_id": "metric", "placeholders": ("measures", "colors")},
    "h6eyw78tblag0": {"wire_type": "d3_ql_node", "viz_id": "treemap", "placeholders": ("dimensions", "measures")},
    "h6f6f1v2h1h40": {"wire_type": "d3_ql_node", "viz_id": "scatter", "placeholders": ("x", "y", "points", "size")},
    "j8g0jgv2jec42": {"wire_type": "table_ql_node", "viz_id": "flatTable", "placeholders": ("flat-table-columns",)},
    "peneqc6d42t88": {"wire_type": "d3_ql_node", "viz_id": "column100p", "placeholders": ("x", "y")},
    "vks9wrtzto8ke": {"wire_type": "d3_ql_node", "viz_id": "line", "placeholders": ("x", "y", "y2")},
}


def _load_reference(chart_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_QL_REFERENCE_DIR / f"{chart_id}.json").read_text()))


def _reference_chart_data(chart_id: str) -> dict[str, Any]:
    return cast(dict[str, Any], _load_reference(chart_id)["data"])


class _FakeOps:
    """Minimal ChartOperations stand-in for unit tests."""

    installation = "yacloud"

    def create_wizard_chart(self, builder: object) -> object:
        raise NotImplementedError

    def get_wizard_chart(self, chart_id: str, workbook_id: str | None = None) -> object:
        raise NotImplementedError

    def update_wizard_chart(self, builder: object) -> object:
        raise NotImplementedError

    def delete_wizard_chart(self, chart_id: str) -> None:
        raise NotImplementedError

    def create_editor_chart(self, builder: object) -> object:
        raise NotImplementedError

    def get_editor_chart(self, entry_id: str, workbook_id: str | None = None) -> object:
        raise NotImplementedError

    def update_editor_chart(self, builder: object) -> object:
        raise NotImplementedError

    def delete_editor_chart(self, entry_id: str) -> None:
        raise NotImplementedError

    def create_ql_chart(self, builder: object) -> object:
        raise NotImplementedError

    def get_ql_chart(self, chart_id: str, workbook_id: str | None = None) -> object:
        raise NotImplementedError

    def update_ql_chart(self, builder: object) -> object:
        raise NotImplementedError

    def delete_ql_chart(self, chart_id: str) -> None:
        raise NotImplementedError


class RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: list(response) if isinstance(response, list) else [response] for path, response in routes.items()
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responses = self._routes.get(request.url.path)
        if not responses:
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        resp = responses.pop(0)
        resp.request = request
        return resp

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)


# ---------------------------------------------------------------------------
# 1. QLChartReadDTO: extra=ignore + raw capture
# ---------------------------------------------------------------------------


def test_ql_chart_read_dto_captures_raw() -> None:
    raw = {
        "entryId": "q1",
        "type": "d3_ql_node",
        "data": {"queryValue": "select 1", "type": "ql"},
        "future_field": "ignored",
    }
    dto = generated_dto.QLChartReadDTO.model_validate(raw)
    assert dto.entry_id == "q1"
    assert dto.type == "d3_ql_node"
    assert dto.raw == raw
    assert "future_field" in dto.raw


def test_ql_chart_read_dto_extra_ignore() -> None:
    dto = generated_dto.QLChartReadDTO.model_validate({"entryId": "x", "unknown": 42})
    assert dto.entry_id == "x"
    assert "unknown" in dto.raw


# ---------------------------------------------------------------------------
# 2. Round-trip fidelity + accessors on live reference charts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chart_id", sorted(_QL_REFERENCE_CHARTS))
def test_round_trip_preserves_structured_data(chart_id: str) -> None:
    """``data`` must round-trip unchanged through to_domain (opaque preservation)."""
    reference = _load_reference(chart_id)
    chart = QLChartConverter.to_domain(reference, installation="yacloud", operations=None)
    assert isinstance(chart, QLChart)
    assert chart.data == reference["data"]


@pytest.mark.parametrize("chart_id", sorted(_QL_REFERENCE_CHARTS))
def test_reference_wire_type_is_ql_node(chart_id: str) -> None:
    """Every live QL chart has a ``*_ql_node`` wire type (never the v1 ``ql_node``).

    The concrete type varies by visualization (``d3_ql_node``, ``table_ql_node``,
    ``metric2_ql_node``); routing matches on the ``_ql_node`` suffix.
    """
    meta = _QL_REFERENCE_CHARTS[chart_id]
    reference = _load_reference(chart_id)
    assert reference["type"] == meta["wire_type"]
    assert is_ql_wire_type(reference["type"])
    chart = QLChartConverter.to_domain(reference, installation="yacloud", operations=None)
    assert chart.wire_type == meta["wire_type"]
    assert chart.category == "ql"


@pytest.mark.parametrize("chart_id", sorted(_QL_REFERENCE_CHARTS))
def test_reference_data_scaffold_keys(chart_id: str) -> None:
    """Every live QL chart shares the stable ``data`` scaffold keys."""
    data = _reference_chart_data(chart_id)
    assert data["chartType"] == "sql"
    assert data["type"] == "ql"
    assert data["version"] == "7"
    assert isinstance(data["connection"], dict)
    assert data["queries"] == []
    for key in (
        "colors",
        "labels",
        "shapes",
        "tooltips",
        "colorsConfig",
        "shapesConfig",
        "extraSettings",
        "geopointsConfig",
    ):
        assert key in data
    assert data["order"] is None


@pytest.mark.parametrize("chart_id", sorted(_QL_REFERENCE_CHARTS))
def test_accessors_read_reference_chart(chart_id: str) -> None:
    """Read accessors return the expected values from the reference ``data``."""
    data = _reference_chart_data(chart_id)
    reference = _load_reference(chart_id)
    chart = QLChartConverter.to_domain(reference, installation="yacloud", operations=None)
    meta = _QL_REFERENCE_CHARTS[chart_id]

    assert chart.query_value == data["queryValue"]
    assert chart.connection == data["connection"]
    assert chart.params == data["params"]
    assert chart.visualization_id == meta["viz_id"]

    placeholders = data["visualization"]["placeholders"]
    if any(ph.get("items") for ph in placeholders):
        assert len(chart.fields) == sum(len(ph.get("items", [])) for ph in placeholders)
    else:
        assert len(chart.fields) == 0


# ---------------------------------------------------------------------------
# 3. from_domain_create: payload shape (structured data)
# ---------------------------------------------------------------------------


def test_from_domain_create_builds_structured_data() -> None:
    spec = QLChartCreateSpec(
        name="my chart",
        location=EntryLocation.path("/dir"),
        connection=Connection(id="c1", type="ch_over_yt"),
        query="SELECT 1",
        params=(QLParam.number("p", default="1"),),
    )
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    assert payload["template"] == "ql"
    data = cast(dict[str, object], payload["data"])
    assert data["chartType"] == "sql"
    assert data["type"] == "ql"
    assert data["version"] == "7"
    assert data["connection"] == {"entryId": "c1", "type": "ch_over_yt"}
    assert data["queryValue"] == "SELECT 1"
    assert data["params"] == [{"type": "number", "name": "p", "defaultValue": "1"}]
    assert data["queries"] == []
    assert data["order"] is None
    for key in ("colors", "labels", "shapes", "tooltips"):
        assert data[key] == []
    for key in ("colorsConfig", "shapesConfig", "extraSettings", "geopointsConfig"):
        assert data[key] == {}


def test_from_domain_create_omits_visualization_when_none() -> None:
    spec = QLChartCreateSpec(name="c", location=EntryLocation.path("/dir"))
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert "visualization" not in data


def test_from_domain_create_includes_visualization_blob() -> None:
    spec = QLChartCreateSpec(
        name="c",
        location=EntryLocation.path("/dir"),
        visualization={"id": "line", "type": "line", "placeholders": []},
    )
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["visualization"] == {"id": "line", "type": "line", "placeholders": []}


def test_from_domain_create_extra_data_merges_and_overrides() -> None:
    spec = QLChartCreateSpec(
        name="c",
        location=EntryLocation.path("/dir"),
        extra_data={"colors": [{"guid": "g1"}], "customKey": 7},
    )
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["colors"] == [{"guid": "g1"}]
    assert data["customKey"] == 7


def test_from_domain_create_passes_nonempty_description_to_annotation() -> None:
    spec = QLChartCreateSpec(name="c", location=EntryLocation.path("/dir"), description="QL description")
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    assert payload["annotation"] == {"description": "QL description"}


@pytest.mark.parametrize("description", [None, ""])
def test_from_domain_create_omits_annotation_without_description(description: str | None) -> None:
    spec = QLChartCreateSpec(name="c", location=EntryLocation.path("/dir"), description=description)
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    assert "annotation" not in payload


def test_from_domain_create_workbook_location() -> None:
    spec = QLChartCreateSpec(name="c", location=EntryLocation.workbook("wb-1"))
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    assert payload["workbookId"] == "wb-1"
    assert payload["name"] == "c"


# ---------------------------------------------------------------------------
# 4. visualization scaffold via builder.to_spec()
# ---------------------------------------------------------------------------


def _make_ql_builder(viz_id: str, ops: ChartOperations) -> Any:
    factory = QLChartCreateFactory(ops)
    return getattr(factory, factory_method_name(viz_id))(name="c", location=EntryLocation.path("/dir"))


@pytest.mark.parametrize("chart_id", sorted(_QL_REFERENCE_CHARTS))
def test_ql_scaffold_matches_reference_visualization_exactly(chart_id: str) -> None:
    meta = _QL_REFERENCE_CHARTS[chart_id]
    viz_id = cast(str, meta["viz_id"])
    ops = cast(ChartOperations, _FakeOps())
    builder = _make_ql_builder(viz_id, ops)
    spec = builder.to_spec()
    assert spec.visualization is not None

    actual = json.loads(json.dumps(spec.visualization))
    expected = json.loads(json.dumps(_reference_chart_data(chart_id)["visualization"]))
    for visualization in (actual, expected):
        for placeholder in visualization["placeholders"]:
            placeholder.pop("items", None)
    assert actual == expected


def test_ql_data_section_methods_land_in_top_level_data() -> None:
    """Top-level data decoration methods write into ``data`` arrays, not placeholders.

    Unlike wizard charts, QL charts store colors/labels/shapes/tooltips as
    top-level ``data`` keys. The 100p charts (and the cartesian family) must
    expose a typed ``.colors()`` that produces a constant-DIMENSION item in
    ``data.colors`` while leaving ``visualization.placeholders`` intact.
    """
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .column_100p(name="c", location=EntryLocation.path("/dir"))
        .x([QLColumn("dttm", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("category", cast="string")])
    )
    payload = QLChartConverter.from_domain_create(builder.to_spec()).to_payload()
    data = cast(dict[str, object], payload["data"])
    colors = cast(list[dict[str, object]], data["colors"])
    assert len(colors) == 1
    assert colors[0]["guid"] == "category"
    assert colors[0]["type"] == "DIMENSION"
    assert colors[0]["datasetId"] == "ql-mocked-dataset"
    assert colors[0]["calc_mode"] == "direct"
    placeholders = cast(list[dict[str, object]], cast(dict[str, object], data["visualization"])["placeholders"])
    assert {ph["id"] for ph in placeholders} == {"x", "y"}


def test_ql_data_section_str_columns_default_to_string_cast() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .bar_100p(name="c", location=EntryLocation.path("/dir"))
        .y([QLColumn("dttm", cast="genericdatetime")])
        .x([QLColumn("events", cast="integer")])
        .colors(["category"])
    )
    spec = builder.to_spec()
    assert spec.visualization is not None
    data = cast(dict[str, object], QLChartConverter.from_domain_create(spec).to_payload()["data"])
    colors = cast(list[dict[str, object]], data["colors"])
    assert colors[0]["cast"] == "string"
    assert colors[0]["data_type"] == "string"


def test_ql_data_section_replaces_previous_values() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .area_100p(name="c", location=EntryLocation.path("/dir"))
        .x([QLColumn("dttm", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .colors([QLColumn("first", cast="string")])
        .colors([QLColumn("second", cast="string")])
    )
    spec = builder.to_spec()
    assert spec.visualization is not None
    data = cast(dict[str, object], QLChartConverter.from_domain_create(spec).to_payload()["data"])
    colors = cast(list[dict[str, object]], data["colors"])
    assert len(colors) == 1
    assert colors[0]["guid"] == "second"


def test_ql_tooltips_section_available_when_no_placeholder() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .indicator(name="c", location=EntryLocation.path("/dir"))
        .measures([QLColumn("value", cast="integer")])
        .colors([QLColumn("dim", cast="string")])
        .tooltips([QLColumn("tip", cast="string")])
    )
    spec = builder.to_spec()
    assert spec.visualization is not None
    data = cast(dict[str, object], QLChartConverter.from_domain_create(spec).to_payload()["data"])
    assert cast(list[dict[str, object]], data["tooltips"])[0]["guid"] == "tip"
    placeholders = cast(list[dict[str, object]], cast(dict[str, object], data["visualization"])["placeholders"])
    assert "colors" in {ph["id"] for ph in placeholders}
    assert data["colors"] == []


def test_ql_scaffold_visualization_lands_in_payload() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = QLChartCreateFactory(ops).line(name="c", location=EntryLocation.path("/dir"))
    payload = QLChartConverter.from_domain_create(builder.to_spec()).to_payload()
    data = cast(dict[str, object], payload["data"])
    visualization = cast(dict[str, object], data["visualization"])
    assert visualization["id"] == "line"
    placeholders = cast(list[dict[str, object]], visualization["placeholders"])
    assert {ph["id"] for ph in placeholders} == {"x", "y", "y2"}


def test_ql_placeholder_methods_build_renderable_items() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .line(name="c", location=EntryLocation.path("/dir"))
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
    )
    spec = builder.to_spec()
    assert spec.visualization is not None
    placeholders = cast(list[dict[str, object]], spec.visualization["placeholders"])
    x_ph = next(ph for ph in placeholders if ph["id"] == "x")
    item = cast(list[dict[str, object]], x_ph["items"])[0]
    assert item["guid"] == "ts"
    assert item["title"] == "ts"
    assert item["cast"] == "genericdatetime"
    assert item["data_type"] == "genericdatetime"
    assert item["type"] == "DIMENSION"
    assert item["datasetId"] == "ql-mocked-dataset"
    assert item["calc_mode"] == "direct"
    assert item["inspectHidden"] is True
    assert item["formulaHidden"] is True
    assert item["noEdit"] is True


def test_ql_column_str_shortcut_defaults_to_string_cast() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .flat_table(name="c", location=EntryLocation.path("/dir"))
        .flat_table_columns(["col_a"])
    )
    spec = builder.to_spec()
    assert spec.visualization is not None
    placeholders = cast(list[dict[str, object]], spec.visualization["placeholders"])
    item = cast(list[dict[str, object]], placeholders[0]["items"])[0]
    assert item["guid"] == "col_a"
    assert item["cast"] == "string"


def test_ql_column_invalid_cast_raises() -> None:
    with pytest.raises(DataLensValidationError, match="cast must be one of"):
        QLColumn("x", cast="bool")  # type: ignore[arg-type]


def test_ql_build_without_required_placeholder_raises() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = QLChartCreateFactory(ops).line(name="c", location=EntryLocation.path("/dir"))
    with pytest.raises(DataLensValidationError, match="requires placeholder"):
        builder.build()


def test_ql_build_with_required_placeholder_succeeds() -> None:
    ops = cast(ChartOperations, _FakeOps())
    builder = (
        QLChartCreateFactory(ops)
        .line(name="c", location=EntryLocation.path("/dir"))
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
    )
    spec = builder.to_spec()
    assert spec.visualization is not None
    placeholders = cast(list[dict[str, object]], spec.visualization["placeholders"])
    required = [ph for ph in placeholders if ph.get("required")]
    assert all(len(cast(list[object], ph["items"])) >= 1 for ph in required)


def test_ql_visualization_blob_overrides_scaffold() -> None:
    ops = cast(ChartOperations, _FakeOps())
    custom_blob = {"id": "custom", "type": "custom", "placeholders": []}
    builder = QLChartCreateFactory(ops).line(name="c", location=EntryLocation.path("/dir"))
    builder.visualization(custom_blob)
    spec = builder.to_spec()
    assert spec.visualization == custom_blob
    builder._validate_required_placeholders()


# ---------------------------------------------------------------------------
# 5. from_domain_update: merge onto current data
# ---------------------------------------------------------------------------


def _reference_chart_as_ql(chart_id: str) -> QLChart:
    reference = _load_reference(chart_id)
    return QLChartConverter.to_domain(reference, installation="yacloud", operations=cast(ChartOperations, _FakeOps()))


def test_from_domain_update_merges_query() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    update = chart.update.query("SELECT new").mode("save")
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["queryValue"] == "SELECT new"
    assert data["connection"] == chart.connection
    assert data["params"] == chart.params


def test_from_domain_update_merges_connection() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    update = chart.update.connection(Connection(id="new-conn", type="ch")).mode("save")
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["connection"] == {"entryId": "new-conn", "type": "ch"}


def test_from_domain_update_merges_params() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    update = chart.update.params([QLParam.string("only", default="x")]).mode("save")
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["params"] == [{"name": "only", "type": "string", "defaultValue": "x"}]


def test_from_domain_update_merges_description_into_annotation() -> None:
    reference = _load_reference("vks9wrtzto8ke")
    reference["annotation"] = {"description": "old", "futureAnnotationField": {"keep": True}}
    chart = QLChartConverter.to_domain(
        reference,
        installation="yacloud",
        operations=cast(ChartOperations, _FakeOps()),
    )
    payload = QLChartConverter.from_domain_update(chart.update.description("new")).to_payload()
    assert payload["annotation"] == {
        "description": "new",
        "futureAnnotationField": {"keep": True},
    }


def test_from_domain_update_empty_description_clears_annotation_description() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    payload = QLChartConverter.from_domain_update(chart.update.description("")).to_payload()
    assert payload["annotation"] == {"description": ""}


def test_from_domain_update_without_description_preserves_reference_annotation() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    payload = QLChartConverter.from_domain_update(chart.update.query("SELECT new")).to_payload()
    assert payload["annotation"] == {"description": ""}


def test_from_domain_update_without_current_or_new_description_omits_annotation() -> None:
    chart = QLChart(id="q1", data={"type": "ql"})
    payload = QLChartConverter.from_domain_update(chart.update.query("SELECT new")).to_payload()
    assert "annotation" not in payload


def test_from_domain_update_without_description_preserves_existing_annotation() -> None:
    reference = _load_reference("vks9wrtzto8ke")
    reference["annotation"] = {"description": "keep", "futureAnnotationField": {"keep": True}}
    chart = QLChartConverter.to_domain(
        reference,
        installation="yacloud",
        operations=cast(ChartOperations, _FakeOps()),
    )
    payload = QLChartConverter.from_domain_update(chart.update.mode("publish")).to_payload()
    assert payload["annotation"] == {
        "description": "keep",
        "futureAnnotationField": {"keep": True},
    }


def test_from_domain_update_typed_placeholders_and_decorations_preserve_untouched_data() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    original_data = json.loads(json.dumps(chart.data))
    update = (
        chart.update.x([QLColumn("new_x", cast="genericdatetime")])
        .y2(["new_y2"])
        .colors(["color"])
        .labels(["label"])
        .shapes(["shape"])
        .tooltips(["tooltip"])
    )
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])

    assert chart.data == original_data
    for key, value in original_data.items():
        if key not in {"visualization", "colors", "labels", "shapes", "tooltips"}:
            assert data[key] == value
    for section in ("colors", "labels", "shapes", "tooltips"):
        items = cast(list[dict[str, object]], data[section])
        assert [item["guid"] for item in items] == [section.removesuffix("s") if section != "colors" else "color"]

    original_visualization = cast(dict[str, object], original_data["visualization"])
    visualization = cast(dict[str, object], data["visualization"])
    assert {key: value for key, value in visualization.items() if key != "placeholders"} == {
        key: value for key, value in original_visualization.items() if key != "placeholders"
    }
    placeholders = cast(list[dict[str, object]], visualization["placeholders"])
    original_placeholders = cast(list[dict[str, object]], original_visualization["placeholders"])
    assert (
        cast(list[dict[str, object]], next(ph for ph in placeholders if ph["id"] == "x")["items"])[0]["guid"] == "new_x"
    )
    assert (
        cast(list[dict[str, object]], next(ph for ph in placeholders if ph["id"] == "y2")["items"])[0]["guid"]
        == "new_y2"
    )
    assert next(ph for ph in placeholders if ph["id"] == "y") == next(
        ph for ph in original_placeholders if ph["id"] == "y"
    )


@pytest.mark.parametrize(
    ("chart_id", "method", "placeholder_id"),
    [
        ("vks9wrtzto8ke", "x", "x"),
        ("vks9wrtzto8ke", "y", "y"),
        ("vks9wrtzto8ke", "y2", "y2"),
        ("6v4dfzzem2fep", "dimensions", "dimensions"),
        ("h6eyoxeihu8c0", "measures", "measures"),
        ("h6f6f1v2h1h40", "points", "points"),
        ("h6f6f1v2h1h40", "size", "size"),
        ("j8g0jgv2jec42", "flat_table_columns", "flat-table-columns"),
    ],
)
def test_from_domain_update_replaces_each_typed_placeholder(
    chart_id: str,
    method: str,
    placeholder_id: str,
) -> None:
    chart = _reference_chart_as_ql(chart_id)
    update = getattr(chart.update, method)(["new_column"])
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])
    visualization = cast(dict[str, object], data["visualization"])
    placeholders = cast(list[dict[str, object]], visualization["placeholders"])
    placeholder = next(item for item in placeholders if item["id"] == placeholder_id)
    assert cast(list[dict[str, object]], placeholder["items"])[0]["guid"] == "new_column"


@pytest.mark.parametrize("chart_id", ["6v4dfzzem2fep", "d2bkncoeml94w", "h6eyoxeihu8c0"])
def test_from_domain_update_routes_pie_donut_metric_colors_to_placeholder(chart_id: str) -> None:
    chart = _reference_chart_as_ql(chart_id)
    original_top_level_colors = chart.data["colors"]
    payload = QLChartConverter.from_domain_update(chart.update.colors(["new_color"])).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["colors"] == original_top_level_colors
    visualization = cast(dict[str, object], data["visualization"])
    placeholders = cast(list[dict[str, object]], visualization["placeholders"])
    color_placeholder = next(ph for ph in placeholders if ph["id"] == "colors")
    assert cast(list[dict[str, object]], color_placeholder["items"])[0]["guid"] == "new_color"


def test_ql_chart_update_fails_closed_for_placeholder_outside_active_visualization() -> None:
    chart = _reference_chart_as_ql("h6eyoxeihu8c0")
    with pytest.raises(DataLensConfigurationError, match=r"not applicable.*metric"):
        chart.update.x(["not-supported"])


def test_ql_chart_update_fails_closed_for_decoration_outside_active_visualization() -> None:
    chart = _reference_chart_as_ql("h6eyw78tblag0")
    with pytest.raises(DataLensConfigurationError, match=r"not applicable.*treemap"):
        chart.update.labels(["not-supported"])


def test_ql_chart_update_fails_closed_for_unknown_active_visualization() -> None:
    chart = QLChart(
        id="q1",
        data={"visualization": {"id": "future-viz", "placeholders": [{"id": "x", "items": []}]}},
    )
    with pytest.raises(DataLensConfigurationError, match="Unsupported active QL visualization"):
        chart.update.x(["not-supported"])


def test_from_domain_update_opaque_data_merge_preserves_untouched() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    original_colors = chart.data["colors"]
    update = chart.update.data({"extraSettings": {"hideTitle": True}}).mode("save")
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["colors"] == original_colors
    assert data["extraSettings"] == {"hideTitle": True}


def test_from_domain_update_publish_mode() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    update = chart.update.mode("publish")
    payload = QLChartConverter.from_domain_update(update).to_payload()
    assert payload["mode"] == "publish"


def test_ql_chart_update_invalid_mode_raises() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    with pytest.raises(DataLensValidationError, match="mode must be"):
        chart.update.mode("invalid_mode")  # type: ignore[arg-type]


def test_ql_chart_update_valid_modes() -> None:
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    assert chart.update.mode("save").mode_value == "save"
    assert chart.update.mode("publish").mode_value == "publish"


# ---------------------------------------------------------------------------
# 6. SDK-layer e2e via mock transport (callable factory + visualization)
# ---------------------------------------------------------------------------


def _ql_chart_response(entry_id: str = "q1", wire_type: str = "d3_ql_node") -> dict[str, object]:
    return {
        "entryId": entry_id,
        "type": wire_type,
        "data": {
            "chartType": "sql",
            "type": "ql",
            "version": "7",
            "connection": {"entryId": "c1", "type": "ch_over_yt", "dataExportForbidden": False},
            "queryValue": "SELECT 1",
            "params": [],
            "queries": [],
            "order": None,
            "colors": [],
            "labels": [],
            "shapes": [],
            "tooltips": [],
            "colorsConfig": {},
            "shapesConfig": {},
            "extraSettings": {},
            "geopointsConfig": {},
            "visualization": {"id": "line", "type": "line", "placeholders": []},
        },
        "name": "Test",
        "key": "/dir/Test",
    }


def test_ql_chart_factory_has_viz_methods() -> None:
    """client.create.ql_chart exposes one builder method per viz_id (no __call__)."""
    recorder = RecordedTransport({"/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    factory = client.create.ql_chart
    assert not callable(factory)
    builder = factory.line(name="Test", location=dl.EntryLocation.path("/dir"))
    assert hasattr(builder, "connection")
    assert hasattr(builder, "query")
    assert hasattr(builder, "x")
    assert hasattr(builder, "y")
    (
        builder.connection(Connection(id="c1", type="ch_over_yt"))
        .query("SELECT 1")
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .build()
    )
    payload = recorder.request_json(0)
    assert payload["template"] == "ql"
    assert isinstance(payload["data"], dict)


def test_ql_chart_create_get_update_delete_flow() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response()),
            "/rpc/getQLChart": httpx.Response(200, json=_ql_chart_response()),
            "/rpc/updateQLChart": httpx.Response(200, json=_ql_chart_response()),
            "/rpc/deleteQLChart": httpx.Response(200, json={}),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    chart = (
        client.create.ql_chart.line(name="Test", location=dl.EntryLocation.path("/dir"))
        .connection(Connection(id="c1", type="ch_over_yt"))
        .query("SELECT 1")
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .build()
    )
    assert isinstance(chart, QLChart)
    assert chart.id == "q1"
    assert chart.category == "ql"

    fetched = client.get.ql_chart(by_id="q1")
    assert isinstance(fetched, QLChart)

    updated = fetched.update.query("SELECT 2").mode("save").execute()
    assert isinstance(updated, QLChart)

    updated.delete()

    assert recorder.requests[0].url.path == "/rpc/createQLChart"
    assert recorder.requests[1].url.path == "/rpc/getQLChart"
    assert recorder.requests[2].url.path == "/rpc/updateQLChart"
    assert recorder.requests[3].url.path == "/rpc/deleteQLChart"


def test_ql_chart_create_payload_carries_filled_items() -> None:
    recorder = RecordedTransport({"/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    (
        client.create.ql_chart.line(name="Test", location=dl.EntryLocation.path("/dir"))
        .query("SELECT 1")
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .build()
    )
    payload = recorder.request_json(0)
    assert payload["template"] == "ql"
    data = cast(dict[str, object], payload["data"])
    assert data["queryValue"] == "SELECT 1"
    assert data["chartType"] == "sql"
    assert data["type"] == "ql"
    placeholders = cast(list[dict[str, object]], cast(dict[str, object], data["visualization"])["placeholders"])
    x_ph = next(ph for ph in placeholders if ph["id"] == "x")
    assert cast(list[dict[str, object]], x_ph["items"])[0]["guid"] == "ts"


def test_ql_chart_create_payload_passes_description_to_annotation() -> None:
    recorder = RecordedTransport({"/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    (
        client.create.ql_chart.line(name="Test", location=dl.EntryLocation.path("/dir"))
        .description("QL description")
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .build()
    )
    payload = recorder.request_json(0)
    assert payload["annotation"] == {"description": "QL description"}


def test_ql_chart_get_sends_chart_id() -> None:
    recorder = RecordedTransport({"/rpc/getQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    client.get.ql_chart(by_id="my-chart-id")
    payload = recorder.request_json(0)
    assert payload["chartId"] == "my-chart-id"


def test_ql_chart_delete_sends_chart_id() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getQLChart": httpx.Response(200, json=_ql_chart_response("to-del")),
            "/rpc/deleteQLChart": httpx.Response(200, json={}),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    chart = client.get.ql_chart(by_id="to-del")
    chart.delete()
    del_payload = recorder.request_json(1)
    assert del_payload["chartId"] == "to-del"


# ---------------------------------------------------------------------------
# 7. get_chart routing: *_ql_node -> QLChart (regression for v1 bug)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wire_type", ["d3_ql_node", "table_ql_node", "metric2_ql_node"])
def test_get_chart_routes_ql_node_to_ql_chart(wire_type: str) -> None:
    entries_response = {"entries": [{"entryId": "q1", "scope": "widget", "type": wire_type}]}
    recorder = RecordedTransport(
        {
            "/rpc/getEntries": httpx.Response(200, json=entries_response),
            "/rpc/getQLChart": httpx.Response(200, json=_ql_chart_response(wire_type=wire_type)),
        }
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    chart = client.get.chart(by_id="q1")
    assert isinstance(chart, QLChart)
    assert chart.category == "ql"
    assert chart.wire_type == wire_type
    assert is_ql_wire_type(chart.wire_type)
    # Routing must hit the QL endpoint, not wizard/editor.
    assert recorder.requests[-1].url.path == "/rpc/getQLChart"


# ---------------------------------------------------------------------------
# 8. QLParam typing and .connection(Connection) behavior
# ---------------------------------------------------------------------------


def test_qlparam_number_to_mapping() -> None:
    param = QLParam.number("limit", default="5")
    assert param.to_mapping() == {"type": "number", "name": "limit", "defaultValue": "5"}


def test_qlparam_string_to_mapping() -> None:
    param = QLParam.string("source", default="Chart")
    assert param.to_mapping() == {"type": "string", "name": "source", "defaultValue": "Chart"}


def test_qlparam_date_interval_to_mapping() -> None:
    param = QLParam.date_interval("interval", default={"from": "__relative_-30d", "to": "__relative_-0d"})
    assert param.to_mapping() == {
        "type": "date-interval",
        "name": "interval",
        "defaultValue": {"from": "__relative_-30d", "to": "__relative_-0d"},
    }


def test_qlparam_invalid_type_raises() -> None:
    with pytest.raises(DataLensValidationError, match="QLParam type must be"):
        QLParam(name="x", type="boolean", default_value="true")  # type: ignore[arg-type]


def test_qlparam_date_interval_requires_mapping() -> None:
    with pytest.raises(DataLensValidationError, match="default_value to be a Mapping"):
        QLParam(name="x", type="date-interval", default_value="not-a-mapping")


def test_qlparam_is_frozen() -> None:
    param = QLParam.number("x", default="1")
    with pytest.raises(AttributeError):
        param.name = "y"  # type: ignore[misc]


def test_create_builder_connection_serializes_connection_object() -> None:
    """create-builder .connection(Connection) maps id/type to data.connection."""
    recorder = RecordedTransport({"/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    (
        client.create.ql_chart.line(name="Test", location=dl.EntryLocation.path("/dir"))
        .connection(Connection(id="c1", type="ch_over_yt"))
        .query("SELECT 1")
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .build()
    )
    data = cast(dict[str, object], recorder.request_json(0)["data"])
    assert data["connection"] == {"entryId": "c1", "type": "ch_over_yt"}


def test_create_builder_connection_without_id_raises() -> None:
    recorder = RecordedTransport({"/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    builder = client.create.ql_chart.line(name="Test", location=dl.EntryLocation.path("/dir"))
    with pytest.raises(DataLensValidationError, match="requires a Connection with an id"):
        builder.connection(Connection(id=None, type="ch_over_yt"))


def test_create_builder_params_uses_qlparam_to_mapping() -> None:
    """create-builder .params([QLParam]) serializes via to_mapping()."""
    recorder = RecordedTransport({"/rpc/createQLChart": httpx.Response(200, json=_ql_chart_response())})
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    (
        client.create.ql_chart.line(name="Test", location=dl.EntryLocation.path("/dir"))
        .connection(Connection(id="c1", type="ch_over_yt"))
        .query("SELECT 1")
        .params([QLParam.number("limit", default="5"), QLParam.string("source", default="Chart")])
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
        .build()
    )
    data = cast(dict[str, object], recorder.request_json(0)["data"])
    assert data["params"] == [
        {"type": "number", "name": "limit", "defaultValue": "5"},
        {"type": "string", "name": "source", "defaultValue": "Chart"},
    ]


# ---------------------------------------------------------------------------
# 9. to_snake invariant: viz-id (wire) -> public method name (snake)
# ---------------------------------------------------------------------------


_QL_WIRE_ID_TO_SNAKE = {
    "line": "line",
    "area": "area",
    "column": "column",
    "bar": "bar",
    "column100p": "column_100p",
    "area100p": "area_100p",
    "bar100p": "bar_100p",
    "flatTable": "flat_table",
    "metric": "metric",
    "scatter": "scatter",
    "treemap": "treemap",
    "pie": "pie",
    "donut": "donut",
}


@pytest.mark.parametrize(("wire_id", "expected"), sorted(_QL_WIRE_ID_TO_SNAKE.items()))
def test_to_snake_projects_all_ql_wire_ids(wire_id: str, expected: str) -> None:
    """to_snake is deterministic over the full QL viz-id set; no collisions."""
    assert to_snake(wire_id) == expected


def test_to_snake_handles_dash_and_camel_and_digits() -> None:
    assert to_snake("combined-chart") == "combined_chart"
    assert to_snake("pivotTable") == "pivot_table"
    assert to_snake("simple") == "simple"


def test_to_snake_outputs_are_unique_across_ql_wire_ids() -> None:
    """Uniqueness is required for the factory method set to be collision-free."""
    mapped = [to_snake(wire_id) for wire_id in QL_VIZ_SPECS]
    assert len(set(mapped)) == len(mapped)


def test_ql_factory_method_names_match_ui_names_for_all_viz_specs() -> None:
    """The factory exposes exactly one UI-aligned method per viz-id."""
    ops = cast(ChartOperations, _FakeOps())
    factory = QLChartCreateFactory(ops)
    for wire_id in QL_VIZ_SPECS:
        method_name = factory_method_name(wire_id)
        assert hasattr(factory, method_name), f"factory missing method {method_name!r} for viz-id {wire_id!r}"
        assert callable(getattr(factory, method_name))


def test_ql_factory_does_not_expose_noncanonical_wire_methods() -> None:
    """Wire viz-ids that differ from UI method names must not leak."""
    ops = cast(ChartOperations, _FakeOps())
    factory = QLChartCreateFactory(ops)
    for wire_id in QL_VIZ_SPECS:
        if wire_id != factory_method_name(wire_id):
            assert not hasattr(factory, wire_id), f"factory should not expose wire method {wire_id!r}"


# ---------------------------------------------------------------------------
# 11. wire serialization lives only in the converter (review note #4)
# ---------------------------------------------------------------------------


def test_update_builder_stores_domain_connection_object() -> None:
    """QLChartUpdate keeps the Connection domain object; no wire dict is built."""
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    connection = Connection(id="c9", type="ch_over_yt", raw={"dataExportForbidden": True})
    update = chart.update.connection(connection).mode("save")
    assert update.connection_obj is connection
    assert isinstance(update.connection_obj, Connection)
    payload = QLChartConverter.from_domain_update(update).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["connection"] == {
        "entryId": "c9",
        "type": "ch_over_yt",
        "dataExportForbidden": True,
    }


def test_update_builder_stores_domain_param_objects() -> None:
    """QLChartUpdate keeps QLParam domain objects; to_mapping() runs in converter."""
    chart = _reference_chart_as_ql("vks9wrtzto8ke")
    params = (QLParam.number("limit", default="5"), QLParam.string("source", default="Chart"))
    update = chart.update.params(params).mode("save")
    params_objs = update.params_objs
    assert params_objs is not None
    assert params_objs == params
    assert all(isinstance(p, QLParam) for p in params_objs)


def test_create_builder_spec_carries_domain_connection_and_params() -> None:
    """to_spec() carries Connection / QLParam; wire assembly is deferred to converter."""
    ops = cast(ChartOperations, _FakeOps())
    connection = Connection(id="c1", type="ch_over_yt", raw={"dataExportForbidden": True})
    params = (QLParam.number("limit", default="5"),)
    builder = (
        QLChartCreateFactory(ops)
        .line(name="c", location=EntryLocation.path("/dir"))
        .connection(connection)
        .params(params)
        .x([QLColumn("ts", cast="genericdatetime")])
        .y([QLColumn("events", cast="integer")])
    )
    spec = builder.to_spec()
    assert spec.connection is connection
    assert spec.params == params
    assert all(isinstance(p, QLParam) for p in spec.params)
    data = cast(dict[str, object], QLChartConverter.from_domain_create(spec).to_payload()["data"])
    assert data["connection"] == {
        "entryId": "c1",
        "type": "ch_over_yt",
        "dataExportForbidden": True,
    }
    assert data["params"] == [{"type": "number", "name": "limit", "defaultValue": "5"}]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"dataExportForbidden": False}, False),
        ({"data_export_forbidden": True}, True),
        ({"data_export_forbidden": "off"}, False),
        ({"data_export_forbidden": "on"}, True),
    ],
)
def test_ql_connection_serializes_data_export_forbidden_from_connection_raw(
    raw: Mapping[str, object],
    expected: bool,
) -> None:
    spec = QLChartCreateSpec(
        name="c",
        location=EntryLocation.path("/dir"),
        connection=Connection(id="c1", type="ch_over_yt", raw=raw),
    )
    payload = QLChartConverter.from_domain_create(spec).to_payload()
    data = cast(dict[str, object], payload["data"])
    assert data["connection"] == {
        "entryId": "c1",
        "type": "ch_over_yt",
        "dataExportForbidden": expected,
    }
