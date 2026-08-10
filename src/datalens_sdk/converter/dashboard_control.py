"""Wire assembly for group_control selector items (epic D4).

Owns the selector default encoding split observed in live UI payloads
(golden fixtures + probe P016): the raw typed value goes to
``source.defaultValue`` while the dashboard ``defaults`` mapping carries the
``__<operation>_``-prefixed form when an operation is set (``__eq_Value 5``,
``__between___interval_...``) and the plain form otherwise. Date intervals
are encoded as ``__interval_<from>_<to>`` with ``__relative_<offset>`` edges;
DATE fields take date-only edges, DATETIME fields full ISO with a ``Z``.
"""

from __future__ import annotations

from typing import cast

from datalens_sdk.domain.dashboard_types import (
    Affects,
    DateInterval,
    RelativeDateInterval,
    SelectorDefaultValue,
    ShowOnTabs,
)
from datalens_sdk.domain.specs.dashboard import (
    DatasetSelectorSource,
    ExternalControlItem,
    GroupControlItem,
    ManualSelectorSource,
    SelectorMemberSpec,
)
from datalens_sdk.errors import DataLensValidationError

_MEMBER_NAMESPACE = "default"

# Wire fieldType marking a date-typed dataset field; everything else keeps
# full ISO datetime edges in interval encodings.
_DATE_FIELD_TYPE = "date"

_INTERVAL_START_TIME = "T00:00:00.000Z"
_INTERVAL_END_TIME = "T23:59:59.999Z"


def _interval_edge_wire(edge: str, *, field_type: str, is_end: bool) -> str:
    """Encode one interval edge: relative offsets get the ``__relative_``
    marker; absolute dates are date-only for DATE fields and full ISO+Z for
    datetime fields (day bounds expand asymmetrically, the UI convention)."""
    if edge.startswith(("+", "-")):
        return f"__relative_{edge}"
    if field_type == _DATE_FIELD_TYPE:
        return edge.split("T", 1)[0]
    if "T" not in edge:
        return f"{edge}{_INTERVAL_END_TIME if is_end else _INTERVAL_START_TIME}"
    return edge if edge.endswith("Z") else f"{edge}Z"


def _interval_wire(value: DateInterval | RelativeDateInterval, *, field_type: str) -> str:
    # DateInterval.__post_init__ normalizes date objects to ISO strings
    start = _interval_edge_wire(cast(str, value.start), field_type=field_type, is_end=False)
    end = _interval_edge_wire(cast(str, value.end), field_type=field_type, is_end=True)
    return f"__interval_{start}_{end}"


def _raw_default_wire(value: SelectorDefaultValue, *, field_type: str) -> str | list[str]:
    """The ``source.defaultValue`` form: typed values without operation prefix."""
    if isinstance(value, (DateInterval, RelativeDateInterval)):
        return _interval_wire(value, field_type=field_type)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return list(value)


def _prefixed_defaults_wire(raw: str | list[str], *, operation: str | None) -> str | list[str]:
    """Apply the ``__<op>_`` operation prefix to an already-encoded raw wire
    value (``source.defaultValue`` form)."""
    if operation is None:
        return raw
    prefix = f"__{operation.lower()}_"
    if isinstance(raw, list):
        return [f"{prefix}{entry}" for entry in raw]
    return f"{prefix}{raw}"


def encode_selector_default(
    value: SelectorDefaultValue,
    *,
    field_type: str,
    operation: str | None,
) -> str | list[str]:
    """The dashboard ``defaults`` form: ``__<op>_``-prefixed when an operation
    is set (the UI convention), plain wire value otherwise (live-verified to
    filter either way, P016)."""
    return _prefixed_defaults_wire(_raw_default_wire(value, field_type=field_type), operation=operation)


