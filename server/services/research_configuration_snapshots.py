"""Immutable Run Configuration Snapshots within one Research Workspace."""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_configurations import validate_payload
from tools.data.sqlite.db import connect_sqlite


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_configuration_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            snapshot_revision INTEGER NOT NULL,
            name TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            source_workspace_id TEXT NOT NULL,
            source_configuration_id TEXT NOT NULL,
            source_configuration_revision INTEGER NOT NULL,
            source_configuration_fingerprint TEXT NOT NULL,
            created_at REAL NOT NULL,
            deleted_at REAL,
            UNIQUE(owner, workspace_id, name, fingerprint)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_config_snapshot_workspace
        ON research_configuration_snapshots(
            owner, workspace_id, created_at, snapshot_id
        )
        """
    )


def create_snapshot(
    *,
    owner: str,
    workspace_id: str,
    source_workspace_id: str,
    source_configuration_id: str,
    source_configuration_revision: int,
    name: str,
) -> dict[str, Any]:
    label = str(name or "").strip()
    if not label:
        raise ValueError("configuration snapshot name is required")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute(
            """
            SELECT 1 FROM research_workspaces
            WHERE workspace_id=? AND owner=? AND deleted_at IS NULL
            """,
            (workspace_id, owner),
        ).fetchone()
        if target is None:
            raise KeyError("target research workspace not found")
        source = conn.execute(
            """
            SELECT configuration_id, workspace_id, schema_version, revision,
                   payload_json
            FROM research_configurations
            WHERE configuration_id=? AND workspace_id=? AND owner=?
              AND role='workspace' AND deleted_at IS NULL
            """,
            (source_configuration_id, source_workspace_id, owner),
        ).fetchone()
        if source is None:
            raise KeyError("source workspace configuration not found")
        if int(source["revision"]) != int(source_configuration_revision):
            raise ValueError("source workspace configuration revision changed")
        payload = validate_payload(orjson.loads(source["payload_json"]))
        encoded = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        fingerprint = hashlib.sha256(encoded).hexdigest()
        snapshot_id = uuid.uuid4().hex
        now = time.time()
        try:
            conn.execute(
                """
                INSERT INTO research_configuration_snapshots (
                    snapshot_id, owner, workspace_id, snapshot_revision,
                    name, schema_version, payload_json, fingerprint,
                    source_workspace_id, source_configuration_id,
                    source_configuration_revision,
                    source_configuration_fingerprint, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    owner,
                    workspace_id,
                    label,
                    int(source["schema_version"]),
                    encoded.decode(),
                    fingerprint,
                    source_workspace_id,
                    source_configuration_id,
                    int(source["revision"]),
                    fingerprint,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "identical named configuration snapshot already exists"
            ) from exc
    return {
        "snapshot_id": snapshot_id,
        "owner": owner,
        "workspace_id": workspace_id,
        "snapshot_revision": 1,
        "name": label,
        "schema_version": int(source["schema_version"]),
        "payload": payload,
        "fingerprint": fingerprint,
        "source_provenance": {
            "workspace_id": source_workspace_id,
            "configuration_id": source_configuration_id,
            "configuration_revision": int(source["revision"]),
            "configuration_fingerprint": fingerprint,
        },
        "created_at": now,
    }


def load_snapshot(
    *,
    owner: str,
    workspace_id: str,
    snapshot_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT * FROM research_configuration_snapshots
            WHERE snapshot_id=? AND workspace_id=? AND owner=?
              AND deleted_at IS NULL
            """,
            (snapshot_id, workspace_id, owner),
        ).fetchone()
    if row is None:
        raise KeyError("configuration snapshot not found")
    if int(row["snapshot_revision"]) != int(expected_revision):
        raise ValueError("configuration snapshot revision changed")
    return _row_payload(row)


def list_snapshots(*, owner: str, workspace_id: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM research_configuration_snapshots
            WHERE workspace_id=? AND owner=? AND deleted_at IS NULL
            ORDER BY created_at, snapshot_id
            """,
            (workspace_id, owner),
        ).fetchall()
    return [_row_payload(row) for row in rows]


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "snapshot_id": str(row["snapshot_id"]),
        "owner": str(row["owner"]),
        "workspace_id": str(row["workspace_id"]),
        "snapshot_revision": int(row["snapshot_revision"]),
        "name": str(row["name"]),
        "schema_version": int(row["schema_version"]),
        "payload": orjson.loads(row["payload_json"]),
        "fingerprint": str(row["fingerprint"]),
        "source_provenance": {
            "workspace_id": str(row["source_workspace_id"]),
            "configuration_id": str(row["source_configuration_id"]),
            "configuration_revision": int(
                row["source_configuration_revision"]
            ),
            "configuration_fingerprint": str(
                row["source_configuration_fingerprint"]
            ),
        },
        "created_at": float(row["created_at"]),
    }
