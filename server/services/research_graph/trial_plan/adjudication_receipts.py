"""Append-only persistence for audited TrialPlan Evidence Actions."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import orjson

from ..protocol import json_hash
from ..research_cycle.adjudication import validate_adjudication_pair
from .contract import trial_plan_hash
from .execution_checkpoint_contract import (
    validate_checkpoint_plan_identity,
    validate_execution_checkpoint,
)


def ensure_action_adjudication_receipt_table(
    conn: sqlite3.Connection,
) -> None:
    """Create the append-only receipt store without reading existing rows."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trial_plan_action_adjudication_receipts (
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            trial_plan_hash TEXT NOT NULL,
            action_id TEXT NOT NULL,
            audit_ref TEXT NOT NULL,
            proposal_hash TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (
                instance_id, branch_id, trial_plan_hash, action_id
            ),
            UNIQUE (instance_id, branch_id, decision_id)
        )
        """
    )


def build_action_adjudication_receipt(
    *,
    instance_id: str,
    branch_id: str,
    trial_plan: dict[str, Any],
    checkpoint: dict[str, Any],
    proposal: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Validate a current or historical audited checkpoint and its cold pair."""
    current = validate_execution_checkpoint(checkpoint)
    plan = validate_checkpoint_plan_identity(current, trial_plan)
    if current["current_action_status"] != "audited":
        raise ValueError("adjudication receipt requires an audited checkpoint")
    validated_proposal, validated_decision = validate_adjudication_pair(
        proposal,
        decision,
        expected_contract_hash=plan["decision_contract_hash"],
        expected_trial_plan_hash=trial_plan_hash(plan),
        expected_methodology_hash=plan["methodology_hash"],
    )
    decision_id = validated_decision["decision_id"]
    if current["current_action_audit_ref"] != f"adjudication:{decision_id}":
        raise ValueError("checkpoint audit_ref does not match decision_id")
    if current["current_action_audit_disposition"] != validated_decision[
        "disposition"
    ]:
        raise ValueError("checkpoint audit disposition does not match decision")
    if current["current_action_audit_route"] != validated_proposal[
        "recommended_action"
    ]:
        raise ValueError("checkpoint audit route does not match proposal")
    if set(current["current_action_output_evidence_refs"]) != set(
        validated_proposal["evidence_refs"]
    ):
        raise ValueError("checkpoint Evidence refs do not match proposal")
    receipt = {
        "schema_version": 1,
        "instance_id": instance_id,
        "branch_id": branch_id,
        "trial_plan_hash": trial_plan_hash(plan),
        "action_id": current["current_action_id"],
        "audit_ref": current["current_action_audit_ref"],
        "contract_hash": plan["decision_contract_hash"],
        "methodology_hash": plan["methodology_hash"],
        "evidence_refs": sorted(validated_proposal["evidence_refs"]),
        "proposal_hash": validated_proposal["proposal_hash"],
        "decision_id": decision_id,
        "proposal": validated_proposal,
        "decision": validated_decision,
    }
    return {**receipt, "receipt_hash": json_hash(receipt)}


def persist_action_adjudication_receipt(
    conn: sqlite3.Connection,
    receipt: dict[str, Any],
) -> None:
    """Insert one receipt; primary and decision identities cannot be replaced."""
    ensure_action_adjudication_receipt_table(conn)
    conn.execute(
        """
        INSERT INTO trial_plan_action_adjudication_receipts (
            instance_id, branch_id, trial_plan_hash, action_id, audit_ref,
            proposal_hash, decision_id, receipt_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt["instance_id"],
            receipt["branch_id"],
            receipt["trial_plan_hash"],
            receipt["action_id"],
            receipt["audit_ref"],
            receipt["proposal_hash"],
            receipt["decision_id"],
            orjson.dumps(receipt, option=orjson.OPT_SORT_KEYS).decode(),
            time.time(),
        ),
    )


def backfill_action_adjudication_receipt(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    trial_plan: dict[str, Any],
    checkpoint: dict[str, Any],
    proposal: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Explicitly validate and append one current or historical receipt."""
    receipt = build_action_adjudication_receipt(
        instance_id=instance_id,
        branch_id=branch_id,
        trial_plan=trial_plan,
        checkpoint=checkpoint,
        proposal=proposal,
        decision=decision,
    )
    persist_action_adjudication_receipt(conn, receipt)
    return receipt


def load_action_adjudication_receipt(
    conn: sqlite3.Connection,
    instance_id: str,
    branch_id: str,
    trial_plan_hash: str,
    action_id: str,
) -> dict[str, Any] | None:
    """Load one receipt using only the caller-owned connection."""
    try:
        row = conn.execute(
            """
            SELECT receipt_json
            FROM trial_plan_action_adjudication_receipts
            WHERE instance_id=? AND branch_id=?
              AND trial_plan_hash=? AND action_id=?
            """,
            (instance_id, branch_id, trial_plan_hash, action_id),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return None
    return None if row is None else orjson.loads(row["receipt_json"])
