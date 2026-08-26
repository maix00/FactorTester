"""Reference-only adapter between Graph packets and generic reports."""

from __future__ import annotations

from copy import deepcopy
import shlex
from typing import Any

from .node_titles import node_title_zh
from .authoring.tree_schema import CONTENT_NODE_KINDS, STRUCTURE_NODE_KINDS


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
    deduped: dict[str, dict[str, Any]] = {}
    for item in tasks:
        ref = item["task_ref"]
        previous = deduped.get(ref)
        if previous is None or (
            "subject_ref" in item and "subject_ref" not in previous
        ):
            deduped[ref] = item
    value["report_packet"] = {
        "document_commands": [
            "factortester research graphs node info <instance> <branch>",
            "factortester research graphs edge info <instance> <branch> <edge-id>",
            "factortester research reports add --profile <profile> --work-package-id <package> --branch-id <branch> --kind chapter|section|subsection|entry|special|list|table|image|code|math|result",
            "factortester research reports asset --profile <profile> --work-package-id <package> --branch-id <branch> --asset-file <json>",
            "factortester research reports manifest --profile <profile> --work-package-id <package> --branch-id <branch>",
            "factortester research reports validate --profile <profile> --work-package-id <package> --branch-id <branch>",
            "factortester research graphs node advance <instance> <branch> --profile-id <profile> --agent-id <agent> --edge-id <edge-id> --evidence-file <file>",
        ],
        "current_node": str(node),
        "required_tasks": list(deduped.values()),
        "data_policy": "Graph carries references and contracts only; load evidence separately",
        "completion_rule": "Every required report task must be covered by the component that declares its report requirement options",
        "component_title_policy": {
            "structure_kinds": list(STRUCTURE_NODE_KINDS),
            "content_kinds": list(CONTENT_NODE_KINDS),
            "rule": (
                "structure nodes require a meaningful subject title; content "
                "components may omit title"
            ),
        },
        "chapter_policy": {
            "mode": "automatic_local_node_entry",
            "anchor": "current Graph node",
            "command": (
                "factortester research workspaces create | "
                "factortester research graphs node advance"
            ),
            "idempotent": True,
            "data_policy": "chapter ownership stays in the current branch Work Package source",
            "branch_policy": (
                "entering a node creates its empty local chapter; Agent prose, "
                "evidence and checkpoint bindings remain explicit"
            ),
        },
        "manifest_contract": {
            "command": (
                "factortester research reports manifest --profile <profile> "
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
        "chapter_title_zh": node_title_zh(node),
        "required": required,
        "suggested_component_kinds": [
            "entry", "list", "table", "image", "code", "math", "result",
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
    report_options = (
        "--report-requirement-id " + ref + " "
        "--report-subject-ref " + subject_ref + " "
        "--report-content-kind <allowed-content-kind>"
    )
    is_obligation_requirement = ref.startswith("report.requirement.")
    if subject_ref.startswith("requirement:"):
        requirement_id = subject_ref.removeprefix("requirement:")
    else:
        requirement_id = ref.removeprefix("report.requirement.")
    title_zh = str(item.get("title_zh") or "").strip()
    if is_obligation_requirement:
        next_command = (
            "factortester research reports add --profile <profile> "
            "--work-package-id <package> --branch-id <branch> "
            "--component-id <component-id> --kind special "
            f"--title {shlex.quote(title_zh or '<short-title-zh>')} "
            "--display-kind obligation_requirement "
            f"--obligation-requirement-id {requirement_id} "
            + report_options
        )
        title_policy = (
            "use the Graph-provided short title_zh for this "
            "obligation_requirement special section"
        )
    else:
        next_command = (
            "factortester research reports add --profile <profile> "
            "--work-package-id <package> --branch-id <branch> "
            "--component-id <component-id> --kind <content-kind> "
            + report_options
        )
        title_policy = (
            "content components may omit --title; structure nodes require a "
            "meaningful subject title"
        )
    task.update({
        "phase": phase,
        "subject_ref": subject_ref,
        "title_zh": title_zh,
        "status": str(item.get("status") or "missing"),
        "allowed_content": list(item.get("allowed_content") or []),
        "next_command": next_command,
        "title_policy": title_policy,
        "report_requirement_options": report_options,
    })
    if is_obligation_requirement:
        task["obligation_requirement_id"] = requirement_id
    return task
