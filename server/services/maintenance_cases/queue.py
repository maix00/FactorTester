"""Bounded read-only queue projection for a Server Maintenance Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson

from .schema import connect_maintenance_cases


def load_agent_case_queue(
    *,
    db_path: str | Path,
    owner_user_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Return the first actionable case and the exact remaining count."""
    with connect_maintenance_cases(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *, COUNT(*) OVER () AS total_count
            FROM research_maintenance_cases
            WHERE owner_user_id=? AND (
                status='open' OR (
                    claimed_agent_id=?
                    AND status IN ('claimed', 'blocked')
                )
            )
            ORDER BY
                CASE status WHEN 'claimed' THEN 0
                            WHEN 'blocked' THEN 1 ELSE 2 END,
                updated_at, case_id
            LIMIT 1
            """,
            (owner_user_id, agent_id),
        ).fetchall()
    total_count = int(rows[0]["total_count"]) if rows else 0
    return {
        "cases": [_case_summary(row) for row in rows],
        "remaining_case_count": max(total_count - len(rows), 0),
    }


def _case_summary(row: Any) -> dict[str, Any]:
    affected_refs = list(orjson.loads(row["affected_refs_json"]))
    change_refs = list(orjson.loads(row["change_refs_json"]))
    return {
        "case_id": str(row["case_id"]),
        "kind": str(row["kind"]),
        "status": str(row["status"]),
        "descriptor_hash": str(row["descriptor_hash"]),
        "affected_refs": affected_refs[:1],
        "remaining_affected_ref_count": max(len(affected_refs) - 1, 0),
        "change_refs": change_refs[:1],
        "remaining_change_ref_count": max(len(change_refs) - 1, 0),
        "claimed_agent_id": str(row["claimed_agent_id"]),
    }
