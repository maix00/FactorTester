"""Compact projection of current Graph and Evidence Action reads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import orjson

from tools.cli.protocols.research_step import context_ref, identifier, sha256


INSPECT_FIELDS = {
    "schema_version", "operation", "binding", "graph", "action", "cas",
    "allowed_operations", "operation_payload_contracts", "capabilities",
    "candidate_edges", "report_requirement_refs", "packet_bytes",
}


def build_inspect_contract(
    next_packet: dict[str, Any],
    execution_contract: dict[str, Any],
) -> dict[str, Any]:
    """Project one current TrialPlan action without leaking its cold body."""
    branch = _object(next_packet.get("branch"), "next.branch")
    node = _object(next_packet.get("node"), "next.node")
    action = _object(
        execution_contract.get("current_action"),
        "execution.current_action",
    )
    checkpoint = _object(
        execution_contract.get("checkpoint"),
        "execution.checkpoint",
    )
    instance_id = identifier(branch.get("instance_id"), "instance_id")
    branch_id = identifier(branch.get("branch_id"), "branch_id")
    if (
        execution_contract.get("instance_id") != instance_id
        or execution_contract.get("branch_id") != branch_id
    ):
        raise ValueError("Graph next and execution checkpoint identities differ")
    plan_hash = sha256(branch.get("trial_plan_hash"), "trial_plan_hash")
    if execution_contract.get("trial_plan_hash") != plan_hash:
        raise ValueError("Graph next and execution TrialPlan identities differ")
    value = {
        "schema_version": 1,
        "operation": "research.step.inspect",
        "binding": _binding(branch, instance_id, branch_id),
        "graph": {
            "graph_ref": identifier(next_packet.get("graph"), "graph_ref"),
            "context_ref": context_ref(next_packet.get("context_ref")),
            "node_id": identifier(node.get("node_id"), "node_id"),
            "node_kind": str(node.get("kind") or ""),
            "trial_plan_hash": plan_hash,
        },
        "action": _action(
            action,
            checkpoint,
            _object(execution_contract.get("trial_plan"), "trial_plan"),
        ),
        "cas": {
            "latest_trace_id": identifier(
                execution_contract.get("latest_trace_id"),
                "latest_trace_id",
            ),
            "checkpoint_hash": sha256(
                checkpoint.get("projection_hash"), "checkpoint_hash",
            ),
        },
        "allowed_operations": list(dict.fromkeys([
            identifier(item, "allowed_operation")
            for item in execution_contract.get("allowed_operations") or []
        ])),
        "operation_payload_contracts": _payload_contracts(
            execution_contract,
        ),
        "capabilities": _capabilities(next_packet),
        "candidate_edges": [
            _candidate_edge(item)
            for item in next_packet.get("candidate_edges") or []
            if isinstance(item, dict)
        ],
        "report_requirement_refs": [
            identifier(item, "report_requirement_ref")
            for item in next_packet.get(
                "node_report_requirement_refs",
            ) or []
        ],
        "packet_bytes": 0,
    }
    for _ in range(4):
        value["packet_bytes"] = len(orjson.dumps(value))
    if value["packet_bytes"] != len(orjson.dumps(value)):
        raise ValueError("research step packet size did not converge")
    return value


def validate_inspect_contract(value: dict[str, Any]) -> None:
    if not isinstance(value, dict) or set(value) != INSPECT_FIELDS:
        raise ValueError("research step inspect contract fields are invalid")
    if value.get("schema_version") != 1:
        raise ValueError("inspect schema_version must be 1")


def _binding(
    branch: dict[str, Any],
    instance_id: str,
    branch_id: str,
) -> dict[str, str]:
    return {
        "profile_ref": identifier(
            branch.get("current_owner_profile_ref"), "profile_ref",
        ),
        "work_package_id": identifier(
            branch.get("work_package_id"), "work_package_id",
        ),
        "instance_id": instance_id,
        "branch_id": branch_id,
    }


def _action(
    action: dict[str, Any],
    checkpoint: dict[str, Any],
    trial_plan: dict[str, Any],
) -> dict[str, Any]:
    comparison_ids = [
        identifier(item, "comparison_id")
        for item in action.get("comparison_ids") or []
    ]
    return {
        "action_id": identifier(action.get("action_id"), "action_id"),
        "status": identifier(
            checkpoint.get("current_action_status"), "action.status",
        ),
        "stage_id": identifier(action.get("stage_id"), "stage_id"),
        "input_hash": sha256(action.get("input_hash"), "input_hash"),
        "execution_mode": identifier(
            action.get("execution_mode"), "execution_mode",
        ),
        "expected_evidence_kind": identifier(
            action.get("expected_evidence_kind"),
            "expected_evidence_kind",
        ),
        "run_spec_hashes": [
            sha256(item, "run_spec_hash")
            for item in action.get("run_spec_hashes") or []
        ],
        "comparison_ids": comparison_ids,
        "comparison_roles": _comparison_roles(
            trial_plan, comparison_ids,
        ),
        "obligation_refs": [
            identifier(item, "obligation_ref")
            for item in action.get("obligation_refs") or []
        ],
    }


def _comparison_roles(
    trial_plan: dict[str, Any],
    comparison_ids: list[str],
) -> dict[str, list[str]]:
    by_id = {
        str(item.get("comparison_id") or ""): item
        for item in trial_plan.get("comparisons") or []
        if isinstance(item, dict)
    }
    values = {}
    for comparison_id in comparison_ids:
        comparison = by_id.get(comparison_id)
        if comparison is None:
            raise ValueError("Evidence Action comparison is unavailable")
        roles = sorted({
            identifier(member.get("trial_role"), "trial_role")
            for member in comparison.get("members") or []
            if isinstance(member, dict)
        })
        if not roles:
            raise ValueError("Evidence Action comparison has no members")
        values[comparison_id] = roles
    return values


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _capabilities(next_packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for raw in next_packet.get("capabilities") or []:
        if not isinstance(raw, dict):
            raise ValueError("capability summary must be an object")
        row = {
            "capability_id": identifier(
                raw.get("capability_id"), "capability_id",
            ),
            "status": identifier(raw.get("status"), "capability.status"),
        }
        for field in ("descriptor_hash", "reason"):
            item = raw.get(field)
            if isinstance(item, str) and item:
                row[field] = item
        rows.append(row)
    if len(rows) > 32:
        raise ValueError("research step has too many current capabilities")
    return rows


def _payload_contracts(
    execution_contract: dict[str, Any],
) -> dict[str, dict[str, list[str]]]:
    source = execution_contract.get("operation_payload_contracts") or {}
    values = {}
    for operation in execution_contract.get("allowed_operations") or []:
        raw = source.get(operation) or {}
        required = raw.get("required_fields") or []
        if not isinstance(required, list) or len(required) > 8:
            raise ValueError("operation required_fields are invalid")
        values[operation] = {
            "required_fields": [
                identifier(item, "operation.required_field")
                for item in required
            ],
        }
    return values


def _candidate_edge(value: dict[str, Any]) -> dict[str, str]:
    return {
        "edge_id": identifier(value.get("edge_id"), "edge_id"),
        "to_node": identifier(value.get("to_node"), "edge.to_node"),
        "readiness": identifier(
            value.get("readiness"), "edge.readiness",
        ),
    }
