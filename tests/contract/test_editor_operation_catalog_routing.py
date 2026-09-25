from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, cast

import httpx
import pytest

from datalens_sdk import EntryLocation, JsonValue
from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.api.chart import ChartAPI, ChartService
from datalens_sdk.api.entries import EntriesService
from datalens_sdk.converter.wizard_chart import WizardChartDtoModule
from datalens_sdk.domain.editor_chart import EditorChart, EditorChartUpdate
from datalens_sdk.domain.ports import NavigationOperations
from datalens_sdk.domain.raw_resource import RawEditorChartCreate, RawEditorChartReplace
from datalens_sdk.errors import NotSupportedError
from datalens_sdk.http import DataLensHTTPClient

_INSTALLATION = "synthetic"
_CREATE_ONLY_WIRE_TYPE = "advanced-chart_node"
_UPDATE_ONLY_WIRE_TYPE = "markdown_node"


class _DivergentEditorDtoModule:
    INSTALLATION_EDITOR_READ_NODE_TYPES: ClassVar[dict[str, frozenset[str]]] = {
        _INSTALLATION: frozenset({_CREATE_ONLY_WIRE_TYPE, _UPDATE_ONLY_WIRE_TYPE})
    }
    INSTALLATION_EDITOR_CREATE_NODE_TYPES: ClassVar[dict[str, frozenset[str]]] = {
        _INSTALLATION: frozenset({_CREATE_ONLY_WIRE_TYPE})
    }
    INSTALLATION_EDITOR_UPDATE_NODE_TYPES: ClassVar[dict[str, frozenset[str]]] = {
        _INSTALLATION: frozenset({_UPDATE_ONLY_WIRE_TYPE})
    }
    INSTALLATION_EDITOR_UPDATE_TABS_BY_WIRE_TYPE: ClassVar[dict[str, dict[str, frozenset[str]]]] = {
        _INSTALLATION: {_UPDATE_ONLY_WIRE_TYPE: frozenset({"controls", "meta", "params", "prepare", "sources"})}
    }
    INSTALLATION_EDITOR_NODE_TYPES: ClassVar[dict[str, frozenset[str]]] = INSTALLATION_EDITOR_CREATE_NODE_TYPES

    def __getattr__(self, name: str) -> object:
        return getattr(generated_dto, name)


def _editor_snapshot(*, chart_id: str) -> dict[str, object]:
    return {
        "entry": {
            "entryId": chart_id,
            "type": _CREATE_ONLY_WIRE_TYPE,
            "key": f"/Charts/{chart_id}",
            "data": {
                "sources": "module.exports = {};\n",
                "params": "module.exports = {};\n",
                "controls": "module.exports = [];\n",
                "meta": "module.exports = {};\n",
                "prepare": "module.exports = {};\n",
            },
        }
    }


def _raw(value: Mapping[str, object]) -> Mapping[str, JsonValue]:
    return cast(Mapping[str, JsonValue], value)


def test_editor_mutations_use_their_operation_specific_catalogs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_editor_snapshot(chart_id="created-chart"))

    http = DataLensHTTPClient(
        installation=_INSTALLATION,
        sdk_version="test",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    service = ChartService(
        installation=_INSTALLATION,
        api=ChartAPI(http),
        entries_service=cast(EntriesService, object()),
        navigation_operations=cast(NavigationOperations, object()),
        dto_module=cast(WizardChartDtoModule, _DivergentEditorDtoModule()),
    )
    source = _raw(_editor_snapshot(chart_id="source-chart"))

    created = RawEditorChartCreate(
        response_snapshot=source,
        name="Clone",
        location=EntryLocation.path("/Charts"),
        operations=service,
    ).build()
    assert [request.url.path for request in requests] == ["/rpc/createEditorChart"]

    with pytest.raises(NotSupportedError, match=_CREATE_ONLY_WIRE_TYPE):
        _ = created.update

    direct_update = EditorChartUpdate(chart=created, operations=service)
    with pytest.raises(NotSupportedError, match=_CREATE_ONLY_WIRE_TYPE):
        service.update_editor_chart(direct_update)

    raw_replace = RawEditorChartReplace(
        response_snapshot=source,
        target=created,
        installation=_INSTALLATION,
        operations=service,
    )
    with pytest.raises(NotSupportedError, match=_CREATE_ONLY_WIRE_TYPE):
        raw_replace.execute()

    assert [request.url.path for request in requests] == ["/rpc/createEditorChart"]


@pytest.mark.parametrize("configured_tabs", [None, frozenset()])
def test_chart_update_facade_distinguishes_missing_and_empty_tab_catalog_entries(
    configured_tabs: frozenset[str] | None,
) -> None:
    tabs_by_wire_type = {"other_node": frozenset({"sources"})}
    if configured_tabs is not None:
        tabs_by_wire_type[_UPDATE_ONLY_WIRE_TYPE] = configured_tabs

    class _TabCatalogDtoModule(_DivergentEditorDtoModule):
        INSTALLATION_EDITOR_UPDATE_TABS_BY_WIRE_TYPE: ClassVar[dict[str, dict[str, frozenset[str]]]] = {
            _INSTALLATION: tabs_by_wire_type
        }

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    http = DataLensHTTPClient(
        installation=_INSTALLATION,
        sdk_version="test",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    service = ChartService(
        installation=_INSTALLATION,
        api=ChartAPI(http),
        entries_service=cast(EntriesService, object()),
        navigation_operations=cast(NavigationOperations, object()),
        dto_module=cast(WizardChartDtoModule, _TabCatalogDtoModule()),
    )
    chart = EditorChart(
        id="update-chart",
        installation=_INSTALLATION,
        wire_type=_UPDATE_ONLY_WIRE_TYPE,
        _operations=service,
    )

    update = chart.update
    if configured_tabs is None:
        assert update.sources("new").tab_edits == {"sources": "new"}
    else:
        with pytest.raises(NotSupportedError, match=r"allowed tabs: \[\]"):
            update.sources("new")

    assert requests == []
