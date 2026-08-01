"""One construction path for semantic report special sections."""

from __future__ import annotations

from typing import Any


def add_special_section_operation(
    *,
    component_id: str,
    title: str,
    parent_id: str,
    display_kind: str,
    body: str = "",
    content: Any = None,
    bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a normal report-tree add operation with special semantics.

    ``display_kind`` labels presentation and workflow policy only. The node is
    still written, validated and committed by the shared report-tree batch.
    """
    return {
        "op": "add",
        "component_id": component_id,
        "kind": "special",
        "title": title,
        "parent_id": parent_id,
        "body": body,
        "content": content,
        "display_kind": display_kind,
        "bindings": list(bindings or []),
    }
