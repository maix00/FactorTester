"""Server-derived token evidence for one bounded shadow comparison."""

from __future__ import annotations

from typing import Any

from server.services import agent_flow
from server.services.research_graph.packet_budget import graph_packet_budget


def derive_token_metrics(
    *,
    owner: str,
    instance_id: str,
    graph_run_id: str,
    baseline_run_id: str,
    run_spec_hash: str,
    graph: dict[str, Any],
    context: dict[str, Any],
    context_latency_ms: float,
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
    quality_by_period = store.measurement_quality_counts(
        owner_user_id=owner,
        period_ids=[
            str(graph_period["period_id"]),
            str(baseline_period["period_id"]),
        ],
    )
    graph_quality = quality_by_period.get(
        str(graph_period["period_id"]),
        {},
    )
    baseline_quality = quality_by_period.get(
        str(baseline_period["period_id"]),
        {},
    )
    provider_actual_comparison = (
        graph_quality.get("provider_actual", 0) > 0
        and baseline_quality.get("provider_actual", 0) > 0
        and set(graph_quality) == {"provider_actual"}
        and set(baseline_quality) == {"provider_actual"}
    )
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
    packet_budget = graph_packet_budget(graph)
    return {
        "routine_context_bytes": int(context["context_bytes"]),
        "routine_context_ceiling_bytes": int(packet_budget["ceiling_bytes"]),
        "routine_context_headroom_bytes": (
            int(packet_budget["ceiling_bytes"])
            - int(context["context_bytes"])
        ),
        "routine_context_latency_ms": round(context_latency_ms, 3),
        "packet_budget_policy_ref": packet_budget["policy_ref"],
        "packet_budget_calibration_status": packet_budget[
            "calibration_status"
        ],
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
        "graph_measurement_quality_counts": graph_quality,
        "baseline_measurement_quality_counts": baseline_quality,
        "provider_actual_token_comparison": provider_actual_comparison,
        "graph_run_id": graph_run_id,
        "baseline_run_id": baseline_run_id,
        "run_spec_hash": run_spec_hash,
        "token_authority": (
            "provider_actual"
            if provider_actual_comparison
            else "mixed_or_fallback"
        ),
    }


def token_failures(metrics: dict[str, Any]) -> list[str]:
    failures = []
    if int(metrics["routine_context_bytes"]) > int(
        metrics["routine_context_ceiling_bytes"]
    ):
        failures.append("routine_context_bytes")
    if float(metrics["routine_context_latency_ms"]) < 0:
        failures.append("routine_context_latency_ms")
    if metrics["packet_budget_calibration_status"] == (
        "missing_graph_calibration"
    ):
        failures.append("packet_budget_calibration")
    if not metrics["provider_actual_token_comparison"]:
        failures.append("provider_actual_token_comparison")
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
