"""Cold-path server evidence for the authoritative backtest transition."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import settings as Settings
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.research_cycle.job_evidence import (
    project_job_attempt_evidence,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


SERVER_ACTION = "bind_job_attempt"
REQUEST_FIELD = "job_attempt_request"
_SERVER_GUARDS = (
    "terminal_job_evidence_retained",
    "terminal_job_trusted",
    "net_return_series_available",
)


def prepare_transition(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    request: Any,
) -> dict[str, Any] | None:
    if request is None:
        return None
    job_id = _request_job_id(request)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if row is None:
            raise KeyError("graph branch not found")
        graph = load_graph_from_conn(
            conn,
            graph_id=str(row["graph_id"]),
            version=int(row["graph_version"]),
        ) or {}
        edge = _edge(graph, edge_id)
        _validate_edge(row=row, edge=edge)
        checkpoint = checkpoint_from_branch_row(row)
        if checkpoint is None:
            raise ValueError(
                "JobAttempt evidence requires a Research Cycle checkpoint"
            )
        expected = branch_identity(row)
    return prepare_bound_job_evidence(
        job_id=job_id,
        owner=owner,
        checkpoint=checkpoint,
        expected=expected,
    )


def prepare_bound_job_evidence(
    *,
    job_id: str,
    owner: str,
    checkpoint: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Project one source-bound Job without changing its Graph identity."""
    detail = JobRepository(Settings.CACHE_DB_PATH).load_detail(
        job_id,
        owner=owner,
    )
    if detail is None:
        raise KeyError("research job not found")
    _validate_binding(
        detail=detail,
        checkpoint=checkpoint,
        expected=expected,
    )
    envelope = project_job_attempt_evidence(
        detail["job"],
        identity_refs=detail["identity_refs"],
        trial_stage=str(detail["trial_binding"]["trial_stage"]),
        active_artifacts=detail["active_artifacts"],
    )
    if envelope is None:
        raise ValueError(
            "JobAttempt lacks terminal server assurance or immutable identity"
        )
    facts = envelope["facts"]
    assurance = facts["assurance"]
    trusted = (
        detail["job"].status is JobStatus.SUCCEEDED
        and assurance["disposition"] == "trusted"
        and not assurance["anomaly_codes"]
    )
    return {
        "expected": expected,
        "guard_facts": {
            "terminal_job_evidence_retained": True,
            "terminal_job_trusted": trusted,
            "net_return_series_available": bool(
                facts["net_return_series_available"]
            ),
        },
        "envelope": envelope,
        "evidence_ref": "evidence:" + envelope["envelope_hash"],
    }


def bind_server_evidence(
    evidence: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> dict[str, Any]:
    value = deepcopy(evidence)
    value.pop(REQUEST_FIELD, None)
    for field in _SERVER_GUARDS:
        value.pop(field, None)
    if prepared is None:
        return value
    value["server_evidence"] = {
        "job_attempt": deepcopy(prepared["envelope"]),
    }
    refs = value.get("evidence_refs", [])
    if not isinstance(refs, list) or not all(
        isinstance(item, str) and item for item in refs
    ):
        raise ValueError("evidence_refs must be a reference array")
    value["evidence_refs"] = list(dict.fromkeys([
        *refs,
        prepared["evidence_ref"],
    ]))
    return value


def validate_preflight(
    *,
    row: Any,
    edge: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> None:
    if edge.get("server_action") == SERVER_ACTION and prepared is None:
        raise ValueError(
            "backtest transition requires job_attempt_request"
        )
    if prepared is None:
        return
    _validate_edge(row=row, edge=edge)
    if branch_identity(row) != prepared["expected"]:
        raise ValueError(
            "JobAttempt preflight is stale; inspect the current branch again"
        )


def _validate_binding(
    *,
    detail: dict[str, Any],
    checkpoint: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    job = detail["job"]
    binding = detail["trial_binding"]
    graph_binding = detail["graph_binding"]
    identity = detail["identity_refs"]
    if binding is None or graph_binding is None or identity is None:
        raise ValueError("JobAttempt lacks immutable TrialPlan identity")
    if job.workspace_id != expected["workspace_id"]:
        raise ValueError("JobAttempt workspace does not match Graph branch")
    if (
        graph_binding["instance_id"] != expected["instance_id"]
        or graph_binding["branch_id"] != expected["branch_id"]
    ):
        raise ValueError("JobAttempt does not belong to this Graph branch")
    required = {
        "contract_hash": checkpoint["contract_hash"],
        "methodology_hash": checkpoint["methodology_hash"],
        "trial_plan_hash": checkpoint["trial_plan_hash"],
    }
    if any(identity.get(key) != value for key, value in required.items()):
        raise ValueError(
            "JobAttempt Contract, Methodology, or TrialPlan is stale"
        )
    if identity["trial_plan_hash"] != expected["trial_plan_hash"]:
        raise ValueError("JobAttempt does not match the active TrialPlan")


def _request_job_id(value: Any) -> str:
    if not isinstance(value, dict) or set(value) != {"job_id"}:
        raise ValueError("job_attempt_request requires only job_id")
    job_id = value.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job_attempt_request.job_id must be non-empty")
    return job_id.strip()


def branch_identity(row: Any) -> dict[str, Any]:
    return {
        "instance_id": str(row["instance_id"]),
        "branch_id": str(row["branch_id"]),
        "current_node": str(row["current_node"]),
        "latest_trace_id": str(row["latest_trace_id"]),
        "graph_id": str(row["graph_id"]),
        "graph_version": int(row["graph_version"]),
        "workspace_id": str(row["workspace_id"]),
        "trial_plan_hash": str(row["current_trial_plan_hash"]),
    }


def _validate_edge(*, row: Any, edge: dict[str, Any]) -> None:
    if edge.get("server_action") != SERVER_ACTION:
        raise ValueError("job_attempt_request is not allowed on this edge")
    if str(edge.get("from_node") or "") != str(row["current_node"]):
        raise ValueError("JobAttempt edge does not leave current node")


def _edge(graph: dict[str, Any], edge_id: str) -> dict[str, Any]:
    edge = next(
        (
            item for item in graph.get("edges") or []
            if str(item.get("edge_id") or "") == edge_id
        ),
        None,
    )
    if edge is None:
        raise KeyError("graph edge not found")
    return edge
