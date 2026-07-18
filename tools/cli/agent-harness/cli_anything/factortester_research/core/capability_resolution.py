"""Node-local capability resolution with bounded predicates and caching."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .capability_bindings import resolve_capability_ids
from .capability_predicates import evaluate_capability_predicate
from .capability_registry import canonical_hash, validate_capability_registry
from .capability_sources import candidate_source_states


_RESOLUTION_CACHE: dict[str, dict[str, Any]] = {}


def _semantic_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Remove runtime identity that must not alter deterministic semantics."""
    value = deepcopy(facts)
    runtime = value.get("runtime")
    if isinstance(runtime, dict):
        for key in ("model_id", "model_provider", "codex_version"):
            runtime.pop(key, None)
        if not runtime:
            value.pop("runtime", None)
    return value


def resolve_graph_capabilities(
    graph: dict[str, Any],
    registry: dict[str, Any],
    *,
    product_group: str,
    approved_implementation_ids: set[str] | None = None,
    node_id: str | None = None,
    facts: dict[str, Any] | None = None,
    triggered_capability_ids: set[str] | None = None,
    include_all: bool = False,
) -> dict[str, Any]:
    """Resolve only the current node unless full activation audit is explicit."""
    catalog = validate_capability_registry(registry)
    contracts = {
        str(item["capability_id"]): item
        for item in catalog["capabilities"]
    }
    grants = set(approved_implementation_ids or set())
    nodes = graph.get("nodes") or []
    selected_node_id = node_id or str(graph.get("entry_node") or "")
    if not selected_node_id and nodes:
        selected_node_id = str(nodes[0].get("node_id") or "")
    if include_all:
        selected_nodes = list(nodes)
        resolution_scope = "activation_audit"
    else:
        selected_nodes = [
            node for node in nodes
            if str(node.get("node_id") or "") == selected_node_id
        ]
        if not selected_nodes:
            raise ValueError(f"unknown graph node: {selected_node_id}")
        resolution_scope = "current_node"
    semantic_fact_payload = _semantic_facts(facts or {})
    explicit_triggers = set(triggered_capability_ids or set())
    required_ids = [
        capability_id
        for node in selected_nodes
        for capability_id in node.get("required_capabilities") or []
    ]
    edge_ids = [
        capability_id
        for edge in graph.get("edges") or []
        if include_all or str(edge.get("from_node") or "") in {
            selected_node_id,
            "*",
        }
        for capability_id in edge.get("required_capabilities") or []
    ]
    triggered_specs, undetermined_specs = _conditional_specs(
        selected_nodes,
        facts=semantic_fact_payload,
        explicit_triggers=explicit_triggers,
    )
    all_selected_ids = (
        required_ids
        + edge_ids
        + [item["capability_id"] for item in triggered_specs]
    )
    source_states = candidate_source_states(
        capability_ids=all_selected_ids,
        contracts=contracts,
        catalog=catalog,
        product_group=product_group,
    )
    semantic_cache_key = canonical_hash({
        "graph": graph,
        "catalog": catalog,
        "product_group": product_group,
        "grants": sorted(grants),
        "selected_node_id": selected_node_id,
        "facts": semantic_fact_payload,
        "explicit_triggers": sorted(explicit_triggers),
        "include_all": include_all,
        "source_states": source_states,
    })
    cached = _RESOLUTION_CACHE.get(semantic_cache_key)
    if cached is not None:
        result = deepcopy(cached)
        result["cache"]["hit"] = True
        return result
    required_by = "all_graph_nodes" if include_all else selected_node_id
    bindings, gaps = resolve_capability_ids(
        capability_ids=required_ids + edge_ids,
        contracts=contracts,
        product_group=product_group,
        grants=grants,
        required_by=required_by,
        source_states=source_states,
    )
    conditional_bindings, conditional_gaps = resolve_capability_ids(
        capability_ids=[
            item["capability_id"] for item in triggered_specs
        ],
        contracts=contracts,
        product_group=product_group,
        grants=grants,
        required_by=selected_node_id,
        source_states=source_states,
    )
    result = {
        "catalog_id": str(catalog.get("catalog_id") or ""),
        "catalog_hash": canonical_hash(catalog),
        "provider_conformance_hash": canonical_hash(source_states),
        "product_group": product_group,
        "scope": resolution_scope,
        "node_id": selected_node_id,
        "bindings": bindings,
        "gaps": gaps,
        "triggered_conditional_bindings": conditional_bindings,
        "triggered_conditional_gaps": conditional_gaps,
        "undetermined_conditions": undetermined_specs,
        "requires_agent_judgment": bool(undetermined_specs),
        "semantic_cache_key": semantic_cache_key,
        "cache": {
            "key": semantic_cache_key,
            "hit": False,
            "scope": "process",
        },
    }
    _RESOLUTION_CACHE[semantic_cache_key] = deepcopy(result)
    return result


def _conditional_specs(
    nodes: list[dict[str, Any]],
    *,
    facts: dict[str, Any],
    explicit_triggers: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    triggered: list[dict[str, Any]] = []
    undetermined: list[dict[str, Any]] = []
    for node in nodes:
        for item in node.get("conditional_capabilities") or []:
            capability_id = str(item["capability_id"])
            outcome = (
                True
                if capability_id in explicit_triggers
                else evaluate_capability_predicate(
                    item.get("predicate") or {},
                    facts,
                )
            )
            compact = {
                "capability_id": capability_id,
                "node_id": str(node.get("node_id") or ""),
                "explanation": str(
                    item.get("explanation") or item.get("when") or ""
                ),
            }
            if outcome is True:
                triggered.append(compact)
            elif outcome is None:
                undetermined.append(compact)
    return triggered, undetermined
