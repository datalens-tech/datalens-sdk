from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pydantic import TypeAdapter

from datalens_sdk.errors import DataLensConfigurationError


def _adapter(module: object, name: str) -> TypeAdapter[object]:
    carrier = getattr(module, name, None)
    if carrier is None:
        raise DataLensConfigurationError(
            f"Generated Dashboard V2 carrier {name!r} is unavailable for this installation."
        )
    return TypeAdapter(cast(Any, carrier))


def _serialize(
    adapter: TypeAdapter[object],
    value: dict[str, object],
    *,
    context: str,
) -> dict[str, object]:
    model = adapter.validate_python(value)
    result = adapter.dump_python(model, mode="json", by_alias=True, exclude_unset=True)
    if not isinstance(result, dict) or not all(isinstance(key, str) for key in result):
        raise DataLensConfigurationError(f"Generated {context} serializer did not return an object.")
    return cast("dict[str, object]", result)


def _restore_integral_layout_coordinates(value: dict[str, object]) -> dict[str, object]:
    """Keep validated DTO fragments usable by the integer-grid RMW engine.

    Some generated installation contracts model dashboard coordinates as
    JSON ``number`` and therefore dump SDK integers as integral floats.  The
    update applier feeds serialized fragments back into later operations in
    the same builder, while layout geometry deliberately accepts integers
    only.  Restore the domain representation after generated validation; the
    final endpoint DTO remains free to serialize these integers as numbers.
    """
    for key in ("x", "y", "w", "h"):
        coordinate = value.get(key)
        if isinstance(coordinate, float) and coordinate.is_integer():
            value[key] = int(coordinate)
    return value


def _restore_tab_layout_coordinates(value: dict[str, object]) -> dict[str, object]:
    layout = value.get("layout")
    if not isinstance(layout, list):
        return value
    for entry in layout:
        if isinstance(entry, dict):
            _restore_integral_layout_coordinates(entry)
    return value


@dataclass(frozen=True, slots=True)
class DashboardGeneratedContract:
    tab: TypeAdapter[object]
    item: TypeAdapter[object]
    layout: TypeAdapter[object]
    connection: TypeAdapter[object]
    aliases: TypeAdapter[object]

    @classmethod
    def from_module(cls, module: object) -> DashboardGeneratedContract:
        return cls(
            tab=_adapter(module, "DashTabV2DTO"),
            item=_adapter(module, "DashTabItemV2DTO"),
            layout=_adapter(module, "DashLayoutItemV2DTO"),
            connection=_adapter(module, "DashConnectionV2DTO"),
            aliases=_adapter(module, "DashTabV2AliasesDTO"),
        )

    def serialize_tab(self, value: dict[str, object]) -> dict[str, object]:
        serialized = _serialize(self.tab, value, context="Dashboard tab")
        return _restore_tab_layout_coordinates(serialized)

    def serialize_item(self, value: dict[str, object]) -> dict[str, object]:
        return _serialize(self.item, value, context="Dashboard item")

    def serialize_layout(self, value: dict[str, object]) -> dict[str, object]:
        serialized = _serialize(self.layout, value, context="Dashboard layout")
        return _restore_integral_layout_coordinates(serialized)

    def serialize_connection(self, value: dict[str, object]) -> dict[str, object]:
        return _serialize(self.connection, value, context="Dashboard connection")

    def serialize_alias(self, fields: tuple[str, ...]) -> list[str]:
        serialized = _serialize(self.aliases, {"default": [list(fields)]}, context="Dashboard aliases")
        groups = serialized.get("default")
        if (
            not isinstance(groups, list)
            or len(groups) != 1
            or not isinstance(groups[0], list)
            or not all(isinstance(field, str) for field in groups[0])
        ):
            raise DataLensConfigurationError("Generated Dashboard alias serializer returned an invalid group.")
        return cast("list[str]", groups[0])
