"""Offline Research Graph navigation for the client CLI.

The Manager may provide a graph version and persist branch state, but it does
not decide which edge an Agent should take.  This module is intentionally
free of HTTP, database, token, and packet-size concerns so the same semantic
decision can be used by a local Agent or by the Swift client.
"""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence
from typing import Any


def evaluate_next(
    graph: Mapping[str, Any],
    *,
    current_node: str,
    capabilities: Sequence[str] = (),
    evidence: Sequence[str] = (),
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic local edge readiness for one graph node.

    ``capabilities`` and ``evidence`` are caller-owned local facts.  Missing
    facts block an edge; the function never calls a server to resolve them.
    Guards use the small equality/presence vocabulary already accepted by the
    graph protocol.  Unknown guard shapes are reported as a blocker rather
    than silently treated as true.
    """
    graph_value = deepcopy(dict(graph))
    node_id = str(current_node or "").strip()
    if not node_id:
        raise ValueError("current_node is required")
    nodes = {
        str(item.get("node_id") or ""): item
        for item in graph_value.get("nodes") or []
        if isinstance(item, Mapping)
    }
    if node_id not in nodes:
        raise ValueError(f"graph node not found: {node_id}")
    known_capabilities = {str(value) for value in capabilities if str(value)}
    known_evidence = {str(value) for value in evidence if str(value)}
    fact_values = facts if isinstance(facts, Mapping) else {}
    candidates = []
    for edge in graph_value.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("from_node") or "")
        if source not in {node_id, "*"}:
            continue
        candidates.append(_edge_result(
            edge,
            capabilities=known_capabilities,
            evidence=known_evidence,
            facts=fact_values,
        ))
    recommended = [
        str(item["edge_id"])
        for item in candidates
        if item["readiness"] == "ready"
    ]
    return {
        "graph": _graph_ref(graph_value),
        "current_node": node_id,
        "node": {
            "node_id": node_id,
            "kind": str(nodes[node_id].get("kind") or ""),
            "purpose": str(nodes[node_id].get("purpose") or ""),
        },
        "candidate_edges": candidates,
        "recommended_edge_ids": recommended if len(recommended) == 1 else [],
        "requires_agent_judgment": len(recommended) != 1,
        "next_actions": _next_actions(candidates, recommended),
        "server_decides_next": False,
    }


def _edge_result(
    edge: Mapping[str, Any],
    *,
    capabilities: set[str],
    evidence: set[str],
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id") or "")
    blockers: list[dict[str, Any]] = []
    required_capabilities = _text_list(edge.get("required_capabilities"))
    missing_capabilities = sorted(set(required_capabilities) - capabilities)
    if missing_capabilities:
        blockers.append({
            "code": "missing_capabilities",
            "values": missing_capabilities,
        })
    required_evidence = _text_list(
        edge.get("required_evidence")
        or edge.get("required_research_evidence")
        or edge.get("required_transition_facts")
    )
    missing_evidence = sorted(set(required_evidence) - evidence)
    if missing_evidence:
        blockers.append({
            "code": "missing_evidence",
            "values": missing_evidence,
        })
    guard = edge.get("guard")
    if guard is not None:
        passed, detail = _guard_result(guard, facts)
        if not passed:
            blockers.append({"code": "guard_not_satisfied", "detail": detail})
    readiness = "blocked" if blockers else "ready"
    return {
        "edge_id": edge_id,
        "to_node": str(edge.get("to_node") or ""),
        "edge_type": str(edge.get("edge_type") or ""),
        "risk_level": str(edge.get("risk_level") or ""),
        "readiness": readiness,
        "blockers": blockers,
        "required_capabilities": required_capabilities,
        "required_evidence": required_evidence,
    }


def _guard_result(guard: Any, facts: Mapping[str, Any]) -> tuple[bool, str]:
    if not isinstance(guard, Mapping):
        return False, "guard must be an object"
    if not guard:
        return True, ""
    if "all" in guard:
        values = guard["all"]
        if not isinstance(values, list):
            return False, "guard.all must be an array"
        results = [_guard_result(item, facts) for item in values]
        failed = [detail for passed, detail in results if not passed]
        return (not failed), "; ".join(failed)
    if "any" in guard:
        values = guard["any"]
        if not isinstance(values, list):
            return False, "guard.any must be an array"
        results = [_guard_result(item, facts) for item in values]
        if any(passed for passed, _ in results):
            return True, ""
        return False, "; ".join(detail for _, detail in results)
    path = guard.get("path") or guard.get("field")
    if not isinstance(path, str) or not path:
        return False, "guard requires path/field"
    actual = facts
    for part in path.split("."):
        if not isinstance(actual, Mapping) or part not in actual:
            actual = None
            break
        actual = actual[part]
    if "equals" in guard:
        return actual == guard["equals"], f"{path} == {guard['equals']!r}"
    if "in" in guard:
        allowed = guard["in"]
        return (
            isinstance(allowed, list) and actual in allowed,
            f"{path} in {allowed!r}",
        )
    if guard.get("present") is True:
        return actual is not None, f"{path} is present"
    return False, "guard requires equals, in, or present"


def _next_actions(
    candidates: list[dict[str, Any]],
    recommended: list[str],
) -> list[dict[str, Any]]:
    if not candidates:
        return [{
            "action_id": "graph.inspect",
            "kind": "inspect",
            "blocking": True,
            "reason": "当前节点没有可用的 Edge",
            "local": True,
        }]
    if len(recommended) == 1:
        return [{
            "action_id": "edge.choose",
            "kind": "edge",
            "blocking": False,
            "edge_id": recommended[0],
            "reason": "本地事实已满足唯一候选 Edge",
            "local": True,
        }]
    return [{
        "action_id": "edge.review",
        "kind": "edge",
        "blocking": not bool(recommended),
        "edge_ids": [str(item["edge_id"]) for item in candidates],
        "reason": "需要本地 Agent 选择候选 Edge 或补充事实",
        "local": True,
    }]


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _graph_ref(graph: Mapping[str, Any]) -> str:
    graph_id = str(graph.get("graph_id") or "")
    version = str(graph.get("version") or "")
    return f"{graph_id}@v{version}" if graph_id and version else graph_id
