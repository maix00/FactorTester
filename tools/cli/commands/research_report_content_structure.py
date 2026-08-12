"""Public authoring rules that distinguish sections from content leaves."""

from __future__ import annotations

from typing import Any


_CONTENT_KINDS = {
    "entry", "list", "table", "image", "code", "math", "result",
}


def validate_titled_chapter_content(
    snapshot: dict[str, Any], operations: list[dict[str, Any]],
) -> None:
    """Reject a titled content leaf masquerading as a report section."""
    kinds = {
        str(item["component_id"]): str(item["kind"])
        for item in snapshot.get("components") or []
        if isinstance(item, dict)
    }
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = operation.get("op")
        if op not in {"add", "replace"}:
            continue
        component_id = str(operation.get("component_id") or "")
        kind = (
            str(operation.get("kind") or "")
            if op == "add" else kinds.get(component_id, "")
        )
        if (
            kind in _CONTENT_KINDS
            and str(operation.get("title") or "").strip()
        ):
            raise ValueError(
                "a content component cannot carry a section title; add a "
                "titled section first and put the untitled content component "
                "inside it"
            )
        if op == "add":
            kinds[component_id] = kind
