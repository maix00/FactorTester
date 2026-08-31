"""Auditable Evidence exclusion and restoration outside immutable identity."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from .schema import bump_catalog_revision, ensure_schema
from .validation import canonical, required_text

_ACTIONS = {
    "exclude": ("active", "excluded"),
    "restore": ("excluded", "active"),
}


def prepare_lifecycle_transition(
    *,
    owner: str,
    evidence_ref: str,
    action: str,
    reason_zh: str,
    profile_ref: str,
    agent_id: str,
    instance_id: str,
    branch_id: str,
    parent_id: str,
) -> dict[str, Any]:
    """Reserve a transition without changing discovery or admission state."""
    if action not in _ACTIONS:
        raise ValueError("evidence lifecycle action must be exclude or restore")
    reason = required_text(
        reason_zh, "reason_zh", maximum=1000, chinese=True,
    )
    profile = required_text(profile_ref, "profile_ref", maximum=256)
    agent = required_text(agent_id, "agent_id", maximum=256)
    instance = required_text(instance_id, "instance_id", maximum=256)
    branch = required_text(branch_id, "branch_id", maximum=256)
    parent = required_text(parent_id, "parent_id", maximum=256)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        _require_owned_evidence(conn, owner, evidence_ref)
        _require_owned_branch(conn, owner, instance, branch)
        expected, target = _ACTIONS[action]
        payload = {
            "owner": owner,
            "evidence_ref": evidence_ref,
            "action": action,
            "from_status": expected,
            "to_status": target,
            "reason_zh": reason,
            "profile_ref": profile,
            "agent_id": agent,
            "instance_id": instance,
            "branch_id": branch,
            "parent_id": parent,
        }
        transition_ref = (
            "evidence-lifecycle:sha256:"
            + hashlib.sha256(canonical(payload).encode()).hexdigest()
        )
        existing = conn.execute(
            """SELECT * FROM research_evidence_lifecycle_transitions
               WHERE transition_ref=? AND owner=?""",
            (transition_ref, owner),
        ).fetchone()
        if existing is not None:
            return _transition_row(existing)
        current = _current_status(conn, owner, evidence_ref)
        if current != expected:
            raise ValueError(
                f"cannot {action} Evidence in {current} status"
            )
        now = time.time()
        conn.execute(
            """INSERT OR IGNORE INTO research_evidence_lifecycle_transitions
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared',
                       '{}', ?, ?)""",
            (
                transition_ref, owner, evidence_ref, action, expected, target,
                reason, profile, agent, instance, branch, parent, now, now,
            ),
        )
        row = conn.execute(
            """SELECT * FROM research_evidence_lifecycle_transitions
               WHERE transition_ref=? AND owner=?""",
            (transition_ref, owner),
        ).fetchone()
    return _transition_row(row)


def finalize_lifecycle_transition(
    *,
    owner: str,
    transition_ref: str,
    report_receipt: Any,
) -> dict[str, Any]:
    """Apply one prepared transition only after its report/Git receipt exists."""
    receipt = _report_receipt(report_receipt)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """SELECT * FROM research_evidence_lifecycle_transitions
               WHERE transition_ref=? AND owner=?""",
            (transition_ref, owner),
        ).fetchone()
        if row is None:
            raise KeyError("evidence lifecycle transition not found")
        if row["status"] == "accepted":
            stored = json.loads(row["report_receipt_json"])
            if stored != receipt:
                raise ValueError(
                    "accepted evidence lifecycle receipt does not match"
                )
            return _lifecycle_result(conn, row)
        if row["status"] != "prepared":
            raise ValueError("evidence lifecycle transition is not prepared")
        current = _current_status(conn, owner, row["evidence_ref"])
        if current != row["from_status"]:
            raise ValueError("evidence lifecycle projection is stale")
        now = time.time()
        conn.execute(
            """INSERT INTO research_evidence_lifecycle
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(owner, evidence_ref) DO UPDATE SET
                 status=excluded.status,
                 latest_transition_ref=excluded.latest_transition_ref,
                 updated_at=excluded.updated_at""",
            (
                owner, row["evidence_ref"], row["to_status"],
                transition_ref, now,
            ),
        )
        conn.execute(
            """UPDATE research_evidence_lifecycle_transitions
               SET status='accepted', report_receipt_json=?, updated_at=?
               WHERE transition_ref=? AND owner=?""",
            (canonical(receipt), now, transition_ref, owner),
        )
        bump_catalog_revision(conn, owner)
        accepted = conn.execute(
            """SELECT * FROM research_evidence_lifecycle_transitions
               WHERE transition_ref=? AND owner=?""",
            (transition_ref, owner),
        ).fetchone()
        return _lifecycle_result(conn, accepted)


def get_evidence_lifecycle(
    *, owner: str, evidence_ref: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        _require_owned_evidence(conn, owner, evidence_ref)
        status = _current_status(conn, owner, evidence_ref)
        row = conn.execute(
            """SELECT * FROM research_evidence_lifecycle_transitions
               WHERE owner=? AND evidence_ref=? AND status='accepted'
               ORDER BY updated_at DESC LIMIT 1""",
            (owner, evidence_ref),
        ).fetchone()
    return {
        "status": status,
        "latest_transition": (
            _transition_row(row) if row is not None else None
        ),
    }


def require_active_evidence(conn, *, owner: str, evidence_ref: str) -> None:
    ensure_schema(conn)
    if _current_status(conn, owner, evidence_ref) != "active":
        raise ValueError("excluded Evidence cannot be admitted or reused")


def _current_status(conn, owner: str, evidence_ref: str) -> str:
    row = conn.execute(
        """SELECT status FROM research_evidence_lifecycle
           WHERE owner=? AND evidence_ref=?""",
        (owner, evidence_ref),
    ).fetchone()
    return str(row["status"]) if row is not None else "active"


def _require_owned_evidence(conn, owner: str, evidence_ref: str) -> None:
    row = conn.execute(
        """SELECT 1 FROM research_fragment_evidence_objects
           WHERE evidence_ref=? AND owner=? LIMIT 1""",
        (evidence_ref, owner),
    ).fetchone()
    if row is None and conn.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='research_evidence_objects'"""
    ).fetchone() is not None:
        row = conn.execute(
            """SELECT 1 FROM research_evidence_objects
               WHERE evidence_ref=? AND owner=? LIMIT 1""",
            (evidence_ref, owner),
        ).fetchone()
    if row is None:
        raise KeyError("research evidence not found")


