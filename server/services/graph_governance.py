"""Graph activation governance projected onto one Maintenance Case."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
from typing import Any

import orjson

from server.services.maintenance_cases import (
    MaintenanceCaseStore,
    approve_gate,
    consume_case_effect_in_connection,
    open_gate,
    record_gate_grill,
    record_gate_review,
    record_gate_validation,
)


ACTION = "activate_graph"


def activation_target_hash(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
    diff_hash: str,
) -> str:
    return _hash({
        "action": ACTION,
        "owner_user_id": owner_user_id,
        "graph_id": graph_id,
        "graph_version": int(graph_version),
        "graph_hash": graph_hash,
        "diff_hash": diff_hash,
    })


def open_activation_gate(
    db_path: str | Path,
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
    diff_hash: str,
    proposer_invocation_id: str,
    conversation_ref: str,
    proposal_evidence_refs: list[str],
) -> dict[str, Any]:
    target_hash = activation_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=graph_hash,
        diff_hash=diff_hash,
    )
    proposal_ref = (
        f"graph-proposal:{graph_id}@{int(graph_version)}:"
        f"{graph_hash}:{diff_hash}"
    )
    case = open_gate(
        MaintenanceCaseStore(db_path),
        owner_user_id=owner_user_id,
        coordinator_agent_id=proposer_invocation_id,
        proposal_ref=proposal_ref,
        proposer_identity_ref=f"agent-invocation:{proposer_invocation_id}",
        action=ACTION,
        target_hash=target_hash,
        conversation_ref=conversation_ref,
        proposal_evidence_refs=proposal_evidence_refs,
    )
    return _gate_projection(case, diff_hash=diff_hash)


def load_activation_gate(
    db_path: str | Path,
    *,
    owner_user_id: str,
    case_id: str,
) -> dict[str, Any]:
    case = MaintenanceCaseStore(db_path).load_case(
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    if case["kind"] != "approval_gate":
        raise ValueError("graph proposal is not an activation Gate")
    return case


def record_activation_review(
    db_path: str | Path,
    *,
    owner_user_id: str,
    case_id: str,
    reviewer_invocation_id: str,
    disposition: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    store = MaintenanceCaseStore(db_path)
    case = load_activation_gate(
        db_path,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    return record_gate_review(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
        coordinator_agent_id=str(case["claimed_agent_id"]),
        reviewer_identity_ref=f"agent-invocation:{reviewer_invocation_id}",
        disposition=disposition,
        evidence_refs=evidence_refs,
    )


def record_activation_validation(
    db_path: str | Path,
    *,
    owner_user_id: str,
    case_id: str,
    validation_summary_hash: str,
) -> dict[str, Any]:
    store = MaintenanceCaseStore(db_path)
    case = load_activation_gate(
        db_path,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    return record_gate_validation(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
        coordinator_agent_id=str(case["claimed_agent_id"]),
        validation_summary_hash=validation_summary_hash,
    )


def record_activation_grill(
    db_path: str | Path,
    *,
    owner_user_id: str,
    case_id: str,
    disposition: str,
    grill_ref: str,
) -> dict[str, Any]:
    store = MaintenanceCaseStore(db_path)
    case = load_activation_gate(
        db_path,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    return record_gate_grill(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
        coordinator_agent_id=str(case["claimed_agent_id"]),
        disposition=disposition,
        grill_ref=grill_ref,
    )


def approve_activation(
    db_path: str | Path,
    *,
    owner_user_id: str,
    case_id: str,
    target_hash: str,
    conversation_ref: str,
    approval_ref: str,
) -> dict[str, Any]:
    store = MaintenanceCaseStore(db_path)
    case = load_activation_gate(
        db_path,
        owner_user_id=owner_user_id,
        case_id=case_id,
    )
    if str(case["conversation_ref"]) != conversation_ref:
        raise ValueError("activation approval conversation does not match")
    if not approval_ref.startswith("auth-conversation-event:"):
        raise ValueError(
            "activation approval requires an authenticated conversation event"
        )
    approved = approve_gate(
        store,
        owner_user_id=owner_user_id,
        case_id=case_id,
        coordinator_agent_id=str(case["claimed_agent_id"]),
        action=ACTION,
        target_hash=target_hash,
        approval_ref=approval_ref,
    )
    return {
        "authorization_id": case_id,
        "case_id": case_id,
        "owner_user_id": owner_user_id,
        "authorized_by": owner_user_id,
        "conversation_ref": conversation_ref,
        "approval_ref": approval_ref,
        "target_hash": target_hash,
        "status": approved["status"],
    }


def consume_activation_in_connection(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    case_id: str,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
    effect_ref: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM research_maintenance_cases
        WHERE owner_user_id=? AND case_id=?
        """,
        (owner_user_id, case_id),
    ).fetchone()
    if row is None:
        raise KeyError("activation Gate not found")
    affected_refs = orjson.loads(row["affected_refs_json"])
    proposal_prefix = (
        f"graph-proposal:{graph_id}@{int(graph_version)}:{graph_hash}:"
    )
    proposals = [
        ref for ref in affected_refs if ref.startswith(proposal_prefix)
    ]
    if len(proposals) != 1:
        raise ValueError("activation Gate graph target does not match")
    diff_hash = proposals[0][len(proposal_prefix):]
    target_hash = activation_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=graph_hash,
        diff_hash=diff_hash,
    )
    return consume_case_effect_in_connection(
        conn,
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id="",
        effect_ref=effect_ref,
        change_refs=[f"gate-effect:{effect_ref}"],
        expected_kind="approval_gate",
        required_affected_refs=(
            f"gate-action:{ACTION}",
            f"gate-target-hash:{target_hash}",
        ),
        required_change_ref_prefixes=(
            "gate-validation:",
            "gate-grill:",
            "gate-approval:",
        ),
        loaded_row=row,
    )


def proposer_invocation_id(case: dict[str, Any]) -> str:
    prefix = "gate-proposer:agent-invocation:"
    values = [
        ref[len(prefix):]
        for ref in case["affected_refs"]
        if ref.startswith(prefix)
    ]
    if len(values) != 1:
        raise ValueError("activation Gate proposer identity is invalid")
    return values[0]


def reviewer_invocation_ids(case: dict[str, Any]) -> list[str]:
    prefix = "gate-reviewer:agent-invocation:"
    return [
        ref[len(prefix):]
        for ref in case["change_refs"]
        if ref.startswith(prefix)
    ]


def require_graph_target(
    case: dict[str, Any],
    *,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
) -> None:
    prefix = (
        f"graph-proposal:{graph_id}@{int(graph_version)}:{graph_hash}:"
    )
    if not any(ref.startswith(prefix) for ref in case["affected_refs"]):
        raise ValueError("activation Gate graph target does not match")


def _gate_projection(
    case: dict[str, Any],
    *,
    diff_hash: str,
) -> dict[str, Any]:
    return {
        "proposal_id": case["case_id"],
        "case_id": case["case_id"],
        "owner_user_id": case["owner_user_id"],
        "risk_level": "L4",
        "diff_hash": diff_hash,
        "conversation_ref": case["conversation_ref"],
        "status": case["status"],
        "created_at": case["created_at"],
    }


def _hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
