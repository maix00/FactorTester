"""Build one bounded narrative from additive current-node report items."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .carrier import MAX_ITEMS
from .section_binding import item_chapter_ref, section_role


def narrative(items: list[dict[str, Any]], *, recorded_at: float, current_node: str) -> dict[str, Any]:
    groups: dict[str, list[list[dict[str, Any]]]] = {}
    for item in items:
        chapter_ref = item_chapter_ref(item, current_node=current_node)
        chunks = groups.setdefault(chapter_ref, [[]])
        candidate = {str(link.get("link_id") or "") for link in item.get("links") or []}
        occupied = {str(link.get("link_id") or "") for prior in chunks[-1] for link in prior.get("links") or []}
        if len(chunks[-1]) >= MAX_ITEMS or occupied.intersection(candidate):
            chunks.append([])
        chunks[-1].append(item)
    sections = []
    for chapter_index, (chapter_ref, chunks) in enumerate(groups.items()):
        for chunk_index, values in enumerate(chunks):
            sections.append(_section(
                chapter_ref, values, chapter_index, chunk_index,
            ))
    return {
        "schema_version": 3, "language": "zh-Hans", "title": "当前节点研究记录",
        "research_occurred_at": recorded_at, "time_basis": "transition",
        "time_source_refs": [], "sections": sections,
    }


def _section(chapter_ref: str, items: list[dict[str, Any]], chapter_index: int, chunk_index: int) -> dict[str, Any]:
    blocks, links = [], []
    for item in items:
        content = deepcopy(item["content"])
        content["report_binding"] = deepcopy(item["report_binding"])
        blocks.append(content)
        links.extend(deepcopy(item.get("links") or []))
    key = hashlib.sha256(json.dumps({
        "chapter_ref": chapter_ref,
        "items": [{
            "report_requirement_id": item["report_requirement_id"],
            "subject_ref": item["subject_ref"], "item_hash": item["item_hash"],
        } for item in items],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return {
        "section_id": f"current-node-{key}", "title": _title(items, chapter_index),
        "chapter_ref": chapter_ref,
        "section_role": section_role(items) if chunk_index == 0 else "node_report_items",
        "blocks": blocks, "links": links,
    }


def _title(items: list[dict[str, Any]], item_index: int) -> str:
    actions = [item for item in items if str(item.get("report_requirement_id") or "").startswith("report.node.") and str(item.get("report_requirement_id") or "").endswith(".action")]
    item = (actions or items)[0]
    title = str(item.get("title_zh") or "").strip()
    if title:
        return title
    rows = (item.get("content") or {}).get("rows") if isinstance(item.get("content"), dict) else None
    first = str((rows or [{}])[0].get("text") or "").strip()
    for separator in ("。", "；", "："):
        first = first.split(separator, 1)[0]
    return first[:43].rstrip() + "…" if len(first) > 44 else first or f"当前节点研究记录 {item_index + 1}"
