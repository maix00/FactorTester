"""Exact-hash authorization consumption for Graph pointer effects."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import orjson

from server.services.maintenance_cases import (
    consume_case_effect_in_connection,
)


ACTIVATE_ACTION = "activate_graph"
ROLLBACK_ACTION = "rollback_graph_pointer"


def pointer_target_hash(
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
    return hashlib.sha256(
        orjson.dumps(
            {
                "action": action,
                "owner_user_id": owner_user_id,
                "graph_id": graph_id,
                "graph_version": int(graph_version),
                "graph_hash": graph_hash,
                "diff_hash": diff_hash,
                "from_version": int(from_version),
                "reason_hash": reason_hash,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()


def consume_activation(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    case_id: str,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
    effect_ref: str,
) -> dict[str, Any]:
    row, diff_hash = _load_gate_target(
        conn,
        owner_user_id=owner_user_id,
        case_id=case_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=graph_hash,
        missing_message="activation Gate not found",
    )
    target_hash = pointer_target_hash(
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
            f"gate-action:{ACTIVATE_ACTION}",
            f"gate-target-hash:{target_hash}",
        ),
        required_change_ref_prefixes=(
            "gate-validation:",
            "gate-grill:",
            "gate-approval:",
        ),
        loaded_row=row,
    )


def consume_rollback(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    case_id: str,
    graph_id: str,
    from_version: int,
    to_version: int,
    graph_hash: str,
    reason_hash: str,
    effect_ref: str,
) -> dict[str, Any]:
    row, diff_hash = _load_gate_target(
        conn,
        owner_user_id=owner_user_id,
        case_id=case_id,
        graph_id=graph_id,
        graph_version=to_version,
        graph_hash=graph_hash,
        missing_message="rollback Gate not found",
    )
    target_hash = pointer_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=to_version,
        graph_hash=graph_hash,
        diff_hash=diff_hash,
        action=ROLLBACK_ACTION,
        from_version=from_version,
        reason_hash=reason_hash,
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
            f"gate-action:{ROLLBACK_ACTION}",
            f"gate-target-hash:{target_hash}",
            f"graph-pointer-from:{int(from_version)}",
            f"graph-pointer-reason-hash:{reason_hash}",
        ),
        required_change_ref_prefixes=(
            "gate-validation:",
            "gate-grill:",
            "gate-approval:",
        ),
        loaded_row=row,
    )


def _load_gate_target(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    case_id: str,
    graph_id: str,
    graph_version: int,
    graph_hash: str,
    missing_message: str,
) -> tuple[sqlite3.Row, str]:
    row = conn.execute(
        """
        SELECT * FROM research_maintenance_cases
        WHERE owner_user_id=? AND case_id=?
        """,
        (owner_user_id, case_id),
    ).fetchone()
    if row is None:
        raise KeyError(missing_message)
    affected_refs = orjson.loads(row["affected_refs_json"])
    proposal_prefix = (
        f"graph-proposal:{graph_id}@{int(graph_version)}:{graph_hash}:"
    )
    proposals = [
        ref for ref in affected_refs if ref.startswith(proposal_prefix)
    ]
    if len(proposals) != 1:
        raise ValueError("Graph pointer Gate target does not match")
    return row, proposals[0][len(proposal_prefix):]
