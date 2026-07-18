"""Immutable research decision graphs and gated Active Graph pointers."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import os
import sqlite3
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from cli_anything.factortester_research.core.graph import (
    graph_content_hash as protocol_graph_content_hash,
    validate_graph as validate_protocol_graph,
)
from tools.data.sqlite.db import connect_sqlite


class GraphVersionConflict(ValueError):
    pass


class GraphActivationBlocked(ValueError):
    pass


_VALIDATION_GATES = (
    "replay_passed",
    "shadow_passed",
    "capability_resolution_complete",
    "unaffected_jobs_preserved",
    "token_efficiency_passed",
)
_SERVER_FORBIDDEN_SKILL_FIELDS = {
    "skill_name",
    "implementation_id",
    "provider",
    "source_path",
    "source_fingerprint",
    "loaded_skill_ids",
    "loaded_skill_receipts",
}
_MAX_CONTEXT_BYTES = 6000
_MAX_CONTEXT_EVIDENCE_REFS = 8
_MAX_EVIDENCE_REF_BYTES = 256
_MAX_ASSURANCE_RECEIPT_BYTES = 1024
_BACKEND_ASSURANCE_POLICY = {
    "policy_id": "backend-assurance@1",
    "checks": [
        "terminal_state",
        "job_spec_hash",
        "execution_plan_hash",
        "run_spec_hash",
        "result_state_coherence",
        "artifact_manifest_hashes",
    ],
    "verifier_trigger": "succeeded_with_semantic_or_integrity_anomaly",
}
_BACKEND_ASSURANCE_POLICY_HASH = hashlib.sha256(orjson.dumps(
    _BACKEND_ASSURANCE_POLICY,
    option=orjson.OPT_SORT_KEYS,
)).hexdigest()
_GRAPH_CACHE: dict[tuple[str, str, int, str], dict[str, Any]] = {}
_GRAPH_CACHE_INDEX: dict[tuple[str, str, int], str] = {}


def _graph_version_cache_key(
    graph_id: str,
    version: int,
) -> tuple[str, str, int]:
    return (str(Settings.CACHE_DB_PATH), graph_id, int(version))


def _cache_graph(graph: dict[str, Any]) -> dict[str, Any]:
    graph_id = str(graph["graph_id"])
    version = int(graph["version"])
    content_hash = str(graph["content_hash"])
    version_key = _graph_version_cache_key(graph_id, version)
    cache_key = (*version_key, content_hash)
    value = deepcopy(graph)
    _GRAPH_CACHE_INDEX[version_key] = content_hash
    _GRAPH_CACHE[cache_key] = value
    return deepcopy(value)


def _cached_graph(
    graph_id: str,
    version: int,
) -> dict[str, Any] | None:
    version_key = _graph_version_cache_key(graph_id, version)
    content_hash = _GRAPH_CACHE_INDEX.get(version_key)
    if content_hash is None:
        return None
    value = _GRAPH_CACHE.get((*version_key, content_hash))
    return deepcopy(value) if value is not None else None


def _clear_graph_cache_for_current_db() -> None:
    db_path = str(Settings.CACHE_DB_PATH)
    version_keys = [
        key for key in _GRAPH_CACHE_INDEX
        if key[0] == db_path
    ]
    for version_key in version_keys:
        content_hash = _GRAPH_CACHE_INDEX.pop(version_key)
        _GRAPH_CACHE.pop((*version_key, content_hash), None)


def _merge_bounded_evidence_refs(
    existing_refs: list[str],
    omitted_count: int,
    incoming_refs: Any,
) -> tuple[list[str], int]:
    """Keep a fixed-size recent evidence window for Agent context."""
    refs = list(existing_refs)
    omitted = int(omitted_count)
    if not isinstance(incoming_refs, list):
        return refs, omitted
    for reference in incoming_refs:
        if (
            not isinstance(reference, str)
            or not reference
            or len(reference.encode()) > _MAX_EVIDENCE_REF_BYTES
        ):
            omitted += 1
            continue
        if reference in refs:
            continue
        refs.append(reference)
        if len(refs) > _MAX_CONTEXT_EVIDENCE_REFS:
            refs.pop(0)
            omitted += 1
    return refs, omitted


def _loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def _content_hash(graph: dict[str, Any]) -> str:
    return protocol_graph_content_hash(graph)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _assert_no_skill_identity(
    value: Any,
    *,
    location: str,
) -> None:
    if isinstance(value, dict):
        forbidden = sorted(
            str(key) for key in value
            if str(key) in _SERVER_FORBIDDEN_SKILL_FIELDS
        )
        if forbidden:
            raise ValueError(
                f"{location} may persist descriptions, not Skill identity: "
                + ", ".join(forbidden)
            )
        for item in value.values():
            _assert_no_skill_identity(item, location=location)
    elif isinstance(value, list):
        for item in value:
            _assert_no_skill_identity(item, location=location)


def _validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    protocol_value = validate_protocol_graph(graph)
    if not str(protocol_value.get("graph_id") or "").strip():
        raise ValueError("graph_id is required")
    if int(protocol_value.get("version") or 0) < 1:
        raise ValueError("graph version must be positive")
    if str(protocol_value.get("research_semantics") or "") != "product_neutral":
        raise ValueError("research graph must declare product_neutral semantics")
    actual_hash = _content_hash(protocol_value)
    declared_hash = str(protocol_value.get("content_hash") or "")
    if declared_hash and declared_hash != actual_hash:
        raise ValueError("graph content_hash mismatch")
    value = deepcopy(protocol_value)
    value["content_hash"] = actual_hash
    return value


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_graph_versions (
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            lifecycle TEXT NOT NULL,
            parent_version INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            graph_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (graph_id, version),
            UNIQUE (graph_id, content_hash)
        );
        CREATE TABLE IF NOT EXISTS research_graph_validations (
            validation_id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            actor TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_graph_validations_version
        ON research_graph_validations(graph_id, version, created_at);
        CREATE TABLE IF NOT EXISTS research_graph_proposals (
            proposal_id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            proposer TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            change_diff_json TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            token_estimate INTEGER NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_agent_executions (
            execution_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            model_id TEXT NOT NULL,
            codex_version TEXT NOT NULL,
            reservation_id TEXT NOT NULL UNIQUE,
            authority_scope TEXT NOT NULL,
            agent_principal_hash TEXT NOT NULL,
            lineage_hash TEXT NOT NULL,
            launcher_attestation TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_token_budgets (
            scope_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            token_limit INTEGER NOT NULL,
            used_tokens INTEGER NOT NULL DEFAULT 0,
            reserved_tokens INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_token_reservations (
            reservation_id TEXT PRIMARY KEY,
            scope_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            work_kind TEXT NOT NULL,
            max_input_tokens INTEGER NOT NULL,
            max_output_tokens INTEGER NOT NULL,
            max_total_tokens INTEGER NOT NULL,
            status TEXT NOT NULL,
            expires_at REAL NOT NULL,
            provider_receipt_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_provider_usage_receipts (
            provider_receipt_id TEXT PRIMARY KEY,
            reservation_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_request_id TEXT NOT NULL UNIQUE,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            usage_attestation TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_agent_executions_owner
        ON research_agent_executions(owner_user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_research_graph_proposals_version
        ON research_graph_proposals(graph_id, version, created_at);
        CREATE TABLE IF NOT EXISTS research_graph_reviews (
            review_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            disposition TEXT NOT NULL,
            scope_drift INTEGER NOT NULL,
            semantic_uncertainty INTEGER NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_graph_reviews_proposal
        ON research_graph_reviews(proposal_id, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_research_graph_review_actor
        ON research_graph_reviews(proposal_id, reviewer);
        CREATE TABLE IF NOT EXISTS research_graph_audits (
            audit_id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            actor TEXT NOT NULL,
            disposition TEXT NOT NULL,
            grill_evidence_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_graph_audits_version
        ON research_graph_audits(graph_id, version, created_at);
        CREATE TABLE IF NOT EXISTS active_research_graphs (
            graph_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            activated_by TEXT NOT NULL,
            activated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS human_activation_authorizations (
            authorization_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_version INTEGER NOT NULL,
            graph_hash TEXT NOT NULL,
            proposal_id TEXT NOT NULL,
            diff_hash TEXT NOT NULL,
            nonce_hash TEXT NOT NULL UNIQUE,
            authorized_by TEXT NOT NULL,
            human_attestation TEXT NOT NULL,
            expires_at REAL NOT NULL,
            consumed_at REAL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_human_activation_graph
        ON human_activation_authorizations(
            owner_user_id, graph_id, graph_version, created_at
        );
        CREATE TABLE IF NOT EXISTS research_backend_assurance_receipts (
            receipt_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            job_id TEXT NOT NULL UNIQUE,
            attempt_id INTEGER NOT NULL,
            graph_id TEXT NOT NULL,
            graph_version INTEGER NOT NULL,
            graph_hash TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            runspec_hash TEXT NOT NULL,
            execution_plan_hash TEXT NOT NULL,
            backend_revision TEXT NOT NULL,
            policy_hash TEXT NOT NULL,
            terminal_status TEXT NOT NULL,
            disposition TEXT NOT NULL,
            checks_bitmap INTEGER NOT NULL,
            anomaly_codes_json TEXT NOT NULL,
            result_summary_hash TEXT NOT NULL,
            artifact_manifest_hash TEXT NOT NULL,
            implementation_execution_id TEXT NOT NULL DEFAULT '',
            verifier_execution_id TEXT NOT NULL DEFAULT '',
            verifier_disposition TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            server_attestation TEXT NOT NULL,
            created_at REAL NOT NULL,
            verified_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_backend_assurance_branch
        ON research_backend_assurance_receipts(
            owner_user_id, instance_id, branch_id, created_at
        );
        CREATE TABLE IF NOT EXISTS research_graph_rollbacks (
            rollback_id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            from_version INTEGER NOT NULL,
            to_version INTEGER NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            grill_evidence_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_graph_instances (
            instance_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_version INTEGER NOT NULL,
            product_group TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            capability_resolution_json TEXT NOT NULL,
            token_budget INTEGER,
            mode TEXT NOT NULL DEFAULT 'live',
            shadow_run_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_graph_instances_owner
        ON research_graph_instances(owner, created_at);
        CREATE TABLE IF NOT EXISTS research_graph_branches (
            branch_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            label TEXT NOT NULL,
            current_node TEXT NOT NULL,
            status TEXT NOT NULL,
            cumulative_input_tokens INTEGER NOT NULL DEFAULT 0,
            cumulative_output_tokens INTEGER NOT NULL DEFAULT 0,
            cumulative_cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cumulative_skill_document_tokens INTEGER NOT NULL DEFAULT 0,
            cumulative_artifact_summary_tokens INTEGER NOT NULL DEFAULT 0,
            cumulative_reviewer_tokens INTEGER NOT NULL DEFAULT 0,
            skill_document_load_count INTEGER NOT NULL DEFAULT 0,
            skill_context_cache_hits INTEGER NOT NULL DEFAULT 0,
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            omitted_evidence_count INTEGER NOT NULL DEFAULT 0,
            latest_trace_id TEXT NOT NULL DEFAULT '',
            trace_count INTEGER NOT NULL DEFAULT 0,
            aggregate_version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_graph_branches_instance
        ON research_graph_branches(instance_id, created_at);
        CREATE TABLE IF NOT EXISTS research_graph_node_resolutions (
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            resolution_json TEXT NOT NULL,
            semantic_cache_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (instance_id, branch_id, node_id)
        );
        CREATE TABLE IF NOT EXISTS research_capability_approvals (
            approval_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            descriptor_hash TEXT NOT NULL,
            product_group TEXT NOT NULL,
            actor TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_capability_receipts (
            receipt_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_version INTEGER NOT NULL,
            graph_hash TEXT NOT NULL,
            node_id TEXT NOT NULL,
            product_group TEXT NOT NULL,
            catalog_hash TEXT NOT NULL,
            product_profile_hash TEXT NOT NULL,
            resolver_version TEXT NOT NULL,
            resolution_json TEXT NOT NULL,
            approval_refs_json TEXT NOT NULL,
            provider_conformance_hash TEXT NOT NULL,
            resolver_attestation TEXT NOT NULL,
            receipt_mode TEXT NOT NULL DEFAULT 'live',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_graph_server_secrets (
            secret_id INTEGER PRIMARY KEY CHECK (secret_id=1),
            secret BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_graph_trace (
            trace_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            telemetry_json TEXT NOT NULL DEFAULT '{}',
            actor TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_graph_trace_branch
        ON research_graph_trace(instance_id, branch_id, created_at);
        """
    )
    trace_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_graph_trace)"
        ).fetchall()
    }
    if "telemetry_json" not in trace_columns:
        conn.execute(
            "ALTER TABLE research_graph_trace "
            "ADD COLUMN telemetry_json TEXT NOT NULL DEFAULT '{}'"
        )
    instance_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_graph_instances)"
        ).fetchall()
    }
    if "token_budget" not in instance_columns:
        conn.execute(
            "ALTER TABLE research_graph_instances ADD COLUMN token_budget INTEGER"
        )
    if "mode" not in instance_columns:
        conn.execute(
            "ALTER TABLE research_graph_instances "
            "ADD COLUMN mode TEXT NOT NULL DEFAULT 'live'"
        )
    if "shadow_run_id" not in instance_columns:
        conn.execute(
            "ALTER TABLE research_graph_instances "
            "ADD COLUMN shadow_run_id TEXT NOT NULL DEFAULT ''"
        )
    branch_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_graph_branches)"
        ).fetchall()
    }
    branch_aggregate_columns = {
        "cumulative_input_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cumulative_output_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cumulative_cache_read_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cumulative_skill_document_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cumulative_artifact_summary_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cumulative_reviewer_tokens": "INTEGER NOT NULL DEFAULT 0",
        "skill_document_load_count": "INTEGER NOT NULL DEFAULT 0",
        "skill_context_cache_hits": "INTEGER NOT NULL DEFAULT 0",
        "evidence_refs_json": "TEXT NOT NULL DEFAULT '[]'",
        "omitted_evidence_count": "INTEGER NOT NULL DEFAULT 0",
        "latest_trace_id": "TEXT NOT NULL DEFAULT ''",
        "trace_count": "INTEGER NOT NULL DEFAULT 0",
        "aggregate_version": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, declaration in branch_aggregate_columns.items():
        if column not in branch_columns:
            conn.execute(
                f"ALTER TABLE research_graph_branches "
                f"ADD COLUMN {column} {declaration}"
            )
    _backfill_branch_aggregates(conn)
    conn.execute(
        "DROP INDEX IF EXISTS idx_research_graph_node_resolutions_branch"
    )
    proposal_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_graph_proposals)"
        ).fetchall()
    }
    if "owner_user_id" not in proposal_columns:
        conn.execute(
            "ALTER TABLE research_graph_proposals "
            "ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''"
        )
    if "proposer_execution_id" not in proposal_columns:
        conn.execute(
            "ALTER TABLE research_graph_proposals "
            "ADD COLUMN proposer_execution_id TEXT NOT NULL DEFAULT ''"
        )
    review_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_graph_reviews)"
        ).fetchall()
    }
    if "owner_user_id" not in review_columns:
        conn.execute(
            "ALTER TABLE research_graph_reviews "
            "ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''"
        )
    if "reviewer_execution_id" not in review_columns:
        conn.execute(
            "ALTER TABLE research_graph_reviews "
            "ADD COLUMN reviewer_execution_id TEXT NOT NULL DEFAULT ''"
        )
    execution_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_agent_executions)"
        ).fetchall()
    }
    if "reservation_id" not in execution_columns:
        conn.execute(
            "ALTER TABLE research_agent_executions "
            "ADD COLUMN reservation_id TEXT NOT NULL DEFAULT ''"
        )
    if "authority_scope" not in execution_columns:
        conn.execute(
            "ALTER TABLE research_agent_executions "
            "ADD COLUMN authority_scope TEXT NOT NULL DEFAULT 'local_research'"
        )
    for column in (
        "agent_principal_hash",
        "lineage_hash",
        "launcher_attestation",
    ):
        if column not in execution_columns:
            conn.execute(
                "ALTER TABLE research_agent_executions "
                f"ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
            )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_research_agent_reservation
        ON research_agent_executions(reservation_id)
        WHERE reservation_id<>''
        """
    )
    receipt_columns = {
        str(row["name"])
        for row in conn.execute(
            "PRAGMA table_info(research_capability_receipts)"
        ).fetchall()
    }
    if "receipt_mode" not in receipt_columns:
        conn.execute(
            "ALTER TABLE research_capability_receipts "
            "ADD COLUMN receipt_mode TEXT NOT NULL DEFAULT 'live'"
        )


def _trace_aggregate(
    rows: list[sqlite3.Row],
) -> dict[str, Any]:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "skill_document_tokens": 0,
        "artifact_summary_tokens": 0,
        "reviewer_tokens": 0,
        "skill_document_load_count": 0,
        "skill_context_cache_hits": 0,
    }
    evidence_refs: list[str] = []
    omitted_evidence_count = 0
    latest_trace_id = ""
    for row in rows:
        telemetry = _loads(row["telemetry_json"]) or {}
        for field in totals:
            totals[field] += int(telemetry.get(field) or 0)
        evidence = _loads(row["evidence_json"]) or {}
        evidence_refs, omitted_evidence_count = (
            _merge_bounded_evidence_refs(
                evidence_refs,
                omitted_evidence_count,
                evidence.get("evidence_refs"),
            )
        )
        latest_trace_id = str(row["trace_id"])
    return {
        **totals,
        "evidence_refs": evidence_refs,
        "omitted_evidence_count": omitted_evidence_count,
        "latest_trace_id": latest_trace_id,
        "trace_count": len(rows),
    }


def _backfill_branch_aggregates(conn: sqlite3.Connection) -> None:
    """One-time cold migration from append-only traces to branch summaries."""
    branches = conn.execute(
        """
        SELECT instance_id, branch_id
        FROM research_graph_branches
        WHERE aggregate_version=0
        """
    ).fetchall()
    for branch in branches:
        rows = conn.execute(
            """
            SELECT trace_id, evidence_json, telemetry_json
            FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            ORDER BY created_at, trace_id
            """,
            (branch["instance_id"], branch["branch_id"]),
        ).fetchall()
        aggregate = _trace_aggregate(rows)
        conn.execute(
            """
            UPDATE research_graph_branches SET
                cumulative_input_tokens=?,
                cumulative_output_tokens=?,
                cumulative_cache_read_tokens=?,
                cumulative_skill_document_tokens=?,
                cumulative_artifact_summary_tokens=?,
                cumulative_reviewer_tokens=?,
                skill_document_load_count=?,
                skill_context_cache_hits=?,
                evidence_refs_json=?,
                omitted_evidence_count=?,
                latest_trace_id=?,
                trace_count=?,
                aggregate_version=1
            WHERE instance_id=? AND branch_id=?
            """,
            (
                aggregate["input_tokens"],
                aggregate["output_tokens"],
                aggregate["cache_read_tokens"],
                aggregate["skill_document_tokens"],
                aggregate["artifact_summary_tokens"],
                aggregate["reviewer_tokens"],
                aggregate["skill_document_load_count"],
                aggregate["skill_context_cache_hits"],
                orjson.dumps(aggregate["evidence_refs"]).decode(),
                aggregate["omitted_evidence_count"],
                aggregate["latest_trace_id"],
                aggregate["trace_count"],
                branch["instance_id"],
                branch["branch_id"],
            ),
        )


def ensure_schema() -> None:
    _clear_graph_cache_for_current_db()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)


def _row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    graph = _loads(row["graph_json"]) or {}
    graph["created_by"] = str(row["created_by"])
    graph["created_at"] = float(row["created_at"])
    return graph


def _load_graph_from_conn(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> dict[str, Any] | None:
    cached = _cached_graph(graph_id, version)
    if cached is not None:
        return cached
    row = conn.execute(
        """
        SELECT * FROM research_graph_versions
        WHERE graph_id=? AND version=?
        """,
        (graph_id, int(version)),
    ).fetchone()
    graph = _row_payload(row)
    return _cache_graph(graph) if graph is not None else None


def _insert_graph(
    conn: sqlite3.Connection,
    graph: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    value = _validate_graph(graph)
    created_at = time.time()
    try:
        conn.execute(
            """
            INSERT INTO research_graph_versions (
                graph_id, version, lifecycle, parent_version, content_hash,
                graph_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                value["graph_id"],
                int(value["version"]),
                value["lifecycle"],
                int(value.get("parent_version") or 0),
                value["content_hash"],
                orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode(),
                actor,
                created_at,
            ),
        )
    except sqlite3.IntegrityError as exc:
        existing = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (value["graph_id"], int(value["version"])),
        ).fetchone()
        if (
            existing is not None
            and str(existing["content_hash"]) == value["content_hash"]
        ):
            stored = _row_payload(existing) or {}
            return _cache_graph(stored)
        raise GraphVersionConflict(
            f"graph version is immutable: {value['graph_id']} "
            f"v{value['version']}"
        ) from exc
    stored = deepcopy(value)
    stored["created_by"] = actor
    stored["created_at"] = created_at
    return _cache_graph(stored)


