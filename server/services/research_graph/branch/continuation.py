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
    insert_continuation as _insert_continuation,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.continuation_gate import (
    consume_continuation_gate,
)
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def preview_graph_continuation(
    *,
    source_instance_id: str,
    source_branch_id: str,
    owner: str,
    target_graph_version: int,
    job_id: str,
) -> dict[str, Any]:
    """Return the exact, content-addressed effect an approval Gate must bind."""
    prepared = _prepare(
        source_instance_id=source_instance_id,
        source_branch_id=source_branch_id,
        owner=owner,
        target_graph_version=target_graph_version,
        job_id=job_id,
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
) -> dict[str, Any]:
    """Create one new-version branch; never rewrite or rebind its source."""
    prepared = _prepare(
        source_instance_id=source_instance_id,
        source_branch_id=source_branch_id,
        owner=owner,
        target_graph_version=target_graph_version,
        job_id=job_id,
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
        if branch_identity(source) != prepared["source_identity"]:
            raise ValueError("Graph continuation source identity is stale")
        active = conn.execute(
            """
            SELECT version FROM active_research_graphs WHERE graph_id=?
            """,
            (prepared["graph_id"],),
        ).fetchone()
        if (
            active is None
            or int(active["version"]) != int(target_graph_version)
        ):
            raise ValueError("Graph continuation target is not active")
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
        "instance_id": instance_id,
        "label": f"continuation-v{int(target_graph_version)}",
        "current_node": prepared["target_node"],
        "status": prepared["target_status"],
        "created_at": now,
        "updated_at": now,
    }
    return {
        "instance_id": instance_id,
        "owner": owner,
        "graph_id": prepared["graph_id"],
        "graph_version": int(target_graph_version),
        "product_group": prepared["product_group"],
        "workspace_id": prepared["workspace_id"],
        "mode": "live",
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
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        source = load_instance_branch_with_latest_trace(
            conn,
            instance_id=source_instance_id,
            branch_id=source_branch_id,
            owner=owner,
        )
        if source is None:
            raise KeyError("source graph branch not found")
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
        active = conn.execute(
            "SELECT version FROM active_research_graphs WHERE graph_id=?",
            (str(source["graph_id"]),),
        ).fetchone()
    if source_graph is None or target_graph is None:
        raise KeyError("source or target Graph version not found")
    if (
        active is None
        or int(active["version"]) != int(target_graph_version)
    ):
        raise ValueError("Graph continuation target is not active")
    if int(target_graph.get("parent_version") or 0) != int(
        source["graph_version"]
    ):
        raise ValueError("Graph continuation target is not a direct child")
    target_nodes = {
        str(node.get("node_id") or ""): node
        for node in target_graph.get("nodes") or []
    }
    if (
        str(source["current_node"]) != "capability_gap"
        or str(source["status"]) != "paused"
    ):
        raise ValueError("Graph continuation source must be a paused gap")
    checkpoint = checkpoint_from_branch_row(source)
    if checkpoint is None:
        raise ValueError("Graph continuation requires a Research Cycle")
    source_identity = branch_identity(source)
    if job_id:
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
        evidence_refs = source_refs
        omitted_evidence_count = int(
            source["omitted_evidence_count"] or 0
        )
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
    descriptor = {
        "schema_version": 1,
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
        "target_node": target_node,
        "workspace_id": str(source["workspace_id"]),
    }
    if continuation_mode == JOB_EVIDENCE_MODE:
        assert envelope is not None
        descriptor.update({
            "job_id": job_id,
            "job_evidence_hash": str(envelope["envelope_hash"]),
        })
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
        "target_graph_version": int(target_graph_version),
        "target_graph_hash": str(target_graph["content_hash"]),
        "current_trial_plan_hash": str(
            source["current_trial_plan_hash"]
        ),
        "trial_stage_projection_json": str(
            source["trial_stage_projection_json"]
        ),
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


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
