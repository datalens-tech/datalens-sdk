from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import re
import uuid

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)


def _normalize_iso_date(value: str, *, end: bool = False, inclusive_end: bool = True) -> str:
    """Normalize an ISO date or datetime string to UTC ISO format with Z suffix.

    For date-only strings like "2026-04-20", appends time and Z suffix.
    For full datetime strings, normalizes offset to Z.
    """
    value = value.strip()
    if not _ISO_DATE_RE.match(value):
        return value
    if "T" not in value:
        try:
            date.fromisoformat(value)
        except ValueError:
            return value
        if end and not inclusive_end:
            time_part = "T00:00:00.000Z"
        elif end:
            time_part = "T23:59:59.999Z"
        else:
            time_part = "T00:00:00.000Z"
        return value + time_part
    parseable = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError:
        return value
    if value.endswith("Z"):
        return value
    offset = re.search(r"[+-]\d{2}:\d{2}$", value)
    if offset is None:
        return value + "Z"
    fraction = re.search(r"T\d{2}:\d{2}:\d{2}(\.\d+)?", value)
    fractional_part = fraction.group(1) if fraction is not None and fraction.group(1) is not None else ""
    utc = parsed.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + fractional_part + "Z"


def build_date_interval(start: str, end: str, *, inclusive_end: bool = True) -> str:
    """Build a DataLens absolute date interval string for BETWEEN filter values.

    Produces ``__interval_<startZ>_<endZ>`` from ISO date or datetime strings.
    Both values are normalized to UTC ISO format with Z suffix.
    """
    start_norm = _normalize_iso_date(start, end=False)
    end_norm = _normalize_iso_date(end, end=True, inclusive_end=inclusive_end)
    return f"__interval_{start_norm}_{end_norm}"


def build_relative_date_interval(start_offset: str, end_offset: str) -> str:
    """Build a DataLens relative date interval string for BETWEEN filter values.

    Offsets follow DataLens format: ``-30d``, ``-1M``, ``+0d``, etc.
    Produces ``__interval___relative_<start>___relative_<end>``.
    """
    return f"__interval___relative_{start_offset}___relative_{end_offset}"


def build_navigator_settings(*, mode: str, current: object = None) -> dict[str, object]:
    """Return the complete navigator object required by the Wizard v3 schema."""
    settings = dict(current) if isinstance(current, Mapping) else {}
    settings.setdefault("linesMode", "all")
    settings["navigatorMode"] = mode
    settings.setdefault(
        "periodSettings",
        {
            "period": "year",
            "type": "genericdatetime",
            "value": "1",
        },
    )
    settings.setdefault("selectedLines", [])
    return settings


def build_gradient_state(
    *,
    mode: str,
    palette: str,
    reversed: bool,
    thresholds: tuple[float, ...] | None,
) -> dict[str, object]:
    state: dict[str, object] = {
        "gradientMode": mode,
        "gradientPalette": palette,
        "reversed": reversed,
    }
    if thresholds is not None:
        state["thresholdsMode"] = "manual"
        if mode == "2-point" and len(thresholds) == 2:
            state["leftThreshold"] = str(thresholds[0])
            state["rightThreshold"] = str(thresholds[1])
        elif mode == "3-point" and len(thresholds) == 3:
            state["leftThreshold"] = str(thresholds[0])
            state["middleThreshold"] = str(thresholds[1])
            state["rightThreshold"] = str(thresholds[2])
    else:
        state["thresholdsMode"] = "auto"
    return state


def build_background_settings(
    *,
    mode: str,
    palette: str,
    reversed: bool,
    thresholds: tuple[float, ...] | None,
) -> dict[str, object]:
    return {
        "enabled": True,
        "settingsId": str(uuid.uuid4()),
        "settings": {
            "gradientState": build_gradient_state(
                mode=mode,
                palette=palette,
                reversed=reversed,
                thresholds=thresholds,
            ),
            "paletteState": {},
            "isContinuous": True,
        },
    }


def build_bars_settings(
    *,
    enabled: bool,
    color_type: str = "one-color",
    color: str | None = None,
    palette: str | None = None,
    color_index: int | None = None,
    color_positive: str | None = None,
    color_negative: str | None = None,
    positive_color_index: int | None = None,
    negative_color_index: int | None = None,
    gradient_palette: str | None = None,
    gradient_type: str = "2-point",
    reversed: bool = False,
    show_labels: bool,
    show_in_totals: bool,
    align: str,
) -> dict[str, object]:
    settings: dict[str, object] = {
        "enabled": enabled,
        "showLabels": show_labels,
        "showBarsInTotals": show_in_totals,
        "align": align,
        "scale": {"mode": "auto"},
    }
    if color_type == "two-color":
        two_color_settings: dict[str, object] = {}
        if color_positive is not None:
            two_color_settings["positiveColor"] = color_positive
        if color_negative is not None:
            two_color_settings["negativeColor"] = color_negative
        if positive_color_index is not None:
            two_color_settings["positiveColorIndex"] = positive_color_index
        if negative_color_index is not None:
            two_color_settings["negativeColorIndex"] = negative_color_index
        settings["colorSettings"] = {"colorType": "two-color", "settings": two_color_settings}
    elif color_type == "gradient":
        settings["colorSettings"] = {
            "colorType": "gradient",
            "settings": {
                "gradientType": gradient_type,
                "thresholds": {"mode": "auto"},
                "palette": gradient_palette or "",
                "reversed": reversed,
            },
        }
    elif color_type == "one-color":
        one_color_settings: dict[str, object] = {}
        if color is not None:
            one_color_settings["color"] = color
        if palette is not None:
            one_color_settings["palette"] = palette
        if color_index is not None:
            one_color_settings["colorIndex"] = color_index
        settings["colorSettings"] = {"colorType": "one-color", "settings": one_color_settings}
    return settings