def _require_owned_branch(
    conn, owner: str, instance_id: str, branch_id: str,
) -> None:
    try:
        row = conn.execute(
            """SELECT 1 FROM research_graph_instances i
               JOIN research_graph_branches b
                 ON b.instance_id=i.instance_id
               WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?
               LIMIT 1""",
            (owner, instance_id, branch_id),
        ).fetchone()
    except Exception as exc:
        raise KeyError("research Graph branch is unavailable") from exc
    if row is None:
        raise KeyError("research Graph branch not found")


def _report_receipt(value: Any) -> dict[str, Any]:
    required = {
        "submission_sequence", "component_id", "git_commit",
        "ledger_generation", "ledger_projection_hash",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("evidence lifecycle report receipt fields are invalid")
    sequence = value["submission_sequence"]
    generation = value["ledger_generation"]
    if (
        not isinstance(sequence, int) or sequence < 1
        or not isinstance(generation, int) or generation < 1
    ):
        raise ValueError("evidence lifecycle report receipt is invalid")
    for field in ("component_id", "git_commit", "ledger_projection_hash"):
        required_text(value[field], field, maximum=256)
    return dict(value)


def _transition_row(row) -> dict[str, Any]:
    return {
        "transition_ref": str(row["transition_ref"]),
        "evidence_ref": str(row["evidence_ref"]),
        "action": str(row["action"]),
        "from_status": str(row["from_status"]),
        "to_status": str(row["to_status"]),
        "reason_zh": str(row["reason_zh"]),
        "profile_ref": str(row["profile_ref"]),
        "agent_id": str(row["agent_id"]),
        "instance_id": str(row["instance_id"]),
        "branch_id": str(row["branch_id"]),
        "parent_id": str(row["parent_id"]),
        "status": str(row["status"]),
        "report_receipt": json.loads(row["report_receipt_json"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _lifecycle_result(conn, row) -> dict[str, Any]:
    return {
        "status": str(row["to_status"]),
        "transition": _transition_row(row),
    }
