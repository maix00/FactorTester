"""Server-owned replay, shadow comparison, and token activation evidence."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.branch.context import (
    build_graph_branch_context,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_row,
)
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.shadow_tokens import (
    derive_token_metrics,
    token_failures,
)
from server.services.research_graph.versions import load_graph
from tools.data.sqlite.db import connect_sqlite


_MAX_COMPARISON_ROWS = 1000


def derive_activation_evidence(
    *,
    graph_id: str,
    version: int,
    routine_instance_id: str,
    routine_branch_id: str,
    baseline_run_id: str,
) -> dict[str, Any]:
    if not all((
        routine_instance_id,
        routine_branch_id,
        baseline_run_id,
    )):
        raise ValueError("complete shadow comparison references are required")
    graph, owner, runtime, graph_run_id, runs = _load_comparison_scope(
        graph_id=graph_id,
        version=version,
        instance_id=routine_instance_id,
        branch_id=routine_branch_id,
        baseline_run_id=baseline_run_id,
    )
    replay = _replay_persisted_trace(
        graph=graph,
        owner=owner,
        runtime=runtime,
    )
    outcomes = _compare_run_outcomes(
        owner=owner,
        graph_run_id=graph_run_id,
        baseline_run_id=baseline_run_id,
    )
    context = build_graph_branch_context(
        instance_id=routine_instance_id,
        branch_id=routine_branch_id,
        owner=owner,
    )
    token_metrics = derive_token_metrics(
        owner=owner,
        instance_id=routine_instance_id,
        graph_run_id=graph_run_id,
        baseline_run_id=baseline_run_id,
        run_spec_hash=str(runs[graph_run_id]["run_spec_hash"]),
        graph=graph,
        context=context,
    )
    token_failure_codes = token_failures(token_metrics)
    capability_complete = not (context.get("open_gaps") or [])
    return {
        "replay_passed": bool(replay["passed"]),
        "shadow_passed": bool(outcomes["equivalent"]),
        "capability_resolution_complete": capability_complete,
        "unaffected_jobs_preserved": bool(outcomes["isolated"]),
        "token_efficiency_passed": not token_failure_codes,
        "replay_summary": replay,
        "shadow_summary": outcomes,
        "token_metrics": token_metrics,
        "token_failures": token_failure_codes,
        "token_metrics_authority": "server_derived",
        "evidence_authority": "server_derived",
    }


def _load_comparison_scope(
    *,
    graph_id: str,
    version: int,
    instance_id: str,
    branch_id: str,
    baseline_run_id: str,
) -> tuple[dict[str, Any], str, sqlite3.Row, str, dict[str, sqlite3.Row]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        owner_row = conn.execute(
            "SELECT owner FROM research_graph_instances WHERE instance_id=?",
            (instance_id,),
        ).fetchone()
        if owner_row is None:
            raise ValueError("shadow graph instance or branch not found")
        owner = str(owner_row["owner"])
        runtime = load_instance_branch_row(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
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
                "comparison instance is not this draft shadow Graph"
            )
        graph_run_id = str(runtime["shadow_run_id"])
        if not graph_run_id or graph_run_id == baseline_run_id:
            raise ValueError("shadow Graph and baseline require distinct run IDs")
        rows = conn.execute(
            """
            SELECT run_id, run_spec_hash, workspace_id
            FROM research_runs
            WHERE owner=? AND run_id IN (?, ?) AND kind='factor_research'
            """,
            (owner, graph_run_id, baseline_run_id),
        ).fetchall()
    runs = {str(row["run_id"]): row for row in rows}
    if set(runs) != {graph_run_id, baseline_run_id}:
        raise ValueError("owned Graph and baseline research runs are required")
    if (
        str(runs[graph_run_id]["run_spec_hash"])
        != str(runs[baseline_run_id]["run_spec_hash"])
    ):
        raise ValueError("Graph and baseline runs must share one RunSpec hash")
    graph = load_graph(graph_id=graph_id, version=version)
    if graph is None or graph.get("lifecycle") != "draft":
        raise ValueError("shadow comparison requires an immutable draft Graph")
    return graph, owner, runtime, graph_run_id, runs


def _replay_persisted_trace(
    *,
    graph: dict[str, Any],
    owner: str,
    runtime: sqlite3.Row,
) -> dict[str, Any]:
    instance_id = str(runtime["instance_id"])
    branch_id = str(runtime["branch_id"])
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT trace_id, edge_id, from_node, to_node, evidence_json
            FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            ORDER BY created_at, trace_id
            LIMIT ?
            """,
            (instance_id, branch_id, _MAX_COMPARISON_ROWS + 1),
        ).fetchall()
    if len(rows) > _MAX_COMPARISON_ROWS:
        raise ValueError("shadow replay trace exceeds bounded comparison rows")
    edges = {
        str(edge["edge_id"]): edge for edge in graph.get("edges") or []
    }
    current = str(
        graph.get("entry_node")
        or ((graph.get("nodes") or [{}])[0].get("node_id") or "")
    )
    if not current:
        raise ValueError("shadow Graph entry node is invalid")
    evidence_count = 0
    path: list[str] = []
    for row in rows:
        edge = edges.get(str(row["edge_id"]))
        if (
            edge is None
            or str(row["from_node"]) != current
            or str(edge["from_node"]) not in {current, "*"}
            or str(row["to_node"]) != str(edge["to_node"])
        ):
            return _replay_summary(
                passed=False,
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
            )
        evidence = orjson.loads(row["evidence_json"])
        if not isinstance(evidence, dict):
            return _replay_summary(
                passed=False,
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
            )
        evidence_count += len(evidence.get("evidence_refs") or [])
        path.append(str(row["edge_id"]))
        current = str(row["to_node"])
    latest_matches = (
        (not rows and not str(runtime["latest_trace_id"]))
        or (
            bool(rows)
            and str(rows[-1]["trace_id"]) == str(runtime["latest_trace_id"])
        )
    )
    return _replay_summary(
        passed=current == str(runtime["current_node"]) and latest_matches,
        current=current,
        expected=str(runtime["current_node"]),
        path=path,
        evidence_count=evidence_count,
    )


