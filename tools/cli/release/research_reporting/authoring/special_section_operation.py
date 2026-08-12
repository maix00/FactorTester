"""One construction path for semantic report special sections."""

from __future__ import annotations

from typing import Any


def add_section_operation(
    *,
    component_id: str,
    title: str,
    parent_id: str,
    display_kind: str = "",
    body: str = "",
    content: Any = None,
    bindings: list[dict[str, Any]] | None = None,
    kind: str = "section",
) -> dict[str, Any]:
    """Build one report-tree section through the shared operation shape."""
    if kind not in {"section", "special"}:
        raise ValueError("report section kind must be section or special")
    return {
        "op": "add",
        "component_id": component_id,
        "kind": kind,
        "title": title,
        "parent_id": parent_id,
        "body": body,
        "content": content,
        "display_kind": display_kind,
        "bindings": list(bindings or []),
    }


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
    return add_section_operation(
        component_id=component_id,
        title=title,
        parent_id=parent_id,
        body=body,
        content=content,
        display_kind=display_kind,
        bindings=bindings,
        kind="special",
    )
