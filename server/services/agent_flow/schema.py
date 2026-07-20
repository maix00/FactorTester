"""SQLite schema and fail-closed connection policy for Agent Flow."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.data.sqlite.db import connect_sqlite


AGENT_FLOW_OWNER_TABLES = frozenset({
    "agent_budget_periods",
    "agent_invocations",
})
LEGACY_INVOCATION_COLUMNS = frozenset({
    "legacy_reservation_id",
    "legacy_provider_receipt_id",
})
AGENT_BUDGET_PERIOD_COLUMNS = frozenset({
    "period_id",
    "owner_user_id",
    "agent_id",
    "token_limit",
    "used_tokens",
    "reserved_tokens",
    "charging_policy_version",
    "revision",
    "status",
    "reset_pending",
    "next_token_limit",
    "reset_requested_at",
    "created_at",
    "closed_at",
})
AGENT_INVOCATION_COLUMNS = frozenset({
    "invocation_id",
    "period_id",
    "owner_user_id",
    "agent_id",
    "idempotency_key",
    "request_hash",
    "sponsor_agent_id",
    "actor_role",
    "authority_scope",
    "task_ref",
    "purpose",
    "runtime_id",
    "model_id",
    "provider_id",
    "agent_principal_hash",
    "lineage_hash",
    "launcher_attestation_hash",
    "input_hash",
    "max_input_tokens",
    "max_output_tokens",
    "reserved_tokens",
    "reservation_expires_at",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "charged_tokens",
    "measurement_quality",
    "provider_request_hash",
    "provider_attestation_hash",
    "context_cost_json",
    "status",
    "created_at",
    "settled_at",
})


def connect_agent_flow(db_path: str | Path) -> sqlite3.Connection:
    return connect_sqlite(db_path, foreign_keys=True)


def ensure_schema(db_path: str | Path) -> None:
    """Create a fresh schema or reject any existing non-final layout."""
    with connect_agent_flow(db_path) as conn:
        tables = _owner_tables(conn)
        if not tables:
            create_schema(conn)
            return
        if tables != AGENT_FLOW_OWNER_TABLES:
            raise RuntimeError(
                "non-final Agent Flow owner schema requires the explicit "
                "finalize_active_graph_cutover migration"
            )
        invocation_columns = table_columns(conn, "agent_invocations")
        if LEGACY_INVOCATION_COLUMNS.intersection(invocation_columns):
            raise RuntimeError(
                "legacy Agent Flow invocation columns require the explicit "
                "finalize_active_graph_cutover migration"
            )
        if (
            invocation_columns != AGENT_INVOCATION_COLUMNS
            or table_columns(conn, "agent_budget_periods")
            != AGENT_BUDGET_PERIOD_COLUMNS
        ):
            raise RuntimeError(
                "non-final Agent Flow columns require the explicit "
                "finalize_active_graph_cutover migration"
            )


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the final two-owner schema without implicit transaction commits."""
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)


def table_columns(
    conn: sqlite3.Connection,
    table: str,
) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _owner_tables(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    )


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_budget_periods (
        period_id TEXT PRIMARY KEY,
        owner_user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        token_limit INTEGER CHECK (token_limit IS NULL OR token_limit > 0),
        used_tokens INTEGER NOT NULL DEFAULT 0 CHECK (used_tokens >= 0),
        reserved_tokens INTEGER NOT NULL DEFAULT 0 CHECK (reserved_tokens >= 0),
        charging_policy_version TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
        status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
        reset_pending INTEGER NOT NULL DEFAULT 0
            CHECK (reset_pending IN (0, 1)),
        next_token_limit INTEGER CHECK (
            next_token_limit IS NULL OR next_token_limit > 0
        ),
        reset_requested_at REAL,
        created_at REAL NOT NULL,
        closed_at REAL,
        UNIQUE (period_id, owner_user_id, agent_id),
        CHECK (
            (status='open' AND closed_at IS NULL)
            OR (status='closed' AND closed_at IS NOT NULL)
        ),
        CHECK (
            reset_pending=1
            OR (next_token_limit IS NULL AND reset_requested_at IS NULL)
        )
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_budget_open_period
    ON agent_budget_periods(owner_user_id, agent_id)
    WHERE status='open'
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_invocations (
        invocation_id TEXT PRIMARY KEY,
        period_id TEXT NOT NULL,
        owner_user_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL DEFAULT '',
        request_hash TEXT NOT NULL DEFAULT '',
        sponsor_agent_id TEXT NOT NULL DEFAULT '',
        actor_role TEXT NOT NULL,
        authority_scope TEXT NOT NULL,
        task_ref TEXT NOT NULL DEFAULT '',
        purpose TEXT NOT NULL,
        runtime_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        provider_id TEXT NOT NULL DEFAULT '',
        agent_principal_hash TEXT NOT NULL,
        lineage_hash TEXT NOT NULL,
        launcher_attestation_hash TEXT NOT NULL DEFAULT '',
        input_hash TEXT NOT NULL DEFAULT '',
        max_input_tokens INTEGER NOT NULL CHECK (max_input_tokens >= 0),
        max_output_tokens INTEGER NOT NULL CHECK (max_output_tokens >= 0),
        reserved_tokens INTEGER NOT NULL CHECK (
            reserved_tokens > 0
            AND reserved_tokens=max_input_tokens+max_output_tokens
        ),
        reservation_expires_at REAL,
        input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
        output_tokens INTEGER CHECK (
            output_tokens IS NULL OR output_tokens >= 0
        ),
        cache_read_tokens INTEGER CHECK (
            cache_read_tokens IS NULL OR cache_read_tokens >= 0
        ),
        charged_tokens INTEGER CHECK (
            charged_tokens IS NULL OR charged_tokens >= 0
        ),
        measurement_quality TEXT NOT NULL DEFAULT '',
        provider_request_hash TEXT NOT NULL DEFAULT '',
        provider_attestation_hash TEXT NOT NULL DEFAULT '',
        context_cost_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL CHECK (
            status IN ('reserved', 'settled', 'released')
        ),
        created_at REAL NOT NULL,
        settled_at REAL,
        FOREIGN KEY (period_id, owner_user_id, agent_id)
            REFERENCES agent_budget_periods(
                period_id, owner_user_id, agent_id
            ),
        CHECK (
            (status='reserved' AND settled_at IS NULL)
            OR (status IN ('settled', 'released') AND settled_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_invocations_owner
    ON agent_invocations(owner_user_id, agent_id, period_id, created_at)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_invocation_request
    ON agent_invocations(owner_user_id, agent_id, idempotency_key)
    WHERE idempotency_key<>''
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_provider_request
    ON agent_invocations(owner_user_id, provider_request_hash)
    WHERE provider_request_hash<>''
    """,
)
