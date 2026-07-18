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


def _loads(value: str | None) -> Any:
    return orjson.loads(value) if value else None


def _content_hash(graph: dict[str, Any]) -> str:
    return protocol_graph_content_hash(graph)


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
        CREATE INDEX IF NOT EXISTS idx_research_graph_node_resolutions_branch
        ON research_graph_node_resolutions(instance_id, branch_id, node_id);
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


def ensure_schema() -> None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)


def _row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    graph = _loads(row["graph_json"]) or {}
    graph["created_by"] = str(row["created_by"])
    graph["created_at"] = float(row["created_at"])
    return graph


def _insert_graph(
    conn: sqlite3.Connection,
    graph: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    value = _validate_graph(graph)
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
                time.time(),
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
            return _row_payload(existing) or {}
        raise GraphVersionConflict(
            f"graph version is immutable: {value['graph_id']} "
            f"v{value['version']}"
        ) from exc
    row = conn.execute(
        """
        SELECT * FROM research_graph_versions
        WHERE graph_id=? AND version=?
        """,
        (value["graph_id"], int(value["version"])),
    ).fetchone()
    return _row_payload(row) or {}


def register_graph(graph: dict[str, Any], *, actor: str) -> dict[str, Any]:
    value = _validate_graph(graph)
    if value["lifecycle"] not in {"observed", "draft"}:
        raise ValueError("only observed or draft graphs may be registered")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        return _insert_graph(conn, value, actor=actor)


def load_graph(*, graph_id: str, version: int) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (graph_id, int(version)),
        ).fetchone()
    return _row_payload(row)