def _replay_summary(
    *,
    passed: bool,
    current: str,
    expected: str,
    path: list[str],
    evidence_count: int,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "transition_count": len(path),
        "path_hash": json_hash(path),
        "evidence_ref_count": evidence_count,
        "derived_node": current,
        "projected_node": expected,
    }


def _compare_run_outcomes(
    *,
    owner: str,
    graph_run_id: str,
    baseline_run_id: str,
) -> dict[str, Any]:
    graph = _run_snapshot(owner=owner, run_id=graph_run_id)
    baseline = _run_snapshot(owner=owner, run_id=baseline_run_id)
    return {
        "equivalent": graph["fingerprint"] == baseline["fingerprint"],
        "isolated": not set(graph["job_ids"]).intersection(
            baseline["job_ids"]
        ),
        "graph_job_count": graph["job_count"],
        "baseline_job_count": baseline["job_count"],
        "graph_artifact_count": graph["artifact_count"],
        "baseline_artifact_count": baseline["artifact_count"],
        "graph_outcome_hash": graph["fingerprint"],
        "baseline_outcome_hash": baseline["fingerprint"],
    }


def _run_snapshot(*, owner: str, run_id: str) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        jobs = conn.execute(
            """
            SELECT job_id, kind, status, run_spec_hash, source_revision,
                   runner_path, execution_plan_hash, result_summary_json,
                   error_json, terminal_assurance_json
            FROM research_jobs
            WHERE owner=? AND run_id=?
            ORDER BY created_at, job_id
            LIMIT ?
            """,
            (owner, run_id, _MAX_COMPARISON_ROWS + 1),
        ).fetchall()
        if len(jobs) > _MAX_COMPARISON_ROWS:
            raise ValueError("shadow run exceeds bounded Job comparison rows")
        job_ids = [str(row["job_id"]) for row in jobs]
        artifacts: list[sqlite3.Row] = []
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            artifacts = conn.execute(
                f"""
                SELECT job_id, name, state, content_hash
                FROM research_job_artifacts
                WHERE job_id IN ({placeholders})
                ORDER BY job_id, name
                LIMIT ?
                """,
                (*job_ids, _MAX_COMPARISON_ROWS + 1),
            ).fetchall()
    if len(artifacts) > _MAX_COMPARISON_ROWS:
        raise ValueError("shadow run exceeds bounded artifact comparison rows")
    payload = {
        "jobs": [{
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "run_spec_hash": str(row["run_spec_hash"]),
            "source_revision": str(row["source_revision"]),
            "runner_path": str(row["runner_path"]),
            "execution_plan_hash": str(row["execution_plan_hash"]),
            "result_hash": _text_hash(row["result_summary_json"]),
            "error_hash": _text_hash(row["error_json"]),
            "assurance_hash": _text_hash(row["terminal_assurance_json"]),
        } for row in jobs],
        "artifacts": [{
            "name": str(row["name"]),
            "state": str(row["state"]),
            "content_hash": str(row["content_hash"]),
        } for row in artifacts],
    }
    return {
        "job_ids": job_ids,
        "job_count": len(jobs),
        "artifact_count": len(artifacts),
        "fingerprint": json_hash(payload),
    }


def _text_hash(value: Any) -> str:
    if value is None:
        return ""
    return hashlib.sha256(str(value).encode()).hexdigest()
