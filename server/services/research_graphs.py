"""Immutable research decision graphs and gated Active Graph pointers."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services import agent_flow, graph_governance
from server.services.research_graph.branch.context import (
    build_graph_branch_context,
    build_graph_branch_next,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_row as _load_instance_branch_row,
    store_current_branch_resolution as _store_current_branch_resolution,
)
from server.services.research_graph.branch.runtime import (
    create_graph_instance,
    fork_graph_branch,
    load_graph_branch,
)
from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
    has_batch4_legacy_schema,
)
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.capability_resolution import (
    issue_capability_receipt,
    record_capability_approval,
)
from server.services.research_graph.protocol import (
    GraphActivationBlocked,
    GraphVersionConflict,
    assert_no_skill_identity as _assert_no_skill_identity,
    graph_content_hash as _content_hash,
    json_hash as _json_hash,
)
from server.services.research_graph.versions import (
    clear_graph_cache_for_current_db as _clear_graph_cache_for_current_db,
    graph_lifecycle as _graph_lifecycle,
    insert_graph as _insert_graph,
    list_graph_versions,
    load_active_graph,
    load_graph,
    load_graph_from_conn as _load_graph_from_conn,
    register_graph,
)
from server.services.maintenance_cases.schema import (
    create_schema as create_maintenance_schema,
)
from tools.data.sqlite.db import connect_sqlite


_VALIDATION_GATES = (
    "replay_passed",
    "shadow_passed",
    "capability_resolution_complete",
    "unaffected_jobs_preserved",
    "token_efficiency_passed",
)


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
        """
    )
    create_instance_branch_schema(conn)
    create_maintenance_schema(conn)