def list_graph_versions(*, graph_id: str) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? ORDER BY version
            """,
            (graph_id,),
        ).fetchall()
    return [_row_payload(row) or {} for row in rows]


def record_validation(
    *,
    graph_id: str,
    version: int,
    actor: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if load_graph(graph_id=graph_id, version=version) is None:
        raise KeyError("graph version not found")
    if not isinstance(evidence, dict):
        raise ValueError("validation evidence must be an object")
    _assert_no_skill_identity(evidence, location="validation evidence")
    if evidence.get("token_efficiency_passed") is True:
        metrics = evidence.get("token_metrics")
        if not isinstance(metrics, dict):
            raise ValueError(
                "token_efficiency_passed requires token_metrics"
            )
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
        "evidence": deepcopy(evidence),
        "created_at": time.time(),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
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
                orjson.dumps(evidence, option=orjson.OPT_SORT_KEYS).decode(),
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
) -> dict[str, Any]:
    if actor_role not in {"proposer", "reviewer", "audit_presenter"}:
        raise ValueError("invalid Agent execution role")
    execution_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO research_agent_executions (
                execution_id, owner_user_id, actor_role, model_id,
                codex_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id,
                owner_user_id,
                actor_role,
                str(model_id),
                str(codex_version),
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
        _ensure_schema(conn)
        graph_row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (graph_id, int(version)),
        ).fetchone()
        graph = _row_payload(graph_row)
        if graph is None:
            raise KeyError("graph version not found")
        if graph.get("lifecycle") != "draft":
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
        _ensure_schema(conn)
        proposal = conn.execute(
            """
            SELECT * FROM research_graph_proposals WHERE proposal_id=?
            """,
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise KeyError("graph proposal not found")
        _require_agent_execution(
            conn,
            owner_user_id=owner_user_id,
            execution_id=actor_agent_id,
            role="reviewer",
        )
        if str(proposal["owner_user_id"]) != owner_user_id:
            raise ValueError("proposal belongs to a different owner")
        if str(proposal["proposer_execution_id"]) == actor_agent_id:
            raise ValueError("proposal reviewer execution must be independent")
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
    if load_graph(graph_id=graph_id, version=version) is None:
        raise KeyError("graph version not found")
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
        _ensure_schema(conn)
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


def activate_graph(
    *,
    graph_id: str,
    source_version: int,
    actor: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        source_row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (graph_id, int(source_version)),
        ).fetchone()
        source = _row_payload(source_row)
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
        if _latest_audit(
            conn, graph_id=graph_id, version=source_version,
        ) != "approved":
            raise GraphActivationBlocked("latest grill audit is not approved")
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
        stored = _insert_graph(conn, active, actor=actor)
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
            (graph_id, next_version, actor, time.time()),
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
        _ensure_schema(conn)
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
        target_row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=? AND lifecycle='active'
            """,
            (graph_id, int(target_version)),
        ).fetchone()
        target = _row_payload(target_row)
        if target is None:
            raise KeyError("rollback target active version not found")
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
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT v.* FROM active_research_graphs a
            JOIN research_graph_versions v
              ON v.graph_id=a.graph_id AND v.version=a.version
            WHERE a.graph_id=?
            """,
            (graph_id,),
        ).fetchone()
    return _row_payload(row)


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
    semantic_cache_key = str(
        value.get("semantic_cache_key")
        or (value.get("cache") or {}).get("key")
        or ""
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
        """,
        (
            instance_id,
            branch_id,
            node_id,
            orjson.dumps(value, option=orjson.OPT_SORT_KEYS).decode(),
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
        _ensure_schema(conn)
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
        _ensure_schema(conn)
        active = conn.execute(
            """
            SELECT version FROM active_research_graphs WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if active is None or int(active["version"]) != int(graph_version):
            raise ValueError("receipt graph version is not active")
        graph_row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (graph_id, int(graph_version)),
        ).fetchone()
        graph = _row_payload(graph_row) or {}
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
                provider_conformance_hash, resolver_attestation, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
) -> dict[str, Any]:
    receipt_id = str(receipt.get("receipt_id") or "")
    signature = str(receipt.get("resolver_attestation") or "")
    row = conn.execute(
        """
        SELECT * FROM research_capability_receipts
        WHERE receipt_id=? AND owner_user_id=? AND graph_id=?
        AND graph_version=? AND node_id=? AND product_group=?
        """,
        (
            receipt_id,
            owner_user_id,
            graph_id,
            int(graph_version),
            node_id,
            product_group,
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
) -> dict[str, Any]:
    active = load_active_graph(graph_id=graph_id)
    if active is None:
        raise GraphActivationBlocked("active graph not found")
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
        token_budget is not None
        and (
            not isinstance(token_budget, int)
            or isinstance(token_budget, bool)
            or token_budget <= 0
        )
    ):
        raise ValueError("token_budget must be a positive integer")
    instance_id = uuid.uuid4().hex
    branch_id = uuid.uuid4().hex
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        local_resolution = _verify_capability_receipt(
            conn,
            owner_user_id=owner,
            receipt=capability_receipt,
            graph_id=graph_id,
            graph_version=int(active["version"]),
            node_id=entry_node,
            product_group=product_group,
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
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                owner,
                graph_id,
                int(active["version"]),
                product_group,
                workspace_id,
                orjson.dumps(
                    local_resolution,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                token_budget,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                created_at, updated_at
            ) VALUES (?, ?, 'primary', ?, 'running', ?, ?)
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
        branch = _branch_payload(conn.execute(
            "SELECT * FROM research_graph_branches WHERE branch_id=?",
            (branch_id,),
        ).fetchone())
    return {
        "instance_id": instance_id,
        "owner": owner,
        "graph_id": graph_id,
        "graph_version": int(active["version"]),
        "product_group": product_group,
        "workspace_id": workspace_id,
        "capability_resolution": deepcopy(local_resolution),
        "token_budget": token_budget,
        "branches": [branch],
        "created_at": now,
    }


def _load_instance_row(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    owner: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM research_graph_instances
        WHERE instance_id=? AND owner=?
        """,
        (instance_id, owner),
    ).fetchone()


def load_graph_branch(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        if _load_instance_row(
            conn, instance_id=instance_id, owner=owner,
        ) is None:
            return None
        row = conn.execute(
            """
            SELECT * FROM research_graph_branches
            WHERE branch_id=? AND instance_id=?
            """,
            (branch_id, instance_id),
        ).fetchone()
    return _branch_payload(row)


def fork_graph_branch(
    *,
    instance_id: str,
    source_branch_id: str,
    owner: str,
    label: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        if _load_instance_row(
            conn, instance_id=instance_id, owner=owner,
        ) is None:
            raise KeyError("graph instance not found")
        source = conn.execute(
            """
            SELECT * FROM research_graph_branches
            WHERE branch_id=? AND instance_id=?
            """,
            (source_branch_id, instance_id),
        ).fetchone()
        if source is None:
            raise KeyError("source branch not found")
        branch_id = uuid.uuid4().hex
        now = time.time()
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'running', ?, ?)
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
        row = conn.execute(
            "SELECT * FROM research_graph_branches WHERE branch_id=?",
            (branch_id,),
        ).fetchone()
    return _branch_payload(row) or {}


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
        _ensure_schema(conn)
        instance = _load_instance_row(
            conn, instance_id=instance_id, owner=owner,
        )
        if instance is None:
            raise KeyError("graph instance not found")
        branch_row = conn.execute(
            """
            SELECT * FROM research_graph_branches
            WHERE branch_id=? AND instance_id=?
            """,
            (branch_id, instance_id),
        ).fetchone()
        branch = _branch_payload(branch_row)
        if branch is None:
            raise KeyError("graph branch not found")
        graph_row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (instance["graph_id"], int(instance["graph_version"])),
        ).fetchone()
        graph = _row_payload(graph_row) or {}
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
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node=?, status=?, updated_at=?
            WHERE branch_id=? AND instance_id=?
            """,
            (target_id, status, now, branch_id, instance_id),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
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
        row = conn.execute(
            "SELECT * FROM research_graph_branches WHERE branch_id=?",
            (branch_id,),
        ).fetchone()
    return _branch_payload(row) or {}


def build_graph_branch_context(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
) -> dict[str, Any]:
    """Return only the local subgraph and compact evidence needed next."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        instance = _load_instance_row(
            conn, instance_id=instance_id, owner=owner,
        )
        if instance is None:
            raise KeyError("graph instance not found")
        branch_row = conn.execute(
            """
            SELECT * FROM research_graph_branches
            WHERE branch_id=? AND instance_id=?
            """,
            (branch_id, instance_id),
        ).fetchone()
        branch = _branch_payload(branch_row)
        if branch is None:
            raise KeyError("graph branch not found")
        graph_row = conn.execute(
            """
            SELECT * FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (instance["graph_id"], int(instance["graph_version"])),
        ).fetchone()
        graph = _row_payload(graph_row) or {}
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
        trace_rows = conn.execute(
            """
            SELECT evidence_json, telemetry_json
            FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            ORDER BY created_at
            """,
            (instance_id, branch_id),
        ).fetchall()
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "skill_document_tokens": 0,
        "artifact_summary_tokens": 0,
        "reviewer_tokens": 0,
    }
    evidence_refs: list[str] = []
    skill_document_load_count = 0
    skill_context_cache_hits = 0
    for row in trace_rows:
        trace_evidence = _loads(row["evidence_json"]) or {}
        for reference in trace_evidence.get("evidence_refs") or []:
            if isinstance(reference, str) and reference not in evidence_refs:
                evidence_refs.append(reference)
        row_telemetry = _loads(row["telemetry_json"]) or {}
        for field in totals:
            totals[field] += int(row_telemetry.get(field) or 0)
        skill_document_load_count += int(
            row_telemetry.get("skill_document_load_count") or 0
        )
        skill_context_cache_hits += int(
            row_telemetry.get("skill_context_cache_hits") or 0
        )
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["skill_document_load_count"] = skill_document_load_count
    totals["skill_context_cache_hits"] = skill_context_cache_hits
    token_budget = (
        int(instance["token_budget"])
        if instance["token_budget"] is not None
        else None
    )
    budget_exceeded = (
        token_budget is not None
        and totals["total_tokens"] >= token_budget
    )
    totals["budget"] = {
        "limit": token_budget,
        "remaining": (
            max(token_budget - totals["total_tokens"], 0)
            if token_budget is not None
            else None
        ),
        "exceeded": budget_exceeded,
    }
    current_ids = set(node.get("required_capabilities") or [])
    open_gaps = [
        deepcopy(gap)
        for capability_id, gap in gap_by_id.items()
        if capability_id in current_ids or node.get("kind") == "capability_gap"
    ]
    return {
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
        "available_edges": available_edges,
        "required_capabilities": required_capabilities,
        "conditional_capabilities": deepcopy(
            node.get("conditional_capabilities") or []
        ),
        "evidence_refs": evidence_refs,
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
