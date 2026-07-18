"""Agent budget-period lifecycle and pending-reset ownership."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any

from .schema import connect_agent_flow
from .validation import (
    CHARGING_POLICY_VERSION,
    require_text,
)


class BudgetPeriods:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def configure_token_limit(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int,
    ) -> dict[str, Any]:
        require_text("owner_user_id", owner_user_id)
        require_text("agent_id", agent_id)
        if (
            not isinstance(token_limit, int)
            or isinstance(token_limit, bool)
            or token_limit <= 0
        ):
            raise ValueError("token_limit must be a positive integer")
        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=? AND status='open'
                """,
                (owner_user_id, agent_id),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    INSERT INTO agent_budget_periods (
                        period_id, owner_user_id, agent_id, token_limit,
                        used_tokens, reserved_tokens,
                        charging_policy_version, revision, status, created_at
                    ) VALUES (?, ?, ?, ?, 0, 0, ?, 1, 'open', ?)
                    RETURNING *
                    """,
                    (
                        uuid.uuid4().hex,
                        owner_user_id,
                        agent_id,
                        token_limit,
                        CHARGING_POLICY_VERSION,
                        now,
                    ),
                ).fetchone()
            elif token_limit < (
                int(row["used_tokens"]) + int(row["reserved_tokens"])
            ):
                raise ValueError(
                    "token_limit cannot be below used plus reserved tokens"
                )
            elif (
                int(row["token_limit"])
                if row["token_limit"] is not None
                else None
            ) != token_limit:
                row = conn.execute(
                    """
                    UPDATE agent_budget_periods
                    SET token_limit=?, revision=revision+1
                    WHERE period_id=?
                    RETURNING *
                    """,
                    (token_limit, row["period_id"]),
                ).fetchone()
        assert row is not None
        return budget_period_value(row)

    def reset_budget_period(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int | None = None,
    ) -> dict[str, Any]:
        require_text("owner_user_id", owner_user_id)
        require_text("agent_id", agent_id)
        if token_limit is not None and (
            not isinstance(token_limit, int)
            or isinstance(token_limit, bool)
            or token_limit <= 0
        ):
            raise ValueError("token_limit must be a positive integer or null")
        now = time.time()
        with connect_agent_flow(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=? AND status='open'
                """,
                (owner_user_id, agent_id),
            ).fetchone()
            if current is not None and int(current["reserved_tokens"]) > 0:
                row = conn.execute(
                    """
                    UPDATE agent_budget_periods
                    SET reset_pending=1, next_token_limit=?,
                        reset_requested_at=?, revision=revision+1
                    WHERE period_id=?
                    RETURNING *
                    """,
                    (token_limit, now, current["period_id"]),
                ).fetchone()
            else:
                if current is not None:
                    conn.execute(
                        """
                        UPDATE agent_budget_periods
                        SET status='closed', closed_at=?,
                            revision=revision+1
                        WHERE period_id=?
                        """,
                        (now, current["period_id"]),
                    )
                row = self.insert_open_period(
                    conn,
                    owner_user_id=owner_user_id,
                    agent_id=agent_id,
                    token_limit=token_limit,
                    now=now,
                )
        assert row is not None
        return budget_period_value(row)

    def list_budget_periods(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        with connect_agent_flow(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=?
                ORDER BY created_at DESC, period_id DESC
                """,
                (owner_user_id, agent_id),
            ).fetchall()
        return [budget_period_value(row) for row in rows]

    def load_current_budget_period(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> dict[str, Any] | None:
        with connect_agent_flow(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_budget_periods
                WHERE owner_user_id=? AND agent_id=? AND status='open'
                """,
                (owner_user_id, agent_id),
            ).fetchone()
        return budget_period_value(row) if row is not None else None

    @staticmethod
    def load_or_create_open_period(
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        agent_id: str,
        now: float,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT * FROM agent_budget_periods
            WHERE owner_user_id=? AND agent_id=? AND status='open'
            """,
            (owner_user_id, agent_id),
        ).fetchone()
        if row is not None:
            return row
        return BudgetPeriods.insert_open_period(
            conn,
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            token_limit=None,
            now=now,
        )

    @staticmethod
    def insert_open_period(
        conn: sqlite3.Connection,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int | None,
        now: float,
    ) -> sqlite3.Row:
        return conn.execute(
            """
            INSERT INTO agent_budget_periods (
                period_id, owner_user_id, agent_id, token_limit,
                used_tokens, reserved_tokens, charging_policy_version,
                revision, status, created_at
            ) VALUES (?, ?, ?, ?, 0, 0, ?, 1, 'open', ?)
            RETURNING *
            """,
            (
                uuid.uuid4().hex,
                owner_user_id,
                agent_id,
                token_limit,
                CHARGING_POLICY_VERSION,
                now,
            ),
        ).fetchone()

    @staticmethod
    def finish_pending_reset(
        conn: sqlite3.Connection,
        *,
        period_row: sqlite3.Row,
        now: float,
    ) -> None:
        closed = conn.execute(
            """
            UPDATE agent_budget_periods
            SET status='closed', closed_at=?,
                reset_pending=0, next_token_limit=NULL,
                reset_requested_at=NULL, revision=revision+1
            WHERE period_id=? AND reserved_tokens=0 AND reset_pending=1
            RETURNING period_id
            """,
            (now, period_row["period_id"]),
        ).fetchone()
        if closed is None:
            return
        BudgetPeriods.insert_open_period(
            conn,
            owner_user_id=str(period_row["period_owner_user_id"]),
            agent_id=str(period_row["period_agent_id"]),
            token_limit=period_row["next_token_limit"],
            now=now,
        )


def budget_period_value(row: sqlite3.Row) -> dict[str, Any]:
    token_limit = (
        int(row["token_limit"]) if row["token_limit"] is not None else None
    )
    used_tokens = int(row["used_tokens"])
    reserved_tokens = int(row["reserved_tokens"])
    value = {
        "period_id": str(row["period_id"]),
        "owner_user_id": str(row["owner_user_id"]),
        "agent_id": str(row["agent_id"]),
        "token_limit": token_limit,
        "used_tokens": used_tokens,
        "reserved_tokens": reserved_tokens,
        "available_tokens": (
            max(token_limit - used_tokens - reserved_tokens, 0)
            if token_limit is not None else None
        ),
        "charging_policy_version": str(row["charging_policy_version"]),
        "revision": int(row["revision"]),
        "status": str(row["status"]),
    }
    if bool(row["reset_pending"]):
        value["reset_pending"] = True
        value["next_token_limit"] = (
            int(row["next_token_limit"])
            if row["next_token_limit"] is not None else None
        )
    return value