def ensure_schema() -> None:
    _clear_graph_cache_for_current_db()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        legacy_assurance = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table'
              AND name='research_backend_assurance_receipts'
            """
        ).fetchone()
        legacy_accounting = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN (
                'research_agent_executions',
                'research_token_budgets',
                'research_token_reservations',
                'research_provider_usage_receipts'
            )
            """
        ).fetchall()
        legacy_governance = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN (
                'research_graph_validations',
                'research_graph_proposals',
                'research_graph_reviews',
                'research_graph_audits',
                'human_activation_authorizations',
                'research_capability_approvals',
                'research_graph_server_secrets'
            )
            """
        ).fetchall()
        legacy_branch_projection = has_batch4_legacy_schema(conn)
    if legacy_assurance is not None:
        raise RuntimeError(
            "legacy backend assurance receipts require the explicit "
            "migrate_backend_assurance cutover"
        )
    if legacy_accounting:
        raise RuntimeError(
            "legacy Graph accounting requires the offline Agent Flow "
            "migration with an explicit Agent identity mapping"
        )
    if legacy_governance:
        raise RuntimeError(
            "legacy Graph governance requires the explicit "
            "migrate_graph_governance cutover"
        )
    if legacy_branch_projection:
        raise RuntimeError(
            "legacy Graph branch projections require the explicit "
            "migrate_graph_branch_projection cutover"
        )
    agent_flow.get_store().ensure_schema()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)


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
    flow_store = agent_flow.get_store()
    graph_period = flow_store.load_current_budget_period(
        owner_user_id=owner,
        agent_id=graph_scope_id,
    )
    baseline_period = flow_store.load_current_budget_period(
        owner_user_id=owner,
        agent_id=baseline_scope_id,
    )
    if graph_period is None or baseline_period is None:
        raise ValueError("graph and baseline Agent budget periods are required")
    budgets = {
        graph_scope_id: int(graph_period["used_tokens"]),
        baseline_scope_id: int(baseline_period["used_tokens"]),
    }
    subagent_count = flow_store.count_subagent_invocations(
        owner_user_id=owner,
        agent_id=graph_scope_id,
    )
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
        "token_authority": "normalized_agent_invocations",
    }


def record_validation(
    *,
    graph_id: str,
    version: int,
    actor: str,
    proposal_id: str,
    evidence: dict[str, Any],
    owner_user_id: str = "",
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
    validation_id = _json_hash(evidence_value)
    row = {
        "validation_id": validation_id,
        "graph_id": graph_id,
        "version": int(version),
        "actor": actor,
        "evidence": deepcopy(evidence_value),
        "created_at": time.time(),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
        if graph is None:
            raise KeyError("graph version not found")
    owner = owner_user_id or actor
    case = graph_governance.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
    )
    graph_governance.require_graph_target(
        case,
        graph_id=graph_id,
        graph_version=version,
        graph_hash=str(graph["content_hash"]),
    )
    failed = [
        gate for gate in _VALIDATION_GATES
        if evidence_value.get(gate) is not True
    ]
    if not failed and (
        evidence_value.get("token_metrics_authority") == "server_derived"
    ):
        graph_governance.record_activation_validation(
            Settings.CACHE_DB_PATH,
            owner_user_id=owner,
            case_id=proposal_id,
            validation_summary_hash=validation_id,
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
    raise RuntimeError(
        "deprecated Agent accounting protocol; reserve one complete "
        "AgentInvocation through /api/agent-flow/invocations"
    )


def create_token_budget(
    *,
    owner_user_id: str,
    scope_id: str,
    token_limit: int,
) -> dict[str, Any]:
    raise RuntimeError(
        "deprecated Graph token budget; configure the Agent Profile budget"
    )


def reserve_tokens(
    *,
    owner_user_id: str,
    scope_id: str,
    work_kind: str,
    max_input_tokens: int,
    max_output_tokens: int,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    raise RuntimeError(
        "deprecated split reservation protocol; reserve one complete "
        "AgentInvocation"
    )


def ingest_provider_usage_receipt(
    *,
    reservation_id: str,
    provider: str,
    provider_request_id: str,
    input_tokens: int,
    output_tokens: int,
    usage_attestation: str,
) -> dict[str, Any]:
    raise RuntimeError(
        "deprecated provider receipt protocol; settle the AgentInvocation"
    )


def commit_token_reservation(
    *,
    owner_user_id: str,
    reservation_id: str,
    provider_receipt_id: str,
) -> dict[str, Any]:
    raise RuntimeError(
        "deprecated token commit protocol; settle the AgentInvocation"
    )


def release_token_reservation(
    *,
    owner_user_id: str,
    reservation_id: str,
) -> dict[str, Any]:
    raise RuntimeError(
        "deprecated token reservation; release the AgentInvocation"
    )


def load_token_budget(
    *,
    owner_user_id: str,
    scope_id: str,
) -> dict[str, Any] | None:
    raise RuntimeError(
        "deprecated Graph token budget; load the Agent Profile budget"
    )


def _require_agent_execution(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    execution_id: str,
    role: str,
) -> dict[str, Any]:
    del conn
    try:
        row = agent_flow.get_store().load_invocation(
            owner_user_id=owner_user_id,
            invocation_id=execution_id,
        )
    except KeyError as exc:
        raise ValueError(
            f"valid {role} Agent invocation is required"
        ) from exc
    if (
        str(row["actor_role"]) != role
        or str(row["status"]) != "settled"
    ):
        raise ValueError(f"valid {role} Agent invocation is required")
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
    conversation_ref: str,
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
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
        if graph is None:
            raise KeyError("graph version not found")
        if graph["lifecycle"] != "draft":
            raise ValueError("only a draft graph accepts proposals")
        _require_agent_execution(
            conn,
            owner_user_id=owner_user_id,
            execution_id=actor_agent_id,
            role="proposer",
        )
    diff_hash = _json_hash(change_diff)
    row = graph_governance.open_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=int(version),
        graph_hash=str(graph["content_hash"]),
        diff_hash=diff_hash,
        proposer_invocation_id=actor_agent_id,
        conversation_ref=conversation_ref,
        proposal_evidence_refs=evidence_refs,
    )
    row.update({
        "graph_id": graph_id,
        "version": int(version),
        "proposer_execution_id": actor_agent_id,
        "risk_level": risk_level,
        "change_diff": deepcopy(change_diff),
        "evidence_refs": list(evidence_refs),
        "token_estimate": token_estimate,
    })
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
    case = graph_governance.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
    )
    proposer_execution_id = graph_governance.proposer_invocation_id(case)
    reviewer_execution = _require_agent_execution(
        None,
        owner_user_id=owner_user_id,
        execution_id=actor_agent_id,
        role="reviewer",
    )
    if proposer_execution_id == actor_agent_id:
        raise ValueError("proposal reviewer execution must be independent")
    proposer_execution = _require_agent_execution(
        None,
        owner_user_id=owner_user_id,
        execution_id=proposer_execution_id,
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
    existing_review_ids = graph_governance.reviewer_invocation_ids(case)
    existing_review_principals = (
        agent_flow.get_store().load_invocations(
            owner_user_id=owner_user_id,
            invocation_ids=existing_review_ids,
        ).values()
    )
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
    effective_disposition = (
        "disagreed"
        if scope_drift or semantic_uncertainty
        else disposition
    )
    review = graph_governance.record_activation_review(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
        reviewer_invocation_id=actor_agent_id,
        disposition=effective_disposition,
        evidence_refs=evidence_refs,
    )
    now = float(review["updated_at"])
    review_id = _json_hash({
        "proposal_id": proposal_id,
        "reviewer_execution_id": actor_agent_id,
    })
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


def record_audit(
    *,
    graph_id: str,
    version: int,
    actor: str,
    proposal_id: str,
    disposition: str,
    grill_evidence: list[dict[str, Any]],
    grill_ref: str,
    owner_user_id: str = "",
) -> dict[str, Any]:
    if disposition not in {"approved", "rejected", "quarantined", "frozen"}:
        raise ValueError("invalid audit disposition")
    if not isinstance(grill_evidence, list) or not grill_evidence:
        raise ValueError("grill_evidence must be a non-empty array")
    _assert_no_skill_identity(grill_evidence, location="grill evidence")
    audit_id = _json_hash({
        "graph_id": graph_id,
        "version": int(version),
        "disposition": disposition,
        "grill_ref": grill_ref,
        "grill_evidence_hash": _json_hash(grill_evidence),
    })
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
        graph = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
        if graph is None:
            raise KeyError("graph version not found")
    owner = owner_user_id or actor
    case = graph_governance.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
    )
    graph_governance.require_graph_target(
        case,
        graph_id=graph_id,
        graph_version=version,
        graph_hash=str(graph["content_hash"]),
    )
    graph_governance.record_activation_grill(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
        disposition=disposition,
        grill_ref=grill_ref,
    )
    return row


def authorize_graph_activation(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    proposal_id: str,
    graph_hash: str,
    diff_hash: str,
    conversation_ref: str,
    approval_ref: str,
) -> dict[str, Any]:
    """Bind an authenticated conversation decision to one exact Gate."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = _load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(graph_version),
        )
        if graph is None or graph.get("lifecycle") != "draft":
            raise ValueError("human activation requires a draft graph")
        actual_graph_hash = str(graph["content_hash"])
        if graph_hash != actual_graph_hash:
            raise ValueError("human activation target hash mismatch")
    case = graph_governance.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
    )
    graph_governance.require_graph_target(
        case,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=actual_graph_hash,
    )
    target_hash = graph_governance.activation_target_hash(
        owner_user_id=owner_user_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_hash=actual_graph_hash,
        diff_hash=diff_hash,
    )
    return graph_governance.approve_activation(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
        target_hash=target_hash,
        conversation_ref=conversation_ref,
        approval_ref=approval_ref,
    )


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
        next_version = int(conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM research_graph_versions WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()["next_version"])
        try:
            graph_governance.consume_activation_in_connection(
                conn,
                owner_user_id=actor,
                case_id=human_authorization_id,
                graph_id=graph_id,
                graph_version=source_version,
                graph_hash=str(source["content_hash"]),
                effect_ref=f"active-graph:{graph_id}@{next_version}",
            )
        except KeyError as exc:
            raise GraphActivationBlocked(
                "human activation authorization Gate not found"
            ) from exc
        except ValueError as exc:
            raise GraphActivationBlocked(str(exc)) from exc
        human_actor = actor
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
