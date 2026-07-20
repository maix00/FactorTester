"""Server-derived token evidence for one bounded shadow comparison."""

from __future__ import annotations

from typing import Any

from server.services import agent_flow


def derive_token_metrics(
    *,
    owner: str,
    instance_id: str,
    graph_run_id: str,
    baseline_run_id: str,
    run_spec_hash: str,
    graph: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    graph_scope = f"instance:{instance_id}"
    baseline_scope = f"research-run:{baseline_run_id}"
    store = agent_flow.get_store()
    graph_period = store.load_current_budget_period(
        owner_user_id=owner,
        agent_id=graph_scope,
    )
    baseline_period = store.load_current_budget_period(
        owner_user_id=owner,
        agent_id=baseline_scope,
    )
    if graph_period is None or baseline_period is None:
        raise ValueError("Graph and baseline Agent budget periods are required")
    node = next(
        (
            item for item in graph.get("nodes") or []
            if str(item.get("node_id") or "")
            == str((context.get("node") or {}).get("node_id") or "")
        ),
        {},
    )
    allowed_gaps = set(node.get("required_capabilities") or []) | {
        str(item.get("capability_id") or "")
        for item in node.get("conditional_capabilities") or []
    }
    future_gaps = (
        0
        if node.get("kind") == "capability_gap"
        else sum(
            str(item.get("capability_id") or "") not in allowed_gaps
            for item in context.get("open_gaps") or []
            if isinstance(item, dict)
        )
    )
    return {
        "routine_context_bytes": int(context["context_bytes"]),
        "full_graph_loaded_for_routine": any(
            key in context for key in (
                "nodes", "edges", "capability_descriptors",
                "capability_contracts",
            )
        ),
        "untriggered_conditionals_in_context": len(
            context.get("conditional_capabilities") or []
        ),
        "future_node_gaps_blocked": future_gaps,
        "routine_subagent_count": store.count_subagent_invocations(
            owner_user_id=owner,
            agent_id=graph_scope,
        ),
        "shadow_graph_total_tokens": int(graph_period["used_tokens"]),
        "shadow_baseline_total_tokens": int(baseline_period["used_tokens"]),
        "graph_run_id": graph_run_id,
        "baseline_run_id": baseline_run_id,
        "run_spec_hash": run_spec_hash,
        "token_authority": "normalized_agent_invocations",
    }


def token_failures(metrics: dict[str, Any]) -> list[str]:
    failures = []
    if int(metrics["routine_context_bytes"]) > 6000:
        failures.append("routine_context_bytes")
    if metrics["full_graph_loaded_for_routine"]:
        failures.append("full_graph_loaded_for_routine")
    for field in (
        "untriggered_conditionals_in_context",
        "future_node_gaps_blocked",
        "routine_subagent_count",
    ):
        if int(metrics[field]) != 0:
            failures.append(field)
    graph_tokens = int(metrics["shadow_graph_total_tokens"])
    baseline_tokens = int(metrics["shadow_baseline_total_tokens"])
    if graph_tokens > baseline_tokens:
        failures.append("shadow_graph_total_tokens")
    if not graph_tokens:
        failures.append("shadow_graph_total_tokens_nonzero")
    if not baseline_tokens:
        failures.append("shadow_baseline_total_tokens_nonzero")
    return failures
