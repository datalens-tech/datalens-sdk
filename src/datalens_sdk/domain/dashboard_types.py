from __future__ import annotations

from dataclasses import dataclass
import datetime
import re
from typing import Literal, TypeAlias, get_args

from datalens_sdk.errors import DatalensValidationError

DashboardItemType = Literal["text", "title", "widget", "image", "neuro_widget", "control", "group_control"]
"""Wire ``type`` of a dashboard item; also keys :data:`DEFAULT_ITEM_SIZES`."""
ImpactType = Literal["allTabs", "currentTab", "selectedTabs", "asGroup"]
ControlElementType = Literal["select", "date", "input", "checkbox"]
DashboardTitleSize = Literal["xs", "s", "m", "l", "xl"]
DashboardLoadPriority = Literal["charts", "selectors"]

# Server-validated operation codes for selector filters (live list from the
# createDashboard 400 body, probe P016; note NE — the server rejects NEQ).
SelectorOperation = Literal[
    "IN",
    "NIN",
    "EQ",
    "NE",
    "GT",
    "LT",
    "GTE",
    "LTE",
    "ISNULL",
    "ISNOTNULL",
    "ISTARTSWITH",
    "STARTSWITH",
    "IENDSWITH",
    "ENDSWITH",
    "ICONTAINS",
    "CONTAINS",
    "NOTICONTAINS",
    "NOTCONTAINS",
    "BETWEEN",
    "LENEQ",
    "LENGT",
    "LENGTE",
    "LENLT",
    "LENLTE",
    "NO_SELECTED_VALUES",
]
SelectorTitlePlacement = Literal["left", "top"]
SelectorPlacementMode = Literal["auto", "%", "px"]
ShowOnTabs: TypeAlias = 'Literal["current", "all"] | tuple[str, ...]'
"""Group-level DISPLAY axis: which tabs render the selector control."""
Affects: TypeAlias = 'Literal["as_group", "all_tabs"] | tuple[str, ...]'
"""Per-member INFLUENCE axis: which tabs' charts a group member filters. Maps to
the wire ``impactType`` (``asGroup``/``allTabs``/``selectedTabs``): ``"as_group"``
inherits the group (emits nothing), ``"all_tabs"`` is one shared value across all
tabs, and a tuple of tab ids scopes the member to exactly those tabs."""

KNOWN_DASHBOARD_ITEM_TYPES: frozenset[str] = frozenset(get_args(DashboardItemType))

PARENT_FIX_HEAD = "__fixHead"
PARENT_FIX_GCONT = "__fixGCont"

# header pin zones: "fixed" (__fixHead, always visible) and "collapsible"
# (__fixGCont, the user can fold it); bool stays accepted (True == collapsible)
PinZone = Literal["fixed", "collapsible"]


ValidationIssueKind = Literal[
    # reference issues — validate_dashboard_refs recipe (HTTP)
    "missing_chart",
    "missing_dataset",
    "missing_dataset_field",
    "unbound_manual_selector",
    "dangling_alias",
    "access_denied",
    # structural issues — Dashboard.validate() (pure, no HTTP)
    "duplicate_id",
    "out_of_grid",
    "overlap",
    "empty_chart_id",
    "orphan_layout",
    "missing_layout",
    "duplicate_layout",
    "alias_group_too_small",
    "duplicate_alias_group",
    "layout_reflow",
]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One dashboard problem: a broken reference (recipe, HTTP) or a structural
    defect (:meth:`Dashboard.validate`, pure). Issues are collected, never raised."""

    kind: ValidationIssueKind
    tab_id: str | None
    item_id: str | None
    message: str
    suggestions: tuple[str, ...] = ()


class _Unset:
    """Tri-state marker for update-builder settings: "leave untouched"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


