"""Assemble the product-neutral Draft Graph."""

from __future__ import annotations

from typing import Any

from .capabilities import capability_descriptor, load_builtin_capability_registry
from .draft_graph_edges import build_draft_edges
from .draft_graph_cycle import (
    maintenance_operations,
    research_cycle_operations,
    review_policy,
)
from .draft_graph_nodes import build_draft_nodes
from .graph_protocol import graph_content_hash, validate_graph


def build_draft_graph() -> dict[str, Any]:
    """Build the candidate Active Graph without product-specific topology."""
    nodes = build_draft_nodes()
    edges = build_draft_edges()
    graph = {
        "schema_version": 1,
        "graph_id": "factor-research",
        "version": 6,
        "lifecycle": "draft",
        "parent_version": 5,
        "research_semantics": "product_neutral",
        "entry_node": "hypothesis_preregistration",
        "nodes": nodes,
        "edges": edges,
        "research_cycle_operations": research_cycle_operations(),
        "maintenance_operations": maintenance_operations(),
        "review_policy": review_policy(),
        "provenance": {
            "source": "observed-harness-plus-reviewed-industry-semantics",
            "description": (
                "Candidate graph with server-derived transition evidence. "
                "Product support is resolved through capability bindings and "
                "does not define the graph topology."
            ),
        },
    }
    registry = load_builtin_capability_registry()
    contracts = {
        str(item["capability_id"]): item
        for item in registry["capabilities"]
    }
    capability_ids = {
        str(capability_id)
        for node in nodes
        for capability_id in node.get("required_capabilities") or []
    } | {
        str(item["capability_id"])
        for node in nodes
        for item in node.get("conditional_capabilities") or []
    } | {
        str(capability_id)
        for item in edges
        for capability_id in item.get("required_capabilities") or []
    } | {
        str(item["capability_id"])
        for item in [
            *graph["research_cycle_operations"],
            *graph["maintenance_operations"],
        ]
    }
    graph["capability_descriptors"] = {
        capability_id: capability_descriptor(contracts[capability_id])
        for capability_id in sorted(capability_ids)
    }
    graph = validate_graph(graph)
    graph["content_hash"] = graph_content_hash(graph)
    return graph