def register_graph(graph: dict[str, Any], *, actor: str) -> dict[str, Any]:
    value = _validate_graph(graph)
    if value["lifecycle"] not in {"observed", "draft"}:
        raise ValueError("only observed or draft graphs may be registered")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        return _insert_graph(conn, value, actor=actor)


def load_graph(*, graph_id: str, version: int) -> dict[str, Any] | None:
    cached = _cached_graph(graph_id, version)
    if cached is not None:
        return cached
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        return _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )


def list_graph_versions(*, graph_id: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? ORDER BY version
            """,
            (graph_id,),
        ).fetchall()
    return [
        _cache_graph(_row_payload(row) or {})
        for row in rows
    ]


def _graph_lifecycle(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> str | None:
    row = conn.execute(
        """
        SELECT lifecycle FROM research_graph_versions
        WHERE graph_id=? AND version=?
        """,
        (graph_id, int(version)),
    ).fetchone()
    return str(row["lifecycle"]) if row is not None else None


def derive_activation_token_metrics(
    *,
    graph_id: str,
    version: int,
    routine_instance_id: str,
    routine_branch_id: str,
    baseline_run_id: str,
) -> dict[str, Any]:
    """Derive activation metrics from server-owned runs and usage receipts."""
    if not all((
        routine_instance_id,
        routine_branch_id,
        baseline_run_id,
    )):
        raise ValueError("complete token measurement references are required")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        owner_row = conn.execute(
            """
            SELECT owner FROM research_graph_instances
            WHERE instance_id=?
            """,
            (routine_instance_id,),
        ).fetchone()
        if owner_row is None:
            raise ValueError("shadow graph instance or branch not found")
        owner = str(owner_row["owner"])
        runtime = _load_instance_branch_row(
            conn,
            instance_id=routine_instance_id,
            branch_id=routine_branch_id,
            owner=owner,
        )
        if runtime is None:
            raise ValueError("shadow graph instance or branch not found")
        if (
            str(runtime["mode"]) != "shadow"
            or str(runtime["graph_id"]) != graph_id
            or int(runtime["graph_version"]) != int(version)
        ):
            raise ValueError(
                "token measurement instance is not this draft shadow graph"
            )
        graph_run_id = str(runtime["shadow_run_id"])
        if not graph_run_id or graph_run_id == baseline_run_id:
            raise ValueError("shadow graph and baseline require distinct run IDs")
        run_rows = conn.execute(
            """
            SELECT run_id, run_spec_hash, workspace_id
            FROM research_runs
            WHERE owner=? AND run_id IN (?, ?)
              AND kind='factor_research'
            """,
            (owner, graph_run_id, baseline_run_id),
        ).fetchall()
        runs = {str(row["run_id"]): row for row in run_rows}
        if set(runs) != {graph_run_id, baseline_run_id}:
            raise ValueError("owned graph and baseline research runs are required")
        if (
            str(runs[graph_run_id]["run_spec_hash"])
            != str(runs[baseline_run_id]["run_spec_hash"])
        ):
            raise ValueError(
                "graph and baseline runs must share one RunSpec hash"
            )
        graph_scope_id = f"instance:{routine_instance_id}"
        baseline_scope_id = f"research-run:{baseline_run_id}"
        budget_rows = conn.execute(
            """
            SELECT scope_id, used_tokens
            FROM research_token_budgets
            WHERE owner_user_id=? AND scope_id IN (?, ?)
            """,
            (owner, graph_scope_id, baseline_scope_id),
        ).fetchall()
        budgets = {
            str(row["scope_id"]): int(row["used_tokens"])
            for row in budget_rows
        }
        if set(budgets) != {graph_scope_id, baseline_scope_id}:
            raise ValueError(
                "graph and baseline token budgets are required"
            )
        subagent_count = int(conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM research_agent_executions e
            JOIN research_token_reservations r
              ON r.reservation_id=e.reservation_id
            WHERE r.owner_user_id=? AND r.scope_id=?
            """,
            (owner, graph_scope_id),
        ).fetchone()["count"])
    context = build_graph_branch_context(
        instance_id=routine_instance_id,
        branch_id=routine_branch_id,
        owner=owner,
    )
    full_graph_loaded = any(
        field in context
        for field in (
            "nodes",
            "edges",
            "capability_descriptors",
            "capability_contracts",
        )
    )
    untriggered_conditionals = (
        len(context.get("conditional_capabilities") or [])
        if "conditional_capabilities" in context
        else 0
    )
    graph = load_graph(graph_id=graph_id, version=version) or {}
    node = next(
        (
            item for item in graph.get("nodes") or []
            if str(item.get("node_id") or "")
            == str((context.get("node") or {}).get("node_id") or "")
        ),
        {},
    )
    allowed_gap_ids = set(node.get("required_capabilities") or []) | {
        str(item.get("capability_id") or "")
        for item in node.get("conditional_capabilities") or []
    }
    future_gap_count = (
        0
        if node.get("kind") == "capability_gap"
        else sum(
            str(item.get("capability_id") or "") not in allowed_gap_ids
            for item in context.get("open_gaps") or []
            if isinstance(item, dict)
        )
    )
    return {
        "routine_context_bytes": int(context["context_bytes"]),
        "full_graph_loaded_for_routine": full_graph_loaded,
        "untriggered_conditionals_in_context": untriggered_conditionals,
        "future_node_gaps_blocked": future_gap_count,
        "routine_subagent_count": subagent_count,
        "shadow_graph_total_tokens": budgets[graph_scope_id],
        "shadow_baseline_total_tokens": budgets[baseline_scope_id],
        "graph_run_id": graph_run_id,
        "baseline_run_id": baseline_run_id,
        "run_spec_hash": str(runs[graph_run_id]["run_spec_hash"]),
        "token_authority": "trusted_provider_usage_receipts",
    }