class _RemoveParam:
    """Marker value: remove this key from ``settings.globalParams`` on update."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "REMOVE_PARAM"


REMOVE_PARAM = _RemoveParam()

_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")


def validate_color_value(value: str, *, field: str) -> str:
    """Validate a single color string used by dashboard item styling.

    An empty string is rejected; ``#``-prefixed values must be 6- or 8-digit
    hex (live payloads carry alpha channels like ``#027bfeb3``); any other
    non-empty string is an opaque theme token and passes through unvalidated.
    """
    if not value:
        raise DatalensValidationError(f"{field} must not be an empty string")
    if value.startswith("#") and not _HEX_COLOR_RE.fullmatch(value):
        raise DatalensValidationError(f"{field} must be a #RRGGBB or #RRGGBBAA hex color, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ThemedColor:
    """A light/dark themed color pair for dashboard item styling."""

    light: str
    dark: str

    def __post_init__(self) -> None:
        validate_color_value(self.light, field="light")
        validate_color_value(self.dark, field="dark")


# text items default to an opaque themed background (user decision, 2026-07-24);
# pass background=None for a transparent text block
DEFAULT_TEXT_BACKGROUND = ThemedColor(light="#FFFFFF", dark="#343535")


DashboardColor: TypeAlias = "str | ThemedColor"

# Relative offset edge of a date interval: optional sign, amount, unit
# (d/w/M/Q/y). The wire form is always signed ("+0d" is a valid live value);
# unsigned input like "7d" normalizes to "+7d".
_RELATIVE_OFFSET_RE = re.compile(r"[+-]?\d+[dwMQy]\Z")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z?)?\Z")


def _signed_offset(value: str) -> str:
    return value if value.startswith(("+", "-")) else f"+{value}"


def _validated_interval_edge(value: str | datetime.date, *, field: str) -> str:
    if isinstance(value, datetime.date):
        return value.isoformat()
    if not isinstance(value, str):
        raise DatalensValidationError(
            f"{field} must be an ISO date, a datetime.date, or a relative offset, got {value!r}"
        )
    if _RELATIVE_OFFSET_RE.fullmatch(value):
        return _signed_offset(value)
    if _ISO_DATE_RE.fullmatch(value):
        return value
    raise DatalensValidationError(
        f"{field} must be an ISO date like '2024-01-01' (optionally with time) or a relative "
        f"offset like '-7d'/'+0d' (units d/w/M/Q/y), got {value!r}"
    )


@dataclass(frozen=True, slots=True)
class DateInterval:
    """A date-interval selector default; each edge is an ISO date/datetime
    (or :class:`datetime.date`), or a relative offset like ``"-7d"`` for
    hybrid absolute+relative intervals."""

    start: str | datetime.date
    end: str | datetime.date

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _validated_interval_edge(self.start, field="start"))
        object.__setattr__(self, "end", _validated_interval_edge(self.end, field="end"))


@dataclass(frozen=True, slots=True)
class RelativeDateInterval:
    """A fully relative date-interval selector default (e.g. "last month"
    is ``RelativeDateInterval("-1M", "-0d")``). Offsets are ``[+-]<n><unit>``
    with units d/w/M/Q/y."""

    start: str = "-1M"
    end: str = "-0d"

    def __post_init__(self) -> None:
        for field_name in ("start", "end"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _RELATIVE_OFFSET_RE.fullmatch(value):
                raise DatalensValidationError(
                    f"{field_name} must be a relative offset like '-1M'/'+0d' (units d/w/M/Q/y), got {value!r}"
                )
            object.__setattr__(self, field_name, _signed_offset(value))


SelectorDefaultValue: TypeAlias = "str | tuple[str, ...] | bool | DateInterval | RelativeDateInterval"


def validate_dashboard_color(value: str | ThemedColor, *, field: str) -> str | ThemedColor:
    if isinstance(value, ThemedColor):
        return value
    return validate_color_value(value, field=field)


def validate_border_radius(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DatalensValidationError(f"border_radius must be an int, got {value!r}")
    if not 0 <= value <= 24 or value % 2 != 0:
        raise DatalensValidationError(f"border_radius must be between 0 and 24 with step 2, got {value}")
    return value


def validate_optional_text(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    if not value:
        raise DatalensValidationError(f"{field} must not be an empty string")
    return value
