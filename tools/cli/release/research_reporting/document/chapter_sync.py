"""Idempotent chapter anchors for Graph-driven report authoring."""

from __future__ import annotations

import hashlib
from typing import Any

from .bindings import add_binding, rebind_document, validate_bindings
from .model import add_component, validate_document


_CHAPTER_TITLES = {
    "hypothesis_preregistration": "假设登记",
    "data_contract": "数据契约",
    "factor_semantics": "因子语义",
    "validation_design": "验证设计",
    "trial_execution": "试验执行",
    "result_audit": "结果审计",
    "research_decision": "研究决策",
}


def ensure_report_chapters(
    document: dict[str, Any],
    bindings: dict[str, Any],
    packet: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create missing current-node chapter anchors without touching prose.

    Chapter ownership is recorded in the sidecar binding. The content-only
    document receives only a stable opaque component id and a human title, so
    Graph references never become document metadata.
    """
    current_document = validate_document(document)
    current_bindings = validate_bindings(bindings, current_document)
    anchors = _chapter_anchors(packet)
    created: list[dict[str, str]] = []
    existing: list[dict[str, str]] = []
    for anchor, title, branch_ref in anchors:
        found = _existing_anchor(current_bindings, anchor, branch_ref)
        if found is not None:
            existing.append({"chapter_ref": anchor, "component_id": found})
            continue
        digest_source = f"{branch_ref}|{anchor}" if branch_ref else anchor
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:24]
        component_id = f"chapter-{digest}"
        binding_id = f"chapter-anchor-{digest}"
        current_document = add_component(
            current_document,
            component_id=component_id,
            kind="chapter",
            title=title,
        )
        current_bindings = rebind_document(current_bindings, current_document)
        current_bindings = add_binding(
            current_bindings,
            current_document,
            component_id=component_id,
            binding_id=binding_id,
            kind="graph_reference",
            target_ref=anchor,
            label="章节锚点",
            data=_chapter_binding_data(anchor, branch_ref),
        )
        created.append({"chapter_ref": anchor, "component_id": component_id})
    return current_document, current_bindings, {
        "status": "synchronized",
        "created": created,
        "existing": existing,
        "created_count": len(created),
        "existing_count": len(existing),
    }


def _chapter_anchors(packet: dict[str, Any]) -> list[tuple[str, str, str]]:
    report_packet = packet.get("report_packet") or {}
    scope = packet.get("research_scope") or {}
    branch_ref = str(scope.get("branch_ref") or "").strip()
    tasks = report_packet.get("required_tasks") or []
    values: dict[str, str] = {}
    for item in tasks:
        if not isinstance(item, dict):
            continue
        chapter_ref = str(item.get("chapter_ref") or "").strip()
        if not chapter_ref:
            node_id = str(item.get("node_id") or "").strip()
            chapter_ref = f"node:{node_id}" if node_id else ""
        if not chapter_ref:
            continue
        title = str(item.get("chapter_title_zh") or "").strip()
        values.setdefault(chapter_ref, title or _title_for(chapter_ref))
    if not values:
        node_id = str((packet.get("node") or {}).get("node_id") or "").strip()
        if node_id:
            values[f"node:{node_id}"] = _title_for(f"node:{node_id}")
    return [
        (chapter_ref, title, branch_ref)
        for chapter_ref, title in sorted(values.items())
    ]


def _existing_anchor(
    bindings: dict[str, Any], chapter_ref: str, branch_ref: str,
) -> str | None:
    for item in bindings.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") != "graph_reference":
            continue
        data = item.get("data") or {}
        if data.get("role") != "report_chapter":
            continue
        if data.get("chapter_ref") != chapter_ref:
            continue
        existing_branch_ref = str(data.get("branch_ref") or "")
        if existing_branch_ref != branch_ref:
            continue
        return str(item.get("component_id") or "") or None
    return None


def _chapter_binding_data(chapter_ref: str, branch_ref: str) -> dict[str, str]:
    value = {"role": "report_chapter", "chapter_ref": chapter_ref}
    if branch_ref:
        value["branch_ref"] = branch_ref
    return value


def _title_for(chapter_ref: str) -> str:
    node_id = chapter_ref.removeprefix("node:")
    return _CHAPTER_TITLES.get(node_id, "研究阶段")
