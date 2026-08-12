"""Stable semantic placement for local research-report sections."""

from __future__ import annotations

from typing import Any


def item_chapter_ref(
    item: dict[str, Any], *, current_node: str,
) -> str:
    """Return the Graph node that owns one report item.

    New producers persist ``chapter_ref`` explicitly.  The deterministic
    fallbacks keep already-authored projections usable without inspecting
    Chinese prose or UUID-shaped object identities.
    """
    explicit = str(item.get("chapter_ref") or "")
    if explicit.startswith("node:") and len(explicit) > len("node:"):
        return explicit
    subject = str(item.get("subject_ref") or "")
    if subject.startswith("node:"):
        return subject
    report_id = str(item.get("report_requirement_id") or "")
    if report_id.startswith("report.node."):
        node_id = report_id.removeprefix("report.node.").split(".", 1)[0]
        if node_id:
            return f"node:{node_id}"
    if report_id.startswith("report.edge."):
        edge_id = report_id.removeprefix("report.edge.")
        source = edge_id.split("__", 1)[0]
        if source:
            return f"node:{source}"
    return f"node:{current_node}"


def section_role(items: list[dict[str, Any]]) -> str:
    report_ids = {
        str(item.get("report_requirement_id") or "") for item in items
    }
    if any(item.endswith(".entry") for item in report_ids):
        return "node_entry"
    return "node_report_items"