def _member_source_wire(member: SelectorMemberSpec) -> tuple[str, str, str, dict[str, object]]:
    """Build the member's ``source`` dict.

    Returns ``(source_type, defaults_key, field_type, source)``; the defaults
    key is the dataset field guid or the manual parameter name.
    """
    source: dict[str, object] = {"showTitle": member.show_title}
    spec = member.source
    if isinstance(spec, DatasetSelectorSource):
        source_type = "dataset"
        defaults_key = spec.field_guid
        field_type = spec.field_type
        source.update(
            {
                "datasetId": spec.dataset_id,
                "datasetFieldId": spec.field_guid,
                "datasetFieldType": spec.dataset_field_type,
                "fieldType": spec.field_type,
                "elementType": spec.element,
            }
        )
    elif isinstance(spec, ManualSelectorSource):
        source_type = "manual"
        defaults_key = spec.param_name
        field_type = ""
        source.update({"fieldName": spec.param_name, "elementType": spec.element})
        if spec.element == "select":
            source["acceptableValues"] = [{"title": title, "value": value} for value, title in spec.options]
    else:  # pragma: no cover - union is closed
        raise DataLensValidationError(f"Unsupported selector source {type(spec).__name__!r}")

    if spec.element == "select":
        source["multiselectable"] = spec.multiselect
    if spec.element == "date":
        source["isRange"] = spec.is_range
    if spec.operation is not None:
        source["operation"] = spec.operation
    source["required"] = spec.required

    source["titlePlacement"] = member.title_placement
    if member.inner_title is not None:
        source["innerTitle"] = member.inner_title
    source["showHint"] = member.hint is not None
    if member.hint is not None:
        source["hint"] = member.hint
    if member.default_value is not None:
        source["defaultValue"] = _raw_default_wire(member.default_value, field_type=field_type)
    return source_type, defaults_key, field_type, source


def _empty_default(element: str) -> str | list[str]:
    """``defaults`` value when no default is set."""
    return [] if element == "select" else ""


def _impact_fields(show_on_tabs: ShowOnTabs) -> dict[str, object]:
    """Wire impact scope for a GROUP-level show_on_tabs value; "current" emits
    nothing (the UI omits the fields on ordinary selectors — fixture canon)."""
    if show_on_tabs == "all":
        return {"impactType": "allTabs"}
    if isinstance(show_on_tabs, tuple):
        return {"impactType": "selectedTabs", "impactTabsIds": list(show_on_tabs)}
    return {}


def _member_impact_fields(affects: Affects) -> dict[str, object]:
    """Wire impact scope for a per-member ``affects`` value. ``"as_group"``
    emits nothing (inherit the group), ``"all_tabs"`` is one shared value across
    tabs, and a tuple scopes the member to exactly those tabs (``selectedTabs``)."""
    if affects == "all_tabs":
        return {"impactType": "allTabs"}
    if isinstance(affects, tuple):
        return {"impactType": "selectedTabs", "impactTabsIds": list(affects)}
    return {}


def _member_wire(member: SelectorMemberSpec) -> dict[str, object]:
    source_type, defaults_key, field_type, source = _member_source_wire(member)
    spec = member.source
    if member.default_value is not None:
        defaults_value = encode_selector_default(member.default_value, field_type=field_type, operation=spec.operation)
    else:
        defaults_value = _empty_default(spec.element)
    wire: dict[str, object] = {
        "id": member.id,
        "title": member.title,
        "namespace": _MEMBER_NAMESPACE,
        "sourceType": source_type,
        "placementMode": member.placement_mode,
        "width": member.width,
        "source": source,
        "defaults": {defaults_key: defaults_value},
    }
    wire.update(_member_impact_fields(member.affects))
    return wire


