"""Evidence status changes owned by Evidence, independent of a research path."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .schema import bump_catalog_revision, ensure_schema
from .validation import canonical, required_text

_ACTIONS = {"exclude": ("active", "excluded"), "restore": ("excluded", "active")}


def change_evidence_status(
    *, owner: str, evidence_ref: str, action: str, reason_zh: str,
    profile_ref: str, operation_id: str,
) -> dict[str, Any]:
    """Apply one idempotent status event in the Evidence catalog transaction."""
    if action not in _ACTIONS:
        raise ValueError("evidence status action must be exclude or restore")
    reason = required_text(reason_zh, "reason_zh", maximum=1000, chinese=True)
    profile = required_text(profile_ref, "profile_ref", maximum=256)
    operation = required_text(operation_id, "operation_id", maximum=128)
    event_ref = "evidence-status:sha256:" + hashlib.sha256(
        canonical({"owner": owner, "evidence_ref": evidence_ref,
                   "operation_id": operation}).encode()
    ).hexdigest()
    payload = {"evidence_ref": evidence_ref, "action": action,
               "reason_zh": reason, "profile_ref": profile,
               "operation_id": operation}
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        _require_owned_evidence(conn, owner, evidence_ref)
        previous = conn.execute(
            "SELECT payload_json FROM research_evidence_status_events "
            "WHERE event_ref=? AND owner=?", (event_ref, owner),
        ).fetchone()
        if previous is not None:
            if json.loads(previous["payload_json"]) != payload:
                raise ValueError("evidence status operation identity conflicts")
            return _lifecycle(conn, owner, evidence_ref)
        expected, target = _ACTIONS[action]
        if _current_status(conn, owner, evidence_ref) != expected:
            raise ValueError(f"cannot {action} Evidence outside {expected} status")
        now = time.time()
        conn.execute(
            "INSERT INTO research_evidence_status_events "
            "(event_ref, owner, evidence_ref, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_ref, owner, evidence_ref, canonical(payload), now),
        )
        conn.execute(
            "INSERT INTO research_evidence_lifecycle "
            "(owner, evidence_ref, status, latest_transition_ref, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(owner, evidence_ref) DO UPDATE SET "
            "status=excluded.status, latest_transition_ref=excluded.latest_transition_ref, "
            "updated_at=excluded.updated_at",
            (owner, evidence_ref, target, event_ref, now),
        )
        bump_catalog_revision(conn, owner)
        return _lifecycle(conn, owner, evidence_ref)


def get_evidence_lifecycle(*, owner: str, evidence_ref: str) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        _require_owned_evidence(conn, owner, evidence_ref)
        return _lifecycle(conn, owner, evidence_ref)


def require_active_evidence(conn, *, owner: str, evidence_ref: str) -> None:
    ensure_schema(conn)
    if _current_status(conn, owner, evidence_ref) != "active":
        raise ValueError("excluded Evidence cannot be admitted or reused")


def _lifecycle(conn, owner: str, evidence_ref: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT event_ref, payload_json, created_at FROM "
        "research_evidence_status_events WHERE owner=? AND evidence_ref=? "
        "ORDER BY created_at DESC, event_ref DESC LIMIT 1",
        (owner, evidence_ref),
    ).fetchone()
    latest = None if row is None else {
        "event_ref": str(row["event_ref"]),
        **json.loads(row["payload_json"]),
        "created_at": float(row["created_at"]),
    }
    return {"status": _current_status(conn, owner, evidence_ref),
            "latest_transition": latest}


def _current_status(conn, owner: str, evidence_ref: str) -> str:
    row = conn.execute(
        "SELECT status FROM research_evidence_lifecycle "
        "WHERE owner=? AND evidence_ref=?", (owner, evidence_ref),
    ).fetchone()
    return str(row["status"]) if row is not None else "active"


def _require_owned_evidence(conn, owner: str, evidence_ref: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM research_fragment_evidence_objects "
        "WHERE evidence_ref=? AND owner=? LIMIT 1", (evidence_ref, owner),
    ).fetchone()
    if row is None and conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='research_evidence_objects'"
    ).fetchone() is not None:
        row = conn.execute(
            "SELECT 1 FROM research_evidence_objects "
            "WHERE evidence_ref=? AND owner=? LIMIT 1",
            (evidence_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("research evidence not found")
