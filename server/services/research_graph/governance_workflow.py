"""Application workflow for Graph proposal, review, grill, and approval."""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

import settings as Settings
from server.services import agent_flow
from server.services.research_graph import activation_gate
from server.services.research_graph.active_pointer import pointer_reason_hash
from server.services.research_graph.protocol import (
    assert_no_skill_identity,
    json_hash,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def record_proposal(
    *,
    graph_id: str,
    version: int,
    owner_user_id: str,
    actor_agent_id: str,
    risk_level: str,
    change_diff: dict[str, Any],
    evidence_refs: list[str],
    token_estimate: int,
    conversation_ref: str,
    pointer_action: str = activation_gate.ACTIVATE_ACTION,
    pointer_from_version: int = 0,
    pointer_reason: str = "",
) -> dict[str, Any]:
    if risk_level not in {"L1", "L2", "L3", "L4"}:
        raise ValueError("invalid proposal risk_level")
    if not isinstance(change_diff, dict) or not change_diff:
        raise ValueError("change_diff must be a non-empty object")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise ValueError("evidence_refs must be an array of references")
    if (
        not isinstance(token_estimate, int)
        or isinstance(token_estimate, bool)
        or token_estimate < 0
    ):
        raise ValueError("token_estimate must be non-negative")
    assert_no_skill_identity(change_diff, location="proposal diff")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
        if graph is None:
            raise KeyError("graph version not found")
        if (
            pointer_action == activation_gate.ACTIVATE_ACTION
            and graph["lifecycle"] != "draft"
        ):
            raise ValueError("only a draft graph accepts proposals")
        if pointer_action == activation_gate.ROLLBACK_ACTION:
            current = conn.execute(
                """
                SELECT version FROM active_research_graphs
                WHERE graph_id=?
                """,
                (graph_id,),
            ).fetchone()
            if (
                current is None
                or int(current["version"]) != int(pointer_from_version)
            ):
                raise ValueError(
                    "rollback proposal from_version is not currently active"
                )
            if int(pointer_from_version) == int(version):
                raise ValueError("rollback target is already active")
        _require_agent_invocation(
            owner_user_id=owner_user_id,
            invocation_id=actor_agent_id,
            role="proposer",
        )
    diff_hash = json_hash(change_diff)
    reason_hash = (
        pointer_reason_hash(pointer_reason)
        if pointer_action == activation_gate.ROLLBACK_ACTION
        else ""
    )
    row = activation_gate.open_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=int(version),
        graph_hash=str(graph["content_hash"]),
        diff_hash=diff_hash,
        proposer_invocation_id=actor_agent_id,
        conversation_ref=conversation_ref,
        proposal_evidence_refs=evidence_refs,
        action=pointer_action,
        from_version=pointer_from_version,
        reason_hash=reason_hash,
    )
    row.update({
        "graph_id": graph_id,
        "version": int(version),
        "proposer_execution_id": actor_agent_id,
        "risk_level": risk_level,
        "change_diff": deepcopy(change_diff),
        "evidence_refs": list(evidence_refs),
        "token_estimate": token_estimate,
        "pointer_action": pointer_action,
        "pointer_from_version": int(pointer_from_version),
        "pointer_reason_hash": reason_hash,
    })
    return row


def record_proposal_review(
    *,
    proposal_id: str,
    owner_user_id: str,
    actor_agent_id: str,
    disposition: str,
    scope_drift: bool,
    semantic_uncertainty: bool,
    evidence_refs: list[str],
) -> dict[str, Any]:
    if disposition not in {"approved", "rejected", "disagreed"}:
        raise ValueError("invalid review disposition")
    if not isinstance(scope_drift, bool) or not isinstance(
        semantic_uncertainty, bool
    ):
        raise ValueError("review flags must be boolean")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise ValueError("evidence_refs must be an array of references")
    case = activation_gate.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
    )
    proposer_id = activation_gate.proposer_invocation_id(case)
    reviewer = _require_agent_invocation(
        owner_user_id=owner_user_id,
        invocation_id=actor_agent_id,
        role="reviewer",
    )
    if proposer_id == actor_agent_id:
        raise ValueError("proposal reviewer invocation must be independent")
    proposer = _require_agent_invocation(
        owner_user_id=owner_user_id,
        invocation_id=proposer_id,
        role="proposer",
    )
    if (
        str(proposer["agent_principal_hash"])
        == str(reviewer["agent_principal_hash"])
        or str(proposer["lineage_hash"]) == str(reviewer["lineage_hash"])
    ):
        raise ValueError(
            "proposal reviewer principal and lineage must be independent"
        )
    existing_ids = activation_gate.reviewer_invocation_ids(case)
    existing = agent_flow.get_store().load_invocations(
        owner_user_id=owner_user_id,
        invocation_ids=existing_ids,
    ).values()
    if any(
        str(row["agent_principal_hash"])
        == str(reviewer["agent_principal_hash"])
        or str(row["lineage_hash"]) == str(reviewer["lineage_hash"])
        for row in existing
    ):
        raise ValueError(
            "reviewer principal or lineage already reviewed this proposal"
        )
    effective = (
        "disagreed" if scope_drift or semantic_uncertainty else disposition
    )
    review = activation_gate.record_activation_review(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
        reviewer_invocation_id=actor_agent_id,
        disposition=effective,
        evidence_refs=evidence_refs,
    )
    return {
        "review_id": json_hash({
            "proposal_id": proposal_id,
            "reviewer_execution_id": actor_agent_id,
        }),
        "proposal_id": proposal_id,
        "owner_user_id": owner_user_id,
        "reviewer_execution_id": actor_agent_id,
        "disposition": disposition,
        "scope_drift": scope_drift,
        "semantic_uncertainty": semantic_uncertainty,
        "evidence_refs": list(evidence_refs),
        "created_at": float(review["updated_at"]),
    }


