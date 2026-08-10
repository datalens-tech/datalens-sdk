"""Chart-reference resolution for the dashboard tab entity (epic D2).

Split out of :mod:`datalens_sdk.domain.dashboard_tab` to keep it within the
domain size invariant. ``DashboardChartTab`` stays publicly importable from
``datalens_sdk`` (re-exported through the tab module).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from datalens_sdk.domain.dashboard_types import validate_optional_text
from datalens_sdk.domain.editor_chart import EditorChart
from datalens_sdk.domain.specs.dashboard import WidgetTabSpec
from datalens_sdk.domain.wizard_chart import WizardChart
from datalens_sdk.errors import DataLensValidationError

DashboardChartParams = Mapping[str, "str | Sequence[str]"]

# Pending items carry the sentinel id; real ids are assigned at attach time.
_PENDING_ID = ""


@dataclass(frozen=True, slots=True)
class DashboardChartTab:
    """One chart inside :meth:`DashboardTab.add_chart_group`."""

    chart: WizardChart | EditorChart | str
    title: str | None = None
    params: DashboardChartParams | None = None
    description: str | None = None
    hint: str | None = None
    auto_height: bool = False
    default: bool = False
    enable_action_params: bool = False


@dataclass(frozen=True, slots=True)
class _ResolvedChartTab:
    """Validated add_chart(_group) inputs, resolved before any state mutation."""

    chart_id: str
    title: str
    installation: str
    is_default: bool
    params: Mapping[str, tuple[str, ...]]
    auto_height: bool
    description: str | None
    hint: str | None
    enable_action_params: bool


def _normalize_params(params: DashboardChartParams | None) -> Mapping[str, tuple[str, ...]]:
    if params is None:
        return MappingProxyType({})
    normalized: dict[str, tuple[str, ...]] = {}
    for key, value in params.items():
        if isinstance(value, str):
            normalized[key] = (value,)
            continue
        if isinstance(value, Sequence):
            values = tuple(value)
            if all(isinstance(entry, str) for entry in values):
                normalized[key] = values
                continue
        raise DataLensValidationError(f"Chart param {key!r} must be a string or a sequence of strings, got {value!r}")
    return MappingProxyType(normalized)


def _resolve_chart_ref(
    chart: WizardChart | EditorChart | str,
    *,
    title: str | None,
) -> tuple[str, str, str]:
    """Resolve a chart reference into (chart_id, title, installation).

    The installation is recorded for the attach-time check against the
    builder's installation; an id string carries no installation ("").
    """
    if isinstance(chart, str):
        if not chart:
            raise DataLensValidationError("chart id must not be an empty string")
        if not title:
            raise DataLensValidationError("title is required when the chart is passed as an id string")
        return chart, title, ""
    if not chart.id:
        raise DataLensValidationError("Cannot place a chart without an id on a dashboard")
    resolved_title = title if title is not None else chart.name
    if not resolved_title:
        raise DataLensValidationError(f"Chart {chart.id!r} has no name; pass an explicit title=")
    return chart.id, resolved_title, chart.installation or ""


def _resolved_chart_tab(
    chart: WizardChart | EditorChart | str,
    *,
    title: str | None,
    params: DashboardChartParams | None,
    description: str | None,
    hint: str | None,
    auto_height: bool,
    is_default: bool,
    enable_action_params: bool = False,
) -> _ResolvedChartTab:
    chart_id, resolved_title, installation = _resolve_chart_ref(chart, title=title)
    return _ResolvedChartTab(
        chart_id=chart_id,
        title=resolved_title,
        installation=installation,
        is_default=is_default,
        params=_normalize_params(params),
        auto_height=auto_height,
        description=validate_optional_text(description, field="description"),
        hint=validate_optional_text(hint, field="hint"),
        enable_action_params=enable_action_params,
    )


def _pending_widget_tabs(resolved: Sequence[_ResolvedChartTab]) -> tuple[WidgetTabSpec, ...]:
    return tuple(
        WidgetTabSpec(
            id=_PENDING_ID,
            chart_id=entry.chart_id,
            title=entry.title,
            is_default=entry.is_default,
            params=entry.params,
            auto_height=entry.auto_height,
            description=entry.description,
            hint=entry.hint,
            enable_action_params=entry.enable_action_params,
        )
        for entry in resolved
    )
