"""Stable graph identity and protocol validation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

_LIFECYCLES = {"observed", "draft", "active", "retired"}
_ENFORCEMENTS = {"advisory", "deterministic", "audited"}
_EDGE_TYPES = {"recommended", "conditional", "failure", "recovery"}
_RISK_LEVELS = {"L1", "L2", "L3", "L4"}
_SERVER_ACTIONS = {
    "bind_data_availability",
    "bind_factor_semantics",
    "bind_job_attempt",
    "start_new_hypothesis_lineage",
}


def graph_content_hash(graph: dict[str, Any]) -> str:
    """Return the stable SHA-256 identity of a graph without self-reference."""
    payload = deepcopy(graph)
    payload.pop("content_hash", None)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Validate the public graph protocol and return an isolated copy."""
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    if int(graph.get("schema_version") or 0) != 1:
        raise ValueError("unsupported graph schema_version")
    if str(graph.get("lifecycle") or "") not in _LIFECYCLES:
        raise ValueError("invalid graph lifecycle")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not all(isinstance(item, dict) for item in nodes):
        raise ValueError("graph nodes must be an array of objects")
    if not isinstance(edges, list) or not all(isinstance(item, dict) for item in edges):
        raise ValueError("graph edges must be an array of objects")

    node_ids = [str(item.get("node_id") or "").strip() for item in nodes]
    if any(not node_id for node_id in node_ids):
        raise ValueError("every graph node requires node_id")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("graph node ids must be unique")
    for node in nodes:
        if str(node.get("enforcement") or "") not in _ENFORCEMENTS:
            raise ValueError(f"invalid node enforcement: {node.get('node_id')}")
        capabilities = node.get("required_capabilities")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise ValueError(
                f"required_capabilities must contain capability ids: "
                f"{node.get('node_id')}"
            )
        conditional = node.get("conditional_capabilities", [])
        if not isinstance(conditional, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("capability_id"), str)
            and bool(item["capability_id"].strip())
            and isinstance(item.get("predicate"), dict)
            and isinstance(item.get("explanation"), str)
            and bool(item["explanation"].strip())
            for item in conditional
        ):
            raise ValueError(
                "conditional_capabilities require id, predicate, explanation: "
                f"{node.get('node_id')}"
            )

    edge_ids = [str(item.get("edge_id") or "").strip() for item in edges]
    if any(not edge_id for edge_id in edge_ids):
        raise ValueError("every graph edge requires edge_id")
    if len(set(edge_ids)) != len(edge_ids):
        raise ValueError("graph edge ids must be unique")
    declared_nodes = set(node_ids)
    for edge in edges:
        edge_id = str(edge["edge_id"])
        for endpoint in ("from_node", "to_node"):
            value = str(edge.get(endpoint) or "").strip()
            if endpoint == "from_node" and value == "*":
                continue
            if value not in declared_nodes:
                raise ValueError(
                    f"edge {edge_id} references unknown node {value!r}"
                )
        if str(edge.get("edge_type") or "") not in _EDGE_TYPES:
            raise ValueError(f"invalid edge_type: {edge_id}")
        if str(edge.get("risk_level") or "") not in _RISK_LEVELS:
            raise ValueError(f"invalid risk_level: {edge_id}")
        server_action = edge.get("server_action")
        if (
            server_action is not None
            and str(server_action) not in _SERVER_ACTIONS
        ):
            raise ValueError(f"invalid server_action: {edge_id}")
        for field in (
            "required_evidence",
            "required_research_evidence",
            "required_transition_facts",
        ):
            items = edge.get(field, [])
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item.strip() for item in items
            ):
                raise ValueError(
                    f"{field} must contain text requirements: {edge_id}"
                )
        if (
            "required_research_evidence" in edge
            or "required_transition_facts" in edge
        ):
            typed = [
                *(edge.get("required_research_evidence") or []),
                *(edge.get("required_transition_facts") or []),
            ]
            if list(edge.get("required_evidence") or []) != typed:
                raise ValueError(
                    "typed edge requirements must match required_evidence: "
                    f"{edge_id}"
                )
    operation_ids: set[str] = set()
    for field in ("research_cycle_operations", "maintenance_operations"):
        operations = graph.get(field, [])
        if not isinstance(operations, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("capability_id"), str)
            and bool(item["capability_id"].strip())
            and isinstance(item.get("output_kind"), str)
            and bool(item["output_kind"].strip())
            for item in operations
        ):
            raise ValueError(
                f"{field} requires capability_id and output_kind"
            )
        for item in operations:
            capability_id = str(item["capability_id"])
            if capability_id in operation_ids:
                raise ValueError(
                    f"duplicate graph-governed operation: {capability_id}"
                )
            operation_ids.add(capability_id)
    if operation_ids & (set(node_ids) | set(edge_ids)):
        raise ValueError("graph-governed operations are not nodes or edges")
    review_policy = graph.get("review_policy", {})
    if not isinstance(review_policy, dict) or not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
        for key, value in review_policy.items()
    ):
        raise ValueError("review_policy must contain text rules")
    descriptors = graph.get("capability_descriptors")
    if str(graph.get("lifecycle") or "") in {"draft", "active"}:
        if not isinstance(descriptors, dict):
            raise ValueError(
                "draft/active graph requires capability_descriptors"
            )
        used_capabilities = {
            str(capability_id)
            for node in nodes
            for capability_id in node.get("required_capabilities") or []
        } | {
            str(item["capability_id"])
            for node in nodes
            for item in node.get("conditional_capabilities") or []
        } | {
            str(capability_id)
            for edge in edges
            for capability_id in edge.get("required_capabilities") or []
        } | operation_ids
        missing_descriptors = sorted(
            used_capabilities - set(descriptors)
        )
        if missing_descriptors:
            raise ValueError(
                "capability descriptors missing: "
                + ", ".join(missing_descriptors)
            )
        for capability_id, descriptor in descriptors.items():
            if not isinstance(descriptor, dict):
                raise ValueError(
                    f"invalid capability descriptor: {capability_id}"
                )
            description = descriptor.get("capability_description")
            descriptor_hash = descriptor.get("descriptor_hash")
            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"capability description is required: {capability_id}"
                )
            if not isinstance(descriptor_hash, str) or (
                len(descriptor_hash) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in descriptor_hash
                )
            ):
                raise ValueError(
                    f"invalid capability descriptor hash: {capability_id}"
                )
    return deepcopy(graph)
