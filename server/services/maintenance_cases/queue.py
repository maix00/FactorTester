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
    limit: int = 16,
) -> dict[str, Any]:
    """Return open or self-claimed work without resolved history."""
    bounded_limit = min(32, max(1, int(limit)))
    with connect_maintenance_cases(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_maintenance_cases
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
            LIMIT ?
            """,
            (owner_user_id, agent_id, bounded_limit + 1),
        ).fetchall()
    return {
        "cases": [_case_summary(row) for row in rows[:bounded_limit]],
        "omitted_case_count": max(len(rows) - bounded_limit, 0),
    }


def _case_summary(row: Any) -> dict[str, Any]:
    return {
        "case_id": str(row["case_id"]),
        "kind": str(row["kind"]),
        "status": str(row["status"]),
        "descriptor_hash": str(row["descriptor_hash"]),
        "affected_refs": orjson.loads(row["affected_refs_json"]),
        "change_refs": orjson.loads(row["change_refs_json"]),
        "claimed_agent_id": str(row["claimed_agent_id"]),
    }
