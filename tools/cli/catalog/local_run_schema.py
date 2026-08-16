"""Additive SQLite schema for client-owned local test runs and outbox rows."""

from __future__ import annotations

import sqlite3


LOCAL_RUN_SCHEMA_VERSION = 1


def ensure_local_run_schema(connection: sqlite3.Connection) -> None:
    """Create local-run tables without changing the catalog schema version.

    The product/factor catalog has its own compatibility contract.  Local runs
    are an additive feature, so an older catalog can be upgraded in place
    without rewriting any existing catalog rows or changing ``user_version``.
    """
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS local_runs (
            local_job_id TEXT PRIMARY KEY,
            owner_ref TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'test',
            status TEXT NOT NULL DEFAULT 'queued',
            execution_mode TEXT NOT NULL DEFAULT 'local',
            workspace_id TEXT NOT NULL DEFAULT '',
            profile_ref TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            requirements_json TEXT NOT NULL DEFAULT '[]',
            configuration_json TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}',
            source_snapshot_json TEXT NOT NULL DEFAULT '{}',
            metadata_hash TEXT NOT NULL,
            sync_state TEXT NOT NULL DEFAULT 'pending'
                CHECK (sync_state IN ('local', 'pending', 'synced', 'error')),
            last_sync_error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_local_runs_owner_updated
            ON local_runs(owner_ref, updated_at DESC, local_job_id);

        CREATE TABLE IF NOT EXISTS local_run_artifacts (
            local_job_id TEXT NOT NULL REFERENCES local_runs(local_job_id)
                ON DELETE CASCADE,
            name TEXT NOT NULL,
            file_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'output'
                CHECK (role IN ('input', 'output')),
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
            content_hash TEXT NOT NULL DEFAULT '',
            local_path TEXT NOT NULL DEFAULT '',
            upload_state TEXT NOT NULL DEFAULT 'local_only'
                CHECK (upload_state IN ('local_only', 'pending', 'uploaded', 'error')),
            updated_at REAL NOT NULL,
            PRIMARY KEY (local_job_id, name)
        );

        CREATE TABLE IF NOT EXISTS local_run_outbox (
            operation_id TEXT PRIMARY KEY,
            local_job_id TEXT NOT NULL REFERENCES local_runs(local_job_id)
                ON DELETE CASCADE,
            operation_kind TEXT NOT NULL
                CHECK (operation_kind IN ('sync_summary', 'upload_artifact')),
            payload_json TEXT NOT NULL,
            projection_hash TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'sending', 'synced', 'error')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_error TEXT NOT NULL DEFAULT '',
            UNIQUE (local_job_id, operation_kind, projection_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_local_run_outbox_pending
            ON local_run_outbox(state, updated_at, operation_id);
        """
    )


__all__ = ["LOCAL_RUN_SCHEMA_VERSION", "ensure_local_run_schema"]
