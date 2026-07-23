"""Immutable cross-version continuation of trusted Job evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch.job_attempt import (
    branch_identity,
    prepare_bound_job_evidence,
)
from server.services.research_graph.branch.continuation_store import (
    JOB_EVIDENCE_MODE,
    JOB_EVIDENCE_TARGET_NODE,
    PRE_TRIAL_CHECKPOINT_MODE,
    PRE_TRIAL_TARGET_NODE,
    SAME_NODE_REENTRY_MODE,
    insert_continuation as _insert_continuation,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.branch.requirement_preflight import (
    assess_requirement_continuation,
)
from server.services.research_graph.branch.entry_resolution import (
    initial_entry_resolution_frame,
)
from server.services.research_graph.continuation_gate import (
    consume_continuation_gate,
)
from server.services.research_graph.packet_budget import graph_packet_budget
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.versions import load_graph_from_conn
from server.services.research_graph.work_packages import require_active
from tools.data.sqlite.db import connect_sqlite


def preview_graph_continuation(
    *,
    source_instance_id: str,
    source_branch_id: str,
    owner: str,
    target_graph_version: int,
    job_id: str,
    execution_mode: str = "live",
) -> dict[str, Any]:
    """Return the exact, content-addressed effect an approval Gate must bind."""
    prepared = _prepare(
        source_instance_id=source_instance_id,
        source_branch_id=source_branch_id,
        owner=owner,
        target_graph_version=target_graph_version,
        job_id=job_id,
        execution_mode=execution_mode,
    )
    return {
        "action": "continue_graph_branch",
        "target_hash": prepared["target_hash"],
        "descriptor": deepcopy(prepared["descriptor"]),
    }


def continue_graph_branch(
    *,
    source_instance_id: str,
    source_branch_id: str,
    owner: str,
    target_graph_version: int,
    job_id: str,
    expected_target_hash: str,
    human_authorization_id: str,
    execution_mode: str = "live",
) -> dict[str, Any]:
    """Create one immutable version instance inside the same Work Package."""
    prepared = _prepare(
        source_instance_id=source_instance_id,
        source_branch_id=source_branch_id,
        owner=owner,
        target_graph_version=target_graph_version,
        job_id=job_id,
        execution_mode=execution_mode,
    )
    if expected_target_hash != prepared["target_hash"]:
        raise ValueError("Graph continuation target hash is stale")
    instance_id = uuid.uuid4().hex
    branch_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    effect_ref = (
        f"graph-continuation:{instance_id}:{branch_id}:"
        f"{prepared['target_hash']}"
    )
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = load_instance_branch_with_latest_trace(
            conn,
            instance_id=source_instance_id,
            branch_id=source_branch_id,
            owner=owner,
        )
        if source is None:
            raise KeyError("source graph branch not found")
        require_active(source)
        if not bool(source["is_current_incarnation"]):
            raise ValueError(
                "Graph continuation source is not the current incarnation"
            )
        if branch_identity(source) != prepared["source_identity"]:
            raise ValueError("Graph continuation source identity is stale")
        _require_execution_target(
            conn,
            graph_id=prepared["graph_id"],
            target_graph_version=target_graph_version,
            execution_mode=execution_mode,
        )
        consume_continuation_gate(
            conn,
            owner_user_id=owner,
            case_id=human_authorization_id,
            target_hash=prepared["target_hash"],
            effect_ref=effect_ref,
        )
        _insert_continuation(
            conn,
            prepared=prepared,
            owner=owner,
            instance_id=instance_id,
            branch_id=branch_id,
            trace_id=trace_id,
            authorization_id=human_authorization_id,
            now=now,
        )
    branch = {
        "branch_id": branch_id,
        "hypothesis_branch_id": prepared["hypothesis_branch_id"],
        "is_current_incarnation": True,
        "instance_id": instance_id,
        "label": f"continuation-v{int(target_graph_version)}",
        "current_node": prepared["target_node"],
        "status": prepared["target_status"],
        "created_at": now,
        "updated_at": now,
    }
    return {
        "instance_id": instance_id,
        "work_package_id": prepared["work_package_id"],
        "owner": owner,
        "graph_id": prepared["graph_id"],
        "graph_version": int(target_graph_version),
        "product_group": prepared["product_group"],
        "workspace_id": prepared["workspace_id"],
        "mode": execution_mode,
        "shadow_run_id": "",
        "branches": [branch],
        "created_at": now,
    }


def _prepare(
    *,
    source_instance_id: str,
    source_branch_id: str,
    owner: str,
    target_graph_version: int,
    job_id: str,
    execution_mode: str,
) -> dict[str, Any]:
    execution_mode = _normalize_execution_mode(execution_mode)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        source = load_instance_branch_with_latest_trace(
            conn,
            instance_id=source_instance_id,
            branch_id=source_branch_id,
            owner=owner,
        )
        if source is None:
            raise KeyError("source graph branch not found")
        require_active(source)
        if not bool(source["is_current_incarnation"]):
            raise ValueError(
                "Graph continuation source is not the current incarnation"
            )
        source_graph = load_graph_from_conn(
            conn,
            graph_id=str(source["graph_id"]),
            version=int(source["graph_version"]),
        )
        target_graph = load_graph_from_conn(
            conn,
            graph_id=str(source["graph_id"]),
            version=int(target_graph_version),
        )
        _require_execution_target(
            conn,
            graph_id=str(source["graph_id"]),
            target_graph_version=target_graph_version,
            execution_mode=execution_mode,
        )
    if source_graph is None or target_graph is None:
        raise KeyError("source or target Graph version not found")
    if int(target_graph.get("parent_version") or 0) != int(
        source["graph_version"]
    ):
        raise ValueError("Graph continuation target is not a direct child")
    target_nodes = {
        str(node.get("node_id") or ""): node
        for node in target_graph.get("nodes") or []
    }
    checkpoint = checkpoint_from_branch_row(source)
    if checkpoint is None:
        raise ValueError("Graph continuation requires a Research Cycle")
    source_identity = branch_identity(source)
    if int(target_graph.get("schema_version") or 1) >= 2:
        if job_id:
            raise ValueError(
                "same-node Graph continuation does not rebind Job evidence"
            )
        continuation_mode = SAME_NODE_REENTRY_MODE
        target_node = str(source["current_node"])
        target_status = str(source["status"])
        envelope = None
        evidence_refs, omitted_evidence_count = _source_evidence_refs(source)
    elif (
        str(source["current_node"]) != "capability_gap"
        or str(source["status"]) != "paused"
    ):
        raise ValueError("Graph continuation source must be a paused gap")
    elif job_id:
        continuation_mode = JOB_EVIDENCE_MODE
        target_node = JOB_EVIDENCE_TARGET_NODE
        target_status = "running"
        job = prepare_bound_job_evidence(
            job_id=job_id,
            owner=owner,
            checkpoint=checkpoint,
            expected=source_identity,
        )
        envelope: dict[str, Any] | None = _continuation_envelope(
            job["envelope"]
        )
        evidence_refs = ["evidence:" + envelope["envelope_hash"]]
        omitted_evidence_count = 0
    else:
        continuation_mode = PRE_TRIAL_CHECKPOINT_MODE
        target_node = PRE_TRIAL_TARGET_NODE
        target_status = "paused"
        if (
            str(checkpoint.get("trial_plan_hash") or "")
            or str(source["current_trial_plan_hash"] or "")
        ):
            raise ValueError(
                "pre-trial Graph continuation requires an empty TrialPlan"
            )
        envelope = None
        evidence_refs, omitted_evidence_count = _source_evidence_refs(source)
    target = target_nodes.get(target_node)
    if target is None:
        raise ValueError(f"target Graph lacks {target_node} node")
    if (
        continuation_mode == JOB_EVIDENCE_MODE
        and target.get("required_capabilities")
    ):
        raise ValueError(
            f"target Graph lacks capability-free {target_node} node"
        )
    budget_profile = graph_packet_budget(target_graph)
    descriptor = {
        "schema_version": 2,
        "continuation_mode": continuation_mode,
        "owner": owner,
        "graph_id": str(source["graph_id"]),
        "source_graph_version": int(source["graph_version"]),
        "source_graph_hash": str(source_graph["content_hash"]),
        "source_instance_id": source_instance_id,
        "source_branch_id": source_branch_id,
        "source_trace_id": str(source["latest_trace_id"]),
        "source_checkpoint_hash": str(checkpoint["projection_hash"]),
        "target_graph_version": int(target_graph_version),
        "target_graph_hash": str(target_graph["content_hash"]),
        "target_graph_lifecycle": str(target_graph["lifecycle"]),
        "execution_mode": execution_mode,
        "budget_profile_ref": str(
            budget_profile.get("profile_ref")
            or budget_profile.get("policy_ref")
            or ""
        ),
        "budget_profile_hash": str(
            budget_profile.get("profile_hash") or ""
        ),
        "target_node": target_node,
        "workspace_id": str(source["workspace_id"]),
        "work_package_id": str(
            source["work_package_id"] or source_instance_id
        ),
        "hypothesis_branch_id": str(
            source["hypothesis_branch_id"] or source_branch_id
        ),
        "created_by_profile_ref": str(
            source["created_by_profile_ref"] or ""
        ),
        "current_owner_profile_ref": str(
            source["current_owner_profile_ref"] or ""
        ),
    }
    if continuation_mode == JOB_EVIDENCE_MODE:
        assert envelope is not None
        descriptor.update({
            "job_id": job_id,
            "job_evidence_hash": str(envelope["envelope_hash"]),
        })
    elif continuation_mode == SAME_NODE_REENTRY_MODE:
        descriptor["requirement_preflight"] = (
            assess_requirement_continuation(
                source_graph=source_graph,
                target_graph=target_graph,
                target_node=target_node,
            )
        )
    return {
        "target_hash": _hash(descriptor),
        "descriptor": descriptor,
        "source_identity": source_identity,
        "checkpoint": checkpoint,
        "envelope": envelope,
        "continuation_mode": continuation_mode,
        "target_node": target_node,
        "target_status": target_status,
        "evidence_refs": evidence_refs,
        "omitted_evidence_count": omitted_evidence_count,
        "graph_id": str(source["graph_id"]),
        "product_group": str(source["product_group"]),
        "workspace_id": str(source["workspace_id"]),
        "work_package_id": str(
            source["work_package_id"] or source_instance_id
        ),
        "hypothesis_branch_id": str(
            source["hypothesis_branch_id"] or source_branch_id
        ),
        "created_by_profile_ref": str(
            source["created_by_profile_ref"] or ""
        ),
        "current_owner_profile_ref": str(
            source["current_owner_profile_ref"] or ""
        ),
        "target_graph_version": int(target_graph_version),
        "target_graph_hash": str(target_graph["content_hash"]),
        "execution_mode": execution_mode,
        "current_trial_plan_hash": str(
            source["current_trial_plan_hash"]
        ),
        "trial_stage_projection_json": str(
            source["trial_stage_projection_json"]
        ),
        "entry_resolution_frame_json": orjson.dumps(
            initial_entry_resolution_frame(
                descriptor,
                inherited_frame=(
                    orjson.loads(source["entry_resolution_frame_json"])
                    if source["entry_resolution_frame_json"]
                    else {}
                ),
            )
        ).decode(),
    }


def _continuation_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(envelope)
    value.pop("envelope_hash", None)
    value["limitations"] = [
        *(value.get("limitations") or []),
        (
            "Evidence was projected through an authorized Graph continuation; "
            "the source Job remains bound to its immutable source branch."
        ),
    ]
    return validate_agent_evidence_envelope(value)


def _source_evidence_refs(source: Any) -> tuple[list[str], int]:
    try:
        source_refs = orjson.loads(
            str(source["evidence_refs_json"] or "[]")
        )
    except orjson.JSONDecodeError as exc:
        raise ValueError("source evidence refs are invalid") from exc
    if not isinstance(source_refs, list) or not all(
        isinstance(reference, str) for reference in source_refs
    ):
        raise ValueError("source evidence refs are invalid")
    return source_refs, int(source["omitted_evidence_count"] or 0)


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _normalize_execution_mode(value: str) -> str:
    mode = str(value or "live").strip().lower()
    if mode not in {"live", "shadow"}:
        raise ValueError("Graph continuation mode must be live or shadow")
    return mode


def _require_execution_target(
    conn: Any,
    *,
    graph_id: str,
    target_graph_version: int,
    execution_mode: str,
) -> None:
    mode = _normalize_execution_mode(execution_mode)
    if mode == "shadow":
        return
    active = conn.execute(
        "SELECT version FROM active_research_graphs WHERE graph_id=?",
        (graph_id,),
    ).fetchone()
    if (
        active is None
        or int(active["version"]) != int(target_graph_version)
    ):
        raise ValueError("Graph continuation target is not active")