def _group_control_data(item: GroupControlItem) -> dict[str, object]:
    """The ``data`` dict of a group_control item. ``updateControlsOnChange``
    and ``showGroupName`` are wire-required booleans and always emitted."""
    members_wire = [_member_wire(member) for member in item.members]
    data: dict[str, object] = {
        "group": members_wire,
        "autoHeight": item.auto_height,
        "buttonApply": item.apply_button,
        "buttonReset": item.reset_button,
        "updateControlsOnChange": item.update_on_change,
        "showGroupName": item.show_group_name,
    }
    group_impact = _impact_fields(item.show_on_tabs)
    if group_impact:
        if len(members_wire) == 1:
            # single-member quirk: impact fields live in data.group[0], not
            # data — otherwise the UI hides the group settings dialog. A member
            # with its own explicit ``affects`` already occupies group[0]; only
            # fall back to the group scope when it did not (avoids leaving a
            # stale impactTabsIds behind a bare dict.update override).
            if "impactType" not in members_wire[0]:
                members_wire[0].update(group_impact)
        else:
            data.update(group_impact)
    if item.border_radius is not None:
        data["borderRadius"] = item.border_radius
    return data


def _external_control_wire(item: ExternalControlItem, *, namespace: str) -> dict[str, object]:
    """The full standalone ``control`` wire item for an external selector.

    ``defaults`` live at ITEM level in this format; ``showTitle`` is never
    emitted (the server silently strips it, P017).
    """
    return {
        "id": item.id,
        "type": "control",
        "namespace": namespace,
        "defaults": {},
        "data": {
            "title": item.title,
            "sourceType": "external",
            "source": {"chartId": item.chart_id},
        },
    }


def _tab_used_fields(tab: dict[str, object] | object) -> set[str]:
    """Every field/parameter name still referenced by the tab's items:
    widget chart-tab ``params`` keys, control/member ``defaults`` keys and
    ``source.fieldName``/``source.datasetFieldId`` — the field-usage set the
    UI's alias self-repair works against."""
    used: set[str] = set()
    if not isinstance(tab, dict):
        return used

    def _absorb_control(node: object) -> None:
        if not isinstance(node, dict):
            return
        defaults = node.get("defaults")
        if isinstance(defaults, dict):
            used.update(key for key in defaults if isinstance(key, str))
        source = node.get("source")
        if isinstance(source, dict):
            for key in ("fieldName", "datasetFieldId"):
                value = source.get(key)
                if isinstance(value, str) and value:
                    used.add(value)

    for container in ("items", "globalItems"):
        entries = tab.get(container)
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            _absorb_control(item)
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            _absorb_control(data)
            for member in data.get("group") or []:
                _absorb_control(member)
            for chart_tab in data.get("tabs") or []:
                if isinstance(chart_tab, dict):
                    _absorb_control(chart_tab)
                    params = chart_tab.get("params")
                    if isinstance(params, dict):
                        used.update(key for key in params if isinstance(key, str))
    return used


def _drop_dangling_aliases(tab: dict[str, object], *, used_before: set[str]) -> None:
    """Drop alias fields whose LAST parameter user this removal took away
    (the UI self-repair semantics); groups shrunk below two fields are removed
    entirely.

    The rule is a diff, not an absolute usage check: an alias field the tab's
    items never referenced as a parameter — e.g. a field of a widget's OTHER
    dataset in a cross-dataset alias, whose usage lives inside the chart and
    is invisible in the dashboard document — must survive removals of
    unrelated items (live UAT P021). Pre-existing dangling fields also stay
    verbatim; detecting those is validate_dashboard_refs' job.
    """
    aliases = tab.get("aliases")
    if not isinstance(aliases, dict):
        return
    default = aliases.get("default")
    if not isinstance(default, list):
        return
    lost = used_before - _tab_used_fields(tab)
    if not lost:
        return
    kept_groups: list[object] = []
    for group in default:
        if not isinstance(group, list):
            kept_groups.append(group)
            continue
        kept = [field for field in group if not (isinstance(field, str) and field in lost)]
        if len(kept) >= 2:
            kept_groups.append(kept if len(kept) != len(group) else group)
    default[:] = kept_groups
