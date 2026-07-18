"""SQLite schema and connection policy for Agent Flow."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.data.sqlite.db import connect_sqlite


def connect_agent_flow(db_path: str | Path) -> sqlite3.Connection:
    return connect_sqlite(db_path, foreign_keys=True)


def ensure_schema(db_path: str | Path) -> None:
    with connect_agent_flow(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_budget_periods (
                period_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                token_limit INTEGER CHECK (
                    token_limit IS NULL OR token_limit > 0
                ),
                used_tokens INTEGER NOT NULL DEFAULT 0 CHECK (used_tokens >= 0),
                reserved_tokens INTEGER NOT NULL DEFAULT 0
                    CHECK (reserved_tokens >= 0),
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
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_budget_open_period
            ON agent_budget_periods(owner_user_id, agent_id)
            WHERE status='open';

            CREATE TABLE IF NOT EXISTS agent_invocations (
                invocation_id TEXT PRIMARY KEY,
                period_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                legacy_reservation_id TEXT NOT NULL DEFAULT '',
                legacy_provider_receipt_id TEXT NOT NULL DEFAULT '',
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
                max_output_tokens INTEGER NOT NULL
                    CHECK (max_output_tokens >= 0),
                reserved_tokens INTEGER NOT NULL CHECK (
                    reserved_tokens > 0
                    AND reserved_tokens=max_input_tokens+max_output_tokens
                ),
                reservation_expires_at REAL,
                input_tokens INTEGER CHECK (
                    input_tokens IS NULL OR input_tokens >= 0
                ),
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
            );
            CREATE INDEX IF NOT EXISTS idx_agent_invocations_owner
            ON agent_invocations(
                owner_user_id, agent_id, period_id, created_at
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_invocation_request
            ON agent_invocations(owner_user_id, agent_id, idempotency_key)
            WHERE idempotency_key<>'';
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_provider_request
            ON agent_invocations(owner_user_id, provider_request_hash)
            WHERE provider_request_hash<>'';
            CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_legacy_reservation
            ON agent_invocations(legacy_reservation_id)
            WHERE legacy_reservation_id<>'';
            """
        )
