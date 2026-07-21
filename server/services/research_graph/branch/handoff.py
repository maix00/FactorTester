"""Atomic Profile handoff at a verified Research Cycle checkpoint."""

from __future__ import annotations

from copy import deepcopy
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch.profile_identity import (
    validate_authorization_ref,
    validate_profile_ref,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.protocol import serialize_bounded_trace_evidence
from tools.data.sqlite.db import connect_sqlite


def handoff_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    source_profile_ref: str,
    destination_profile_ref: str,
    expected_checkpoint_ref: str,
    expected_checkpoint_hash: str,
    authorization_ref: str,
    source_display_name: str = "",
    destination_display_name: str = "",
) -> dict[str, Any]:
    """Transfer one Work Package owner without adding a handoff table.

    The instance row is the sole mutable ownership projection.  The existing
    append-only trace is the audit record, and the compare-and-swap check under
    ``BEGIN IMMEDIATE`` prevents an old Profile from resuming after transfer.
    """
    source_profile_ref = validate_profile_ref(source_profile_ref)
    destination_profile_ref = validate_profile_ref(
        destination_profile_ref,
        field="destination_profile_ref",
    )
    if source_profile_ref == destination_profile_ref:
        raise ValueError("destination Profile must differ from source Profile")
    expected_checkpoint_ref = _checkpoint_ref(expected_checkpoint_ref)
    expected_checkpoint_hash = _hash(expected_checkpoint_hash)
    authorization_ref = validate_authorization_ref(authorization_ref)
    source_display_name = _display_name(source_display_name)
    destination_display_name = _display_name(destination_display_name)

    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        branch = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if branch is None:
            raise KeyError("graph branch not found")
        current_owner = str(branch["current_owner_profile_ref"] or "")
        if not current_owner:
            raise ValueError(
                "Profile handoff requires an existing current owner Profile"
            )
        if current_owner != source_profile_ref:
            existing = _idempotent_handoff(
                branch,
                source_profile_ref=source_profile_ref,
                destination_profile_ref=destination_profile_ref,
                expected_checkpoint_ref=expected_checkpoint_ref,
                authorization_ref=authorization_ref,
            )
            if existing is not None:
                return existing
            raise PermissionError("branch is owned by another Profile")

        latest_trace_id = str(branch["latest_trace_id"] or "")
        checkpoint = checkpoint_from_branch_row(branch)
        if not latest_trace_id or checkpoint is None:
            raise ValueError(
                "Profile handoff requires a Research Cycle checkpoint"
            )
        actual_checkpoint_ref = f"trace:{latest_trace_id}"
        if expected_checkpoint_ref != actual_checkpoint_ref:
            raise ValueError("handoff checkpoint reference is stale")
        if expected_checkpoint_hash != str(checkpoint["projection_hash"]):
            raise ValueError("handoff checkpoint hash is stale")

        trace_id = uuid.uuid4().hex
        handoff = {
            "schema_version": 1,
            "source_profile_ref": source_profile_ref,
            "destination_profile_ref": destination_profile_ref,
            "source_display_name": source_display_name,
            "destination_display_name": destination_display_name,
            "effective_at": now,
            "checkpoint_ref": expected_checkpoint_ref,
            "checkpoint_hash": expected_checkpoint_hash,
            "authorization_ref": authorization_ref,
        }
        previous_trace_id = latest_trace_id
        evidence = {
            "profile_handoff": handoff,
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": expected_checkpoint_ref,
                "checkpoint_before_hash": expected_checkpoint_hash,
                "events": [],
            },
            "research_cycle_checkpoint": deepcopy(checkpoint),
            "report_lineage": {
                "status": "linked",
                "predecessor_checkpoint_ref": expected_checkpoint_ref,
            },
        }
        evidence_json = serialize_bounded_trace_evidence(evidence)
        conn.execute(
            """
            UPDATE research_graph_instances
            SET current_owner_profile_ref=?
            WHERE instance_id=? AND owner=?
              AND current_owner_profile_ref=?
            """,
            (
                destination_profile_ref,
                instance_id,
                owner,
                source_profile_ref,
            ),
        )
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise PermissionError("branch ownership changed during handoff")
        conn.execute(
            """
            UPDATE research_graph_branches
            SET latest_trace_id=?, updated_at=?
            WHERE instance_id=? AND branch_id=?
            """,
            (trace_id, now, instance_id, branch_id),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, acting_profile_ref,
                created_at
            ) VALUES (?, ?, ?, '__profile_handoff__', ?, ?, ?, '{}', ?, ?, ?)
            """,
            (
                trace_id,
                instance_id,
                branch_id,
                str(branch["current_node"]),
                str(branch["current_node"]),
                evidence_json,
                owner,
                source_profile_ref,
                now,
            ),
        )
    return {
        "instance_id": instance_id,
        "branch_id": branch_id,
        "created_by_profile_ref": str(
            branch["created_by_profile_ref"] or ""
        ),
        "current_owner_profile_ref": destination_profile_ref,
        "acting_profile_ref": source_profile_ref,
        "handoff": handoff,
        "trace_ref": f"trace:{trace_id}",
        "checkpoint_ref": expected_checkpoint_ref,
        "checkpoint_hash": expected_checkpoint_hash,
        "previous_trace_ref": f"trace:{previous_trace_id}",
    }


def _idempotent_handoff(
    branch: Any,
    *,
    source_profile_ref: str,
    destination_profile_ref: str,
    expected_checkpoint_ref: str,
    authorization_ref: str,
) -> dict[str, Any] | None:
    evidence = _loads(branch["latest_trace_evidence_json"])
    handoff = evidence.get("profile_handoff")
    if not isinstance(handoff, dict):
        return None
    if {
        str(handoff.get("source_profile_ref") or ""),
        str(handoff.get("destination_profile_ref") or ""),
        str(handoff.get("checkpoint_ref") or ""),
        str(handoff.get("authorization_ref") or ""),
    } != {
        source_profile_ref,
        destination_profile_ref,
        expected_checkpoint_ref,
        authorization_ref,
    }:
        return None
    trace_ref = f"trace:{str(branch['latest_trace_id'])}"
    return {
        "instance_id": str(branch["instance_id"]),
        "branch_id": str(branch["branch_id"]),
        "created_by_profile_ref": str(
            branch["created_by_profile_ref"] or ""
        ),
        "current_owner_profile_ref": destination_profile_ref,
        "acting_profile_ref": source_profile_ref,
        "handoff": deepcopy(handoff),
        "trace_ref": trace_ref,
        "checkpoint_ref": expected_checkpoint_ref,
        "checkpoint_hash": str(handoff.get("checkpoint_hash") or ""),
        "previous_trace_ref": expected_checkpoint_ref,
    }


def _checkpoint_ref(value: Any) -> str:
    if not isinstance(value, str) or not re_fullmatch_trace(value):
        raise ValueError("expected_checkpoint_ref must use trace:<id>")
    return value


def _hash(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("expected_checkpoint_hash must be sha256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("expected_checkpoint_hash must be sha256") from exc
    return value


def _display_name(value: Any) -> str:
    value = str(value or "").strip()
    if len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValueError("Profile display name is invalid")
    return value


def _loads(value: Any) -> dict[str, Any]:
    try:
        parsed = orjson.loads(value) if value else {}
    except orjson.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def re_fullmatch_trace(value: str) -> bool:
    return value.startswith("trace:") and len(value) > 6 and all(
        char.isalnum() or char in "._-"
        for char in value.removeprefix("trace:")
    )