def record_validation(
    *,
    graph_id: str,
    version: int,
    actor: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("validation evidence must be an object")
    _assert_no_skill_identity(evidence, location="validation evidence")
    if "token_metrics" in evidence:
        raise ValueError(
            "client token_metrics are not accepted; submit measurement refs"
        )
    evidence_value = deepcopy(evidence)
    if evidence.get("token_efficiency_passed") is True:
        refs = evidence.get("token_measurement_refs")
        if not isinstance(refs, dict):
            raise ValueError(
                "token_efficiency_passed requires token_measurement_refs"
            )
        metrics = derive_activation_token_metrics(
            graph_id=graph_id,
            version=version,
            routine_instance_id=str(refs.get("routine_instance_id") or ""),
            routine_branch_id=str(refs.get("routine_branch_id") or ""),
            baseline_run_id=str(refs.get("baseline_run_id") or ""),
        )
        evidence_value["token_metrics"] = metrics
        evidence_value["token_metrics_authority"] = "server_derived"
        required_metrics = {
            "routine_context_bytes": int,
            "full_graph_loaded_for_routine": bool,
            "untriggered_conditionals_in_context": int,
            "future_node_gaps_blocked": int,
            "routine_subagent_count": int,
            "shadow_graph_total_tokens": int,
            "shadow_baseline_total_tokens": int,
        }
        for field, expected_type in required_metrics.items():
            value = metrics.get(field)
            if not isinstance(value, expected_type) or (
                expected_type is int and isinstance(value, bool)
            ):
                raise ValueError(f"token_metrics.{field} has invalid type")
        failed_token_checks = []
        if metrics["routine_context_bytes"] > 6000:
            failed_token_checks.append("routine_context_bytes")
        if metrics["full_graph_loaded_for_routine"]:
            failed_token_checks.append("full_graph_loaded_for_routine")
        for field in (
            "untriggered_conditionals_in_context",
            "future_node_gaps_blocked",
            "routine_subagent_count",
        ):
            if metrics[field] != 0:
                failed_token_checks.append(field)
        if (
            metrics["shadow_graph_total_tokens"]
            > metrics["shadow_baseline_total_tokens"]
        ):
            failed_token_checks.append("shadow_graph_total_tokens")
        if not metrics["shadow_graph_total_tokens"]:
            failed_token_checks.append("shadow_graph_total_tokens_nonzero")
        if not metrics["shadow_baseline_total_tokens"]:
            failed_token_checks.append("shadow_baseline_total_tokens_nonzero")
        if failed_token_checks:
            raise ValueError(
                "token efficiency checks failed: "
                + ", ".join(failed_token_checks)
            )
    validation_id = uuid.uuid4().hex
    row = {
        "validation_id": validation_id,
        "graph_id": graph_id,
        "version": int(version),
        "actor": actor,
        "evidence": deepcopy(evidence_value),
        "created_at": time.time(),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if _graph_lifecycle(
            conn,
            graph_id=graph_id,
            version=version,
        ) is None:
            raise KeyError("graph version not found")
        conn.execute(
            """
            INSERT INTO research_graph_validations (
                validation_id, graph_id, version, actor, evidence_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                validation_id,
                graph_id,
                int(version),
                actor,
                orjson.dumps(
                    evidence_value,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                row["created_at"],
            ),
        )
    return row


def create_agent_execution(
    *,
    owner_user_id: str,
    actor_role: str,
    model_id: str = "",
    codex_version: str = "",
    reservation_id: str = "",
    authority_scope: str = "local_research",
    agent_principal_hash: str = "",
    lineage_hash: str = "",
    launcher_attestation: str = "",
) -> dict[str, Any]:
    if actor_role not in {
        "proposer",
        "reviewer",
        "audit_presenter",
        "implementation_agent",
        "backend_verifier",
    }:
        raise ValueError("invalid Agent execution role")
    if authority_scope not in {
        "local_research",
        "server_research",
        "server_backend_code",
    }:
        raise ValueError("invalid Agent authority_scope")
    if (
        actor_role in {"implementation_agent", "backend_verifier"}
        and authority_scope != "server_backend_code"
    ):
        raise ValueError(
            f"{actor_role} requires server_backend_code authority"
        )
    for field, value in (
        ("agent_principal_hash", agent_principal_hash),
        ("lineage_hash", lineage_hash),
    ):
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"{field} must be sha256")
    launcher_secret = os.environ.get("RESEARCH_AGENT_LAUNCHER_SECRET", "")
    if not launcher_secret:
        raise ValueError("trusted Agent launcher is not configured")
    attested_payload = {
        "owner_user_id": owner_user_id,
        "actor_role": actor_role,
        "model_id": str(model_id),
        "codex_version": str(codex_version),
        "reservation_id": reservation_id,
        "authority_scope": authority_scope,
        "agent_principal_hash": agent_principal_hash,
        "lineage_hash": lineage_hash,
    }
    expected_attestation = hmac.new(
        launcher_secret.encode(),
        orjson.dumps(attested_payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(
        expected_attestation,
        launcher_attestation,
    ):
        raise ValueError("Agent launcher attestation is invalid")
    execution_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        reservation = conn.execute(
            """
            SELECT * FROM research_token_reservations
            WHERE reservation_id=? AND owner_user_id=? AND status='granted'
            AND expires_at>?
            """,
            (reservation_id, owner_user_id, time.time()),
        ).fetchone()
        if reservation is None:
            raise ValueError(
                "active token reservation is required before Agent launch"
            )
        expected_work_kind = {
            "proposer": "proposer",
            "reviewer": "reviewer",
            "audit_presenter": "audit_presenter",
            "implementation_agent": "implementation_agent",
            "backend_verifier": "backend_verifier",
        }[actor_role]
        if str(reservation["work_kind"]) != expected_work_kind:
            raise ValueError("token reservation work_kind does not match role")
        conn.execute(
            """
            INSERT INTO research_agent_executions (
                execution_id, owner_user_id, actor_role, model_id,
                codex_version, reservation_id, authority_scope,
                agent_principal_hash, lineage_hash, launcher_attestation,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id,
                owner_user_id,
                actor_role,
                str(model_id),
                str(codex_version),
                reservation_id,
                authority_scope,
                agent_principal_hash,
                lineage_hash,
                launcher_attestation,
                now,
            ),
        )
    return {
        "execution_id": execution_id,
        "owner_user_id": owner_user_id,
        "actor_role": actor_role,
        "model_id": str(model_id),
        "codex_version": str(codex_version),
        "created_at": now,
        "reservation_id": reservation_id,
        "authority_scope": authority_scope,
        "agent_principal_hash": agent_principal_hash,
        "lineage_hash": lineage_hash,
    }


def create_token_budget(
    *,
    owner_user_id: str,
    scope_id: str,
    token_limit: int,
) -> dict[str, Any]:
    if not scope_id.strip():
        raise ValueError("token budget scope_id is required")
    if (
        not isinstance(token_limit, int)
        or isinstance(token_limit, bool)
        or token_limit <= 0
    ):
        raise ValueError("token_limit must be positive")
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        try:
            conn.execute(
                """
                INSERT INTO research_token_budgets (
                    scope_id, owner_user_id, token_limit, used_tokens,
                    reserved_tokens, created_at
                ) VALUES (?, ?, ?, 0, 0, ?)
                """,
                (scope_id, owner_user_id, token_limit, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("token budget scope already exists") from exc
    return {
        "scope_id": scope_id,
        "owner_user_id": owner_user_id,
        "token_limit": token_limit,
        "used_tokens": 0,
        "reserved_tokens": 0,
        "created_at": now,
    }


def reserve_tokens(
    *,
    owner_user_id: str,
    scope_id: str,
    work_kind: str,
    max_input_tokens: int,
    max_output_tokens: int,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    if work_kind not in {
        "researcher",
        "proposer",
        "reviewer",
        "audit_presenter",
        "implementation_agent",
        "backend_verifier",
        "skill",
    }:
        raise ValueError("invalid token reservation work_kind")
    for field, value in (
        ("max_input_tokens", max_input_tokens),
        ("max_output_tokens", max_output_tokens),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field} must be non-negative")
    max_total = max_input_tokens + max_output_tokens
    if max_total <= 0:
        raise ValueError("token reservation must be positive")
    if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
        raise ValueError("ttl_seconds must be between 1 and 3600")
    reservation_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        budget = conn.execute(
            """
            SELECT * FROM research_token_budgets
            WHERE scope_id=? AND owner_user_id=?
            """,
            (scope_id, owner_user_id),
        ).fetchone()
        if budget is None:
            raise KeyError("token budget scope not found")
        available = (
            int(budget["token_limit"])
            - int(budget["used_tokens"])
            - int(budget["reserved_tokens"])
        )
        if max_total > available:
            raise ValueError(
                f"token reservation denied: requested={max_total}, "
                f"available={available}"
            )
        conn.execute(
            """
            UPDATE research_token_budgets
            SET reserved_tokens=reserved_tokens+?
            WHERE scope_id=? AND owner_user_id=?
            """,
            (max_total, scope_id, owner_user_id),
        )
        conn.execute(
            """
            INSERT INTO research_token_reservations (
                reservation_id, scope_id, owner_user_id, work_kind,
                max_input_tokens, max_output_tokens, max_total_tokens,
                status, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'granted', ?, ?)
            """,
            (
                reservation_id,
                scope_id,
                owner_user_id,
                work_kind,
                max_input_tokens,
                max_output_tokens,
                max_total,
                now + ttl_seconds,
                now,
            ),
        )
    return {
        "reservation_id": reservation_id,
        "scope_id": scope_id,
        "work_kind": work_kind,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "max_total_tokens": max_total,
        "status": "granted",
        "expires_at": now + ttl_seconds,
    }


def ingest_provider_usage_receipt(
    *,
    reservation_id: str,
    provider: str,
    provider_request_id: str,
    input_tokens: int,
    output_tokens: int,
    usage_attestation: str,
) -> dict[str, Any]:
    """Trusted gateway adapter: reject when no provider secret is configured."""
    secret = os.environ.get("RESEARCH_PROVIDER_USAGE_SECRET", "")
    if not secret:
        raise ValueError("trusted provider usage adapter is not configured")
    payload = {
        "reservation_id": reservation_id,
        "provider": provider,
        "provider_request_id": provider_request_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    expected = hmac.new(
        secret.encode(),
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, usage_attestation):
        raise ValueError("provider usage attestation is invalid")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (input_tokens, output_tokens)
    ):
        raise ValueError("provider usage tokens must be non-negative")
    provider_receipt_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        reservation = conn.execute(
            """
            SELECT * FROM research_token_reservations
            WHERE reservation_id=? AND status='granted'
            """,
            (reservation_id,),
        ).fetchone()
        if reservation is None:
            raise ValueError("active token reservation not found")
        if input_tokens > int(reservation["max_input_tokens"]) or (
            output_tokens > int(reservation["max_output_tokens"])
        ):
            raise ValueError("provider usage exceeded granted token maximum")
        conn.execute(
            """
            INSERT INTO research_provider_usage_receipts (
                provider_receipt_id, reservation_id, provider,
                provider_request_id, input_tokens, output_tokens,
                usage_attestation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider_receipt_id,
                reservation_id,
                provider,
                provider_request_id,
                input_tokens,
                output_tokens,
                usage_attestation,
                now,
            ),
        )
    return {
        "provider_receipt_id": provider_receipt_id,
        **payload,
        "created_at": now,
    }


def commit_token_reservation(
    *,
    owner_user_id: str,
    reservation_id: str,
    provider_receipt_id: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT r.*, p.input_tokens, p.output_tokens
            FROM research_token_reservations r
            JOIN research_provider_usage_receipts p
              ON p.reservation_id=r.reservation_id
            WHERE r.reservation_id=? AND r.owner_user_id=?
              AND r.status='granted' AND p.provider_receipt_id=?
            """,
            (reservation_id, owner_user_id, provider_receipt_id),
        ).fetchone()
        if row is None:
            raise ValueError("trusted provider usage receipt is required")
        actual = int(row["input_tokens"]) + int(row["output_tokens"])
        conn.execute(
            """
            UPDATE research_token_budgets
            SET used_tokens=used_tokens+?,
                reserved_tokens=reserved_tokens-?
            WHERE scope_id=? AND owner_user_id=?
            """,
            (
                actual,
                int(row["max_total_tokens"]),
                row["scope_id"],
                owner_user_id,
            ),
        )
        conn.execute(
            """
            UPDATE research_token_reservations
            SET status='committed', provider_receipt_id=?
            WHERE reservation_id=?
            """,
            (provider_receipt_id, reservation_id),
        )
    return {
        "reservation_id": reservation_id,
        "scope_id": str(row["scope_id"]),
        "status": "committed",
        "used_tokens": actual,
        "released_tokens": int(row["max_total_tokens"]) - actual,
    }


def release_token_reservation(
    *,
    owner_user_id: str,
    reservation_id: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM research_token_reservations
            WHERE reservation_id=? AND owner_user_id=? AND status='granted'
            """,
            (reservation_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise ValueError("active token reservation not found")
        conn.execute(
            """
            UPDATE research_token_budgets
            SET reserved_tokens=reserved_tokens-?
            WHERE scope_id=? AND owner_user_id=?
            """,
            (
                int(row["max_total_tokens"]),
                row["scope_id"],
                owner_user_id,
            ),
        )
        conn.execute(
            """
            UPDATE research_token_reservations SET status='released'
            WHERE reservation_id=?
            """,
            (reservation_id,),
        )
    return {
        "reservation_id": reservation_id,
        "status": "released",
        "released_tokens": int(row["max_total_tokens"]),
    }


def load_token_budget(
    *,
    owner_user_id: str,
    scope_id: str,
) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT * FROM research_token_budgets
            WHERE scope_id=? AND owner_user_id=?
            """,
            (scope_id, owner_user_id),
        ).fetchone()
    if row is None:
        return None
    limit = int(row["token_limit"])
    used = int(row["used_tokens"])
    reserved = int(row["reserved_tokens"])
    return {
        "scope_id": scope_id,
        "token_limit": limit,
        "used_tokens": used,
        "reserved_tokens": reserved,
        "available_tokens": max(limit - used - reserved, 0),
    }


def _require_agent_execution(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    execution_id: str,
    role: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT * FROM research_agent_executions
        WHERE execution_id=? AND owner_user_id=? AND actor_role=?
        """,
        (execution_id, owner_user_id, role),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"valid {role} Agent execution is required"
        )
    return row


def record_proposal(
    *,
    graph_id: str,
    version: int,
    owner_user_id: str,
    actor_agent_id: str,
    risk_level: str,
    change_diff: dict[str, Any],
    evidence_refs: list[str],
    token_estimate: int,
) -> dict[str, Any]:
    if risk_level not in {"L1", "L2", "L3", "L4"}:
        raise ValueError("invalid proposal risk_level")
    if not isinstance(change_diff, dict) or not change_diff:
        raise ValueError("change_diff must be a non-empty object")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise ValueError("evidence_refs must be an array of references")
    if (
        not isinstance(token_estimate, int)
        or isinstance(token_estimate, bool)
        or token_estimate < 0
    ):
        raise ValueError("token_estimate must be non-negative")
    _assert_no_skill_identity(change_diff, location="proposal diff")
    proposal_id = uuid.uuid4().hex
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        lifecycle = _graph_lifecycle(
            conn,
            graph_id=graph_id,
            version=version,
        )
        if lifecycle is None:
            raise KeyError("graph version not found")
        if lifecycle != "draft":
            raise ValueError("only a draft graph accepts proposals")
        _require_agent_execution(
            conn,
            owner_user_id=owner_user_id,
            execution_id=actor_agent_id,
            role="proposer",
        )
        now = time.time()
        conn.execute(
            """
            INSERT INTO research_graph_proposals (
                proposal_id, graph_id, version, proposer, risk_level,
                change_diff_json, evidence_refs_json, token_estimate, created_at,
                owner_user_id, proposer_execution_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                graph_id,
                int(version),
                actor_agent_id,
                risk_level,
                orjson.dumps(change_diff, option=orjson.OPT_SORT_KEYS).decode(),
                orjson.dumps(evidence_refs).decode(),
                token_estimate,
                now,
                owner_user_id,
                actor_agent_id,
            ),
        )
    row = {
        "proposal_id": proposal_id,
        "graph_id": graph_id,
        "version": int(version),
        "owner_user_id": owner_user_id,
        "proposer_execution_id": actor_agent_id,
        "risk_level": risk_level,
        "change_diff": deepcopy(change_diff),
        "evidence_refs": list(evidence_refs),
        "token_estimate": token_estimate,
        "created_at": now,
    }
    return row


def record_proposal_review(
    *,
    proposal_id: str,
    owner_user_id: str,
    actor_agent_id: str,
    disposition: str,
    scope_drift: bool,
    semantic_uncertainty: bool,
    evidence_refs: list[str],
) -> dict[str, Any]:
    if disposition not in {"approved", "rejected", "disagreed"}:
        raise ValueError("invalid review disposition")
    if not isinstance(scope_drift, bool) or not isinstance(
        semantic_uncertainty, bool
    ):
        raise ValueError("review flags must be boolean")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise ValueError("evidence_refs must be an array of references")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        proposal = conn.execute(
            """
            SELECT * FROM research_graph_proposals WHERE proposal_id=?
            """,
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise KeyError("graph proposal not found")
        reviewer_execution = _require_agent_execution(
            conn,
            owner_user_id=owner_user_id,
            execution_id=actor_agent_id,
            role="reviewer",
        )
        if str(proposal["owner_user_id"]) != owner_user_id:
            raise ValueError("proposal belongs to a different owner")
        if str(proposal["proposer_execution_id"]) == actor_agent_id:
            raise ValueError("proposal reviewer execution must be independent")
        proposer_execution = _require_agent_execution(
            conn,
            owner_user_id=owner_user_id,
            execution_id=str(proposal["proposer_execution_id"]),
            role="proposer",
        )
        if (
            str(proposer_execution["agent_principal_hash"])
            == str(reviewer_execution["agent_principal_hash"])
            or str(proposer_execution["lineage_hash"])
            == str(reviewer_execution["lineage_hash"])
        ):
            raise ValueError(
                "proposal reviewer principal and lineage must be independent"
            )
        existing_review_principals = conn.execute(
            """
            SELECT e.agent_principal_hash, e.lineage_hash
            FROM research_graph_reviews r
            JOIN research_agent_executions e
              ON e.execution_id=r.reviewer_execution_id
            WHERE r.proposal_id=?
            """,
            (proposal_id,),
        ).fetchall()
        if any(
            str(row["agent_principal_hash"])
            == str(reviewer_execution["agent_principal_hash"])
            or str(row["lineage_hash"])
            == str(reviewer_execution["lineage_hash"])
            for row in existing_review_principals
        ):
            raise ValueError(
                "reviewer principal or lineage already reviewed this proposal"
            )
        review_id = uuid.uuid4().hex
        now = time.time()
        try:
            conn.execute(
                """
                INSERT INTO research_graph_reviews (
                    review_id, proposal_id, reviewer, disposition, scope_drift,
                    semantic_uncertainty, evidence_refs_json, created_at,
                    owner_user_id, reviewer_execution_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    proposal_id,
                    actor_agent_id,
                    disposition,
                    int(scope_drift),
                    int(semantic_uncertainty),
                    orjson.dumps(evidence_refs).decode(),
                    now,
                    owner_user_id,
                    actor_agent_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "reviewer already reviewed this proposal"
            ) from exc
    return {
        "review_id": review_id,
        "proposal_id": proposal_id,
        "owner_user_id": owner_user_id,
        "reviewer_execution_id": actor_agent_id,
        "disposition": disposition,
        "scope_drift": scope_drift,
        "semantic_uncertainty": semantic_uncertainty,
        "evidence_refs": list(evidence_refs),
        "created_at": now,
    }


def _proposal_review_gate(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> None:
    proposal = conn.execute(
        """
        SELECT * FROM research_graph_proposals
        WHERE graph_id=? AND version=?
        ORDER BY created_at DESC, proposal_id DESC LIMIT 1
        """,
        (graph_id, int(version)),
    ).fetchone()
    if proposal is None:
        raise GraphActivationBlocked("graph proposal is missing")
    reviews = conn.execute(
        """
        SELECT * FROM research_graph_reviews
        WHERE proposal_id=? ORDER BY created_at, review_id
        """,
        (proposal["proposal_id"],),
    ).fetchall()
    if not reviews:
        raise GraphActivationBlocked("independent proposal review is missing")
    if any(bool(row["scope_drift"]) for row in reviews):
        raise GraphActivationBlocked("proposal review detected scope drift")
    disagreement = any(
        str(row["disposition"]) in {"rejected", "disagreed"}
        or bool(row["semantic_uncertainty"])
        for row in reviews
    )
    if disagreement and len(reviews) < 3:
        raise GraphActivationBlocked(
            "review disagreement requires a third reviewer"
        )
    approved_count = sum(
        str(row["disposition"]) == "approved" for row in reviews
    )
    if approved_count <= len(reviews) // 2:
        raise GraphActivationBlocked(
            "proposal does not have an independent approval majority"
        )


def record_audit(
    *,
    graph_id: str,
    version: int,
    actor: str,
    disposition: str,
    grill_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if disposition not in {"approved", "rejected", "quarantined", "frozen"}:
        raise ValueError("invalid audit disposition")
    if not isinstance(grill_evidence, list) or not grill_evidence:
        raise ValueError("grill_evidence must be a non-empty array")
    _assert_no_skill_identity(grill_evidence, location="grill evidence")
    audit_id = uuid.uuid4().hex
    row = {
        "audit_id": audit_id,
        "graph_id": graph_id,
        "version": int(version),
        "actor": actor,
        "disposition": disposition,
        "grill_evidence": deepcopy(grill_evidence),
        "created_at": time.time(),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if _graph_lifecycle(
            conn,
            graph_id=graph_id,
            version=version,
        ) is None:
            raise KeyError("graph version not found")
        conn.execute(
            """
            INSERT INTO research_graph_audits (
                audit_id, graph_id, version, actor, disposition,
                grill_evidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                graph_id,
                int(version),
                actor,
                disposition,
                orjson.dumps(
                    grill_evidence,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                row["created_at"],
            ),
        )
    return row


def _latest_validation(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT evidence_json FROM research_graph_validations
        WHERE graph_id=? AND version=?
        ORDER BY created_at DESC, validation_id DESC LIMIT 1
        """,
        (graph_id, int(version)),
    ).fetchone()
    return _loads(row["evidence_json"]) if row is not None else None


def _latest_audit(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    version: int,
) -> str:
    row = conn.execute(
        """
        SELECT disposition FROM research_graph_audits
        WHERE graph_id=? AND version=?
        ORDER BY created_at DESC, audit_id DESC LIMIT 1
        """,
        (graph_id, int(version)),
    ).fetchone()
    return str(row["disposition"]) if row is not None else ""


def authorize_graph_activation(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    proposal_id: str,
    graph_hash: str,
    diff_hash: str,
    nonce: str,
    authorized_by: str,
    expires_at: float,
    human_attestation: str,
) -> dict[str, Any]:
    """Ingest an authorization signed by a human-presence adapter."""
    secret = os.environ.get("RESEARCH_HUMAN_ACTIVATION_SECRET", "")
    if not secret:
        raise ValueError("trusted human activation adapter is not configured")
    if not nonce or len(nonce.encode()) > 256:
        raise ValueError("human activation nonce is required and bounded")
    if not authorized_by.strip():
        raise ValueError("authorized_by is required")
    now = time.time()
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        raise ValueError("expires_at must be a timestamp")
    if not now + 5 <= float(expires_at) <= now + 900:
        raise ValueError("human activation authorization must expire within 15 minutes")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(graph_version),
        )
        if graph is None or graph.get("lifecycle") != "draft":
            raise ValueError("human activation requires a draft graph")
        proposal = conn.execute(
            """
            SELECT * FROM research_graph_proposals
            WHERE proposal_id=? AND graph_id=? AND version=?
            """,
            (proposal_id, graph_id, int(graph_version)),
        ).fetchone()
        if proposal is None:
            raise ValueError("human activation proposal is invalid")
        actual_graph_hash = str(graph["content_hash"])
        actual_diff_hash = _json_hash(_loads(proposal["change_diff_json"]) or {})
        if graph_hash != actual_graph_hash or diff_hash != actual_diff_hash:
            raise ValueError("human activation target hash mismatch")
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
        signed_payload = {
            "owner_user_id": owner_user_id,
            "graph_id": graph_id,
            "graph_version": int(graph_version),
            "graph_hash": actual_graph_hash,
            "proposal_id": proposal_id,
            "diff_hash": actual_diff_hash,
            "nonce_hash": nonce_hash,
            "authorized_by": authorized_by,
            "expires_at": float(expires_at),
        }
        expected = hmac.new(
            secret.encode(),
            orjson.dumps(signed_payload, option=orjson.OPT_SORT_KEYS),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, human_attestation):
            raise ValueError("human activation attestation is invalid")
        authorization_id = uuid.uuid4().hex
        try:
            conn.execute(
                """
                INSERT INTO human_activation_authorizations (
                    authorization_id, owner_user_id, graph_id, graph_version,
                    graph_hash, proposal_id, diff_hash, nonce_hash,
                    authorized_by, human_attestation, expires_at, consumed_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    authorization_id,
                    owner_user_id,
                    graph_id,
                    int(graph_version),
                    actual_graph_hash,
                    proposal_id,
                    actual_diff_hash,
                    nonce_hash,
                    authorized_by,
                    human_attestation,
                    float(expires_at),
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("human activation nonce was already used") from exc
    return {
        "authorization_id": authorization_id,
        **signed_payload,
        "created_at": now,
    }


def _consume_human_activation_authorization(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    graph: dict[str, Any],
    authorization_id: str,
) -> str:
    proposal = conn.execute(
        """
        SELECT * FROM research_graph_proposals
        WHERE graph_id=? AND version=?
        ORDER BY created_at DESC, proposal_id DESC LIMIT 1
        """,
        (graph["graph_id"], int(graph["version"])),
    ).fetchone()
    if proposal is None:
        raise GraphActivationBlocked("graph proposal is missing")
    row = conn.execute(
        """
        SELECT * FROM human_activation_authorizations
        WHERE authorization_id=? AND owner_user_id=? AND graph_id=?
        AND graph_version=? AND graph_hash=? AND proposal_id=?
        AND consumed_at IS NULL AND expires_at>?
        """,
        (
            authorization_id,
            owner_user_id,
            graph["graph_id"],
            int(graph["version"]),
            graph["content_hash"],
            proposal["proposal_id"],
            time.time(),
        ),
    ).fetchone()
    expected_diff_hash = _json_hash(
        _loads(proposal["change_diff_json"]) or {}
    )
    if row is None or str(row["diff_hash"]) != expected_diff_hash:
        raise GraphActivationBlocked(
            "valid one-time human activation authorization is required"
        )
    consumed_at = time.time()
    updated = conn.execute(
        """
        UPDATE human_activation_authorizations SET consumed_at=?
        WHERE authorization_id=? AND consumed_at IS NULL
        """,
        (consumed_at, authorization_id),
    )
    if updated.rowcount != 1:
        raise GraphActivationBlocked(
            "human activation authorization was already consumed"
        )
    return str(row["authorized_by"])


def activate_graph(
    *,
    graph_id: str,
    source_version: int,
    actor: str,
    human_authorization_id: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=source_version,
        )
        if source is None:
            raise KeyError("graph version not found")
        if source["lifecycle"] != "draft":
            raise GraphActivationBlocked("only a draft graph can be activated")
        _proposal_review_gate(
            conn,
            graph_id=graph_id,
            version=source_version,
        )
        validation = _latest_validation(
            conn, graph_id=graph_id, version=source_version,
        )
        if validation is None:
            raise GraphActivationBlocked("validation evidence is missing")
        failed = [gate for gate in _VALIDATION_GATES if validation.get(gate) is not True]
        if failed:
            raise GraphActivationBlocked(
                "activation gates failed: " + ", ".join(failed)
            )
        if validation.get("token_metrics_authority") != "server_derived":
            raise GraphActivationBlocked(
                "activation requires server-derived token metrics"
            )
        if _latest_audit(
            conn, graph_id=graph_id, version=source_version,
        ) != "approved":
            raise GraphActivationBlocked("latest grill audit is not approved")
        human_actor = _consume_human_activation_authorization(
            conn,
            owner_user_id=actor,
            graph=source,
            authorization_id=human_authorization_id,
        )
        next_version = int(conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM research_graph_versions WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()["next_version"])
        active = deepcopy(source)
        active.pop("created_by", None)
        active.pop("created_at", None)
        active.update({
            "version": next_version,
            "lifecycle": "active",
            "parent_version": int(source_version),
            "activated_from_hash": source["content_hash"],
        })
        active["content_hash"] = _content_hash(active)
        stored = _insert_graph(conn, active, actor=human_actor)
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(graph_id) DO UPDATE SET
                version=excluded.version,
                activated_by=excluded.activated_by,
                activated_at=excluded.activated_at
            """,
            (graph_id, next_version, human_actor, time.time()),
        )
    return stored


def rollback_active_graph(
    *,
    graph_id: str,
    target_version: int,
    actor: str,
    reason: str,
    grill_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if not str(reason).strip():
        raise ValueError("rollback reason is required")
    if not isinstance(grill_evidence, list) or not grill_evidence:
        raise ValueError("rollback requires grill_evidence")
    _assert_no_skill_identity(
        grill_evidence,
        location="rollback grill evidence",
    )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        current = conn.execute(
            """
            SELECT version FROM active_research_graphs WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if current is None:
            raise KeyError("active graph not found")
        from_version = int(current["version"])
        if from_version == int(target_version):
            raise ValueError("rollback target is already active")
        if _graph_lifecycle(
            conn,
            graph_id=graph_id,
            version=target_version,
        ) != "active":
            raise KeyError("rollback target active version not found")
        target = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=target_version,
        ) or {}
        now = time.time()
        rollback_id = uuid.uuid4().hex
        conn.execute(
            """
            UPDATE active_research_graphs
            SET version=?, activated_by=?, activated_at=?
            WHERE graph_id=?
            """,
            (int(target_version), actor, now, graph_id),
        )
        conn.execute(
            """
            INSERT INTO research_graph_rollbacks (
                rollback_id, graph_id, from_version, to_version, actor,
                reason, grill_evidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollback_id,
                graph_id,
                from_version,
                int(target_version),
                actor,
                str(reason),
                orjson.dumps(
                    grill_evidence,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                now,
            ),
        )
    return {
        "rollback_id": rollback_id,
        "graph_id": graph_id,
        "from_version": from_version,
        "to_version": int(target_version),
        "actor": actor,
        "reason": str(reason),
        "grill_evidence": deepcopy(grill_evidence),
        "active_graph": target,
        "created_at": now,
    }


def load_active_graph(*, graph_id: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT version FROM active_research_graphs
            WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if row is None:
            return None
        return _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(row["version"]),
        )


def _branch_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "branch_id": str(row["branch_id"]),
        "instance_id": str(row["instance_id"]),
        "label": str(row["label"]),
        "current_node": str(row["current_node"]),
        "status": str(row["status"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _normalize_node_resolution(
    resolution: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any]:
    if not isinstance(resolution, dict):
        raise ValueError("capability_resolution must be an object")
    declared_node = str(resolution.get("node_id") or node_id)
    if declared_node != node_id:
        raise ValueError(
            f"capability resolution is for {declared_node}, not {node_id}"
        )
    if resolution.get("scope") == "activation_audit":
        raise ValueError(
            "runtime requires a current-node capability resolution"
        )
    value = deepcopy(resolution)
    value["node_id"] = node_id
    for key in (
        "bindings",
        "gaps",
        "triggered_conditional_bindings",
        "triggered_conditional_gaps",
        "undetermined_conditions",
    ):
        items = value.get(key, [])
        if not isinstance(items, list):
            raise ValueError(f"capability resolution {key} must be an array")
        semantic_items = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(
                    f"capability resolution {key} entries must be objects"
                )
            semantic_items.append({
                field: deepcopy(item[field])
                for field in (
                    "capability_id",
                    "capability_description",
                    "descriptor_hash",
                    "reason",
                    "required_by",
                    "explanation",
                )
                if field in item
            })
        value[key] = semantic_items
    value.pop("provider_source_states", None)
    return value


def _store_node_resolution(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    node_id: str,
    resolution: dict[str, Any],
) -> dict[str, Any]:
    value = _normalize_node_resolution(resolution, node_id=node_id)
    serialized = orjson.dumps(
        value,
        option=orjson.OPT_SORT_KEYS,
    ).decode()
    semantic_cache_key = str(
        value.get("semantic_cache_key")
        or (value.get("cache") or {}).get("key")
        or hashlib.sha256(serialized.encode()).hexdigest()
    )
    conn.execute(
        """
        INSERT INTO research_graph_node_resolutions (
            instance_id, branch_id, node_id, resolution_json,
            semantic_cache_key, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id, branch_id, node_id) DO UPDATE SET
            resolution_json=excluded.resolution_json,
            semantic_cache_key=excluded.semantic_cache_key,
            created_at=excluded.created_at
        WHERE research_graph_node_resolutions.semantic_cache_key
              <> excluded.semantic_cache_key
        """,
        (
            instance_id,
            branch_id,
            node_id,
            serialized,
            semantic_cache_key,
            time.time(),
        ),
    )
    return value


def _load_node_resolution(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT resolution_json FROM research_graph_node_resolutions
        WHERE instance_id=? AND branch_id=? AND node_id=?
        """,
        (instance_id, branch_id, node_id),
    ).fetchone()
    return _loads(row["resolution_json"]) if row is not None else None


def record_capability_approval(
    *,
    owner_user_id: str,
    capability_id: str,
    descriptor_hash: str,
    product_group: str,
    actor: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    if not capability_id or not product_group:
        raise ValueError("capability_id and product_group are required")
    if len(descriptor_hash) != 64 or any(
        character not in "0123456789abcdef"
        for character in descriptor_hash
    ):
        raise ValueError("descriptor_hash must be sha256")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError("capability approval requires evidence_refs")
    approval_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO research_capability_approvals (
                approval_id, owner_user_id, capability_id, descriptor_hash,
                product_group, actor, evidence_refs_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                owner_user_id,
                capability_id,
                descriptor_hash,
                product_group,
                actor,
                orjson.dumps(evidence_refs).decode(),
                now,
            ),
        )
    return {
        "approval_id": approval_id,
        "owner_user_id": owner_user_id,
        "capability_id": capability_id,
        "descriptor_hash": descriptor_hash,
        "product_group": product_group,
        "actor": actor,
        "evidence_refs": list(evidence_refs),
        "created_at": now,
    }


def _attestation_secret(conn: sqlite3.Connection) -> bytes:
    row = conn.execute(
        "SELECT secret FROM research_graph_server_secrets WHERE secret_id=1"
    ).fetchone()
    if row is not None:
        return bytes(row["secret"])
    secret = os.urandom(32)
    conn.execute(
        """
        INSERT INTO research_graph_server_secrets (secret_id, secret)
        VALUES (1, ?)
        """,
        (secret,),
    )
    return secret


def _receipt_signature(
    secret: bytes,
    payload: dict[str, Any],
) -> str:
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return hmac.new(secret, raw, hashlib.sha256).hexdigest()


def _backend_assurance_packet(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    anomaly_codes = _loads(row["anomaly_codes_json"]) or []
    verifier_disposition = str(row["verifier_disposition"] or "")
    disposition = str(row["disposition"])
    packet = {
        "receipt_id": str(row["receipt_id"]),
        "receipt_ref": f"backend-assurance:{row['receipt_id']}",
        "job_id": str(row["job_id"]),
        "terminal_status": str(row["terminal_status"]),
        "disposition": disposition,
        "anomaly_codes": anomaly_codes,
        "requires_verifier": (
            disposition == "verifier_required" and not verifier_disposition
        ),
        "verifier_disposition": verifier_disposition,
        "policy_hash": str(row["policy_hash"]),
        "server_attestation": str(row["server_attestation"]),
        "next_action": (
            "launch_one_backend_verifier"
            if disposition == "verifier_required" and not verifier_disposition
            else "continue"
            if disposition == "trusted"
            or verifier_disposition == "confirmed_reliable"
            else "route_capability_gap_and_propose_change"
            if verifier_disposition == "backend_change_proposed"
            else "revise_research_input"
            if verifier_disposition == "research_input_issue"
            else "stop_or_retry"
        ),
        "receipt_bytes": 0,
    }
    for _ in range(2):
        packet["receipt_bytes"] = len(orjson.dumps(packet))
    if len(orjson.dumps(packet)) > _MAX_ASSURANCE_RECEIPT_BYTES:
        raise ValueError("backend assurance packet exceeds hard byte limit")
    return packet


def evaluate_backend_assurance(
    *,
    owner_user_id: str,
    job_id: str,
    instance_id: str,
    branch_id: str,
    node_id: str,
    policy_hash: str = _BACKEND_ASSURANCE_POLICY_HASH,
    implementation_execution_id: str = "",
) -> dict[str, Any]:
    """Issue one compact deterministic receipt for an immutable terminal job."""
    if policy_hash != _BACKEND_ASSURANCE_POLICY_HASH:
        raise ValueError("backend assurance policy hash is not active")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        existing = conn.execute(
            """
            SELECT * FROM research_backend_assurance_receipts
            WHERE job_id=? AND owner_user_id=?
            """,
            (job_id, owner_user_id),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["instance_id"]) != instance_id
                or str(existing["branch_id"]) != branch_id
                or str(existing["node_id"]) != node_id
                or str(existing["policy_hash"]) != policy_hash
            ):
                raise ValueError(
                    "job already has an assurance receipt for another context"
                )
            return _backend_assurance_packet(existing)
        runtime = conn.execute(
            """
            SELECT i.graph_id, i.graph_version, i.owner, b.current_node
            FROM research_graph_instances i
            JOIN research_graph_branches b ON b.instance_id=i.instance_id
            WHERE i.instance_id=? AND b.branch_id=?
            """,
            (instance_id, branch_id),
        ).fetchone()
        if runtime is None or str(runtime["owner"]) != owner_user_id:
            raise ValueError("owned research graph branch is required")
        if str(runtime["current_node"]) != node_id:
            raise ValueError("backend assurance node is not current")
        graph = _load_graph_from_conn(
            conn,
            graph_id=str(runtime["graph_id"]),
            version=int(runtime["graph_version"]),
        )
        if graph is None:
            raise ValueError("research graph version is missing")
        job = conn.execute(
            """
            SELECT * FROM research_jobs
            WHERE job_id=? AND owner=?
            """,
            (job_id, owner_user_id),
        ).fetchone()
        if job is None:
            raise KeyError("research job not found")
        terminal_status = str(job["status"])
        if terminal_status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("backend assurance requires a terminal job")
        if implementation_execution_id:
            _require_agent_execution(
                conn,
                owner_user_id=owner_user_id,
                execution_id=implementation_execution_id,
                role="implementation_agent",
            )

        anomalies: list[str] = []
        checks_bitmap = 1
        job_spec = _loads(job["job_spec_json"]) or {}
        actual_job_spec_hash = _json_hash(job_spec)
        if actual_job_spec_hash == str(job["job_spec_hash"]):
            checks_bitmap |= 2
        else:
            anomalies.append("job_spec_hash_mismatch")

        execution_plan = _loads(job["execution_plan_json"])
        execution_plan_hash = str(job["execution_plan_hash"] or "")
        if (
            isinstance(execution_plan, dict)
            and execution_plan_hash
            and _json_hash(execution_plan) == execution_plan_hash
        ):
            checks_bitmap |= 4
        else:
            anomalies.append("execution_plan_missing_or_changed")

        run = conn.execute(
            """
            SELECT * FROM research_runs WHERE run_id=? AND owner=?
            """,
            (str(job["run_id"]), owner_user_id),
        ).fetchone()
        runspec_hash = str(run["run_spec_hash"]) if run is not None else ""
        if (
            run is not None
            and _json_hash(_loads(run["run_spec_json"]) or {}) == runspec_hash
            and str(run["workspace_id"]) == str(job["workspace_id"])
        ):
            checks_bitmap |= 8
        else:
            anomalies.append("runspec_missing_or_changed")

        result_summary = _loads(job["result_summary_json"])
        result_summary_hash = (
            _json_hash(result_summary) if result_summary is not None else ""
        )
        error = _loads(job["error_json"])
        if terminal_status == "succeeded":
            if result_summary is None:
                anomalies.append("succeeded_without_result")
            if error is not None:
                anomalies.append("succeeded_with_error")
            if job["worker_exitcode"] != 0:
                anomalies.append("succeeded_without_zero_exit")
            if not any(code.startswith("succeeded_") for code in anomalies):
                checks_bitmap |= 16
        elif terminal_status == "failed":
            if error is not None:
                checks_bitmap |= 16
            else:
                anomalies.append("failed_without_error")
        else:
            checks_bitmap |= 16

        artifacts = conn.execute(
            """
            SELECT name, content_hash, size_bytes, state
            FROM research_job_artifacts
            WHERE job_id=? ORDER BY name
            """,
            (job_id,),
        ).fetchall()
        artifact_manifest = [
            {
                "name": str(item["name"]),
                "content_hash": str(item["content_hash"]),
                "size_bytes": int(item["size_bytes"]),
                "state": str(item["state"]),
            }
            for item in artifacts
        ]
        artifact_manifest_hash = _json_hash(artifact_manifest)
        if all(
            item["state"] != "active" or bool(item["content_hash"])
            for item in artifact_manifest
        ):
            checks_bitmap |= 32
        else:
            anomalies.append("active_artifact_without_hash")

        integrity_anomalies = {
            "job_spec_hash_mismatch",
            "execution_plan_missing_or_changed",
            "runspec_missing_or_changed",
            "active_artifact_without_hash",
        }
        if terminal_status == "succeeded" and anomalies:
            disposition = "verifier_required"
        elif any(code in integrity_anomalies for code in anomalies):
            disposition = "verifier_required"
        elif terminal_status == "succeeded":
            disposition = "trusted"
        else:
            disposition = "not_usable"
        receipt_id = uuid.uuid4().hex
        created_at = time.time()
        signed_payload = {
            "receipt_id": receipt_id,
            "owner_user_id": owner_user_id,
            "run_id": str(job["run_id"]),
            "job_id": job_id,
            "attempt_id": int(job["attempt"]),
            "graph_id": str(runtime["graph_id"]),
            "graph_version": int(runtime["graph_version"]),
            "graph_hash": str(graph["content_hash"]),
            "instance_id": instance_id,
            "branch_id": branch_id,
            "node_id": node_id,
            "runspec_hash": runspec_hash,
            "execution_plan_hash": execution_plan_hash,
            "backend_revision": str(job["source_revision"] or "unattested"),
            "policy_hash": policy_hash,
            "terminal_status": terminal_status,
            "disposition": disposition,
            "checks_bitmap": checks_bitmap,
            "anomaly_codes": anomalies,
            "result_summary_hash": result_summary_hash,
            "artifact_manifest_hash": artifact_manifest_hash,
            "implementation_execution_id": implementation_execution_id,
            "created_at": created_at,
        }
        server_attestation = _receipt_signature(
            _attestation_secret(conn),
            signed_payload,
        )
        conn.execute(
            """
            INSERT INTO research_backend_assurance_receipts (
                receipt_id, owner_user_id, run_id, job_id, attempt_id,
                graph_id, graph_version, graph_hash, instance_id, branch_id,
                node_id, runspec_hash, execution_plan_hash, backend_revision,
                policy_hash, terminal_status, disposition, checks_bitmap,
                anomaly_codes_json, result_summary_hash,
                artifact_manifest_hash, implementation_execution_id,
                server_attestation, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                receipt_id,
                owner_user_id,
                str(job["run_id"]),
                job_id,
                int(job["attempt"]),
                str(runtime["graph_id"]),
                int(runtime["graph_version"]),
                str(graph["content_hash"]),
                instance_id,
                branch_id,
                node_id,
                runspec_hash,
                execution_plan_hash,
                str(job["source_revision"] or "unattested"),
                policy_hash,
                terminal_status,
                disposition,
                checks_bitmap,
                orjson.dumps(anomalies).decode(),
                result_summary_hash,
                artifact_manifest_hash,
                implementation_execution_id,
                server_attestation,
                created_at,
            ),
        )
        stored = conn.execute(
            """
            SELECT * FROM research_backend_assurance_receipts
            WHERE receipt_id=?
            """,
            (receipt_id,),
        ).fetchone()
    return _backend_assurance_packet(stored)


def record_backend_assurance_verification(
    *,
    owner_user_id: str,
    receipt_id: str,
    verifier_execution_id: str,
    disposition: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    if disposition not in {
        "confirmed_reliable",
        "backend_change_proposed",
        "research_input_issue",
    }:
        raise ValueError("invalid backend verifier disposition")
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or len(evidence_refs) > _MAX_CONTEXT_EVIDENCE_REFS
        or not all(
            isinstance(ref, str)
            and ref.strip()
            and len(ref.encode()) <= _MAX_EVIDENCE_REF_BYTES
            for ref in evidence_refs
        )
    ):
        raise ValueError("bounded verifier evidence_refs are required")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT * FROM research_backend_assurance_receipts
            WHERE receipt_id=? AND owner_user_id=?
            """,
            (receipt_id, owner_user_id),
        ).fetchone()
        if row is None:
            raise KeyError("backend assurance receipt not found")
        if str(row["disposition"]) != "verifier_required":
            raise ValueError("trusted backend receipt does not accept a verifier")
        if str(row["verifier_execution_id"]):
            raise ValueError("backend assurance receipt is already verified")
        verifier = _require_agent_execution(
            conn,
            owner_user_id=owner_user_id,
            execution_id=verifier_execution_id,
            role="backend_verifier",
        )
        implementation_execution_id = str(
            row["implementation_execution_id"] or ""
        )
        if implementation_execution_id:
            implementation = _require_agent_execution(
                conn,
                owner_user_id=owner_user_id,
                execution_id=implementation_execution_id,
                role="implementation_agent",
            )
            if (
                str(implementation["agent_principal_hash"])
                == str(verifier["agent_principal_hash"])
                or str(implementation["lineage_hash"])
                == str(verifier["lineage_hash"])
            ):
                raise ValueError(
                    "backend verifier principal and lineage must be independent"
                )
        verified_at = time.time()
        conn.execute(
            """
            UPDATE research_backend_assurance_receipts
            SET verifier_execution_id=?, verifier_disposition=?,
                evidence_refs_json=?, verified_at=?
            WHERE receipt_id=? AND verifier_execution_id=''
            """,
            (
                verifier_execution_id,
                disposition,
                orjson.dumps(evidence_refs).decode(),
                verified_at,
                receipt_id,
            ),
        )
        stored = conn.execute(
            """
            SELECT * FROM research_backend_assurance_receipts
            WHERE receipt_id=?
            """,
            (receipt_id,),
        ).fetchone()
    return _backend_assurance_packet(stored)


def issue_capability_receipt(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    node_id: str,
    product_group: str,
    catalog_hash: str,
    product_profile_hash: str,
    resolver_version: str,
    semantic_resolution: dict[str, Any],
    approval_refs: dict[str, str],
    provider_conformance_hash: str,
    shadow_mode: bool = False,
) -> dict[str, Any]:
    for field, value in (
        ("catalog_hash", catalog_hash),
        ("product_profile_hash", product_profile_hash),
        ("provider_conformance_hash", provider_conformance_hash),
    ):
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"{field} must be sha256")
    if not resolver_version:
        raise ValueError("resolver_version is required")
    if not isinstance(approval_refs, dict):
        raise ValueError("approval_refs must be an object")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=graph_version,
        ) or {}
        if shadow_mode:
            if graph.get("lifecycle") != "draft":
                raise ValueError("shadow receipt requires a draft graph")
            receipt_mode = "shadow"
        else:
            active = conn.execute(
                """
                SELECT version FROM active_research_graphs WHERE graph_id=?
                """,
                (graph_id,),
            ).fetchone()
            if active is None or int(active["version"]) != int(graph_version):
                raise ValueError("receipt graph version is not active")
            receipt_mode = "live"
        node = next(
            (
                item for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == node_id
            ),
            None,
        )
        if node is None:
            raise ValueError("receipt node is not in the active graph")
        resolution = _normalize_node_resolution(
            semantic_resolution,
            node_id=node_id,
        )
        allowed_ids = set(node.get("required_capabilities") or []) | {
            str(item.get("capability_id") or "")
            for item in node.get("conditional_capabilities") or []
        }
        descriptors = graph.get("capability_descriptors") or {}
        for key in ("bindings", "triggered_conditional_bindings"):
            for binding in resolution.get(key) or []:
                capability_id = str(binding.get("capability_id") or "")
                expected = descriptors.get(capability_id)
                if capability_id not in allowed_ids or binding != {
                    "capability_id": capability_id,
                    "capability_description": expected.get(
                        "capability_description"
                    ) if expected else None,
                    "descriptor_hash": expected.get(
                        "descriptor_hash"
                    ) if expected else None,
                }:
                    raise ValueError(
                        f"capability descriptor mismatch: {capability_id}"
                    )
                approval_id = str(approval_refs.get(capability_id) or "")
                approval = conn.execute(
                    """
                    SELECT * FROM research_capability_approvals
                    WHERE approval_id=? AND owner_user_id=?
                    AND capability_id=? AND descriptor_hash=?
                    AND product_group IN (?, 'all')
                    """,
                    (
                        approval_id,
                        owner_user_id,
                        capability_id,
                        binding["descriptor_hash"],
                        product_group,
                    ),
                ).fetchone()
                if approval is None:
                    raise ValueError(
                        f"approved capability receipt is missing: {capability_id}"
                    )
        receipt_id = uuid.uuid4().hex
        signed_payload = {
            "receipt_id": receipt_id,
            "owner_user_id": owner_user_id,
            "graph_id": graph_id,
            "graph_version": int(graph_version),
            "graph_hash": str(graph["content_hash"]),
            "node_id": node_id,
            "product_group": product_group,
            "catalog_hash": catalog_hash,
            "product_profile_hash": product_profile_hash,
            "resolver_version": resolver_version,
            "resolution": resolution,
            "approval_refs": approval_refs,
            "provider_conformance_hash": provider_conformance_hash,
            "receipt_mode": receipt_mode,
        }
        signature = _receipt_signature(
            _attestation_secret(conn),
            signed_payload,
        )
        now = time.time()
        conn.execute(
            """
            INSERT INTO research_capability_receipts (
                receipt_id, owner_user_id, graph_id, graph_version, graph_hash,
                node_id, product_group, catalog_hash, product_profile_hash,
                resolver_version, resolution_json, approval_refs_json,
                provider_conformance_hash, resolver_attestation, receipt_mode,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                owner_user_id,
                graph_id,
                int(graph_version),
                graph["content_hash"],
                node_id,
                product_group,
                catalog_hash,
                product_profile_hash,
                resolver_version,
                orjson.dumps(resolution, option=orjson.OPT_SORT_KEYS).decode(),
                orjson.dumps(approval_refs, option=orjson.OPT_SORT_KEYS).decode(),
                provider_conformance_hash,
                signature,
                receipt_mode,
                now,
            ),
        )
    return {
        **signed_payload,
        "resolver_attestation": signature,
        "created_at": now,
    }


def _verify_capability_receipt(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    receipt: dict[str, Any],
    graph_id: str,
    graph_version: int,
    node_id: str,
    product_group: str,
    expected_mode: str,
) -> dict[str, Any]:
    receipt_id = str(receipt.get("receipt_id") or "")
    signature = str(receipt.get("resolver_attestation") or "")
    row = conn.execute(
        """
        SELECT * FROM research_capability_receipts
        WHERE receipt_id=? AND owner_user_id=? AND graph_id=?
        AND graph_version=? AND node_id=? AND product_group=?
        AND receipt_mode=?
        """,
        (
            receipt_id,
            owner_user_id,
            graph_id,
            int(graph_version),
            node_id,
            product_group,
            expected_mode,
        ),
    ).fetchone()
    if row is None or not hmac.compare_digest(
        signature,
        str(row["resolver_attestation"]),
    ):
        raise ValueError("valid server capability receipt is required")
    return _loads(row["resolution_json"]) or {}


def _missing_required_capabilities(
    node: dict[str, Any],
    resolution: dict[str, Any],
) -> list[str]:
    bound_capabilities = {
        str(item.get("capability_id") or "")
        for key in ("bindings", "triggered_conditional_bindings")
        for item in resolution.get(key) or []
        if isinstance(item, dict)
    }
    return sorted(
        set(node.get("required_capabilities") or []) - bound_capabilities
    )


def create_graph_instance(
    *,
    graph_id: str,
    owner: str,
    product_group: str,
    workspace_id: str,
    capability_receipt: dict[str, Any],
    token_budget: int | None = None,
    shadow_graph_version: int | None = None,
    shadow_run_id: str = "",
) -> dict[str, Any]:
    if shadow_graph_version is not None:
        active = load_graph(
            graph_id=graph_id,
            version=int(shadow_graph_version),
        )
        if active is None or active.get("lifecycle") != "draft":
            raise GraphActivationBlocked("shadow draft graph not found")
        if not shadow_run_id:
            raise ValueError("shadow_run_id is required for a shadow instance")
        mode = "shadow"
    else:
        if shadow_run_id:
            raise ValueError("shadow_run_id is only valid in shadow mode")
        active = load_active_graph(graph_id=graph_id)
        if active is None:
            raise GraphActivationBlocked("active graph not found")
        mode = "live"
    entry_node = str(
        active.get("entry_node")
        or ((active.get("nodes") or [{}])[0].get("node_id") or "")
    )
    declared_nodes = {
        str(node.get("node_id") or "") for node in active.get("nodes") or []
    }
    if not entry_node or entry_node not in declared_nodes:
        raise ValueError("active graph entry_node is invalid")
    entry = next(
        node for node in active.get("nodes") or []
        if str(node.get("node_id") or "") == entry_node
    )
    if (
        not isinstance(token_budget, int)
        or isinstance(token_budget, bool)
        or token_budget <= 0
    ):
        raise ValueError("token_budget must be a positive integer")
    instance_id = uuid.uuid4().hex
    branch_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if mode == "shadow":
            try:
                run = conn.execute(
                    """
                    SELECT run_id FROM research_runs
                    WHERE run_id=? AND owner=? AND workspace_id=?
                    AND kind='factor_research'
                    """,
                    (shadow_run_id, owner, workspace_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                raise ValueError(
                    "research run schema is not initialized"
                ) from exc
            if run is None:
                raise ValueError(
                    "shadow_run_id must reference an owned research run "
                    "in the same workspace"
                )
        local_resolution = _verify_capability_receipt(
            conn,
            owner_user_id=owner,
            receipt=capability_receipt,
            graph_id=graph_id,
            graph_version=int(active["version"]),
            node_id=entry_node,
            product_group=product_group,
            expected_mode=mode,
        )
        missing_entry = _missing_required_capabilities(entry, local_resolution)
        if missing_entry:
            raise ValueError(
                "entry node has unresolved capabilities: "
                + ", ".join(missing_entry)
            )
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, capability_resolution_json, token_budget,
                mode, shadow_run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                owner,
                graph_id,
                int(active["version"]),
                product_group,
                workspace_id,
                "{}",
                token_budget,
                mode,
                shadow_run_id,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_token_budgets (
                scope_id, owner_user_id, token_limit, used_tokens,
                reserved_tokens, created_at
            ) VALUES (?, ?, ?, 0, 0, ?)
            """,
            (f"instance:{instance_id}", owner, token_budget, now),
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                aggregate_version, created_at, updated_at
            ) VALUES (?, ?, 'primary', ?, 'running', 1, ?, ?)
            """,
            (branch_id, instance_id, entry_node, now, now),
        )
        _store_node_resolution(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            node_id=entry_node,
            resolution=local_resolution,
        )
        branch = {
            "branch_id": branch_id,
            "instance_id": instance_id,
            "label": "primary",
            "current_node": entry_node,
            "status": "running",
            "created_at": now,
            "updated_at": now,
        }
    return {
        "instance_id": instance_id,
        "owner": owner,
        "graph_id": graph_id,
        "graph_version": int(active["version"]),
        "product_group": product_group,
        "workspace_id": workspace_id,
        "capability_resolution": deepcopy(local_resolution),
        "token_budget": token_budget,
        "mode": mode,
        "shadow_run_id": shadow_run_id,
        "branches": [branch],
        "created_at": now,
    }


def _load_instance_branch_row(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT i.*, b.*
        FROM research_graph_instances i
        JOIN research_graph_branches b
          ON b.instance_id=i.instance_id
        WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
        """,
        (instance_id, branch_id, owner),
    ).fetchone()


def load_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = _load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
    return _branch_payload(row)


def fork_graph_branch(
    *,
    instance_id: str,
    source_branch_id: str,
    owner: str,
    label: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        source = _load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=source_branch_id,
            owner=owner,
        )
        if source is None:
            raise KeyError("source branch not found")
        branch_id = uuid.uuid4().hex
        now = time.time()
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                aggregate_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'running', 1, ?, ?)
            """,
            (
                branch_id,
                instance_id,
                str(label or "fork").strip(),
                str(source["current_node"]),
                now,
                now,
            ),
        )
        current_resolution = _load_node_resolution(
            conn,
            instance_id=instance_id,
            branch_id=source_branch_id,
            node_id=str(source["current_node"]),
        )
        if current_resolution is not None:
            _store_node_resolution(
                conn,
                instance_id=instance_id,
                branch_id=branch_id,
                node_id=str(source["current_node"]),
                resolution=current_resolution,
            )
    return {
        "branch_id": branch_id,
        "instance_id": instance_id,
        "label": str(label or "fork").strip(),
        "current_node": str(source["current_node"]),
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }


def advance_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("transition evidence must be an object")
    telemetry = evidence.get("token_telemetry") or {}
    if not isinstance(telemetry, dict):
        raise ValueError("token_telemetry must be an object")
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "skill_document_tokens",
        "artifact_summary_tokens",
        "reviewer_tokens",
    )
    for field in token_fields:
        value = telemetry.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"token_telemetry.{field} must be a non-negative integer")
    input_tokens = int(telemetry.get("input_tokens") or 0)
    for field in (
        "cache_read_tokens",
        "skill_document_tokens",
        "artifact_summary_tokens",
    ):
        if int(telemetry.get(field) or 0) > input_tokens:
            raise ValueError(
                f"token_telemetry.{field} is an input attribution subset"
            )
    if (
        int(telemetry.get("skill_document_tokens") or 0)
        + int(telemetry.get("artifact_summary_tokens") or 0)
        > input_tokens
    ):
        raise ValueError(
            "Skill document and artifact attribution exceed input tokens"
        )
    for field in ("model_id", "model_provider", "codex_version"):
        value = telemetry.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"token_telemetry.{field} must be a string")
    persisted_evidence = deepcopy(evidence)
    persisted_evidence.pop("target_capability_receipt", None)
    persisted_telemetry = {
        key: value
        for key, value in telemetry.items()
        if key not in {
            "loaded_skill_ids",
            "loaded_skill_receipts",
        }
    }
    persisted_evidence["token_telemetry"] = persisted_telemetry
    _assert_no_skill_identity(
        persisted_evidence,
        location="transition evidence",
    )
    for field in ("skill_document_load_count", "skill_context_cache_hits"):
        value = telemetry.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"token_telemetry.{field} must be a non-negative integer"
            )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        branch_row = _load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if branch_row is None:
            raise KeyError("graph branch not found")
        instance = branch_row
        branch = _branch_payload(branch_row) or {}
        reported_team_tokens = (
            int(telemetry.get("input_tokens") or 0)
            + int(telemetry.get("output_tokens") or 0)
            + int(telemetry.get("reviewer_tokens") or 0)
        )
        reservation_ids = evidence.get("token_reservation_ids") or []
        if not isinstance(reservation_ids, list) or not all(
            isinstance(item, str) and item for item in reservation_ids
        ):
            raise ValueError("token_reservation_ids must be an array")
        if reported_team_tokens and not reservation_ids:
            raise ValueError(
                "trusted committed token reservation is required"
            )
        authoritative_tokens = 0
        if reservation_ids:
            placeholders = ",".join("?" for _ in reservation_ids)
            rows = conn.execute(
                f"""
                SELECT r.reservation_id, p.input_tokens, p.output_tokens
                FROM research_token_reservations r
                JOIN research_provider_usage_receipts p
                  ON p.provider_receipt_id=r.provider_receipt_id
                WHERE r.reservation_id IN ({placeholders})
                  AND r.owner_user_id=? AND r.scope_id=?
                  AND r.status='committed'
                """,
                (
                    *reservation_ids,
                    owner,
                    f"instance:{instance_id}",
                ),
            ).fetchall()
            if len(rows) != len(set(reservation_ids)):
                raise ValueError(
                    "all token reservations must be committed and trusted"
                )
            authoritative_tokens = sum(
                int(row["input_tokens"]) + int(row["output_tokens"])
                for row in rows
            )
        if authoritative_tokens != reported_team_tokens:
            raise ValueError(
                "reported team token total does not match provider usage"
            )
        graph = _load_graph_from_conn(
            conn,
            graph_id=str(instance["graph_id"]),
            version=int(instance["graph_version"]),
        ) or {}
        edge = next(
            (
                item for item in graph.get("edges") or []
                if str(item.get("edge_id") or "") == edge_id
            ),
            None,
        )
        if edge is None:
            raise KeyError("graph edge not found")
        edge_from = str(edge.get("from_node") or "")
        if edge_from not in {branch["current_node"], "*"}:
            raise ValueError(
                f"edge {edge_id} does not leave current node "
                f"{branch['current_node']}"
            )
        if branch["status"] == "paused" and edge.get("edge_type") != "recovery":
            raise ValueError("paused branch only accepts a recovery edge")
        failed_guards = [
            key for key, expected in (edge.get("guard") or {}).items()
            if evidence.get(key) != expected
        ]
        if failed_guards:
            raise ValueError(
                "transition guards not satisfied: " + ", ".join(failed_guards)
            )
        required_evidence = edge.get("required_evidence") or []
        evidence_refs = evidence.get("evidence_refs") or []
        if required_evidence and (
            not isinstance(evidence_refs, list) or not evidence_refs
        ):
            raise ValueError("transition requires evidence_refs")
        target_id = str(edge.get("to_node") or "")
        target = next(
            (
                item for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == target_id
            ),
            None,
        )
        if target is None:
            raise ValueError("transition target node is missing")
        supplied_receipt = evidence.get("target_capability_receipt")
        if supplied_receipt is not None:
            supplied_resolution = _verify_capability_receipt(
                conn,
                owner_user_id=owner,
                receipt=supplied_receipt,
                graph_id=str(instance["graph_id"]),
                graph_version=int(instance["graph_version"]),
                node_id=target_id,
                product_group=str(instance["product_group"]),
                expected_mode=str(instance["mode"]),
            )
            target_resolution = _store_node_resolution(
                conn,
                instance_id=instance_id,
                branch_id=branch_id,
                node_id=target_id,
                resolution=supplied_resolution,
            )
        else:
            target_resolution = _load_node_resolution(
                conn,
                instance_id=instance_id,
                branch_id=branch_id,
                node_id=target_id,
            )
        if target_resolution is None:
            target_resolution = _store_node_resolution(
                conn,
                instance_id=instance_id,
                branch_id=branch_id,
                node_id=target_id,
                resolution={"node_id": target_id},
            )
        missing_capabilities = (
            _missing_required_capabilities(target, target_resolution or {})
        )
        if missing_capabilities and target.get("kind") != "capability_gap":
            raise ValueError(
                "target node has unresolved capabilities: "
                + ", ".join(missing_capabilities)
                + "; use the declared capability-gap edge"
            )
        status = (
            "paused"
            if target.get("kind") == "capability_gap"
            or target_id == "code_improvement_required"
            else "running"
        )
        now = time.time()
        trace_evidence = deepcopy(persisted_evidence)
        trace_evidence.pop("token_telemetry", None)
        if supplied_receipt is not None:
            trace_evidence["target_capability_receipt_ref"] = (
                f"node-resolution:{instance_id}:{branch_id}:{target_id}"
            )
        bounded_evidence_refs, omitted_evidence_count = (
            _merge_bounded_evidence_refs(
                _loads(branch_row["evidence_refs_json"]) or [],
                int(branch_row["omitted_evidence_count"]),
                trace_evidence.get("evidence_refs"),
            )
        )
        trace_id = uuid.uuid4().hex
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node=?, status=?,
                cumulative_input_tokens=cumulative_input_tokens+?,
                cumulative_output_tokens=cumulative_output_tokens+?,
                cumulative_cache_read_tokens=
                    cumulative_cache_read_tokens+?,
                cumulative_skill_document_tokens=
                    cumulative_skill_document_tokens+?,
                cumulative_artifact_summary_tokens=
                    cumulative_artifact_summary_tokens+?,
                cumulative_reviewer_tokens=cumulative_reviewer_tokens+?,
                skill_document_load_count=skill_document_load_count+?,
                skill_context_cache_hits=skill_context_cache_hits+?,
                evidence_refs_json=?, omitted_evidence_count=?,
                latest_trace_id=?, trace_count=trace_count+1,
                aggregate_version=1, updated_at=?
            WHERE branch_id=? AND instance_id=?
            """,
            (
                target_id,
                status,
                int(telemetry.get("input_tokens") or 0),
                int(telemetry.get("output_tokens") or 0),
                int(telemetry.get("cache_read_tokens") or 0),
                int(telemetry.get("skill_document_tokens") or 0),
                int(telemetry.get("artifact_summary_tokens") or 0),
                int(telemetry.get("reviewer_tokens") or 0),
                int(telemetry.get("skill_document_load_count") or 0),
                int(telemetry.get("skill_context_cache_hits") or 0),
                orjson.dumps(bounded_evidence_refs).decode(),
                omitted_evidence_count,
                trace_id,
                now,
                branch_id,
                instance_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                instance_id,
                branch_id,
                edge_id,
                branch["current_node"],
                target_id,
                orjson.dumps(
                    trace_evidence,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                orjson.dumps(
                    persisted_telemetry,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                owner,
                now,
            ),
        )
    return {
        "branch_id": branch_id,
        "instance_id": instance_id,
        "label": branch["label"],
        "current_node": target_id,
        "status": status,
        "created_at": branch["created_at"],
        "updated_at": now,
    }


def _build_graph_branch_local_state(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build compact current state plus internal candidate edge definitions."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        branch_row = _load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if branch_row is None:
            raise KeyError("graph branch not found")
        instance = branch_row
        branch = _branch_payload(branch_row)
        graph = _load_graph_from_conn(
            conn,
            graph_id=str(instance["graph_id"]),
            version=int(instance["graph_version"]),
        ) or {}
        node = next(
            (
                item for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == branch["current_node"]
            ),
            None,
        )
        if node is None:
            raise ValueError("current graph node is missing")
        available_edges = [
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "to_node": str(edge.get("to_node") or ""),
                "edge_type": str(edge.get("edge_type") or ""),
                "risk_level": str(edge.get("risk_level") or ""),
                "guard": deepcopy(edge.get("guard") or {}),
                "required_evidence": deepcopy(
                    edge.get("required_evidence") or []
                ),
            }
            for edge in graph.get("edges") or []
            if str(edge.get("from_node") or "") in {
                branch["current_node"],
                "*",
            }
            and (
                branch["status"] != "paused"
                or edge.get("edge_type") == "recovery"
            )
        ]
        resolution = _load_node_resolution(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            node_id=branch["current_node"],
        )
        if resolution is None:
            legacy_resolution = (
                _loads(instance["capability_resolution_json"]) or {}
            )
            resolution = _normalize_node_resolution(
                legacy_resolution,
                node_id=branch["current_node"],
            )
        binding_by_id = {
            str(item.get("capability_id") or ""): item
            for key in ("bindings", "triggered_conditional_bindings")
            for item in resolution.get(key) or []
            if isinstance(item, dict)
        }
        gap_by_id = {
            str(item.get("capability_id") or ""): item
            for key in ("gaps", "triggered_conditional_gaps")
            for item in resolution.get(key) or []
            if isinstance(item, dict)
        }
        required_capabilities = []
        for capability_id in node.get("required_capabilities") or []:
            required_capabilities.append({
                "capability_id": capability_id,
                "binding": deepcopy(binding_by_id.get(capability_id)),
                "gap": deepcopy(gap_by_id.get(capability_id)),
            })
        budget_row = conn.execute(
            """
            SELECT * FROM research_token_budgets
            WHERE scope_id=? AND owner_user_id=?
            """,
            (f"instance:{instance_id}", owner),
        ).fetchone()
    totals = {
        "input_tokens": int(branch_row["cumulative_input_tokens"]),
        "output_tokens": int(branch_row["cumulative_output_tokens"]),
        "cache_read_tokens": int(
            branch_row["cumulative_cache_read_tokens"]
        ),
        "skill_document_tokens": int(
            branch_row["cumulative_skill_document_tokens"]
        ),
        "artifact_summary_tokens": int(
            branch_row["cumulative_artifact_summary_tokens"]
        ),
        "reviewer_tokens": int(branch_row["cumulative_reviewer_tokens"]),
    }
    evidence_refs = _loads(branch_row["evidence_refs_json"]) or []
    totals["primary_total_tokens"] = (
        totals["input_tokens"] + totals["output_tokens"]
    )
    totals["team_total_tokens"] = (
        totals["primary_total_tokens"] + totals["reviewer_tokens"]
    )
    totals["total_tokens"] = totals["team_total_tokens"]
    totals["skill_document_load_count"] = int(
        branch_row["skill_document_load_count"]
    )
    totals["skill_context_cache_hits"] = int(
        branch_row["skill_context_cache_hits"]
    )
    token_budget = int(budget_row["token_limit"])
    authoritative_used = int(budget_row["used_tokens"])
    authoritative_reserved = int(budget_row["reserved_tokens"])
    authoritative_remaining = max(
        token_budget - authoritative_used - authoritative_reserved,
        0,
    )
    budget_exceeded = authoritative_remaining == 0
    totals["authority"] = "client_reported_diagnostic_only"
    totals["budget"] = {
        "limit": token_budget,
        "used": authoritative_used,
        "reserved": authoritative_reserved,
        "remaining": authoritative_remaining,
        "exceeded": budget_exceeded,
        "authority": "trusted_provider_usage_receipts",
    }
    current_ids = set(node.get("required_capabilities") or [])
    open_gaps = [
        deepcopy(gap)
        for capability_id, gap in gap_by_id.items()
        if capability_id in current_ids or node.get("kind") == "capability_gap"
    ]
    triggered_capabilities = [
        {
            "capability_id": capability_id,
            "binding": deepcopy(binding_by_id.get(capability_id)),
            "gap": deepcopy(gap_by_id.get(capability_id)),
        }
        for capability_id in sorted({
            str(item.get("capability_id") or "")
            for key in (
                "triggered_conditional_bindings",
                "triggered_conditional_gaps",
            )
            for item in resolution.get(key) or []
            if isinstance(item, dict)
        })
    ]
    context = {
        "graph": f"{graph['graph_id']}@v{graph['version']}",
        "branch": {
            "instance_id": instance_id,
            "branch_id": branch_id,
            "status": branch["status"],
            "product_group": str(instance["product_group"]),
            "workspace_id": str(instance["workspace_id"]),
        },
        "node": {
            "node_id": branch["current_node"],
            "kind": str(node.get("kind") or ""),
            "purpose": str(node.get("purpose") or ""),
        },
        "required_capabilities": required_capabilities,
        "triggered_capabilities": triggered_capabilities,
        "undetermined_conditions": deepcopy(
            resolution.get("undetermined_conditions") or []
        ),
        "evidence_refs": evidence_refs,
        "omitted_evidence_count": int(
            branch_row["omitted_evidence_count"]
        ),
        "history_cursor": (
            f"trace:{branch_row['latest_trace_id']}"
            if branch_row["latest_trace_id"]
            else None
        ),
        "open_gaps": open_gaps,
        "skill_policy": {
            "match_on": "capability_description",
            "agent_action": (
                "reuse_matching_runtime_skill_else_load_after_trigger_"
                "and_approval"
            ),
            "persist": "description_and_descriptor_hash_only",
        },
        "token_telemetry": totals,
        "review_policy": {
            "L1": "deterministic_only",
            "L2": (
                "zero_by_default; one_reviewer_only_for_conflict_"
                "semantic_uncertainty_or_low_confidence"
            ),
            "L3": "exactly_one_relevant_specialist_reviewer",
            "L4": (
                "one_proposer_plus_one_independent_reviewer; "
                "third_only_on_disagreement; grill_only_change_diff"
            ),
        },
        "review_gate": {
            "default_reviewer_count": 0,
            "max_new_reviewers": 0 if budget_exceeded else 2,
            "budget_action": (
                "defer_new_reviewers_keep_backend_jobs_running"
                if budget_exceeded
                else "within_budget"
            ),
            "l2_triggers": [
                "evidence_conflict",
                "semantic_uncertainty",
                "low_confidence",
            ],
            "l3_max_reviewers": 0 if budget_exceeded else 1,
            "l4_initial_reviewers": 0 if budget_exceeded else 2,
            "third_reviewer_only_on_disagreement": True,
            "running_backend_jobs_action": "continue",
        },
    }
    context["context_bytes"] = 0
    for _ in range(3):
        context["context_bytes"] = len(orjson.dumps(context))
    serialized_bytes = len(orjson.dumps(context))
    if serialized_bytes > _MAX_CONTEXT_BYTES:
        raise ValueError(
            f"bounded context exceeds {_MAX_CONTEXT_BYTES} bytes: "
            f"{serialized_bytes}"
        )
    return context, available_edges


def build_graph_branch_context(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return current state without edge-selection instructions."""
    context, _ = _build_graph_branch_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    return context


def build_graph_branch_next(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return deterministic edge readiness and only necessary Agent triggers."""
    context, edges = _build_graph_branch_local_state(
        instance_id=instance_id,
        branch_id=branch_id,
        owner=owner,
    )
    open_gap_ids = sorted({
        str(item.get("capability_id") or "")
        for item in context.get("open_gaps") or []
        if isinstance(item, dict)
    })
    undetermined_ids = sorted({
        str(item.get("capability_id") or "")
        for item in context.get("undetermined_conditions") or []
        if isinstance(item, dict)
    })
    candidates = []
    for edge in edges:
        guard_fields = sorted((edge.get("guard") or {}).keys())
        required_evidence = list(edge.get("required_evidence") or [])
        blockers = []
        if open_gap_ids and edge.get("edge_type") != "failure":
            blockers.append({
                "code": "open_capability_gaps",
                "capability_ids": open_gap_ids,
            })
        if undetermined_ids:
            blockers.append({
                "code": "semantic_conditions_undetermined",
                "capability_ids": undetermined_ids,
            })
        if blockers:
            readiness = "blocked"
        elif guard_fields or required_evidence:
            readiness = "requires_evidence"
        else:
            readiness = "ready"
        risk_level = str(edge.get("risk_level") or "L1")
        review_requirement = {
            "L1": "none",
            "L2": "self_check; one_reviewer_only_on_trigger",
            "L3": "one_specialist",
            "L4": "proposer_plus_independent_reviewer",
        }.get(risk_level, "invalid")
        candidates.append({
            "edge_id": str(edge.get("edge_id") or ""),
            "to_node": str(edge.get("to_node") or ""),
            "edge_type": str(edge.get("edge_type") or ""),
            "risk_level": risk_level,
            "readiness": readiness,
            "required_guard_fields": guard_fields,
            "required_evidence": required_evidence,
            "blockers": blockers,
            "review_requirement": review_requirement,
        })
    ready_l1 = [
        item["edge_id"]
        for item in candidates
        if item["readiness"] == "ready"
        and item["risk_level"] == "L1"
    ]
    recommended_edge_ids = ready_l1 if len(ready_l1) == 1 else []
    requires_agent_judgment = bool(
        undetermined_ids
        or len([
            item for item in candidates
            if item["readiness"] != "blocked"
        ]) > 1
    )
    budget = (
        (context.get("token_telemetry") or {}).get("budget") or {}
    )
    packet = {
        "graph": context["graph"],
        "branch": deepcopy(context["branch"]),
        "node": deepcopy(context["node"]),
        "context_ref": "sha256:" + hashlib.sha256(
            orjson.dumps(context, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
        "candidate_edges": candidates,
        "recommended_edge_ids": recommended_edge_ids,
        "requires_agent_judgment": requires_agent_judgment,
        "new_llm_work_allowed": int(budget.get("remaining") or 0) > 0,
        "running_backend_jobs_action": "continue",
        "next_bytes": 0,
    }
    for _ in range(3):
        packet["next_bytes"] = len(orjson.dumps(packet))
    serialized_bytes = len(orjson.dumps(packet))
    if serialized_bytes > _MAX_CONTEXT_BYTES:
        raise ValueError(
            f"bounded next packet exceeds {_MAX_CONTEXT_BYTES} bytes: "
            f"{serialized_bytes}"
        )
    return packet
