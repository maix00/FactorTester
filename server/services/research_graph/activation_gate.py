"""Graph pointer-change governance projected onto one Maintenance Case."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.services.maintenance_cases import (
    MaintenanceCaseStore,
    approve_gate,
    open_gate,
    record_gate_grill,
    record_gate_review,
    record_gate_validation,
)
from server.services.research_graph.pointer_gate import (
    ACTIVATE_ACTION,
    ROLLBACK_ACTION,
    pointer_target_hash,
)


def activation_target_hash(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
    diff_hash: str,
    action: str = ACTIVATE_ACTION,
    from_version: int = 0,
    reason_hash: str = "",
) -> str:
    return pointer_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=graph_hash,
        diff_hash=diff_hash,
        action=action,
        from_version=from_version,
        reason_hash=reason_hash,
    )


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
    action: str = ACTIVATE_ACTION,
    from_version: int = 0,
    reason_hash: str = "",
) -> dict[str, Any]:
    _validate_pointer_action(
        action=action,
        from_version=from_version,
        reason_hash=reason_hash,
    )
    target_hash = activation_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=graph_hash,
        diff_hash=diff_hash,
        action=action,
        from_version=from_version,
        reason_hash=reason_hash,
    )
    proposal_ref = (
        f"graph-proposal:{graph_id}@{int(graph_version)}:"
        f"{graph_hash}:{diff_hash}"
    )
    pointer_refs = (
        []
        if action == ACTIVATE_ACTION
        else [
            f"graph-pointer-from:{int(from_version)}",
            f"graph-pointer-reason-hash:{reason_hash}",
        ]
    )
    case = open_gate(
        MaintenanceCaseStore(db_path),
        owner_user_id=owner_user_id,
        coordinator_agent_id=proposer_invocation_id,
        proposal_ref=proposal_ref,
        proposer_identity_ref=f"agent-invocation:{proposer_invocation_id}",
        action=action,
        target_hash=target_hash,
        conversation_ref=conversation_ref,
        proposal_evidence_refs=[
            *proposal_evidence_refs,
            *pointer_refs,
        ],
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
        action=gate_action(case),
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


def gate_action(case: dict[str, Any]) -> str:
    prefix = "gate-action:"
    values = [
        ref[len(prefix):]
        for ref in case["affected_refs"]
        if ref.startswith(prefix)
    ]
    if len(values) != 1 or values[0] not in {
        ACTIVATE_ACTION,
        ROLLBACK_ACTION,
    }:
        raise ValueError("activation Gate action is invalid")
    return values[0]


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


def _validate_pointer_action(
    *,
    action: str,
    from_version: int,
    reason_hash: str,
) -> None:
    if action == ACTIVATE_ACTION:
        if int(from_version) != 0 or reason_hash:
            raise ValueError("activation Gate cannot bind rollback fields")
        return
    if action != ROLLBACK_ACTION:
        raise ValueError("unsupported Graph pointer action")
    if int(from_version) < 1:
        raise ValueError("rollback Gate requires from_version")
    if len(reason_hash) != 64 or any(
        character not in "0123456789abcdef" for character in reason_hash
    ):
        raise ValueError("rollback Gate requires reason_hash")


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
