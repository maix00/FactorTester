"""Public authoring rules that distinguish sections from content leaves."""

from __future__ import annotations

from typing import Any


_CONTENT_KINDS = {
    "entry", "list", "table", "image", "code", "math", "result",
}


def validate_titled_chapter_content(
    snapshot: dict[str, Any], operations: list[dict[str, Any]],
) -> None:
    """Reject a titled content leaf masquerading as a chapter subsection."""
    kinds = {
        str(item["component_id"]): str(item["kind"])
        for item in snapshot.get("components") or []
        if isinstance(item, dict)
    }
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") != "add":
            continue
        component_id = str(operation.get("component_id") or "")
        kind = str(operation.get("kind") or "")
        parent_id = str(operation.get("parent_id") or "root")
        if (
            kinds.get(parent_id) == "chapter"
            and kind in _CONTENT_KINDS
            and str(operation.get("title") or "").strip()
        ):
            raise ValueError(
                "a titled chapter child must be a section; add the titled "
                "section first and put an untitled content component inside it"
            )
        kinds[component_id] = kind
