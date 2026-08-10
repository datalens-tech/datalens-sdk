"""Selector input resolution for the dashboard tab entity (epic D4).

Split out of :mod:`datalens_sdk.domain.dashboard_tab` to keep it within the
domain size invariant; everything here is package-internal call-time
validation — no tab state is touched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import get_args

from datalens_sdk.domain.dashboard_types import (
    Affects,
    ControlElementType,
    DateInterval,
    RelativeDateInterval,
    SelectorDefaultValue,
    SelectorOperation,
    ShowOnTabs,
)
from datalens_sdk.domain.dataset import Dataset
from datalens_sdk.domain.fields import FieldLike
from datalens_sdk.domain.specs.dashboard import (
    DatasetSelectorSource,
    ManualSelectorSource,
    SelectorMemberSpec,
    SelectorSourceSpec,
)
from datalens_sdk.domain.wizard_chart import resolve_field_snapshot
from datalens_sdk.errors import DataLensValidationError

# -- selector input resolution (epic D4) -------------------------------------
#
# Date-typed data types pass through to the wire fieldType verbatim: interval
# encoding needs to distinguish plain DATE (date-only edges) from datetime
# types (full ISO+Z edges). Everything else is "string".
_DATE_DATA_TYPES = frozenset({"date", "datetime", "genericdatetime"})


def _resolved_selector_source(
    *,
    dataset: Dataset | None,
    field: FieldLike | str | None,
    param_name: str | None,
    element: ControlElementType,
    multiselect: bool,
    is_range: bool,
    options: Sequence[str | tuple[str, str] | Mapping[str, str]] | None,
    operation: SelectorOperation | None,
    required: bool,
) -> tuple[SelectorSourceSpec, str | None]:
    """Resolve and validate selector source inputs.

    Returns ``(source, auto_title)``: the auto-title is the resolved dataset
    field title or the prettified manual parameter name — used when the caller
    passed no explicit ``title=``.
    """
    if element not in get_args(ControlElementType):
        raise DataLensValidationError(
            f"element must be one of {', '.join(get_args(ControlElementType))}, got {element!r}"
        )
    if operation is not None and operation not in get_args(SelectorOperation):
        raise DataLensValidationError(f"Unknown selector operation {operation!r}")
    if multiselect and element != "select":
        raise DataLensValidationError("multiselect applies to element='select' only")
    if is_range and element != "date":
        raise DataLensValidationError("is_range applies to element='date' only")
    if options is not None and element != "select":
        raise DataLensValidationError("options apply to element='select' only")

    is_dataset = dataset is not None or field is not None
    is_manual = param_name is not None
    if is_dataset == is_manual:
        raise DataLensValidationError("Pass exactly one selector source: dataset=/field= or param_name=")

    if is_manual:
        assert param_name is not None
        if not param_name:
            raise DataLensValidationError("param_name must not be an empty string")
        if element == "select" and options is None:
            raise DataLensValidationError("options are required for a manual select selector")
        auto_title = " ".join(part.capitalize() for part in param_name.replace("_", " ").split())
        return ManualSelectorSource(
            param_name=param_name,
            element=element,
            options=_normalized_options(options) if options is not None else (),
            multiselect=multiselect,
            is_range=is_range,
            operation=operation,
            required=required,
        ), auto_title or None

    if dataset is None or field is None:
        raise DataLensValidationError("A dataset selector needs both dataset= and field=")
    if options is not None:
        raise DataLensValidationError("options apply to manual selectors only; a dataset selector reads field values")
    if not dataset.id:
        raise DataLensValidationError("Cannot reference a dataset without an id in a selector")
    snapshot = resolve_field_snapshot(field, fields=list(dataset.fields))
    guid = snapshot.get("guid")
    if not isinstance(guid, str) or not guid:
        raise DataLensValidationError(f"Field reference {field!r} resolved without a guid")
    data_type = snapshot.get("data_type")
    field_type = data_type if isinstance(data_type, str) and data_type in _DATE_DATA_TYPES else "string"
    dataset_field_type = snapshot.get("type")
    field_title = snapshot.get("title")
    if dataset_field_type == "MEASURE":
        raise DataLensValidationError(
            f"Selector field {field_title if isinstance(field_title, str) else field!r} is a MEASURE; "
            "selectors filter by DIMENSION fields (a measure has no value dictionary — "
            "the UI would render an empty list)"
        )
    source = DatasetSelectorSource(
        dataset_id=dataset.id,
        field_guid=guid,
        field_type=field_type,
        dataset_field_type=dataset_field_type
        if isinstance(dataset_field_type, str) and dataset_field_type
        else "DIMENSION",
        element=element,
        multiselect=multiselect,
        is_range=is_range,
        operation=operation,
        required=required,
    )
    return source, field_title if isinstance(field_title, str) and field_title else None


def _normalized_options(
    options: Sequence[str | tuple[str, str] | Mapping[str, str]],
) -> tuple[tuple[str, str], ...]:
    """Normalize select options into (value, title) pairs."""
    if isinstance(options, (str, bytes)) or not isinstance(options, Sequence):
        raise DataLensValidationError(f"options must be a sequence, got {options!r}")
    if not options:
        raise DataLensValidationError("options must not be empty")
    normalized: list[tuple[str, str]] = []
    for entry in options:
        if isinstance(entry, str):
            if not entry:
                raise DataLensValidationError("option values must not be empty strings")
            normalized.append((entry, entry))
            continue
        if isinstance(entry, Mapping):
            value, entry_title = entry.get("value"), entry.get("title")
            if isinstance(value, str) and value:
                normalized.append((value, entry_title if isinstance(entry_title, str) and entry_title else value))
                continue
            raise DataLensValidationError(f"option mapping needs a non-empty 'value', got {entry!r}")
        if isinstance(entry, Sequence) and len(entry) == 2:
            value, entry_title = entry[0], entry[1]
            if isinstance(value, str) and value and isinstance(entry_title, str) and entry_title:
                normalized.append((value, entry_title))
                continue
        raise DataLensValidationError(
            f"Each option must be a string, a (value, title) pair or a mapping, got {entry!r}"
        )
    return tuple(normalized)


def _derived_selector_title(title: str | None, *, auto_title: str | None) -> str:
    """Explicit title wins; otherwise the resolver-derived one (the server
    400s an empty selector title, so an empty derivation fails loud)."""
    if title is not None:
        if not title:
            raise DataLensValidationError("Selector title must not be an empty string")
        return title
    if not auto_title:
        raise DataLensValidationError("Selector title could not be derived; pass an explicit title=")
    return auto_title


def _validated_selector_default(
    default_value: str | Sequence[str] | bool | DateInterval | RelativeDateInterval | None,
    *,
    element: ControlElementType,
) -> SelectorDefaultValue | None:
    if element == "checkbox":
        if not isinstance(default_value, bool):
            raise DataLensValidationError("A checkbox selector requires a bool default_value")
        return default_value
    if default_value is None:
        return None
    if isinstance(default_value, bool):
        raise DataLensValidationError("A bool default_value applies to element='checkbox' only")
    if isinstance(default_value, (DateInterval, RelativeDateInterval)):
        if element != "date":
            raise DataLensValidationError("Interval defaults apply to element='date' only")
        return default_value
    if isinstance(default_value, str):
        if element == "select":
            return (default_value,)
        return default_value
    if isinstance(default_value, Sequence):
        values = tuple(default_value)
        if element != "select":
            raise DataLensValidationError("A sequence default_value applies to element='select' only")
        if not all(isinstance(entry, str) for entry in values):
            raise DataLensValidationError(f"Select default values must be strings, got {default_value!r}")
        return values
    raise DataLensValidationError(f"Unsupported default_value {default_value!r} for element {element!r}")


def _normalized_show_on_tabs(show_on_tabs: ShowOnTabs) -> ShowOnTabs:
    if isinstance(show_on_tabs, str):
        if show_on_tabs in ("current", "all"):
            return show_on_tabs
        raise DataLensValidationError(
            f"show_on_tabs must be 'current', 'all' or a sequence of tab ids, got {show_on_tabs!r}"
        )
    if isinstance(show_on_tabs, Sequence):
        tab_ids = tuple(show_on_tabs)
        if not tab_ids:
            raise DataLensValidationError("show_on_tabs tab list must not be empty")
        if not all(isinstance(entry, str) and entry for entry in tab_ids):
            raise DataLensValidationError(f"show_on_tabs tab ids must be non-empty strings, got {show_on_tabs!r}")
        if len(set(tab_ids)) != len(tab_ids):
            raise DataLensValidationError(f"show_on_tabs tab ids must be unique, got {show_on_tabs!r}")
        return tab_ids
    raise DataLensValidationError(
        f"show_on_tabs must be 'current', 'all' or a sequence of tab ids, got {show_on_tabs!r}"
    )


def _normalized_affects(affects: Affects) -> Affects:
    if isinstance(affects, str):
        if affects in ("as_group", "all_tabs"):
            return affects
        raise DataLensValidationError(
            f"affects must be 'as_group', 'all_tabs' or a sequence of tab ids, got {affects!r}"
        )
    if isinstance(affects, Sequence):
        tab_ids = tuple(affects)
        if not tab_ids:
            raise DataLensValidationError("affects tab list must not be empty")
        if not all(isinstance(entry, str) and entry for entry in tab_ids):
            raise DataLensValidationError(f"affects tab ids must be non-empty strings, got {affects!r}")
        if len(set(tab_ids)) != len(tab_ids):
            raise DataLensValidationError(f"affects tab ids must be unique, got {affects!r}")
        return tab_ids
    raise DataLensValidationError(f"affects must be 'as_group', 'all_tabs' or a sequence of tab ids, got {affects!r}")


def _reject_conflicting_singleton_scope(members: Sequence[SelectorMemberSpec], group_show_on_tabs: ShowOnTabs) -> None:
    """A single-member group serializes ONE impact slot (``data.group[0]``); it
    cannot carry both a group-level display scope and a member influence scope
    without silently dropping one axis, so reject the ambiguous combination."""
    if len(members) == 1 and group_show_on_tabs != "current" and members[0].affects != "as_group":
        raise DataLensValidationError(
            "a single-member shared group cannot combine a group-level show_on_tabs with a member affects "
            "(the wire has one impact slot); add a second member or use only one axis"
        )


def _validated_member_scope(
    *, group: str | None, show_on_tabs: ShowOnTabs, affects: Affects
) -> tuple[ShowOnTabs, Affects]:
    """Normalize and cross-validate a selector's two tab axes: ``show_on_tabs``
    is group-level DISPLAY (only for a standalone selector's own singleton
    group); ``affects`` is per-member INFLUENCE (only inside a group=)."""
    if group is not None and not group:
        raise DataLensValidationError("group must not be an empty string")
    member_show_on_tabs = _normalized_show_on_tabs(show_on_tabs)
    member_affects = _normalized_affects(affects)
    if group is not None:
        if member_show_on_tabs != "current":
            raise DataLensValidationError(
                "show_on_tabs is a group-level display setting: pass it to add_group_selector; "
                "for per-member tab influence use affects="
            )
    elif member_affects != "as_group":
        raise DataLensValidationError(
            "affects applies to group members; a standalone selector's tab scope is show_on_tabs"
        )
    return member_show_on_tabs, member_affects
