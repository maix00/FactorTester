"""Hash-bound structural facts for one current-node report chapter."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_FIELDS = {
    "schema_version", "chapter_component_id", "report_head_hash",
    "direct_component_count", "direct_special_count",
    "direct_ordinary_component_ids", "structure_hash",
}


def current_chapter_structure(
    snapshot: dict[str, Any],
    *,
    chapter_component_id: str,
) -> dict[str, Any]:
    components = snapshot.get("components")
    head = snapshot.get("head")
    if not isinstance(components, list) or not isinstance(head, dict):
        raise ValueError("report snapshot is invalid")
    chapter = next((
        item for item in components
        if isinstance(item, dict)
        and item.get("component_id") == chapter_component_id
    ), None)
    if chapter is None or chapter.get("kind") != "chapter":
        raise ValueError("current report chapter is missing")
    direct = [
        item for item in components
        if isinstance(item, dict)
        and item.get("parent_id") == chapter_component_id
    ]
    ordinary = sorted(
        str(item.get("component_id") or "")
        for item in direct
        if item.get("kind") != "special"
    )
    value = {
        "schema_version": 1,
        "chapter_component_id": chapter_component_id,
        "report_head_hash": _hash(head),
        "direct_component_count": len(direct),
        "direct_special_count": sum(
            item.get("kind") == "special" for item in direct
        ),
        "direct_ordinary_component_ids": ordinary,
    }
    return {**value, "structure_hash": _hash(value)}


def validate_current_chapter_structure(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("report structure fields are invalid")
    if value.get("schema_version") != 1:
        raise ValueError("report structure schema_version must be 1")
    chapter = str(value.get("chapter_component_id") or "")
    if not chapter:
        raise ValueError("report structure chapter_component_id is required")
    for field in ("report_head_hash", "structure_hash"):
        digest = str(value.get(field) or "")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError(f"report structure {field} must be sha256")
    direct_count = value.get("direct_component_count")
    special_count = value.get("direct_special_count")
    ordinary = value.get("direct_ordinary_component_ids")
    if (
        type(direct_count) is not int
        or type(special_count) is not int
        or direct_count < 0
        or special_count < 0
        or special_count > direct_count
        or not isinstance(ordinary, list)
        or not ordinary
        or not all(isinstance(item, str) and item for item in ordinary)
        or len(ordinary) != direct_count - special_count
    ):
        raise ValueError(
            "current node chapter needs a direct ordinary research section"
        )
    projected = {key: value[key] for key in _FIELDS - {"structure_hash"}}
    if value["structure_hash"] != _hash(projected):
        raise ValueError("report structure hash mismatch")
    return dict(value)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()).hexdigest()