def record_audit(
    *,
    graph_id: str,
    version: int,
    actor: str,
    proposal_id: str,
    disposition: str,
    grill_evidence: list[dict[str, Any]],
    grill_ref: str,
    owner_user_id: str = "",
) -> dict[str, Any]:
    if disposition not in {"approved", "rejected", "quarantined", "frozen"}:
        raise ValueError("invalid audit disposition")
    if not isinstance(grill_evidence, list) or not grill_evidence:
        raise ValueError("grill_evidence must be a non-empty array")
    assert_no_skill_identity(grill_evidence, location="grill evidence")
    audit_id = json_hash({
        "graph_id": graph_id,
        "version": int(version),
        "disposition": disposition,
        "grill_ref": grill_ref,
        "grill_evidence_hash": json_hash(grill_evidence),
    })
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
    if graph is None:
        raise KeyError("graph version not found")
    owner = owner_user_id or actor
    case = activation_gate.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
    )
    activation_gate.require_graph_target(
        case,
        graph_id=graph_id,
        graph_version=version,
        graph_hash=str(graph["content_hash"]),
    )
    activation_gate.record_activation_grill(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
        disposition=disposition,
        grill_ref=grill_ref,
    )
    return {
        "audit_id": audit_id,
        "graph_id": graph_id,
        "version": int(version),
        "actor": actor,
        "disposition": disposition,
        "grill_evidence": deepcopy(grill_evidence),
        "created_at": time.time(),
    }


def authorize_graph_activation(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    proposal_id: str,
    graph_hash: str,
    diff_hash: str,
    conversation_ref: str,
    approval_ref: str,
    pointer_action: str = activation_gate.ACTIVATE_ACTION,
    pointer_from_version: int = 0,
    pointer_reason: str = "",
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(graph_version),
        )
    if graph is None:
        raise ValueError("human pointer change requires a Graph version")
    if (
        pointer_action == activation_gate.ACTIVATE_ACTION
        and graph.get("lifecycle") != "draft"
    ):
        raise ValueError("human activation requires a draft Graph")
    actual_hash = str(graph["content_hash"])
    if graph_hash != actual_hash:
        raise ValueError("human activation target hash mismatch")
    case = activation_gate.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
    )
    activation_gate.require_graph_target(
        case,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=actual_hash,
    )
    if activation_gate.gate_action(case) != pointer_action:
        raise ValueError("human authorization action does not match")
    reason_hash = (
        pointer_reason_hash(pointer_reason)
        if pointer_action == activation_gate.ROLLBACK_ACTION
        else ""
    )
    target_hash = activation_gate.activation_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=actual_hash,
        diff_hash=diff_hash,
        action=pointer_action,
        from_version=pointer_from_version,
        reason_hash=reason_hash,
    )
    return activation_gate.approve_activation(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
        target_hash=target_hash,
        conversation_ref=conversation_ref,
        approval_ref=approval_ref,
    )


def _require_agent_invocation(
    *,
    owner_user_id: str,
    invocation_id: str,
    role: str,
) -> dict[str, Any]:
    try:
        row = agent_flow.get_store().load_invocation(
            owner_user_id=owner_user_id,
            invocation_id=invocation_id,
        )
    except KeyError as exc:
        raise ValueError(
            f"valid {role} Agent invocation is required"
        ) from exc
    if str(row["actor_role"]) != role or str(row["status"]) != "settled":
        raise ValueError(f"valid {role} Agent invocation is required")
    return row
