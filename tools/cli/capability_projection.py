"""Project local capability resolution into a server-safe descriptor view."""

from __future__ import annotations

from typing import Any


_LIST_FIELDS = (
    "bindings",
    "gaps",
    "triggered_conditional_bindings",
    "triggered_conditional_gaps",
)
_DESCRIPTOR_FIELDS = (
    "capability_id",
    "capability_description",
    "descriptor_hash",
)


def server_capability_resolution(value: dict[str, Any]) -> dict[str, Any]:
    """Remove local implementation identity before server persistence."""
    result = {
        key: value[key]
        for key in (
            "node_id",
            "catalog_hash",
            "provider_conformance_hash",
        )
        if key in value
    }
    for key in _LIST_FIELDS:
        result[key] = [
            {
                field: item[field]
                for field in _DESCRIPTOR_FIELDS
                if field in item
            }
            for item in _objects(value.get(key), field=key)
        ]
    result["undetermined_conditions"] = [
        {
            key: item[key]
            for key in ("capability_id", "node_id", "explanation")
            if key in item
        }
        for item in _objects(
            value.get("undetermined_conditions"),
            field="undetermined_conditions",
        )
    ]
    return result


def _objects(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"capability resolution {field} must be an array")
    return value
