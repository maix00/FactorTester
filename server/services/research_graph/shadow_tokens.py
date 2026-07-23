"""Server-derived token evidence for one bounded shadow comparison."""

from __future__ import annotations

from typing import Any

from server.services import agent_flow
from server.services.research_graph.packet_calibration_binding import (
    bind_packet_calibration,
)
from server.services.research_graph.packet_budget import graph_packet_budget
from server.services.research_graph.protocol import json_hash


def shadow_token_contract(
    *,
    graph_id: str,
    version: int,
    instance_id: str,
    branch_id: str,
    graph_run_id: str,
    baseline_run_id: str,
    run_spec_hash: str,
) -> dict[str, Any]:
    comparison_hash = json_hash({
        "contract": "active-graph-token-shadow@1",
        "graph_id": graph_id,
        "graph_version": int(version),
        "instance_id": instance_id,
        "branch_id": branch_id,
        "graph_run_id": graph_run_id,
        "baseline_run_id": baseline_run_id,
        "run_spec_hash": run_spec_hash,
    })
    input_hash = json_hash({
        "contract": "active-graph-token-shadow-workload@1",
        "run_spec_hash": run_spec_hash,
    })
    prefix = f"graph-activation-shadow:{comparison_hash}"
    return {
        "comparison_hash": comparison_hash,
        "input_hash": input_hash,
        "graph": {
            "agent_id": f"instance:{instance_id}",
            "task_ref": (
                f"{prefix}:graph:{instance_id}:{branch_id}:{graph_run_id}"
            ),
        },
        "baseline": {
            "agent_id": f"research-run:{baseline_run_id}",
            "task_ref": f"{prefix}:baseline:{baseline_run_id}",
        },
    }


def derive_token_metrics(
    *,
    owner: str,
    graph_id: str,
    version: int,
    instance_id: str,
    branch_id: str,
    graph_run_id: str,
    baseline_run_id: str,
    run_spec_hash: str,
    graph: dict[str, Any],
    context: dict[str, Any],
    context_latency_ms: float,
    calibration_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = shadow_token_contract(
        graph_id=graph_id,
        version=version,
        instance_id=instance_id,
        branch_id=branch_id,
        graph_run_id=graph_run_id,
        baseline_run_id=baseline_run_id,
        run_spec_hash=run_spec_hash,
    )
    graph_scope = contract["graph"]["agent_id"]
    baseline_scope = contract["baseline"]["agent_id"]
    store = agent_flow.get_store()
    cohort = store.load_shadow_token_cohort(
        owner_user_id=owner,
        lineage_hash=contract["comparison_hash"],
    )
    graph_rows = _side_rows(
        cohort,
        agent_id=graph_scope,
        task_ref=contract["graph"]["task_ref"],
    )
    baseline_rows = _side_rows(
        cohort,
        agent_id=baseline_scope,
        task_ref=contract["baseline"]["task_ref"],
    )
    graph_quality = _quality_counts(graph_rows)
    baseline_quality = _quality_counts(baseline_rows)
    provider_actual_comparison = all((
        _valid_verified_side(graph_rows, contract["input_hash"]),
        _valid_verified_side(baseline_rows, contract["input_hash"]),
        len(graph_rows) == 1,
        len(baseline_rows) == 1,
        len(cohort) == 2,
    ))
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
    calibration = bind_packet_calibration(
        graph=graph,
        context=context,
        packet_budget=packet_budget,
        cohort=cohort,
        request=calibration_request,
    )
    calibrated_context_ceiling = int(
        (calibration.get("summary") or {}).get(
            "agent_context_byte_ceiling",
            packet_budget["ceiling_bytes"],
        )
    )
    return {
        "routine_context_bytes": int(context["context_bytes"]),
        "routine_context_ceiling_bytes": calibrated_context_ceiling,
        "routine_context_headroom_bytes": (
            calibrated_context_ceiling
            - int(context["context_bytes"])
        ),
        "routine_context_latency_ms": round(context_latency_ms, 3),
        "packet_budget_policy_ref": packet_budget["policy_ref"],
        "packet_budget_policy_status": packet_budget["calibration_status"],
        "packet_budget_calibration_status": calibration[
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
        "shadow_graph_total_tokens": _total_tokens(graph_rows),
        "shadow_baseline_total_tokens": _total_tokens(baseline_rows),
        "graph_measurement_quality_counts": graph_quality,
        "baseline_measurement_quality_counts": baseline_quality,
        "provider_actual_token_comparison": provider_actual_comparison,
        "graph_run_id": graph_run_id,
        "baseline_run_id": baseline_run_id,
        "run_spec_hash": run_spec_hash,
        "shadow_comparison_hash": contract["comparison_hash"],
        "shadow_workload_input_hash": contract["input_hash"],
        "token_authority": (
            "provider_actual"
            if provider_actual_comparison
            else "mixed_or_fallback"
        ),
        "packet_calibration": calibration,
    }
def _side_rows(
    rows: list[dict[str, Any]],
    *,
    agent_id: str,
    task_ref: str,
) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if str(row["agent_id"]) == agent_id
        and str(row["task_ref"]) == task_ref
    ]


def _quality_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        quality = str(row["measurement_quality"])
        counts[quality] = counts.get(quality, 0) + 1
    return counts


def _valid_verified_side(
    rows: list[dict[str, Any]],
    input_hash: str,
) -> bool:
    return bool(rows) and all(
        str(row["status"]) == "settled"
        and str(row["actor_role"]) == "researcher"
        and not str(row["sponsor_agent_id"])
        and str(row["input_hash"]) == input_hash
        and str(row["measurement_quality"]) == "provider_actual"
        and bool(str(row["provider_id"]))
        and bool(str(row["provider_request_hash"]))
        and bool(str(row["provider_attestation_hash"]))
        and bool(str(row["launcher_attestation_hash"]))
        for row in rows
    )


def _total_tokens(rows: list[dict[str, Any]]) -> int:
    return sum(int(row["charged_tokens"] or 0) for row in rows)


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
    calibration = metrics.get("packet_calibration") or {}
    if calibration.get("calibration_status") not in {
        "provider_verified",
        "legacy_schema_exempt",
    }:
        failures.append("packet_calibration_receipt")
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
