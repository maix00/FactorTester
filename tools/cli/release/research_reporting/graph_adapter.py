"""Reference-only adapter between Graph packets and generic reports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def enrich_graph_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Add actionable report tasks without copying evidence or result data."""
    value = deepcopy(packet)
    node = (value.get("node") or {}).get("node_id") or ""
    tasks: list[dict[str, Any]] = []
    for edge in value.get("candidate_edges") or []:
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("edge_id") or "")
        refs = [
            str(item) for item in (
                edge.get("report_requirement_refs") or []
            ) if isinstance(item, str) and item
        ]
        for ref in refs:
            tasks.append(_task(ref, node, edge_id, required=True))
    for ref in value.get("node_report_requirement_refs") or []:
        if isinstance(ref, str) and ref:
            tasks.append(_task(ref, node, "node", required=True))
    deduped = {item["task_ref"]: item for item in tasks}
    value["report_packet"] = {
        "document_commands": [
            "cycle next <instance> <branch> --report-file <file>",
            "report fork --source-file <file> --output-file <file>",
            "report add --kind chapter|section|subsection|entry|special|table|image",
            "report asset --asset-file <json>",
            "report chip --kind evidence|obligation|task|job|artifact|report_requirement",
            "report manifest --file <file>",
            "report validate-document",
        ],
        "current_node": str(node),
        "required_tasks": list(deduped.values()),
        "data_policy": "Graph carries references and contracts only; load evidence separately",
        "completion_rule": "Every required report task must have a report_requirement chip",
        "chapter_policy": {
            "mode": "automatic_on_cycle_next",
            "anchor": "current Graph node",
            "command": "cycle next --report-file <content-only-report.json>",
            "idempotent": True,
            "data_policy": "chapter ownership stays in the bindings sidecar",
            "branch_policy": (
                "cycle next records branch_ref in sidecar data; content-only "
                "reports may be cloned with report fork"
            ),
        },
        "manifest_contract": {
            "command": "report manifest --file <file>",
            "purpose": "content-free receipt for local report identity",
            "fields": [
                "document_id", "revision", "document_hash",
                "component_refs", "asset_refs", "bindings_hash",
            ],
            "data_policy": "Manifest carries refs and hashes only; report content stays local",
        },
    }
    return value


def validate_report_tasks(packet: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    """Check Graph-declared report tasks against external bindings."""
    required = ((packet.get("report_packet") or {}).get("required_tasks") or [])
    requirements = {
        (str(item.get("target_ref") or ""), str(item.get("kind") or ""))
        for item in bindings.get("bindings") or []
        if isinstance(item, dict)
    }
    missing = [
        item["task_ref"] for item in required
        if (item["task_ref"], "report_requirement") not in requirements
    ]
    return {
        "valid": not missing,
        "required": [item["task_ref"] for item in required],
        "missing": missing,
    }


def _task(ref: str, node: str, edge: str, *, required: bool) -> dict[str, Any]:
    chapter_ref = f"node:{node}" if node else f"edge:{edge}"
    return {
        "task_ref": ref,
        "node_id": node,
        "edge_id": edge,
        "chapter_ref": chapter_ref,
        "chapter_title_zh": _chapter_title(node),
        "required": required,
        "suggested_component_kinds": ["entry", "table", "image"],
        "submission": "attach a report_requirement chip to the completed component",
    }


def _chapter_title(node: str) -> str:
    return {
        "hypothesis_preregistration": "假设登记",
        "data_contract": "数据契约",
        "factor_semantics": "因子语义",
        "validation_design": "验证设计",
        "trial_execution": "试验执行",
        "result_audit": "结果审计",
        "research_decision": "研究决策",
    }.get(node, "研究阶段")
