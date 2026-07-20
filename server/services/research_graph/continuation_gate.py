"""Exact-hash Gate consumption for immutable Graph continuation."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.services.maintenance_cases import (
    consume_case_effect_in_connection,
)


CONTINUE_ACTION = "continue_graph_branch"


def consume_continuation_gate(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    case_id: str,
    target_hash: str,
    effect_ref: str,
) -> dict[str, Any]:
    """Consume one approved continuation effect in the caller transaction."""
    return consume_case_effect_in_connection(
        conn,
        owner_user_id=owner_user_id,
        case_id=case_id,
        agent_id="",
        effect_ref=effect_ref,
        change_refs=[f"gate-effect:{effect_ref}"],
        expected_kind="approval_gate",
        required_affected_refs=(
            f"gate-action:{CONTINUE_ACTION}",
            f"gate-target-hash:{target_hash}",
        ),
        required_change_ref_prefixes=(
            "gate-validation:",
            "gate-grill:",
            "gate-approval:",
        ),
    )
