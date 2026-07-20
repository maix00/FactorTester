"""Pure, non-mutating replay of research graph traces."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .graph import validate_graph
from .server_guards import derive_server_guard_facts


def replay_graph_trace(
    graph: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    """Replay recorded decisions without running jobs, Skills, or commands."""
    graph_value = validate_graph(graph)
    trace_value = deepcopy(trace)
    source = deepcopy(trace_value.get("source") or {})
    entry_node = str(
        graph_value.get("entry_node")
        or ((graph_value.get("nodes") or [{}])[0].get("node_id") or "")
    )
    nodes = {
        str(item.get("node_id") or ""): item
        for item in graph_value.get("nodes") or []
    }
    edges = {
        str(item.get("edge_id") or ""): item
        for item in graph_value.get("edges") or []
    }
    branches: dict[str, dict[str, str]] = {
        "primary": {
            "current_node": entry_node,
            "status": "running",
        }
    }
    covered_nodes = [entry_node]
    covered_edges: list[str] = []
    errors: list[str] = []
    for index, event in enumerate(trace_value.get("events") or []):
        if not isinstance(event, dict):
            errors.append(f"event {index} must be an object")
            break
        event_type = str(event.get("type") or "")
        branch_id = str(event.get("branch_id") or "primary")
        if event_type == "fork":
            source_branch_id = str(
                event.get("source_branch_id") or "primary"
            )
            source_branch = branches.get(source_branch_id)
            if source_branch is None:
                errors.append(
                    f"event {index}: source branch not found: "
                    f"{source_branch_id}"
                )
                break
            branches[branch_id] = deepcopy(source_branch)
            continue
        if event_type != "transition":
            errors.append(f"event {index}: unsupported type {event_type!r}")
            break
        branch = branches.get(branch_id)
        if branch is None:
            errors.append(f"event {index}: branch not found: {branch_id}")
            break
        edge_id = str(event.get("edge_id") or "")
        edge = edges.get(edge_id)
        if edge is None:
            errors.append(f"event {index}: edge not found: {edge_id}")
            break
        edge_from = str(edge.get("from_node") or "")
        if edge_from not in {branch["current_node"], "*"}:
            errors.append(
                f"event {index}: edge {edge_id} does not leave "
                f"{branch['current_node']}"
            )
            break
        if branch["status"] == "paused" and edge.get("edge_type") != "recovery":
            errors.append(
                f"event {index}: paused branch requires recovery edge"
            )
            break
        evidence = event.get("evidence") or {}
        if not isinstance(evidence, dict):
            errors.append(f"event {index}: evidence must be an object")
            break
        try:
            guard_evidence = {
                **evidence,
                **derive_server_guard_facts(edge, evidence),
            }
        except ValueError as exc:
            errors.append(f"event {index}: invalid server evidence: {exc}")
            break
        failed_guards = [
            key for key, expected in (edge.get("guard") or {}).items()
            if guard_evidence.get(key) != expected
        ]
        if failed_guards:
            errors.append(
                f"event {index}: unsatisfied guards: "
                + ", ".join(failed_guards)
            )
            break
        if edge.get("required_evidence") and not (
            evidence.get("evidence_refs") or []
        ):
            errors.append(f"event {index}: evidence_refs required")
            break
        target_id = str(edge.get("to_node") or "")
        target = nodes.get(target_id)
        if target is None:
            errors.append(f"event {index}: target node not found: {target_id}")
            break
        branch["current_node"] = target_id
        branch["status"] = (
            "paused"
            if target.get("kind") == "capability_gap"
            or target_id == "code_improvement_required"
            else "running"
        )
        covered_edges.append(edge_id)
        if target_id not in covered_nodes:
            covered_nodes.append(target_id)
    expected = str(source.get("expected_outcome") or "complete")
    expected_block = (
        expected == "expected_block"
        and not errors
        and any(item["status"] == "paused" for item in branches.values())
    )
    status = (
        "failed"
        if errors
        else "expected_block"
        if expected_block
        else "complete"
    )
    return {
        "graph_ref": (
            f"{graph_value.get('graph_id')}@v{graph_value.get('version')}"
        ),
        "status": status,
        "source": source,
        "branches": branches,
        "coverage": {
            "node_ids": covered_nodes,
            "edge_ids": covered_edges,
            "node_ratio": (
                len(covered_nodes) / len(nodes) if nodes else 0.0
            ),
            "edge_ratio": (
                len(set(covered_edges)) / len(edges) if edges else 0.0
            ),
        },
        "errors": errors,
        "external_mutations": 0,
    }
