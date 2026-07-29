"""Reference-only adapter between Graph packets and generic reports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def enrich_graph_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Add actionable report tasks without copying evidence or result data."""
    value = deepcopy(packet)
    node = (value.get("node") or {}).get("node_id") or ""
    tasks: list[dict[str, Any]] = []
    report_contract = value.get("report_requirements") or {}
    current = report_contract.get("current_node") or {}
    for phase in ("on_entry", "on_exit"):
        for item in current.get(phase) or []:
            if isinstance(item, dict):
                tasks.append(_requirement_task(item, node, phase=phase))
    for edge_id, rows in (report_contract.get("candidate_edges") or {}).items():
        for item in rows or []:
            if isinstance(item, dict):
                tasks.append(_requirement_task(
                    item,
                    node,
                    edge_id=str(edge_id),
                    phase=str(item.get("phase") or "edge"),
                ))
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
            "factortester node info <instance> <branch>",
            "factortester edge info <instance> <branch> <edge-id>",
            "factortester report add --profile <profile> --work-package-id <package> --branch-id <branch> --kind chapter|section|subsection|entry|special|table|image|code|math|result",
            "factortester report asset --profile <profile> --work-package-id <package> --branch-id <branch> --asset-file <json>",
            "factortester report manifest --profile <profile> --work-package-id <package> --branch-id <branch>",
            "factortester report validate --profile <profile> --work-package-id <package> --branch-id <branch>",
            "factortester node advance <instance> <branch> --profile-id <profile> --agent-id <agent> --edge-id <edge-id> --evidence-file <file>",
        ],
        "current_node": str(node),
        "required_tasks": list(deduped.values()),
        "data_policy": "Graph carries references and contracts only; load evidence separately",
        "completion_rule": "Every required report task must be covered by the component that declares its report requirement options",
        "chapter_policy": {
            "mode": "automatic_local_node_entry",
            "anchor": "current Graph node",
            "command": "factortester client research create|node advance",
            "idempotent": True,
            "data_policy": "chapter ownership stays in the current branch Work Package source",
            "branch_policy": (
                "entering a node creates its empty local chapter; Agent prose, "
                "evidence and checkpoint bindings remain explicit"
            ),
        },
        "manifest_contract": {
            "command": (
                "factortester report manifest --profile <profile> "
                "--work-package-id <package> --branch-id <branch>"
            ),
            "purpose": "content-free receipt for local report identity",
            "fields": [
                "document_id", "revision", "document_hash",
                "component_refs", "asset_refs", "bindings_hash",
            ],
            "data_policy": "Manifest carries refs and hashes only; report content stays local",
        },
    }
    if value.get("next_actions"):
        value["report_packet"]["next_action"] = value["next_actions"][0]
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
        "suggested_component_kinds": [
            "entry", "table", "image", "code", "math", "result",
        ],
        "submission": "add the completed component with its report requirement options",
    }


def _requirement_task(
    item: dict[str, Any],
    node: str,
    *,
    phase: str,
    edge_id: str = "",
) -> dict[str, Any]:
    """Translate the server report contract into one actionable task."""
    ref = str(item.get("report_requirement_id") or "")
    subject_ref = str(item.get("subject_ref") or "")
    task = _task(ref, node, edge_id or "node", required=True)
    task.update({
        "phase": phase,
        "subject_ref": subject_ref,
        "status": str(item.get("status") or "missing"),
        "allowed_content": list(item.get("allowed_content") or []),
        "next_command": (
            "factortester report add --profile <profile> "
            "--work-package-id <package> --branch-id <branch> "
            "--component-id <component-id> --kind <kind> --title <title>"
        ),
        "report_requirement_options": (
            "--report-requirement-id " + ref + " "
            "--report-subject-ref " + subject_ref + " "
            "--report-content-kind <allowed-content-kind>"
        ),
    })
    return task


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
