"""Read and aggregate Agent Flow state behind one query Module."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import orjson

from .schema import connect_agent_flow


class AgentFlowQueries:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def load_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE owner_user_id=? AND invocation_id=?
                """,
                (owner_user_id, invocation_id),
            ).fetchone()
        if row is None:
            raise KeyError("Agent invocation not found")
        return invocation_value(row)

    def load_invocations(
        self,
        *,
        owner_user_id: str,
        invocation_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        unique_ids = list(dict.fromkeys(invocation_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM agent_invocations
                WHERE owner_user_id=? AND invocation_id IN ({placeholders})
                """,
                (owner_user_id, *unique_ids),
            ).fetchall()
        return {
            str(row["invocation_id"]): invocation_value(row)
            for row in rows
        }

    def count_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        subagents_only: bool = False,
    ) -> int:
        subagent_predicate = (
            "AND sponsor_agent_id<>''" if subagents_only else ""
        )
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count FROM agent_invocations
                WHERE owner_user_id=? AND agent_id=?
                {subagent_predicate}
                """,
                (owner_user_id, agent_id),
            ).fetchone()
        return int(row["count"])

    def settled_tokens_for_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        invocation_ids: list[str],
    ) -> int:
        unique_ids = list(dict.fromkeys(invocation_ids))
        if not unique_ids:
            return 0
        placeholders = ",".join("?" for _ in unique_ids)
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT invocation_id, charged_tokens
                FROM agent_invocations
                WHERE owner_user_id=? AND agent_id=? AND status='settled'
                  AND invocation_id IN ({placeholders})
                """,
                (owner_user_id, agent_id, *unique_ids),
            ).fetchall()
        if len(rows) != len(unique_ids):
            raise ValueError(
                "all Agent invocations must be settled in the expected scope"
            )
        return sum(int(row["charged_tokens"]) for row in rows)

    def measurement_quality_counts(
        self,
        *,
        owner_user_id: str,
        period_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        unique_ids = list(dict.fromkeys(period_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT period_id, measurement_quality, COUNT(*) AS count
                FROM agent_invocations
                WHERE owner_user_id=? AND status='settled'
                  AND period_id IN ({placeholders})
                GROUP BY period_id, measurement_quality
                """,
                (owner_user_id, *unique_ids),
            ).fetchall()
        result = {period_id: {} for period_id in unique_ids}
        for row in rows:
            result[str(row["period_id"])][
                str(row["measurement_quality"])
            ] = int(row["count"])
        return result

    def load_shadow_token_cohort(
        self,
        *,
        owner_user_id: str,
        lineage_hash: str,
    ) -> list[dict[str, Any]]:
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_invocations
                WHERE owner_user_id=? AND lineage_hash=?
                ORDER BY created_at, invocation_id
                LIMIT 3
                """,
                (owner_user_id, lineage_hash),
            ).fetchall()
        return [invocation_value(row) for row in rows]


def invocation_value(row: sqlite3.Row) -> dict[str, Any]:
    return {
        key: row[key]
        for key in row.keys()
        if key != "context_cost_json"
    } | {
        "context_cost": orjson.loads(row["context_cost_json"]),
    }


def reserved_invocation_value(row: sqlite3.Row) -> dict[str, Any]:
    token_limit = row["current_token_limit"]
    return {
        "invocation_id": str(row["invocation_id"]),
        "period_id": str(row["period_id"]),
        "owner_user_id": str(row["owner_user_id"]),
        "agent_id": str(row["agent_id"]),
        "status": str(row["status"]),
        "token_limit": (
            int(token_limit) if token_limit is not None else None
        ),
        "reserved_tokens": int(row["reserved_tokens"]),
        "created_at": float(row["created_at"]),
    }


def settled_invocation_value(row: sqlite3.Row) -> dict[str, Any]:
    charged_tokens = int(row["charged_tokens"])
    reserved_tokens = int(row["reserved_tokens"])
    return {
        "invocation_id": str(row["invocation_id"]),
        "period_id": str(row["period_id"]),
        "status": str(row["status"]),
        "charged_tokens": charged_tokens,
        "measurement_quality": str(row["measurement_quality"]),
        "released_tokens": reserved_tokens - charged_tokens,
        "settled_at": float(row["settled_at"]),
    }
