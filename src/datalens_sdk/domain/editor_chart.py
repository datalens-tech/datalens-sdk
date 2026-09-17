from __future__ import annotations

from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import cast, get_args

from typing_extensions import Self

from datalens_sdk.domain.chart import Chart
from datalens_sdk.domain.chart_types import ChartCategory
from datalens_sdk.domain.entry_types import EntryUpdateMode
from datalens_sdk.domain.ports import ChartOperations
from datalens_sdk.errors import DataLensConfigurationError, DataLensValidationError, NotSupportedError
from datalens_sdk.serialization.artifacts import ArtifactPath

_UNBOUND = "Object is not bound to client operations. Use a client namespace."


class EditorChartUpdate:
    def __init__(
        self,
        *,
        chart: EditorChart,
        operations: ChartOperations | None,
        installation: str | None = None,
        wire_type: str | None = None,
        writable_tabs: AbstractSet[str] | None = None,
    ) -> None:
        self._chart = chart
        self._operations = operations
        self._installation = installation
        self._wire_type = chart.wire_type if wire_type is None else wire_type
        self._writable_tabs = None if writable_tabs is None else frozenset(writable_tabs)
        self._mode: EntryUpdateMode = "save"
        self._tab_edits: dict[str, str | None] = {}
        self._description: str | None = None

    @property
    def chart(self) -> EditorChart:
        return self._chart

    @property
    def wire_type_value(self) -> str | None:
        return self._wire_type

    @property
    def mode_value(self) -> EntryUpdateMode:
        return self._mode

    @property
    def tab_edits(self) -> Mapping[str, str | None]:
        return self._tab_edits

    @property
    def description_value(self) -> str | None:
        return self._description

    def mode(self, value: EntryUpdateMode) -> Self:
        if value not in get_args(EntryUpdateMode):
            raise DataLensValidationError(f"mode must be one of {get_args(EntryUpdateMode)}, got {value!r}")
        self._mode = value
        return self

    def _set_tab(self, tab: str, content: str | None) -> Self:
        if self._writable_tabs is not None and tab not in self._writable_tabs:
            raise NotSupportedError(
                f"Editor chart update tab {tab!r} is not available for installation {self._installation!r} "
                f"and wire_type {self._wire_type!r}; allowed tabs: {sorted(self._writable_tabs)!r}"
            )
        self._tab_edits[tab] = content
        return self

    def activities(self, value: str | None) -> Self:
        return self._set_tab("activities", value)

    def sources(self, value: str) -> Self:
        return self._set_tab("sources", value)

    def params(self, value: str) -> Self:
        return self._set_tab("params", value)

    def controls(self, value: str) -> Self:
        return self._set_tab("controls", value)

    def meta(self, value: str) -> Self:
        return self._set_tab("meta", value)

    def prepare(self, value: str) -> Self:
        return self._set_tab("prepare", value)

    def config(self, value: str) -> Self:
        return self._set_tab("config", value)

    def graph(self, value: str) -> Self:
        return self._set_tab("graph", value)

    def statface_graph(self, value: str) -> Self:
        return self._set_tab("statface_graph", value)

    def shared(self, value: str) -> Self:
        return self._set_tab("shared", value)

    def ymap(self, value: str) -> Self:
        return self._set_tab("ymap", value)

    def documentation_en(self, value: str | None) -> Self:
        return self._set_tab("documentation_en", value)

    def documentation_ru(self, value: str | None) -> Self:
        return self._set_tab("documentation_ru", value)

    def description(self, text: str) -> Self:
        self._description = text
        return self

    def execute(self) -> EditorChart:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        return self._operations.update_editor_chart(self)


@dataclass(slots=True)
class EditorChart(Chart):
    @property
    def category(self) -> ChartCategory:
        return "editor"

    def to_file(
        self,
        path: ArtifactPath,
        *,
        split_tabs: bool = False,
    ) -> Path:
        return self._write_artifact(path, split_tabs=split_tabs)

    @property
    def update(self) -> EditorChartUpdate:
        if not self.id:
            raise DataLensValidationError("Cannot update an editor chart without an id")
        if self._operations is not None:
            build_update = getattr(self._operations, "build_editor_chart_update", None)
            if build_update is not None:
                return cast(Callable[[EditorChart], EditorChartUpdate], build_update)(self)
        return EditorChartUpdate(chart=self, operations=self._operations)

    def delete(self) -> None:
        if self._operations is None:
            raise DataLensConfigurationError(_UNBOUND)
        if not self.id:
            raise DataLensValidationError("Cannot delete an editor chart without an id")
        self._operations.delete_editor_chart(self.id)
